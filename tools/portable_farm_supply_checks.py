#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare the complete Chute, portable dock and moving Deployer chain."""
import argparse
import json
from pathlib import Path
import tempfile

from actor_native_checks import matched
from bearing_native_checks import Batch
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from deployer_farm_checks import held_count
from native_check_session import NativeCheckSession
from portable_chute_input_checks import (
    AIR, CLEAR, CONTRAPTION, LANDING, MOTOR, POINTS, SAPLING, X, Y, Z,
    compare, read, rig, slot_counts,
)


RING = [(x, Y - 1, z) for x in range(X - 2, X + 3) for z in range(Z - 2, Z + 3)
        if (x, z) != (X, Z)]
DEPLOYER = (X, Y + 1, Z + 1)
DEPLOYER_STATE = 'create:deployer[facing=down,axis_along_first=false]'


def original():
    host = Original()
    folder = Path(tempfile.mkdtemp(prefix='chute-to-deployer-java-', dir=ROOT / '.local'))
    report = {'passed': False, 'source': PINS['create_revision']}

    def put(pos, state):
        host.command(f'setblock {xyz(pos)} {state}')

    def observe(ticks, positions):
        return host.call('observe_ticks', {'ticks': ticks, 'positions': positions})['samples']

    try:
        assert host.call('state', {})['data_version'] == 3955
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        host.command(f'tp @s {X}.5 {Y+8} {Z}.5')
        host.command(f'forceload add {X} {Z}')
        observe(24, [POINTS[0]])
        host.command(f'kill {CONTRAPTION}')
        host.command(CLEAR)
        rig(put, host.command, 'farm')
        host.command(f'fill {X-2} {Y-2} {Z-2} {X+2} {Y-2} {Z+2} minecraft:dirt')
        host.command('gamerule randomTickSpeed 0')
        put(DEPLOYER, DEPLOYER_STATE)
        observe(3, POINTS)
        put(MOTOR, 'create:creative_motor[facing=up]{ScrollValue:32}')
        rows = []
        for sample in observe(125, [*POINTS, *RING]):
            blocks = sample['blocks']
            row = read([block['nbt'] for block in blocks[:len(POINTS)]])
            row['planted'] = [
                pos for pos, block in zip(RING, blocks[len(POINTS):], strict=True)
                if block['id'] == SAPLING
            ]
            rows.append(row)
        report['rows'] = rows
        put(MOTOR, AIR)
        final = observe(4, LANDING)[-1]['blocks']
        cargo = {block['id']: block for block in final
                 if block['id'] in ('minecraft:chest', 'create:deployer')}
        assert len(cargo) == 2, final
        slots = slot_counts(cargo['minecraft:chest']['nbt'])
        held = held_count(cargo['create:deployer']['nbt'])
        remaining = sum(count for _, count, _ in slots.values())
        row = rows[-1]
        assert not row['item'] and not row['source'] and len(row['planted']) > 0, row
        assert len(row['planted']) + held + remaining == 16, (row, held, slots)
        report.update(passed=True, chest=slots, held=held, remaining=remaining,
                      planted=row['planted'], landed=cargo)
    finally:
        (folder / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        print(folder / 'result.json', flush=True)
        host.command(f'kill {CONTRAPTION}')
        host.command(f'forceload remove {X} {Z}')
        host.call('tick', {'frozen': False})


def native(args):
    expected = json.loads(args.reference.read_text())
    assert expected['passed'] and expected['source'] == PINS['create_revision']
    session = NativeCheckSession(args.game, args.resources, args.ctl, None, graphics=False,
                                 name='chute-to-deployer-native', world='ChuteToDeployer')
    print(session.scratch, flush=True)
    result = {'passed': False}

    try:
        batch = Batch()
        batch.load((X, Y + 8, Z))
        batch.command(CLEAR)
        rig(batch.put, batch.command, 'farm')
        batch.command(f'fill {X-2} {Y-2} {Z-2} {X+2} {Y-2} {Z+2} minecraft:dirt')
        batch.command('gamerule minecraft:random_tick_speed 0')
        batch.put(DEPLOYER, DEPLOYER_STATE)
        batch.tick(3)
        batch.put(MOTOR, 'create:creative_motor[facing=up]{ScrollValue:32}')
        for row in expected['rows']:
            batch.tick()
            for pos in POINTS:
                batch.data(pos)
            planted = {tuple(pos) for pos in row['planted']}
            for pos in RING:
                batch.expect(pos,SAPLING if pos in planted else AIR)
        batch.put(MOTOR, AIR)
        batch.tick(4)
        for pos in LANDING:
            batch.data(pos)
        trace = batch.run(session, 'chute-to-deployer')
        observed, landed = trace[:-len(LANDING)], trace[-len(LANDING):]
        cargo = {kind: next(row for row in landed if f'id: "{kind}"' in row)
                 for kind in ('minecraft:chest', 'create:deployer')}
        slots = slot_counts(cargo['minecraft:chest'])
        held = held_count(cargo['create:deployer'])
        width = len(POINTS) + len(RING)
        rows = []
        mismatches = []
        for tick, offset in enumerate(range(0, len(observed), width), 1):
            row = observed[offset:offset + width]
            rows.append(read(row[:len(POINTS)]))
            missed = [pos for pos, reply in zip(RING, row[len(POINTS):], strict=True)
                      if not matched(reply)]
            if missed:
                mismatches.append(dict(tick=tick, positions=missed))
        diffs = compare(expected['rows'], rows)
        result.update(chute_differences=diffs, plant_differences=mismatches,
                      slots=slots, held=held, landed=cargo)
        assert not diffs and not mismatches, (diffs[:2], mismatches[:2])
        assert {str(slot): list(item) for slot, item in slots.items()} == expected['chest'], slots
        assert held == expected['held'], held
        result['passed'] = True
    finally:
        session.control_temp.cleanup()
        file = session.scratch / 'result.json'
        file.write_text(json.dumps(result, indent=2) + '\n')
        print(file, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for key in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + key, type=Path)
    args = parser.parse_args()
    if args.java:
        original()
    elif all((args.game, args.resources, args.ctl, args.reference)):
        native(args)
    else:
        parser.error('Horizon checks require --game, --resources, --ctl and --reference')


if __name__ == '__main__':
    main()
