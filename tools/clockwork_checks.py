#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare the Clockwork Bearing's independent hour and minute arms in both games."""
import argparse
import json
from pathlib import Path
import tempfile

from burner_heat_java_checks import number
from bearing_native_checks import Batch
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded
import reference_java as java

PIVOT = (970, 100, 55)
DRIVE = (969, 100, 55)
HOUR = (971, 100, 55)
MINUTE = (972, 100, 55)
POINTS = [PIVOT, HOUR, MINUTE]
TARGETS = [(0, -30, -90), (1, -90, -30), (2, 165, -90)]


def java_reference():
    manifest = json.loads((java.BASE / 'manifest.json').read_text())
    assert manifest['create_sha256'] == java.CREATE_SHA256 and manifest['data_version'] == 3955
    host = Original()
    state = host.call('state', {})
    assert state['ready'] and state['data_version'] == 3955, state
    work = Path(tempfile.mkdtemp(prefix='clockwork-reference-', dir=ROOT / '.local'))
    result = dict(passed=False, create=PINS['create_revision'], cases=[])

    def put(pos, block):
        host.command(f'setblock {xyz(pos)} {block}')

    def ticks(count):
        return host.call('observe_ticks', {'ticks': count, 'positions': POINTS})['samples']

    def click(name):
        name = f'{work.name}/{name}.png'
        host.call('capture', {'name': name, 'frames': 16})
        hit = host.call('state', {})['hit']
        assert tuple(hit['pos']) == PIVOT and hit['face'] == 'west', hit
        host.call('input', {'key': 'use'})
        host.call('capture', {'name': name, 'frames': 12})
        host.call('input', {'key': 'use', 'down': False})

    try:
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        host.command('clear @s')
        host.command('tp @s 967.2 99 55.84')
        host.command('forceload add 960 48 991 79')
        ticks(24)
        host.command('fill 966 96 52 976 108 58 minecraft:air')
        host.command('fill 966 98 52 968 98 58 minecraft:smooth_stone')
        host.command('gamerule doDaylightCycle false')
        host.command('time set 7250')
        host.call('camera', {'position': [967.2, 99, 55.84], 'target': [970.5, 100.78, 55.84]})
        for mode, hour_target, minute_target in TARGETS:
            put(DRIVE, 'minecraft:air')
            put(PIVOT, 'minecraft:air')
            put(PIVOT, f'create:clockwork_bearing[facing=east]{{ScrollValue:{mode}}}')
            put(HOUR, 'minecraft:oak_log[axis=y]')
            put(MINUTE, 'minecraft:oak_log[axis=z]')
            row = dict(mode=mode)
            result['cases'].append(row)

            row['idle'] = ticks(5)
            assert number(row['idle'][-1]['blocks'][0], 'Running') == 0, row
            assert number(row['idle'][-1]['blocks'][0], 'ScrollValue') == mode, row
            click(f'{mode}-assemble')
            row['manual'] = ticks(5)
            resting = row['manual'][-1]['blocks']
            assert number(resting[0], 'Running') == 1, resting
            assert number(resting[0], 'HourAngle') == number(resting[0], 'MinuteAngle') == 0, resting
            assert [b['id'] for b in resting[1:]] == ['minecraft:air', 'minecraft:air'], resting

            put(DRIVE, 'create:creative_motor[facing=east]{ScrollValue:32}')
            row['rotating'] = ticks(40)
            settled = row['rotating'][-1]['blocks'][0]
            assert number(settled, 'Speed') == 32, settled
            assert number(settled, 'HourAngle') == hour_target, settled
            assert number(settled, 'MinuteAngle') == minute_target, settled
            put(DRIVE, 'minecraft:air')
            row['restored'] = ticks(5)
            restored = row['restored'][-1]['blocks']
            assert number(restored[0], 'Running') == 0, restored
            assert [b['id'] for b in restored[1:]] == ['minecraft:oak_log'] * 2, restored
            assert [b['properties']['axis'] for b in restored[1:]] == ['y', 'z'], restored
        result['passed'] = True
    finally:
        (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
    print(json.dumps(dict(result=str(work / 'result.json'), cases=len(result['cases']))))


def pose(block):
    return number(block, 'HourAngle'), number(block, 'MinuteAngle')


def native_persistence(session):
    def rotor(batch):
        batch.put(DRIVE, 'minecraft:air')
        batch.put(PIVOT, 'minecraft:air')
        batch.put(PIVOT, 'create:clockwork_bearing[facing=east]')
        batch.put(HOUR, 'minecraft:oak_log[axis=y]')
        batch.put(MINUTE, 'minecraft:oak_log[axis=z]')
        batch.put(DRIVE, 'create:creative_motor[facing=east]{ScrollValue:32}')
        batch.tick(16)

    def verify_running(batch, minute='minecraft:air'):
        batch.data(PIVOT)
        batch.expect(HOUR, 'minecraft:air')
        batch.expect(MINUTE, minute)

    def verify_restored(batch, controller='create:clockwork_bearing'):
        batch.expect(PIVOT, controller)
        batch.expect(HOUR, 'minecraft:oak_log[axis=y]')
        batch.expect(MINUTE, 'minecraft:oak_log[axis=z]')

    batch = Batch()
    batch.load((967, 100, 55))
    rotor(batch)
    verify_running(batch)
    initial = batch.run(session, 'clockwork-save-active')
    assert number({'nbt': initial[0]}, 'Running') == 1 and pose({'nbt': initial[0]}) == (-30, -90)
    assert all('bearing_check' in line for line in initial[1:]), initial

    batch = Batch()
    batch.load((967, 100, 55))
    verify_running(batch)
    batch.put(MINUTE, 'minecraft:stone')
    batch.put(DRIVE, 'minecraft:air')
    batch.tick(4)
    verify_running(batch, 'minecraft:stone')
    batch.put(MINUTE, 'minecraft:air')
    batch.tick(4)
    batch.data(PIVOT)
    verify_restored(batch)
    rotor(batch)
    batch.put(PIVOT, 'minecraft:air')
    batch.tick(4)
    verify_restored(batch, 'minecraft:air')

    reloaded = batch.run(session, 'clockwork-resume-and-recover')
    for index in (0, 3):
        state = {'nbt': reloaded[index]}
        assert number(state, 'Running') == 1 and pose(state) == (-30, -90), reloaded
    assert number({'nbt': reloaded[6]}, 'Running') == 0, reloaded
    assert pose({'nbt': reloaded[6]}) == (0, 0), reloaded
    assert all('bearing_check' in line for i, line in enumerate(reloaded) if i not in (0, 3, 6)), reloaded
    return dict(before_restart=initial, after_restart=reloaded)


def native_manual_click(session):
    # A fresh unpowered bearing and two disconnected logs occupy their cells
    # until the actual right-click operation reaches the server.
    batch = Batch()
    batch.load((967, 100, 55))
    batch.command('fill 966 98 52 968 98 58 minecraft:smooth_stone')
    batch.put(PIVOT, 'create:clockwork_bearing[facing=east]')
    batch.put(HOUR, 'minecraft:oak_log[axis=y]')
    batch.put(MINUTE, 'minecraft:oak_log[axis=z]')
    batch.put(DRIVE, 'minecraft:air')
    batch.run(session, 'clockwork-manual-input-setup')
    with session:
        call = session.call
        wait_loaded(call, POINTS)
        call('command', 'tp @s 967.2 99 55.84')
        call('command', 'clear @s')
        call('wait', 8)
        call('look-at', 'block', *PIVOT, 'west')

        def click_to(expected):
            call('mouse', 'right', 'click')
            for _ in range(16):
                data = ' '.join(call('command', 'data get block ' + xyz(PIVOT))['chat'])
                if number({'nbt': data}, 'Running', 0) == expected:
                    return data
                call('wait', 5)
            raise AssertionError((expected, data))

        def expect_blocks(hour, minute):
            for pos, expected in [(HOUR, hour), (MINUTE, minute)]:
                command = f'execute if block {xyz(pos)} {expected} run say clockwork_check'
                assert any('clockwork_check' in line for line in call('command', command)['chat'])
            call('wait', 5)
            for pos, expected in [(HOUR, hour), (MINUTE, minute)]:
                assert call('block', *pos)['block'] == expected.split('[')[0], (pos, expected)

        assert call('block', *HOUR)['block'] == 'minecraft:oak_log'
        assembled = click_to(1)
        expect_blocks('minecraft:air', 'minecraft:air')
        restored = click_to(0)
        expect_blocks('minecraft:oak_log[axis=y]', 'minecraft:oak_log[axis=z]')
    return dict(assembled=assembled, restored=restored)


def native_comparison(args):
    reference = json.loads(args.reference.read_text())
    assert reference['passed'] and reference['create'] == PINS['create_revision'], reference
    session = NativeCheckSession(
        args.game, args.resources, args.ctl, args.create_jar,
        name='clockwork-native', graphics=False, world='CreateClockworkTest',
    )
    report = dict(passed=False, reference=str(args.reference), cases=[])
    print(session.scratch, flush=True)
    batch = Batch()
    batch.load((967, 100, 55))
    batch.command('fill 966 96 52 976 108 58 minecraft:air')
    batch.command('gamerule minecraft:advance_time false')
    batch.command('time set 7250')
    for mode, _, _ in TARGETS:
        batch.put(DRIVE, 'minecraft:air')
        batch.put(PIVOT, 'minecraft:air')
        batch.put(PIVOT, f'create:clockwork_bearing[facing=east]{{ScrollValue:{mode},'
                         '"create_horizon:ClockworkAssembly":1b}')
        batch.put(HOUR, 'minecraft:oak_log[axis=y]')
        batch.put(MINUTE, 'minecraft:oak_log[axis=z]')
        batch.tick(5)
        batch.data(PIVOT)
        batch.expect(HOUR, 'minecraft:air')
        batch.expect(MINUTE, 'minecraft:air')

        batch.put(DRIVE, 'create:creative_motor[facing=east]{ScrollValue:32}')
        for _ in range(40):
            batch.tick()
            batch.data(PIVOT)
        batch.put(DRIVE, 'minecraft:air')
        batch.tick(5)
        batch.data(PIVOT)
        batch.expect(HOUR, 'minecraft:oak_log[axis=y]')
        batch.expect(MINUTE, 'minecraft:oak_log[axis=z]')

    try:
        replies = iter(batch.run(session, 'clockwork-traces'))
        for original in reference['cases']:
            manual = {'nbt': next(replies)}
            air = [next(replies), next(replies)]
            turning = [{'nbt': next(replies)} for _ in range(40)]
            restored = {'nbt': next(replies)}
            logs = [next(replies), next(replies)]
            case = dict(mode=original['mode'], manual=manual, turning=turning, restored=restored,
                        air=air, logs=logs)
            report['cases'].append(case)
            assert number(manual, 'Running') == 1 and pose(manual) == (0, 0), case
            assert all('bearing_check' in line for line in air), case
            java_turning = [sample['blocks'][0] for sample in original['rotating']]
            java_motion = [pose(block) for block in java_turning if number(block, 'Speed') == 32]
            native_motion = [pose(block) for block in turning if number(block, 'Speed') == 32]
            assert native_motion == java_motion and len(native_motion) == 40, (
                case['mode'], native_motion, java_motion,
            )
            assert pose(turning[-1]) == pose(java_turning[-1]), case
            assert number(restored, 'Running') == 0 and pose(restored) == (0, 0), case
            assert all('bearing_check' in line for line in logs), case
        assert next(replies, None) is None
        report['persistence'] = native_persistence(session)
        report['manual_input'] = native_manual_click(session)
        report['passed'] = True
    finally:
        output = session.scratch / 'result.json'
        output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(result=str(output), cases=len(report['cases']))))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('reference', 'game', 'resources', 'ctl', 'create-jar'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.reference:
        if not all((args.game, args.resources, args.ctl)):
            parser.error('Native comparison requires --game, --resources and --ctl')
        native_comparison(args)
    else:
        java_reference()
