#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare a Mechanical Bearing's single closed barrel in Java and Horizon."""

import argparse
import errno
import json
from pathlib import Path
import re
import shutil
import tempfile

from bearing_native_checks import Batch
from bearing_reference_checks import offset
from burner_heat_java_checks import field, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession


AIR = 'minecraft:air'
BARREL = 'minecraft:barrel'
SLIME = 'minecraft:slime_block'
ROOM = '1137 126 241 1150 147 254'
FORCE = '1136 240 1151 255'
CAMERA = (1143, 137, 248)
STICK = 'minecraft:stick[minecraft:custom_data={barrel_probe:173}] 11'
LOOSE = ('execute if entity @e[type=minecraft:item,x=1137,y=126,z=241,dx=13,dy=21,dz=13]'
         ' run say barrel_loose')


def state(facing, open='false'):
    return f'{BARREL}[facing={facing},open={open}]'


class Rig:
    def __init__(self, pivot, facing, axis, from_side, to_side, original, rotated):
        self.pivot = pivot
        self.anchor = offset(pivot, axis)
        self.motor = offset(pivot, axis, -1)
        self.source = offset(self.anchor, from_side)
        self.target = offset(self.anchor, to_side)
        self.facing = facing
        self.original = original
        self.rotated = rotated

    def setup(self, command, put):
        put(self.pivot, f'create:mechanical_bearing[facing={self.facing}]')
        put(self.anchor, SLIME)
        put(self.source, state(self.original))
        command(f'item replace block {xyz(self.source)} container.0 with minecraft:diamond 7')
        command(f'item replace block {xyz(self.source)} container.26 with {STICK}')
        put(self.motor, f'create:creative_motor[facing={self.facing}]{{ScrollValue:32}}')

    def positions(self):
        return (self.pivot, self.anchor, self.source, self.target)


RIGS = (
    Rig((1141, 130, 245), 'east', (1, 0, 0), (0, 0, 1), (0, -1, 0), 'up', 'south'),
    Rig((1148, 130, 251), 'up', (0, 1, 0), (1, 0, 0), (0, 0, -1), 'north', 'west'),
)
POINTS = [pos for rig in RIGS for pos in rig.positions()]
GUARDS = (
    (1140, state('up', 'true'), '', None),
    (1143, state('up'), '{CustomName:"Test barrel"}', 'Test barrel'),
    (1146, state('up'), '{lock:{items:"minecraft:diamond"}}', 'lock:'),
    (1149, state('up'), '{LootTable:"minecraft:chests/simple_dungeon",LootTableSeed:41L}', 'LootTable:'),
)


def pose(raw):
    nbt = {'nbt': raw}
    return [number(nbt, 'Running', 0), number(nbt, 'Angle', 0)]


def inventory(raw):
    cargo = field(raw, 'Items')
    slots = map(int, re.findall(r'\bSlot\s*:\s*(\d+)b', cargo))
    ids = re.findall(r'\bid\s*:\s*"([^"]+)"', cargo)
    counts = map(int, re.findall(r'\bcount\s*:\s*(\d+)', cargo))
    stacks = sorted([slot, item, count] for slot, item, count in zip(slots, ids, counts, strict=True))
    assert stacks == [[0, 'minecraft:diamond', 7], [26, 'minecraft:stick', 11]], raw
    assert 'barrel_probe:173' in cargo.replace(' ', ''), raw
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

    try:
        host.command('gamemode creative')
        host.command(f'tp @s {CAMERA[0]}.5 {CAMERA[1] + 1} {CAMERA[2]}.5')
        host.command('forceload add ' + FORCE)
        host.snapshot(POINTS, 25)
        host.command('fill ' + ROOM + ' ' + AIR)
        for rig in RIGS:
            rig.setup(host.command, put)
        captured = host.snapshot(POINTS, 10)
        moving = host.snapshot(POINTS, 1)
        for rig in RIGS:
            put(rig.motor, AIR)
        landed = host.snapshot(POINTS, 1)
        cases = []
        for i, rig in enumerate(RIGS):
            start, end = i * 4, (i + 1) * 4
            assert [block['block'] for block in captured[start + 1:end]] == [AIR] * 3, captured
            assert [block['block'] for block in moving[start + 1:end]] == [AIR] * 3, moving
            assert [block['block'] for block in landed[start + 1:end]] == [SLIME, AIR, BARREL], landed
            assert landed[end - 1]['properties'] == dict(facing=rig.rotated, open='false'), landed
            assert pose(captured[start]['nbt']) == [1, 86.399994], captured
            assert pose(moving[start]['nbt']) == [1, 95.99999], moving
            assert pose(landed[start]['nbt']) == [0, 0], landed
            cases.append(dict(captured=pose(captured[start]['nbt']), moving=pose(moving[start]['nbt']),
                              landed=pose(landed[start]['nbt']), items=inventory(landed[end - 1]['nbt'])))
        assert not any('barrel_loose' in row for row in host.command(LOOSE)['messages']), host.trace[-1]
        return cases
    finally:
        host.command('fill ' + ROOM + ' ' + AIR)
        host.command('forceload remove ' + FORCE)
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def check_blocks(rows):
    assert all('bearing_check' in row for row in rows), rows


def native_run(session, expected):
    batch = Batch()
    batch.load(CAMERA)
    batch.command('fill ' + ROOM + ' ' + AIR)
    for rig in RIGS:
        rig.setup(batch.command, batch.put)
    for x, block, extra, _ in GUARDS:
        batch.put((x, 140, 245), 'create:mechanical_bearing[facing=up]')
        batch.put((x, 141, 245), block + extra)
        batch.put((x, 139, 245), 'create:creative_motor[facing=up]{ScrollValue:32}')
    batch.tick(10)
    for rig in RIGS:
        batch.data(rig.pivot)
        for pos in (rig.anchor, rig.source, rig.target):
            batch.expect(pos, AIR)
    for x, block, _, _ in GUARDS:
        batch.data((x, 140, 245))
        batch.expect((x, 141, 245), block)
        batch.data((x, 141, 245))
    before = batch.run(session, 'barrels-before-restart')
    for i, case in enumerate(expected):
        assert pose(before[i * 4]) == case['captured'], before
        check_blocks(before[i * 4 + 1:(i + 1) * 4])
    guards = before[len(RIGS) * 4:]
    assert len(guards) == len(GUARDS) * 3 and all(pose(row) == [0, 0] for row in guards[::3]), guards
    check_blocks(guards[1::3])
    for row, (_, _, _, marker) in zip(guards[2::3], GUARDS, strict=True):
        assert marker is None or marker in row, row

    batch = Batch()
    batch.load(CAMERA)
    for rig in RIGS:
        batch.data(rig.pivot)
        for pos in (rig.anchor, rig.source, rig.target):
            batch.expect(pos, AIR)
    batch.tick()
    for rig in RIGS:
        batch.data(rig.pivot)
        batch.put(rig.motor, AIR)
    batch.tick()
    for rig in RIGS:
        batch.data(rig.pivot)
        batch.expect(rig.anchor, SLIME)
        batch.expect(rig.source, AIR)
        batch.expect(rig.target, state(rig.rotated))
        batch.data(rig.target)
    batch.command(LOOSE, True)
    after = batch.run(session, 'barrels-after-restart')
    assert 'barrel_loose' not in after[-1], after
    cases = []
    for i, case in enumerate(expected):
        assert pose(after[i * 4]) == case['captured'], after
        check_blocks(after[i * 4 + 1:(i + 1) * 4])
        moving = pose(after[len(RIGS) * 4 + i])
        start = len(RIGS) * 5 + i * 5
        check_blocks(after[start + 1:start + 4])
        actual = dict(captured=pose(before[i * 4]), moving=moving, landed=pose(after[start]),
                      items=inventory(after[start + 4]))
        assert actual == case, (actual, case)
        cases.append(actual)
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='bearing-barrel-java-', dir=ROOT / '.local'))
        cases = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon runs require --game, --resources, --ctl and --reference')
        expected = json.loads(args.reference.read_text())
        assert expected['passed'] and expected['create'] == PINS['create_revision'], expected
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='bearing-barrel-native', graphics=False, world='CreateBearingBarrel')
        work = session.scratch
        try:
            cases = native_run(session, expected['cases'])
        finally:
            session.control_temp.cleanup()
            try:
                shutil.rmtree(session.resources)
            except OSError as error:
                if error.errno != errno.ENOTEMPTY:
                    raise
                shutil.rmtree(session.resources)
    report = dict(passed=True, create=PINS['create_revision'], cases=cases)
    if not args.java:
        report.update(cold_restart=True, rejected=['open', 'named', 'locked', 'loot_table'])
    output = work / 'result.json'
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(output)


if __name__ == '__main__':
    main()
