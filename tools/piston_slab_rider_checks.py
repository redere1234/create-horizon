#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare grounded player transfer on moving top and bottom slabs."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

from bearing_chunk_sweep_checks import put
from bearing_slab_checks import HEIGHT_TOLERANCE
from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded
from piston_slab_checks import AIR, BOTTOM, TOP


X, Y = 1450, 100
CASES = [('bottom', BOTTOM, 630, Y + .5), ('top', TOP, 646, Y + 1)]
FORCE = '1440 624 1455 655'
FRAMES = 18


def build(command, block, z):
    command(f'fill {X - 4} 96 {z - 3} {X + 5} 108 {z + 3} {AIR}')
    command(f'fill {X - 4} 95 {z - 3} {X + 5} 95 {z + 3} minecraft:stone')
    put(command, (X, Y, z), 'create:mechanical_piston[facing=east,axis_along_first=false]')
    for pole in range(X - 3, X):
        put(command, (pole, Y, z), 'create:piston_extension_pole[facing=east]')
    put(command, (X + 1, Y, z), block)


def exercise(command, tick, snapshot, require_client_ground):
    result = {}
    for name, block, z, height in CASES:
        command(f'tp @s {X + 1.5} {Y + 4} {z + .5}')
        tick(z, 20)
        build(command, block, z)
        command(f'tp @s {X + 1.5} {height + .25} {z + .5}')
        tick(z, 14)
        still = snapshot(z)
        assert still['grounded'] and abs(still['position'][1] - height) < HEIGHT_TOLERANCE, still
        put(command, (X, Y, z - 1), 'create:creative_motor[facing=south]{ScrollValue:-8}')
        tick(z, 4)
        start = snapshot(z)
        tick(z, FRAMES)
        end = snapshot(z)
        assert 0 < start['offset'] < end['offset'] < 1, (start, end)
        # The Java bridge reads the local position and server ground flag.
        # The latter is asynchronous. Prove local contact there by its fixed
        # surface height and by movement matching the piston stroke.
        if require_client_ground:
            assert start['grounded'] and end['grounded'], (start, end)
        for observed in (start, end):
            assert abs(observed['position'][1] - height) < HEIGHT_TOLERANCE, observed
            assert abs(observed['position'][2] - (z + .5)) < 1e-5, observed
        result[name] = dict(start=start, end=end,
                            player_distance=end['position'][0] - start['position'][0],
                            stroke_distance=end['offset'] - start['offset'])
    return result


def java(work):
    host = Original()
    initial = host.call('state', {})
    if initial.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    host.command('gamemode survival')
    host.command(f'forceload add {FORCE}')

    def tick(z, count):
        host.call('observe_ticks', {'ticks': count, 'positions': [[X, Y, z]]})

    def snapshot(z):
        state = host.call('state', {})
        block = host.call('block', {'pos': [X, Y, z]})
        ground = host.command('data get entity @s OnGround')['messages']
        value = re.search(r'\b([01])b$', ' '.join(ground))
        assert value, ground
        return dict(position=state['position'], grounded=value[1] == '1',
                    offset=number(block, 'Offset', 0))

    try:
        return exercise(host.command, tick, snapshot, require_client_ground=False)
    finally:
        host.command('gamemode creative')
        host.command(f'forceload remove {FORCE}')
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session):
    def command(text):
        return session.call('command', text)

    def tick(z, count):
        wait_loaded(session.call, [(X, Y, z)])
        session.call('wait', count)

    def snapshot(z):
        state = session.call('state')['player']
        nbt = ' '.join(command(f'data get block {xyz((X, Y, z))}')['chat'])
        return dict(position=state['position'], grounded=state['on_ground'],
                    offset=number({'nbt': nbt}, 'Offset', 0))

    with session:
        command('tick unfreeze')
        command('gamemode survival')
        return exercise(command, tick, snapshot, require_client_ground=True)


def compare(result):
    for name, row in result.items():
        # One asynchronous position packet can arrive between the player
        # snapshot and the server offset query. Allow two ticks at 8 RPM.
        assert abs(row['player_distance'] - row['stroke_distance']) <= 2 * 8.0 / 512.0, (name, row)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for key in ('game', 'resources', 'ctl', 'reference', 'build-result'):
        parser.add_argument('--' + key, type=Path)
    args = parser.parse_args()
    report = dict(passed=False, create=PINS['create_revision'],
                  fixture_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    session = expected = None
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='piston-slab-rider-java-', dir=ROOT / '.local'))
    else:
        if not all((args.game, args.resources, args.ctl, args.build_result)):
            parser.error('Native checks need --game, --resources, --ctl and --build-result')
        if args.reference:
            expected = json.loads(args.reference.read_text())
            assert expected['passed'] and expected['create'] == report['create'], expected
            assert expected['fixture_sha256'] == report['fixture_sha256'], 'Regenerate --reference with this fixture version'
            report['java_reference'] = str(args.reference.resolve())
        receipt = json.loads(args.build_result.read_text())
        with args.game.open('rb') as game:
            digest = hashlib.file_digest(game, 'sha256').hexdigest()
        assert receipt['passed'] and digest == receipt['game_sha256'], receipt
        report.update(horizon=receipt['horizon'], game_sha256=digest)
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='piston-slab-rider-native', graphics=True, size=(800, 450),
                                     world='CreatePistonSlabRiders')
        work = session.scratch
    print(work, flush=True)
    try:
        report['cases'] = native(session) if session else java(work)
        compare(report['cases'])
        if expected:
            assert report['cases'].keys() == expected['cases'].keys()
        report['passed'] = True
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        if session:
            session.control_temp.cleanup()
            # Finder can add a .DS_Store while the disposable tree is removed.
            shutil.rmtree(session.resources, ignore_errors=True)
            if session.resources.exists():
                shutil.rmtree(session.resources)
    print(json.dumps(dict(result=str(work / 'result.json'))), flush=True)


if __name__ == '__main__':
    main()
