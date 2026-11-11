#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare every Encased Cogwheel state in all twelve horizontal transforms."""

import argparse
import hashlib
from itertools import product
import json
from pathlib import Path
import re
import shutil
import tempfile

from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded
from reference_java import BASE, stage_schematic
from schematic_checks import _json_reply
from schematic_rotation_checks import ROTATIONS, fixture


ANCHOR = (2215, 112, 1333)
ROOM = '2202 111 1320 2228 115 1346'
FORCE = '2192 1312 2239 1359'
MIRRORS = ('none', 'left_right', 'front_back')
AXES = {
    'x': [('x', False), ('z', False), ('x', True), ('z', True)],
    'y': [('y', False)] * 4,
    'z': [('z', False), ('x', True), ('z', True), ('x', False)],
}
BLOCKS = []
for i, (metal, size, axis, top, bottom) in enumerate(product(
        ('andesite', 'brass'), ('', 'large_'), AXES, ('false', 'true'), ('false', 'true'))):
    name = f'create:{metal}_encased_{size}cogwheel'
    entity = f'create:encased_{size}cogwheel'
    position = (2 * (i % 7), 0, 2 * (i // 7))
    BLOCKS.append((position, name, dict(axis=axis, top_shaft=top, bottom_shaft=bottom),
                   {'id': (8, entity)} if i % 2 else None))


def expected(mirror, turns):
    for (x, y, z), name, state, _ in BLOCKS:
        x = -x if mirror == 'front_back' else x
        z = -z if mirror == 'left_right' else z
        dx, dz = [(x, z), (-z, x), (-x, -z), (z, -x)][turns]
        axis, rotated = AXES[state['axis']][turns]
        reflected = (mirror, state['axis']) in (('front_back', 'x'), ('left_right', 'z'))
        top, bottom = state['top_shaft'], state['bottom_shaft']
        if rotated ^ reflected:
            top, bottom = bottom, top
        entity = 'create:encased_large_cogwheel' if '_large_' in name else 'create:encased_cogwheel'
        yield ((ANCHOR[0] + dx, ANCHOR[1] + y, ANCHOR[2] + dz), name,
               dict(axis=axis, top_shaft=top, bottom_shaft=bottom), entity)


def java(path):
    host = Original()
    state = host.call('state', {})
    if state.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        state = host.call('state', {})
    assert state['ready'] and state['data_version'] == 3955
    staged = Path(stage_schematic(BASE, path)['staged'])
    count = 0
    host.call('tick', {'frozen': True})
    try:
        host.command('gamemode creative')
        host.command(f'forceload add {FORCE}')
        host.command(f'tp @s {ANCHOR[0]}.5 118 {ANCHOR[2]}.5')
        host.snapshot([ANCHOR], 22)
        for mirror, turns in product(MIRRORS, range(4)):
            host.command(f'fill {ROOM} minecraft:air')
            reply = host.call('schematic', {'file': staged.name, 'origin': ANCHOR,
                                            'rotation': ROTATIONS[turns], 'mirror': mirror.upper()})
            assert reply['placed'], (mirror, turns, reply)
            states = list(expected(mirror, turns))
            observed = [block for offset in range(0, len(states), 32)
                        for block in host.snapshot([row[0] for row in states[offset:offset + 32]], 1)]
            for block, (pos, name, props, entity) in zip(observed, states, strict=True):
                assert block['block'] == name and block['properties'] == props, (mirror, turns, pos, block, props)
                assert f'id:"{entity}"' in block['nbt'] and block['speed'] == 0, block
                count += 1
        return count
    finally:
        host.command(f'fill {ROOM} minecraft:air')
        host.command(f'forceload remove {FORCE}')
        host.call('camera', {key: state[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': state['server']['frozen']})
        staged.unlink()
        (path.parent / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(path, session):
    directory = session.scratch / 'schematics'
    directory.mkdir()
    shutil.copy2(path, directory / path.name)
    count = 0
    with session:
        call = session.call
        call('command', f'tp @s {ANCHOR[0]}.5 118 {ANCHOR[2]}.5')
        columns = {(pos[0] >> 4, pos[2] >> 4): pos for mirror, turns in product(MIRRORS, range(4))
                   for pos, *_ in expected(mirror, turns)}
        wait_loaded(call, columns.values())
        for mirror, turns in product(MIRRORS, range(4)):
            call('command', f'fill {ROOM} minecraft:air')
            reply = _json_reply(call('command', f'create schematic paste {path.name} {xyz(ANCHOR)} {turns} {mirror}'))
            assert reply['ok'] and reply['placed'] == len(BLOCKS), (mirror, turns, reply)
            call('wait', 3)
            for pos, name, props, entity in expected(mirror, turns):
                block = call('block', *pos)
                state = dict(re.findall(r'(\w+)=(\w+)', block['state']))
                assert block['block'] == name and state == props, (mirror, turns, pos, block)
                raw = ' '.join(call('command', f'data get block {xyz(pos)}')['chat'])
                assert f'id: "{entity}"' in raw and number({'nbt': raw}, 'Speed', 0) == 0, raw
                count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + key, type=Path)
    args = parser.parse_args()
    if args.game:
        if not all((args.resources, args.ctl, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None, size=(800, 600),
                                     name='schematic-cog-native', world='SchematicEncasedCog')
        work = session.scratch
        try:
            path = args.reference.parent / reference['fixture']
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            assert digest == reference['sha256']
            count = native(path, session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    else:
        work = Path(tempfile.mkdtemp(prefix='schematic-cog-java-', dir=ROOT / '.local'))
        path = fixture(work, blocks=BLOCKS, size=(13, 1, 13), prefix='encased-cogs')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        count = java(path)
    assert count == 576
    output = work / 'result.json'
    output.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], fixture=path.name,
                                      sha256=digest, placements=count), indent=2) + '\n')
    print(output)


if __name__ == '__main__':
    main()
