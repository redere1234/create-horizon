#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Collect the original controlled entity stall and controller angle per tick."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile

from actor_native_checks import matched
from bearing_native_checks import Batch
from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession

PIVOT = (1448, 148, 150)
MOTOR = (1448, 147, 150)
TARGET = (1449, 149, 149)
AIR = 'minecraft:air'
TICKS = 70
SCENES = {
    'saw': ('create:mechanical_saw[facing=north,axis_along_first=false,flipped=false]', 'minecraft:oak_log[axis=y]'),
    'drill': ('create:mechanical_drill[facing=north]', 'minecraft:oak_planks'),
}


def motor():
    return 'create:creative_motor[facing=up]{ScrollValue:32}'


def put(command, pos, block):
    command(f'setblock {xyz(pos)} {block}')


def setup(command, block, target):
    command('fill 1444 147 145 1454 153 155 minecraft:air')
    put(command, PIVOT, 'create:mechanical_bearing[facing=up]')
    put(command, (1448, 149, 150), 'minecraft:slime_block')
    put(command, (1449, 149, 150), block)
    put(command, TARGET, target)


def check(cases):
    for rows in cases.values():
        angles = [round(row['angle'], 3) for row in rows]
        assert angles[:3] == [0.0, 9.6, 19.2], angles[:4]
        assert all(angle == 19.2 for angle in angles[3:57]), angles[3:58]
        removed = next(row for row in rows if row['target'] == AIR)
        assert removed['tick'] == 58 and angles[57] == 28.8, removed


def original():
    host = Original()
    scratch = Path(tempfile.mkdtemp(prefix='bearing-actor-phase-java-', dir=ROOT / '.local'))
    report = dict(create=PINS['create_revision'], cases={})

    try:
        assert host.call('state', {})['data_version'] == 3955
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        host.command('tp @s 1448.5 156 150.5')
        host.command('forceload add 1440 144 1455 159')
        host.snapshot([PIVOT], 25)
        for tool, (block, target) in SCENES.items():
            setup(host.command, block, target)
            put(host.command, MOTOR, motor())
            trace = host.call('observe_ticks', {'ticks': TICKS, 'positions': [PIVOT, TARGET]})
            report['cases'][tool] = [
                dict(tick=sample['tick'], target=sample['blocks'][1]['id'],
                     angle=number(sample['blocks'][0], 'Angle', 0))
                for sample in trace['samples']
            ]
            put(host.command, MOTOR, AIR)
            host.snapshot([PIVOT], 10)
    finally:
        put(host.command, MOTOR, AIR)
        host.command('forceload remove 1440 144 1455 159')
        host.call('tick', {'frozen': False})
        (scratch / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
    return scratch, report


def native(args):
    session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                 name='bearing-actor-phase-native', graphics=False,
                                 world='CreateBearingActorPhase')
    report = dict(create=PINS['create_revision'], cases={})
    try:
        for tool, (block, target) in SCENES.items():
            batch = Batch()
            batch.load((PIVOT[0], PIVOT[1] + 8, PIVOT[2]))
            setup(batch.command, block, target)
            batch.tick(3)
            batch.put(MOTOR, motor())
            for _ in range(TICKS):
                batch.tick()
                batch.data(PIVOT)
                batch.expect(TARGET, AIR)
            batch.put(MOTOR, AIR)
            batch.tick(10)
            rows = batch.run(session, tool)
            assert len(rows) == 2 * TICKS, rows
            report['cases'][tool] = [
                dict(tick=tick + 1, angle=number({'nbt': rows[2 * tick]}, 'Angle', 0),
                     target=AIR if matched(rows[2 * tick + 1]) else target.partition('[')[0])
                for tick in range(TICKS)
            ]
        # An empty ordinary inventory is recreated on landing. A configured
        # filter still requires a saved actor payload and must stay in place.
        batch = Batch()
        batch.load(PIVOT)
        setup(batch.command, *SCENES['saw'])
        saw = (PIVOT[0] + 1, PIVOT[1] + 1, PIVOT[2])
        batch.command(f'data merge block {xyz(saw)} {{Filter:{{id:"minecraft:oak_planks",count:1}}}}')
        batch.tick(3)
        batch.put(MOTOR, motor())
        batch.tick(20)
        batch.expect(saw, 'create:mechanical_saw')
        batch.data(saw)
        placed, preserved = batch.run(session, 'filtered-saw-refused')
        assert matched(placed) and 'minecraft:oak_planks' in preserved, (placed, preserved)
        report['filtered_saw_preserved'] = True
    finally:
        session.control_temp.cleanup()
        for folder in (session.resources, session.scratch / '.horizon-cache', session.scratch / 'horizon-mods'):
            shutil.rmtree(folder, ignore_errors=True)
    return session.scratch, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--reference', type=Path)
    for flag in ('game', 'resources', 'ctl', 'create-jar'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        scratch, report = original()
    elif args.game and args.resources and args.ctl:
        scratch, report = native(args)
    else:
        parser.error('Horizon runs require --game, --resources and --ctl')
    report['passed'] = False
    try:
        check(report['cases'])
        if args.reference:
            reference = json.loads(args.reference.read_text())
            assert reference['create'] == PINS['create_revision'], reference
            for tool, rows in report['cases'].items():
                for actual, expected in zip(rows, reference['cases'][tool], strict=True):
                    assert (actual['tick'], actual['target']) == (expected['tick'], expected['target']), (tool, actual, expected)
                    assert abs(actual['angle'] - expected['angle']) < 1e-4, (tool, actual, expected)
        report['passed'] = True
    finally:
        path = scratch / 'result.json'
        path.write_text(json.dumps(report, indent=2) + '\n')
        print(path)


if __name__ == '__main__':
    main()
