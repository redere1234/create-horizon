#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Exercise Cart Assembler rail actions in the isolated Java Create instance."""
import json
import math
from pathlib import Path
import tempfile

from chain_drive_checks import Original
from common import PINS, ROOT


FIRST = 980
SECOND = 984
ASSEMBLER = 'create:cart_assembler'
MOUNTED = 'create:contraption'


def lane(host, z, kind):
    def put(x, y, state):
        host.command(f'setblock {x} {y} {z} {state}')

    for entity_type in (MOUNTED, 'minecraft:minecart', 'minecraft:chest_minecart', 'minecraft:tnt_minecart'):
        host.command(f'kill @e[type={entity_type},x=974,y=97,z={z},dx=18,dy=10,dz=0]')
    host.command(f'fill 973 99 {z-1} 991 105 {z+1} minecraft:air')
    host.command(f'fill 973 99 {z-1} 991 99 {z+1} minecraft:stone')
    for x in range(976, 990):
        put(x, 100, 'minecraft:rail[shape=east_west]')
    put(FIRST, 100, f'{ASSEMBLER}[shape=east_west,backwards=true,rail_type={kind}]')
    put(SECOND, 100, f'{ASSEMBLER}[shape=east_west,rail_type=regular]')
    host.command(f'setblock {FIRST} 100 {z-1} minecraft:redstone_block')
    return put


def summon(host, z, x, cart, velocity):
    host.command(f'summon minecraft:{cart} {x+.5} 100.1 {z+.5} {{Motion:[{velocity}d,0d,0d]}}')


def snapshot(host, z, positions, ticks):
    blocks = host.call('observe_ticks', {'ticks': ticks, 'positions': positions})['samples'][-1]['blocks']
    entities = host.call('entities', {'center': [982, 100, z+.5], 'radius': 8})['entities']
    lane_entities = [entity for entity in entities if abs(entity['position'][2] - z - .5) < .3]
    return {'blocks': blocks, 'entities': lane_entities}


def block_ids(observed):
    return [block['id'] for block in observed['blocks']]


def mounted(observed):
    return [entity for entity in observed['entities'] if entity['type'] == MOUNTED]


def single(host, z, kind, cart):
    put = lane(host, z, kind)
    put(FIRST, 101, 'minecraft:oak_planks')
    summon(host, z, FIRST, cart, .17)
    positions = [(FIRST, 100, z), (SECOND, 100, z), (FIRST, 101, z), (SECOND, 101, z)]
    return [snapshot(host, z, positions, 1) for _ in range(16)]


def coupled(host, z):
    lane(host, z, 'regular')
    host.command(f'fill {FIRST} 101 {z} {SECOND} 101 {z} minecraft:slime_block')
    summon(host, z, SECOND, 'minecart', 0)
    summon(host, z, FIRST, 'minecart', .01)
    positions = [(FIRST, 100, z), (SECOND, 100, z), *((x, 101, z) for x in range(FIRST, SECOND+1))]
    active = snapshot(host, z, positions, 16)
    assert block_ids(active) == [ASSEMBLER] * 2 + ['minecraft:air'] * 5
    entities = mounted(active)
    assert len(entities) == 1 and 'OnCoupling:' in entities[0]['nbt'], entities
    host.command(f'setblock {FIRST} 100 {z-1} minecraft:air')
    restored = snapshot(host, z, positions, 12)
    assert block_ids(restored) == [ASSEMBLER] * 2 + ['minecraft:slime_block'] * 5
    assert not mounted(restored)
    return {'active': active, 'restored': restored}


def java_reference():
    host = Original()
    work = Path(tempfile.mkdtemp(prefix='cart-assembler-reference-', dir=ROOT / '.local'))
    try:
        assert host.call('state', {})['data_version'] == 3955
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        host.command('tp @s 989.5 106 151.5')
        host.command('forceload add 960 144 1007 159')
        host.command('forceload add 960 192 1007 207')
        snapshot(host, 150, [(FIRST, 100, 150)], 30)
        regular = single(host, 150, 'regular', 'minecart')
        assert block_ids(regular[0]) == [ASSEMBLER] * 2 + ['minecraft:air'] * 2

        controller = single(host, 154, 'controller_rail', 'chest_minecart')
        chest = [entity for entity in controller[0]['entities'] if entity['type'] == 'minecraft:chest_minecart']
        assert len(chest) == 1 and math.isclose(chest[0]['motion'][0], .4, abs_tol=1e-7), chest
        assert block_ids(controller[12])[3] == 'minecraft:air'
        assert block_ids(controller[13]) == [ASSEMBLER] * 2 + ['minecraft:air', 'minecraft:oak_planks']

        tnt = single(host, 157, 'regular', 'tnt_minecart')
        assert all(block_ids(row)[2:] == ['minecraft:oak_planks', 'minecraft:air'] for row in tnt)

        result = dict(create=PINS['create_revision'], regular=regular, controller=controller,
                      tnt=tnt, coupled=coupled(host, 196))
        path = work / 'result.json'
        path.write_text(json.dumps(result, indent=2) + '\n')
        print(path)
    finally:
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


if __name__ == '__main__':
    java_reference()
