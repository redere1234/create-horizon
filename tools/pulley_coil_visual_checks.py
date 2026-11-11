#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Capture the real Rope Pulley coil at matched fractional extension and retraction."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile
import time

from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded
from pulley_reference_checks import actuator_state


PULLEY = (1524, 164, 194)
DOWN = (1524, 164, 193)
UP = (1524, 164, 195)
CAMERA = (1526.9, 162.88, 194.5)
FOCUS = (1524.5, 164.5, 194.5)
PATH = [PULLEY, DOWN, UP] + [(1524, y, 194) for y in range(159, 164)]
AIR = 'minecraft:air'


def capture_phases(put, observe, capture):
    put(PULLEY, 'create:rope_pulley[axis=z]')
    assert observe() == [0, 0, 0]
    frames = {'parked': {'offset': 0, 'path': capture('parked')}}

    def seek(offset):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            state = observe()
            if state[0] == offset and state[1] == 1:
                return
            time.sleep(.015)
        raise AssertionError((offset, state))

    def record(label, offset):
        seek(offset)
        frame = capture(label)
        end = observe()[0]
        assert abs(end - offset) <= .0625, (label, offset, end)
        frames[label] = {'offset': offset, 'offset_after_capture': end, 'path': frame}

    # The rope repeats every four texels. At 32 RPM each tick moves one
    # texel. Space the samples five ticks apart for asynchronous readback.
    offsets = [('one', .0625), ('two', .375), ('three', .6875)]
    put(DOWN, 'create:creative_motor[facing=south]{ScrollValue:32}')
    for label, offset in offsets:
        record(f'down-{label}', offset)
    seek(1)
    put(DOWN, AIR)
    put(UP, 'create:creative_motor[facing=north]{ScrollValue:32}')
    for label, offset in reversed(offsets):
        record(f'up-{label}', offset)
    return frames


def java_run(work):
    host = Original()
    initial = host.call('state', {})
    if initial.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
    assert host.call('state', {})['ready'] and initial['data_version'] == 3955
    assert initial['render_backend']['supports_visualization'], initial['render_backend']

    def put(pos, block):
        host.command(f'setblock {xyz(pos)} {block}')

    def observe():
        return actuator_state(host.call('block', {'pos': PULLEY}))

    def capture(label):
        # The initial terrain mesh can arrive after the block entity itself.
        frames = 30 if label == 'parked' else 2
        shot = host.call('capture', {'name': f'{work.name}/{label}.png', 'frames': frames})
        assert shot['width'] >= 640 and shot['height'] >= 360
        return shot['path']

    force = f'{PULLEY[0]} {PULLEY[2]}'
    mode = next(mode for mode in ('creative', 'spectator', 'survival', 'adventure')
                if host.command(f'execute if entity @s[gamemode={mode}]')['messages']
                == ['Test passed, count: 1'])
    owned = False
    try:
        host.call('tick', {'frozen': True})
        host.command('gamemode spectator')
        host.call('camera', {'position': CAMERA, 'target': FOCUS, 'hide_gui': True,
                             'window_size': [1280, 720], 'fov': 70})
        host.command(f'forceload add {force}')
        host.call('tick', {'step': 20})
        for position in PATH:
            assert host.call('block', {'pos': position})['id'] == AIR, position
        owned = True
        host.command('tick rate 2')
        host.call('tick', {'frozen': False})
        return capture_phases(put, observe, capture)
    finally:
        host.call('tick', {'frozen': True})
        host.command('tick rate 20')
        if owned:
            for position in PATH:
                put(position, AIR)
        host.command(f'forceload remove {force}')
        host.command(f'gamemode {mode}')
        host.call('camera', {'position': initial['position'], 'yaw': initial['yaw'],
                             'pitch': initial['pitch'], 'hide_gui': False, 'fov': initial['fov']})
        host.call('tick', {'frozen': initial['server']['frozen']})
        if initial.get('screen') == 'PauseScreen':
            host.call('input', {'kind': 'escape'})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    with session:
        call = session.call

        def command(text):
            return call('command', text)

        def put(pos, block):
            command(f'setblock {xyz(pos)} {block}')

        def observe():
            nbt = ' '.join(command(f'data get block {xyz(PULLEY)}')['chat'])
            return actuator_state({'nbt': nbt})

        def capture(label):
            path = session.scratch / f'{label}.png'
            call('screenshot', path)
            assert path.stat().st_size > 1024
            return str(path)

        command('gamemode spectator')
        command('tp @s ' + xyz(CAMERA))
        call('look-at', *FOCUS)
        wait_loaded(call, [PULLEY])
        call('key', 'f1', 'tap')
        command('tick rate 1')
        return capture_phases(put, observe, capture)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'create-jar'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='pulley-coil-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        frames = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.create_jar)):
            parser.error('Horizon runs require --game, --resources, --ctl and --create-jar')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='pulley-coil-native', world='CreatePulleyCoilVisual',
                                     size=(640, 360))
        work = session.scratch
        print(work, flush=True)
        try:
            frames = native_run(session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    result = {'passed': True, 'create': PINS['create_revision'], 'frames': frames}
    (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
