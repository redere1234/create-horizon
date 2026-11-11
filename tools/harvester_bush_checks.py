#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Check a moving Harvester's vanilla flower and sapling drops in both games."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from bearing_native_checks import Batch
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession


X, Y, Z = 2630, 152, 1643
PIVOT, MOTOR = (X, Y, Z), (X, Y - 1, Z)
ROOM = '2626 149 1638 2636 160 1648'
FORCE = '2624 1632 2639 1647'
CASES = (
    ((X + 3, Y + 1, Z - 1), 'dandelion', 'dirt'),
    ((X + 2, Y + 1, Z - 2), 'poppy', 'dirt'),
    ((X + 1, Y + 1, Z - 3), 'oak_sapling[stage=1]', 'dirt'),
    ((X, Y + 1, Z - 3), 'birch_sapling[stage=0]', 'dirt'),
    ((X - 1, Y + 1, Z - 3), 'wheat[age=3]', 'farmland[moisture=7]'),
)
POSITIONS = [pos for pos, _, _ in CASES]
DROPS = f'@e[type=minecraft:item,x={X},y={Y},z={Z},distance=..8]'
PLANTS = [f'minecraft:{plant.partition("[")[0]}' for _, plant, _ in CASES]
EXPECTED = dict.fromkeys(PLANTS[:-1], 1)
TICKS = 18


def setup(command):
    def put(pos, state):
        command(f'setblock {xyz(pos)} {state}')

    command(f'fill {ROOM} minecraft:air')
    put(PIVOT, 'create:mechanical_bearing[facing=up]')
    for i in range(3):
        put((X + i, Y + 1, Z), 'minecraft:slime_block')
    put((X + 3, Y + 1, Z), 'create:mechanical_harvester[facing=north]')
    for (x, y, z), plant, soil in CASES:
        put((x, y - 1, z), 'minecraft:' + soil)
        put((x, y, z), 'minecraft:' + plant)


def power(command):
    command(f'setblock {xyz(MOTOR)} create:creative_motor[facing=up]{{ScrollValue:32}}')


def drops(text):
    counts = {}
    for payload in re.findall(r'\{[^{}]*\bid\s*:\s*"[^"{}]+"[^{}]*\}', text):
        item = re.search(r'\bid\s*:\s*"([^"{}]+)"', payload)[1]
        count = int(re.search(r'\bcount\s*:\s*(\d+)', payload)[1])
        counts[item] = counts.get(item, 0) + count
    return counts


def java(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    command = host.command
    game_rule = ' '.join(command('gamerule randomTickSpeed')['messages'])
    speed = int(re.search(r'\b(\d+)\.?$', game_rule)[1])

    def step(ticks):
        return host.call('observe_ticks', {'positions': POSITIONS, 'ticks': ticks})['samples']

    host.call('tick', {'frozen': True})
    try:
        command(f'forceload add {FORCE}')
        command(f'tp @s {X+5}.5 {Y+6} {Z+4}.5')
        step(24)
        command(f'kill {DROPS}')
        command('gamerule randomTickSpeed 0')
        setup(command)
        before = [host.call('block', {'pos': pos}) for pos in POSITIONS]
        assert [block['id'] for block in before] == PLANTS
        power(command)
        trace = step(TICKS)
        blocks = trace[-1]['blocks']
        assert [block['id'] for block in blocks] == ['minecraft:air'] * 4 + ['minecraft:wheat'], blocks
        assert blocks[-1]['properties']['age'] == '3', blocks[-1]
        cargo = host.call('entities', {'center': PIVOT, 'radius': 8})['entities']
        item_nbt = [entity['nbt'] for entity in cargo if entity['type'] == 'minecraft:item']
        counts = drops('\n'.join(item_nbt))
        assert counts == EXPECTED, (counts, item_nbt)
        return dict(drops=counts, trace=[[block['id'] for block in row['blocks']] for row in trace])
    finally:
        command(f'kill @e[type=create:stationary_contraption,x={X},y={Y},z={Z},distance=..8]')
        command(f'kill {DROPS}')
        command(f'fill {ROOM} minecraft:air')
        command(f'forceload remove {FORCE}')
        command(f'gamerule randomTickSpeed {speed}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session):
    batch = Batch()
    batch.load((X + 5, Y + 6, Z + 4))
    batch.command('gamerule minecraft:random_tick_speed 0')
    setup(batch.command)
    for pos, plant, _ in CASES:
        batch.expect(pos, 'minecraft:' + plant)
    power(batch.command)
    for _ in range(TICKS):
        batch.tick()
        for pos in POSITIONS:
            batch.expect(pos, 'minecraft:air')
    for pos in POSITIONS[:-1]:
        batch.expect(pos, 'minecraft:air')
    batch.expect(POSITIONS[-1], 'minecraft:wheat[age=3]')
    batch.command(f'execute as {DROPS} run data get entity @s Item', True)
    *rows, cargo = batch.run(session, 'harvester-bushes')
    size = len(POSITIONS)
    before, trace, after = rows[:size], rows[size:-size], rows[-size:]
    assert all('bearing_check' in row for row in before + after), (before, after)
    assert len(trace) == TICKS * size, trace
    observed = [['minecraft:air' if 'bearing_check' in row else plant
                 for row, plant in zip(trace[i:i + size], PLANTS, strict=True)]
                for i in range(0, len(trace), size)]
    counts = drops(cargo)
    assert counts == EXPECTED, (counts, cargo)
    return dict(drops=counts, trace=observed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    report = dict(passed=False, create=PINS['create_revision'])
    if args.game:
        if not all((args.resources, args.ctl, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == report['create']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='harvester-bush-native', world='HarvesterBush', graphics=False)
        work = session.scratch
        try:
            report['case'] = native(session)
            for tick, (actual, expected) in enumerate(zip(report['case']['trace'], reference['case']['trace'], strict=True), 1):
                assert actual == expected, (tick, actual, expected)
            assert report['case']['drops'] == reference['case']['drops']
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    else:
        work = Path(tempfile.mkdtemp(prefix='harvester-bush-java-', dir=ROOT / '.local'))
        report['case'] = java(work)
    report['passed'] = True
    path = work / 'result.json'
    path.write_text(json.dumps(report, indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
