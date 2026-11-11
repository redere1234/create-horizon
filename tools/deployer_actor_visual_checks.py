#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare the moving Deployer's rendered hand extension before, during and after a stall."""

import argparse
import json
import math
from pathlib import Path
import shutil
import struct
import tempfile

from bearing_actor_phase_checks import AIR, MOTOR, PIVOT, SCENES, TARGET, motor, put, setup
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded

DEPLOYER = (1448, 149, 151)
CAMERA = (1445.5, 149.2, 154.5)
LOOK = (1448.8, 149.2, 150.8)
MARKER = 'Create deployer actor frame: '


def rig(command):
    setup(command, *SCENES['saw'])
    put(command, DEPLOYER, 'create:deployer[facing=down,axis_along_first=false]')


def f32(value):
    return struct.unpack('f', struct.pack('f', value))[0]


def expected(row):
    position = row.get('position')
    if row.get('disabled'):
        return 0.0
    if row['stalled'] or position is None or row.get('stationary_timer'):
        radians = f32(row['render_time'] * .5)
        index = int(f32(radians * f32(10430.378))) & 65535
        return f32(f32(math.sin(index * math.tau / 65536)) * .25 + .25)
    center = [math.floor(coordinate) + .5 for coordinate in position]
    next_position = [a + b for a, b in zip(position, row['motion'], strict=True)]
    before = math.dist(position, center)
    after = math.dist(next_position, center)
    return .5 - min(1.0, max(0.0, before + row['partial'] * (after - before)))


def verify(rows):
    stalls = [row for row in rows if row['stalled']]
    assert len(stalls) >= 10, ('not enough rendered stall frames', len(stalls))
    first = next(index for index, row in enumerate(rows) if row['stalled'])
    last = max(index for index, row in enumerate(rows) if row['stalled'])
    assert any(not row['stalled'] and any(row['motion']) for row in rows[:first])
    assert any(not row['stalled'] and any(row['motion']) for row in rows[last + 1:])
    assert not any(row.get('disabled') or row.get('stationary_timer') for row in rows)
    lowest, highest = min(row['extension'] for row in stalls), max(row['extension'] for row in stalls)
    assert lowest < .05 and highest > .45, (lowest, highest)
    error = max(abs(row['extension'] - expected(row)) for row in rows)
    assert error < 1e-6, error
    return dict(frames=len(rows), stalled=len(stalls), range=[lowest, highest], max_error=error)


def java_run(work):
    host = Original()
    initial = host.call('state', {})
    if initial.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955

    def advance(ticks):
        return host.call('observe_ticks', {'ticks': ticks, 'positions': [PIVOT, TARGET]})

    try:
        host.call('tick', {'frozen': True})
        host.command('gamemode spectator')
        host.command('forceload add 1440 144 1455 159')
        host.call('camera', {'position': CAMERA, 'target': LOOK, 'hide_gui': True,
                             'window_size': [1280, 720], 'fov': 70})
        advance(25)
        rig(host.command)
        host.call('deployer_actor_frames', {})
        put(host.command, MOTOR, motor())
        advance(27)
        screenshot = host.call('capture', {'name': f'{work.name}/stalled.png', 'frames': 2})['path']
        early = host.call('deployer_actor_frames', {})['frames']
        last = advance(55)['samples'][-1]['blocks'][1]
        assert last['id'] == AIR, last
        return early + host.call('deployer_actor_frames', {})['frames'], screenshot
    finally:
        put(host.command, MOTOR, AIR)
        advance(5)
        host.command('fill 1444 147 145 1454 153 155 minecraft:air')
        host.command('forceload remove 1440 144 1455 159')
        host.command('gamemode creative')
        host.call('camera', {'position': initial['position'], 'yaw': initial['yaw'],
                             'pitch': initial['pitch'], 'hide_gui': False})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    session.env['CREATE_TRACE_CONTRAPTION_FRAMES'] = '1'
    screenshot = session.scratch / 'stalled.png'
    try:
        with session:
            call = session.call

            def command(text):
                return call('command', text)

            command('gamemode spectator')
            command('tp @s ' + xyz(CAMERA))
            call('look-at', *LOOK)
            wait_loaded(call, [PIVOT, DEPLOYER, TARGET])
            command('tick freeze')
            rig(command)
            put(command, MOTOR, motor())
            call('key', 'f1', 'tap')
            command('tick unfreeze')
            call('wait', 26)
            call('screenshot', screenshot)
            call('wait', 56)
            assert call('block', *TARGET)['block'] == AIR
    finally:
        session.control_temp.cleanup()
        for folder in (session.resources, session.scratch / '.horizon-cache', session.scratch / 'horizon-mods'):
            shutil.rmtree(folder, ignore_errors=True)
    rows = [json.loads(line.split(MARKER, 1)[1]) for line in session.log.read_text().splitlines()
            if MARKER in line]
    return [row for row in rows if row['controller'] == list(PIVOT)], str(screenshot)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='deployer-actor-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        rows, screenshot = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon runs require --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='deployer-actor-native', world='CreateDeployerActorVisual')
        work = session.scratch
        print(work, flush=True)
        rows, screenshot = native_run(session)
    (work / 'frames.json').write_text(json.dumps(rows, indent=2) + '\n')
    summary = verify(rows)
    result = dict(passed=True, create=PINS['create_revision'], screenshot=screenshot, summary=summary)
    (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
