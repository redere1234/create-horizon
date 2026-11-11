#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Audit capture and snapped landing at an actual chunk and region boundary."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from bearing_native_checks import Batch
from bearing_repeat_checks import SCENE
from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession
from saved_block_checks import read_saved_chunk_tag

AIR = 'minecraft:air'
ROOT_BLOCK = 'minecraft:slime_block'
TIP = 'minecraft:oak_planks'
# x=1024 is both a chunk and a 512-block Anvil region boundary.
X, Y = 1023, 100
LOAD = '1008 576 1039 607'
CASES = {
    'crossing_source': (582, (1, 0), (1, 0), 8),
    'crossing_destination': (598, (0, 1), (1, 0), 20),
}


def prepare(command, z, source):
    def put(pos, block):
        command(f'setblock {xyz(pos)} {block}')

    command(f'fill {X-3} {Y-1} {z-3} {X+3} {Y+3} {z+3} {AIR}')
    put((X, Y, z), 'create:mechanical_bearing[facing=up]')
    put((X, Y+1, z), ROOT_BLOCK)
    put((X+source[0], Y+1, z+source[1]), TIP)
    put((X, Y-1, z), 'create:creative_motor[facing=up]{ScrollValue:8}')


def positions(z, source, destination):
    return [(X, Y, z), (X, Y+1, z), (X+source[0], Y+1, z+source[1]),
            (X+destination[0], Y+1, z+destination[1])]


def reference(work):
    host = Original()
    state = host.call('state', {})
    if state.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        state = host.call('state', {})
    assert state['ready'] and state['data_version'] == 3955, state
    host.call('tick', {'frozen': True})
    host.command('tp @s 1022.5 107 590.5')
    host.command('forceload add ' + LOAD)
    host.snapshot([(X, Y, 582), (X+1, Y, 598)], 28)
    rows = {}
    try:
        for name, (z, source, dest, ticks) in CASES.items():
            cells = positions(z, source, dest)
            prepare(host.command, z, source)
            active = host.snapshot(cells, ticks)
            assert number(active[0], 'Running', 0) == 1, active
            assert [block['block'] for block in active[1:]] == [AIR] * 3, active
            host.command(f'setblock {X} {Y-1} {z} {AIR}')
            stopped = host.snapshot(cells, 5)
            assert number(stopped[0], 'Running', 0) == 0, stopped
            assert [block['block'] for block in stopped[1:]] == [
                ROOT_BLOCK, TIP if source == dest else AIR, TIP,
            ], stopped
            rows[name] = dict(captured=True, landed=True, angle=number(active[0], 'Angle'))
        return rows
    finally:
        for z, *_ in CASES.values():
            host.command(f'fill {X-3} {Y-1} {z-3} {X+3} {Y+3} {z+3} {AIR}')
        host.command('forceload remove ' + LOAD)
        host.call('camera', {key: state[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': state['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session):
    def inspect(batch):
        for z, source, dest, _ in CASES.values():
            pivot, seed, tip, target = positions(z, source, dest)
            batch.data(pivot)
            batch.expect(seed, ROOT_BLOCK)
            batch.expect(tip, TIP)
            if source != dest:
                batch.expect(target, AIR)

    def verify(rows):
        rows = iter(rows)
        for name, (z, source, dest, _) in CASES.items():
            pivot = (X, Y, z)
            assert number({'nbt': next(rows)}, 'Running', 0) == 0, name
            assert all('bearing_check' in next(rows) for _ in range(2 + (source != dest))), name
            for x in (X, X+1):
                tag = read_saved_chunk_tag(session.scratch, (x, Y, z), SCENE, session.world)
                assert tag['nbt'] is None, (name, pivot, tag)
        assert next(rows, None) is None

    batch = Batch()
    batch.load((1022, 107, 590))
    batch.command('forceload add ' + LOAD)
    batch.tick(20)
    for z, source, _, ticks in CASES.values():
        prepare(batch.command, z, source)
        batch.tick(ticks)
    inspect(batch)
    verify(batch.run(session, 'capture-refused'))
    batch = Batch()
    batch.load((1022, 107, 590))
    batch.tick(12)
    inspect(batch)
    verify(batch.run(session, 'cold-capture-refused'))
    return {name: dict(captured=False, retained_source_after_restart=True) for name in CASES}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='column-boundary-java-', dir=ROOT / '.local'))
        result = reference(work)
    else:
        if not all((args.game, args.resources, args.ctl)):
            parser.error('Horizon checks require --game, --resources and --ctl')
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='column-boundary', graphics=False,
                                     world='CreateColumnBoundary')
        work = session.scratch
        try:
            result = native(session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    output = work / 'result.json'
    output.write_text(json.dumps(dict(create=PINS['create_revision'], **result), indent=2) + '\n')
    print(output)


if __name__ == '__main__':
    main()
