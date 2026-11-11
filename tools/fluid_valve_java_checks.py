#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Observe an inline Fluid Valve with an independently driven shaft in Java."""

import argparse
import json
from pathlib import Path
import tempfile
import time

from burner_heat_java_checks import field, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from fluid_pump_java_checks import PIPE, PUMP, TANK, amount, measure, put, seed
import reference_java as java


X, Y, Z = 2560, 143, 1415
VALVE = 'create:fluid_valve'
POSITIONS = [(X+i, Y, Z) for i in range(6)]
SOURCE, _, PUMP_POS, VALVE_POS, _, TARGET = POSITIONS
PUMP_MOTOR = (X+1, Y, Z-1)
VALVE_MOTOR = (X+3, Y, Z-2)
SHIFT = (X+3, Y, Z-1)
SIGNAL = (X+4, Y, Z-1)
LOAD = '2544 1408 2575 1423'
AREA = '2558 142 1410 2567 147 1418'


def drive(pos, rpm, face):
    return f'setblock {xyz(pos)} create:creative_motor[facing={face}]{{ScrollValue:{rpm}}}'


def setup(host):
    host.command(f'fill {AREA} minecraft:air')
    host.command('fill 2558 142 1410 2567 142 1418 minecraft:smooth_stone')
    pipe = PIPE + '[east=true,west=true,waterlogged=false]'
    valve = VALVE + '[facing=up,axis_along_first=false,enabled=false,waterlogged=false]'
    for pos, state in zip(POSITIONS, (TANK, pipe, PUMP+'[facing=east,waterlogged=false]', valve, pipe, TANK), strict=True):
        put(host, pos, state)
    put(host, (X+2, Y, Z-1), 'create:cogwheel[axis=x]')
    put(host, SHIFT, 'create:gearshift[axis=z,powered=false]')
    host.command(drive(PUMP_MOTOR, 32, 'east'))


def valve_state(block):
    raw = block['nbt']
    pointer = field(raw, 'Pointer')
    rate = number(dict(nbt=raw.replace(pointer, '{}', 1)), 'Speed', 0)
    data = measure(dict(block, id=PUMP))
    data.update(block=VALVE, speed=rate,
                pointer={key.lower(): number(dict(nbt=pointer), key) for key in ('Value', 'Target', 'Speed')})
    return data


def state(block):
    return valve_state(block) if block['id'] == VALVE else measure(block)


def observe(host, ticks, *commands):
    return [dict(tick=row['tick'], blocks=[state(block) for block in row['blocks']])
            for row in host.call('observe_ticks', {'positions': POSITIONS, 'ticks': ticks,
                                                  'commands': list(commands)})['samples']]


def stopped(host, name, save):
    before = [state(host.call('block', {'pos': pos})) for pos in POSITIONS]
    host.call('quit', {})
    deadline = time.monotonic() + 60
    while java.process_alive(java.BASE):
        if time.monotonic() > deadline:
            raise RuntimeError('The private Java client did not save and exit')
        time.sleep(.2)
    assert java.launch(java.BASE)['ready']
    host.call('tick', {'frozen': True})
    after = [state(host.call('block', {'pos': pos})) for pos in POSITIONS]
    save(name, [dict(before=before, after=after)])
    assert before == after, (before, after)


def verify(rows):
    def valve(row): return row['blocks'][3]
    def target(row): return amount(row['blocks'][-1])
    def enabled(row): return valve(row)['props']['enabled'] == 'true'
    def last(name): return rows[name][-1]

    assert all(not enabled(row) and target(row) == 0 for row in rows['closed'])
    assert valve(last('closed'))['connections']['west']['pressure'] == [32, 0]
    assert valve(last('closed'))['connections']['east']['pressure'] == [0, 32]
    assert valve(last('closed'))['connections']['west']['flow'] is None
    assert valve(last('opening'))['speed'] == 32 and enabled(last('opening')) and target(last('opening')) > 0
    assert valve(last('toward-close'))['speed'] == -32 and enabled(last('toward-close'))
    assert 0 < valve(last('toward-close'))['pointer']['value'] < 1
    assert valve(last('stopped-midway'))['speed'] == 0 and enabled(last('stopped-midway'))
    pointer = valve(last('stopped-midway'))['pointer']
    assert 0 < pointer['value'] < 1 and pointer['speed'] == 0 and pointer['target'] == 0
    assert all(valve(row)['pointer'] == pointer for row in rows['stopped-midway'][-8:])
    assert target(last('stopped-midway')) > target(last('toward-close'))
    assert valve(last('finish-close'))['speed'] == -32 and not enabled(last('finish-close'))
    assert all(not enabled(row) and target(row) == target(last('finish-close')) for row in rows['finish-close'][-8:])
    assert enabled(last('reopen')) and target(last('reopen')) > target(last('finish-close'))
    assert not enabled(last('running-close'))
    assert all(target(row) == target(last('running-close')) for row in rows['running-close'][-8:])
    phases = ('closed', 'opening', 'toward-close', 'stopped-midway', 'finish-close', 'reopen', 'running-close')
    for name in phases:
        assert all(amount(row['blocks'][0]) + target(row) == 8000 for row in rows[name]), name
    return {name: dict(pointer=valve(last(name))['pointer'], valve_rpm=valve(last(name))['speed'],
                       enabled=enabled(last(name)), target=target(last(name))) for name in phases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cold', action='store_true')
    args = parser.parse_args()
    work = Path(tempfile.mkdtemp(prefix='fluid-valve-java-', dir=ROOT / '.local'))
    print(work, flush=True)
    host = Original()
    assert json.loads((java.BASE / 'manifest.json').read_text())['create_sha256'] == java.CREATE_SHA256
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955
    host.call('tick', {'frozen': True})
    phases = {}

    def save(name, data):
        phases[name] = data
        (work / 'observed.json').write_text(json.dumps(phases, indent=2) + '\n')

    def phase(name, ticks, *commands):
        save(name, observe(host, ticks, *commands))

    try:
        host.command(f'forceload add {LOAD}')
        host.call('observe_ticks', {'positions': [list(map(int, initial['position']))], 'ticks': 20})
        host.command(f'tp @s {X+3}.5 {Y+4} {Z+2}.5')
        setup(host)
        observe(host, 16)
        phase('closed', 32, seed(SOURCE, 'water', 8000))
        phase('opening', 48, drive(VALVE_MOTOR, 32, 'south'))
        phase('toward-close', 6, f'setblock {xyz(SIGNAL)} minecraft:redstone_block')
        phase('stopped-midway', 16, f'setblock {xyz(VALVE_MOTOR)} minecraft:air')
        if args.cold:
            phase('parked', 12, f'setblock {xyz(PUMP_MOTOR)} minecraft:air')
            stopped(host, 'cold', save)
        phase('finish-close', 48, drive(PUMP_MOTOR, 32, 'east'), drive(VALVE_MOTOR, 32, 'south'))
        phase('reopen', 48, f'setblock {xyz(SIGNAL)} minecraft:air')
        phase('running-close', 32, f'setblock {xyz(SIGNAL)} minecraft:redstone_block')
        result = dict(passed=True, create=PINS['create_revision'], cold=args.cold, phases=verify(phases))
        (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result, indent=2), flush=True)
    finally:
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('camera', {'position': initial['position'], 'yaw': initial['yaw'], 'pitch': initial['pitch']})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


if __name__ == '__main__':
    main()
