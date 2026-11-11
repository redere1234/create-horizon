#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Place identical schematic bytes in both clients with both mirrors and all turns."""

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
from schematic_rotation_checks import BLOCKS, GOLD, ROTATIONS, fixture


AIR = 'minecraft:air'
FORCE = '1504 688 1551 735'
ROOM = '1505 86 701 1550 90 728'
CASES = [(mirror, turns, (x, 86, z))
         for mirror, z in [('left_right', 706), ('front_back', 722)]
         for turns, x in enumerate((1510, 1522, 1534, 1546))]
CARGO = BLOCKS + [
    ((0, 2, 3), 'create:creative_motor', {'facing': 'north'},
     {'id': (8, 'create:motor'), 'ScrollValue': (3, 24), 'Speed': (5, 999)}),
    ((0, 2, 2), 'create:shaft', {'axis': 'z', 'waterlogged': 'false'},
     {'id': (8, 'create:simple_kinetic')}),
]
FACINGS = {'north': (0, -1), 'east': (1, 0), 'south': (0, 1), 'west': (-1, 0)}


def transform(mirror, turns, x, z):
    if mirror == 'left_right':
        z = -z
    else:
        x = -x
    return [(x, z), (-z, x), (-x, -z), (z, -x)][turns]


def facing(mirror, turns, source):
    wanted = transform(mirror, turns, *FACINGS[source])
    return next(name for name, vector in FACINGS.items() if vector == wanted)


def placements(mirror, turns, anchor):
    for (x, y, z), name, source, _ in CARGO:
        dx, dz = transform(mirror, turns, x, z)
        state = dict(source)
        if 'facing' in state:
            state['facing'] = facing(mirror, turns, state['facing'])
        if state.get('axis') in ('x', 'z') and turns % 2:
            state['axis'] = 'z' if state['axis'] == 'x' else 'x'
        if 'waterlogged' in state:
            state['waterlogged'] = 'false'
        yield (anchor[0] + dx, anchor[1] + y, anchor[2] + dz), name, state


def setup(command, wait):
    command('gamemode creative')
    command('tp @s 1528.5 92 714.5')
    command(f'forceload add {FORCE}')
    wait(40)
    command(f'fill {ROOM} {AIR}')
    command('fill 1505 85 701 1550 85 728 minecraft:smooth_stone')
    for case in CASES:
        air = list(placements(*case))[8][0]
        command(f'setblock {xyz(air)} {GOLD}')


def snapshot(case, block_at):
    mirror, turns, _ = case
    main_facing = facing(mirror, turns, 'east')
    extra_facing = facing(mirror, turns, 'north')
    rows = []
    for index, (pos, name, state) in enumerate(placements(*case)):
        actual = block_at(pos)
        identifier = GOLD if name == AIR else name
        assert actual['id'] == identifier, (case, pos, actual, identifier)
        properties = {key: actual['properties'][key] for key in state}
        assert properties == state, (case, pos, properties, state)
        row = dict(pos=pos, id=identifier, properties=properties)
        if index < 4 or index >= 9:
            amount, direction = (48, main_facing) if index < 4 else (24, extra_facing)
            wanted = amount if direction in ('east', 'south') else -amount
            row['rpm'] = number(actual, 'Speed')
            assert row['rpm'] == wanted, (case, row, wanted, actual)
        if index in (0, 9):
            row['setting'] = number(actual, 'ScrollValue')
            assert row['setting'] == (48 if index == 0 else 24), (case, row)
        rows.append(row)
    return rows


def production(command, wait, block_at):
    depots = [list(placements(*case))[4][0] for case in CASES]
    for pos in depots:
        command(f'data merge block {xyz(pos)} '
                '{HeldItem:{Item:{id:"minecraft:copper_ingot",count:1},Pos:0.5f,PrevPos:0.5f,InDirection:1}}')
    wait(180)
    result = []
    for pos in depots:
        held = field(block_at(pos)['nbt'], 'HeldItem')
        assert 'create:copper_sheet' in held and number({'nbt': held}, 'count') == 1, (pos, held)
        result.append('create:copper_sheet')
    return result


def java_run(path):
    host = Original()
    assert json.loads((BASE / 'manifest.json').read_text())['create_sha256'] == CREATE_SHA256
    state = host.call('state', {})
    if state.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        state = host.call('state', {})
    assert state['ready'] and state['data_version'] == 3955, state
    name = stage_schematic(BASE, path)['file']
    host.call('tick', {'frozen': True})

    def wait(ticks):
        host.call('observe_ticks', {'ticks': ticks, 'positions': [anchor for _, _, anchor in CASES]})

    def block_at(pos):
        return host.call('block', {'pos': pos})

    try:
        setup(host.command, wait)
        for mirror, turns, anchor in CASES:
            reply = host.call('schematic', {'file': name, 'origin': anchor,
                                          'rotation': ROTATIONS[turns], 'mirror': mirror.upper()})
            assert reply['placed'], reply
        wait(30)
        placements = [snapshot(case, block_at) for case in CASES]
        return dict(placements=placements, outputs=production(host.command, wait, block_at))
    finally:
        host.command(f'fill {ROOM} {AIR}')
        host.command(f'forceload remove {FORCE}')
        host.call('tick', {'frozen': state['server']['frozen']})
        (path.parent / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session, path):
    directory = session.scratch / 'schematics'
    directory.mkdir()
    shutil.copy2(path, directory / path.name)
    unsupported = fixture(directory, unsupported=True, blocks=CARGO, size=(4, 3, 4), prefix='mirrored')
    call = session.call

    def command(text):
        return call('command', text)

    def wait(ticks):
        call('wait', ticks)

    def block_at(pos):
        block = call('block', *pos)
        return dict(id=block['block'], properties=dict(re.findall(r'(\w+)=(\w+)', block['state'])),
                    nbt=' '.join(command(f'data get block {xyz(pos)}')['chat']))

    def paste(filename, mirror, turns, anchor):
        return _json_reply(command(f'create schematic paste {filename} {xyz(anchor)} {turns} {mirror}'))

    setup(command, wait)
    wait_loaded(call, [anchor for _, _, anchor in CASES])
    mirror, turns, anchor = CASES[1]
    positions = [pos for pos, _, _ in placements(mirror, turns, anchor)]
    barrier = positions[3]
    command(f'setblock {xyz(barrier)} minecraft:bedrock')
    wait(3)
    before = [block_at(pos) for pos in positions]
    assert before[3]['id'] == 'minecraft:bedrock', before
    refused = {}
    for reason, filename, mode in [
        ('unknown_mirror', path.name, 'sideways'),
        ('unsupported_palette', unsupported.name, mirror),
        ('blocked_target', path.name, mirror),
    ]:
        reply = paste(filename, mode, turns, anchor)
        assert not reply['ok'] and reply['issues'], reply
        assert [block_at(pos) for pos in positions] == before, reply
        refused[reason] = reply['issues']
    command(f'setblock {xyz(barrier)} {AIR}')
    for mirror, turns, anchor in CASES:
        reply = paste(path.name, mirror, turns, anchor)
        assert reply['ok'] and reply['placed'] == 10 and reply['skipped_air'] == 1, reply
        assert reply['mirror'] == mirror and reply.get('quarter_turns', 0) == turns, reply
    wait(30)
    rows = [snapshot(case, block_at) for case in CASES]
    return dict(placements=rows, outputs=production(command, wait, block_at)), refused


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    work = Path(tempfile.mkdtemp(prefix='schematic-mirror-', dir=ROOT / '.local'))
    path = fixture(work, blocks=CARGO, size=(4, 3, 4), prefix='mirrored')
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    report = dict(passed=False, sha256=sha, create=PINS['create_revision'])
    session = None
    print(work, flush=True)
    try:
        if args.java:
            report['result'] = java_run(path)
        else:
            if not all((args.game, args.resources, args.ctl, args.reference)):
                parser.error('Horizon needs --game, --resources, --ctl and --reference')
            expected = json.loads(args.reference.read_text())
            assert expected['passed'] and expected['sha256'] == sha and expected['create'] == report['create']
            session = NativeCheckSession(args.game, args.resources, args.ctl, None, graphics=False,
                                         world='CreateMirroredSchematic', name='mirrored-schematic')
            with session:
                result, report['refusals_without_writes'] = native_run(session, path)
                report['result'] = json.loads(json.dumps(result))
            assert report['result'] == expected['result'], (report['result'], expected['result'])
        report['passed'] = True
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        if session:
            shutil.rmtree(session.resources, ignore_errors=True)
            if session.resources.exists():
                shutil.rmtree(session.resources)
    print(json.dumps(dict(result=str(work / 'result.json'), placements=len(CASES))), flush=True)


if __name__ == '__main__':
    main()
