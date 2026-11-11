#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Observe the camera on a horizontal rotor and rider contact on a rising blade."""

import argparse
import json
import math
from pathlib import Path
import shutil
import tempfile
import time

from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from contraption_frame_checks import MARKER
from native_check_session import NativeCheckSession, wait_loaded

HORIZONTAL = (1509, 100, 280)
VERTICAL = (1509, 100, 296)
FEET = (1510.5, 101.0, 298.5)
MOTOR = 'setblock 1508 100 296 create:creative_motor[facing=east]{ScrollValue:-8}'
VERTICAL_SPACE = '1506 99 291 1514 107 302'
VERTICAL_LOAD = '1504 288 1519 303'


def setup_vertical(command):
    command(f'fill {VERTICAL_SPACE} minecraft:air')
    command('fill 1506 99 291 1514 99 302 minecraft:stone')
    command('setblock 1509 100 296 create:mechanical_bearing[facing=east]')
    command('fill 1510 100 295 1510 100 297 minecraft:slime_block')
    command('setblock 1510 100 298 minecraft:oak_planks')
    command('gamemode survival')


def observe_vertical(read, pause):
    trace = []
    for _ in range(230):
        row = read()
        if not trace or row['angle'] != trace[-1]['angle']:
            trace.append(row)
        if abs(row['angle']) >= 125.0:
            return trace
        pause()
    raise AssertionError(('No complete sweep', trace))


def java_vertical(work):
    host = Original()
    state = host.call('state', {})
    if state['screen'] == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        state = host.call('state', {})
    assert state['ready'] and state['data_version'] == 3955, state

    def read():
        bearing = host.call('block', {'pos': VERTICAL})
        return dict(angle=number(bearing, 'Angle', 0), position=host.call('state', {})['position'])

    try:
        host.call('tick', {'frozen': True})
        host.command('forceload add ' + VERTICAL_LOAD)
        host.command('tp @s 1509.5 105 296.5')
        host.snapshot([VERTICAL], 24)
        setup_vertical(host.command)
        host.call('camera', {'position': FEET, 'target': [1510.5, 101.0, 296.5]})
        host.snapshot([VERTICAL], 8)
        before = host.call('state', {})['position']
        host.command('tick rate 8')
        host.command(MOTOR)
        host.call('tick', {'frozen': False})
        return before, observe_vertical(read, lambda: time.sleep(.045))
    finally:
        host.call('tick', {'frozen': True})
        host.command('tick rate 20')
        host.command(f'fill {VERTICAL_SPACE} minecraft:air')
        host.command('forceload remove ' + VERTICAL_LOAD)
        host.call('camera', {'position': state['position'], 'yaw': state['yaw'], 'pitch': state['pitch']})
        host.call('tick', {'frozen': state['server']['frozen']})
        (work / 'java-transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_vertical(call):
    def command(text):
        return call('command', text)['chat']

    def read():
        block = {'nbt': ' '.join(command('data get block ' + xyz(VERTICAL)))}
        return dict(angle=number(block, 'Angle', 0), position=call('state')['player']['position'])

    command('tp @s 1509.5 105 296.5')
    wait_loaded(call, [VERTICAL])
    setup_vertical(command)
    command('tp @s ' + xyz(FEET))
    call('wait', 10)
    player = call('state')['player']
    assert player['on_ground'], player
    command('tick freeze')
    command('tick rate 8')
    command(MOTOR)
    command('tick unfreeze')
    trace = observe_vertical(read, lambda: call('wait', 1))
    command('tick rate 20')
    return player['position'], trace


def native_horizontal(call):
    def command(text):
        return call('command', text)

    command('gamemode creative')
    command('tp @s 1510.9 105 280.5')
    wait_loaded(call, [HORIZONTAL])
    command('fill 1504 99 275 1514 107 285 minecraft:air')
    command('fill 1504 99 275 1514 99 285 minecraft:stone')
    command('setblock 1509 100 280 create:mechanical_bearing[facing=up]')
    command('fill 1506 101 277 1512 101 283 minecraft:slime_block')
    command('tp @s 1510.9 102.1 280.5')
    command('gamemode survival')
    call('look-at', 1509.5, 103.6, 280.5)
    call('wait', 8)
    command('setblock 1509 99 280 create:creative_motor[facing=up]{ScrollValue:12}')
    call('wait', 18)
    standing = call('state')
    call('key', 'w', 'down')
    try:
        call('wait', 8)
    finally:
        call('key', 'w', 'up')
    walking = call('state')
    call('wait', 8)
    return standing, walking


def camera_metrics(rows, standing, walking):
    rotor = [row for row in rows if row['controller'] == list(HORIZONTAL)]
    last_standing = standing['ticks'] - 1
    still = [row for row in rotor if last_standing - 10 <= row['tick'] <= last_standing]
    walking = [row for row in rotor if last_standing + 2 <= row['tick'] < walking['ticks']]

    def metrics(frames):
        assert len(frames) > 12, len(frames)
        steps = [math.dist(a['camera'], b['camera']) for a, b in zip(frames, frames[1:])]
        short_steps = [step for step, a, b in zip(steps, frames, frames[1:])
                       if 0 < b['tick'] - a['tick'] + b['camera_partial'] - a['camera_partial'] < 0.35]
        assert short_steps, len(frames)
        return dict(frames=len(frames), distance=sum(steps), largest_short_frame=max(short_steps))

    return dict(standing=metrics(still), walking=metrics(walking))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--observe-only', action='store_true')
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    report = {'create': PINS['create_revision']}
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='vertical-rider-java-', dir=ROOT / '.local'))
        before, vertical = java_vertical(work)
    else:
        if not all((args.game, args.resources, args.ctl)):
            parser.error('Native test requires --game, --resources and --ctl')
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='contraption-rider', world='CreateMotionChecks',
                                     size=(640, 360), username='BearingReview')
        session.env['CREATE_TRACE_CONTRAPTION_FRAMES'] = '1'
        work = session.scratch
        print(work, flush=True)
        try:
            with session:
                standing, walking = native_horizontal(session.call)
                before, vertical = native_vertical(session.call)
            rows = [json.loads(line.split(MARKER, 1)[1]) for line in session.log.read_text().splitlines()
                    if MARKER in line]
            if rows and 'camera' in rows[0]:
                report['camera'] = camera_metrics(rows, standing, walking)
        finally:
            session.control_temp.cleanup()
            for path in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(path, ignore_errors=True)
    report.update(before=before, vertical=vertical)
    if args.reference:
        original = json.loads(args.reference.read_text())
        assert original['create'] == PINS['create_revision'], original
        distances = [math.dist(native['position'], java['position'])
                     for native in vertical for java in original['vertical']
                     if abs(native['angle'] - java['angle']) < .001]
        assert len(distances) >= 14, len(distances)
        report['java_comparison'] = dict(matched_angles=len(distances), max_distance=max(distances))
    (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(work)
    print('Vertical max height:', max(row['position'][1] for row in vertical), report.get('camera'))
    if not args.observe_only:
        rising = [row['position'][1] for row in vertical if 25 <= abs(row['angle']) <= 50]
        assert rising and min(rising) > before[1] + 0.6, rising
        assert vertical[-1]['position'][1] < max(rising), vertical[-1]
        if not args.java:
            assert report['camera']['standing']['largest_short_frame'] < 0.05, report['camera']
            assert report['camera']['walking']['largest_short_frame'] < 0.15, report['camera']
        if args.reference:
            assert report['java_comparison']['max_distance'] < .45, report['java_comparison']


if __name__ == '__main__':
    main()
