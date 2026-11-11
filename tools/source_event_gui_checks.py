#!/usr/bin/env python3
"""Actual frozen motor GUI and settled ordinary-wrench checks in a fresh world.

Normal input and vanilla commands only; no machine-method calls, /data power
edits, production modifications, clock offsets, or full-frame parity claims.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re

from native_check_session import NativeCheckSession, wait_loaded

MOTOR = (618, 66, 30)
PRESS = (620, 66, 30)
FIELDS = ['Speed', 'NeedsUpdate', 'Running', 'Ticks', 'Mode', 'Finished']


def fields(text):
    result = {}
    for name in FIELDS:
        found = re.search(r'\b' + name + r':\s*(-?[\d.]+)', text)
        if found:
            result[name] = float(found[1])
    return result


def run(call, scratch, log, reference, *, wrench_only=False):
    scratch = Path(scratch)
    original = json.loads(Path(reference).read_text())
    source = next(row for row in original['cases'] if row['name'] == 'ordinary_gui_zero_to_32')
    result = {'passed': False, 'source_receipt': str(Path(reference).resolve()), 'checks': [], 'images': []}

    def save():
        (scratch / 'source-event-result.json').write_text(json.dumps(result, indent=2) + '\n')

    def cmd(text):
        return call('command', text)

    def snapshot(pos=PRESS):
        raw = ' '.join(cmd('data get block ' + ' '.join(map(str, pos)))['chat'])
        return {'raw': raw, 'fields': fields(raw), 'block': call('block', *pos)}

    def clock():
        reply = cmd('time query gametime')
        numbers = re.findall(r'\b\d+\b', ' '.join(reply['chat']))
        assert len(numbers) == 1, reply
        return int(numbers[0])

    def image(name):
        path = scratch / name
        call('screenshot', path)
        result['images'].append(str(path))

    save()
    try:
        cmd('gamemode spectator')
        cmd('tick unfreeze')
        cmd('forceload add 608 16 639 47')
        cmd('tp @s 620.5 72 34.5')
        call('wait-ready', 120)
        wait_loaded(call, [(616, 63, 28), (625, 72, 36)])
        cmd('fill 616 64 28 625 72 36 minecraft:air')
        cmd('fill 617 63 28 624 63 36 minecraft:smooth_stone')
        motor_rpm = 32 if wrench_only else 0
        for pos, block in [(MOTOR, 'create:creative_motor[facing=east]{ScrollValue:' + str(motor_rpm) + '}'),
                           ((619, 66, 30), 'create:shaft[axis=x]'),
                           ((620, 64, 30), 'create:basin[facing=down]'),
                           (PRESS, 'create:mechanical_press[facing=east]')]:
            cmd('setblock ' + ' '.join(map(str, pos)) + ' ' + block)
        call('wait', 30)
        cmd('gamemode survival')
        cmd('tp @s 618.5 64 33.5')
        call('wait', 8)
        assert call('state')['player']['on_ground']
        cmd('gamemode creative')
        cmd('clear @s')
        if not wrench_only:
            cmd('data merge block 620 64 30 {InputItems:{Size:9,Items:[{Slot:0,id:"minecraft:snowball",count:8}]},OutputItems:{Size:9,Items:[]}}')
            cmd('tick freeze')
            call('wait', 3)
            before_time = clock()
            result['before'] = snapshot()
            assert result['before']['fields']['Speed'] == 0, result['before']
            call('look-at', 'block', *MOTOR, 'south')
            call('wait', 3)
            call('mouse', 'right', 'down')
            call('wait', 9)
            assert call('screen')['screen'] == 'mod'
            boards = [json.loads(line.split('Create motor board: ', 1)[1])
                      for line in Path(log).read_text().splitlines() if 'Create motor board: ' in line]
            assert boards, 'No actual rendered motor board trace'
            layout = boards[-1]
            left, top = layout['origin']
            label = layout['size'][0] - 318
            point = (left + 32 + 1.5 + label + 18 + 2 + 4, top + 1.5 * 11 - .5)
            result['board'] = {'layout': layout, 'choice': point, 'row': 1, 'rpm': 32}
            image('frozen-motor-board.png')
            call('click-at', *point, 'right')
            call('release')
            call('wait', 5)
            after_time = clock()
            after = snapshot()
            result['after_callback'] = after
            result['frozen_clock'] = [before_time, after_time]
            assert before_time == after_time, result['frozen_clock']
            wanted = fields(next(block for block in source['after_callback']['blocks']
                                 if block['id'] == 'create:mechanical_press')['nbt'])
            for key in ['Speed', 'NeedsUpdate', 'Running', 'Ticks']:
                assert after['fields'][key] == wanted[key], (key, after, wanted)
            image('frozen-motor-applied.png')
            result['checks'].append('Actual frozen GUI publishes 32 RPM/NeedsUpdate before simulation; source callback fields match')
            cmd('tick step 1')
            call('wait', 8)
            stepped = snapshot()
            stepped_time = clock()
            result['frozen_step'] = stepped
            result['step_clock'] = [after_time, stepped_time]
            assert stepped_time == after_time + 1, result['step_clock']
            # Source KineticBlockEntity.getSpeed returns zero while the tick-rate
            # manager is frozen, including a debug-stepped tick. The reference's
            # samples[] observer unfreezes the server, so its first ordinary tick
            # is intentionally not a comparison for this boundary.
            frozen_expected = {'Speed': 32, 'Running': 0, 'Ticks': 0, 'Mode': 0}
            result['frozen_step_contract'] = {
                'source_revision': 'ac0c444d9828da3453ae8cc65338e8de063286fb',
                'source': 'KineticBlockEntity.java#getSpeed',
                'scope': 'Source-extracted freeze contract; no paired Java debug-step capture',
                'expected': frozen_expected,
                'ordinary_source_samples_compared': False,
            }
            for key, wanted in frozen_expected.items():
                assert stepped['fields'][key] == wanted, (key, stepped, frozen_expected)
            result['checks'].append('One frozen debug step retains stored 32 RPM without starting the Press')
            save()
        cmd('tick unfreeze')
        cmd('setblock 617 66 30 create:shaft[axis=x]')
        cmd('fill 617 67 32 620 67 34 minecraft:smooth_stone')
        cmd('gamemode survival')
        cmd('tp @s 618.5 68 32.5')
        call('wait', 8)
        assert call('state')['player']['on_ground']
        cmd('gamemode creative')
        cmd('item replace entity @s weapon.mainhand with create:wrench 1')
        call('select', 'create:wrench')
        call('release')
        call('wait', 3)
        result['wrench_inventory'] = call('inventory')
        result['wrench_selected_item'] = cmd('data get entity @s SelectedItem')
        rotations = []
        for before_facing, expected in [('east', 'south'), ('south', 'west')]:
            # The center Up-face hit is inside the source value box. Its
            # input handler consumes that click even with a Wrench. Aim at a
            # real top-face corner instead; ctl interact would re-aim centrally.
            call('look-at', MOTOR[0] + .75, MOTOR[1] + .8125, MOTOR[2] + .75)
            call('wait', 3)
            state = call('state')
            result.setdefault('wrench_pre_click', []).append(state)
            save()
            assert state['screen'] == 'playing', state
            assert not state['player']['sneaking'], state
            assert 'create:wrench' in json.dumps(state['held']), state
            assert state['looking_at']['kind'] == 'block', state
            hit = state['looking_at']['block']
            assert hit['pos'] == list(MOTOR) and hit['face'] == 'up', hit
            facing = {'east': (1, 0, 0), 'south': (0, 0, 1)}[before_facing]
            center = [value + .5 - direction / 16
                      for value, direction in zip(MOTOR, facing)]
            center[1] += 4.5 / 16
            distance = math.dist(hit['point'], center)
            result.setdefault('wrench_value_box_distances', []).append(distance)
            assert distance > .25, (hit, center, distance)
            save()
            image('wrench-before-' + expected + '.png')
            call('mouse', 'right', 'down')
            call('wait', 1)
            call('mouse', 'right', 'up')
            call('wait', 12)
            motor = snapshot(MOTOR)
            assert 'facing=' + expected in motor['block']['state'], motor
            rotations.append(motor)
        west = snapshot((617, 66, 30))
        assert rotations[-1]['fields']['Speed'] == west['fields']['Speed'] == -32, (rotations, west)
        result['wrench'] = {'rotations': rotations, 'west_shaft': west,
                            'scope': 'Settled sign only; no instantaneous detach claim'}
        image('wrench-west-negative32.png')
        result['checks'].append('Two ordinary Up-face Wrench actions: east→south→west; motor/output−32 after own turns')
        result['passed'] = True
    except BaseException as error:
        result['error'] = repr(error)
        raise
    finally:
        save()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['game', 'resources', 'ctl', 'create-jar', 'build-receipt', 'reference']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--wrench-only', action='store_true',
                        help='Check an initialized 32-RPM motor without repeating the GUI phase')
    args = parser.parse_args()
    receipt = json.loads(args.build_receipt.read_text())
    assert receipt['passed'] and Path(receipt['game']).resolve() == args.game.resolve()
    assert hashlib.sha256(args.game.read_bytes()).hexdigest() == receipt['game_sha256']
    session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                 name='source-event-gui', graphics=True, world='CreateSourceEvents07')
    session.env.update(HORIZON_API_DISCOVERY='http://127.0.0.1:9/', HORIZON_NO_DISCORD='1')
    (session.scratch / 'options.txt').write_text('tutorialStep:none\nchatVisibility:2\nlang:en_us\n')
    report = {'passed': False, 'game_sha256': receipt['game_sha256'], 'scratch': str(session.scratch)}
    print(session.scratch, flush=True)
    try:
        with session:
            report['result'] = run(session.call, session.scratch, session.log, args.reference,
                                   wrench_only=args.wrench_only)
        report['passed'] = True
    finally:
        (session.scratch / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        print(session.scratch / 'result.json', flush=True)


if __name__ == '__main__':
    main()
