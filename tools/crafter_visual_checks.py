#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Capture real original-JAR Crafter input, assembly and result phases."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile
import time

from bearing_native_checks import Batch
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from crafter_java_checks import DROPS, FORCE, POINTS, ROOM, SINK, X, Y, Z, click, held_stack, phase, setup
from native_check_session import NativeCheckSession, wait_loaded


CAMERA = (X + 2.5, Y + .3, Z + 6.5)
FOCUS = (X + 2.5, Y + 1.3, Z + 1.0)
PHASES = (('loaded', 'IDLE', 0, 0),
          ('merge', 'CRAFTING', 1232, 1808),
          ('wheel', 'CRAFTING', 336, 752))


def slow_setup(command):
    motor = (X - 1, Y + 2, Z - 1)
    # Use ordinary replacement instead of a raw edit to an initialized motor.
    setup(command)
    command(f'setblock {xyz(motor)} minecraft:air')
    command(f'setblock {xyz(motor)} create:creative_motor[facing=south]{{ScrollValue:32}}')


def java(work):
    host = Original()
    initial = host.call('state', {})
    if initial.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial

    def observe():
        return host.call('block', {'pos': SINK})['nbt']

    def step():
        host.call('observe_ticks', {'positions': [SINK], 'ticks': 4})

    def capture(name):
        host.call('camera', {'position': CAMERA, 'target': FOCUS, 'hide_gui': True})
        return Path(host.call('capture', {'name': f'{work.name}/{name}.png', 'frames': 8})['path'])

    try:
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        host.command(f'tp @s {xyz(CAMERA)}')
        host.command('forceload add ' + FORCE)
        host.snapshot([SINK], 25)
        slow_setup(host.command)
        host.snapshot(POINTS, 20)
        for row in range(5):
            stand = (X, Y + row - 2, Z + 3)
            host.command(f'fill {xyz(stand)} {X + 4} {stand[1]} {stand[2]} minecraft:stone')
            for pos in (p for p in POINTS if p[1] == Y + row):
                click(host, pos, held_stack(pos))
        host.command(f'fill {X} {Y - 2} {Z + 3} {X + 4} {Y + 2} {Z + 3} minecraft:air')
        host.command('gamemode spectator')
        host.command(f'tp @s {xyz(CAMERA)}')
        host.call('camera', {'position': CAMERA, 'target': FOCUS, 'hide_gui': True})
        return captures(observe, step, capture)
    finally:
        host.command('gamemode creative')
        host.command(f'kill {DROPS}')
        host.command('fill ' + ROOM + ' minecraft:air')
        host.command('forceload remove ' + FORCE)
        host.call('camera', {'position': initial['position'], 'yaw': initial['yaw'],
                             'pitch': initial['pitch'], 'hide_gui': False})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def captures(observe, step, capture, phases=PHASES):
    frames = {}
    for name, expected, low, high in phases:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            phase_name, count = phase({'nbt': observe()})
            if phase_name == expected and low <= count <= high:
                frame = capture(name)
                assert frame.stat().st_size > 1024, frame
                frames[name] = {'path': str(frame), 'countdown': count}
                break
            step()
        else:
            raise AssertionError((name, phase_name, count))
    return frames


def native(session):
    batch = Batch()
    batch.load((X + 2, Y + 2, Z + 4))
    slow_setup(batch.command)
    batch.tick(20)
    batch.command('tick freeze')
    for i, pos in enumerate(POINTS, 1):
        if pos == SINK:
            continue
        x, y, z = pos
        batch.command(f'tp @s {x + .5} {y - 1} {z + 3.25}')
        batch.command(f'item replace entity @s weapon.mainhand with {held_stack(pos)} 2')
        batch.ops.append(dict(op='use_block', pos=pos, face=3, sequence=i))
    batch.run(session, 'load-ingredients')

    def observe():
        return ' '.join(session.call('command', f'data get block {xyz(SINK)}')['chat'])

    def capture(name):
        path = session.scratch / (name + '.png')
        session.call('screenshot', path)
        return path

    with session:
        x, y, z = SINK
        session.call('command', f'tp @s {x + .5} {y - 1} {z + 3.25}')
        wait_loaded(session.call, [SINK])
        session.call('command', 'time set noon')
        session.call('command', 'tick unfreeze')
        session.call('command', 'gamemode spectator')
        session.call('command', f'tp @s {xyz(CAMERA)}')
        session.call('look-at', *FOCUS)
        session.call('key', 'f1', 'tap')
        session.call('wait', 6)
        loaded = capture('loaded')
        session.call('command', f'tp @s {x + .5} {y - 1} {z + 3.25}')
        session.call('command', 'gamemode creative')
        session.call('command', f'item replace entity @s weapon.mainhand with {held_stack(SINK)} 2')
        session.call('interact', *SINK, 'south')
        session.call('command', 'gamemode spectator')
        session.call('command', f'tp @s {xyz(CAMERA)}')
        session.call('look-at', *FOCUS)
        # The GUI-free camera was already placed for the loaded frame.
        assert loaded.stat().st_size > 1024
        return {'loaded': {'path': str(loaded), 'countdown': 0}} | captures(
            observe, lambda: session.call('wait', 2), capture, PHASES[1:])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('game', 'resources', 'ctl', 'create-jar'):
        parser.add_argument('--' + key, type=Path)
    args = parser.parse_args()
    if args.game:
        if not all((args.resources, args.ctl, args.create_jar)):
            parser.error('Horizon requires --game, --resources, --ctl and --create-jar')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='crafter-visual-native', world='CrafterVisual')
        work = session.scratch
        try:
            frames = native(session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    else:
        work = Path(tempfile.mkdtemp(prefix='crafter-visual-java-', dir=ROOT / '.local'))
        frames = java(work)
    path = work / 'captures.json'
    path.write_text(json.dumps({'create': PINS['create_revision'], 'frames': frames}, indent=2) + '\n')
    print(path)
