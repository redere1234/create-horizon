#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Check that a filter change cannot interrupt an active Deployer stroke."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile
import time

from bearing_native_checks import Batch
from burner_heat_java_checks import field, items, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession


DEPOT = (1957, 126, 1239)
DEPLOYER = (1957, 128, 1239)
MOTOR = (1956, 128, 1239)
PROBES = (DEPOT, DEPLOYER)
FEET = (1957.5, 127, 1242.5)
AIM = (1957.5, 128.625, 1239.96875)
AREA = '1955 124 1237 1960 130 1242'
LOAD = '1957 1239'
PLANK = 'minecraft:oak_planks'
NUGGET = 'minecraft:iron_nugget'
SHAFT = 'create:shaft'
COG = 'create:cogwheel'
SAMPLES = (1, 3, 12)


def install(command, tick):
    command(f'fill {AREA} minecraft:air')
    command('fill 1955 124 1237 1960 124 1242 minecraft:stone')
    command('setblock 1957 126 1242 minecraft:stone')
    command(f'setblock {xyz(DEPOT)} create:depot')
    command(f'setblock {xyz(DEPLOYER)} create:deployer[facing=down,axis_along_first=true]'
            f'{{Mode:"USE",State:"WAITING",Timer:0,Inventory:[{{Slot:0b,id:"{PLANK}",count:2,'
            'components:{"minecraft:custom_data":{filter_probe:19}}}]}')
    tick(2)
    command(f'setblock {xyz(MOTOR)} create:creative_motor[facing=east]{{ScrollValue:256}}')
    tick(23)
    command(f'data merge block {xyz(DEPOT)} {{HeldItem:{{Item:{{id:"{SHAFT}",count:2}},'
            'Pos:.5f,PrevPos:.5f,Angle:180,InDirection:1}}')


def set_filter(host, item):
    host.command(f'item replace entity @s weapon.mainhand with {item} 1')
    host.call('camera', {'position': FEET, 'target': AIM})
    for _ in range(12):
        hit = host.call('state', {})['hit']
        if hit and hit['pos'] == list(DEPLOYER) and hit['face'] == 'south':
            break
        time.sleep(.02)
    else:
        raise AssertionError(('The crosshair did not reach the filter slot', hit))
    host.call('input', {'key': 'use'})


def snapshot(depot, deployer):
    phase = re.search(r'\bState\s*:\s*"([A-Z]+)"', deployer)
    assert phase, deployer
    hand = field(deployer, 'HeldItem')
    return dict(state=phase[1], timer=int(number({'nbt': deployer}, 'Timer')),
                hand=items(deployer, 'HeldItem'), marked='filter_probe:19' in re.sub(r'\s+', '', hand),
                filter=items(deployer, 'Filter') if re.search(r'\bFilter\s*:', deployer) else {},
                depot=items(depot, 'HeldItem'), buffer=items(depot, 'OutputBuffer'))


def verify(rows):
    started = rows[0]
    assert started['state'] == 'EXPANDING' and started['hand'] == {PLANK: 2} and started['marked'], started
    active = rows[1:1 + SAMPLES[1]]
    applied = next((row for row in active if row['buffer'] == {COG: 1}), None)
    assert applied and applied['state'] == 'RETRACTING' and 0 < applied['timer'] <= 1000, active
    assert applied['filter'] == {NUGGET: 1} and applied['hand'] == {PLANK: 1} and applied['marked'], applied
    assert applied['depot'] == {SHAFT: 1} and applied['buffer'] == {COG: 1}, applied
    final = rows[-1]
    assert final['filter'] == {PLANK: 1} and not final['hand'] and not final['marked'], final
    assert final['depot'] == final['buffer'] == {COG: 1}, final


def original(work):
    host = Original()
    state = host.call('state', {})
    if state.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        state = host.call('state', {})
    assert state['ready'] and state['data_version'] == 3955, state
    host.call('tick', {'frozen': True})

    def sample(ticks):
        return host.call('observe_ticks', {'ticks': ticks, 'positions': PROBES})['samples']

    try:
        host.command(f'forceload add {LOAD}')
        host.command(f'tp @s {xyz(FEET)}')
        sample(24)
        install(host.command, sample)
        rows = []
        for item, count in zip((None, NUGGET, PLANK), SAMPLES, strict=True):
            if item:
                set_filter(host, item)
            rows.extend(snapshot(*(block['nbt'] for block in row['blocks'])) for row in sample(count))
        return rows
    finally:
        host.command('item replace entity @s weapon.mainhand with minecraft:air')
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('camera', {key: state[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': state['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session):
    # Debug /tick step has zero effective kinetic RPM. A command script advances
    # the real simulation and changes only the filter NBT between normal ticks.
    batch = Batch()
    batch.load(DEPLOYER)
    install(batch.command, batch.tick)
    for item, count in zip((None, NUGGET, PLANK), SAMPLES, strict=True):
        if item:
            batch.command(f'data merge block {xyz(DEPLOYER)} {{Filter:{{id:"{item}",count:1}}}}')
        for _ in range(count):
            batch.tick()
            for pos in PROBES:
                batch.data(pos)
    values = batch.run(session, 'filter-during-stroke')
    return [snapshot(depot, deployer) for depot, deployer in zip(values[::2], values[1::2], strict=True)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.game:
        if not all((args.resources, args.ctl, args.reference)):
            parser.error('Horizon needs --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='deployer-filter-transport-native', graphics=False,
                                     world='DeployerFilterTransport')
        work = session.scratch
        try:
            rows = native(session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    else:
        work = Path(tempfile.mkdtemp(prefix='deployer-filter-transport-java-', dir=ROOT / '.local'))
        rows = original(work)
    report = dict(passed=False, create=PINS['create_revision'], rows=rows)
    path = work / 'result.json'
    try:
        verify(rows)
        if args.game:
            for tick, (actual, expected) in enumerate(zip(rows, reference['rows'], strict=True), 1):
                assert actual == expected, (tick, actual, expected)
        report['passed'] = True
    finally:
        path.write_text(json.dumps(report, indent=2) + '\n')
        print(path, flush=True)


if __name__ == '__main__':
    main()
