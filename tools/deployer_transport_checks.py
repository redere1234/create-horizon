#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare stationary Deployer wheel recipes on a Depot and a bare Belt."""
import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field, items, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession


X, Y = 1955, 126
DEPOT_Z, BELT_Z, PASS_Z = 1170, 1175, 1180
LOAD = '1952 1168 1967 1183'
AREA = '1953 124 1168 1964 130 1182'
ITEMS = '@e[type=minecraft:item,x=1953,y=124,z=1168,dx=11,dy=7,dz=14]'
LANES = {
    'depot': ((X, Y, DEPOT_Z), (X, Y + 2, DEPOT_Z), (X, Y, DEPOT_Z)),
    'belt': ((X, Y, BELT_Z), (X + 2, Y + 2, BELT_Z), (X + 4, Y, BELT_Z)),
    'pass': ((X, Y, PASS_Z), (X, Y + 2, PASS_Z), (X, Y, PASS_Z)),
}
PROBES = list(dict.fromkeys(pos for positions in LANES.values() for pos in positions))
SHAFT = 'create:shaft'
COG = 'create:cogwheel'
LARGE = 'create:large_cogwheel'
PLANK = 'minecraft:oak_planks'
STICK = 'minecraft:stick'


def install(command, advance):
    command(f'fill {AREA} minecraft:air')
    command(f'kill {ITEMS}')
    command(f'fill 1953 124 1168 1964 124 1182 minecraft:stone')
    for lane, (carrier, deployer, depot) in LANES.items():
        command(f'setblock {xyz(depot)} create:depot')
        if lane == 'belt':
            for i, part in enumerate(('start', 'middle', 'middle', 'end')):
                command(f'setblock {carrier[0] + i} {Y} {BELT_Z} create:belt[facing=east,slope=horizontal,part={part}]')
            command(f'setblock {X} {Y} {BELT_Z - 1} create:creative_motor[facing=south]{{ScrollValue:-32}}')
        command(f'setblock {xyz(deployer)} create:deployer[facing=down,axis_along_first=true]'
                f'{{Mode:"USE",State:"WAITING",Timer:0,Inventory:[{{Slot:0b,id:"{PLANK}",count:2}}]}}')
    advance(2)
    for _, (dx, dy, dz), _ in LANES.values():
        command(f'setblock {dx - 1} {dy} {dz} create:creative_motor[facing=east]{{ScrollValue:64}}')
    advance(23)
    for lane, (carrier, _, _) in LANES.items():
        item = COG if lane == 'belt' else SHAFT if lane == 'depot' else STICK
        pose = 'Pos:2.35f,PrevPos:2.35f,Angle:180,InSegment:2,InDirection:5' if lane == 'belt' else 'Pos:.5f,PrevPos:.5f,Angle:180,InDirection:1'
        stack = f'{{Item:{{id:"{item}",count:2}},{pose}}}'
        if lane == 'belt':
            command(f'data merge block {xyz(carrier)} {{Inventory:{{PositiveOrder:1b,Items:[{stack}]}}}}')
        else:
            command(f'data merge block {xyz(carrier)} {{HeldItem:{stack}}}')


def tag_items(raw, key):
    return items(raw, key) if re.search(r'\b' + key + r'\s*:', raw) else {}


def snapshot(raw_rows):
    values = dict(zip(PROBES, raw_rows, strict=True))
    output = {}
    for lane, (carrier, deployer, depot) in LANES.items():
        nbt = values[deployer]
        match = re.search(r'\bState:\s*"([A-Z]+)"', nbt)
        assert match, nbt
        phase = match[1]
        output[lane] = {
            'state': phase,
            'timer': int(number({'nbt': nbt}, 'Timer', 0)) if phase != 'WAITING' else None,
            'hand': tag_items(nbt, 'HeldItem'),
            'depot': tag_items(values[depot], 'HeldItem'),
            'buffer': tag_items(values[depot], 'OutputBuffer'),
        }
        if lane == 'belt':
            output[lane]['belt'] = tag_items(values[carrier], 'Inventory')
    return output


def verify(rows):
    assert any(row['depot']['state'] == 'EXPANDING' for row in rows), rows[:12]
    assert any(row['depot']['state'] == 'RETRACTING' for row in rows), rows[:12]
    assert any(row['belt']['state'] == 'EXPANDING' for row in rows), rows[:12]
    assert all(row['pass']['hand'] == {PLANK: 2} and row['pass']['depot'] == {STICK: 2} for row in rows), rows[:12]
    final = rows[-1]
    assert not final['depot']['hand'] and final['depot']['depot'] == final['depot']['buffer'] == {COG: 1}, final
    # The end Depot holds its first result. The second stays in the belt queue
    # until that receiver accepts another stack.
    assert not final['belt']['hand'] and final['belt']['depot'] == {LARGE: 1}, final
    assert final['belt']['belt'] == {LARGE: 1}, final


def java(work):
    host = Original()
    state = host.call('state', {})
    if state.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        state = host.call('state', {})
    assert state['ready'] and state['data_version'] == 3955
    host.call('tick', {'frozen': True})

    def sample(ticks):
        return host.call('observe_ticks', {'ticks': ticks, 'positions': PROBES})['samples']

    try:
        host.command(f'forceload add {LOAD}')
        host.command(f'tp @s {X + 2}.5 {Y + 1} {BELT_Z + 2}.5')
        sample(25)
        install(host.command, sample)
        rows = [snapshot(block['nbt'] for block in row['blocks']) for row in sample(85)]
        (work / 'observed.json').write_text(json.dumps(rows, indent=2) + '\n')
        verify(rows)
        return rows
    finally:
        host.command(f'kill {ITEMS}')
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('tick', {'frozen': state['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def read_batch(batch):
    for pos in PROBES:
        batch.data(pos)


def native(session, expected):
    batch = Batch()
    batch.load((X + 2, Y + 2, BELT_Z + 2))
    install(batch.command, batch.tick)
    for _ in expected:
        batch.tick()
        read_batch(batch)
    values = iter(batch.run(session, 'same-order'))
    rows = [snapshot(next(values) for _ in PROBES) for _ in expected]
    assert next(values, None) is None
    (session.scratch / 'observed.json').write_text(json.dumps(rows, indent=2) + '\n')
    verify(rows)
    for tick, (actual, reference) in enumerate(zip(rows, expected, strict=True), 1):
        assert actual == reference, (tick, actual, reference)
    return rows


def cold(session, expected):
    # Use the same prepared resources in a separate save. The command-script
    # process exits after each Batch and the second run reads disk state.
    session.world = 'DeployerTransportCold'
    checkpoint = next(tick for tick, row in enumerate(expected, 1)
                      if row['depot']['state'] == 'EXPANDING' and row['depot']['hand'] == {PLANK: 2})
    first = Batch()
    first.load((X + 2, Y + 2, BELT_Z + 2))
    install(first.command, first.tick)
    first.tick(checkpoint)
    read_batch(first)
    before = snapshot(first.run(session, 'before-restart'))
    assert before == expected[checkpoint - 1], (before, expected[checkpoint - 1])

    second = Batch()
    second.load((X + 2, Y + 2, BELT_Z + 2))
    read_batch(second)
    second.tick(100)
    read_batch(second)
    values = second.run(session, 'after-restart')
    assert snapshot(values[:len(PROBES)]) == before
    # The original Deployer can keep making empty-hand strokes after work
    # ends. Compare settled cargo, not an arbitrary later idle stroke.
    def cargo(snapshot):
        return {lane: {key: value for key, value in row.items() if key not in ('state', 'timer')}
                for lane, row in snapshot.items()}

    assert cargo(snapshot(values[len(PROBES):])) == cargo(expected[-1])
    return checkpoint


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.game:
        if not all((args.resources, args.ctl, args.reference)):
            parser.error('Horizon needs --game, --resources, --ctl and --reference')
        source = json.loads(args.reference.read_text())
        assert source['passed'] and source['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='deployer-transport-native', graphics=False, world='DeployerTransport')
        work = session.scratch
        try:
            rows = native(session, source['rows'])
            checkpoint = cold(session, source['rows'])
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    else:
        work = Path(tempfile.mkdtemp(prefix='deployer-transport-java-', dir=ROOT / '.local'))
        rows = java(work)
        checkpoint = None
    path = work / 'result.json'
    path.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], rows=rows,
                                    checkpoint=checkpoint), indent=2) + '\n')
    print(path)
