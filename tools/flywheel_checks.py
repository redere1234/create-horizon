#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare Flywheel placement, wrench rotation and shaft connections in both games."""
import argparse
import json
from pathlib import Path
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded

PLACED = (1142, 101, 1173)
SUPPORT = (1142, 100, 1173)
PLAYER = (1142.5, 101, 1174.5)


def placement(command, axis, click, held):
    command('fill 1140 101 1171 1144 106 1176 minecraft:air')
    command('fill 1140 100 1171 1144 100 1176 minecraft:smooth_stone')
    command('setblock 1143 101 1173 create:shaft[axis=x]')
    command('tp @s ' + xyz(PLAYER))
    held('create:flywheel')
    click(SUPPORT)
    preferred = axis()
    held('create:wrench')
    click(PLACED)
    rotated = axis()
    command('setblock 1142 101 1173 minecraft:air')
    command('setblock 1142 101 1172 create:shaft[axis=z]')
    held('create:flywheel')
    click(SUPPORT)
    return {'preferred': preferred, 'wrenched': rotated, 'conflicting': axis()}


def java_placement(host):
    def click(pos):
        x, y, z = pos
        host.call('camera', {'position': PLAYER, 'target': (x + 0.5, y + 0.5, z + 0.5)})
        host.call('capture', {'name': 'flywheel-placement-aim.png', 'frames': 12})
        hit = host.call('state', {})['hit']
        assert hit['pos'] == list(pos) and hit['face'] == 'up', hit
        host.call('input', {'key': 'use'})
        try:
            host.call('capture', {'name': 'flywheel-placement-use.png', 'frames': 16})
        finally:
            host.call('input', {'key': 'use', 'down': False})

    def axis():
        block = host.call('block', {'pos': PLACED})
        assert block['id'] == 'create:flywheel', block
        return block['properties']['axis'].lower()

    return placement(host.command, axis, click, lambda item: host.command(
        f'item replace entity @s weapon.mainhand with {item}'))


def native_placement(session):
    def command(command):
        return session.call('command', command)

    def click(pos):
        session.call('look-at', 'block', *pos, 'up')
        session.call('wait', 3)
        session.call('interact', *pos, 'up')
        session.call('wait', 6)

    def axis():
        block = session.call('block', *PLACED)
        assert block['block'] == 'create:flywheel', block
        return block['state'].split('axis=', 1)[1].rstrip(']')

    try:
        session.start()
        command('tp @s ' + xyz(PLAYER))
        wait_loaded(session.call, [PLACED])
        return placement(command, axis, click, lambda item: command(
            f'item replace entity @s weapon.mainhand with {item}'))
    finally:
        session.stop()


def rig(axis, put):
    wheel = (1136 + 6 * axis, 100, 1168)
    motor = tuple(value - (i == axis) for i, value in enumerate(wheel))
    shaft = tuple(value + (i == axis) for i, value in enumerate(wheel))
    face = ('east', 'up', 'south')[axis]
    axis_name = 'xyz'[axis]
    state = 'create:flywheel' if axis == 1 else f'create:flywheel[axis={axis_name}]'
    put(wheel, state)
    put(shaft, f'create:shaft[axis={axis_name}]')
    put(motor, f'create:creative_motor[facing={face}]{{ScrollValue:32}}')
    return wheel, motor, shaft


def java():
    host = Original()
    work = Path(tempfile.mkdtemp(prefix='flywheel-java-', dir=ROOT / '.local'))
    before = host.call('state', {})
    if before.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        before = host.call('state', {})
    assert before['ready'] and before['data_version'] == 3955, before

    def put(pos, block):
        host.command(f'setblock {xyz(pos)} {block}')

    cases = []
    host.call('tick', {'frozen': True})
    try:
        host.command('gamemode creative')
        host.command('tp @s 1142.5 102 1168.5')
        host.command('forceload add 1120 1152 1167 1183')
        host.snapshot([(1142, 100, 1168)], 40)
        host.command('fill 1133 97 1165 1152 105 1171 minecraft:air')
        for axis in range(3):
            wheel, motor, shaft = rig(axis, put)
            powered = host.snapshot([wheel, shaft], 8)
            assert powered[0]['block'] == 'create:flywheel', powered
            assert powered[0]['properties'] == {'axis': 'xyz'[axis]}, powered
            assert 'create:flywheel' in powered[0]['nbt'], powered
            assert [block['speed'] for block in powered] == [32, 32], powered
            put(motor, 'minecraft:air')
            stopped = host.snapshot([wheel, shaft], 4)
            assert [block['speed'] for block in stopped] == [0, 0], stopped
            cases.append(dict(axis='xyz'[axis], powered=powered, stopped=stopped))
        host.call('tick', {'frozen': False})
        installed = java_placement(host)
        assert installed == {'preferred': 'x', 'wrenched': 'z', 'conflicting': 'y'}, installed
    finally:
        host.command('forceload remove 1120 1152 1167 1183')
        host.call('tick', {'frozen': before['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
    result = dict(passed=True, create=PINS['create_revision'], cases=cases, placement=installed)
    (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(result=str(work / 'result.json'))))


def speeds(rows):
    return [number({'nbt': row}, 'Speed', 0) for row in rows]


def native(session, reference):
    batch = Batch()
    batch.load((1142, 100, 1168))
    batch.command('fill 1133 97 1165 1152 105 1171 minecraft:air')
    rigs = [rig(axis, batch.put) for axis in range(3)]
    batch.tick(8)
    for axis, (wheel, _, shaft) in enumerate(rigs):
        batch.expect(wheel, f'create:flywheel[axis={"xyz"[axis]}]')
        batch.data(wheel)
        batch.data(shaft)
    rows = batch.run(session, 'flywheels-powered')
    for i, case in enumerate(reference['cases']):
        state, *nbt = rows[i * 3:(i + 1) * 3]
        assert 'bearing_check' in state and 'create:flywheel' in nbt[0], rows
        assert speeds(nbt) == [block['speed'] for block in case['powered']], rows

    batch = Batch()
    batch.load((1142, 100, 1168))
    batch.tick(8)
    for wheel, _, shaft in rigs:
        batch.data(wheel)
        batch.data(shaft)
    for _, motor, _ in rigs:
        batch.put(motor, 'minecraft:air')
    batch.tick(4)
    for wheel, _, shaft in rigs:
        batch.data(wheel)
        batch.data(shaft)
    rows = batch.run(session, 'flywheels-restarted')
    expected = [
        block['speed']
        for phase in ('powered', 'stopped')
        for case in reference['cases']
        for block in case[phase]
    ]
    assert speeds(rows) == expected, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        java()
        return
    if not all((args.game, args.resources, args.ctl, args.reference)):
        parser.error('--game, --resources, --ctl and --reference are required for Horizon')
    reference = json.loads(args.reference.read_text())
    assert reference['passed'] and reference['create'] == PINS['create_revision']
    session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                 name='flywheel-native', graphics=False, world='CreateFlywheelChecks')
    try:
        native(session, reference)
        installed = native_placement(session)
        assert installed == reference['placement'], (installed, reference['placement'])
    finally:
        session.control_temp.cleanup()
    result = dict(passed=True, world=str(session.scratch), placement=installed)
    (session.scratch / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
