#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare finite mounted chest refill with the pinned Java Deployer."""
import argparse
import json
from pathlib import Path
import re
import tempfile

from deployer_farm_checks import (
    DEPLOYER, PIVOT, RING, SAPLING, Batch, NativeCheckSession, held_count, number,
    planted, setup as farm, start, stop, xyz,
)
from chain_drive_checks import Original
from common import PINS, ROOT
import reference_java as java

CHEST = (1159, 100, 56)
EXTRA_ROCK = (1159, 97, 53)
SAW = (1158, 100, 55)
SLOT_STOCK = {0: ('minecraft:oak_log', 4), 3: (SAPLING, 3), 8: (SAPLING, 2)}
PARTIAL = (10, (1159, 100, 53), (1160, 100, 55))
FULL = (40, DEPLOYER, CHEST)


def setup(command, *, filtered=True):
    farm(command, stock=2)
    command(f'setblock {xyz(EXTRA_ROCK)} minecraft:stone')
    if filtered:
        command(f'data merge block {xyz(DEPLOYER)} {{Filter:{{id:"{SAPLING}",count:1}},FilterAmount:64,UpTo:1b}}')
    items = ','.join(f'{{Slot:{slot}b,id:"{item}",count:{count}}}'
                     for slot, (item, count) in SLOT_STOCK.items() if filtered or item == SAPLING)
    command(f'setblock {xyz(CHEST)} minecraft:chest[facing=north]{{Items:[{items}]}}')


def chest_slots(raw):
    items = re.search(r'\bItems\s*:\s*\[(.*?)\]', raw)
    if not items:
        return {}
    slots = {}
    for nbt in re.findall(r'\{([^}]+)\}', items[1]):
        slot = re.search(r'\bSlot\s*:\s*(\d+)b', nbt)
        item = re.search(r'\bid\s*:\s*"([\w:]+)"', nbt)
        count = re.search(r'\bcount\s*:\s*(\d+)', nbt)
        assert slot and item and count, nbt
        slots[slot[1]] = [item[1], int(count[1])]
    return slots


def assert_stock(case, partial):
    if partial:
        assert len(case['planted']) == 3, case
        assert case['held'] == 1, case
        assert case['chest'] == {'0': ['minecraft:oak_log', 4], '3': [SAPLING, 2], '8': [SAPLING, 2]}, case
    else:
        assert len(case['planted']) == 8, case
        assert case['held'] == 0, case
        assert case['chest'] == {'0': ['minecraft:oak_log', 4]}, case
    assert [EXTRA_ROCK[0], EXTRA_ROCK[1] + 1, EXTRA_ROCK[2]] not in case['planted'], case


def java_review(base):
    java.BASE = base
    manifest = json.loads((base / 'manifest.json').read_text())
    assert manifest['create_sha256'] == java.CREATE_SHA256 and manifest['data_version'] == 3955
    host = Original()
    work = Path(tempfile.mkdtemp(prefix='deployer-refill-java-', dir=ROOT / '.local'))
    report = dict(passed=False, create=PINS['create_revision'], cases={})
    try:
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        host.command('tp @s 1156.5 98 60.5')
        host.command('forceload add 1152 48 1167 63')
        host.call('observe_ticks', {'ticks': 24, 'positions': [PIVOT]})
        for name, (ticks, deployer, chest) in [('blocked_refill', PARTIAL), ('exhaustion', FULL)]:
            setup(host.command)
            start(host.command)
            observed = host.call('observe_ticks', {'ticks': ticks, 'positions': [PIVOT, *RING]})['samples']
            trace = [dict(tick=s['tick'], angle=number(s['blocks'][0], 'Angle'),
                          planted=planted(s['blocks'][1:])) for s in observed]
            stop(host.command)
            final = host.call('observe_ticks', {'ticks': 2, 'positions': [PIVOT, *RING, deployer, chest]})['samples'][-1]['blocks']
            assert number(final[0], 'Running') == 0, final[0]
            assert [entry['id'] for entry in final[-2:]] == ['create:deployer', 'minecraft:chest'], final[-2:]
            case = dict(trace=trace, planted=planted(final[1:-2]), held=held_count(final[-2]['nbt']),
                        chest=chest_slots(final[-1]['nbt']))
            report['cases'][name] = case
            assert_stock(case, name == 'blocked_refill')
        report['passed'] = True
    finally:
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
        print(json.dumps(dict(result=str(work / 'result.json'), passed=report['passed'])))


def native_setup(*, filtered=True):
    batch = Batch()
    batch.load((1157, 98, 60))
    batch.command('gamerule minecraft:random_tick_speed 0')
    setup(batch.command, filtered=filtered)
    start(batch.command)
    return batch


def native_case(session, name, spec, reference, *, filtered=True):
    ticks, deployer, chest = spec
    batch = native_setup(filtered=filtered)
    for _ in range(ticks):
        batch.tick()
        batch.data(PIVOT)
        for pos in RING:
            batch.expect(pos, SAPLING)
    stop(batch.command)
    batch.tick(2)
    batch.data(PIVOT)
    batch.data(deployer)
    batch.data(chest)
    rows = batch.run(session, name)
    stride = 1 + len(RING)
    assert len(rows) == ticks * stride + 3, len(rows)
    trace = []
    for i in range(ticks):
        row = rows[i * stride:(i + 1) * stride]
        trace.append(dict(tick=i + 1, angle=number({'nbt': row[0]}, 'Angle', 0),
                          planted=[list(pos) for pos, cell in zip(RING, row[1:], strict=True)
                                   if 'bearing_check' in cell]))
    assert trace == reference['trace'], next(((i, a, b) for i, (a, b) in enumerate(
        zip(trace, reference['trace'], strict=True), 1) if a != b), None)
    assert number({'nbt': rows[-3]}, 'Running') == 0, rows[-3:]
    assert ('Filter' in rows[-2]) == filtered, rows[-2]
    case = dict(trace=trace, planted=trace[-1]['planted'], held=held_count(rows[-2]), chest=chest_slots(rows[-1]))
    assert case == reference, (case, reference)
    return case


def native_restart(session, reference, resume):
    batch = native_setup()
    batch.tick(PARTIAL[0])
    batch.data(PIVOT)
    batch.expect(DEPLOYER, 'minecraft:air')
    batch.expect(CHEST, 'minecraft:air')
    active = batch.run(session, 'saved-with-one-refilled-sapling')
    assert number({'nbt': active[0]}, 'Running') == 1 and number({'nbt': active[0]}, 'Angle') == 86.399994, active
    assert all('bearing_check' in row for row in active[1:]), active
    batch = Batch()
    batch.load((1157, 98, 60))
    batch.data(PIVOT)
    if resume:
        batch.tick(FULL[0] - PARTIAL[0])
    _, deployer, chest = FULL if resume else PARTIAL
    stop(batch.command)
    batch.tick(2)
    batch.data(PIVOT)
    batch.data(deployer)
    batch.data(chest)
    for pos in RING:
        batch.expect(pos, SAPLING)
    landed = batch.run(session, 'restored-after-restart')
    assert number({'nbt': landed[0]}, 'Running') == 1, landed[0]
    assert number({'nbt': landed[1]}, 'Running') == 0, landed[1]
    case = dict(held=held_count(landed[2]), chest=chest_slots(landed[3]),
                planted=[list(pos) for pos, cell in zip(RING, landed[4:], strict=True) if 'bearing_check' in cell])
    for field, value in case.items():
        assert value == reference[field], (field, value, reference[field])
    return case


def native_farm_cycle(session, reference):
    batch = native_setup()
    batch.put(SAW, 'create:mechanical_saw[facing=south,axis_along_first=false,flipped=false]')
    trunk = [(1158, y, 56) for y in range(100, 103)]
    for pos in trunk:
        batch.put(pos, 'minecraft:oak_log[axis=y]')
    batch.tick(150)
    for pos in trunk:
        batch.expect(pos, 'minecraft:air')
    stop(batch.command)
    batch.tick(2)
    batch.data(PIVOT)
    for pos in RING:
        batch.expect(pos, SAPLING)
    chests = (CHEST, (1160, 100, 55), (1159, 100, 54), (1158, 100, 55))
    for pos in chests:
        batch.data(pos)
    rows = batch.run(session, 'moving-saw-and-deployer')
    assert all('bearing_check' in row for row in rows[:len(trunk)]), rows
    assert number({'nbt': rows[len(trunk)]}, 'Running') == 0, rows
    field = [list(pos) for pos, cell in zip(RING, rows[len(trunk) + 1:-len(chests)], strict=True)
             if 'bearing_check' in cell]
    assert field == reference['planted'], (field, reference['planted'])
    inventories = [slots for raw in rows[-len(chests):] if (slots := chest_slots(raw))]
    assert len(inventories) == 1 and inventories[0] == {'0': ['minecraft:oak_log', 7]}, inventories
    return dict(planted=field, trunk_blocks_cut=len(trunk), chest=inventories[0])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', type=Path)
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--combined', action='store_true', help='also check the moving saw and Deployer together')
    args = parser.parse_args()
    if args.java:
        java_review(args.java.resolve())
        return
    if not all((args.game, args.resources, args.ctl, args.reference)):
        parser.error('Pass --java or --game, --resources, --ctl and --reference')
    reference = json.loads(args.reference.read_text())
    assert reference['passed'] and reference['create'] == PINS['create_revision'], args.reference
    session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                 name='deployer-refill-native', world='DeployerRefillBlocked', graphics=False)
    print(session.scratch, flush=True)
    report = dict(passed=False)
    try:
        report['blocked_refill'] = native_case(session, 'blocked_refill', PARTIAL, reference['cases']['blocked_refill'])
        session.world = 'DeployerRefillExhaustion'
        report['exhaustion'] = native_case(session, 'exhaustion', FULL, reference['cases']['exhaustion'])
        session.world = 'DeployerRefillUnfiltered'
        unfiltered = dict(reference['cases']['exhaustion'], chest={})
        report['unfiltered_saplings'] = native_case(session, 'unfiltered', FULL, unfiltered, filtered=False)
        session.world = 'DeployerRefillStoppedAfterRestart'
        report['restarted_stop'] = native_restart(session, reference['cases']['blocked_refill'], False)
        session.world = 'DeployerRefillResumed'
        report['restarted_resume'] = native_restart(session, reference['cases']['exhaustion'], True)
        if args.combined:
            session.world = 'SawDeployerCycle'
            report['saw_and_deployer'] = native_farm_cycle(session, reference['cases']['exhaustion'])
        report['passed'] = True
    finally:
        (session.scratch / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        session.control_temp.cleanup()
        print(json.dumps(dict(result=str(session.scratch / 'result.json'), passed=report['passed'])))


if __name__ == '__main__':
    main()
