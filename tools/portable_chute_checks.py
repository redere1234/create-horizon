#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Observe a Chute pulling from the original item Portable Storage Interface."""

import argparse
import json
from pathlib import Path
import tempfile

from actor_native_checks import matched
from bearing_native_checks import Batch
from burner_heat_java_checks import items, number
from chain_drive_checks import Original, xyz
from chute_reference_checks import CHUTE, scalar
from common import PINS, ROOT
from native_check_session import NativeCheckSession
import portable_storage_reference_checks as psi


SHIFT = 16
TICKS = 116


def shift(pos):
    return (pos[0] + SHIFT, pos[1], pos[2])


POINTS = tuple(map(shift, (psi.PIVOT, psi.STATION, psi.HOPPER, psi.OUTPUT)))
COMPARATOR, WIRE = shift(psi.COMPARATOR), shift(psi.WIRE)
X, Y, Z = POINTS[0]
CONTRAPTION = f'@e[type=create:stationary_contraption,x={X},y={Y},z={Z},distance=..10]'
CLEAR = f'fill {X - 6} {Y - 3} {Z - 7} {X + 5} {Y + 5} {Z + 5} {psi.AIR}'


def fixture(put, command):
    psi.rig(lambda pos, block: put(shift(pos), CHUTE if pos == psi.HOPPER else block),
            lambda text: command(text.replace(xyz(psi.MOUNTED), xyz(shift(psi.MOUNTED)), 1)))
    mounted = xyz(shift(psi.MOUNTED))
    for slot, count in [(5, 10), (7, 12)]:
        command(f'item replace block {mounted} container.{slot} with minecraft:wheat {count}')


def observe_nbt(rows):
    bearing, station, chute, output = rows
    return dict(angle=number({'nbt': bearing}, 'Angle', 0), timer=number({'nbt': station}, 'Timer'),
                distance=number({'nbt': station}, 'Distance'), item=items(chute, 'Item'),
                position=scalar(chute, 'ItemPosition'), output=items(output, 'Items'),
                component='psi_probe:173' in output.replace(' ', ''))


def verify_reference(rows):
    resets = [tick for tick, row in enumerate(rows, 1) if row['timer'] == 64]
    assert resets == [11, 18, 25], resets
    assert [rows[i - 1]['item'] for i in resets] == [
        {'minecraft:wheat': 16}, {'minecraft:wheat': 6}, {'minecraft:stick': 2},
    ]
    assert rows[16]['output'] == {'minecraft:wheat': 16}
    assert rows[23]['output'] == {'minecraft:wheat': 22}
    assert rows[30]['output'] == {'minecraft:wheat': 22, 'minecraft:stick': 2}
    assert rows[-1]['output'] == rows[30]['output'] and rows[-1]['component']
    assert rows[84]['timer'] == 4 and rows[85]['angle'] > rows[84]['angle']
    assert rows[12]['wire'] == 15 and rows[-1]['wire'] == 0


def java_reference():
    host = Original()
    work = Path(tempfile.mkdtemp(prefix='portable-chute-java-', dir=ROOT / '.local'))
    loaded = False

    def put(pos, state):
        host.command(f'setblock {xyz(pos)} {state}')

    try:
        assert host.call('state', {})['data_version'] == 3955
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        host.command(f'tp @s {X}.5 {Y + 8} {Z}.5')
        host.command('forceload add 1408 144 1423 159')
        loaded = True
        host.call('observe_ticks', {'ticks': 24, 'positions': [POINTS[0]]})
        host.command(f'kill {CONTRAPTION}')
        host.command(CLEAR)
        fixture(put, host.command)
        host.call('observe_ticks', {'ticks': 3, 'positions': [POINTS[0]]})
        put(shift(psi.MOTOR), 'create:creative_motor[facing=up]{ScrollValue:32}')
        samples = host.call('observe_ticks', {
            'ticks': TICKS, 'positions': [*POINTS, COMPARATOR, WIRE],
        })['samples']
        rows = []
        for sample in samples:
            *blocks, comparator, wire = sample['blocks']
            row = observe_nbt([block['nbt'] for block in blocks])
            row['comparator'] = comparator['properties']['powered'].lower() == 'true'
            row['wire'] = int(wire['properties']['power'])
            rows.append(row)
        path = work / 'result.json'
        path.write_text(json.dumps(dict(create=PINS['create_revision'], rows=rows), indent=2) + '\n')
        verify_reference(rows)
        return path
    finally:
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
        if loaded:
            host.command(f'kill {CONTRAPTION}')
            host.command('forceload remove 1408 144 1423 159')


def native_setup(batch):
    batch.load((X, Y + 8, Z))
    batch.command(CLEAR)
    fixture(batch.put, batch.command)
    batch.tick(3)
    batch.put(shift(psi.MOTOR), 'create:creative_motor[facing=up]{ScrollValue:32}')


def native(session, reference):
    batch = Batch()
    native_setup(batch)
    for row in reference:
        batch.tick()
        for pos in POINTS:
            batch.data(pos)
        batch.expect(COMPARATOR, f'minecraft:comparator[powered={str(row["comparator"]).lower()}]')
        batch.expect(WIRE, f'minecraft:redstone_wire[power={row["wire"]}]')
    observed = batch.run(session, 'portable-chute')
    assert len(observed) == 6 * len(reference), len(observed)
    errors = []
    for i, expected in enumerate(reference):
        row = observed[i * 6:(i + 1) * 6]
        actual = observe_nbt(row[:4])
        fields = [key for key in ('timer', 'item', 'output', 'component') if actual[key] != expected[key]]
        fields += [key for key in ('angle', 'distance', 'position') if abs(actual[key] - expected[key]) > 0.0002]
        fields += [key for key, value in zip(('comparator', 'wire'), row[4:]) if not matched(value)]
        if fields:
            errors.append(dict(tick=i + 1, fields=fields, actual=actual, expected=expected))
    path = session.scratch / 'result.json'
    path.write_text(json.dumps(dict(samples=len(reference), differences=errors), indent=2) + '\n')
    assert not errors, (path, errors[:4])
    return path


def restart(session):
    batch = Batch()
    native_setup(batch)
    batch.tick(13)
    batch.data(POINTS[2])
    batch.data(POINTS[3])
    staged, empty = batch.run(session, 'portable-chute-moving-save')
    assert items(staged, 'Item') == {'minecraft:wheat': 16}, staged
    assert not items(empty, 'Items'), empty

    batch = Batch()
    batch.load((X, Y + 8, Z))
    batch.tick(220)
    batch.data(POINTS[2])
    batch.data(POINTS[3])
    empty, landed = batch.run(session, 'portable-chute-restart')
    assert not items(empty, 'Item'), empty
    assert items(landed, 'Items') == {'minecraft:wheat': 22, 'minecraft:stick': 2}, landed
    assert 'psi_probe:173' in landed.replace(' ', ''), landed
    path = session.scratch / 'result.json'
    path.write_text(json.dumps(dict(staged=staged, landed=landed), indent=2) + '\n')
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--restart', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        print(java_reference())
        return
    if not all((args.game, args.resources, args.ctl, args.reference)):
        parser.error('Specify --java or all native fixture arguments')
    reference = json.loads(args.reference.read_text())
    assert reference['create'] == PINS['create_revision']
    verify_reference(reference['rows'])
    session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                 name='portable-chute-native', graphics=False, world='CreatePortableChuteCheck')
    print(restart(session) if args.restart else native(session, reference['rows']))


if __name__ == '__main__':
    main()
