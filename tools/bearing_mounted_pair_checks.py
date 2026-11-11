#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare two mounted item banks in a vertical Mechanical Bearing."""

import argparse
import errno
import json
from pathlib import Path
import re
import shutil
import tempfile

from bearing_barrel_checks import check_blocks, pose
from bearing_native_checks import Batch
from bearing_reference_checks import offset
from burner_heat_java_checks import field
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession
from saved_block_checks import read_saved_chunk_tag


AIR = 'minecraft:air'
SLIME = 'minecraft:slime_block'
BEARING = 'create:mechanical_bearing[facing=up]'
MOTOR = 'create:creative_motor[facing=up]{ScrollValue:32}'
ROOM = '1154 125 241 1166 157 254'
FORCE = '1152 240 1167 255'
STORAGE = ('horizon:attachments', 'create', 'mounted_item_storage', 'value')
CAMERA = (1160, 155, 247)
WEST, EAST, SOUTH, UP = (-1, 0, 0), (1, 0, 0), (0, 0, 1), (0, 1, 0)
CHEST = 'minecraft:chest[type=single,waterlogged=false,facing={}]'
BARREL = 'minecraft:barrel[open=false,facing={}]'
LOOSE = ('execute if entity @e[type=minecraft:item,x=1154,y=125,z=241,dx=12,dy=32,dz=13]'
         ' run say mounted_pair_loose')
BANK_ITEMS = (
    ((0, 'minecraft:diamond', 7, ''), (26, 'minecraft:stick', 11, '[minecraft:custom_data={first_bank:31}]')),
    ((3, 'minecraft:iron_ingot', 23, ''), (26, 'minecraft:diamond_pickaxe', 1, '[minecraft:damage=37]')),
)


def state(kind, landed=False):
    if kind == 'chest':
        return CHEST.format('west' if landed else 'north')
    return BARREL.format('north' if landed else 'east')


class Rig:
    def __init__(self, y, kinds, second_side):
        self.pivot = (1160, y, 247)
        self.anchor = offset(self.pivot, UP)
        self.motor = offset(self.pivot, UP, -1)
        self.locals = (WEST, second_side)
        self.kinds = kinds
        self.sources = tuple(offset(self.anchor, local) for local in self.locals)
        self.targets = tuple(offset(self.anchor, (z, v, -x)) for x, v, z in self.locals)
        self.empty = tuple(dict.fromkeys((self.anchor, *self.sources, *self.targets)))

    def setup(self, command, put):
        put(self.pivot, BEARING)
        put(self.anchor, SLIME)
        for pos, kind, items in zip(self.sources, self.kinds, BANK_ITEMS, strict=True):
            put(pos, state(kind))
            for slot, item, count, component in items:
                command(f'item replace block {xyz(pos)} container.{slot} with {item}{component} {count}')
        put(self.motor, MOTOR)

    def landed(self):
        layout = {pos: AIR for pos in self.empty}
        layout[self.anchor] = SLIME
        layout.update((pos, state(kind, True)) for pos, kind in zip(self.targets, self.kinds, strict=True))
        return layout


RIGS = (Rig(130, ('chest', 'barrel'), SOUTH), Rig(140, ('chest', 'chest'), EAST),
        Rig(150, ('barrel', 'barrel'), EAST))
POINTS = [p for rig in RIGS for p in (rig.pivot, *rig.empty)]
GUARDS = (
    (130, ((WEST, CHEST.format('north')), (EAST, 'minecraft:barrel[open=true,facing=east]'))),
    (150, ((WEST, CHEST.format('north')), (EAST, BARREL.format('east')), (UP, BARREL.format('up')))),
)


def verify_inventory(raw, index):
    cargo = field(raw, 'Items')
    slots = map(int, re.findall(r'\bSlot\s*:\s*(\d+)b', cargo))
    ids = re.findall(r'\bid\s*:\s*"([^"]+)"', cargo)
    counts = map(int, re.findall(r'\bcount\s*:\s*(\d+)', cargo))
    stacks = sorted([slot, item, count] for slot, item, count in zip(slots, ids, counts, strict=True))
    assert stacks == [list(entry[:3]) for entry in BANK_ITEMS[index]], raw
    assert ('first_bank:31' if index == 0 else '"minecraft:damage":37') in cargo.replace(' ', ''), raw
    return stacks


def java_run(work):
    host = Original()
    initial = host.call('state', {})
    if initial.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})

    def put(pos, block):
        host.command(f'setblock {xyz(pos)} {block}')

    def observe(ticks):
        return dict(zip(POINTS, host.snapshot(POINTS, ticks), strict=True))

    try:
        host.command('gamemode creative')
        host.command(f'tp @s {CAMERA[0]}.5 {CAMERA[1] + 1} {CAMERA[2]}.5')
        host.command('forceload add ' + FORCE)
        observe(25)
        host.command('fill ' + ROOM + ' ' + AIR)
        for rig in RIGS:
            rig.setup(host.command, put)
        captured = observe(10)
        cases = []
        for rig in RIGS:
            assert all(captured[pos]['block'] == AIR for pos in rig.empty), captured
            assert pose(captured[rig.pivot]['nbt']) == [1, 86.399994], captured
            x, y, z = rig.anchor
            selector = f'@e[type=create:stationary_contraption,x={x},y={y},z={z},distance=..3,limit=1]'
            reply = host.command(f'data get entity {selector} Contraption.items')
            raw = ' '.join(reply['messages'])
            locals_ = [tuple(map(int, row)) for row in re.findall(r'pos:\s*\[I;\s*(-?\d+),\s*(-?\d+),\s*(-?\d+)\]', raw)]
            assert locals_ == list(rig.locals), raw
            assert re.findall(r'\btype:\s*"(create:[^"]+)"', raw) == [
                'create:chest' if kind == 'chest' else 'create:simple' for kind in rig.kinds
            ], raw
            assert raw.count('size: 27') == 2 and 'first_bank: 31' in raw, raw
            cases.append(dict(captured=pose(captured[rig.pivot]['nbt']), order=[list(p) for p in locals_]))
        moving = observe(1)
        for rig in RIGS:
            put(rig.motor, AIR)
        landed = observe(1)
        for rig, case in zip(RIGS, cases, strict=True):
            case['moving'] = pose(moving[rig.pivot]['nbt'])
            assert case['moving'] == [1, 95.99999], moving
            case['landed'] = pose(landed[rig.pivot]['nbt'])
            assert case['landed'] == [0, 0], landed
            for pos, block in rig.landed().items():
                base, _, properties = block.partition('[')
                assert landed[pos]['block'] == base, landed
                if properties:
                    expected = dict(entry.split('=') for entry in properties.rstrip(']').split(','))
                    assert landed[pos]['properties'] == expected, landed[pos]
            case['items'] = [verify_inventory(landed[pos]['nbt'], i) for i, pos in enumerate(rig.targets)]
        assert not any('mounted_pair_loose' in line for line in host.command(LOOSE)['messages'])
        return cases
    finally:
        for rig in RIGS:
            put(rig.motor, AIR)
        observe(2)
        host.command('fill ' + ROOM + ' ' + AIR)
        host.command('forceload remove ' + FORCE)
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session, expected):
    batch = Batch()
    batch.load(CAMERA)
    batch.command('fill ' + ROOM + ' ' + AIR)
    for rig in RIGS:
        rig.setup(batch.command, batch.put)
    guards = []
    for y, banks in GUARDS:
        pivot = (1164, y, 252)
        anchor = offset(pivot, UP)
        cells = {anchor: SLIME, **{offset(anchor, side): block for side, block in banks}}
        batch.put(pivot, BEARING)
        for pos, block in cells.items():
            batch.put(pos, block)
            if pos != anchor:
                batch.command(f'item replace block {xyz(pos)} container.0 with minecraft:diamond 7')
        batch.put(offset(pivot, UP, -1), MOTOR)
        guards.append((pivot, cells))

    def capture(batch):
        for rig in RIGS:
            batch.data(rig.pivot)
            for pos in rig.empty:
                batch.expect(pos, AIR)

    def check_capture(rows):
        for rig, case in zip(RIGS, expected, strict=True):
            assert pose(next(rows)) == case['captured'], case
            check_blocks([next(rows) for _ in rig.empty])

    batch.tick(10)
    capture(batch)
    for pivot, cells in guards:
        batch.data(pivot)
        for pos, block in cells.items():
            batch.expect(pos, block)
            if block != SLIME:
                batch.data(pos)
    before = iter(batch.run(session, 'paired-storage-before-restart'))
    check_capture(before)
    for _, cells in guards:
        assert pose(next(before)) == [0, 0]
        for block in cells.values():
            check_blocks([next(before)])
            if block != SLIME:
                assert re.search(r'count:\s*7\b', next(before))
    assert next(before, None) is None

    saved = read_saved_chunk_tag(session.scratch, RIGS[0].pivot, STORAGE, session.world)['nbt']['value']
    assert saved['Version']['value'] == 2, saved
    banks = [entry['value'] for entry in saved['Chests']['value']]
    assert len(banks) == 2 * len(RIGS), banks
    for rig, case in zip(RIGS, expected, strict=True):
        pair = [entry for entry in banks if entry['Controller']['value'] == list(rig.pivot)]
        assert [entry['Pos']['value'] for entry in pair] == case['order'], pair
        for entry, expected_items in zip(pair, case['items'], strict=True):
            slots = [item['value'] for item in entry['Items']['value']]
            assert [[item[key]['value'] for key in ('Slot', 'id', 'count')] for item in slots] == expected_items

    batch = Batch()
    batch.load(CAMERA)
    capture(batch)
    batch.tick()
    for rig in RIGS:
        batch.data(rig.pivot)
        batch.put(rig.motor, AIR)
    blocked = RIGS[0].targets[1]
    batch.put(blocked, 'minecraft:obsidian')
    batch.tick()
    batch.data(RIGS[0].pivot)
    for pos in RIGS[0].empty:
        batch.expect(pos, 'minecraft:obsidian' if pos == blocked else AIR)
    batch.put(blocked, AIR)
    batch.tick()
    for rig in RIGS:
        batch.data(rig.pivot)
        for pos, block in rig.landed().items():
            batch.expect(pos, block)
        for pos in rig.targets:
            batch.data(pos)
    batch.command(LOOSE, True)
    after = iter(batch.run(session, 'paired-storage-after-restart'))
    check_capture(after)
    for case in expected:
        assert pose(next(after)) == case['moving'], case
    assert pose(next(after)) == expected[0]['moving']
    check_blocks([next(after) for _ in RIGS[0].empty])
    for rig, case in zip(RIGS, expected, strict=True):
        assert pose(next(after)) == case['landed'], case
        check_blocks([next(after) for _ in rig.landed()])
        assert [verify_inventory(next(after), i) for i, _ in enumerate(rig.targets)] == case['items']
    assert 'mounted_pair_loose' not in next(after)
    assert next(after, None) is None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='mounted-pair-java-', dir=ROOT / '.local'))
        cases = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon runs require --game, --resources, --ctl and --reference')
        expected = json.loads(args.reference.read_text())
        assert expected['passed'] and expected['create'] == PINS['create_revision'], expected
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='mounted-pair-native', graphics=False, world='CreateMountedPair')
        work = session.scratch
        cases = expected['cases']
        try:
            native_run(session, cases)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                if not folder.exists():
                    continue
                try:
                    shutil.rmtree(folder)
                except OSError as error:
                    if error.errno != errno.ENOTEMPTY:
                        raise
                    shutil.rmtree(folder)
    result = dict(passed=True, create=PINS['create_revision'], cases=cases)
    if not args.java:
        result.update(cold_restart=True, obstructed_retry=True, refusal=['open', 'three_banks'])
    output = work / 'result.json'
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(output)


if __name__ == '__main__':
    main()
