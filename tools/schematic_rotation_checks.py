#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Paste the same asymmetric schematic in both games at all four orientations."""
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
from schematic_checks import _json_reply, _write


ANCHORS = [(x, 86, 64) for x in (1408, 1418, 1428, 1438)]
FORCE_RANGE = '1392 48 1455 79'
ROTATIONS = ['NONE', 'CLOCKWISE_90', 'CLOCKWISE_180', 'COUNTERCLOCKWISE_90']
GOLD = 'minecraft:gold_block'
BLOCKS = [
    ((0, 2, 0), 'create:creative_motor', {'facing': 'east'}, {'id': (8, 'create:motor'), 'ScrollValue': (3, 48), 'Speed': (5, 999)}),
    ((1, 2, 0), 'create:shaft', {'axis': 'x', 'waterlogged': 'true'}, {'id': (8, 'create:simple_kinetic')}),
    ((2, 2, 0), 'create:flywheel', {'axis': 'x'}, {'id': (8, 'create:flywheel')}),
    ((3, 2, 0), 'create:mechanical_press', {'facing': 'east'}, {'id': (8, 'create:mechanical_press')}),
    ((3, 0, 0), 'create:depot', {'waterlogged': 'false'}, {'id': (8, 'create:depot')}),
    ((0, 0, 1), 'minecraft:smooth_stone', {}, None),
    ((1, 0, 1), 'minecraft:oak_log', {'axis': 'z'}, None),
    ((2, 0, 1), 'minecraft:oak_log', {'axis': 'y'}, None),
    ((3, 0, 1), 'minecraft:air', {}, None),
]


def fixture(directory, unsupported=False, *, blocks=BLOCKS, size=(4, 3, 2), prefix='rotated'):
    palette, entries = [], []
    for index, (pos, name, properties, data) in enumerate(blocks):
        palette.append({'Name': (8, name), 'Properties': (10, {
            key: (8, value) for key, value in properties.items()})})
        entry = {'pos': (9, (3, pos)), 'state': (3, index)}
        if data:
            entry['nbt'] = (10, data | {'x': (3, 900), 'y': (3, 80), 'z': (3, -500)})
        entries.append(entry)
    if unsupported:
        palette.append({'Name': (8, 'minecraft:lever')})
    filename = directory / (prefix + ('-unsupported.nbt' if unsupported else '-press.nbt'))
    _write(filename, {
        'DataVersion': (3, 3955), 'size': (9, (3, size)),
        'palette': (9, (10, palette)), 'blocks': (9, (10, entries)), 'entities': (9, (10, [])),
    })
    return filename


def placements(turns):
    origin = ANCHORS[turns]
    for (x, y, z), block, properties, _ in BLOCKS:
        dx, dz = [(x, z), (-z, x), (-x, -z), (z, -x)][turns]
        yield (origin[0] + dx, origin[1] + y, origin[2] + dz), block, properties


def snapshot(turns, block_at):
    rows = []
    for index, (pos, source_id, source_properties) in enumerate(placements(turns)):
        block = block_at(pos)
        assert block['id'] == (GOLD if source_id == 'minecraft:air' else source_id), (turns, pos, block)
        row = dict(pos=pos, id=block['id'],
                   properties={key: block['properties'][key] for key in source_properties})
        if index < 4:
            row['speed'] = number(block, 'Speed')
            assert row['speed'] == (48 if turns < 2 else -48), (turns, block)
        if index == 0:
            row['setting'] = number(block, 'ScrollValue')
            assert row['setting'] == 48, block
        rows.append(row)
    return rows


def paste_setup(command, wait):
    command('gamemode creative')
    command('tp @s 1422.5 91 64.5')
    command(f'forceload add {FORCE_RANGE}')
    wait(40)
    command('fill 1403 86 59 1443 90 69 minecraft:air')
    command('fill 1403 85 59 1443 85 69 minecraft:smooth_stone')
    for turns in range(4):
        air = list(placements(turns))[-1][0]
        command(f'setblock {xyz(air)} {GOLD}')


def production(command, wait, block_at):
    depots = [list(placements(turns))[4][0] for turns in range(4)]
    for pos in depots:
        command(f'data merge block {xyz(pos)} '
                '{HeldItem:{Item:{id:"minecraft:copper_ingot",count:1},Pos:0.5f,PrevPos:0.5f,InDirection:1}}')
    wait(180)
    stacks = []
    for pos in depots:
        held = field(block_at(pos)['nbt'], 'HeldItem')
        assert 'create:copper_sheet' in held and number({'nbt': held}, 'count') == 1, (pos, held)
        stacks.append('create:copper_sheet')
    return stacks


def java_run(path):
    host = Original()
    manifest = json.loads((BASE / 'manifest.json').read_text())
    assert manifest['create_sha256'] == CREATE_SHA256
    state = host.call('state', {})
    assert state['ready'] and state['data_version'] == 3955, state
    name = stage_schematic(BASE, path)['file']
    host.call('tick', {'frozen': True})

    def wait(ticks):
        host.call('observe_ticks', {'ticks': ticks, 'positions': ANCHORS})

    def block_at(pos):
        return host.call('block', {'pos': pos})

    try:
        paste_setup(host.command, wait)
        for origin, rotation in zip(ANCHORS, ROTATIONS, strict=True):
            reply = host.call('schematic', {'file': name, 'origin': origin, 'rotation': rotation})
            assert reply['placed'], reply
        wait(30)
        rows = [snapshot(turns, block_at) for turns in range(4)]
        return dict(rotations=rows, output=production(host.command, wait, block_at))
    finally:
        host.command(f'forceload remove {FORCE_RANGE}')
        (path.parent / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session, path):
    directory = session.scratch / 'schematics'
    directory.mkdir()
    shutil.copy2(path, directory / path.name)
    unsupported = fixture(directory, unsupported=True)
    call = session.call

    def command(value):
        return call('command', value)

    def wait(ticks):
        call('wait', ticks)

    def block_at(pos):
        block = call('block', *pos)
        return dict(id=block['block'], properties=dict(re.findall(r'(\w+)=(\w+)', block['state'])),
                    nbt=' '.join(command(f'data get block {xyz(pos)}')['chat']))

    paste_setup(command, wait)
    wait_loaded(call, ANCHORS)

    def paste(filename, anchor, suffix):
        return _json_reply(command(f'create schematic paste {filename} {xyz(anchor)}{suffix}'))

    target = ANCHORS[1]
    locations = [pos for pos, _, _ in placements(1)]
    barrier = locations[3]
    command(f'setblock {xyz(barrier)} minecraft:bedrock')
    before = [block_at(pos)['id'] for pos in locations]
    for filename, suffix in [(path.name, ' 4'), (path.name, ' 1 mirror'),
                             (unsupported.name, ' 1'), (path.name, ' 1')]:
        report = paste(filename, target, suffix)
        assert not report['ok'] and report['issues'], report
        assert [block_at(pos)['id'] for pos in locations] == before, report
    command(f'setblock {xyz(barrier)} minecraft:air')
    for turns, anchor in enumerate(ANCHORS):
        report = paste(path.name, anchor, f' {turns}' if turns else '')
        assert report['ok'] and report['placed'] == 8 and report['skipped_air'] == 1, report
    wait(30)
    rows = [snapshot(turns, block_at) for turns in range(4)]
    return dict(rotations=rows, output=production(command, wait, block_at))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    work = Path(tempfile.mkdtemp(prefix='schematic-rotation-', dir=ROOT / '.local'))
    path = fixture(work)
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if args.java:
        result = java_run(path)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon needs --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['sha256'] == sha and reference['create'] == PINS['create_revision']
        with NativeCheckSession(args.game, args.resources, args.ctl, None, graphics=False,
                                world='CreateRotatedSchematic', name='rotated-schematic') as session:
            result = native_run(session, path)
        result = json.loads(json.dumps(result))
        assert result == reference['result'], (result, reference['result'])
    receipt = work / 'result.json'
    receipt.write_text(json.dumps(dict(passed=True, sha256=sha, create=PINS['create_revision'],
                                       result=result), indent=2) + '\n')
    print(json.dumps(dict(result=str(receipt), rotations=4, copper_sheets=4)), flush=True)


if __name__ == '__main__':
    main()
