#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare ordinary shaped/shapeless recipes and container remainders through Mechanical Crafters."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field, items, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from crafter_java_checks import phase
from funnel_checks import click, put, text
from native_check_session import NativeCheckSession
import reference_java


X, Y, Z = 2387, 151, 942
AREA = '2384 147 938 2393 157 949'
TICKET = '2384 928 2399 959'
DROPS = '@e[type=minecraft:item,x=2384,y=147,z=938,dx=9,dy=10,dz=11]'
INGREDIENTS = {
    ' ': 'create:crafter_slot_cover', 'P': 'minecraft:oak_planks', 'S': 'minecraft:stick',
    'L': 'minecraft:leather', 'R': 'minecraft:paper', 'M': 'minecraft:milk_bucket',
    'U': 'minecraft:sugar', 'E': 'minecraft:egg', 'W': 'minecraft:wheat',
}
CASES = {
    'mirror_axe': (('PP', 'SP', 'S '), 'minecraft:wooden_axe', False),
    'shapeless_book': (('LR', 'RR'), 'minecraft:book', False),
    'cake_buckets': (('MMM', 'UEU', 'WWW'), 'minecraft:cake', True),
}


def layout(pattern):
    cells = [(X + x, Y + len(pattern) - 1 - row, Z, symbol)
             for row, line in enumerate(pattern) for x, symbol in enumerate(line)]
    sink = X + len(pattern[0]) - 1, Y, Z
    return sorted(cells, key=lambda p: (p[1], p[0])), sink


def setup(command, cells, sink, blocked):
    command(f'fill {AREA} minecraft:air')
    command(f'kill {DROPS}')
    for x, y, z, _ in cells:
        direction = 'down' if x == sink[0] else 'right'
        put(command, (x, y, z), f'create:mechanical_crafter[facing=south,pointing={direction}]')
    put(command, (X - 1, Y + 1, Z), 'create:cogwheel[axis=z]')
    put(command, (X - 1, Y + 1, Z - 1), 'create:creative_motor[facing=south]{ScrollValue:128}')
    chest = sink[0], Y - 1, Z
    put(command, chest, 'minecraft:chest')
    if blocked:
        full = ','.join(f'{{Slot:{slot}b,id:"minecraft:diamond",count:64}}' for slot in range(27))
        command(f'data merge block {xyz(chest)} {{Items:[{full}]}}')
    return chest


def stand(command, y):
    command(f'fill {X-1} {y-2} {Z+3} {X+3} {y-2} {Z+3} minecraft:smooth_stone')


def grid(raw):
    values = field(raw, 'Grid')
    cells = re.findall(r'\{item:\s*\{[^{}]*\bid:\s*"([^"]+)"[^{}]*\},\s*x:\s*(-?\d+),\s*y:\s*(-?\d+)\}', values)
    counts = items(raw, 'Grid')
    assert len(cells) == sum(counts.values()), (cells, raw)
    return sorted([int(x), int(y), item] for item, x, y in cells)


def result(name, observations, chest_items):
    _, product, blocked = CASES[name]
    crafting = next((raw for raw in observations if phase({'nbt': raw})[0] == 'CRAFTING'), None)
    assert crafting is not None, [phase({'nbt': raw}) for raw in observations]
    expected = [[0, 0, product]]
    if blocked:
        expected.extend([i, 0, 'minecraft:bucket'] for i in range(1, 4))
    assert grid(crafting) == expected, crafting
    saved = observations[-1]
    assert phase({'nbt': saved}) == (['INSERTING', 0] if blocked else ['IDLE', 0]), saved
    report = {'grouped': expected, 'chest': [items(raw, 'Items') for raw in chest_items]}
    if blocked:
        assert grid(saved) == expected, saved
        assert report['chest'] == [
            {'minecraft:diamond': 27 * 64},
            {'minecraft:diamond': 26 * 64, product: 1},
            {'minecraft:diamond': 25 * 64, product: 1, 'minecraft:bucket': 3},
        ], report
    else:
        assert report['chest'] == [{product: 1}], report
    return report


def java_run(work):
    host = Original()
    manifest = json.loads((reference_java.BASE / 'manifest.json').read_text())
    assert manifest['create_sha256'] == reference_java.CREATE_SHA256
    previous = host.call('state', {})
    assert previous['ready'] and previous['data_version'] == 3955, previous
    host.call('tick', {'frozen': True})
    command = host.command
    report = {}
    try:
        command(f'forceload add {TICKET}')
        host.snapshot([(X, Y, Z)], 20)
        command('gamemode survival')
        for name, (pattern, _, blocked) in CASES.items():
            cells, sink = layout(pattern)
            chest = setup(command, cells, sink, blocked)
            host.snapshot([sink], 20)
            for i, (x, y, z, symbol) in enumerate(cells):
                if i == 0 or cells[i - 1][1] != y:
                    stand(command, y)
                pos = x, y, z
                click(host, work, f'{name}-{i}', pos, 'south', (x + .5, y - 1, z + 3.25),
                      (x + .5, y + .5, z + .5), INGREDIENTS[symbol])
                nbt = host.call('block', {'pos': pos})['nbt']
                if symbol == ' ':
                    assert number({'nbt': nbt}, 'Cover') == 1, nbt
                else:
                    assert items(field(nbt, 'Inventory'), 'Items') == {INGREDIENTS[symbol]: 1}, nbt
            samples = host.call('observe_ticks', {'ticks': 80, 'positions': [sink]})['samples']
            observed = [row['blocks'][0]['nbt'] for row in samples]
            containers = [text(host, f'data get block {xyz(chest)}')]
            if blocked:
                for slot in (0, 1):
                    command(f'item replace block {xyz(chest)} container.{slot} with minecraft:air')
                    host.snapshot([sink], 25)
                    containers.append(text(host, f'data get block {xyz(chest)}'))
            report[name] = result(name, observed, containers)
        return report
    finally:
        command('gamemode creative')
        command('item replace entity @s weapon.mainhand with minecraft:air')
        command(f'fill {AREA} minecraft:air')
        command(f'kill {DROPS}')
        command(f'forceload remove {TICKET}')
        host.call('camera', {'position': previous['position'], 'yaw': previous['yaw'], 'pitch': previous['pitch']})
        host.call('tick', {'frozen': previous['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(
            [row for row in host.trace if row['method'] != 'observe_ticks'], indent=2) + '\n')


def native_run(session):
    batch = Batch()
    batch.load((X + 1, Y + 1, Z + 4))
    batch.command('gamemode survival')
    for name, (pattern, _, blocked) in CASES.items():
        cells, sink = layout(pattern)
        chest = setup(batch.command, cells, sink, blocked)
        batch.tick(20)
        for i, (x, y, z, symbol) in enumerate(cells, 1):
            batch.command(f'tp @s {x + .5} {y - 1} {z + 3.25}')
            batch.command(f'item replace entity @s weapon.mainhand with {INGREDIENTS[symbol]}')
            batch.ops.append(dict(op='use_block', pos=(x, y, z), face=3, sequence=i))
        for _ in range(80):
            batch.tick()
            batch.data(sink)
        batch.data(chest)
        if blocked:
            batch.command(f'item replace block {xyz(chest)} container.0 with minecraft:air')
            batch.tick(25)
            batch.data(chest)
            batch.data(sink)
    rows = iter(batch.run(session, 'ordinary-recipes'))
    report = {}
    for name, (_, _, blocked) in CASES.items():
        observations = [next(rows) for _ in range(80)]
        chests = [next(rows) for _ in range(2 if blocked else 1)]
        if blocked:
            saved = next(rows)
            assert phase({'nbt': saved}) == ['INSERTING', 0], saved
            pending = [[i, 0, 'minecraft:bucket'] for i in range(1, 4)]
            assert grid(saved) == pending, saved
            _, sink = layout(CASES[name][0])
            chest = sink[0], Y - 1, Z
            after = Batch()
            after.load((X + 1, Y + 1, Z + 4))
            after.data(sink)
            after.data(chest)
            after.command(f'item replace block {xyz(chest)} container.1 with minecraft:air')
            after.tick(25)
            after.data(chest)
            after.data(sink)
            cold, cold_chest, released, done = after.run(session, 'cake-remainders-restart')
            assert phase({'nbt': cold}) == ['INSERTING', 0] and grid(cold) == pending, cold
            assert items(cold_chest, 'Items') == items(chests[-1], 'Items'), cold_chest
            assert phase({'nbt': done}) == ['IDLE', 0], done
            chests.append(released)
        report[name] = result(name, observations, chests)
    assert next(rows, None) is None
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='crafter-standard-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        report = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon check requires --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['create'] == PINS['create_revision'] and reference['passed']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='crafter-standard-native', graphics=False, world='CreateStandardCrafter')
        work = session.scratch
        print(work, flush=True)
        try:
            report = native_run(session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        assert report == reference['cases'], (report, reference)
    path = work / 'result.json'
    path.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], cases=report), indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
