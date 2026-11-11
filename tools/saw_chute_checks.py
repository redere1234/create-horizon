#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare direct Saw-to-Chute and Saw-to-Funnel transfer and a native restart."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field, items, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession


X, Y = 2095, 121
LANES = dict(plain=1300, match=1303, wrong=1306, powered=1309, funnel=1312)
ROOM = '2093 119 1298 2098 127 1313'
FORCE = '2093 1298 2098 1313'
MARK = 'saw_chute_probe'
CARGO = 'minecraft:andesite'
DROPS = '@e[type=minecraft:item,x=2093,y=119,z=1298,dx=5,dy=8,dz=15]'


def points(z):
    return (X, Y, z), (X + 1, Y, z), (X + 1, Y - 1, z)


PROBES = [pos for z in LANES.values() for pos in points(z)]


def configure(command, advance, *, native=False):
    command(f'fill {ROOM} minecraft:air')
    command(f'kill {DROPS}')
    for name, z in LANES.items():
        saw, chute, chest = points(z)
        command(f'setblock {xyz(chest)} minecraft:chest[facing=south]')
        command(f'setblock {xyz(saw)} create:mechanical_saw[facing=up,axis_along_first=false]')
        if name == 'plain':
            command(f'setblock {xyz(chute)} create:chute[facing=down,shape=window]')
        elif name == 'funnel':
            command(f'setblock {X+1} {Y} {z+1} minecraft:redstone_block')
            command(f'setblock {xyz(chute)} create:brass_funnel[facing=up,extracting=false,powered=true]'
                    f'{{Filter:{{id:"{CARGO}",count:1}}}}')
        else:
            filtered = 'minecraft:granite' if name == 'wrong' else CARGO
            command(f'setblock {xyz(chute)} create:smart_chute[powered={str(name == "powered").lower()}]'
                    f'{{Filter:{{id:"{filtered}",count:1}},FilterAmount:16,UpTo:0b}}')
            if name == 'powered':
                command(f'setblock {X+1} {Y} {z+1} minecraft:redstone_block')
    advance(22)
    for marker, z in enumerate(LANES.values(), 1):
        saw, _, _ = points(z)
        stack = f'id:"{CARGO}",count:3,components:{{"minecraft:custom_data":{{{MARK}:{marker}}}}}'
        live = f',Items:[{{Slot:0b,{stack}}}]' if native else ''
        command(f'data merge block {xyz(saw)} {{Inventory:{{Size:32,Items:[{{Slot:0,{stack}}}],'
                f'ProcessingTime:0f,RecipeTime:20f,AppliedRecipe:1b}}{live}}}')
    # The source reloads a Saw's kinetic fields on block-NBT merge. Seed the
    # ready output before connecting any source, in both clients.
    for z in LANES.values():
        command(f'setblock {X} {Y} {z-1} create:creative_motor[facing=south]{{ScrollValue:128}}')


def release(command):
    z = LANES['wrong']
    command(f'data merge block {xyz(points(z)[1])} {{Filter:{{id:"{CARGO}",count:1}}}}')
    command(f'setblock {X+1} {Y} {LANES["powered"]+1} minecraft:air')
    command(f'setblock {X+1} {Y} {LANES["funnel"]+1} minecraft:air')


def snapshot(raw):
    rows = {}
    for name, saw, chute, chest in zip(LANES, raw[::3], raw[1::3], raw[2::3], strict=True):
        pairs = ((saw, 'Inventory'), (chute, 'Item'), (chest, 'Items'))
        inventories = [field(nbt, key) if f'{key}:' in nbt else '{}' for nbt, key in pairs]
        parts = [items(nbt, key) if f'{key}:' in nbt else {} for nbt, key in pairs]
        for inventory, payload in zip(inventories, parts, strict=True):
            if payload:
                assert payload == {CARGO: 3}, (name, inventory, payload)
        rows[name] = dict(cargo=[number({'nbt': inv}, MARK, 0) for inv in inventories],
                          chute_pos=number({'nbt': chute}, 'ItemPosition', 0) if parts[1] else None)
    return rows


def verify(warm, cold, resumed):
    assert cold == warm[-1], (cold, warm[-1])
    for marker, name in enumerate(LANES, 1):
        saw, chute, chest = [marker, 0, 0], [0, marker, 0], [0, 0, marker]
        for row in warm + resumed:
            assert row[name]['cargo'] in (saw, chute, chest), (name, row[name])
        if name in ('plain', 'match'):
            assert any(row[name]['cargo'] == chute for row in warm)
            assert cold[name]['cargo'] == chest
        else:
            assert all(row[name]['cargo'] == saw for row in warm)
            if name == 'funnel':
                assert resumed[0][name]['cargo'] == chest
                assert all(row[name]['cargo'] != chute for row in resumed)
            else:
                assert any(row[name]['cargo'] == chute for row in resumed)
        assert resumed[-1][name]['cargo'] == chest, resumed[-1]


def java(work):
    host = Original()
    initial = host.call('state', {})
    if initial.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955

    def advance(ticks):
        return host.call('observe_ticks', {'positions': PROBES, 'ticks': ticks})['samples']

    def rows(ticks):
        return [snapshot([block['nbt'] for block in sample['blocks']]) for sample in advance(ticks)]

    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {FORCE}')
        host.command('tp @s 2095.5 125 1304.5')
        advance(23)
        configure(host.command, advance)
        warm = rows(24)
        release(host.command)
        resumed = rows(24)
        return warm, warm[-1], resumed
    finally:
        host.command(f'kill {DROPS}')
        host.command(f'fill {ROOM} minecraft:air')
        host.command(f'forceload remove {FORCE}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session):
    def read(batch, label):
        values = batch.run(session, label)
        return [snapshot(values[i:i+len(PROBES)]) for i in range(0, len(values), len(PROBES))]

    def sample(batch, ticks):
        for _ in range(ticks):
            batch.tick()
            for pos in PROBES:
                batch.data(pos)

    before = Batch()
    before.load((2095, 124, 1304))
    configure(before.command, before.tick, native=True)
    sample(before, 24)
    warm = read(before, 'warm')

    after = Batch()
    after.load((2095, 124, 1304))
    for pos in PROBES:
        after.data(pos)
    release(after.command)
    sample(after, 24)
    cold, *resumed = read(after, 'resume')
    return warm, cold, resumed


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
        session = NativeCheckSession(args.game, args.resources, args.ctl, None, graphics=False,
                                     name='saw-chute-native', world='SawChute')
        work = session.scratch
        try:
            warm, cold, resumed = native(session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    else:
        work = Path(tempfile.mkdtemp(prefix='saw-chute-java-', dir=ROOT / '.local'))
        warm, cold, resumed = java(work)
    path = work / 'result.json'
    report = dict(passed=False, create=PINS['create_revision'], warm=warm, cold=cold, resumed=resumed)
    path.write_text(json.dumps(report, indent=2) + '\n')
    verify(warm, cold, resumed)
    if args.game:
        for label in ('warm', 'resumed'):
            for tick, (row, expected) in enumerate(zip(report[label], reference[label], strict=True), 1):
                assert row == expected, (label, tick, row, expected)
    report['passed'] = True
    path.write_text(json.dumps(report, indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
