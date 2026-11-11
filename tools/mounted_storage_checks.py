#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Check a bearing farm's chest on Create 6.0.10 or a real Horizon build."""
import argparse
import json
from pathlib import Path
import tempfile

from actor_native_checks import bearing, matched, powered
from bearing_native_checks import Batch
from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession


PIVOT = (952, 105, 58)
CHEST = 'minecraft:chest[facing=north,type=single,waterlogged=false]'
PROBE = 'minecraft:stick[minecraft:custom_data={mounted_probe:173}] 11'
STICK = '{Slot:26b,id:"minecraft:stick",count:11,components:{"minecraft:custom_data":{mounted_probe:173}}}'
ORIGINAL_WHEAT = '{Slot:5b,id:"minecraft:wheat",count:60}'
HARVESTED_WHEAT = '{Slot:0b,id:"minecraft:wheat",count:1}'


def fixture(batch, pivot, full=False):
    x, y, z = pivot
    batch.command(f'fill {x - 5} {y - 5} {z - 5} {x + 5} {y + 8} {z + 5} minecraft:air')
    motor = bearing(batch, pivot, 'create:mechanical_harvester[facing=north,waterlogged=false]', 3)
    source = (x - 1, y + 1, z)
    anchor = (x, y + 1, z)
    crop = (x + 3, y + 1, z - 1)
    batch.put((x + 3, y, z - 1), 'minecraft:farmland[moisture=7]')
    batch.put(crop, 'minecraft:wheat[age=7]')
    batch.put(source, CHEST)
    if full:
        for slot in range(27):
            batch.command(f'item replace block {xyz(source)} container.{slot} with minecraft:cobblestone 64')
    else:
        batch.command(f'item replace block {xyz(source)} container.5 with minecraft:wheat 60')
        batch.command(f'item replace block {xyz(source)} container.26 with {PROBE}')
    powered(batch, motor, 32)
    return motor, source, anchor, crop


def targets(anchor):
    x, y, z = anchor
    return [(x - 1, y, z), (x, y, z + 1), (x + 1, y, z), (x, y, z - 1)]


def expect_item(batch, pos, item):
    batch.command(f'execute if data block {xyz(pos)} Items[{item}] run say bearing_check', True)


def expect_drop(batch, pivot, item, *, present):
    x, y, z = pivot
    check = 'if' if present else 'unless'
    batch.command(
        f'execute {check} entity @e[type=minecraft:item,x={x},y={y},z={z},distance=..12,'
        f'nbt={{Item:{{id:"minecraft:{item}"}}}},limit=1] run say bearing_check', True,
    )


def native(session):
    x, y, z = PIVOT
    batch = Batch()
    batch.load((x, y + 8, z))
    batch.command('gamerule minecraft:random_tick_speed 0')
    _, source, anchor, crop = fixture(batch, PIVOT)
    batch.tick(14)
    batch.data(PIVOT)
    batch.expect(source, 'minecraft:air')
    batch.expect(crop, 'minecraft:wheat[age=0]')
    expect_drop(batch, PIVOT, 'stick', present=False)
    expect_drop(batch, PIVOT, 'wheat', present=False)
    captured = batch.run(session, 'captured')
    assert number({'nbt': captured[0]}, 'Running', 0) == 1 and all(map(matched, captured[1:])), captured

    batch = Batch()
    batch.load((x, y + 8, z))
    batch.data(PIVOT)
    batch.put(anchor, 'minecraft:obsidian')
    batch.put(PIVOT, 'minecraft:air')
    batch.tick(3)
    batch.expect(anchor, 'minecraft:obsidian')
    for candidate in targets(anchor):
        batch.expect(candidate, 'minecraft:air')
    blocked = batch.run(session, 'blocked-orphan-after-restart')
    assert number({'nbt': blocked[0]}, 'Running', 0) == 1 and all(map(matched, blocked[1:])), blocked

    batch = Batch()
    batch.load((x, y + 8, z))
    batch.put(anchor, 'minecraft:air')
    batch.tick(3)
    batch.expect(anchor, 'minecraft:slime_block')
    for candidate in targets(anchor):
        batch.expect(candidate, 'minecraft:chest')
    landed = batch.run(session, 'landed-after-second-restart')
    assert matched(landed[0]) and sum(map(matched, landed[1:])) == 1, landed
    destination = targets(anchor)[next(i for i, row in enumerate(landed[1:]) if matched(row))]

    batch = Batch()
    batch.load((x, y + 8, z))
    for item in (HARVESTED_WHEAT, ORIGINAL_WHEAT, STICK):
        expect_item(batch, destination, item)
    expect_drop(batch, PIVOT, 'stick', present=False)
    expect_drop(batch, PIVOT, 'wheat', present=False)
    batch.command(f'data get block {xyz(destination)} Items', True)
    inventory = batch.run(session, 'inventory-after-third-restart')
    assert len(inventory) == 6 and all(map(matched, inventory[:5])), inventory
    assert inventory[-1].count('Slot: ') == 3, inventory[-1]

    batch = Batch()
    batch.load((x, y + 8, z))
    batch.put(PIVOT, 'create:mechanical_bearing[facing=up]')
    batch.tick(3)
    batch.data(PIVOT)
    batch.expect(destination, 'minecraft:air')
    batch.put(PIVOT, 'minecraft:air')
    batch.tick(2)
    for item in (HARVESTED_WHEAT, ORIGINAL_WHEAT, STICK):
        expect_item(batch, destination, item)
    captured_again = batch.run(session, 'recapture-after-restart')
    assert number({'nbt': captured_again[0]}, 'Running', 0) == 1, captured_again
    assert len(captured_again) == 5 and all(map(matched, captured_again[1:])), captured_again

    return dict(captured=captured, blocked=blocked, landed=landed, destination=destination,
                inventory=inventory, captured_again=captured_again,
                full=full_chest(session), saw=moving_cutter(session, 'saw'),
                drill=moving_cutter(session, 'drill'), neighboring_column=neighboring_column(session))


def full_chest(session):
    batch = Batch()
    full_pivot = (936, 105, 58)
    batch.load((936, 113, 58))
    motor, _, full_anchor, crop = fixture(batch, full_pivot, full=True)
    batch.tick(10)
    batch.expect(crop, 'minecraft:wheat[age=0]')
    expect_drop(batch, full_pivot, 'wheat', present=True)
    batch.put(motor, 'minecraft:air')
    batch.tick(2)
    expect_item(batch, targets(full_anchor)[1], '{Slot:0b,id:"minecraft:cobblestone",count:64}')
    expect_item(batch, targets(full_anchor)[1], '{Slot:26b,id:"minecraft:cobblestone",count:64}')
    full = batch.run(session, 'full-chest-overflow')
    assert len(full) == 4 and all(map(matched, full)), full
    return full


def moving_cutter(session, tool):
    pivot = (968, 105, 74) if tool == 'saw' else (952, 105, 74)
    x, y, z = pivot
    anchor = (x, y + 1, z)
    batch = Batch()
    batch.load((x, y + 8, z))
    batch.command(f'fill {x - 5} {y - 5} {z - 5} {x + 5} {y + 8} {z + 5} minecraft:air')
    state = ('create:mechanical_saw[facing=north,axis_along_first=false,flipped=false]' if tool == 'saw'
             else 'create:mechanical_drill[facing=north]')
    motor = bearing(batch, pivot, state, 1)
    batch.put((x - 1, y + 1, z), CHEST)
    if tool == 'saw':
        cut = [(x + 1, y + dy, z - 1) for dy in (1, 2, 3)]
        for pos in cut:
            batch.put(pos, 'minecraft:oak_log[axis=y]')
        item, count = 'oak_log', 3
    else:
        cut = [(x + 1, y + 1, z - 1)]
        batch.put(cut[0], 'minecraft:oak_planks')
        item, count = 'oak_planks', 1
    powered(batch, motor, 32)
    batch.tick(110)
    for pos in cut:
        batch.expect(pos, 'minecraft:air')
    expect_drop(batch, pivot, item, present=False)
    batch.put(motor, 'minecraft:air')
    batch.tick(2)
    batch.expect(anchor, 'minecraft:slime_block')
    for candidate in targets(anchor):
        expect_item(batch, candidate, f'{{Slot:0b,id:"minecraft:{item}",count:{count}}}')
    rows = batch.run(session, f'{tool}-deposits-loot')
    assert len(rows) == len(cut) + 6 and all(map(matched, rows[:-4])), rows
    assert sum(map(matched, rows[-4:])) == 1, rows
    return rows


def neighboring_column(session):
    pivot = (1000, 105, 55)
    anchor = (1000, 106, 55)
    batch = Batch()
    batch.load((1000, 113, 55))
    batch.command('fill 992 100 48 1011 114 63 minecraft:air')
    motor = bearing(batch, pivot, 'create:mechanical_drill[facing=east]', 7)
    batch.put((999, 106, 55), CHEST)
    # At the first angle the drill's forward active point crosses x=1008,
    # but the payload itself and the chest can land within the owner column.
    target = (1008, 106, 54)
    batch.put(target, 'minecraft:oak_planks')
    powered(batch, motor, 32)
    batch.tick(110)
    batch.expect(target, 'minecraft:air')
    expect_drop(batch, pivot, 'oak_planks', present=True)
    batch.put(motor, 'minecraft:air')
    batch.tick(2)
    batch.expect(anchor, 'minecraft:slime_block')
    for candidate in targets(anchor):
        p = xyz(candidate)
        batch.command(f'execute if block {p} minecraft:chest unless data block {p} '
                      'Items[{id:"minecraft:oak_planks"}] run say bearing_check', True)
    rows = batch.run(session, 'neighboring-column-overflow')
    assert len(rows) == 7 and all(map(matched, rows[:3])), rows
    assert sum(map(matched, rows[3:])) == 1, rows
    return rows


def original():
    host = Original()
    assert host.call('state', {})['data_version'] == 3955
    host.call('tick', {'frozen': True})
    host.command('gamemode creative')
    x, y, z = PIVOT
    host.command(f'tp @s {x}.5 {y + 8} {z}.5')
    host.command('forceload add 944 48 959 63')
    host.call('observe_ticks', {'ticks': 20, 'positions': [PIVOT]})
    batch = Batch()
    motor, source, anchor, crop = fixture(batch, PIVOT)
    for entry in batch.ops:
        host.command(entry['cmd'])
    positions = [PIVOT, source, crop]
    captured = host.call('observe_ticks', {'ticks': 10, 'positions': positions})['samples'][-1]['blocks']
    assert number(captured[0], 'Running', 0) == 1, captured
    assert captured[1]['id'] == 'minecraft:air' and captured[2]['properties']['age'] == '0', captured
    host.command(f'setblock {xyz(motor)} minecraft:air')
    final = host.call('observe_ticks', {'ticks': 2, 'positions': targets(anchor)})['samples'][-1]['blocks']
    assert [b['id'] for b in final] == ['minecraft:air', 'minecraft:chest', 'minecraft:air',
                                        'minecraft:slime_block'], final
    assert final[1]['properties']['facing'] == 'west', final
    destination = targets(anchor)[1]
    inventory = []
    for item in (HARVESTED_WHEAT, ORIGINAL_WHEAT, STICK):
        result = host.command(f'execute if data block {xyz(destination)} Items[{item}]')
        assert any('Test passed' in message for message in result['messages']), (item, result, final)
        inventory.append(result)
    return dict(captured=captured, landed=final, destination=destination, inventory=inventory,
                transcript=host.trace)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'create-jar'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='mounted-storage-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        result = original()
    else:
        if not all((args.game, args.resources, args.ctl)):
            parser.error('Horizon requires --game, --resources and --ctl')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='mounted-storage-native', graphics=False, world='CreateMountedStorage')
        work = session.scratch
        print(work, flush=True)
        try:
            result = native(session)
        finally:
            session.stop()
    path = work / 'result.json'
    path.write_text(json.dumps(dict(create=PINS['create_revision'], passed=True, **result), indent=2) + '\n')
    print(json.dumps(dict(passed=True, result=str(path))))


if __name__ == '__main__':
    main()
