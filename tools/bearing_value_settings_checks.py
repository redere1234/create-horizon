#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare contraption settings boards and live mode changes in Java and Horizon."""
import argparse
import errno
import json
from pathlib import Path
import shutil
import tempfile

from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded

MECHANICAL = (998, 101, 152)
WINDMILL = (1000, 101, 152)
CLOCKWORK = (1005, 101, 152)
SHAFT = (1000, 100, 152)
CASES = (
    (MECHANICAL, 'mechanical_bearing', 'Movement Mode', (
        'Always Place when Stopped', 'Only Place near Initial Angle',
        'Only Place when Anchor Destroyed',
    )),
    (WINDMILL, 'windmill_bearing', 'Rotation Direction', ('Clockwise', 'Counter-Clockwise')),
    (CLOCKWORK, 'clockwork_bearing', 'Clock Hand Arrangement', (
        'Hour hand first', 'Minute hand first', '24-Hour hand first',
    )),
)
PISTON = (1003, 101, 152)
STICKY_PISTON = (998, 101, 152)
PULLEY = (1009, 101, 152)
PISTON_MOTOR = (PISTON[0], PISTON[1] - 1, PISTON[2])
ACTUATOR_CHOICES = (
    'Always Place when Stopped', 'Place only in Starting Position',
    'Place only when Anchor Destroyed',
)
ACTUATORS = tuple((pos, block, 'Movement Mode', ACTUATOR_CHOICES) for pos, block in (
    (PISTON, 'mechanical_piston'), (STICKY_PISTON, 'sticky_mechanical_piston'),
    (PULLEY, 'rope_pulley'),
))


def place(command, actuators):
    command('fill 995 100 147 1010 106 159 minecraft:air')
    command('fill 995 99 147 1010 99 159 minecraft:smooth_stone')
    command('clear @s')
    if actuators:
        for pos, block, _, _ in ACTUATORS:
            props = '[axis=x]' if pos == PULLEY else '[facing=east,axis_along_first=true]'
            command(f'setblock {xyz(pos)} create:{block}{props}')
            x, y, z = pos
            command(f'setblock {x} {y+1} {z+1} minecraft:smooth_stone')
        x, y, z = PISTON
        for rod_x in range(x - 3, x):
            command(f'setblock {rod_x} {y} {z} create:piston_extension_pole[facing=east]')
        command(f'setblock {xyz(landing(0))} minecraft:oak_planks')
        return
    for pos, block, _, _ in CASES:
        command(f'setblock {xyz(pos)} create:{block}[facing=up]')
    command(f'setblock {xyz(SHAFT)} create:shaft[axis=y]')
    for z in range(152, 160):
        command(f'setblock 1000 102 {z} minecraft:slime_block')
        command(f'setblock 1000 103 {z} minecraft:white_wool')


def pose(pos, height=.375, actuators=False, valid=True):
    x, y, z = pos
    if actuators:
        top = (pos == PULLEY) == valid
        x += 0.5 if pos == PULLEY else 0.375
        if top:
            return [x, y + 2, z + 1.5], [x, y + 31 / 32, z + .5], 'up'
    else:
        x += .5
    return [x, y - 1, z + 3.5], [x, y + height, z + 31 / 32], 'south'


def landing(offset):
    x, y, z = PISTON
    return x + 1 + offset, y, z


def java_run(work, actuators, queued):
    host = Original()
    call = host.call
    command = host.command
    count = 0

    def frame(frames=20):
        nonlocal count
        count += 1
        return call('capture', {'name': f'{work.name}/frame-{count}.png', 'frames': frames})

    def value(pos, field='ScrollValue'):
        return number(call('block', {'pos': pos}), field, 0)

    def aim(pos, height=.375, valid=True):
        position, target, face = pose(pos, height, actuators, valid)
        call('camera', {'position': position, 'target': target, 'hide_gui': False})
        frame()
        hit = call('state', {})['hit']
        assert hit['pos'] == list(pos), hit
        if height == .375:
            assert hit['face'] == face, hit

    def reject(pos):
        aim(pos, valid=False)
        call('input', {'key': 'use', 'down': True})
        frame(25)
        assert 'value_settings' not in call('ui', {}), pos
        call('input', {'key': 'use', 'down': False})
        frame(10)

    def choose(pos, wanted, current, label, title, maximum):
        aim(pos)
        call('input', {'key': 'use', 'down': True})
        frame(40)
        ui = call('ui', {})
        assert 'value_settings' in ui, ui
        board = ui['value_settings']
        assert board['title']['text'] == title and board['max_value'] == maximum, board
        assert board['milestone_interval'] == 1 and board['rows'][0]['text'] == 'Select', board
        assert board['initial']['value'] == current and value(pos) == current, board
        x, y = board['initial']['gui_coordinate']
        point = dict(x=x + (wanted - current) * 10, y=y)
        call('input', dict(kind='move', **point))
        frame(10)
        hovered = call('ui', {})['value_settings']['hovered']
        assert hovered['formatted']['text'] == label and hovered['value'] == wanted, hovered
        call('input', dict(kind='mouse', button=1, down=False, **point))
        call('input', {'key': 'use', 'down': False})
        frame()
        assert value(pos) == wanted, (pos, wanted, value(pos))
        return hovered['formatted']['text']

    command('gamemode creative')
    call('tick', {'frozen': False})
    command('forceload add 992 144 1023 159')
    call('camera', {'position': [1000.5, 100, 155.5], 'target': [1000.5, 101.5, 152.5]})
    frame(25)
    place(command, actuators)
    report = {}
    for pos, block, title, labels in ACTUATORS if actuators else CASES:
        if actuators:
            reject(pos)
        current = 0
        choices = {}
        for wanted in range(1, len(labels)):
            choices[wanted] = choose(pos, wanted, current, labels[wanted], title, len(labels) - 1)
            current = wanted
        choices[0] = choose(pos, 0, current, labels[0], title, len(labels) - 1)
        report[block] = dict(title=title, choices=[choices[i] for i in range(len(labels))])

    if actuators:
        _, _, title, labels = ACTUATORS[0]
        choose(PISTON, 2, 0, labels[2], title, 2)
        if queued:
            offset = stop_midstroke(command, value, lambda: frame(10))
            aim(PISTON, valid=False)
            call('input', {'key': 'use'})
            frame(20)
            assert value(PISTON, 'Offset') == offset
        else:
            power_piston(command)
            frame(55)
            offset = 3
        assert value(PISTON, 'Running') == value(PISTON, 'Waiting') == 1
        assert value(PISTON, 'Offset') == offset
        choose(PISTON, 0, 2, labels[0], title, 2)
        frame(20)
        assert value(PISTON, 'Running') == 0
        assert call('block', {'pos': landing(offset)})['id'] == 'minecraft:oak_planks'
        report['running_after_mode_change'] = [1, 0]
        if queued:
            report['queued_stop_offset'] = offset
    else:
        aim(WINDMILL, .85)
        call('input', {'key': 'use'})
        frame(30)
        assert value(WINDMILL, 'Running') == value(WINDMILL, 'LastGenerated') == value(SHAFT, 'Speed') == 1
        choose(WINDMILL, 1, 0, 'Counter-Clockwise', 'Rotation Direction', 1)
        assert value(WINDMILL, 'Running') == 1
        assert value(WINDMILL, 'LastGenerated') == value(SHAFT, 'Speed') == -1
        report['live_generation'] = [1, -1]
    call('tick', {'frozen': True})
    (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
    return report


def power_piston(command, rpm=128):
    command(f'setblock {xyz(PISTON_MOTOR)} create:creative_motor[facing=up]{{ScrollValue:{-rpm}}}')


def stop_midstroke(command, value, wait):
    power_piston(command, 16)
    for _ in range(60):
        wait()
        if value(PISTON, 'Offset') >= 1:
            break
    assert 1 <= value(PISTON, 'Offset') < 2
    command(f'setblock {xyz(PISTON_MOTOR)} minecraft:air')
    wait()
    offset = value(PISTON, 'Offset')
    assert offset == 1 and value(PISTON, 'Running') == 1
    return int(offset)


def native_run(session, expected, actuators, queued):
    call = session.call
    cases = ACTUATORS if actuators else CASES
    points = [pos for pos, _, _, _ in cases]

    def command(text):
        return call('command', text)['chat']

    def value(pos, field='ScrollValue'):
        nbt = ' '.join(command('data get block ' + xyz(pos)))
        return number({'nbt': nbt}, field, 0)

    def aim(pos, height=.375, valid=True):
        position, target, face = pose(pos, height, actuators, valid)
        command('tp @s ' + xyz(position))
        call('look-at', *target)
        call('wait', 3)
        hit = call('looking-at')['block']
        assert hit['pos'] == list(pos), hit
        if height == .375:
            assert hit['face'] == face, hit

    def reject(pos):
        aim(pos, valid=False)
        call('mouse', 'right', 'down')
        call('wait', 9)
        assert call('screen')['screen'] == 'playing', pos
        call('release')

    def trace():
        prefix = 'Create actuator board: ' if actuators else 'Create bearing board: '
        return [json.loads(line.split(prefix, 1)[1]) for line in session.log.read_text().splitlines()
                if prefix in line][-1]

    def open_board(pos, title, current, labels):
        aim(pos)
        call('mouse', 'right', 'down')
        call('wait', 9)
        assert call('screen')['screen'] == 'mod', (pos, call('screen'))
        layout = trace()
        assert layout['pos'] == list(pos) and layout['title'] == title, layout
        assert layout['row'] == 0 and layout['size'] == [7 + len(labels) * 10, 11], layout
        assert layout['cursor'] == labels[current] and layout['value'] == current, layout
        return layout

    def choose(pos, wanted, current, title, labels):
        layout = open_board(pos, title, current, labels)
        x, y = layout['coordinate']
        point = (x + (wanted - current) * 10, y)
        call('click-at', *point)
        call('wait', 2)
        assert call('screen')['screen'] == 'mod'
        assert value(pos) == current
        assert trace()['cursor'] == labels[wanted] and trace()['value'] == wanted, trace()
        call('screenshot', session.scratch / f'settings-{pos[0]}-{wanted}.png')
        call('click-at', *point, 'right')
        call('release')
        call('wait', 8)
        assert call('screen')['screen'] == 'playing'
        assert value(pos) == wanted, (pos, wanted, value(pos))

    with session:
        command('gamemode creative')
        command('tp @s 1000.5 100 155.5')
        wait_loaded(call, points)
        place(command, actuators)
        for pos, block, title, labels in cases:
            assert expected[block] == {'title': title, 'choices': list(labels)}, expected[block]
            if actuators:
                reject(pos)
            current = 0
            for wanted in range(1, len(labels)):
                choose(pos, wanted, current, title, labels)
                current = wanted
            if pos == WINDMILL:
                choose(pos, 0, current, title, labels)

        if actuators:
            if queued:
                offset = stop_midstroke(command, value, lambda: call('wait', 4))
                assert offset == expected['queued_stop_offset']
                aim(PISTON, valid=False)
                call('mouse', 'right', 'click')
                call('wait', 8)
                assert value(PISTON, 'AssembleNextTick') == 1
            else:
                power_piston(command)
                call('wait', 30)
                offset = 3
            assert value(PISTON, 'Running') == expected['running_after_mode_change'][0]
            assert value(PISTON, 'Offset') == offset
            _, _, title, labels = ACTUATORS[0]
            choose(PISTON, 0, 2, title, labels)
            assert value(PISTON, 'Running') == expected['running_after_mode_change'][1]
            assert 'settings_landing' in ' '.join(command(
                f'execute if block {xyz(landing(offset))} minecraft:oak_planks run say settings_landing'))
            selections = [0, 2, 2]
            result = dict(running_after_mode_change=expected['running_after_mode_change'])
            if queued:
                result['queued_stop_offset'] = offset
        else:
            aim(WINDMILL, .85)
            call('mouse', 'right', 'click')
            call('wait', 12)
            assert value(WINDMILL, 'Running') == 1
            assert value(WINDMILL, 'LastGenerated') == value(SHAFT, 'Speed') == expected['live_generation'][0]
            _, _, title, labels = CASES[1]
            choose(WINDMILL, 1, 0, title, labels)
            assert value(WINDMILL, 'Running') == 1
            assert value(WINDMILL, 'LastGenerated') == value(SHAFT, 'Speed') == expected['live_generation'][1]
            selections = [2, 1, 2]
            result = dict(live_generation=expected['live_generation'])
        call('save')
        session.restart()
        wait_loaded(call, points)
        assert [value(pos) for pos in points] == selections
        for pos, _, title, labels in cases:
            open_board(pos, title, int(value(pos)), labels)
            call('key', 'escape', 'tap')
            call('release')
            call('wait', 8)
        if not actuators:
            assert value(WINDMILL, 'LastGenerated') == expected['live_generation'][1]
    return dict(selections_after_restart=selections, **result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--actuators', action='store_true')
    parser.add_argument('--queued', action='store_true', help='test a queued click at a mid-stroke stop')
    for name in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.queued and not args.actuators:
        parser.error('--queued requires --actuators')
    kind = 'actuator' if args.actuators else 'bearing'
    if args.java:
        work = Path(tempfile.mkdtemp(prefix=f'{kind}-settings-java-', dir=ROOT / '.local'))
        result = java_run(work, args.actuators, args.queued)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl and --reference')
        source = json.loads(args.reference.read_text())
        assert source['passed'] and source['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name=f'{kind}-settings-native', world='MotionSettings')
        session.env.pop('CREATE_HORIZON_TRACE_POSES', None)
        session.env.pop('CREATE_HORIZON_PARTICLE_TRACE', None)
        work = session.scratch
        print(work, flush=True)
        try:
            result = native_run(session, source['cases'], args.actuators, args.queued)
        finally:
            for copy in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                if copy.is_dir():
                    try:
                        shutil.rmtree(copy)
                    except OSError as error:
                        if error.errno != errno.ENOTEMPTY:
                            raise
                        # Finder can add .DS_Store after rmtree scans a directory.
                        shutil.rmtree(copy)
    path = work / 'result.json'
    path.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], cases=result), indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
