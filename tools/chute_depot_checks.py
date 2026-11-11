#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare dry vertical Chute output into an ordinary Depot."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field, items, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession
import reference_java


X, Y = 2534, 175
LANES = dict(open=1030, held=1034, buffer=1038)
LOAD = '2528 1024 2543 1039'
REGION = '2532 172 1028 2536 177 1039'
DROPS = '@e[type=minecraft:item,x=2532,y=172,z=1028,dx=4,dy=5,dz=11]'
CHUTE = 'create:chute[facing=down,shape=normal,waterlogged=false]'
DEPOT = 'create:depot'
BOTTLE = 'minecraft:glass_bottle'
DIAMOND = 'minecraft:diamond'
PHASES = dict(warm=8, release=8)


def positions(z):
    return (X, Y, z), (X, Y - 1, z)


POINTS = [p for z in LANES.values() for p in positions(z)]


def setup(command, advance):
    command(f'fill {REGION} minecraft:air')
    command(f'kill {DROPS}')
    for z in LANES.values():
        chute, depot = map(xyz, positions(z))
        command(f'setblock {depot} {DEPOT}')
        command(f'setblock {chute} {CHUTE}')
    advance(4)
    _, depot = map(xyz, positions(LANES['held']))
    command(f'data merge block {depot} {{HeldItem:{{Item:{{id:"{DIAMOND}",count:1}},'
            'Pos:0.5f,PrevPos:0.5f,Offset:0f,PrevOffset:0f,Angle:180,InDirection:1,InSegment:0}}')
    _, depot = map(xyz, positions(LANES['buffer']))
    command(f'data merge block {depot} '
            f'{{OutputBuffer:{{Size:8,Items:[{{Slot:0,id:"{DIAMOND}",count:1}}]}}}}')
    for marker, z in enumerate(LANES.values(), 1):
        chute, _ = map(xyz, positions(z))
        command(f'data merge block {chute} '
                f'{{ItemPosition:1f,Item:{{id:"{BOTTLE}",count:12,'
                f'components:{{"minecraft:custom_data":{{chute_depot_marker:{marker}}}}}}}}}')


def release(command):
    _, depot = map(xyz, positions(LANES['held']))
    command(f'data remove block {depot} HeldItem')
    _, depot = map(xyz, positions(LANES['buffer']))
    command(f'data merge block {depot} {{OutputBuffer:{{Size:8,Items:[]}}}}')


def snapshot(values):
    result = {}
    for lane, chute, depot in zip(LANES, values[::2], values[1::2], strict=True):
        assert 'create:chute' in chute and DEPOT in depot, (chute, depot)
        held = None
        if 'HeldItem:' in depot:
            raw = field(depot, 'HeldItem')
            held = dict(item=items(raw, 'Item'), marker=number({'nbt': raw}, 'chute_depot_marker', 0))
            held.update({key: number({'nbt': raw}, key) for key in
                         ('Pos', 'PrevPos', 'InDirection', 'InSegment', 'Offset', 'PrevOffset', 'Angle')})
        result[lane] = dict(source=items(chute, 'Item'), position=number({'nbt': chute}, 'ItemPosition'),
                            marker=number({'nbt': chute}, 'chute_depot_marker', 0), held=held,
                            buffer=items(depot, 'OutputBuffer'))
    return result


def java_run(work):
    host = Original()
    manifest = json.loads((reference_java.BASE / 'manifest.json').read_text())
    state = host.call('state', {})
    assert state['ready'] and state['data_version'] == 3955
    assert manifest['create_sha256'] == reference_java.CREATE_SHA256
    host.call('tick', {'frozen': True})

    def advance(ticks):
        return host.call('observe_ticks', {'positions': POINTS, 'ticks': ticks})['samples']

    try:
        host.command(f'forceload add {LOAD}')
        host.call('observe_ticks', {'positions': [list(map(int, state['position']))], 'ticks': 40})
        setup(host.command, advance)
        phases = {}
        for name, ticks in PHASES.items():
            if name == 'release':
                release(host.command)
            phases[name] = [snapshot([block['nbt'] for block in row['blocks']]) for row in advance(ticks)]
            drops = host.command(f'execute if entity {DROPS} run say loose_chute_depot')
            assert not any('loose_chute_depot' in line for line in drops['messages']), drops
        return phases
    finally:
        host.command(f'fill {REGION} minecraft:air')
        host.command(f'kill {DROPS}')
        host.command(f'forceload remove {LOAD}')
        host.call('tick', {'frozen': state['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    batch = Batch()
    batch.load((X, Y + 4, 1034))
    setup(batch.command, batch.tick)
    for name, ticks in PHASES.items():
        if name == 'release':
            release(batch.command)
        for _ in range(ticks):
            batch.tick()
            for pos in POINTS:
                batch.data(pos)
        batch.command(f'execute if entity {DROPS} run say loose_chute_depot', True)
    values = batch.run(session, 'chute-depot')
    phases = {}
    start = 0
    for name, ticks in PHASES.items():
        end = start + len(POINTS) * ticks
        phases[name] = [snapshot(values[i:i + len(POINTS)]) for i in range(start, end, len(POINTS))]
        assert 'loose_chute_depot' not in values[end], values[end]
        start = end + 1
    assert start == len(values)
    return phases


def verify(phases):
    warm, released = phases['warm'], phases['release']
    assert warm[-1]['held']['held']['item'] == {DIAMOND: 1}, warm
    assert warm[-1]['buffer']['held'] is None and warm[-1]['buffer']['buffer'] == {DIAMOND: 1}, warm
    for row in warm[2:]:
        for marker, lane in enumerate(('held', 'buffer'), 2):
            assert (row[lane]['source'], row[lane]['position'], row[lane]['marker']) == ({BOTTLE: 12}, .5, marker)
    for marker, lane in enumerate(LANES, 1):
        rows = warm if lane == 'open' else released
        first = 5 if lane == 'open' else 2
        assert all(row[lane]['source'] == {BOTTLE: 12} for row in rows[:first]), rows
        incoming = [row[lane] for row in rows[first:]]
        for received in incoming:
            assert not received['source'] and not received['buffer'], received
            record = received['held']
            assert record and record['item'] == {BOTTLE: 12} and record['marker'] == marker, received
            assert record['Angle'] == 180 and record['InDirection'] == 1, record
            assert record['InSegment'] == record['Offset'] == record['PrevOffset'] == 0, record
        assert [row['held']['Pos'] for row in incoming[:3]] == [0, 0.125, 0.21875], incoming
        assert [row['held']['PrevPos'] for row in incoming[:3]] == [0, 0, 0.125], incoming


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='chute-depot-java-', dir=ROOT / '.local'))
        phases = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon runs require --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None, graphics=False,
                                     name='chute-depot-native', world='CreateChuteDepot')
        work = session.scratch
        try:
            phases = native_run(session)
        finally:
            session.control_temp.cleanup()
            for path in (session.resources, work / '.horizon-cache'):
                shutil.rmtree(path, ignore_errors=True)
    (work / 'observed.json').write_text(json.dumps(phases, indent=2) + '\n')
    verify(phases)
    if not args.java:
        for name, expected in reference['phases'].items():
            for tick, (got, wanted) in enumerate(zip(phases[name], expected, strict=True), 1):
                assert got == wanted, (name, tick, got, wanted)
    path = work / 'result.json'
    path.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], phases=phases), indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
