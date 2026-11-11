#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare grounded riders on both treads of a moving dry straight stair."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile

from bearing_slab_checks import HEIGHT_TOLERANCE
from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from contraption_stair_checks import AIR, SLIME, stair
from native_check_session import NativeCheckSession, wait_loaded


X, Y = 1656, 100
CASES = (
    ('rotary_lower', 1032, True, .95, .5),
    ('rotary_upper', 1048, True, .25, 1.),
    ('linear_lower', 1064, False, .95, .5),
    ('linear_upper', 1080, False, .25, 1.),
)
FORCE = '1648 1024 1663 1087'


def build(command, z, rotary):
    command(f'fill {X-4} 97 {z-4} {X+6} 106 {z+4} {AIR}')
    command(f'fill {X-4} 96 {z-4} {X+6} 96 {z+4} minecraft:stone')
    block = stair('oak', 'north', 'bottom')
    if rotary:
        command(f'setblock {X} {Y} {z} create:mechanical_bearing[facing=up]')
        command(f'setblock {X} {Y+1} {z} {SLIME}')
        command(f'setblock {X+1} {Y+1} {z} {block}')
        return f'setblock {X} {Y-1} {z} create:creative_motor[facing=up]{{ScrollValue:8}}'
    command(f'setblock {X} {Y} {z} create:mechanical_piston[facing=east,axis_along_first=false]')
    for x in range(X-3, X):
        command(f'setblock {x} {Y} {z} create:piston_extension_pole[facing=east]')
    command(f'setblock {X+1} {Y} {z} {block}')
    return f'setblock {X} {Y} {z-1} create:creative_motor[facing=south]{{ScrollValue:-8}}'


def exercise(command, tick, snapshot, *, native):
    result = {}
    for name, z, rotary, relative_z, tread in CASES:
        command('gamemode creative')
        command(f'tp @s {X+1.5} {Y+4} {z+.5}')
        tick(z, 20)
        power = build(command, z, rotary)
        height = Y + int(rotary) + tread
        command(f'tp @s {X+1.5} {height+.25} {z+relative_z}')
        command('gamemode survival')
        tick(z, 14)
        before = snapshot(z, rotary)
        command(power)
        tick(z, 5)
        start = snapshot(z, rotary)
        tick(z, 15)
        end = snapshot(z, rotary)
        for row in (before, start, end):
            assert abs(row['position'][1] - height) < HEIGHT_TOLERANCE, (name, row)
            if native:
                assert row['grounded'], (name, row)
        assert 0 < start['pose'] < end['pose'], (name, start, end)
        if rotary:
            cx, cz = X + .5, z + .5
            radius = math.hypot(before['position'][0] - cx, before['position'][2] - cz)
            for row in (start, end):
                x, _, pz = row['position']
                assert abs(math.hypot(x - cx, pz - cz) - radius) < .004, (name, row)
            ax, _, az = start['position']
            bx, _, bz = end['position']
            travelled = math.degrees(math.atan2(az - cz, ax - cx) - math.atan2(bz - cz, bx - cx))
            assert travelled > 25, (name, start, end, travelled)
            # Java's local bearing interpolates independently of the frozen
            # server samples. Compare the path and bound that sampling skew.
            tolerance = 5.0 if native else 12.1
        else:
            travelled = end['position'][0] - start['position'][0]
            assert travelled > .18, (name, start, end, travelled)
            assert abs(end['position'][2] - (z+relative_z)) < 1e-5, (name, end)
            tolerance = 2 * 8.0 / 512.0
        pose_delta = end['pose'] - start['pose']
        assert abs(travelled - pose_delta) <= tolerance, (name, travelled, pose_delta)
        result[name] = dict(start=start, end=end, travel=travelled, pose_delta=pose_delta)
    return result


def java(work):
    host = Original()
    initial = host.call('state', {})
    if initial.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    host.command(f'forceload add {FORCE}')

    def tick(z, count):
        host.call('observe_ticks', {'ticks': count, 'positions': [[X, Y, z]]})

    def snapshot(z, rotary):
        block = host.call('block', {'pos': [X, Y, z]})
        return dict(position=host.call('state', {})['position'],
                    pose=number(block, 'Angle' if rotary else 'Offset', 0))

    try:
        return exercise(host.command, tick, snapshot, native=False)
    finally:
        host.command('gamemode creative')
        host.command(f'forceload remove {FORCE}')
        host.call('camera', {'position': initial['position'], 'yaw': initial['yaw'], 'pitch': initial['pitch']})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session):
    def command(text):
        return session.call('command', text)

    def tick(z, count):
        wait_loaded(session.call, [(X, Y, z)])
        session.call('wait', count)

    def snapshot(z, rotary):
        player = session.call('state')['player']
        nbt = ' '.join(command(f'data get block {xyz((X, Y, z))}')['chat'])
        return dict(position=player['position'], grounded=player['on_ground'],
                    pose=number({'nbt': nbt}, 'Angle' if rotary else 'Offset', 0))

    with session:
        command('tick unfreeze')
        return exercise(command, tick, snapshot, native=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for key in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + key, type=Path)
    args = parser.parse_args()
    report = dict(passed=False, create=PINS['create_revision'],
                  fixture_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    session = expected = None
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='stair-rider-java-', dir=ROOT / '.local'))
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Native checks need --game, --resources, --ctl and --reference')
        expected = json.loads(args.reference.read_text())
        assert expected['passed'] and expected['create'] == report['create'], expected
        assert expected['fixture_sha256'] == report['fixture_sha256'], 'Regenerate the Java reference'
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='stair-rider-native', graphics=True, size=(800, 450),
                                     world='CreateStairRiders')
        work = session.scratch
    print(work, flush=True)
    try:
        report['cases'] = native(session) if session else java(work)
        if expected:
            assert report['cases'].keys() == expected['cases'].keys()
        report['passed'] = True
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        if session:
            for path in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(path, ignore_errors=True)


if __name__ == '__main__':
    main()
