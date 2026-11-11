#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare ordinary empty Deployer schematic paste for all horizontal transforms."""

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


BLOCK = 'create:deployer'
AIR = 'minecraft:air'
GOLD = 'minecraft:gold_block'
ROOM = '2032 108 1284 2070 115 1316'
FORCE = '2032 1280 2079 1327'
CAMERA = (2051.5, 115, 1300.5)
FACINGS = ('north', 'east', 'south', 'west', 'up', 'down')
MIRRORS = ('none', 'left_right', 'front_back')
CASES = [(mirror, turns, (2036 + 10 * turns, 110, 1290 + 10 * row))
         for row, mirror in enumerate(MIRRORS) for turns in range(4)]
SIZE = (4, 2, 4)
EMPTY = (9, (10, []))
SAFE = {'id': (8, BLOCK), 'Mode': (8, 'USE'), 'Filter': (10, {}),
        'FilterAmount': (3, 64), 'UpTo': (1, 1)}
FULL = SAFE | {'State': (8, 'WAITING'), 'Timer': (3, 500), 'Speed': (5, 0), 'Powered': (1, 0),
               'Inventory': EMPTY, 'HeldItem': (10, {}), 'Overflow': EMPTY}
SOURCE_DATA = (FULL, SAFE | {'FilterAmount': (3, 23), 'UpTo': (1, 0)}, None)
STICK = {'id': (8, 'minecraft:stick'), 'count': (3, 1)}
BLOCKS = [((index % 4, (index // 4) % 2, index // 4 + 1), BLOCK,
           {'facing': facing, 'axis_along_first': str(axis).lower()}, SOURCE_DATA[index % len(SOURCE_DATA)])
          for index, (facing, axis) in enumerate((f, a) for f in FACINGS for a in (False, True))]


def placements(case):
    mirror, turns, anchor = case
    for (x, y, z), _, props, data in BLOCKS:
        if mirror == 'left_right':
            z = -z
        if mirror == 'front_back':
            x = -x
        dx, dz = ((x, z), (-z, x), (-x, -z), (z, -x))[turns]
        facing = props['facing']
        if facing in FACINGS[:4]:
            flip = mirror == 'left_right' and facing in ('north', 'south') or (
                mirror == 'front_back' and facing in ('east', 'west'))
            facing = FACINGS[(FACINGS.index(facing) + 2 * flip + turns) % 4]
        axis = (props['axis_along_first'] == 'true') ^ bool(turns % 2)
        filters = data or SAFE
        yield ((anchor[0] + dx, anchor[1] + y, anchor[2] + dz),
               dict(facing=facing, axis_along_first=str(axis).lower()),
               dict(amount=filters['FilterAmount'][1], up_to=filters['UpTo'][1]))


def safe_deployer(nbt, filters):
    assert re.search(r'\bMode:\s*"USE"', nbt), nbt
    assert re.search(r'\bState:\s*"WAITING"', nbt), nbt
    assert all(number({'nbt': nbt}, key, 0) == 0 for key in ('Speed', 'Timer', 'Powered')), nbt
    assert re.sub(r'\s+', '', field(nbt, 'Filter')) == '{}', nbt
    assert number({'nbt': nbt}, 'FilterAmount') == filters['amount'], nbt
    assert number({'nbt': nbt}, 'UpTo') == filters['up_to'], nbt
    for key, empty in (('Inventory', '[]'), ('Overflow', '[]'), ('HeldItem', '{}')):
        if re.search(r'\b' + key + r'\s*:', nbt):
            assert re.sub(r'\s+', '', field(nbt, key)) == empty, nbt
    assert not re.search(r'\b(Source|Network|Sequence|Owner)\s*:', nbt), nbt
    return dict(mode='USE', state='WAITING', **filters)


def java_run(work, path):
    host = Original()
    assert json.loads((BASE / 'manifest.json').read_text())['create_sha256'] == CREATE_SHA256
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    stage = Path(stage_schematic(BASE, path)['staged'])
    try:
        host.command('gamemode creative')
        host.command('tp @s ' + xyz(CAMERA))
        host.command('forceload add ' + FORCE)
        host.snapshot([anchor for _, _, anchor in CASES], 28)
        host.command('fill ' + ROOM + ' ' + AIR)
        for mirror, turns, anchor in CASES:
            result = host.call('schematic', {'file': stage.name, 'origin': anchor,
                                             'rotation': ROTATIONS[turns], 'mirror': mirror.upper()})
            assert result['placed'], (mirror, turns, result)
        rows = []
        for case in CASES:
            for pos, props, filters in placements(case):
                actual = host.call('block', {'pos': pos})
                state = {key: value.lower() for key, value in actual['properties'].items()}
                assert actual['id'] == BLOCK and state == props, (case, pos, actual, props)
                rows.append(dict(pos=list(pos), properties=props, **safe_deployer(actual['nbt'], filters)))
        return rows
    finally:
        host.command('fill ' + ROOM + ' ' + AIR)
        host.command('forceload remove ' + FORCE)
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        stage.unlink()
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session, path, expected):
    directory = session.scratch / 'schematics'
    directory.mkdir()
    shutil.copy2(path, directory / path.name)
    call = session.call

    def command(text):
        return call('command', text)

    def paste(filename, case):
        mirror, turns, anchor = case
        return _json_reply(command(f'create schematic paste {filename} {xyz(anchor)} {turns} {mirror}'))

    command('gamemode creative')
    command('tp @s ' + xyz(CAMERA))
    columns = {(pos[0] // 16, pos[2] // 16): pos for case in CASES for pos, _, _ in placements(case)}
    wait_loaded(call, columns.values())
    command('fill ' + ROOM + ' ' + AIR)
    case = CASES[-1]
    locations = [pos for pos, _, _ in placements(case)]
    command(f'setblock {xyz(locations[0])} {GOLD}')
    call('wait', 3)
    refusals = {
        'Mode': (8, 'PUNCH'), 'State': (8, 'EXPANDING'), 'Powered': (1, 1),
        'HeldItem': (10, STICK), 'Inventory': (9, (10, [STICK | {'Slot': (1, 0)}])),
        'Overflow': (9, (10, [STICK])), 'Filter': (10, STICK), 'Speed': (5, 32),
        'Unknown': (1, 1),
    }
    issues = {}
    for field_name, value in refusals.items():
        invalid = BLOCKS[:-1] + [(*BLOCKS[-1][:3], FULL | {field_name: value})]
        bad = fixture(directory, blocks=invalid, size=SIZE, prefix=field_name.lower())
        result = paste(bad.name, case)
        assert not result['ok'] and any(field_name in str(issue) for issue in result['issues']), result
        issues[field_name] = result['issues']
        assert [call('block', *pos)['block'] for pos in locations] == [GOLD] + [AIR] * (len(locations) - 1)
    command(f'setblock {xyz(locations[0])} {AIR}')

    # A valid schematic must also protect an unsafe, differently oriented
    # destination Deployer before touching an unrelated prior write.
    overwrite_case = ('none', 0, (2036, 113, 1290))
    guard, existing = overwrite_case[2], (2037, 113, 1290)
    overwrite = fixture(directory, blocks=[
        ((0, 0, 0), 'minecraft:stone', {}, None),
        ((1, 0, 0), BLOCK, {'facing': 'north', 'axis_along_first': 'false'}, SAFE),
    ], size=(2, 1, 1), prefix='destination')
    command(f'setblock {xyz(guard)} {GOLD}')
    old_state = f'{BLOCK}[facing=west,axis_along_first=false]'
    for name, raw, expected_nbt in [
        ('occupied', '{Inventory:[{Slot:0b,id:"minecraft:oak_planks",count:1}]}', 'minecraft:oak_planks'),
        ('active', '{Mode:"USE",State:"EXPANDING",Timer:488}', 'EXPANDING'),
    ]:
        command(f'setblock {xyz(existing)} {AIR}')
        command(f'setblock {xyz(existing)} {old_state}{raw}')
        call('wait', 3)
        result = paste(overwrite.name, overwrite_case)
        assert not result['ok'] and any('occupied or active Deployer' in issue['message']
                                        for issue in result['issues']), result
        issues[f'destination_{name}'] = result['issues']
        assert call('block', *guard)['block'] == GOLD
        state = call('block', *existing)['state']
        assert 'facing=west' in state and 'axis_along_first=false' in state, state
        nbt = ' '.join(command(f'data get block {xyz(existing)}')['chat'])
        assert expected_nbt in nbt, nbt
    command(f'setblock {xyz(existing)} {AIR}')
    command(f'setblock {xyz(guard)} {AIR}')

    for case in CASES:
        result = paste(path.name, case)
        assert result['ok'] and result['placed'] == len(BLOCKS), result
    repeated = paste(path.name, CASES[0])
    assert repeated['ok'] and repeated['placed'] == 0, repeated
    call('wait', 6)
    observed = []
    for case in CASES:
        for pos, props, filters in placements(case):
            actual = call('block', *pos)
            state = dict(re.findall(r'(\w+)=(\w+)', actual['state']))
            assert actual['block'] == BLOCK and state == props, (case, pos, actual)
            nbt = ' '.join(command(f'data get block {xyz(pos)}')['chat'])
            observed.append(dict(pos=list(pos), properties=props, **safe_deployer(nbt, filters)))
    assert observed == expected
    return dict(placements=len(observed), refusals=issues, scratch=str(session.scratch))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    work = Path(tempfile.mkdtemp(prefix='schematic-deployer-', dir=ROOT / '.local'))
    path = fixture(work, blocks=BLOCKS, size=SIZE, prefix='deployers')
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    report = dict(passed=False, create=PINS['create_revision'], sha256=sha)
    print(work, flush=True)
    try:
        if args.java:
            report['placements'] = java_run(work, path)
        else:
            if not all((args.game, args.resources, args.ctl, args.reference)):
                parser.error('Horizon needs --game, --resources, --ctl and --reference')
            expected = json.loads(args.reference.read_text())
            assert expected['passed'] and expected['sha256'] == sha and expected['create'] == report['create']
            session = NativeCheckSession(args.game, args.resources, args.ctl, None, graphics=False,
                                         world='DeployerSchematic', name='deployer-schematic-native')
            try:
                with session:
                    report.update(native_run(session, path, expected['placements']))
            finally:
                for folder in (session.resources, session.scratch / '.horizon-cache', session.scratch / 'horizon-mods'):
                    shutil.rmtree(folder, ignore_errors=True)
        report['passed'] = True
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        result = work / 'result.json'
        result.write_text(json.dumps(report, indent=2) + '\n')
        print(result, flush=True)


if __name__ == '__main__':
    main()
