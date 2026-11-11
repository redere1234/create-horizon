#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Check harvested wheat and tree logs reach the stationary output chest."""

import argparse
import json
from pathlib import Path
import tempfile

from actor_native_checks import matched
from bearing_native_checks import Batch
from burner_heat_java_checks import items
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession


X, Y, Z = 1400, 146, 151
PIVOT = (X, Y, Z)
MOTOR = (X, Y - 1, Z)
DOCK = (X, Y + 2, Z - 4)
HOPPER = (X, Y + 1, Z - 4)
OUTPUT = (X, Y, Z - 4)
CARGO = (X - 1, Y + 1, Z)
WORK = (X + 3, Y + 1, Z - 1)
SECOND = (X + 3, Y + 2, Z - 1)
CONTROL = (X + 1, Y + 1, Z - 3)
AIR = 'minecraft:air'
CHEST = 'minecraft:chest[facing=north,type=single,waterlogged=false]'
INTERFACE = 'create:portable_storage_interface'
POWER = 'create:creative_motor[facing=up]{ScrollValue:32}'
CLEAR = f'fill {X - 5} {Y - 2} {Z - 6} {X + 5} {Y + 5} {Z + 5} {AIR}'


def setup(put, command, tree):
    command(CLEAR)
    put(PIVOT, 'create:mechanical_bearing[facing=up]')
    for x in range(X, X + 3):
        put((x, Y + 1, Z), 'minecraft:slime_block')
    put((X + 2, Y + 2, Z), f'{INTERFACE}[facing=east]')
    actor = 'mechanical_saw[facing=north,axis_along_first=false,flipped=false]' if tree else 'mechanical_harvester[facing=north]'
    put((X + 3, Y + 1, Z), 'create:' + actor)
    put(CARGO, CHEST)
    put(DOCK, f'{INTERFACE}[facing=south]')
    put(HOPPER, 'minecraft:hopper[facing=down]')
    put(OUTPUT, CHEST)
    if tree:
        put(WORK, 'minecraft:oak_log[axis=y]')
        put(SECOND, 'minecraft:oak_log[axis=y]')
        put(CONTROL, 'minecraft:birch_log[axis=y]')
    else:
        for pos, age in [(WORK, 7), (CONTROL, 3)]:
            x, y, z = pos
            put((x, y - 1, z), 'minecraft:farmland[moisture=7]')
            put(pos, f'minecraft:wheat[age={age}]')


def checks(tree):
    if tree:
        return {WORK: 'minecraft:oak_log[axis=y]', SECOND: 'minecraft:oak_log[axis=y]',
                CONTROL: AIR}, 'minecraft:birch_log', 1
    return {WORK: 'minecraft:wheat[age=0]', CONTROL: 'minecraft:wheat[age=3]'}, 'minecraft:wheat', 1


def java():
    host = Original()
    work = Path(tempfile.mkdtemp(prefix='portable-farm-java-', dir=ROOT / '.local'))
    report = dict(passed=False, create=PINS['create_revision'], cases={})
    def put(pos, state):
        host.command(f'setblock {xyz(pos)} {state}')
    try:
        assert host.call('state', {})['data_version'] == 3955
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        host.command(f'tp @s {X}.5 {Y + 7} {Z}.5')
        host.command('forceload add 1392 144 1407 159')
        host.call('observe_ticks', {'ticks': 25, 'positions': [PIVOT]})
        host.command('gamerule randomTickSpeed 0')
        for label, tree in [('wheat', False), ('logs', True)]:
            host.command(f'kill @e[type=create:stationary_contraption,x={X},y={Y},z={Z},distance=..12]')
            setup(put, host.command, tree)
            expected, item, count = checks(tree)
            put(MOTOR, POWER)
            rows = host.call('observe_ticks', {'ticks': 135, 'positions': [*expected, OUTPUT]})['samples']
            landed = rows[-1]['blocks']
            got = items(landed[-1]['nbt'], 'Items')
            assert got.get(item) == count, (label, got, landed)
            for block, state in zip(landed[:-1], expected.values(), strict=True):
                name, _, props = state.partition('[')
                assert block['id'] == name, block
                if props:
                    prop, val = props.rstrip(']').split('=')
                    assert block['properties'][prop].lower() == val, block
            report['cases'][label] = dict(output=got, blocks=landed)
        report['passed'] = True
    finally:
        host.command('forceload remove 1392 144 1407 159')
        host.call('tick', {'frozen': False})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
        path = work / 'result.json'
        path.write_text(json.dumps(report, indent=2) + '\n')
        print(path)


def native(session):
    report = {}
    for label, tree in [('wheat', False), ('logs', True)]:
        batch = Batch()
        batch.load(PIVOT)
        batch.command('gamerule minecraft:random_tick_speed 0')
        setup(batch.put, batch.command, tree)
        batch.tick(3)
        batch.put(MOTOR, POWER)
        batch.tick(135)
        expected, item, count = checks(tree)
        batch.data(OUTPUT)
        for pos, state in expected.items():
            batch.expect(pos, state)
        output, *rows = batch.run(session, 'portable-farm-' + label)
        got = items(output, 'Items')
        assert got.get(item) == count and all(map(matched, rows)), (label, got, rows, output)
        report[label] = dict(output=got, blocks=len(rows))
        # Leave no running attachment to be picked up by the next fresh rig.
        clean = Batch()
        clean.load(PIVOT)
        clean.put(MOTOR, AIR)
        clean.tick(4)
        clean.run(session, 'stop-portable-farm-' + label)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for key in ('game', 'resources', 'ctl'):
        parser.add_argument('--' + key, type=Path)
    args = parser.parse_args()
    if args.java:
        java()
        return
    if not all((args.game, args.resources, args.ctl)):
        parser.error('Specify --java or all of --game, --resources and --ctl')
    session = NativeCheckSession(args.game, args.resources, args.ctl, None, name='portable-farm-native',
                                 graphics=False, world='PortableFarm')
    path = session.scratch / 'result.json'
    try:
        path.write_text(json.dumps(native(session), indent=2) + '\n')
    finally:
        session.control_temp.cleanup()
        print(path)


if __name__ == '__main__':
    main()
