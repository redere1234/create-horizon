#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare the 5×5 Crushing Wheel recipe through real front-slot interactions."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile
import time

from bearing_native_checks import Batch
from burner_heat_java_checks import field, items, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession


X, Y, Z = 1843, 109, 1030
ROOM = '1840 105 1027 1850 116 1035'
FORCE = '1840 1024 1855 1039'
PATTERN = (' AAA ', 'AAPAA', 'APSPA', 'AAPAA', ' AAA ')
INGREDIENTS = {'A': 'create:andesite_alloy', 'P': 'minecraft:oak_planks', 'S': 'minecraft:andesite'}
POINTS = [(X + col, Y + row, Z) for row in range(5) for col in range(5)
          if PATTERN[4 - row][col] != ' ']
SINK = (X + 2, Y, Z)
LEAF = (X + 1, Y + 4, Z)
MARK = 'crafter_probe'
DEPOT = (SINK[0], SINK[1] - 1, SINK[2])
BELT_START = (SINK[0], SINK[1] - 1, SINK[2] - 2)
BELT_MOTOR = (BELT_START[0] - 1, BELT_START[1], BELT_START[2])
SIGNAL = (LEAF[0], LEAF[1], LEAF[2] - 1)
DENSE = [(X + col, Y + row, Z) for row in range(5) for col in range(5)]
CORNERS = [pos for pos in DENSE if pos not in POINTS]
COVER = 'create:crafter_slot_cover'
DROPS = ('@e[type=minecraft:item,x=1840,y=105,z=1027,dx=10,dy=11,dz=8]')


def pointing(pos):
    if pos[0] == X + 2:
        return 'down'
    return 'right' if pos[0] < X + 2 else 'left'


def ingredient(pos):
    return INGREDIENTS[PATTERN[4 - (pos[1] - Y)][pos[0] - X]]


def held_stack(pos):
    item = ingredient(pos)
    return f'{item}[minecraft:custom_data={{{MARK}:37}}]' if pos == LEAF else item


def setup(command, dense=False):
    command('fill ' + ROOM + ' minecraft:air')
    command('fill 1840 105 1027 1850 105 1035 minecraft:stone')
    for pos in DENSE if dense else POINTS:
        command(f'setblock {xyz(pos)} create:mechanical_crafter[facing=south,pointing={pointing(pos)}]')
    command(f'setblock {xyz((X - 1, Y + 2, Z))} create:cogwheel[axis=z]')
    command(f'setblock {xyz((X - 1, Y + 2, Z - 1))} create:creative_motor[facing=south]{{ScrollValue:128}}')


def phase(block):
    nbt = block['nbt']
    value = re.search(r'\bPhase:\s*"([A-Z]+)"', nbt)
    assert value, nbt
    return [value[1], int(number(block, 'CountDown'))]


def check_assembled(assembled):
    assert items(assembled, 'Grid') == {
        'create:andesite_alloy': 16, 'minecraft:oak_planks': 4, 'minecraft:andesite': 1,
    }, assembled
    assert f'{MARK}:37' in assembled.replace(' ', ''), assembled
    coords = {(int(x), int(y)) for x, y in re.findall(r'\bx:\s*(-?\d+)\s*,\s*y:\s*(-?\d+)', assembled)}
    assert coords == {(p[0] - SINK[0], p[1] - SINK[1]) for p in POINTS}, assembled


def check_output(raw, entity_count):
    assert 'create:crushing_wheel' in raw and number({'nbt': raw}, 'count') == 2, raw
    assert re.search(r'\bcount:\s*1\b', entity_count, re.IGNORECASE), entity_count


def click(host, pos, stack, cover=False):
    x, y, z = pos
    host.command(f'item replace entity @s weapon.mainhand with {stack} 2')
    host.call('camera', {'position': (x + .5, y - 1, z + 3.25),
                         'target': (x + .5, y + .5, z + .5)})
    for _ in range(25):
        hit = host.call('state', {})['hit']
        if hit and hit.get('pos') == list(pos) and hit.get('face') == 'south':
            break
        time.sleep(.025)
    else:
        raise AssertionError((pos, hit))
    host.call('input', {'key': 'use'})
    try:
        for _ in range(25):
            observed = host.call('block', {'pos': pos})
            nbt = field(observed['nbt'], 'Inventory')
            placed = number(observed, 'Cover', 0) == 1 if cover else items(nbt, 'Items') == {ingredient(pos): 1}
            if placed:
                break
            time.sleep(.025)
        else:
            raise AssertionError((pos, observed))
    finally:
        host.call('input', {'key': 'use', 'down': False})
    held = ' '.join(host.command('data get entity @s SelectedItem')['messages'])
    assert number({'nbt': held}, 'count') == (2 if cover else 1), held
    return nbt


def run(work):
    host = Original()
    initial = host.call('state', {})
    if initial.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    try:
        host.command('gamemode creative')
        host.command(f'tp @s {X + 2}.5 {Y + 2} {Z + 4}.5')
        host.command('forceload add ' + FORCE)
        host.snapshot([SINK], 25)
        setup(host.command)
        initial_rows = host.snapshot(POINTS, 20)
        assert all(abs(b['speed']) == 128 and phase(b) == ['IDLE', 0] for b in initial_rows), initial_rows

        inventories = []
        for row in range(5):
            stand = (X, Y + row - 2, Z + 3)
            host.command(f'fill {xyz(stand)} {X + 4} {stand[1]} {stand[2]} minecraft:stone')
            for pos in (p for p in POINTS if p[1] == Y + row):
                inventories.append(click(host, pos, held_stack(pos)))
        assert sum(f'{MARK}:37' in value.replace(' ', '') for value in inventories) == 1
        assert all('Size:1' in value.replace(' ', '') for value in inventories), inventories
        assert all(phase(host.call('block', {'pos': p})) == ['IDLE', 0] for p in POINTS)
        ticker_order = host.call('ticker_order', {'positions': POINTS})
        observed = host.call('observe_ticks', {'ticks': 100, 'positions': POINTS})['samples']
        rows = [[phase(block) for block in sample['blocks']] for sample in observed]
        sink = POINTS.index(SINK)
        leaf = POINTS.index(LEAF)
        start = next(i for i, row in enumerate(rows) if row[sink][0] != 'IDLE')
        finish = next(i for i in range(start + 1, len(rows)) if rows[i][sink][0] == 'IDLE')
        trace = rows[start:finish + 1]
        assert {'ACCEPTING', 'ASSEMBLING', 'CRAFTING', 'IDLE'} <= {row[sink][0] for row in trace}
        assert any(row[leaf][0] == 'EXPORTING' for row in trace)
        assert any(row[leaf][0] == 'WAITING' for row in trace)
        craft_start = next(i for i in range(start, finish) if rows[i][sink][0] == 'CRAFTING')
        assembled = field(observed[craft_start - 1]['blocks'][sink]['nbt'], 'GroupedItems')
        check_assembled(assembled)
        check_output(' '.join(host.command(f'data get entity {DROPS[:-1]},limit=1] Item')['messages']),
                     ' '.join(host.command(f'execute if entity {DROPS}')['messages']))
        assert all(row == ['IDLE', 0] for row in trace[-1]), trace[-1]
        return dict(passed=True, create=PINS['create_revision'], pattern=PATTERN, points=POINTS,
                    ticker_order=ticker_order, start_tick=start + 1, trace=trace,
                    assembled=assembled, output={'id': 'create:crushing_wheel', 'count': 2})
    finally:
        host.command(f'kill {DROPS}')
        host.command('fill ' + ROOM + ' minecraft:air')
        host.command('forceload remove ' + FORCE)
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_setup(batch, dense=False, covers=False, chest=False, belt=False):
    batch.load((X + 2, Y + 2, Z + 4))
    setup(batch.command, dense)
    if dense:
        seed_output(batch.command, chest, belt)
    batch.tick(20)
    batch.command('tick freeze')
    if covers:
        for i, (x, y, z) in enumerate(CORNERS, 100):
            batch.command(f'tp @s {x + .5} {y - 1} {z + 3.25}')
            batch.command(f'item replace entity @s weapon.mainhand with {COVER} 2')
            batch.ops.append(dict(op='use_block', pos=(x, y, z), face=3, sequence=i))
            batch.data((x, y, z))
            batch.command('data get entity @s SelectedItem', True)
    for i, (x, y, z) in enumerate(POINTS, 1):
        batch.command(f'tp @s {x + .5} {y - 1} {z + 3.25}')
        batch.command(f'item replace entity @s weapon.mainhand with {held_stack((x, y, z))} 2')
        # UseItemOn from the connected owner's main hand, facing south.
        batch.ops.append(dict(op='use_block', pos=(x, y, z), face=3, sequence=i))
        batch.data((x, y, z))
        batch.command('data get entity @s SelectedItem', True)
    batch.command(f'tp @s {X + 2}.5 {Y + 2} {Z + 4}.5')
    batch.command('tick unfreeze')


def check_native_feed(rows):
    for pos in POINTS:
        block = next(rows)
        held = next(rows)
        inv = field(block, 'Inventory')
        assert items(inv, 'Items') == {ingredient(pos): 1}, (pos, block)
        assert phase({'nbt': block}) == ['IDLE', 0], (pos, block)
        assert 'Size:1' in inv.replace(' ', ''), inv
        assert number({'nbt': held}, 'count') == 1, held
        if pos == LEAF:
            assert all(f'{MARK}:37' in value.replace(' ', '') for value in (inv, held)), (inv, held)


def read_grid(batch):
    for pos in POINTS:
        batch.data(pos)


def native(session, reference):
    batch = Batch()
    native_setup(batch)
    for _ in range(100):
        batch.tick()
        read_grid(batch)
    batch.command(f'data get entity {DROPS[:-1]},limit=1] Item', True)
    batch.command(f'execute if entity {DROPS}', True)
    rows = iter(batch.run(session, 'crafting-trace'))
    check_native_feed(rows)
    samples = [[next(rows) for _ in POINTS] for _ in range(100)]
    trace = [[phase({'nbt': sample}) for sample in row] for row in samples]
    sink = POINTS.index(SINK)
    start = next(i for i, row in enumerate(trace) if row[sink][0] != 'IDLE')
    assert start + 1 == reference['start_tick'], (start + 1, reference['start_tick'])
    finish = next(i for i in range(start + 1, len(trace)) if trace[i][sink][0] == 'IDLE')
    actual = trace[start:finish + 1]
    for tick, (a, b) in enumerate(zip(actual, reference['trace'], strict=True), 1):
        assert a == b, (tick, a, b)
    craft_start = next(i for i in range(start, finish) if trace[i][sink][0] == 'CRAFTING')
    check_assembled(field(samples[craft_start - 1][sink], 'GroupedItems'))
    check_output(next(rows), next(rows))
    assert next(rows, None) is None
    return dict(start_tick=start + 1, ticks=len(actual))


def cold_checkpoint(session, reference):
    # Another world in the same scratch directory uses the same resource tree.
    session.world = 'CrafterCold'
    before = Batch()
    native_setup(before)
    checkpoint_tick = reference['start_tick'] + 22
    before.tick(checkpoint_tick)
    read_grid(before)
    rows = iter(before.run(session, 'cold-before'))
    check_native_feed(rows)
    checkpoints = [next(rows) for _ in POINTS]
    assert next(rows, None) is None

    def state(raw):
        return phase({'nbt': raw}), field(raw, 'GroupedItems')

    expected = [state(raw) for raw in checkpoints]
    assert any(value[0][0] == 'EXPORTING' for value in expected), expected
    assert any(f'{MARK}:37' in value[1].replace(' ', '') for value in expected), expected

    after = Batch()
    after.load((X + 2, Y + 2, Z + 4))
    read_grid(after)
    after.tick(100)
    read_grid(after)
    after.command(f'data get entity {DROPS[:-1]},limit=1] Item', True)
    after.command(f'execute if entity {DROPS}', True)
    rows = iter(after.run(session, 'cold-after'))
    actual = [state(next(rows)) for _ in POINTS]
    assert actual == expected, (expected, actual)
    assert all(phase({'nbt': next(rows)}) == ['IDLE', 0] for _ in POINTS)
    check_output(next(rows), next(rows))
    assert next(rows, None) is None
    return dict(checkpoint_ticks=checkpoint_tick, occupied_nodes=sum(value[0][0] != 'IDLE' for value in expected))


def ordinary_break(session):
    session.world = 'CrafterBreak'
    batch = Batch()
    batch.load((X + 2, Y + 2, Z + 4))
    batch.command('fill ' + ROOM + ' minecraft:air')
    batch.command('gamemode survival')
    x, y, z = SINK
    batch.command(f'tp @s {x + .5} {y - 1} {z + 3.25}')
    block = 'create:mechanical_crafter'
    cargo = 'create:andesite_alloy'
    batch.put(SINK, block + '[facing=south,pointing=up]')
    batch.command(f'item replace entity @s weapon.mainhand with {cargo}[minecraft:custom_data={{{MARK}:37}}] 2')
    batch.ops.append(dict(op='use_block', pos=SINK, face=3, sequence=1))
    batch.data(SINK)
    batch.command('data get entity @s SelectedItem', True)
    batch.command('item replace entity @s weapon.mainhand with create:wrench')
    pointing_order = ('left', 'down', 'right', 'up')
    for sequence, arrow in enumerate(pointing_order, 2):
        batch.ops.append(dict(op='use_block', pos=SINK, face=3, sequence=sequence))
        batch.expect(SINK, block + f'[facing=south,pointing={arrow}]')
    batch.data(SINK)
    batch.command('item replace entity @s weapon.mainhand with minecraft:iron_pickaxe')
    batch.ops.append(dict(op='break', pos=SINK))
    batch.expect(SINK, 'minecraft:air')
    for item in (block, cargo):
        batch.command(f'data get entity {DROPS[:-1]},nbt={{Item:{{id:"{item}"}}}},limit=1] Item', True)
    batch.command(f'execute if entity {DROPS}', True)
    rows = iter(batch.run(session, 'survival-break'))
    stored = next(rows)
    held = next(rows)
    inv = field(stored, 'Inventory')
    assert items(inv, 'Items') == {cargo: 1} and phase({'nbt': stored}) == ['IDLE', 0], stored
    assert number({'nbt': held}, 'count') == 1, held
    assert all(f'{MARK}:37' in value.replace(' ', '') for value in (inv, held)), (inv, held)
    assert all('bearing_check' in next(rows) for _ in pointing_order)
    assert field(next(rows), 'Inventory') == inv
    assert 'bearing_check' in next(rows)
    for item in (block, cargo):
        result = next(rows)
        assert item in result and number({'nbt': result}, 'count') == 1, result
        if item == cargo:
            assert f'{MARK}:37' in result.replace(' ', ''), result
    entity_count = next(rows)
    assert re.search(r'\bcount:\s*2\b', entity_count, re.IGNORECASE), entity_count
    assert next(rows, None) is None
    return dict(pointing=pointing_order, drops=[block, cargo])


def seed_output(command, chest, belt=False):
    if belt:
        x, y, z = BELT_START
        for index, part in enumerate(('start', 'middle', 'middle', 'middle', 'end')):
            command(f'setblock {x} {y} {z + index} create:belt[facing=south,slope=horizontal,part={part}]')
        return
    if chest:
        command(f'setblock {xyz(DEPOT)} minecraft:chest')
        slots = ['{Slot:0b,id:"create:crushing_wheel",count:63}']
        slots.extend(f'{{Slot:{slot}b,id:"minecraft:diamond",count:64}}' for slot in range(1, 27))
        command(f'data merge block {xyz(DEPOT)} {{Items:[{",".join(slots)}]}}')
        return
    command(f'setblock {xyz(DEPOT)} create:depot')
    command(f'data merge block {xyz(DEPOT)} '
            '{HeldItem:{Item:{id:"minecraft:diamond",count:1},Pos:0.5f,PrevPos:0.5f,Angle:180,InDirection:1}}')


def clear_output(command, chest, belt=False):
    if belt:
        command(f'setblock {xyz(BELT_MOTOR)} create:creative_motor[facing=east]{{ScrollValue:32}}')
        return
    if chest:
        command(f'item replace block {xyz(DEPOT)} container.1 with minecraft:air')
    else:
        command(f'data remove block {xyz(DEPOT)} HeldItem')


def dense_snapshot(crafter, target, chest=False, belt=False):
    if belt:
        inventory = field(target, 'Inventory')
        items_in_belt = items(inventory, 'Items')
        return {'phase': phase({'nbt': crafter}), 'output': items(crafter, 'Grid'), 'belt': items_in_belt,
                'entry': None if not items_in_belt else [
                    number({'nbt': inventory}, key) for key in ('InSegment', 'InDirection', 'Pos', 'PrevPos')
                ]}
    inventory = items(target, 'Items') if chest else items(target, 'HeldItem') if 'HeldItem:' in target else {}
    return {'phase': phase({'nbt': crafter}), 'output': items(crafter, 'Grid'), 'depot': inventory}


def verify_chest(trace, cleared):
    product = 'create:crushing_wheel'
    filler = 'minecraft:diamond'
    assert trace[0] == dict(phase=['IDLE', 0], output={}, depot={product: 63, filler: 26 * 64}), trace[0]
    blocked = dict(phase=['INSERTING', 0], output={product: 1}, depot={product: 64, filler: 26 * 64})
    assert trace[-1] == cleared[0] == blocked, (trace[-1], cleared[0])
    delivered = dict(phase=['IDLE', 0], output={}, depot={product: 65, filler: 25 * 64})
    assert cleared[-1] == delivered, cleared
    assert all(row in (dict(blocked, depot={product: 64, filler: 25 * 64}), delivered)
               for row in cleared[1:]), cleared


def verify_belt(trace, cleared):
    product = {'create:crushing_wheel': 2}
    blocked = {'phase': ['INSERTING', 0], 'output': product, 'belt': {}, 'entry': None}
    assert trace[-1] == cleared[0] == blocked, (trace[-1], cleared[0])
    first = next(row for row in cleared[1:] if row['belt'])
    assert first['belt'] == product and first['phase'] == ['IDLE', 0] and not first['output'], first
    segment, direction, position, previous = first['entry']
    assert segment == 2 and direction == 0 and abs(position - 2.5) < .15, first
    assert abs(position - previous) <= .07, first
    assert all(sum(row['output'].values()) + sum(row['belt'].values()) == 2 for row in cleared)


def verify_depot(trace, cleared):
    assert trace[0] == dict(phase=['IDLE', 0], output={}, depot={'minecraft:diamond': 1}), trace[0]
    blocked = dict(phase=['INSERTING', 0], output={'create:crushing_wheel': 2},
                   depot={'minecraft:diamond': 1})
    assert trace[-1] == blocked, trace[-1]
    assert all(row['depot'] == blocked['depot'] for row in trace), trace
    assert cleared[0] == blocked, cleared
    assert cleared[1] == dict(phase=['IDLE', 0], output={}, depot={'create:crushing_wheel': 2}), cleared
    assert all(row == cleared[1] for row in cleared[1:]), cleared


def java_depot(work, covers=False, chest=False, belt=False):
    host = Original()
    initial = host.call('state', {})
    if initial.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    positions = [SINK, BELT_START if belt else DEPOT]

    def snapshots(ticks):
        return [dense_snapshot(*(block['nbt'] for block in row['blocks']), chest=chest, belt=belt)
                for row in host.call('observe_ticks', {'ticks': ticks, 'positions': positions})['samples']]

    try:
        host.command('gamemode creative')
        host.command(f'tp @s {X + 2}.5 {Y + 2} {Z + 4}.5')
        host.command('forceload add ' + FORCE)
        host.snapshot([SINK], 25)
        setup(host.command, dense=True)
        seed_output(host.command, chest, belt)
        host.snapshot(POINTS, 20)
        for row in range(5):
            stand = (X, Y + row - 2, Z + 3)
            host.command(f'fill {xyz(stand)} {X + 4} {stand[1]} {stand[2]} minecraft:stone')
            if covers:
                for pos in (p for p in CORNERS if p[1] == Y + row):
                    click(host, pos, COVER, cover=True)
            for pos in (p for p in POINTS if p[1] == Y + row):
                click(host, pos, held_stack(pos))
        if covers:
            trace = [dense_snapshot(*(host.call('block', {'pos': pos})['nbt'] for pos in positions), chest=chest)]
            trace.extend(snapshots(87))
        else:
            trace = snapshots(3)
            assert all(row['phase'] == ['IDLE', 0] for row in trace), trace
            host.command(f'setblock {xyz(SIGNAL)} minecraft:redstone_block')
            trace.extend(snapshots(85))
        cold = dense_snapshot(*(host.call('block', {'pos': pos})['nbt'] for pos in positions), chest=chest, belt=belt)
        clear_output(host.command, chest, belt)
        cleared = [cold, *snapshots(25 if chest else 10 if belt else 4)]
        (verify_belt if belt else verify_chest if chest else verify_depot)(trace, cleared)
        count = host.command(f'execute if entity {DROPS} run say crafter_loose_output')
        assert not any('crafter_loose_output' in line for line in count['messages']), count
        if covers:
            assert all(number(host.call('block', {'pos': pos}), 'Cover') == 1 for pos in CORNERS)
        return dict(passed=True, create=PINS['create_revision'], covers=covers, chest=chest, belt=belt,
                    trace=trace, cleared=cleared)
    finally:
        host.command(f'kill {DROPS}')
        host.command('fill ' + ROOM + ' minecraft:air')
        host.command('forceload remove ' + FORCE)
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_depot(session, reference, covers=False, chest=False, belt=False):
    batch = Batch()
    native_setup(batch, dense=True, covers=covers, chest=chest, belt=belt)
    target = BELT_START if belt else DEPOT
    for tick in range(88):
        if tick == 3 and not covers:
            batch.put(SIGNAL, 'minecraft:redstone_block')
        if tick > 0 or not covers:
            batch.tick()
        batch.data(SINK)
        batch.data(target)
    values = iter(batch.run(session, 'dense-covers' if covers else 'dense-redstone'))
    if covers:
        for pos in CORNERS:
            raw, held = next(values), next(values)
            assert number({'nbt': raw}, 'Cover') == 1 and not items(raw, 'Inventory'), (pos, raw)
            assert number({'nbt': held}, 'count') == 2 and COVER in held, (pos, held)
    check_native_feed(values)
    trace = [dense_snapshot(next(values), next(values), chest, belt) for _ in range(88)]
    assert next(values, None) is None
    for tick, (observed, expected) in enumerate(zip(trace, reference['trace'], strict=True), 1):
        assert observed == expected, (tick, observed, expected)

    batch = Batch()
    batch.load((X + 2, Y + 2, Z + 4))
    batch.data(SINK)
    batch.data(target)
    if covers:
        for pos in CORNERS:
            batch.data(pos)
    clear_output(batch.command, chest, belt)
    release_ticks = 25 if chest else 10 if belt else 4
    for _ in range(release_ticks):
        batch.tick()
        batch.data(SINK)
        batch.data(target)
    batch.command(f'execute if entity {DROPS} run say crafter_loose_output', True)
    values = iter(batch.run(session, 'clear-after-restart'))
    cold = dense_snapshot(next(values), next(values), chest, belt)
    if covers:
        for pos in CORNERS:
            raw = next(values)
            assert number({'nbt': raw}, 'Cover') == 1, (pos, raw)
    cleared = [cold, *(dense_snapshot(next(values), next(values), chest, belt) for _ in range(release_ticks))]
    if not chest:
        assert cleared == reference['cleared'], (cleared, reference['cleared'])
    assert 'crafter_loose_output' not in next(values)
    assert next(values, None) is None
    (verify_belt if belt else verify_chest if chest else verify_depot)(trace, cleared)
    return dict(ticks=len(trace), cold=cleared[0], released=cleared[-1],
                release_tick=cleared.index(cleared[-1]))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + key, type=Path)
    cases = parser.add_mutually_exclusive_group()
    cases.add_argument('--depot', action='store_true')
    cases.add_argument('--covers', action='store_true')
    cases.add_argument('--chest', action='store_true')
    cases.add_argument('--belt', action='store_true')
    args = parser.parse_args()
    dense = args.depot or args.covers or args.chest or args.belt
    if args.game:
        if not all((args.resources, args.ctl, args.reference)):
            parser.error('Horizon runs require --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision'], reference
        if not dense:
            assert reference['points'] == [list(pos) for pos in POINTS], reference['points']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='crafter-native', graphics=False, world='CrafterParity')
        work = session.scratch
        try:
            if dense:
                assert reference.get('covers', False) == args.covers
                assert reference.get('chest', False) == args.chest
                assert reference.get('belt', False) == args.belt
                report = dict(passed=True, create=PINS['create_revision'],
                              **native_depot(session, reference, covers=args.covers, chest=args.chest, belt=args.belt))
            else:
                report = dict(passed=True, create=PINS['create_revision'], **native(session, reference),
                              restart=cold_checkpoint(session, reference), survival_break=ordinary_break(session))
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                # Finder may add .DS_Store during removal of these disposable trees.
                shutil.rmtree(folder, ignore_errors=True)
    else:
        work = Path(tempfile.mkdtemp(prefix='crafter-java-', dir=ROOT / '.local'))
        report = java_depot(work, covers=args.covers, chest=args.chest, belt=args.belt) if dense else run(work)
    output = work / 'result.json'
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(output)
