#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare stationary Deployer fertilizer use and the unchanged stroke schedule."""
import argparse
import json
from pathlib import Path
import re
import tempfile

from actor_native_checks import matched
from bearing_native_checks import Batch
from chain_drive_checks import Original
from common import PINS, ROOT
from deployer_stationary_native_checks import observe, snapshot
from deployer_stationary_reference_checks import (
    AIR, DEPLOYER, MOTOR, POSITIONS, SOIL, STONE, TARGET, motor, put, trace,
)
from native_check_session import NativeCheckSession

MEAL = 'minecraft:bone_meal'
COUNT = 3
TICKS = 115
OAK = 'minecraft:oak_sapling[stage=1]'
MATURE = 'minecraft:wheat[age=7]'
CASES = {
    'blocked_tree': ('minecraft:dirt', OAK, OAK, 0),
    'wheat': ('minecraft:farmland[moisture=7]', 'minecraft:wheat[age=6]', MATURE, 2),
    'stone': ('minecraft:dirt', STONE, STONE, 3),
}


def setup(command, soil, target):
    command('fill 1128 99 82 1134 105 88 minecraft:air')
    command(put(SOIL, soil))
    command(put(TARGET, target))
    command(put(DEPLOYER, 'create:deployer[facing=down,axis_along_first=true]'
                + '{Mode:"USE",State:"WAITING",Timer:0,Inventory:['
                + f'{{Slot:0b,id:"{MEAL}",count:{COUNT}}}' + ']}'))


def held_count(nbt):
    held = re.search(r'HeldItem\s*:\s*\{([^}]*)\}', nbt)
    if held and MEAL in held[1]:
        count = re.search(r'count\s*:\s*(\d+)', held[1])
        assert count, nbt
        return int(count[1])
    return 0


def meal_trace(host, ticks, commands=()):
    rows = trace(host, ticks, commands)
    for row in rows:
        row['held'] = held_count(row['nbt'])
    return rows


def original():
    host = Original()
    scratch = Path(tempfile.mkdtemp(prefix='deployer-meal-java-', dir=ROOT / '.local'))
    report = dict(passed=False, create=PINS['create_revision'], cases={})
    try:
        assert host.call('state', {})['data_version'] == 3955
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        host.command('tp @s 1128.5 107 85.5')
        host.command('forceload add 1131 85')
        host.call('observe_ticks', {'ticks': 20, 'positions': POSITIONS})
        host.command('gamerule randomTickSpeed 0')
        for label, (soil, target, final, held) in CASES.items():
            setup(host.command, soil, target)
            [initial] = meal_trace(host, 1)
            rows = meal_trace(host, TICKS, [motor()])
            report['cases'][label] = dict(initial=initial, rows=rows)
            assert initial['held'] == COUNT, initial
            assert rows[-1]['held'] == held, (label, rows[-1])
            name, _, props = final.partition('[')
            assert rows[-1]['target'] == name, (label, rows[-1])
            if props:
                key, value = props.rstrip(']').split('=')
                assert rows[-1]['target_properties'][key] == value, (label, rows[-1])
            assert any(row['state'] == 'RETRACTING' for row in rows), label
        report['passed'] = True
    finally:
        host.command(put(MOTOR, AIR))
        host.command('forceload remove 1131 85')
        host.call('tick', {'frozen': False})
        (scratch / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
        path = scratch / 'result.json'
        path.write_text(json.dumps(report, indent=2) + '\n')
        print(path)


def native(args):
    reference = json.loads(args.reference.read_text())
    assert reference['passed'] and reference['create'] == PINS['create_revision'], args.reference
    session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                 name='deployer-meal-native', graphics=False, world='CreateDeployerMeal')
    report = dict(passed=False, create=PINS['create_revision'], cases={})
    try:
        for label, (soil, target, _, _) in CASES.items():
            case = reference['cases'][label]
            expected = [case['initial'], *case['rows']]
            batch = Batch()
            batch.load(DEPLOYER)
            batch.command('gamerule minecraft:random_tick_speed 0')
            setup(batch.command, soil, target)
            batch.tick()
            observe(batch, case['initial'])
            batch.command(motor())
            for row in case['rows']:
                batch.tick()
                observe(batch, row)
            actual = batch.run(session, label)
            assert len(actual) == 2 * len(expected), (label, len(actual))
            failures = []
            for row, nbt, block in zip(expected, actual[::2], actual[1::2], strict=True):
                parsed = snapshot(nbt)
                parsed['held'] = held_count(nbt)
                if not matched(block) or any(row[key] != value for key, value in parsed.items()):
                    failures.append(dict(expected=row, actual=parsed, target=block))
            report['cases'][label] = dict(samples=len(expected), failures=failures)
            assert not failures, (label, failures[:3])
        report['passed'] = True
    finally:
        session.control_temp.cleanup()
        path = session.scratch / 'result.json'
        path.write_text(json.dumps(report, indent=2) + '\n')
        print(path)


if __name__ == '__main__':
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
