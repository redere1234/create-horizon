#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Observe the pinned Java Deployer planting a sapling on ordinary server ticks."""
import json
from pathlib import Path
import re
import tempfile

from chain_drive_checks import Original, xyz
from common import PINS, ROOT
import reference_java as java

DEPLOYER = (1062, 100, 55)
TARGET = (1064, 100, 55)
MOTOR = (1062, 100, 54)
PISTON = (1044, 104, 55)
MOVING_START = (1045, 104, 55)
MOVING_END = (1048, 104, 55)


def field(block, name):
    match = re.search(rf'\b{name}:("[^"]+"|-?[\d.]+)', block.get('nbt', ''))
    assert match, (name, block)
    return match[1].strip('"')


def moving_planting(host):
    row = [(x, 102, 55) for x in range(1045, 1049)]
    points = [PISTON, *row, MOVING_START, MOVING_END]

    def put(pos, block):
        host.command(f'setblock {xyz(pos)} {block}')

    def ticks(count):
        return host.call('observe_ticks', {'ticks': count, 'positions': points})['samples']

    host.command('tp @s 1047.5 104 59.5')
    host.command('forceload add 1040 48 1055 63')
    ticks(20)
    host.command('fill 1041 99 51 1052 108 59 minecraft:air')
    host.command('fill 1045 101 55 1048 101 55 minecraft:dirt')
    put(PISTON, 'create:mechanical_piston[facing=east,axis_along_first=false]')
    for x in range(1041, 1044):
        put((x, 104, 55), 'create:piston_extension_pole[facing=east]')
    put(MOVING_START, 'create:deployer[facing=down,axis_along_first=false]'
                      '{Mode:"USE",Inventory:[{Slot:0b,id:"minecraft:oak_sapling",count:8}]}')
    before = ticks(4)[-1]['blocks'][-2]
    assert field(before, 'Mode') == 'USE', before
    assert 'HeldItem:{count:8,id:"minecraft:oak_sapling"}' in before['nbt'], before

    put((1044, 104, 54), 'create:creative_motor[facing=south]{ScrollValue:-128}')
    samples = ticks(24)
    final = samples[-1]['blocks']
    assert all(block['id'] == 'minecraft:oak_sapling' for block in final[1:5]), final
    first_planting_ticks = [
        next(sample['tick'] for sample in samples if sample['blocks'][index]['id'] == 'minecraft:oak_sapling')
        for index in range(1, 5)
    ]
    assert first_planting_ticks == [4, 5, 9, 13], first_planting_ticks
    assert final[-1]['id'] == 'create:deployer', final
    assert 'HeldItem:{count:4,id:"minecraft:oak_sapling"}' in final[-1]['nbt'], final
    return dict(start=before, points=points, samples=samples, first_planting_ticks=first_planting_ticks)


def run():
    manifest = json.loads((java.BASE / 'manifest.json').read_text())
    assert manifest['create_sha256'] == java.CREATE_SHA256 and manifest['data_version'] == 3955
    host = Original()
    assert host.call('state', {})['ready']
    work = Path(tempfile.mkdtemp(prefix='deployer-reference-', dir=ROOT / '.local'))
    report = dict(passed=False, create=PINS['create_revision'])

    def put(pos, block):
        host.command(f'setblock {xyz(pos)} {block}')

    def ticks(count):
        return host.call('observe_ticks', {'ticks': count, 'positions': [DEPLOYER, TARGET, MOTOR]})['samples']

    try:
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        host.command('tp @s 1065.5 99 55.5')
        host.command('forceload add 1056 48 1071 63')
        ticks(20)
        host.command('fill 1059 96 51 1069 106 59 minecraft:air')
        host.command('fill 1064 98 51 1069 98 59 minecraft:smooth_stone')
        put((1064, 99, 55), 'minecraft:dirt')
        put(DEPLOYER, 'create:deployer[facing=east,axis_along_first=false]')
        ticks(3)
        host.command('clear @s')
        host.command('item replace entity @s weapon.mainhand with minecraft:oak_sapling 3')
        host.call('camera', {'position': [1065.5, 99, 55.5], 'target': [1062.5, 100.65, 55.5]})
        host.call('capture', {'name': f'{work.name}/held-before.png', 'frames': 16})
        hit = host.call('state', {})['hit']
        assert tuple(hit['pos']) == DEPLOYER and hit['face'] == 'east', hit
        host.call('input', {'key': 'use'})
        host.call('capture', {'name': f'{work.name}/held-after.png', 'frames': 16})
        host.call('input', {'key': 'use', 'down': False})
        report['waiting'] = ticks(4)
        idle = report['waiting'][-1]['blocks'][0]
        assert 'HeldItem:{count:3,id:"minecraft:oak_sapling"}' in idle['nbt'], idle

        put(MOTOR, 'create:creative_motor[facing=south]{ScrollValue:32}')
        report['planting'] = ticks(64)
        samples = [sample['blocks'] for sample in report['planting']]
        expanded = [int(field(block, 'Timer')) for block, _, _ in samples if field(block, 'State').lower() == 'expanding']
        assert expanded[:17] == [1000 - 64 * tick for tick in range(17)], expanded
        planted = [index for index, (_, target, _) in enumerate(samples) if target['id'] == 'minecraft:oak_sapling']
        assert planted and planted == list(range(planted[0], len(samples))), planted
        first = samples[planted[0]][0]
        assert field(first, 'State').lower() == 'retracting' and int(field(first, 'Timer')) == 1000, first
        assert 'HeldItem:{count:2,id:"minecraft:oak_sapling"}' in samples[-1][0]['nbt'], samples[-1]
        assert any(
            field(block, 'State').lower() == 'waiting' and int(field(block, 'Timer')) == 640
            for block, _, _ in samples
        ), samples[-1]
        report['moving'] = moving_planting(host)
        report['passed'] = True
    finally:
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
        print(json.dumps(dict(result=str(work / 'result.json'), passed=report['passed'])))


if __name__ == '__main__':
    run()
