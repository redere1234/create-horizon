#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare creative paste of one empty dry Chute line in all horizontal transforms."""

import argparse
import hashlib
from itertools import product
import json
from pathlib import Path
import re
import shutil
import tempfile

from burner_heat_java_checks import field, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded
from reference_java import BASE, CREATE_SHA256, stage_schematic
from schematic_checks import _json_reply
from schematic_rotation_checks import ROTATIONS, fixture


CHUTE = 'create:chute'
AIR = 'minecraft:air'
GOLD = 'minecraft:gold_block'
ANCHOR = (2678, 148, 1688)
ROOM = '2673 145 1682 2683 154 1694'
FORCE = '2672 1680 2687 1695'
MIRRORS = ('none', 'left_right', 'front_back')
FACINGS = ('north', 'east', 'south', 'west')
CASES = tuple(product(MIRRORS, range(4)))
FIELDS = ('ItemPosition', 'Pull', 'Push', 'BottomAirFlowDistance')
SAFE = {'id': (8, CHUTE)}
EMPTY = SAFE | {'Item': (10, {}), **dict.fromkeys(FIELDS, (5, 0.0))}
SIZE = (3, 3, 1)
BLOCKS = [((index, index, 0), CHUTE, dict(facing=facing, shape=shape, waterlogged='false'), nbt)
          for index, (facing, shape, nbt) in enumerate((('down', 'intersection', None),
                                                       ('east', 'normal', SAFE),
                                                       ('east', 'intersection', EMPTY)))]


def placements(mirror, turns):
    direction = FACINGS[(1 + 2 * (mirror == 'front_back') + turns) % 4]
    for (x, y, _), _, props, _ in BLOCKS:
        x = -x if mirror == 'front_back' else x
        dx, dz = ((x, 0), (0, x), (-x, 0), (0, -x))[turns]
        pos = (ANCHOR[0] + dx, ANCHOR[1] + y, ANCHOR[2] + dz)
        yield pos, props | {'facing': 'down' if y == 0 else direction}


def record(row, props, pos):
    state = {key: value.lower() for key, value in row['properties'].items()}
    assert row['id'] == CHUTE and state == props, (row, props)
    nbt = row['nbt']
    assert re.search(r'\bid:\s*"create:chute"', nbt), nbt
    assert field(nbt, 'Item') == '{}', nbt
    keys = set(re.findall(r'[,{]\s*(\w+)\s*:', nbt))
    if 'components' in keys:
        assert field(nbt, 'components') == '{}', nbt
        keys.remove('components')
    assert keys == {'id', 'x', 'y', 'z', 'Item', *FIELDS}, nbt
    assert [number(row, axis) for axis in 'xyz'] == list(pos), nbt
    values = {key: number(row, key) for key in FIELDS}
    assert values == dict.fromkeys(FIELDS, 0), nbt
    return dict(properties=props, **values)


def java(work, path):
    host = Original()
    initial = host.call('state', {})
    if initial.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    assert json.loads((BASE / 'manifest.json').read_text())['create_sha256'] == CREATE_SHA256
    staged = Path(stage_schematic(BASE, path)['staged'])
    results, raw = [], []
    host.call('tick', {'frozen': True})
    try:
        host.command('gamemode creative')
        host.command(f'forceload add {FORCE}')
        host.command(f'tp @s {ANCHOR[0]}.5 {ANCHOR[1]+5} {ANCHOR[2]}.5')
        host.snapshot([ANCHOR], 24)
        for mirror, turns in CASES:
            host.command(f'fill {ROOM} {AIR}')
            reply = host.call('schematic', {'file': staged.name, 'origin': ANCHOR,
                                            'rotation': ROTATIONS[turns], 'mirror': mirror.upper()})
            assert reply['placed'], (mirror, turns, reply)
            before = [host.call('block', {'pos': pos}) for pos, _ in placements(mirror, turns)]
            samples = host.call('observe_ticks', {'ticks': 3, 'positions': [pos for pos, _ in placements(mirror, turns)]})['samples']
            frames = [before, *(sample['blocks'] for sample in samples)]
            states = list(placements(mirror, turns))
            rows = [[record(row, props, pos) for row, (pos, props) in zip(frame, states, strict=True)] for frame in frames]
            assert all(row == rows[0] for row in rows[1:]), (mirror, turns, rows)
            results.append(rows[-1])
            raw.append(dict(mirror=mirror, turns=turns, nbt=[[row['nbt'] for row in frame] for frame in frames]))
        (work / 'java-raw-nbt.json').write_text(json.dumps(raw, indent=2) + '\n')
        return results
    finally:
        host.command(f'fill {ROOM} {AIR}')
        host.command(f'forceload remove {FORCE}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        staged.unlink()
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session, path):
    directory = session.scratch / 'schematics'
    directory.mkdir()
    shutil.copy2(path, directory / path.name)
    call = session.call

    def command(text):
        return call('command', text)

    def paste(name, mirror='none', turns=0):
        return _json_reply(command(f'create schematic paste {name} {xyz(ANCHOR)} {turns} {mirror}'))

    def server_record(pos, props):
        state = CHUTE + '[' + ','.join(f'{key}={value}' for key, value in props.items()) + ']'
        reply = command(f'execute if block {xyz(pos)} {state} run data get block {xyz(pos)}')
        return record(dict(id=CHUTE, properties=props, nbt=' '.join(reply['chat'])), props, pos)

    command(f'tp @s {ANCHOR[0]}.5 {ANCHOR[1]+5} {ANCHOR[2]}.5')
    wait_loaded(call, [ANCHOR])
    command('tick freeze')
    results, refusals = [], {}
    for mirror, turns in CASES:
        command(f'fill {ROOM} {AIR}')
        reply = paste(path.name, mirror, turns)
        assert reply['ok'] and reply['placed'] == len(BLOCKS), (mirror, turns, reply)
        states = list(placements(mirror, turns))
        before = [server_record(pos, props) for pos, props in states]
        for _ in range(3):
            command('tick step 1')
            call('wait', 4)
            assert [server_record(pos, props) for pos, props in states] == before
        for pos, props in states:
            client = call('block', *pos)
            assert client['block'] == CHUTE and dict(re.findall(r'(\w+)=(\w+)', client['state'])) == props, client
        results.append(before)

    command(f'fill {ROOM} {AIR}')
    command(f'setblock {xyz(ANCHOR)} {GOLD}')
    cargo = {'id': (8, 'minecraft:iron_ingot'), 'count': (3, 7)}
    for key, blocks in {
        'disconnected': [(BLOCKS[0][0], 'minecraft:stone', {}, None), *BLOCKS[1:]],
        'loaded': [*BLOCKS[:-1], (*BLOCKS[-1][:3], EMPTY | {'Item': (10, cargo), 'ItemPosition': (5, .5)})],
    }.items():
        bad = fixture(directory, blocks=blocks, size=SIZE, prefix=key)
        reply = paste(bad.name)
        assert not reply['ok'] and reply['issues'], (key, reply)
        locations = [pos for pos, _ in placements('none', 0)]
        for pos, block in zip(locations, (GOLD, AIR, AIR), strict=True):
            check = command(f'execute if block {xyz(pos)} {block} run say chute_unchanged')
            assert any('chute_unchanged' in message for message in check['chat']), (key, pos, check)
        refusals[key] = reply['issues']
    return dict(placements=results, refusals=refusals)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    work = Path(tempfile.mkdtemp(prefix='schematic-chute-', dir=ROOT / '.local'))
    path = fixture(work, blocks=BLOCKS, size=SIZE, prefix='dry-chutes')
    report = dict(passed=False, create=PINS['create_revision'], sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    try:
        if args.game:
            if not all((args.resources, args.ctl, args.reference)):
                parser.error('Horizon requires --game, --resources, --ctl and --reference')
            source = json.loads(args.reference.read_text())
            assert source['passed'] and source['create'] == report['create'] and source['sha256'] == report['sha256']
            session = NativeCheckSession(args.game, args.resources, args.ctl, None, graphics=False,
                                         world='SchematicChute', name='schematic-chute-native')
            try:
                with session:
                    report.update(native(session, path))
                assert report['placements'] == source['placements']
            finally:
                session.control_temp.cleanup()
                for folder in (session.resources, session.scratch / '.horizon-cache', session.scratch / 'horizon-mods'):
                    shutil.rmtree(folder, ignore_errors=True)
        else:
            report['placements'] = java(work, path)
        report['passed'] = True
    finally:
        result = work / 'result.json'
        result.write_text(json.dumps(report, indent=2) + '\n')
        print(result, flush=True)


if __name__ == '__main__':
    main()
