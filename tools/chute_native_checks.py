#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare a dry vertical Chute to Java, including a native process restart."""

import argparse
import json
from pathlib import Path
import shutil

from actor_native_checks import matched
from bearing_native_checks import Batch
from burner_heat_java_checks import items
from chain_drive_checks import xyz
from chute_reference_checks import (
    AIR, CASES, CHEST, CHUTE, LOWER, SOURCE, UPPER, X, Y, Z, fixture, seed, snapshot, verify,
)
from common import PINS
from foundation_checks import crafting
from native_check_session import NativeCheckSession, wait_loaded


def setup(batch, mode):
    batch.load((X, Y + 8, Z))
    batch.command(f'fill {X - 2} {Y - 3} {Z - 2} {X + 2} {Y + 5} {Z + 2} {AIR}')
    target = fixture(batch.put, batch.command, mode)
    batch.tick(3)
    seed(batch.command, mode)
    points = [SOURCE, UPPER, LOWER, target] if mode == 'column' else [SOURCE, UPPER, target]
    return points, target


def compare_case(session, mode, reference):
    batch = Batch()
    points, target = setup(batch, mode)
    for i in range(len(reference)):
        if mode == 'blocked' and i == 10:
            batch.command(f'item replace block {xyz(target)} container.6 with {AIR}')
        if mode == 'funnel' and i == 10:
            batch.put(target, CHEST)
        batch.tick()
        for pos in points:
            batch.data(pos)
    rows = batch.run(session, f'chute-{mode}')
    assert len(rows) == len(reference) * len(points), (len(rows), len(reference), points)
    observations = [snapshot([{'nbt': row} for row in rows[i:i + len(points)]])
                    for i in range(0, len(rows), len(points))]
    errors = []
    for tick, (actual, expected) in enumerate(zip(observations, reference), 1):
        if (actual['source'] != expected['source'] or actual['target'] != expected['target']
                or any(a['item'] != b['item'] or abs(a['position'] - b['position']) > 1e-6
                       for a, b in zip(actual['chutes'], expected['chutes']))
                or ('chute_probe:43' in actual['target_nbt'].replace(' ', ''))
                != ('chute_probe:43' in expected['target_nbt'].replace(' ', ''))):
            errors.append(dict(tick=tick, actual=actual, expected=expected))
    return dict(trace=observations, differences=errors)


def restart(session):
    batch = Batch()
    _, target = setup(batch, 'column')
    batch.tick(9)
    batch.data(LOWER)
    batch.data(target)
    staged, empty = batch.run(session, 'chute-moving-save')
    sticks = {'minecraft:stick': 12}
    assert items(staged, 'Item') == sticks and not items(empty, 'Items'), (staged, empty)

    batch = Batch()
    batch.load((X, Y + 8, Z))
    batch.tick(8)
    batch.data(UPPER)
    batch.data(LOWER)
    batch.data(target)
    upper, lower, landed = batch.run(session, 'chute-restored')
    assert not items(upper, 'Item') and not items(lower, 'Item'), (upper, lower)
    assert items(landed, 'Items') == sticks and 'chute_probe:43' in landed.replace(' ', ''), landed
    return dict(staged=staged, upper=upper, lower=lower, landed=landed)


def open_drop(session):
    batch = Batch()
    batch.load((X, Y + 8, Z))
    batch.command(f'fill {X - 2} {Y - 3} {Z - 2} {X + 2} {Y + 5} {Z + 2} {AIR}')
    batch.put(UPPER, CHUTE)
    batch.put((X, Y - 2, Z), 'minecraft:stone')
    batch.tick()
    batch.command(f'summon minecraft:item {X}.5 {Y + 3} {Z}.5 '
                  '{Item:{id:"minecraft:wheat",count:3,components:{"minecraft:custom_data":'
                  '{chute_probe:43}}},PickupDelay:32767s}')
    for _ in range(24):
        batch.tick()
        batch.data(UPPER)
    batch.command(f'execute if entity @e[type=minecraft:item,x={X},y={Y - 1},z={Z},distance=..2,'
                  'nbt={Item:{id:"minecraft:wheat",count:3,components:{"minecraft:custom_data":'
                  '{chute_probe:43}}}},limit=1] run say bearing_check', True)
    *transit, emitted = batch.run(session, 'chute-open-drop')
    assert any(items(row, 'Item') == {'minecraft:wheat': 3} and 'chute_probe:43' in row.replace(' ', '')
               for row in transit), transit
    assert not items(transit[-1], 'Item') and matched(emitted), (transit[-1], emitted)
    return dict(transit=transit, emitted=emitted)


def craft(session):
    with session:
        call = session.call
        call('command', f'tp @s {X}.5 67 2.5')
        wait_loaded(call, [(X, 64, 0), (X + 1, 64, 2)])
        call('fill', X - 2, 64, -2, X + 4, 68, 4, AIR)
        call('fill', X - 2, 63, -2, X + 4, 63, 4, 'minecraft:stone')
        call('command', 'gamemode survival')
        crafting(call, X, lambda: call('command', 'clear @s'),
                 recipes=['kinetics/chute', 'kinetics/portable_storage_interface'])
        counts = call('inventory')['counts']
        assert counts['create:portable_storage_interface'] == 1, counts
    return dict(crafted=['create:chute', 'create:portable_storage_interface'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + flag, type=Path, required=True)
    parser.add_argument('--create-jar', type=Path)
    parser.add_argument('--case', action='append', choices=(*CASES, 'restart', 'drop', 'craft'))
    args = parser.parse_args()
    reference = json.loads(args.reference.read_text())
    assert reference['create'] == PINS['create_revision']
    verify(reference['cases'])
    scenarios = args.case or (*reference['cases'], 'restart', 'drop', 'craft')
    for name in scenarios:
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name=f'chute-native-{name}', graphics=name == 'craft', world='CreateChuteCheck')
        try:
            if name in CASES:
                result = compare_case(session, name, reference['cases'][name])
            else:
                result = {'restart': restart, 'drop': open_drop, 'craft': craft}[name](session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, session.scratch / '.horizon-cache',
                           session.scratch / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        path = session.scratch / 'result.json'
        path.write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(dict(case=name, path=str(path), differences=len(result.get('differences', [])))), flush=True)
        assert not result.get('differences'), (name, result['differences'][:3], path)


if __name__ == '__main__':
    main()
