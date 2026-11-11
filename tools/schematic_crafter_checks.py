#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Paste identical empty Mechanical Crafter schematics in Java and Horizon."""

import argparse
import hashlib
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


BLOCK = 'create:mechanical_crafter'
AIR = 'minecraft:air'
GOLD = 'minecraft:gold_block'
ROOM = '1924 108 1236 1956 115 1260'
FORCE = '1920 1232 1967 1279'
CAMERA = (1940, 115, 1248)
FACINGS = ('north', 'east', 'south', 'west')
MIRRORS = ('none', 'left_right', 'front_back')
CASES = [(mirror, turns, (1928 + 8 * turns, 110, 1240 + 8 * row))
         for row, mirror in enumerate(MIRRORS) for turns in range(4)]
CONNECTED = (10, {'Controller': (1, 1), 'Data': (9, (10, [
    {axis: (3, 0) for axis in ('X', 'Y', 'Z')},
]))})
SAFE = {'id': (8, BLOCK), 'ConnectedInput': CONNECTED}
FULL = SAFE | {'Cover': (1, 0), 'Phase': (8, 'IDLE'), 'CountDown': (3, 0),
               'Inventory': (10, {'Items': (9, (10, [])), 'Size': (3, 1)}),
               'GroupedItems': (10, {'Grid': (9, (10, []))})}
BLOCKS = [
    ((0, 0, 0), BLOCK, {'facing': 'north', 'pointing': 'left'}, FULL),
    ((2, 1, 0), BLOCK, {'facing': 'east', 'pointing': 'down'}, SAFE),
    ((1, 0, 2), BLOCK, {'facing': 'south', 'pointing': 'right'}, None),
    ((0, 2, 1), BLOCK, {'facing': 'west', 'pointing': 'up'}, FULL | {'Speed': (5, 128)}),
]


def placements(case):
    mirror, turns, anchor = case
    for (x, y, z), name, props, _ in BLOCKS:
        if mirror == 'left_right':
            z = -z
        if mirror == 'front_back':
            x = -x
        dx, dz = ((x, z), (-z, x), (-x, -z), (z, -x))[turns]
        facing = props['facing']
        flip = mirror == 'left_right' and facing in ('north', 'south') or (
            mirror == 'front_back' and facing in ('east', 'west'))
        target = FACINGS[(FACINGS.index(facing) + 2 * flip + turns) % 4]
        yield (anchor[0] + dx, anchor[1] + y, anchor[2] + dz), name, dict(props, facing=target)


def empty_crafter(nbt):
    connected = re.sub(r'\s+', '', field(nbt, 'ConnectedInput'))
    offsets = field(connected, 'Data')
    assert offsets.startswith('[{') and offsets.endswith('}]'), nbt
    assert set(offsets[2:-2].split(',')) == {'X:0', 'Y:0', 'Z:0'}, nbt
    assert set(connected.replace(offsets, '[]')[1:-1].split(',')) == {'Controller:1b', 'Data:[]'}, nbt
    inventory = re.sub(r'\s+', '', field(nbt, 'Inventory'))
    assert set(inventory[1:-1].split(',')) == {'Items:[]', 'Size:1'}, nbt
    assert re.sub(r'\s+', '', field(nbt, 'GroupedItems')) == '{Grid:[]}', nbt
    assert re.search(r'\bPhase:\s*"IDLE"', nbt), nbt
    assert all(number({'nbt': nbt}, key, 0) == 0 for key in ('Speed', 'CountDown', 'Cover')), nbt
    return dict(connected='{Controller:1b,Data:[{X:0,Y:0,Z:0}]}', inventory='{Items:[],Size:1}', phase='IDLE')


def java_run(path):
    host = Original()
    assert json.loads((BASE / 'manifest.json').read_text())['create_sha256'] == CREATE_SHA256
    initial = host.call('state', {})
    if initial.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    stage = Path(stage_schematic(BASE, path)['staged'])
    try:
        host.command('gamemode creative')
        host.command(f'tp @s {CAMERA[0]}.5 {CAMERA[1]} {CAMERA[2]}.5')
        host.command('forceload add ' + FORCE)
        host.snapshot([anchor for _, _, anchor in CASES], 30)
        host.command('fill ' + ROOM + ' ' + AIR)
        for mirror, turns, anchor in CASES:
            result = host.call('schematic', {'file': stage.name, 'origin': anchor,
                                             'rotation': ROTATIONS[turns], 'mirror': mirror.upper()})
            assert result['placed'], (mirror, turns, result)
        rows = []
        for case in CASES:
            for pos, name, props in placements(case):
                actual = host.call('block', {'pos': pos})
                state = {key: value.lower() for key, value in actual['properties'].items()}
                assert actual['id'] == name and state == props, (case, pos, actual, props)
                rows.append(dict(pos=pos, id=name, properties=props, **empty_crafter(actual['nbt'])))
        return rows
    finally:
        host.command('fill ' + ROOM + ' ' + AIR)
        host.command('forceload remove ' + FORCE)
        host.call('tick', {'frozen': initial['server']['frozen']})
        stage.unlink()
        (path.parent / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session, path, expected):
    directory = session.scratch / 'schematics'
    directory.mkdir()
    shutil.copy2(path, directory / path.name)
    linked = (10, {'Controller': (1, 1), 'Data': (9, (10, [
        {axis: (3, 0) for axis in ('X', 'Y', 'Z')}, {'X': (3, 1), 'Y': (3, 0), 'Z': (3, 0)},
    ]))})
    refusals = {
        'linked': FULL | {'ConnectedInput': linked},
        'active': FULL | {'Phase': (8, 'EXPORTING'), 'CountDown': (3, 250)},
        'occupied': FULL | {'Inventory': (10, {'Size': (3, 1), 'Items': (9, (10, [
            {'Slot': (3, 0), 'id': (8, 'create:andesite_alloy'), 'count': (3, 1)},
        ]))})},
    }
    call = session.call

    def command(text):
        return call('command', text)

    def paste(filename, case):
        mirror, turns, anchor = case
        return _json_reply(command(f'create schematic paste {filename} {xyz(anchor)} {turns} {mirror}'))

    command('gamemode creative')
    command(f'tp @s {CAMERA[0]}.5 {CAMERA[1]} {CAMERA[2]}.5')
    wait_loaded(call, [anchor for _, _, anchor in CASES])
    command('fill ' + ROOM + ' ' + AIR)
    case = CASES[-1]
    anchor = case[2]
    command(f'setblock {xyz(anchor)} {GOLD}')
    call('wait', 3)
    locations = [pos for pos, _, _ in placements(case)]
    issues = {}
    for reason, message in [('linked', 'unlinked'), ('active', 'Phase'), ('occupied', 'Inventory')]:
        invalid = BLOCKS[:-1] + [(*BLOCKS[-1][:3], refusals[reason])]
        file = fixture(directory, blocks=invalid, size=(3, 3, 3), prefix=reason)
        result = paste(file.name, case)
        assert not result['ok'] and result['issues'], result
        assert any(message in issue['message'] for issue in result['issues']), result
        issues[reason] = result['issues']
        assert [call('block', *pos)['block'] for pos in locations] == [GOLD, AIR, AIR, AIR]
    command(f'setblock {xyz(anchor)} {AIR}')
    for case in CASES:
        result = paste(path.name, case)
        assert result['ok'] and result['placed'] == len(BLOCKS), result
    call('wait', 5)
    observed = []
    for case in CASES:
        for pos, name, props in placements(case):
            actual = call('block', *pos)
            state = dict(re.findall(r'(\w+)=(\w+)', actual['state']))
            assert actual['block'] == name and state == props, (case, pos, actual)
            nbt = ' '.join(command(f'data get block {xyz(pos)}')['chat'])
            observed.append(dict(pos=list(pos), id=name, properties=props, **empty_crafter(nbt)))
    assert observed == expected
    return dict(placements=len(observed), refusals=issues)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for key in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + key, type=Path)
    args = parser.parse_args()
    work = Path(tempfile.mkdtemp(prefix='schematic-crafter-', dir=ROOT / '.local'))
    path = fixture(work, blocks=BLOCKS, size=(3, 3, 3), prefix='crafters')
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if args.java:
        report = dict(placements=java_run(path))
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon needs --game, --resources, --ctl and --reference')
        expected = json.loads(args.reference.read_text())
        assert expected['passed'] and expected['sha256'] == sha and expected['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None, graphics=False,
                                     world='CrafterSchematic', name='crafter-schematic-native')
        try:
            with session:
                report = dict(**native_run(session, path, expected['placements']), scratch=str(session.scratch))
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, session.scratch / '.horizon-cache', session.scratch / 'horizon-mods'):
                if folder.exists():
                    shutil.rmtree(folder)
    output = work / 'result.json'
    output.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], sha256=sha, **report), indent=2) + '\n')
    print(output)


if __name__ == '__main__':
    main()
