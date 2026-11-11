#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare chassis capture and translated Gantry landing with Create 6.0.10."""

import argparse
import json
from pathlib import Path
import tempfile

from actor_native_checks import matched
from bearing_native_checks import Batch
from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from chassis_native_checks import block_state, expect_restored, expected_range
from chassis_reference_checks import LINEAR, RADIAL, SECONDARY, STONE, chassis
from common import PINS, ROOT
from native_check_session import NativeCheckSession


AIR = 'minecraft:air'
CARRIAGE = 'create:gantry_carriage[facing=up,axis_along_first=false]'
CHASSIS = (LINEAR, SECONDARY, RADIAL)
LEFT, RIGHT, RAIL_Y = 1364, 1366, 170


def rig(put, z, source, rpm, payload, controls):
    for x in range(LEFT, RIGHT + 1):
        put((x, RAIL_Y, z), 'create:gantry_shaft[facing=east]')
    put((source, RAIL_Y + 1, z), CARRIAGE)
    for pos, state in (payload | controls).items():
        put(pos, state)

    def power():
        put((LEFT - 1, RAIL_Y, z), f'create:creative_motor[facing=east]{{ScrollValue:{rpm}}}')

    return power


def translate(blocks, distance):
    return {(x + distance, y, z): state for (x, y, z), state in blocks.items()}


def scenes():
    y = RAIL_Y + 2
    return {
        'linear_east': (114, LEFT, -128, RIGHT, {
            (LEFT, y, 114): chassis(LINEAR, 'x', 2, 'sticky_bottom'),
            (LEFT - 1, y, 114): 'minecraft:oak_log[axis=z]',
            (LEFT - 2, y, 114): STONE,
            (LEFT, y, 115): f'{LINEAR}[axis=x,sticky_bottom=true]',
            (LEFT - 1, y, 115): 'minecraft:oak_planks',
        }, {
            (LEFT - 3, y, 114): 'minecraft:gold_block',
            (LEFT, y, 113): f'{SECONDARY}[axis=x]',
        }),
        'radial_west': (119, RIGHT, 128, LEFT, {
            (RIGHT, y, 119): chassis(RADIAL, 'x', 2, 'sticky_east'),
            (RIGHT, y, 120): 'minecraft:oak_log[axis=y]',
            (RIGHT, y, 121): STONE,
        }, {
            (RIGHT, y, 122): 'minecraft:gold_block',
        }),
        'unglued_forward': (124, LEFT, -128, LEFT, {
            (LEFT, y, 124): f'{LINEAR}[axis=x]',
        }, {
            (LEFT + 1, y, 124): STONE,
        }),
    }


def phases(z, source, destination, payload, controls):
    start = {(source, RAIL_Y + 1, z): CARRIAGE} | payload
    target = translate(start, destination - source)
    cells = dict.fromkeys(start | target | controls, AIR)
    before = cells | start | controls
    moving = cells | controls if source != destination else before
    landed = cells | target | controls
    return (before, moving, landed)


def observed_java(host, expected, ticks):
    blocks = host.call('observe_ticks', {
        'ticks': ticks, 'positions': list(expected),
    })['samples'][-1]['blocks']
    assert len(expected) == len(blocks), blocks
    for (pos, state), block in zip(expected.items(), blocks):
        identifier, _, props = block_state(state).partition('[')
        assert block['id'] == identifier, (pos, state, block)
        if props:
            for assignment in props[:-1].split(','):
                key, value = assignment.split('=')
                assert block['properties'][key].lower() == value, (pos, state, block)
        if identifier in CHASSIS:
            assert number(block, 'ScrollValue') == expected_range(state), (pos, state, block)
    return blocks


def java_reference():
    host = Original()
    work = Path(tempfile.mkdtemp(prefix='gantry-chassis-reference-', dir=ROOT / '.local'))
    loaded = False
    try:
        assert host.call('state', {})['data_version'] == 3955
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        host.command(f'tp @s {RIGHT}.5 {RAIL_Y + 8} 119.5')
        host.command(f'forceload add {LEFT - 4} 112 {RIGHT + 3} 127')
        loaded = True
        host.call('observe_ticks', {'ticks': 30, 'positions': [(LEFT, RAIL_Y, 119)]})
        host.command(f'fill {LEFT - 4} {RAIL_Y - 1} 112 {RIGHT + 3} {RAIL_Y + 4} 127 {AIR}')
        cases = {}
        for name, (z, source, rpm, destination, payload, controls) in scenes().items():
            power = rig(lambda p, s: host.command(f'setblock {xyz(p)} {s}'),
                        z, source, rpm, payload, controls)
            before, moving, landed = phases(z, source, destination, payload, controls)
            rows = [observed_java(host, before, 1)]
            power()
            rows.append(observed_java(host, moving, 4))
            rows.append(observed_java(host, landed, 10))
            cases[name] = rows
        path = work / 'result.json'
        path.write_text(json.dumps(dict(create=PINS['create_revision'], cases=cases), indent=2) + '\n')
        return path
    finally:
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
        if loaded:
            host.command(f'forceload remove {LEFT - 4} 112 {RIGHT + 3} 127')


def verify(batch, session, label):
    rows = batch.run(session, label)
    errors = [(i, row) for i, row in enumerate(rows) if not matched(row)]
    assert rows and not errors, (label, errors)
    return len(rows)


def native_geometry(session):
    batch = Batch()
    batch.load((RIGHT, RAIL_Y + 7, 119))
    batch.command(f'fill {LEFT - 4} {RAIL_Y - 1} 112 {RIGHT + 3} {RAIL_Y + 4} 127 {AIR}')
    for z, source, rpm, destination, payload, controls in scenes().values():
        power = rig(batch.put, z, source, rpm, payload, controls)
        before, moving, landed = phases(z, source, destination, payload, controls)
        batch.tick()
        expect_restored(batch, before)
        power()
        batch.tick(4)
        expect_restored(batch, moving)
        batch.tick(10)
        expect_restored(batch, landed)
    return verify(batch, session, 'gantry-chassis-geometry')


def native_reload(session):
    z, y = 133, RAIL_Y + 2
    root = (LEFT, y, z)
    cargo = {root: chassis(SECONDARY, 'z', 3, 'sticky_top'),
             (LEFT, y, z + 1): 'minecraft:oak_log[axis=x]'}
    control = {(LEFT, y, z - 1): STONE}
    source = {(LEFT, y - 1, z): CARRIAGE} | cargo
    target = translate(source, 1)
    end = translate(source, 2)
    landing = (LEFT + 1, y - 1, z)
    switch = (LEFT + 1, RAIL_Y, z + 1)
    cells = dict.fromkeys(source | target | end, AIR)

    batch = Batch()
    batch.load((RIGHT, RAIL_Y + 7, z))
    batch.command(f'fill {LEFT - 4} {RAIL_Y - 1} 129 {RIGHT + 3} {RAIL_Y + 4} 139 {AIR}')
    power = rig(batch.put, z, LEFT, -128, cargo, control)
    batch.tick()
    power()
    batch.tick(7)
    expect_restored(batch, cells | control)
    moving = verify(batch, session, 'gantry-chassis-moving-save')

    batch = Batch()
    batch.load((RIGHT, RAIL_Y + 7, z))
    batch.put(landing, 'minecraft:obsidian')
    batch.put(switch, 'minecraft:redstone_block')
    batch.tick(3)
    expect_restored(batch, cells | control | {landing: 'minecraft:obsidian'})
    blocked = verify(batch, session, 'gantry-chassis-parked-save')

    batch = Batch()
    batch.load((RIGHT, RAIL_Y + 7, z))
    batch.put(landing, AIR)
    batch.tick(3)
    expect_restored(batch, cells | target | control)
    recovered = verify(batch, session, 'gantry-chassis-restored')

    batch = Batch()
    batch.load((RIGHT, RAIL_Y + 7, z))
    batch.put(switch, AIR)
    batch.tick(14)
    expect_restored(batch, cells | end | control)
    recaptured = verify(batch, session, 'gantry-chassis-resumed')
    return dict(moving=moving, blocked=blocked, recovered=recovered, recaptured=recaptured)


def native_refusals(session):
    y = RAIL_Y + 2
    cases = {
        147: {(LEFT, y, 147): chassis(LINEAR, 'x', 5, 'sticky_bottom')} | {
            (LEFT - d, y, 147): STONE for d in range(1, 6)
        },
        151: {(LEFT, y, 151): chassis(LINEAR, 'y', 16, 'sticky_top'),
              (LEFT, y + 16, 151): f'{SECONDARY}[axis=z]'} | {
            (LEFT, y + d, 151): STONE for d in range(1, 16)
        },
        155: {(LEFT, y, 155): f'{LINEAR}[axis=x]{{ScrollValue:2,Foreign:1}}'},
    }
    batch = Batch()
    batch.load((RIGHT, RAIL_Y + 7, 151))
    batch.command(f'fill {LEFT - 6} {RAIL_Y - 1} 145 {RIGHT + 3} {y + 17} 157 {AIR}')
    for z, cargo in cases.items():
        power = rig(batch.put, z, LEFT, -128, cargo, {})
        batch.tick()
        power()
        batch.tick(14)
        batch.expect((LEFT, y - 1, z), CARRIAGE)
        batch.expect((RIGHT, y - 1, z), AIR)
        # The unsupported entity uses a separate exact NBT check below.
        if z != 155:
            expect_restored(batch, cargo)
    batch.expect((LEFT, y, 155), f'{LINEAR}[axis=x]')
    batch.command(f'execute if data block {LEFT} {y} 155 {{ScrollValue:2,Foreign:1}} '
                  'run say bearing_check', True)
    return verify(batch, session, 'gantry-chassis-refused-capture')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        print(java_reference())
        return
    if not all((args.game, args.resources, args.ctl)):
        parser.error('Specify --java or all of --game, --resources and --ctl')
    session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                 name='gantry-chassis-native', graphics=False,
                                 world='CreateGantryChassisChecks')
    path = session.scratch / 'result.json'
    report = dict(geometry=native_geometry(session), reload=native_reload(session),
                  refusals=native_refusals(session))
    path.write_text(json.dumps(report, indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
