#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Record the original portable item interface on a vertical bearing."""

import json
from pathlib import Path
import tempfile

from burner_heat_java_checks import items, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT


BLOCK = 'create:portable_storage_interface'
X, Y, Z = 1400, 146, 151
PIVOT = (X, Y, Z)
MOTOR = (X, Y - 1, Z)
MOVING = (X + 2, Y + 1, Z)
MOUNTED = (X - 1, Y + 1, Z)
STATION = (X, Y + 1, Z - 4)
HOPPER = (X, Y, Z - 4)
OUTPUT = (X, Y - 1, Z - 4)
COMPARATOR = (X, Y + 1, Z - 5)
WIRE = (X, Y + 1, Z - 6)
SWITCH = (X - 1, Y + 1, Z - 4)
AIR = 'minecraft:air'
CONTRAPTION = f'@e[type=create:stationary_contraption,x={X},y={Y},z={Z},distance=..12]'


def rig(put, command):
    put(PIVOT, 'create:mechanical_bearing[facing=up]')
    put((X, Y + 1, Z), 'minecraft:slime_block')
    put((X + 1, Y + 1, Z), 'minecraft:slime_block')
    put(MOVING, f'{BLOCK}[facing=east]')
    put(MOUNTED, 'minecraft:chest[facing=north,type=single,waterlogged=false]')
    command(f'item replace block {xyz(MOUNTED)} container.5 with minecraft:wheat 3')
    command(f'item replace block {xyz(MOUNTED)} container.26 '
            'with minecraft:stick[minecraft:custom_data={psi_probe:173}] 2')
    put(STATION, f'{BLOCK}[facing=south]')
    put(HOPPER, 'minecraft:hopper[facing=down]')
    put(OUTPUT, 'minecraft:chest[facing=north,type=single,waterlogged=false]')
    put((X, Y, Z - 5), 'minecraft:stone')
    put((X, Y, Z - 6), 'minecraft:stone')
    put(COMPARATOR, 'minecraft:comparator[facing=south]')
    put(WIRE, 'minecraft:redstone_wire')


def snapshot(sample):
    bearing, psi, hopper, output, comparator, wire = sample['blocks']
    return dict(angle=number(bearing, 'Angle', 0), timer=number(psi, 'Timer'),
                distance=number(psi, 'Distance'), powered=number(psi, 'Powered'),
                hopper=items(hopper.get('nbt', ''), 'Items'),
                output=items(output.get('nbt', ''), 'Items'), output_nbt=output.get('nbt', ''),
                comparator=comparator['properties']['powered'].lower() == 'true',
                wire=int(wire['properties']['power']))


def verify(phases):
    natural = phases['natural']
    received = {'minecraft:wheat': 3, 'minecraft:stick': 2}
    reset_ticks = [tick for tick, row in enumerate(natural, 1) if row['timer'] == 64]
    assert reset_ticks == [11, 19, 27, 35, 43], reset_ticks
    hold = [row['angle'] for row in natural[10:103]]
    assert len(set(hold)) == 1 and abs(hold[0] - 86.399994) < 1e-5, hold
    assert abs(natural[10]['distance'] - 1.0076) < 1e-4, natural[10]
    assert natural[102]['timer'] == 4 and natural[103]['angle'] > hold[0], natural[102:104]
    assert [i for i, row in enumerate(natural, 1) if row['wire'] == 15] == list(range(13, 111))
    assert all(row['wire'] == (15 if row['comparator'] else 0) for row in natural)
    assert natural[50]['output'] == received and not natural[50]['hopper'], natural[50]
    assert 'psi_probe:173' in natural[-1]['output_nbt'], natural[-1]

    powered, unpowered = (phases['redstone'][name] for name in ('powered', 'unpowered'))
    assert all(row['powered'] == 1 for row in powered), powered
    assert powered[0]['timer'] == 3 and powered[0]['angle'] > hold[0], powered[0]
    assert powered[-1]['output'] == {'minecraft:wheat': 2} and not powered[-1]['hopper'], powered[-1]
    assert powered[-1]['timer'] == powered[-1]['wire'] == 0, powered[-1]
    assert all(row['powered'] == 0 for row in unpowered), unpowered
    assert any(row['timer'] == 64 and row['wire'] == 15 for row in unpowered), unpowered
    assert unpowered[-1]['output'] == received and not unpowered[-1]['hopper'], unpowered[-1]


def main():
    host = Original()
    work = Path(tempfile.mkdtemp(prefix='psi-reference-', dir=ROOT / '.local'))
    loaded = False
    points = (PIVOT, STATION, HOPPER, OUTPUT, COMPARATOR, WIRE)

    def put(pos, state):
        host.command(f'setblock {xyz(pos)} {state}')

    def observe(ticks):
        return [snapshot(sample) for sample in host.call('observe_ticks', {
            'ticks': ticks, 'positions': points,
        })['samples']]

    try:
        assert host.call('state', {})['data_version'] == 3955
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        host.command(f'tp @s {X}.5 {Y + 8} {Z}.5')
        host.command('forceload add 1392 144 1407 159')
        loaded = True
        host.call('observe_ticks', {'ticks': 24, 'positions': [PIVOT]})
        phases = {}
        for phase in ('natural', 'redstone'):
            host.command(f'kill {CONTRAPTION}')
            host.command(f'fill {X - 6} {Y - 3} {Z - 7} {X + 5} {Y + 5} {Z + 5} {AIR}')
            rig(put, host.command)
            observe(3)
            put(MOTOR, 'create:creative_motor[facing=up]{ScrollValue:32}')
            initial = observe(24)
            if phase == 'redstone':
                put(SWITCH, 'minecraft:redstone_block')
                stopped = observe(10)
                put(SWITCH, AIR)
                phases[phase] = dict(initial=initial, powered=stopped, unpowered=observe(60))
            else:
                phases[phase] = initial + observe(110)
        result = work / 'result.json'
        result.write_text(json.dumps(dict(create=PINS['create_revision'], phases=phases), indent=2) + '\n')
        verify(phases)
        print(result)
    finally:
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
        if loaded:
            host.command(f'kill {CONTRAPTION}')
            host.command('forceload remove 1392 144 1407 159')


if __name__ == '__main__':
    main()
