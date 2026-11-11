#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare Belt-to-Millstone publication on the transfer tick and after a native restart."""
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
from reference_java import BASE, CREATE_SHA256


Y = 168
CENTER = (2050, Y + 2, 777)
REGION = '2048 165 768 2056 175 783'
LOAD = '2048 768 2056 783'
DROPS = '@e[type=minecraft:item,x=2048,y=165,z=768,dx=8,dy=10,dz=15]'
WHEAT = 'minecraft:wheat'
DIAMOND = 'minecraft:diamond'
LANES = {
    'accept': (770, WHEAT, 11, 0),
    'partial': (773, WHEAT, 22, 63),
    'reject': (776, DIAMOND, 33, 0),
    'full': (779, WHEAT, 44, 64),
}


def positions(z, chute=False):
    inlet = (2053, Y+1, z) if chute else (2049, Y, z)
    return inlet, (2053, Y, z)


def stack(item, count, marker):
    return f'id:"{item}",count:{count},components:{{"minecraft:custom_data":{{belt_mill_marker:{marker}}}}}'


def setup(command, chute):
    command(f'fill {REGION} minecraft:air')
    command(f'kill {DROPS}')
    # Install receivers first in the same column to control the ticker order.
    for z, *_ in LANES.values():
        _, millstone = positions(z)
        command(f'setblock {xyz(millstone)} create:millstone')
    z = LANES['accept'][0]
    command(f'setblock 2053 {Y - 1} {z} create:creative_motor[facing=up]{{ScrollValue:16}}')
    for z, _, marker, stock in LANES.values():
        belt, millstone = positions(z)
        if chute:
            command(f'setblock {millstone[0]} {Y + 1} {z} create:chute[facing=down,shape=window]')
        else:
            for index, part in enumerate(('start', 'middle', 'middle', 'end')):
                command(f'setblock {belt[0] + index} {Y} {z} '
                        f'create:belt[facing=east,slope=horizontal,part={part}]')
            command(f'setblock {belt[0]} {Y} {z - 1} create:creative_motor[facing=south]{{ScrollValue:-32}}')
        if stock:
            command(f'data merge block {xyz(millstone)} '
                    f'{{InputInventory:{{Size:1,Items:[{{Slot:0,{stack(WHEAT, stock, marker)}}}]}}}}')


def seed(command, chute, *, native=False):
    for z, item, marker, _ in LANES.values():
        belt, millstone = positions(z)
        if chute:
            item_nbt = stack(item, 3, marker)
            live = f',Items:[{{Slot:0b,{item_nbt}}}]' if native else ''
            command(f'data merge block {millstone[0]} {Y + 1} {z} '
                    f'{{Item:{{{item_nbt}}},ItemPosition:0.1f{live}}}')
            continue
        command(f'data merge block {xyz(belt)} '
                f'{{Inventory:{{PositiveOrder:1b,Items:[{{Item:{{{stack(item, 3, marker)}}},'
                'Pos:3.74f,PrevPos:3.74f,Offset:0f,PrevOffset:0f,InSegment:3,InDirection:5,Angle:180}]}}')


def first_stack(raw, key):
    if key + ':' not in raw or not (stacks := items(raw, key)):
        return None
    [(item, count)] = stacks.items()
    marker = int(number({'nbt': field(raw, key)}, 'belt_mill_marker'))
    return [item, count, marker]


def sample(values, chute):
    result = {}
    for lane, raw_inlet, raw_millstone in zip(LANES, values[::2], values[1::2], strict=True):
        inlet = 'create:chute' if chute else 'create:belt'
        assert inlet in raw_inlet and 'create:millstone' in raw_millstone, (raw_inlet, raw_millstone)
        assert not items(raw_millstone, 'OutputInventory'), raw_millstone
        result[lane] = dict(belt=first_stack(raw_inlet, 'Item' if chute else 'Inventory'),
                            millstone=first_stack(raw_millstone, 'InputInventory'),
                            timer=int(number({'nbt': raw_millstone}, 'Timer', 0)))
    return result


def verify(rows):
    transfer = {
        'accept': dict(belt=None, millstone=[WHEAT, 3, 11], timer=0),
        'partial': dict(belt=[WHEAT, 2, 22], millstone=[WHEAT, 64, 22], timer=0),
        'reject': dict(belt=[DIAMOND, 3, 33], millstone=None, timer=0),
        'full': dict(belt=[WHEAT, 3, 44], millstone=[WHEAT, 64, 44], timer=0),
    }
    assert rows['transfer'] == transfer, rows['transfer']
    # Timer 0 on the transfer tick and 150 on the next prove receiver-first order.
    assert rows['next'] == dict(transfer, accept=dict(transfer['accept'], timer=150)), rows['next']
    if 'cold' in rows:
        assert rows['cold'] == transfer, rows['cold']


def java_run(work, chute, points):
    host = Original()
    assert json.loads((BASE / 'manifest.json').read_text())['create_sha256'] == CREATE_SHA256
    state = host.call('state', {})
    assert state['ready'] and state['data_version'] == 3955, state
    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {LOAD}')
        host.call('observe_ticks', {'positions': [list(map(int, state['position']))], 'ticks': 40})
        setup(host.command, chute)
        host.call('observe_ticks', {'positions': points, 'ticks': 12})
        seed(host.command, chute)
        reply = host.call('observe_ticks', {'positions': points, 'ticks': 2})
        drops = host.command(f'execute if entity {DROPS} run say loose_belt_millstone')
        assert not any('loose_belt_millstone' in message for message in drops['messages']), drops
        return {phase: sample([b['nbt'] for b in entry['blocks']], chute)
                for phase, entry in zip(('transfer', 'next'), reply['samples'], strict=True)}
    finally:
        host.command(f'fill {REGION} minecraft:air')
        host.command(f'kill {DROPS}')
        host.command(f'forceload remove {LOAD}')
        host.call('tick', {'frozen': state['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session, chute, points):
    rows = {}
    for name, phases in [('before-restart', ('transfer',)), ('after-restart', ('cold', 'next'))]:
        batch = Batch()
        batch.load(CENTER)
        for pos in points:
            batch.command(f'execute if loaded {xyz(pos)} run say loaded_belt_millstone', True)
        if name == 'before-restart':
            setup(batch.command, chute)
            batch.tick(12)
            seed(batch.command, chute, native=True)
        for phase in phases:
            if phase != 'cold':
                batch.tick()
            for pos in points:
                batch.data(pos)
        batch.command(f'execute if entity {DROPS} run say loose_belt_millstone', True)
        values = batch.run(session, name)
        n = len(points)
        assert all('loaded_belt_millstone' in line for line in values[:n]), values[:n]
        assert 'loose_belt_millstone' not in values[-1], values[-1]
        assert len(values) == n * (1 + len(phases)) + 1, values
        for index, phase in enumerate(phases, 1):
            rows[phase] = sample(values[n * index:n * (index + 1)], chute)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--chute', action='store_true', help='Use a dry Chute instead of a Belt inlet')
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    label = 'chute-millstone' if args.chute else 'belt-millstone'
    points = [pos for z, *_ in LANES.values() for pos in positions(z, args.chute)]
    if args.java:
        work = Path(tempfile.mkdtemp(prefix=f'{label}-java-', dir=ROOT / '.local'))
        rows = java_run(work, args.chute, points)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon runs require --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None, graphics=False,
                                     name=f'{label}-native', world='CreateMillstone')
        work = session.scratch
        try:
            rows = native_run(session, args.chute, points)
        finally:
            session.control_temp.cleanup()
            for path in (session.resources, work / '.horizon-cache'):
                shutil.rmtree(path, ignore_errors=True)
        (work / 'observed.json').write_text(json.dumps(rows, indent=2) + '\n')
        assert reference['rows'] == {phase: rows[phase] for phase in reference['rows']}, rows
    verify(rows)
    path = work / 'result.json'
    path.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], rows=rows), indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
