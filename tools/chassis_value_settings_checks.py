#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Exercise the Chassis Wrench value board in a private real native client."""
import argparse
import json
from pathlib import Path

from burner_heat_java_checks import number
from chain_drive_checks import xyz
from native_check_session import NativeCheckSession, wait_loaded
from value_settings_checks import run as motor_checks


LINEAR = (1040, 101, 119)
NEIGHBOR = (1041, 101, 119)
SECONDARY = (1039, 101, 119)
RADIAL = (1044, 101, 119)
AXIS_CONTROL = (1040, 101, 118)
MOTOR = (1047, 101, 119)


def run(session, report):
    call = session.call

    def cmd(line):
        return call('command', line)['chat']

    def value(pos):
        nbt = ' '.join(cmd('data get block ' + xyz(pos)))
        return int(number({'nbt': nbt}, 'ScrollValue'))

    def aim(pos):
        cmd(f'tp @s {pos[0] + .5} 100 122.5')
        call('wait', 4)
        call('look-at', 'block', *pos, 'south')
        call('wait', 3)
        hit = call('looking-at')['block']
        assert hit['pos'] == list(pos) and hit['face'] == 'south', hit

    def trace():
        prefix = 'Create chassis board: '
        return [json.loads(line.split(prefix, 1)[1]) for line in session.log.read_text().splitlines()
                if prefix in line][-1]

    def board(pos, expected, current):
        aim(pos)
        call('mouse', 'right', 'down')
        call('wait', 9)
        assert call('screen')['screen'] == 'mod', call('screen')
        layout = trace()
        assert layout['title'] == expected and layout['size'] == [163, 11], layout
        assert layout['row'] == 0 and layout['pos'] == list(pos), layout
        assert layout['cursor'] == str(current) and layout['value'] == current - 1, layout
        return layout

    def choose(layout, raw, *, bulk=False, image=None):
        left, top = layout['origin']
        x = left + max(raw - 1, 0) * 4 + raw * 2 + 42 + 18 + 1.5 + 2 + (4 if raw else 0)
        point = (x, top + 5.)
        # Only the bound use control releases the screen.
        call('click-at', *point)
        call('wait', 2)
        assert call('screen')['screen'] == 'mod'
        hovered = trace()
        assert hovered['value'] == raw and hovered['cursor'] == str(raw + 1), hovered
        if image:
            call('screenshot', session.scratch / image)
        if bulk:
            call('key', 'ctrl', 'down')
        try:
            call('click-at', *point, 'right')
        finally:
            if bulk:
                call('key', 'ctrl', 'up')
        call('release')
        call('wait', 7)
        assert call('screen')['screen'] == 'playing'
        return hovered

    def assert_values(expected):
        assert (actual := [value(pos) for pos in (LINEAR, NEIGHBOR, SECONDARY, RADIAL, AXIS_CONTROL)]) == expected, actual

    with session:
        cmd('gamemode creative')
        cmd('tp @s 1040.5 100 122.5')
        wait_loaded(call, [LINEAR, RADIAL, MOTOR])
        cmd('fill 1036 100 117 1048 104 123 minecraft:air')
        cmd('fill 1036 99 117 1048 99 123 minecraft:smooth_stone')
        for pos, state in [(LINEAR, 'linear_chassis[axis=y]'), (NEIGHBOR, 'linear_chassis[axis=y]'),
                           (SECONDARY, 'secondary_linear_chassis[axis=y]'), (RADIAL, 'radial_chassis[axis=y]'),
                           (AXIS_CONTROL, 'linear_chassis[axis=x]'), (MOTOR, 'creative_motor[facing=up]')]:
            cmd(f'setblock {xyz(pos)} create:{state}')
        cmd('clear @s')
        assert_values([8, 8, 8, 8, 8])
        aim(LINEAR)
        call('mouse', 'right', 'down')
        call('wait', 9)
        assert call('screen')['screen'] == 'playing'
        call('release')
        cmd('item replace entity @s weapon.mainhand with create:wrench')
        call('wait', 6)
        aim(LINEAR)
        call('mouse', 'right', 'click')
        call('wait', 8)
        assert call('screen')['screen'] == 'playing'
        assert 'axis=y' in call('block', *LINEAR)['state']
        call('screenshot', session.scratch / 'linear-wrench-hover.png')
        title = 'Range of Sticky Sides'
        report['range'] = choose(board(LINEAR, title, 8), 15, image='linear-range.png')
        assert_values([16, 8, 8, 8, 8])
        report['group'] = choose(board(LINEAR, title, 16), 4, bulk=True)
        assert_values([5, 5, 8, 8, 8])
        # The source compares the adjusted value to its previous zero-based
        # value for a single edit, so decreasing by one alone is a no-op.
        choose(board(LINEAR, title, 5), 3)
        assert_values([5, 5, 8, 8, 8])
        pending = board(LINEAR, title, 5)
        cmd('clear @s')
        call('wait', 6)
        choose(pending, 12)
        assert_values([5, 5, 8, 8, 8])
        cmd('item replace entity @s weapon.mainhand with create:wrench')
        call('wait', 6)
        report['radius'] = choose(board(RADIAL, 'Radius when Sticky', 8), 0, image='radial-radius.png')
        assert_values([5, 5, 8, 1, 8])
        report['secondary'] = board(SECONDARY, title, 8)
        call('key', 'escape', 'tap')
        call('release')
        call('wait', 8)
        call('save')
        session.restart()
        wait_loaded(call, [LINEAR, RADIAL, MOTOR])
        assert_values([5, 5, 8, 1, 8])
        cmd('item replace entity @s weapon.mainhand with create:wrench')
        call('wait', 6)
        report['reopened_after_restart'] = board(LINEAR, title, 5)
        call('key', 'escape', 'tap')
        call('release')
        call('wait', 8)
        aim(MOTOR)
        report['motor'] = motor_checks(call, session.graphics, session.log, session.scratch, MOTOR)
        report['persisted'] = [5, 5, 8, 1, 8]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'resources', 'ctl'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--create-jar', type=Path)
    args = parser.parse_args()
    session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                 name='chassis-value-settings', world='ChassisValueSettings')
    (session.scratch / 'options.txt').write_text('lang:en_us\ntutorialStep:none\nchatVisibility:2\n')
    print(session.scratch, flush=True)
    report = dict(passed=False, original_assets=args.create_jar is not None)
    try:
        run(session, report)
        report['passed'] = True
    finally:
        (session.scratch / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        session.control_temp.cleanup()
        print(json.dumps(dict(result=str(session.scratch / 'result.json'), passed=report['passed'])))


if __name__ == '__main__':
    main()
