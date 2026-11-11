#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare real singleton Fluid Tank bucket use, window, comparator and save."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile
import time
from zipfile import ZipFile

from burner_heat_java_checks import field, number
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from funnel_checks import block, put, text
from native_check_session import NativeCheckSession, wait_loaded
import reference_java as java


TANK = 'create:fluid_tank'
POS = (2408, 168, 990)
COMPARATOR = (2408, 168, 989)
WIRE = (2408, 168, 988)
SPILL = (2408, 168, 991)
COLUMN = '2400 976 2415 991'
AREA = '2404 167 986 2412 173 993'
FEET = (2408.5, 168, 992.65)
AIM = (2408.5, 168.75, 991)
BUCKET = 'minecraft:bucket'
WATER = 'minecraft:water_bucket'
LAVA = 'minecraft:lava_bucket'


def click(host, work, name, held, *, feet=FEET, aim=AIM, pos=POS, face='south'):
    host.command(f'item replace entity @s weapon.mainhand with {held}')
    if isinstance(host, Native):
        call = host.session.call
        host.command(f'tp @s {xyz(feet)}')
        call('look-at', *aim)
        call('wait', 4)
        hit = call('looking-at')['block']
        assert hit['pos'] == list(pos) and hit['face'] == face, hit
        call('mouse', 'right', 'click')
        call('wait', 6)
    else:
        host.call('camera', {'position': feet, 'target': aim})
        host.call('capture', {'name': f'{work.name}/{name}-aim.png', 'frames': 4})
        hit = host.call('state', {})['hit']
        assert hit['pos'] == list(pos) and hit['face'] == face, hit
        host.call('input', {'key': 'use', 'down': True})
        try:
            host.call('capture', {'name': f'{work.name}/{name}-tap.png', 'frames': 4})
        finally:
            host.call('input', {'key': 'use', 'down': False})
        host.call('capture', {'name': f'{work.name}/{name}-after.png', 'frames': 6})


def snapshot(host):
    tank = block(host, POS)
    assert tank['id'] == TANK, tank
    content = field(tank['nbt'], 'TankContent')
    fluid = re.search(r'\bid\s*:\s*"([^"]+)"', content)
    hand = re.search(r'\bid\s*:\s*"([^"]+)"', text(host, 'data get entity @s SelectedItem'))
    known_pos = re.search(r'\bLastKnownPos:\s*\[I;\s*(-?\d+),\s*(-?\d+),\s*(-?\d+)\]', tank['nbt'])
    assert known_pos and tuple(map(int, known_pos.groups())) == POS, tank
    return dict(state={k: v.lower() for k, v in tank['properties'].items()},
                fluid=fluid[1] if fluid else None, amount=int(number({'nbt': content}, 'amount', 0)),
                window=int(number(tank, 'Window')), size=int(number(tank, 'Size')),
                height=int(number(tank, 'Height')), luminosity=int(number(tank, 'Luminosity')),
                comparator=int(block(host, WIRE)['properties']['power']),
                held=hand[1] if hand else None, spill=block(host, SPILL)['id'])


def settle(host, ticks=5):
    if isinstance(host, Native):
        host.session.call('wait', ticks)
    else:
        host.call('observe_ticks', {'positions': [POS], 'ticks': ticks})


def setup(host, work):
    cmd = host.command
    cmd('gamemode creative')
    cmd('item replace entity @s weapon.mainhand with minecraft:air')
    cmd(f'fill {AREA} minecraft:air')
    cmd('fill 2404 167 986 2412 167 993 minecraft:smooth_stone')
    put(cmd, POS, TANK)
    put(cmd, COMPARATOR, 'minecraft:comparator[facing=south]')
    put(cmd, WIRE, 'minecraft:redstone_wire')
    settle(host, 8)
    raw = block(host, POS)['nbt']
    (work / 'initial-nbt.txt').write_text(raw + '\n')
    return raw


def scenarios(host, work):
    setup(host, work)
    phases = {}

    def take(name):
        settle(host)
        phases[name] = snapshot(host)
        (work / 'observed.json').write_text(json.dumps(phases, indent=2) + '\n')
        if isinstance(host, Native) and name in ('lava', 'hide', 'show', 'almost-full'):
            host.session.call('key', 'f1', 'tap')
            host.session.call('wait', 3)
            host.session.call('screenshot', work / f'{name}.png')
            host.session.call('key', 'f1', 'tap')

    take('empty')
    for name, item in [('water', WATER), ('incompatible', LAVA), ('drain-water', BUCKET),
                       ('lava', LAVA), ('hide', 'create:wrench'), ('show', 'create:wrench')]:
        click(host, work, name, item)
        take(name)
    (work / 'lava-nbt.txt').write_text(block(host, POS)['nbt'] + '\n')
    host.command('gamemode survival')
    click(host, work, 'survival-empty', BUCKET)
    take('survival-empty')
    click(host, work, 'survival-water', WATER)
    take('survival-water')
    put(host.command, SPILL, 'minecraft:air')
    host.command('gamemode creative')
    click(host, work, 'drain-lava', BUCKET)
    take('drain-lava')
    # Horizon's generic data command does not notify comparators. Exercise
    # the normal bucket action on both sides after seeding the fractional fill.
    host.command(f'data merge block {xyz(POS)} {{TankContent:{{Fluid:{{id:"minecraft:water",amount:6500}}}}}}')
    click(host, work, 'finish-pour', WATER)
    take('almost-full')
    click(host, work, 'would-overflow', WATER)
    take('would-overflow')
    return phases


def verify(phases):
    expected = {
        'empty': (None, 0, 0, 0, 1),
        'water': ('water', 1000, 2, 0, 1),
        'incompatible': ('water', 1000, 2, 0, 1),
        'drain-water': (None, 0, 0, 0, 1),
        'lava': ('lava', 1000, 2, 12, 1),
        'hide': ('lava', 1000, 2, 12, 0),
        'show': ('lava', 1000, 2, 12, 1),
        'survival-empty': ('lava', 1000, 2, 12, 1),
        'survival-water': ('lava', 1000, 2, 12, 1),
        'drain-lava': (None, 0, 0, 0, 1),
        'almost-full': ('water', 7500, 14, 0, 1),
        'would-overflow': ('water', 7500, 14, 0, 1),
    }
    for name, row in phases.items():
        fluid, amount, comparator, luminosity, window = expected[name]
        assert row['state'] == dict(top='true', bottom='true', shape='window' if window else 'plain'), (name, row)
        assert (row['fluid'], row['amount'], row['comparator'], row['luminosity'], row['window']) == (
            f'minecraft:{fluid}' if fluid else None, amount, comparator, luminosity, window), (name, row)
        assert row['size'] == row['height'] == 1, (name, row)
    assert phases['water']['held'] == WATER and phases['incompatible']['held'] == LAVA, phases
    assert phases['drain-water']['held'] == phases['drain-lava']['held'] == BUCKET, phases
    assert phases['survival-empty']['held'] == phases['survival-water']['held'] == BUCKET, phases
    assert phases['survival-water']['spill'] == 'minecraft:water', phases


def original(work, cold):
    host = Original()
    assert json.loads((java.BASE / 'manifest.json').read_text())['create_sha256'] == java.CREATE_SHA256
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {COLUMN}')
        settle(host, 20)
        phases = scenarios(host, work)
        if cold:
            host.call('quit', {})
            deadline = time.monotonic() + 60
            while java.process_alive(java.BASE):
                if time.monotonic() >= deadline:
                    raise RuntimeError('The private Java client did not save and exit')
                time.sleep(.2)
            after = java.launch(java.BASE)
            assert after['ready'], after
            host.call('tick', {'frozen': True})
            settle(host, 8)
            assert snapshot(host) == phases['would-overflow']
        return phases
    finally:
        host.command('gamemode creative')
        host.command('item replace entity @s weapon.mainhand with minecraft:air')
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {COLUMN}')
        host.call('camera', {'position': initial['position'], 'yaw': initial['yaw'], 'pitch': initial['pitch']})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_admission(host, work):
    above = POS[0], POS[1] + 1, POS[2]
    click(host, work, 'blocked-tower', TANK, aim=(POS[0] + .5, POS[1] + 1, POS[2] + .5), face='up')
    assert block(host, above)['id'] == 'minecraft:air'
    assert snapshot(host)['amount'] == 7500

    click(host, work, 'separate-neighbor', TANK)
    assert block(host, SPILL)['id'] == TANK
    assert number(block(host, SPILL), 'Size') == 1
    assert snapshot(host)['amount'] == 7500

    adjacent = POS[0] + 1, POS[1], POS[2]
    fourth = adjacent[0], adjacent[1], adjacent[2] + 1
    put(host.command, adjacent, TANK)
    click(host, work, 'blocked-square', TANK, feet=(FEET[0] + 1, *FEET[1:]),
          aim=(AIM[0] + 1, *AIM[1:]), pos=adjacent)
    assert block(host, fourth)['id'] == 'minecraft:air'
    assert snapshot(host)['amount'] == 7500

    put(host.command, SPILL, 'minecraft:air')
    host.command(f'data merge block {xyz(POS)} {{Size:2,Controller:[I;2407,168,990],FutureData:{{keep:37}}}}')
    before = block(host, POS)
    for name, held in [('opaque-pour', WATER), ('opaque-extract', BUCKET), ('opaque-window', 'create:wrench')]:
        click(host, work, name, held)
        assert block(host, POS) == before, (name, before, block(host, POS))
    return ['vertical-refused', 'horizontal-singletons', 'wider-square-refused', 'opaque-save-preserved']


def native_resources(session, jar):
    receipts = list((session.scratch / '.horizon-cache/create-assets/imports').glob('*/import.json'))
    if jar is None:
        assert not receipts, receipts
        bundle = session.scratch / 'horizon-mods/.create-native-content'
        model = bundle / 'assets/create/models/block/fluid_tank/block_single_window.json'
        textures = json.loads(model.read_text())['textures']
        assert set(textures.values()) == {'minecraft:block/copper_block', 'minecraft:block/glass', '#frame'}
        return {'fallback': True}
    assert len(receipts) == 1, receipts
    pack = receipts[0].parent / 'pack'
    paths = {'assets/create/blockstates/fluid_tank.json', 'assets/create/models/item/fluid_tank.json',
             *('assets/create/models/block/fluid_tank/block_single' + suffix + '.json' for suffix in ('', '_window'))}
    with ZipFile(jar) as archive:
        for model in [p for p in paths if '/models/block/' in p]:
            for texture in json.loads(archive.read(model))['textures'].values():
                if texture.startswith('create:'):
                    paths.add('assets/create/textures/' + texture.removeprefix('create:') + '.png')
        for path in paths:
            assert (pack / path).read_bytes() == archive.read(path), path
    return {'original_files': sorted(paths)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--cold', action='store_true', help='Also restart the private Java reference')
    for flag in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    report = dict(passed=True, create=PINS['create_revision'])
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='fluid-tank-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        phases = original(work, args.cold)
        report['cold'] = args.cold
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='fluid-tank-native', world='CreateFluidTank')
        work = session.scratch
        print(work, flush=True)
        try:
            with session:
                session.call('command', f'tp @s {xyz(FEET)}')
                wait_loaded(session.call, [POS, (2408, 168, 993)])
                phases = scenarios(Native(session), work)
                report['assets'] = native_resources(session, args.create_jar)
                session.restart()
                wait_loaded(session.call, [POS])
                assert snapshot(Native(session)) == phases['would-overflow']
                report['cold'] = True
                report['admission'] = native_admission(Native(session), work)
        finally:
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        for phase, observed in phases.items():
            expected = reference['phases'][phase]
            assert observed == expected, (phase, observed, expected)
    verify(phases)
    path = work / 'result.json'
    path.write_text(json.dumps(dict(report, phases=phases), indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
