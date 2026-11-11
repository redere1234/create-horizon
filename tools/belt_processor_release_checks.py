#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Check that removing a Deployer releases its held Belt cargo after reload."""

import argparse
import json
from pathlib import Path
import shutil
import struct
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field, items, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession


X, Y, Z = 2494, 131, 1478
START, DEPLOYER, DEPOT = (X, Y, Z), (X + 2, Y + 2, Z), (X + 5, Y, Z)
ROOM = '2492 129 1476 2501 135 1480'
FORCE = '2480 1472 2511 1487'
PROBES = (START, DEPOT)
CARGO = 'create:iron_sheet'
MARKER = 'processor_release_probe'
WARM, HOLD, RELEASE = 18, 6, 48


def setup(command, step):
    command(f'fill {ROOM} minecraft:air')
    command(f'setblock {xyz(DEPOT)} create:depot')
    for i, part in enumerate(('start', 'middle', 'middle', 'middle', 'end')):
        command(f'setblock {X+i} {Y} {Z} create:belt[facing=east,slope=horizontal,part={part}]')
    command(f'setblock {xyz(DEPLOYER)} create:deployer[facing=down,axis_along_first=true]')
    step(3)
    command(f'setblock {X+1} {Y+2} {Z} create:creative_motor[facing=east]{{ScrollValue:64}}')
    command(f'setblock {X} {Y} {Z-1} create:creative_motor[facing=south]{{ScrollValue:-32}}')
    step(24)
    command(f'data merge block {xyz(START)} {{Inventory:{{PositiveOrder:1b,Items:[{{'
            f'Item:{{id:"{CARGO}",count:3,components:{{"minecraft:custom_data":{{{MARKER}:37}}}}}},'
            'Pos:1.9f,PrevPos:1.9f,InDirection:5,InSegment:1,Angle:180}]}}')


def snapshot(belt, depot):
    cargo = []
    for nbt, key in ((belt, 'Inventory'), (depot, 'HeldItem')):
        container = field(nbt, key) if f'{key}:' in nbt else '{}'
        if f'{MARKER}:' not in container:
            cargo.append(None)
            continue
        data = {'nbt': container}
        assert items(nbt, key) == {CARGO: 3} and number(data, MARKER) == 37, container
        position = struct.unpack('f', struct.pack('f', number(data, 'Pos')))[0]
        cargo.append(dict(position=position, locked=number(data, 'Locked', 0) == 1))
    assert sum(item is not None for item in cargo) == 1, cargo
    return dict(belt=cargo[0], depot=cargo[1])


def verify(warm, cold, held, resumed):
    assert warm[-1] == cold
    assert cold['belt'] == dict(position=2.5 + 1 / 512, locked=True)
    assert all(row == cold for row in held), held
    assert resumed[0]['belt'] and not resumed[0]['belt']['locked'], resumed[0]
    assert resumed[0]['belt']['position'] > cold['belt']['position'], resumed[0]
    assert resumed[-1]['belt'] is None and resumed[-1]['depot'], resumed[-1]


def original(work):
    host = Original()
    initial = host.call('state', {})
    if initial.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955

    def step(ticks):
        samples = host.call('observe_ticks', {'positions': PROBES, 'ticks': ticks})['samples']
        return [snapshot(*(block['nbt'] for block in row['blocks'])) for row in samples]

    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {FORCE}')
        host.command(f'tp @s {X+2}.5 {Y+4} {Z}.5')
        host.call('observe_ticks', {'positions': PROBES, 'ticks': 24})
        setup(host.command, lambda ticks: host.call('observe_ticks', {'positions': PROBES, 'ticks': ticks}))
        warm = step(WARM)
        held = step(HOLD)
        host.command(f'setblock {xyz(DEPLOYER)} minecraft:air')
        return warm, warm[-1], held, step(RELEASE)
    finally:
        host.command(f'fill {ROOM} minecraft:air')
        host.command(f'forceload remove {FORCE}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session):
    def observe(batch, ticks):
        for _ in range(ticks or 1):
            if ticks:
                batch.tick()
            for pos in PROBES:
                batch.data(pos)

    def read(batch, name):
        rows = batch.run(session, name)
        return [snapshot(belt, depot) for belt, depot in zip(rows[::2], rows[1::2], strict=True)]

    before = Batch()
    before.load((X + 2, Y + 3, Z))
    setup(before.command, before.tick)
    observe(before, WARM)
    warm = read(before, 'before-restart')

    after = Batch()
    after.load((X + 2, Y + 3, Z))
    observe(after, 0)
    after.command(f'forceload add {X} {Z}')
    after.load((X + 256, Y + 3, Z + 256))
    after.tick(120)
    after.command(f'execute if loaded {xyz(START)} run say source_loaded', True)
    after.command(f'execute if loaded {xyz(DEPLOYER)} run say processor_loaded', True)
    after.data(START)
    after.load((X + 2, Y + 3, Z))
    after.command(f'forceload remove {X} {Z}')
    observe(after, HOLD)
    after.command(f'setblock {xyz(DEPLOYER)} minecraft:air')
    observe(after, RELEASE)
    belt, depot, source, processor, unloaded, *rows = after.run(session, 'after-restart')
    cold = snapshot(belt, depot)
    assert 'source_loaded' in source and 'processor_loaded' not in processor, (source, processor)
    assert snapshot(unloaded, depot) == cold
    resumed = [snapshot(belt, depot) for belt, depot in zip(rows[::2], rows[1::2], strict=True)]
    return warm, cold, resumed[:HOLD], resumed[HOLD:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    reference = None
    if args.game:
        if not all((args.resources, args.ctl, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None, graphics=False,
                                     name='belt-processor-release-native', world='BeltProcessorRelease')
        work = session.scratch
        try:
            phases = native(session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    else:
        work = Path(tempfile.mkdtemp(prefix='belt-processor-release-java-', dir=ROOT / '.local'))
        phases = original(work)
    path = work / 'result.json'
    report = dict(passed=False, create=PINS['create_revision'], phases=phases)
    path.write_text(json.dumps(report, indent=2) + '\n')
    verify(*phases)
    if reference:
        assert phases[1] == reference['phases'][1], (phases[1], reference['phases'][1])
        for index, name in ((0, 'warm'), (2, 'held'), (3, 'release')):
            rows = zip(phases[index], reference['phases'][index], strict=True)
            for tick, (row, original_row) in enumerate(rows, 1):
                # The receiver can run its own slide tick before or after
                # Belt delivery. Compare the exact transfer tick and Belt
                # pose, independent of the Depot's interpolation phase.
                assert (row['belt'], bool(row['depot'])) == (
                    original_row['belt'], bool(original_row['depot'])
                ), (name, tick, row, original_row)
    report['passed'] = True
    path.write_text(json.dumps(report, indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
