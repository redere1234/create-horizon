#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Record the Gantry carriage in the pinned isolated Java Create instance."""
import json
from pathlib import Path
import tempfile

from chain_drive_checks import Original, xyz
from common import PINS, ROOT


CASES = (('east', 99, 948, -128, 950), ('west', 104, 950, 128, 948),
         ('powered', 109, 948, -128, 949))
TRACE_TICKS = 14


def rig(put, z, initial, rpm):
    rails = [(x, 100, z) for x in range(948, 951)]
    for pos in rails:
        put(pos, 'create:gantry_shaft[facing=east]')
    put((initial, 101, z), 'create:gantry_carriage[facing=up,axis_along_first=false]')
    put((initial, 102, z), 'minecraft:oak_planks')

    def power():
        put((947, 100, z), f'create:creative_motor[facing=east]{{ScrollValue:{rpm}}}')

    return rails, power


def java_reference():
    host = Original()
    work = Path(tempfile.mkdtemp(prefix='gantry-reference-', dir=ROOT / '.local'))

    def blocks(points, ticks=1):
        return host.call('observe_ticks', {'ticks': ticks, 'positions': points})['samples'][-1]['blocks']

    def put(pos, state):
        host.command(f'setblock {xyz(pos)} {state}')

    try:
        assert host.call('state', {})['data_version'] == 3955
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        host.command('tp @s 954.5 109 104.5')
        host.command('forceload add 944 96 959 111')
        blocks([(949, 100, 104)], 40)
        host.command('fill 944 97 97 958 107 111 minecraft:air')
        result = dict(create=PINS['create_revision'], cases={})
        for name, z, initial, rpm, destination in CASES:
            rails, power = rig(put, z, initial, rpm)
            assert [b['properties']['part'].lower() for b in blocks(rails)] == ['start', 'middle', 'end']
            power()
            carriage = [(x, y, z) for x in range(948, 951) for y in (101, 102)]
            positions, presence = [], []
            for tick in range(TRACE_TICKS):
                if name == 'powered' and tick == 6:
                    put((949, 100, z + 1), 'minecraft:redstone_block')
                observed = blocks(rails + carriage)
                moving = [entity for entity in host.call('entities', {'center': [949, 101, z], 'radius': 3})['entities']
                          if entity['type'] == 'create:gantry_contraption']
                assert len(moving) <= 1, moving
                positions.append(moving[0]['position'][0] if moving else None)
                presence.append([block['id'] for block in observed[3:]])
            index = 2 * (destination - 948)
            final = presence[-1]
            assert final[index:index + 2] == ['create:gantry_carriage', 'minecraft:oak_planks'], final
            assert final.count('create:gantry_carriage') == final.count('minecraft:oak_planks') == 1
            if name == 'powered':
                assert all(block['properties']['powered'] == 'true' for block in observed[:3]), observed
            result['cases'][name] = dict(positions=positions, presence=presence, landed=destination)
        path = work / 'result.json'
        path.write_text(json.dumps(result, indent=2) + '\n')
        print(path)
    finally:
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


if __name__ == '__main__':
    java_reference()
