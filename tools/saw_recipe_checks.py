#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare Mechanical Saw processing, output filters and recipe order."""
import argparse
import json
from pathlib import Path
import tempfile

from bearing_native_checks import Batch
from chain_drive_checks import Original
from common import PINS, ROOT
from native_check_session import NativeCheckSession
from saw_processing_checks import row


CASES = (
    ('alloy', 'create:andesite_alloy', 'create:shaft', 1),
    ('bamboo', 'minecraft:bamboo_planks', None, 10),
    ('oak', 'minecraft:oak_planks', None, 9),
    ('stone', 'minecraft:stone', None, 7),
    ('filter', 'minecraft:stone', 'minecraft:stone_brick_wall', 1),
    ('rejected', 'minecraft:stone', 'minecraft:diamond', 1),
)
POINTS = [(1400 + 4 * i, 124, 88) for i in range(len(CASES))]


def rig(command):
    command('fill 1396 123 82 1428 123 93 minecraft:stone')
    command('fill 1396 124 82 1428 131 93 minecraft:air')
    for (x, y, z), (_, _, output, _) in zip(POINTS, CASES):
        command(f'setblock {x} {y} {z} create:mechanical_saw[facing=up,axis_along_first=false]')
        command(f'setblock {x} {y} {z - 1} create:creative_motor[facing=south]{{ScrollValue:128}}')
        if output:
            command(f'data merge block {x} {y} {z} {{Filter:{{id:"{output}",count:1}},FilterAmount:17}}')


def drop(command, iteration):
    command('kill @e[type=minecraft:item,x=1396,y=122,z=82,dx=32,dy=10,dz=12]')
    for (x, y, z), (_, item, _, rounds) in zip(POINTS, CASES):
        if iteration < rounds:
            command(f'summon minecraft:item {x+.5} {y+1.3} {z+.5} '
                    f'{{PickupDelay:32767s,Item:{{id:"{item}",count:1}}}}')


def collect(trace, iteration):
    results = {}
    for i, (name, _, _, rounds) in enumerate(CASES):
        states = [tick[i] for tick in trace]
        if iteration >= rounds:
            assert all(not s[4] for s in states), (name, states)
            continue
        start = next((s for s in states if s[4] and not s[2]), None)
        applied = next(s for s in states if s[2] and s[4])
        assert states[-1][:3] == [-1, 0, 0] and not states[-1][4], (name, states)
        results[name] = dict(duration=start[1] if start else None, index=applied[3], output=applied[4])
    return results


def verify(rounds):
    first = rounds[0]
    assert first['alloy'] == dict(duration=200, index=0, output=[[1, 'create:shaft', 6]]), first
    assert first['filter'] == dict(duration=50, index=0, output=[[1, 'minecraft:stone_brick_wall', 1]]), first
    assert first['rejected'] == dict(duration=None, index=0, output=[[0, 'minecraft:stone', 1]]), first
    bamboo = [r['bamboo'] for r in rounds]
    assert {r['duration'] for r in bamboo} == {20, 50}, bamboo
    assert len({tuple(r['output'][0]) for r in bamboo}) == 10, bamboo
    for name, _, _, count in CASES:
        if count > 1:
            assert [r[name]['index'] for r in rounds[:count]] == [*range(1, count), 0], (name, rounds)


def reference():
    host = Original()
    before = host.call('state', {})
    assert before['ready'] and before['data_version'] == 3955
    work = Path(tempfile.mkdtemp(prefix='saw-recipes-java-', dir=ROOT / '.local'))
    result = dict(create=PINS['create_revision'], passed=False, rounds=[], trace=[])
    try:
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        host.command('tp @s 1411.5 128 93.5')
        host.command('forceload add 1392 80 1439 95')
        host.snapshot(POINTS, 28)
        rig(host.command)
        host.snapshot(POINTS, 8)
        for i in range(10):
            drop(host.command, i)
            samples = host.call('observe_ticks', {'positions': POINTS, 'ticks': 47 if i == 0 else 18})['samples']
            trace = [[row(block['nbt']) for block in sample['blocks']] for sample in samples]
            result['trace'].append(trace)
            result['rounds'].append(collect(trace, i))
        verify(result['rounds'])
        result['passed'] = True
    finally:
        host.call('tick', {'frozen': before['server']['frozen']})
        (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
        print(work / 'result.json')


def native(session, reference, restart):
    def part(first, last, setup):
        batch = Batch()
        batch.load((1411, 124, 93))
        if setup:
            rig(batch.command)
            batch.tick(8)
        for index in range(first, last):
            drop(batch.command, index)
            for _ in reference['trace'][index]:
                batch.tick()
                for pos in POINTS:
                    batch.data(pos)
        recorded = iter(batch.run(session, f'saw-recipes-{first}-{last}'))
        values = []
        for index in range(first, last):
            trace = [[row(next(recorded)) for _ in POINTS] for _ in reference['trace'][index]]
            values.append(trace)
            for tick, (actual, expected) in enumerate(zip(trace, reference['trace'][index])):
                for case, (observed, original) in enumerate(zip(actual, expected)):
                    assert abs(observed[0] - original[0]) < 1e-5 and observed[1:] == original[1:], (
                        'Saw cycle difference', index, tick, CASES[case][0], observed, original)
        assert next(recorded, None) is None
        return values

    count = len(reference['trace'])
    traces = part(0, 5, True) + part(5, count, False) if restart else part(0, count, True)
    rounds = [collect(trace, index) for index, trace in enumerate(traces)]
    verify(rounds)
    assert rounds == reference['rounds'], rounds
    return dict(passed=True, create=PINS['create_revision'], restart=restart, rounds=rounds, trace=traces)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--restart', action='store_true')
    for name in ('game', 'ctl', 'resources', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java:
        reference()
        return
    if not all((args.game, args.ctl, args.resources, args.reference)):
        parser.error('Horizon runs require --game, --ctl, --resources and --reference')
    expected = json.loads(args.reference.read_text())
    assert expected['passed'] and expected['create'] == PINS['create_revision']
    session = NativeCheckSession(args.game, args.resources, args.ctl, None, name='saw-recipes-native',
                                 graphics=False, world='CreateSawRecipes')
    print(session.scratch, flush=True)
    try:
        result = native(session, expected, args.restart)
        path = session.scratch / 'result.json'
        path.write_text(json.dumps(result, indent=2) + '\n')
        print(path)
    finally:
        session.control_temp.cleanup()


if __name__ == '__main__':
    main()
