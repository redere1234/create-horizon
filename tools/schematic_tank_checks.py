#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Check creative paste of two separate empty Fluid Tanks in both games."""

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
from schematic_chute_checks import CASES
from schematic_rotation_checks import ROTATIONS, fixture


TANK = 'create:fluid_tank'
AIR = 'minecraft:air'
GOLD = 'minecraft:gold_block'
ANCHOR = (2711, 146, 1719)
ROOM = '2707 144 1715 2715 151 1723'
FORCE = '2704 1712 2719 1727'
SIZE = (3, 1, 1)
BOILER = dict.fromkeys(('ActiveHeat', 'Engines', 'PassiveHeat', 'Supply', 'Update', 'Whistles'), 0)
BLOCKS = [((2 * window, 0, 0), TANK,
           dict(top='true', bottom='true', shape='window' if window else 'plain'),
           {'id': (8, TANK), 'Window': (1, window), 'Height': (3, 1), 'Size': (3, 1)})
          for window in (0, 1)]


def placements(mirror, turns):
    for (x, _, _), _, props, _ in BLOCKS:
        x = -x if mirror == 'front_back' else x
        dx, dz = ((x, 0), (0, x), (-x, 0), (0, -x))[turns]
        yield (ANCHOR[0] + dx, ANCHOR[1], ANCHOR[2] + dz), props


def record(block, pos, props):
    state = {key: value.lower() for key, value in block['properties'].items()}
    nbt = block['nbt']
    assert block['id'] == TANK and state == props, (block, props)
    assert re.search(r'\bid:\s*"create:fluid_tank"', nbt), nbt
    assert field(nbt, 'TankContent') == '{}', nbt
    assert not re.search(r'\b(Controller|Uninitialized)\s*:', nbt), nbt
    boiler = field(nbt, 'Boiler')
    assert set(re.findall(r'[,{]\s*(\w+)\s*:', boiler)) == BOILER.keys(), boiler
    assert {key: number({'nbt': boiler}, key) for key in BOILER} == BOILER, boiler
    window = int(props['shape'] == 'window')
    assert tuple(number(block, key) for key in ('Window', 'Size', 'Height', 'Luminosity')) == (window, 1, 1, 0), nbt
    assert [number(block, axis) for axis in 'xyz'] == list(pos), nbt
    location = re.search(r'\bLastKnownPos:\s*\[I;\s*(-?\d+),\s*(-?\d+),\s*(-?\d+)\]', nbt)
    if location:
        assert tuple(map(int, location.groups())) == pos, nbt
    return dict(properties=props, last_known_pos=bool(location))


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
        host.command(f'tp @s {ANCHOR[0]}.5 {ANCHOR[1]+4} {ANCHOR[2]}.5')
        host.snapshot([ANCHOR], 24)
        for mirror, turns in CASES:
            host.command(f'fill {ROOM} {AIR}')
            reply = host.call('schematic', {'file': staged.name, 'origin': ANCHOR,
                                            'rotation': ROTATIONS[turns], 'mirror': mirror.upper()})
            assert reply['placed'], (mirror, turns, reply)
            states = list(placements(mirror, turns))
            positions = [pos for pos, _ in states]
            before = [host.call('block', {'pos': pos}) for pos in positions]
            first = host.call('observe_ticks', {'ticks': 1, 'positions': positions})['samples'][0]['blocks']
            frames = [before, first]
            rows = [[record(row, pos, props) for row, (pos, props) in zip(frame, states, strict=True)] for frame in frames]
            assert [row['last_known_pos'] for frame in rows for row in frame] == [False, False, True, True], rows
            results.append(rows)
            raw.append([[row['nbt'] for row in frame] for frame in frames])
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
        state = TANK + '[' + ','.join(f'{key}={value}' for key, value in props.items()) + ']'
        reply = command(f'execute if block {xyz(pos)} {state} run data get block {xyz(pos)}')
        return record(dict(id=TANK, properties=props, nbt=' '.join(reply['chat'])), pos, props)

    command(f'tp @s {ANCHOR[0]}.5 {ANCHOR[1]+4} {ANCHOR[2]}.5')
    wait_loaded(call, [ANCHOR])
    command('tick freeze')
    results, refusals = [], {}
    for mirror, turns in CASES:
        command(f'fill {ROOM} {AIR}')
        reply = paste(path.name, mirror, turns)
        assert reply['ok'] and reply['placed'] == len(BLOCKS), (mirror, turns, reply)
        states = list(placements(mirror, turns))
        before = [server_record(pos, props) for pos, props in states]
        command('tick step 1')
        call('wait', 4)
        after = [server_record(pos, props) for pos, props in states]
        for pos, props in states:
            client = call('block', *pos)
            assert client['block'] == TANK and dict(re.findall(r'(\w+)=(\w+)', client['state'])) == props, client
        results.append([before, after])

    command(f'fill {ROOM} {AIR}')
    command(f'setblock {xyz(ANCHOR)} {GOLD}')
    fluid = {'id': (8, 'minecraft:water'), 'amount': (3, 1000)}
    for key, blocks in {
        'adjacent': [BLOCKS[0], ((1, 0, 0), *BLOCKS[1][1:])],
        'filled': [BLOCKS[0], (*BLOCKS[1][:3], BLOCKS[1][3] | {'TankContent': (10, {'Fluid': (10, fluid)})})],
    }.items():
        bad = fixture(directory, blocks=blocks, size=SIZE, prefix=key)
        reply = paste(bad.name)
        assert not reply['ok'] and reply['issues'], (key, reply)
        for dx, block in enumerate((GOLD, AIR, AIR)):
            pos = (ANCHOR[0] + dx, ANCHOR[1], ANCHOR[2])
            check = command(f'execute if block {xyz(pos)} {block} run say tank_unchanged')
            assert any('tank_unchanged' in message for message in check['chat']), (key, pos, check)
        refusals[key] = reply['issues']
    return dict(placements=results, refusals=refusals)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    work = Path(tempfile.mkdtemp(prefix='schematic-tank-', dir=ROOT / '.local'))
    path = fixture(work, blocks=BLOCKS, size=SIZE, prefix='empty-fluid-tanks')
    report = dict(passed=False, create=PINS['create_revision'], sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    try:
        if args.game:
            if not all((args.resources, args.ctl, args.reference)):
                parser.error('Horizon requires --game, --resources, --ctl and --reference')
            source = json.loads(args.reference.read_text())
            assert source['passed'] and source['create'] == report['create'] and source['sha256'] == report['sha256']
            session = NativeCheckSession(args.game, args.resources, args.ctl, None, graphics=False,
                                         world='SchematicTank', name='schematic-tank-native')
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
