#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Record dry vertical Chute timings in the pinned Java Create instance."""

import json
from pathlib import Path
import re
import tempfile

from burner_heat_java_checks import items
from chain_drive_checks import Original, xyz
from common import PINS, ROOT


X, Y, Z = 1464, 140, 151
SOURCE = (X, Y + 2, Z)
UPPER = (X, Y + 1, Z)
LOWER = (X, Y, Z)
CHEST = 'minecraft:chest[facing=north,type=single,waterlogged=false]'
CHUTE = 'create:chute[facing=down,shape=normal,waterlogged=false]'
FUNNEL = 'create:andesite_funnel[facing=down,extracting=true,powered=true,waterlogged=false]'
AIR = 'minecraft:air'
CASES = ('single', 'column', 'blocked', 'hopper', 'funnel')


def fixture(put, command, mode):
    put(SOURCE, CHEST)
    put(UPPER, CHUTE)
    target = LOWER
    if mode == 'column':
        put(LOWER, CHUTE)
        target = (X, Y - 1, Z)
    if mode == 'funnel':
        put((X + 1, Y, Z), 'minecraft:redstone_block')
        put(target, FUNNEL)
    else:
        put(target, 'minecraft:hopper[facing=down]' if mode == 'hopper' else CHEST)
    if mode == 'blocked':
        for slot in range(27):
            command(f'item replace block {xyz(target)} container.{slot} with minecraft:cobblestone 64')
    return target


def seed(command, mode):
    if mode == 'single':
        stacks = [(0, 'minecraft:wheat 10'), (1, 'minecraft:oak_planks 5'), (5, 'minecraft:wheat 12')]
    else:
        stacks = [(2, 'minecraft:stick[minecraft:custom_data={chute_probe:43}] 12')]
    for slot, stack in stacks:
        command(f'item replace block {xyz(SOURCE)} container.{slot} with {stack}')


def scalar(nbt, name):
    match = re.search(r'\b' + name + r'\s*:\s*(-?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?)', nbt)
    assert match, (name, nbt)
    return float(match[1])


def snapshot(blocks):
    source, *chutes, target = (block['nbt'] for block in blocks)
    target_items = {} if 'id:"create:funnel"' in target.replace(' ', '') else items(target, 'Items')
    return dict(source=items(source, 'Items'), target=target_items, target_nbt=target,
                chutes=[dict(item=items(chute, 'Item'), position=scalar(chute, 'ItemPosition'),
                             nbt=chute) for chute in chutes])


def verify(cases):
    single = cases['single']
    wheat, planks = 'minecraft:wheat', 'minecraft:oak_planks'
    assert [single[i]['chutes'][0]['item'] for i in (0, 7, 14)] == [
        {wheat: 16}, {planks: 5}, {wheat: 6},
    ], single
    assert single[5]['chutes'][0]['position'] > 0 and not single[5]['target']
    assert single[6]['chutes'][0]['position'] == 0.20000003
    assert single[-1]['target'] == {wheat: 22, planks: 5} and not single[-1]['source']

    column = cases['column']
    sticks = {'minecraft:stick': 12}
    assert not column[5]['chutes'][1]['item'] and column[6]['chutes'][1]['item'] == sticks
    assert column[6]['chutes'][0]['position'] == 1 and column[6]['chutes'][1]['position'] == 0.8
    assert not column[10]['target'] and column[11]['target'] == sticks
    assert 'chute_probe:43' in column[-1]['target_nbt']

    blocked = cases['blocked']
    assert all(row['chutes'][0]['position'] == 0.5 and row['chutes'][0]['item'] == sticks
               for row in blocked[3:10])
    assert [row['chutes'][0]['position'] for row in blocked[10:13]] == [0.3, 0.10000001, 0.3]
    assert blocked[12]['target'] == {'minecraft:cobblestone': 26 * 64, **sticks}
    assert 'chute_probe:43' in blocked[-1]['target_nbt']

    hopper = cases['hopper']
    assert hopper[0]['chutes'][0]['item'] == {'minecraft:stick': 11}
    assert hopper[0]['target'] == {'minecraft:stick': 1}
    assert hopper[6]['target'] == sticks and 'chute_probe:43' in hopper[-1]['target_nbt']

    if 'funnel' in cases:
        funnel = cases['funnel']
        assert all('create:funnel' in row['target_nbt'] for row in funnel[:10])
        assert all(row['chutes'][0]['position'] == 0.5 and row['chutes'][0]['item'] == sticks
                   for row in funnel[3:10])
        assert [row['chutes'][0]['position'] for row in funnel[10:13]] == [0.3, 0.10000001, 0.3]
        assert funnel[12]['target'] == sticks and 'chute_probe:43' in funnel[-1]['target_nbt']


def main():
    host = Original()
    work = Path(tempfile.mkdtemp(prefix='chute-reference-', dir=ROOT / '.local'))
    loaded = False

    def put(pos, state):
        host.command(f'setblock {xyz(pos)} {state}')

    def observe(points, ticks):
        return [snapshot(sample['blocks']) for sample in host.call('observe_ticks', {
            'ticks': ticks, 'positions': points,
        })['samples']]

    try:
        assert host.call('state', {})['data_version'] == 3955
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        host.command(f'tp @s {X}.5 {Y + 8} {Z}.5')
        host.command('forceload add 1456 144 1471 159')
        loaded = True
        host.call('observe_ticks', {'ticks': 24, 'positions': [SOURCE]})
        results = {}
        for mode in CASES:
            host.command(f'fill {X - 2} {Y - 3} {Z - 2} {X + 2} {Y + 5} {Z + 2} {AIR}')
            target = fixture(put, host.command, mode)
            points = [SOURCE, UPPER, LOWER, target] if mode == 'column' else [SOURCE, UPPER, target]
            observe(points, 3)
            seed(host.command, mode)
            if mode in ('blocked', 'funnel'):
                rows = observe(points, 10)
                if mode == 'funnel':
                    put(target, CHEST)
                else:
                    host.command(f'item replace block {xyz(target)} container.6 with {AIR}')
                rows += observe(points, 8)
            else:
                rows = observe(points, 24)
            results[mode] = rows
        path = work / 'result.json'
        path.write_text(json.dumps(dict(create=PINS['create_revision'], cases=results), indent=2) + '\n')
        verify(results)
        print(path)
    finally:
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
        if loaded:
            host.command('forceload remove 1456 144 1471 159')


if __name__ == '__main__':
    main()
