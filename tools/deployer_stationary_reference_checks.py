#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Observe ordinary downward stationary Deployer use in pinned Create."""
import argparse
import json
from pathlib import Path
import re

from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS
from deployer_farm_checks import held_count
import reference_java as java


DEPLOYER = (1131, 103, 85)
MOTOR = (1130, 103, 85)
LOCK = (1132, 103, 85)
GAP = (1131, 102, 85)
TARGET = (1131, 101, 85)
SOIL = (1131, 100, 85)
POSITIONS = [DEPLOYER, GAP, TARGET, SOIL]
SAPLING = 'minecraft:oak_sapling'
AIR = 'minecraft:air'
DIRT = 'minecraft:dirt'
STONE = 'minecraft:stone'
REDSTONE = 'minecraft:redstone_block'


def put(pos, state):
    return f'setblock {xyz(pos)} {state}'


def trace(host, ticks, commands=(), after=0):
    frames = host.call('observe_ticks', {'ticks': ticks, 'positions': POSITIONS, 'commands': list(commands)})
    rows = []
    for frame in frames['samples']:
        deployer, gap, target, soil = frame['blocks']
        nbt = deployer['nbt']
        state = re.search(r'\bState:\s*"([A-Z]+)"', nbt)[1]
        rows.append(dict(tick=after+frame['tick'], state=state, timer=number(deployer, 'Timer'),
                         rpm=number(deployer, 'Speed', 0), powered=bool(number(deployer, 'Powered', 0)),
                         held=held_count(nbt), gap=gap['id'], target=target['id'],
                         target_properties=target['properties'], soil=soil['id'], nbt=nbt))
    return rows


def motor(rpm=32):
    return put(MOTOR, f'create:creative_motor[facing=east]{{ScrollValue:{rpm}}}')


def prepare(host, *, soil=DIRT, target=AIR, stock=3, locked=False):
    host.command('fill 1128 99 82 1134 105 88 minecraft:air')
    host.command(put(SOIL, soil))
    if target != AIR:
        host.command(put(TARGET, target))
    nbt = '{Mode:"USE",State:"WAITING",Timer:0,Inventory:['
    if stock:
        nbt += f'{{Slot:0b,id:"{SAPLING}",count:{stock}}}'
    nbt += ']}'
    host.command(put(DEPLOYER, 'create:deployer[facing=down,axis_along_first=true]' + nbt))
    if locked:
        host.command(put(LOCK, REDSTONE))
    [initial] = trace(host, 1)
    assert initial['rpm'] == 0 and initial['held'] == stock and initial['powered'] == locked, initial
    return initial


def state_edges(rows):
    return [{k: row[k] for k in ('tick', 'state', 'timer', 'rpm', 'powered', 'held', 'target')}
            for i, row in enumerate(rows) if i == 0 or any(row[key] != rows[i-1][key]
            for key in ('state', 'rpm', 'powered', 'held', 'target'))]


def run(base, output):
    java.BASE = base
    manifest = json.loads((base / 'manifest.json').read_text())
    assert manifest['create_sha256'] == java.CREATE_SHA256 and manifest['data_version'] == 3955
    host = Original()
    report = dict(passed=False, source=PINS['create_revision'], cases={})
    cases = report['cases']
    try:
        assert host.call('state', {})['data_version'] == 3955
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        host.command('tp @s 1128.5 107 85.5')
        host.command('forceload add 1131 85')
        host.call('observe_ticks', {'ticks': 18, 'positions': POSITIONS})
        host.command('gamerule randomTickSpeed 0')

        init = prepare(host)
        plant = trace(host, 65, [motor()])
        assert all(row['gap'] == AIR and row['soil'] == DIRT for row in plant), plant
        assert plant[-1]['target'] == SAPLING and plant[-1]['held'] == 2, plant
        cases['plant'] = dict(initial=init, rows=plant, edges=state_edges(plant))

        init = prepare(host, target=SAPLING + '[stage=1]')
        same = trace(host, 24, [motor()])
        assert all(r['target'] == SAPLING and r['target_properties']['stage'] == '1'
                   and r['state'] == 'WAITING' and r['held'] == 3 for r in same), same
        cases['same_stage_1'] = dict(initial=init, rows=same, edges=state_edges(same))

        init = prepare(host, soil=STONE)
        invalid = trace(host, 62, [motor()])
        assert all(r['target'] == AIR and r['held'] == 3 for r in invalid), invalid
        assert any(r['state'] == 'RETRACTING' for r in invalid), invalid
        cases['invalid_substrate'] = dict(initial=init, rows=invalid, edges=state_edges(invalid))

        init = prepare(host, locked=True)
        locked = trace(host, 15, [motor()])
        assert all(r['state'] == 'WAITING' and r['target'] == AIR and r['powered'] for r in locked), locked
        unlocked = trace(host, 26, [put(LOCK, AIR)], after=len(locked))
        assert unlocked[-1]['target'] == SAPLING and unlocked[-1]['held'] == 2, unlocked
        locked += unlocked
        cases['waiting_lock'] = dict(initial=init, rows=locked, edges=state_edges(locked))

        init = prepare(host)
        active = trace(host, 6, [motor()])
        assert active[-1]['state'] == 'EXPANDING' and active[-1]['target'] == AIR, active
        active += trace(host, 48, [put(LOCK, REDSTONE)], after=len(active))
        assert active[-1]['powered'] and active[-1]['target'] == SAPLING and active[-1]['held'] == 2, active
        held = trace(host, 24, [put(TARGET, AIR)], after=len(active))
        assert all(r['state'] == 'WAITING' and r['target'] == AIR and r['held'] == 2 for r in held), held
        active += held
        active += trace(host, 25, [put(LOCK, AIR)], after=len(active))
        assert active[-1]['target'] == SAPLING and active[-1]['held'] == 1, active[-1]
        cases['active_lock'] = dict(initial=init, rows=active, edges=state_edges(active))

        init = prepare(host, stock=1)
        pause = trace(host, 6, [motor(-32)])
        pause += trace(host, 6, [put(MOTOR, AIR)], after=len(pause))
        assert pause[-1]['state'] == 'EXPANDING' and pause[-1]['rpm'] == 0 and pause[-1]['held'] == 1, pause[-1]
        assert pause[-1]['timer'] == pause[-2]['timer'], pause[-2:]
        pause += trace(host, 55, [motor(-32)], after=len(pause))
        assert pause[-1]['target'] == SAPLING and pause[-1]['held'] == 0, pause[-1]
        cases['pause_resume'] = dict(initial=init, rows=pause, edges=state_edges(pause))
        report['passed'] = True
    finally:
        host.command('forceload remove 1131 85')
        host.call('tick', {'frozen': False})
        output.mkdir(parents=True, exist_ok=True)
        (output/'result.json').write_text(json.dumps(report, indent=2) + '\n')
        (output/'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
        print(output/'result.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.java, args.output)
