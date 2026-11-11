#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare ordinary stationary Deployer strokes and a cold reload."""

import argparse
import json
from pathlib import Path
import re

from actor_native_checks import matched
from bearing_native_checks import Batch
from burner_heat_java_checks import number
from common import PINS
from deployer_farm_checks import held_count
from deployer_stationary_reference_checks import (
    AIR, DEPLOYER, GAP, LOCK, MOTOR, REDSTONE, SAPLING, SOIL, TARGET,
)
from native_check_session import NativeCheckSession
from saved_block_checks import read_saved_block


def motor(rpm):
    return f'create:creative_motor[facing=east]{{ScrollValue:{rpm}}}'


def setup(batch, initial):
    batch.load(DEPLOYER)
    batch.command('gamerule minecraft:random_tick_speed 0')
    batch.command('fill 1128 99 82 1134 105 88 minecraft:air')
    batch.put(SOIL, initial['soil'])
    batch.put(TARGET, target_state(initial))
    inventory = '' if not initial['held'] else f'{{Slot:0b,id:"{SAPLING}",count:{initial["held"]}}}'
    batch.put(DEPLOYER, 'create:deployer[facing=down,axis_along_first=true]'
              + '{Mode:"USE",State:"WAITING",Timer:0,Inventory:[' + inventory + ']}')
    if initial['powered']:
        batch.put(LOCK, REDSTONE)
    batch.tick()


def target_state(sample):
    props = sample['target_properties']
    return sample['target'] + ('[' + ','.join(f'{key}={value}' for key, value in props.items()) + ']'
                               if props else '')


def observe(batch, expected):
    batch.data(DEPLOYER)
    batch.expect(TARGET, target_state(expected))


def snapshot(nbt):
    state = re.search(r'\bState:\s*"([A-Z]+)"', nbt)
    assert state, nbt
    return dict(state=state[1], timer=number({'nbt': nbt}, 'Timer'),
                rpm=number({'nbt': nbt}, 'Speed', 0),
                powered=bool(number({'nbt': nbt}, 'Powered', 0)), held=held_count(nbt))


def compare(samples, rows):
    assert len(rows) == 2 * len(samples), (len(rows), len(samples))
    failures = []
    for expected, nbt, target in zip(samples, rows[::2], rows[1::2], strict=True):
        actual = snapshot(nbt)
        if any(value != expected[key] for key, value in actual.items()) or not matched(target):
            failures.append(dict(tick=expected['tick'], actual=actual, expected=expected, target=target))
    return failures


def scenarios(session, cases):
    edits = {
        'waiting_lock': {16: (LOCK, AIR)},
        'active_lock': {7: (LOCK, REDSTONE), 55: (TARGET, AIR), 79: (LOCK, AIR)},
        'pause_save_resume': {7: (MOTOR, AIR), 13: (MOTOR, motor(-32))},
    }
    reports = {}
    for name, case in cases.items():
        batch = Batch()
        setup(batch, case['initial'])
        observe(batch, case['initial'])
        batch.put(MOTOR, motor(-32 if name == 'pause_save_resume' else 32))
        for row in case['rows']:
            if edit := edits.get(name, {}).get(row['tick']):
                batch.put(*edit)
            batch.tick()
            observe(batch, row)
        batch.expect(GAP, AIR)
        batch.expect(SOIL, case['initial']['soil'])
        rows = batch.run(session, 'stationary-deployer-' + name)
        assert all(map(matched, rows[-2:])), rows[-2:]
        failures = compare([case['initial'], *case['rows']], rows[:-2])
        reports[name] = dict(samples=len(case['rows']), failures=failures)
    return reports


def cold_restart(session, case):
    batch = Batch()
    setup(batch, case['initial'])
    batch.put(MOTOR, motor(-32))
    batch.tick(6)
    batch.put(MOTOR, AIR)
    batch.tick(6)
    observe(batch, case['rows'][11])
    rows = batch.run(session, 'stationary-deployer-paused-save')
    assert not compare([case['rows'][11]], rows), rows
    saved = read_saved_block(session.scratch, DEPLOYER, session.world)['nbt']['value']
    assert saved['State']['value'] == 'EXPANDING' and saved['Timer']['value'] == 744, saved
    assert 'Reach' not in saved and 'create_horizon:DeployerTick' not in saved, saved

    batch = Batch()
    batch.load(DEPLOYER)
    batch.tick()
    observe(batch, case['rows'][11])
    batch.put(MOTOR, motor(-32))
    for row in case['rows'][12:]:
        batch.tick()
        observe(batch, row)
    rows = batch.run(session, 'stationary-deployer-cold-resume')
    return compare(case['rows'][11:], rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args()
    reference = json.loads(args.reference.read_text())
    assert reference['passed'] and reference['source'] == PINS['create_revision']
    session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                 name='stationary-deployer', graphics=False, world='StationaryDeployer')
    print(session.scratch, flush=True)
    report = dict(passed=False, source=reference['source'])
    try:
        report['cases'] = scenarios(session, reference['cases'])
        assert not (failed := {name: case['failures'][:2] for name, case in report['cases'].items()
                               if case['failures']}), failed
        report['cold_restart'] = cold_restart(session, reference['cases']['pause_save_resume'])
        assert not report['cold_restart'], report['cold_restart'][:2]
        report['passed'] = True
    finally:
        session.control_temp.cleanup()
        (session.scratch / 'result.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
