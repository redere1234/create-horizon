#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Record Chute insertion into an ordinary chest on a docked bearing."""

import argparse
import json
from pathlib import Path
import re
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import items, number
from chain_drive_checks import Original, xyz
from chute_reference_checks import CHUTE, scalar
from common import PINS, ROOT
from native_check_session import NativeCheckSession
import portable_storage_reference_checks as psi
import reference_java as java

SHIFT = 32
CASES = ('merge_first', 'partial', 'full', 'components', 'power_interrupt')
SAPLING = 'minecraft:oak_sapling'
STONE = 'minecraft:stone'
CHEST = 'minecraft:chest[facing=north,type=single,waterlogged=false]'
AIR = 'minecraft:air'


def shift(pos):
    return (pos[0] + SHIFT, pos[1], pos[2])


PIVOT, MOTOR, STATION, MOUNTED, SWITCH = map(
    shift, (psi.PIVOT, psi.MOTOR, psi.STATION, psi.MOUNTED, psi.SWITCH),
)
X, Y, Z = PIVOT
CHUTE_POS = (STATION[0], STATION[1] + 1, STATION[2])
INPUT = (STATION[0], STATION[1] + 2, STATION[2])
POINTS = (PIVOT, STATION, CHUTE_POS, INPUT)
LANDING = tuple((X + dx, Y + 1, Z + dz) for dx, dz in ((-1, 0), (0, 1), (1, 0), (0, -1)))
CONTRAPTION = f'@e[type=create:stationary_contraption,x={X},y={Y},z={Z},distance=..10]'
CLEAR = f'fill {X - 6} {Y - 3} {Z - 7} {X + 5} {Y + 5} {Z + 5} {AIR}'
TICKS = 90


def rig(put, command, case):
    put(PIVOT, 'create:mechanical_bearing[facing=up]')
    put((X, Y + 1, Z), 'minecraft:slime_block')
    put((X + 1, Y + 1, Z), 'minecraft:slime_block')
    put(shift(psi.MOVING), f'{psi.BLOCK}[facing=east]')
    put(MOUNTED, CHEST)
    put(STATION, f'{psi.BLOCK}[facing=south]')
    put(CHUTE_POS, CHUTE)
    put(INPUT, CHEST)
    if case in ('partial', 'full'):
        command(f'data merge block {xyz(MOUNTED)} {{Items:[' +
                ','.join(f'{{Slot:{slot}b,id:"{STONE}",count:64}}' for slot in range(27)) + ']}')
    if case in ('merge_first', 'partial', 'components'):
        command(f'item replace block {xyz(MOUNTED)} container.5 with {SAPLING} 60')
    mark = '[minecraft:custom_data={psi_feed:230}]' if case == 'components' else ''
    command(f'item replace block {xyz(INPUT)} container.0 with {SAPLING}{mark} 16')


def read(rows):
    bearing, station, chute, source = rows
    return dict(angle=number({'nbt': bearing}, 'Angle', 0),
                timer=number({'nbt': station}, 'Timer'),
                powered=number({'nbt': station}, 'Powered'),
                item=items(chute, 'Item'), position=scalar(chute, 'ItemPosition'),
                source=items(source, 'Items'))


def slot_counts(raw):
    container = re.search(r'\bItems\s*:\s*\[(.*?)\]', raw)
    assert container, raw
    stacks = re.finditer(r'\{((?:[^{}]|\{(?:[^{}]|\{[^{}]*\})*\})*)\}', container[1])
    return {int(re.search(r'\bSlot\s*:\s*(\d+)b', match[1])[1]): (
        re.search(r'\bid\s*:\s*"([^"]+)"', match[1])[1],
        int(re.search(r'\bcount\s*:\s*(\d+)', match[1])[1]),
        'psi_feed:230' in re.sub(r'\s+', '', match[1]),
    ) for match in stacks}


def verify(case, samples, landed):
    slots = slot_counts(landed)
    resets = [tick for tick, row in enumerate(samples, 1) if row['timer'] == 64]
    if case == 'merge_first':
        assert slots == {0: (SAPLING, 12, False), 5: (SAPLING, 64, False)}, slots
    elif case == 'partial':
        assert len(slots) == 27 and slots[5] == (SAPLING, 64, False), slots
        assert samples[-1]['item'] == {SAPLING: 12}, samples[-1]
        assert samples[-1]['position'] == 0.5, samples[-1]
    elif case == 'full':
        assert len(slots) == 27 and all(v == (STONE, 64, False) for v in slots.values()), slots
        assert samples[-1]['item'] == {SAPLING: 16}, samples[-1]
        assert samples[-1]['position'] == 0.5, samples[-1]
    elif case == 'components':
        assert slots == {0: (SAPLING, 16, True), 5: (SAPLING, 60, False)}, slots
    else:
        assert not slots and samples[-1]['item'] == {SAPLING: 16}, (slots, samples[-1])
    assert all(not row['source'] for row in samples[2:]), samples[:3]
    assert len(resets) == (0 if case in ('full', 'power_interrupt') else 1), resets
    if case in ('merge_first', 'components'):
        assert not samples[-1]['item'], samples[-1]
    return resets


def java_reference():
    manifest = json.loads((java.BASE / 'manifest.json').read_text())
    assert manifest['data_version'] == 3955 and manifest['create_sha256'] == java.CREATE_SHA256
    host = Original()
    work = Path(tempfile.mkdtemp(prefix='portable-chute-input-java-', dir=ROOT / '.local'))
    report = dict(passed=False, create=PINS['create_revision'], cases={})

    def command(text):
        return host.command(text)

    def put(pos, block):
        command(f'setblock {xyz(pos)} {block}')

    def observe(ticks, positions=POINTS):
        return host.call('observe_ticks', {'ticks': ticks, 'positions': positions})['samples']

    try:
        assert host.call('state', {})['data_version'] == 3955
        host.call('tick', {'frozen': True})
        command('gamemode creative')
        command(f'tp @s {X}.5 {Y + 8} {Z}.5')
        command(f'forceload add {X} {Z}')
        observe(24)
        for case in CASES:
            command(f'kill {CONTRAPTION}')
            command(CLEAR)
            rig(put, command, case)
            observe(3)
            put(MOTOR, 'create:creative_motor[facing=up]{ScrollValue:32}')
            if case == 'power_interrupt':
                rows = observe(11)
                put(SWITCH, 'minecraft:redstone_block')
                rows += observe(TICKS - len(rows))
            else:
                rows = observe(TICKS)
            samples = [read([block['nbt'] for block in row['blocks']]) for row in rows]
            put(MOTOR, AIR)
            after = observe(4, LANDING)[-1]['blocks']
            candidates = [(p, b['nbt']) for p, b in zip(LANDING, after, strict=True)
                          if b['id'] == 'minecraft:chest']
            assert len(candidates) == 1, after
            pos, landed = candidates[0]
            data = dict(rows=samples, landed=landed, landing=pos)
            report['cases'][case] = data
            data['reset_ticks'] = verify(case, samples, landed)
        report['passed'] = True
    finally:
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
        print(work / 'result.json', flush=True)
        command(f'kill {CONTRAPTION}')
        command(f'forceload remove {X} {Z}')
        host.call('tick', {'frozen': False})


def prepare_native(batch, case):
    batch.load((X, Y + 8, Z))
    batch.command(CLEAR)
    rig(batch.put, batch.command, case)
    batch.tick(3)
    batch.put(MOTOR, 'create:creative_motor[facing=up]{ScrollValue:32}')


def compare(expected, rows):
    differences = []
    for tick, (java, native) in enumerate(zip(expected, rows, strict=True), 1):
        fields = [key for key in ('timer', 'item', 'powered', 'source') if native[key] != java[key]]
        fields += [key for key in ('angle', 'position') if abs(native[key] - java[key]) > 0.0002]
        if fields:
            differences.append(dict(tick=tick, fields=fields, java=java, native=native))
    return differences


def native(session, reference):
    report = dict(passed=False, create=PINS['create_revision'], cases={})
    path = session.scratch / 'result.json'
    try:
        for case, java in reference.items():
            batch = Batch()
            prepare_native(batch, case)
            for i in range(len(java['rows'])):
                if i == 11 and case == 'power_interrupt':
                    batch.put(SWITCH, 'minecraft:redstone_block')
                batch.tick()
                for pos in POINTS:
                    batch.data(pos)
            batch.put(MOTOR, AIR)
            batch.tick(4)
            batch.data(java['landing'])
            *text, landed = batch.run(session, 'portable-chute-input-' + case)
            assert len(text) == len(POINTS) * len(java['rows']), len(text)
            rows = [read(text[i:i + len(POINTS)]) for i in range(0, len(text), len(POINTS))]
            differences = compare(java['rows'], rows)
            report['cases'][case] = dict(samples=len(rows), differences=differences, landed=landed)
            assert not differences, (case, differences[:3])
            assert slot_counts(landed) == slot_counts(java['landed']), (case, landed, java['landed'])
            verify(case, rows, landed)

        # The partial transfer and remainder already exist on disk. Restart the
        # real headless client with the same private world and land the chest.
        batch = Batch()
        prepare_native(batch, 'partial')
        batch.tick(13)
        batch.data(CHUTE_POS)
        before, = batch.run(session, 'portable-chute-input-save')
        assert items(before, 'Item') == {SAPLING: 12}, before
        batch = Batch()
        batch.load((X, Y + 8, Z))
        batch.put(MOTOR, AIR)
        batch.tick(4)
        batch.data(CHUTE_POS)
        batch.data((X, Y + 1, Z + 1))
        remainder, landed = batch.run(session, 'portable-chute-input-restart')
        assert items(remainder, 'Item') == {SAPLING: 12}, remainder
        assert len(slot_counts(landed)) == 27 and slot_counts(landed)[5] == (SAPLING, 64, False), landed
        report['restart'] = dict(remainder=remainder, landed=landed)
        report['passed'] = True
    finally:
        session.control_temp.cleanup()
        path.write_text(json.dumps(report, indent=2) + '\n')
        print(path, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for option in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + option, type=Path)
    args = parser.parse_args()
    if args.java:
        java_reference()
        return
    if not all((args.game, args.resources, args.ctl, args.reference)):
        parser.error('Specify --java or all native fixture arguments')
    reference = json.loads(args.reference.read_text())
    assert reference['passed'] and reference['create'] == PINS['create_revision']
    session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                 name='portable-chute-input', graphics=False, world='ChuteInput')
    print(session.scratch, flush=True)
    native(session, reference['cases'])


if __name__ == '__main__':
    main()
