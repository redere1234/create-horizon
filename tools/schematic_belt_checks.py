#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare empty horizontal Belt schematic reconstruction and motion."""

import argparse
import hashlib
import json
import math
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


ID, AIR, GOLD = 'create:belt', 'minecraft:air', 'minecraft:gold_block'
ROOM = '2017 115 1298 2044 120 1324'
FORCE = '2016 1296 2047 1327'
CAMERA = (2029, 123, 1310)
PARTS = ('start', 'middle', 'pulley', 'end')
CASES = [
    ((2023, 116, 1304), 'none', 0, 'east', (1, 0, 0), 32),
    ((2034, 116, 1310), 'front_back', 1, 'north', (0, 0, -1), -32),
]
BOUNDARY = ((2029, 116, 1320), 'none', 0, 'east', (1, 0, 0), 32)
ORDINARY = ((2024, 116, 1317), 'none', 0, 'east', (1, 0, 0), 32)


def state(facing, part):
    return dict(facing=facing, slope='horizontal', part=part, casing='false', waterlogged='false')


def source():
    result = []
    for i, part in enumerate(PARTS):
        data = {'id': (8, ID), 'Controller': (11, (800, 70, 900)), 'IsController': (1, int(i == 0)),
                'Length': (3, 4), 'Index': (3, i), 'Casing': (8, 'NONE'), 'Covered': (1, 0),
                'Speed': (5, 90)}
        if i == 0:
            data['Inventory'] = (10, {'Items': (9, (10, [])), 'PositiveOrder': (1, 1)})
        result.append(((i, 0, 1), ID, state('east', part), data))
    result.append(((0, 0, 0), 'create:creative_motor', {'facing': 'south'},
                   {'id': (8, 'create:motor'), 'ScrollValue': (3, 32)}))
    return result


def points(case):
    (x, y, z), _, _, facing, (dx, _, dz), _ = case
    start = (x, y, z + 1) if facing == 'east' else (x - 1, y, z)
    return [(start[0] + i * dx, y, start[2] + i * dz) for i in range(len(PARTS))]


def controller(raw):
    match = re.search(r'\bController:\s*\[I;\s*(-?\d+),\s*(-?\d+),\s*(-?\d+)\]', raw)
    assert match, raw
    return list(map(int, match.groups()))


def snapshot(case, blocks, parts=PARTS):
    _, _, _, facing, _, rpm = case
    result = []
    origin = points(case)[0]
    for i, (block, part) in enumerate(zip(blocks, parts, strict=True)):
        assert block['block'] == ID and block['properties'] == state(facing, part), block
        raw = block['nbt']
        assert controller(raw) == list(origin), raw
        assert number(block, 'IsController') == (i == 0), raw
        assert number(block, 'Length') == len(PARTS) and number(block, 'Index') == i, raw
        assert number(block, 'Speed') == rpm and number(block, 'Covered') == 0, raw
        assert re.search(r'\bCasing:\s*"NONE"', raw), raw
        if i == 0:
            inv = field(raw, 'Inventory')
            assert field(inv, 'Items') == '[]', inv
            positive = int(number({'nbt': inv}, 'PositiveOrder'))
        else:
            assert 'Inventory:' not in raw, raw
            positive = None
        result.append(dict(controller=list(origin), rpm=rpm, index=i, positive=positive))
    return result


def seed(command, origin):
    command(f'data merge block {xyz(origin)} {{Inventory:{{Items:[{{'
            'Item:{id:"minecraft:copper_ingot",count:4,components:{"minecraft:custom_data":{belt_schematic:73}}},'
            'Pos:2.0f,PrevPos:2.0f,Offset:0.125f,PrevOffset:0.125f,InSegment:2,InDirection:1,Angle:315}],'
            'PositiveOrder:0b}}')


def motion(case, block):
    raw = field(block['nbt'], 'Inventory')
    assert 'minecraft:copper_ingot' in raw and 'belt_schematic:73' in raw.replace(' ', ''), raw
    assert number({'nbt': raw}, 'count') == 4, raw
    delta = number({'nbt': raw}, 'Pos') - number({'nbt': raw}, 'PrevPos')
    _, _, _, _, (dx, _, dz), rpm = case
    assert math.isclose(delta, rpm * (dz - dx) / 480, abs_tol=2e-6), raw
    return round(delta, 6)


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
        host.snapshot([case[0] for case in CASES], 25)
        host.command('fill ' + ROOM + ' ' + AIR)
        result = []
        for case in CASES:
            anchor, mirror, turns, _, _, _ = case
            reply = host.call('schematic', {'file': stage.name, 'origin': anchor,
                                            'rotation': ROTATIONS[turns], 'mirror': mirror.upper()})
            assert reply['placed'], reply
            pre = [host.call('block', {'pos': pos}) for pos in points(case)]
            assert all(number(b, 'Length') == 0 and 'Controller:[' not in b['nbt'] for b in pre), pre
            settled = snapshot(case, host.snapshot(points(case), 4))
            origin = points(case)[0]
            seed(host.command, origin)
            step = motion(case, host.snapshot([origin], 5)[0])
            result.append(dict(settled=settled, motion=step))
        return result
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
    blocks = source()
    partial = fixture(directory, blocks=blocks[:1] + blocks[2:], size=(4, 1, 2), prefix='partial')
    occupied = list(blocks)
    inv = (10, {'Items': (9, (10, [{'Item': (10, {
        'id': (8, 'minecraft:copper_ingot'), 'count': (3, 1),
    })}])), 'PositiveOrder': (1, 0)})
    occupied[0] = (*occupied[0][:3], occupied[0][3] | {'Inventory': inv})
    cargo = fixture(directory, blocks=occupied, size=(4, 1, 2), prefix='occupied')
    call = session.call

    def command(text):
        return call('command', text)

    def paste(file, case):
        anchor, mirror, turns, _, _, _ = case
        return _json_reply(command(f'create schematic paste {file.name} {xyz(anchor)} {turns} {mirror}'))

    def block_at(pos):
        actual = call('block', *pos)
        return dict(block=actual['block'], properties=dict(re.findall(r'(\w+)=(\w+)', actual['state'])),
                    nbt=' '.join(command(f'data get block {xyz(pos)}')['chat']))

    def interact(pos):
        x, y, z = pos
        command(f'setblock {x} {y - 1} {z + 3} minecraft:stone')
        command(f'tp @s {x + .5} {y} {z + 3.5}')
        call('wait', 3)
        call('look-at', 'block', *pos, 'south')
        call('interact', *pos, 'south')
        call('wait', 5)

    with session:
        command(f'tp @s {CAMERA[0]}.5 {CAMERA[1]} {CAMERA[2]}.5')
        wait_loaded(call, [pos for case in (*CASES, BOUNDARY) for pos in points(case)])
        command('fill ' + ROOM + ' ' + AIR)
        refused = {}
        for label, file, case, message in [
            ('partial', partial, CASES[0], 'complete horizontal chain'),
            ('occupied', cargo, CASES[0], 'empty Belt Inventory'),
            ('cross_column', path, BOUNDARY, 'one destination column'),
            ('blocked_destination', path, CASES[0], 'require air'),
        ]:
            locations = [case[0], *points(case)]
            sentinel = locations[2] if label == 'blocked_destination' else locations[0]
            command(f'setblock {xyz(sentinel)} {GOLD}')
            call('wait', 3)
            before = [call('block', *pos)['block'] for pos in locations]
            result = paste(file, case)
            assert not result['ok'] and any(message in issue['message'] for issue in result['issues']), result
            assert [call('block', *pos)['block'] for pos in locations] == before
            refused[label] = result['issues']
            command(f'setblock {xyz(sentinel)} {AIR}')
        for case in CASES:
            result = paste(path, case)
            assert result['ok'] and result['placed'] == len(blocks), result
        call('wait', 8)
        result = [dict(settled=snapshot(case, [block_at(pos) for pos in points(case)]))
                  for case in CASES]
        session.restart()
        wait_loaded(call, [pos for case in CASES for pos in points(case)])
        for index, case in enumerate(CASES):
            assert snapshot(case, [block_at(pos) for pos in points(case)]) == result[index]['settled']
            origin = points(case)[0]
            seed(command, origin)
            call('wait', 5)
            result[index]['motion'] = motion(case, block_at(origin))
        assert result == expected, (result, expected)
        ordinary = points(ORDINARY)
        for endpoint in (ordinary[0], ordinary[-1]):
            command(f'setblock {xyz(endpoint)} create:shaft[axis=z]')
        command('item replace entity @s weapon.mainhand with create:belt_connector')
        for endpoint in (ordinary[0], ordinary[-1]):
            interact(endpoint)
        command(f'setblock {xyz(ORDINARY[0])} create:creative_motor[facing=south]{{ScrollValue:32}}')
        call('wait', 10)
        snapshot(ORDINARY, [block_at(pos) for pos in ordinary], ('start', 'middle', 'middle', 'end'))
        seed(command, ordinary[0])
        call('wait', 5)
        step = motion(ORDINARY, block_at(ordinary[0]))
        assert step == expected[0]['motion']
        return dict(cases=result, refusals=refused, cold_restart=True, ordinary_connector_motion=step)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for key in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + key, type=Path)
    args = parser.parse_args()
    work = Path(tempfile.mkdtemp(prefix='schematic-belt-', dir=ROOT / '.local'))
    path = fixture(work, blocks=source(), size=(4, 1, 2), prefix='belt')
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if args.java:
        report = dict(cases=java_run(path))
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon needs --game, --resources, --ctl and --reference')
        expected = json.loads(args.reference.read_text())
        assert expected['passed'] and expected['sha256'] == sha and expected['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None, graphics=False,
                                     world='BeltSchematic', name='belt-schematic-native')
        try:
            report = native_run(session, path, expected['cases'])
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
