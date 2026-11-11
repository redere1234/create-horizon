#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare two independently filtered moving Deployers sharing one chest."""
import argparse
import json
from pathlib import Path
import re
import tempfile

from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from deployer_farm_checks import DEPLOYER, PIVOT, SAPLING, Batch, start, stop
from deployer_refill_checks import CHEST, chest_slots
from native_check_session import NativeCheckSession
from saved_block_checks import read_saved_chunk_tag

AIR = 'minecraft:air'
MEAL = 'minecraft:bone_meal'
FERTILIZER = (1157, 100, 55)
PLANT = (1161, 98, 54)
WHEAT = (1157, 98, 56)
TREE = (1160, 98, 53)
POSITIONS = (PIVOT, PLANT, WHEAT, TREE)
STOCK = {SAPLING: 2, MEAL: 24, 'minecraft:stick': 4}
SCENARIOS = (('wheat_and_plant', 76), ('blocked_tree', 151), ('open_tree', 301))
CARGO = ('horizon:attachments', 'create', 'mounted_deployer', 'value')
ACTORS = ('horizon:attachments', 'create', 'moving_actor_ticks', 'value')


def put(host, pos, state):
    host.command(f'setblock {xyz(pos)} {state}')


def below(pos):
    return pos[0], pos[1] - 1, pos[2]


def setup(host, case):
    host.command('fill 1154 96 51 1165 112 62 minecraft:air')
    host.command('fill 1154 97 51 1165 97 62 minecraft:stone')
    if case == 'wheat_and_plant':
        put(host, below(PLANT), 'minecraft:dirt')
        put(host, below(WHEAT), 'minecraft:farmland[moisture=7]')
        put(host, WHEAT, 'minecraft:wheat[age=6]')
    else:
        put(host, below(TREE), 'minecraft:dirt')
        put(host, TREE, SAPLING + '[stage=1]')
        if case == 'blocked_tree':
            put(host, (TREE[0], TREE[1] + 1, TREE[2]), 'minecraft:glass')
    put(host, PIVOT, 'create:mechanical_bearing[facing=up]')
    for x in range(1158, 1161):
        put(host, (x, 100, 55), 'minecraft:slime_block')
    for pos, item in ((DEPLOYER, SAPLING), (FERTILIZER, MEAL)):
        put(host, pos, 'create:deployer[facing=down,axis_along_first=false]'
            + f'{{Mode:"USE",Inventory:[],Filter:{{id:"{item}",count:1}},FilterAmount:64,UpTo:1b}}')
    entries = ','.join(f'{{Slot:{slot}b,id:"{item}",count:{count}}}'
                       for slot, (item, count) in enumerate(STOCK.items()))
    put(host, CHEST, f'minecraft:chest[facing=north]{{Items:[{entries}]}}')


def kept(nbt):
    held = re.search(r'HeldItem\s*:\s*\{([^}]*)\}', nbt)
    if not held:
        return None
    item = re.search(r'\bid\s*:\s*"([\w:]+)"', held[1])
    count = re.search(r'\bcount\s*:\s*(\d+)', held[1])
    return [item[1], int(count[1])] if item and count else None


def trace(host, ticks, after=0):
    return [
        dict(tick=after + row['tick'], angle=number(row['blocks'][0], 'Angle', 0),
             targets=[(block['id'], block['properties']) for block in row['blocks'][1:]])
        for row in host.call('observe_ticks', {'ticks': ticks, 'positions': POSITIONS})['samples']
    ]


def stock(hands, slots):
    assert all(hand is None or hand[0] == expected for hand, expected in
               zip(hands, (SAPLING, MEAL), strict=True)), hands
    totals = dict.fromkeys(STOCK, 0)
    for item, count in [*slots.values(), *(hand for hand in hands if hand)]:
        totals[item] += count
    assert totals['minecraft:stick'] == STOCK['minecraft:stick'], totals
    return dict(hands=hands, chest=slots, totals=totals)


def inspect_landed(host):
    positions = (PIVOT, DEPLOYER, FERTILIZER, CHEST)
    pivot, planter, fertilizer, chest = host.call(
        'observe_ticks', {'ticks': 2, 'positions': positions})['samples'][-1]['blocks']
    assert number(pivot, 'Running', 0) == 0, pivot
    assert [block['id'] for block in (planter, fertilizer, chest)] == [
        'create:deployer', 'create:deployer', 'minecraft:chest'], (planter, fertilizer, chest)
    return stock([kept(block['nbt']) for block in (planter, fertilizer)], chest_slots(chest['nbt']))


def java_review():
    host = Original()
    scratch = Path(tempfile.mkdtemp(prefix='deployer-moving-meal-java-', dir=ROOT / '.local'))
    report = dict(passed=False, create=PINS['create_revision'], cases={})
    try:
        assert host.call('state', {})['data_version'] == 3955
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        host.command('tp @s 1156.5 106 60.5')
        host.command('forceload add 1152 48 1167 63')
        host.call('observe_ticks', {'ticks': 24, 'positions': [PIVOT]})
        host.command('gamerule randomTickSpeed 0')
        for name, ticks in SCENARIOS:
            setup(host, name)
            start(host.command)
            rows = trace(host, ticks)
            if name == 'open_tree' and rows[-1]['targets'][2][0] != 'minecraft:oak_log':
                rows += trace(host, 150, ticks)
            assert abs((rows[-1]['angle'] + 180.0) % 360 - 180) <= 15.0, rows[-1]
            stop(host.command)
            landed = inspect_landed(host)
            row = report['cases'][name] = dict(rows=rows, **landed)
            assert row['totals'][MEAL] < STOCK[MEAL], (name, landed)
            if name == 'wheat_and_plant':
                assert rows[-1]['targets'][0][0] in (SAPLING, 'minecraft:oak_log'), rows[-1]
                assert rows[-1]['targets'][1] == ('minecraft:wheat', {'age': '7'}), rows[-1]
                assert row['totals'][SAPLING] == 1, row['totals']
            elif name == 'blocked_tree':
                assert rows[-1]['targets'][2] == (SAPLING, {'stage': '1'}), rows[-1]
            else:
                assert rows[-1]['targets'][2][0] == 'minecraft:oak_log', rows[-1]
        report['passed'] = True
    finally:
        stop(host.command)
        host.command('forceload remove 1152 48 1167 63')
        host.call('tick', {'frozen': False})
        (scratch / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
        path = scratch / 'result.json'
        path.write_text(json.dumps(report, indent=2) + '\n')
        print(path)


NATIVE_STATES = (
    (AIR, SAPLING + '[stage=0]', SAPLING + '[stage=1]', 'minecraft:oak_log[axis=y]'),
    (AIR, 'minecraft:wheat[age=6]', 'minecraft:wheat[age=7]'),
    (AIR, SAPLING + '[stage=1]', 'minecraft:oak_log[axis=y]'),
)
STRIDE = 1 + sum(map(len, NATIVE_STATES))
LOCAL_HANDS = {(-2, 0, 0): MEAL, (2, 0, 0): SAPLING}


def native_setup(case):
    batch = Batch()
    batch.load((1156, 106, 60))
    batch.command('gamerule minecraft:random_tick_speed 0')
    setup(batch, case)
    return batch


def observe(batch, ticks):
    for _ in range(ticks):
        batch.tick()
        batch.data(PIVOT)
        for pos, states in zip(POSITIONS[1:], NATIVE_STATES, strict=True):
            for state in states:
                batch.expect(pos, state)


def native_trace(rows, offset=0):
    assert len(rows) % STRIDE == 0, len(rows)
    trace_rows = []
    for start_index in range(0, len(rows), STRIDE):
        row = rows[start_index:start_index + STRIDE]
        targets = []
        index = 1
        for states in NATIVE_STATES:
            [state] = [state for state, raw in zip(states, row[index:index + len(states)], strict=True)
                       if 'bearing_check' in raw]
            name, _, properties = state.partition('[')
            targets.append([name, dict([properties[:-1].split('=')]) if properties else {}])
            index += len(states)
        trace_rows.append(dict(tick=offset + len(trace_rows) + 1,
                               angle=number({'nbt': row[0]}, 'Angle', 0), targets=targets))
    return trace_rows


def read_mounted(session, key):
    return read_saved_chunk_tag(session.scratch, PIVOT, key, session.world)['nbt']


def inspect_cold_chunk(session, both_stocked):
    cargo = read_mounted(session, CARGO)['value']
    assert cargo['Version']['value'] == 2, cargo
    slots = {}
    for actor in cargo['Deployers']['value']:
        data = actor['value']
        assert data['Controller']['value'] == list(PIVOT), data
        nbt = data['Data']['value']
        local = tuple(data['Pos']['value'])
        assert local not in slots, cargo
        slots[local] = nbt['Filter']['value']['id']['value']
        held = nbt.get('HeldItem', {}).get('value', {})
        if both_stocked:
            assert held['id']['value'] == slots[local] and held['count']['value'] == 1, nbt
        else:
            assert not held, nbt
    assert slots == LOCAL_HANDS, cargo
    motion = read_mounted(session, ACTORS)['value']
    assert motion['Version']['value'] == 2, motion
    [structure] = motion['Structures']['value']
    assert structure['value']['Controller']['value'] == list(PIVOT), structure
    actors = [actor['value'] for actor in structure['value']['Actors']['value']]
    assert sorted(actor['Local']['value'] for actor in actors) == sorted(map(list, LOCAL_HANDS)), actors
    assert all(actor['Deployer']['value'] == 1 and 'Position' in actor for actor in actors), actors


def native_landed(batch, session, label):
    stop(batch.command)
    batch.tick(2)
    for pos in (PIVOT, DEPLOYER, FERTILIZER, CHEST):
        batch.data(pos)
    return batch.run(session, label)


def inspect_native_landing(session, rows):
    pivot, planter, fertilizer, chest = rows
    assert number({'nbt': pivot}, 'Running') == 0, rows
    for raw, item in zip((planter, fertilizer), (SAPLING, MEAL), strict=True):
        match = re.search(r'Filter\s*:\s*\{([^}]+)\}', raw)
        assert match and re.search(r'\bid\s*:\s*"' + re.escape(item) + '"', match[1]), raw
    assert read_mounted(session, CARGO) is None
    assert read_mounted(session, ACTORS) is None
    return stock([kept(planter), kept(fertilizer)], chest_slots(chest))


def native_case(session, case, reference, split=None):
    ticks = len(reference['rows'])
    if case == 'open_tree':
        # Vanilla growth uses each engine's RNG. Give both the full reference
        # retry window and compare the resulting tree rather than the draw.
        ticks = 451
    batch = native_setup(case)
    start(batch.command)
    rows = []
    if split:
        observe(batch, split)
        for pos in (DEPLOYER, FERTILIZER, CHEST):
            batch.expect(pos, AIR)
        prefix = batch.run(session, case + '-before-restart')
        assert all('bearing_check' in raw for raw in prefix[-3:]), prefix[-3:]
        rows += native_trace(prefix[:-3])
        inspect_cold_chunk(session, both_stocked=case == 'blocked_tree')
        batch = Batch()
        batch.load((1156, 106, 60))
    offset = len(rows)
    observe(batch, ticks - offset)
    observed = native_landed(batch, session, case + '-landing')
    rows += native_trace(observed[:-4], offset)
    landed = inspect_native_landing(session, observed[-4:])
    trace_len = len(reference['rows'])
    assert [row['angle'] for row in rows[:trace_len]] == [row['angle'] for row in reference['rows']]
    if case == 'blocked_tree':
        assert rows == reference['rows'] and landed == {k: reference[k] for k in landed}, landed
    else:
        assert landed['hands'] == reference['hands'], landed
        assert landed['totals'][SAPLING] == reference['totals'][SAPLING], landed
        assert 0 < landed['totals'][MEAL] < STOCK[MEAL], landed
        if case == 'wheat_and_plant':
            assert rows[:4] == reference['rows'][:4], rows[:4]
            assert all(row['targets'][1] == ['minecraft:wheat', {'age': '7'}]
                       for row in rows[3:]), rows[-1]
        else:
            assert rows[-1]['targets'][2] == ['minecraft:oak_log', {'axis': 'y'}], rows[-1]
    return dict(rows=rows, **landed)


def refuses_third_deployer(session):
    batch = native_setup('blocked_tree')
    third = (1159, 100, 53)
    batch.put((1159, 100, 54), 'minecraft:slime_block')
    batch.put(third, 'create:deployer[facing=down,axis_along_first=false]'
              '{Mode:"USE",Inventory:[{Slot:0b,id:"minecraft:oak_sapling",count:3}]}')
    start(batch.command)
    batch.tick(8)
    for pos in (DEPLOYER, FERTILIZER, third):
        batch.expect(pos, 'create:deployer')
    batch.data(PIVOT)
    batch.data(third)
    batch.data(CHEST)
    rows = batch.run(session, 'three-deployers-refused')
    assert all('bearing_check' in raw for raw in rows[:3]), rows
    assert number({'nbt': rows[3]}, 'Running', 0) == 0, rows
    assert SAPLING in rows[4] and 'count:3' in rows[4].replace(' ', ''), rows
    assert stock([None, None], chest_slots(rows[5]))['totals'] == STOCK, rows
    assert read_mounted(session, CARGO) is None
    return True


def native_review(args):
    reference = json.loads(args.reference.read_text())
    assert reference['passed'] and reference['create'] == PINS['create_revision'], args.reference
    session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                 name='deployer-moving-meal-native', graphics=False)
    print(session.scratch, flush=True)
    report = dict(passed=False, cases={})
    try:
        for case, split in (('wheat_and_plant', 3), ('blocked_tree', 76), ('open_tree', None)):
            session.world = case
            report['cases'][case] = native_case(session, case, reference['cases'][case], split)
        session.world = 'three-deployers-refused'
        report['third_actor_refused'] = refuses_third_deployer(session)
        report['passed'] = True
    finally:
        (session.scratch / 'result.json').write_text(json.dumps(report, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java:
        java_review()
    elif all((args.game, args.resources, args.ctl, args.reference)):
        native_review(args)
    else:
        parser.error('Pass --java or --game, --resources, --ctl and --reference')


if __name__ == '__main__':
    main()
