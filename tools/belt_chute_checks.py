#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare Belt-to-Chute-to-Belt transfer across a loaded chunk boundary."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile
import time

from bearing_native_checks import Batch
from burner_heat_java_checks import field, items, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession
import reference_java


X, Y = 2093, 121
LANES = {'chute': 1314, 'smart_chute': 1318}
ROOM = '2091 118 1312 2102 126 1320'
FORCE = '2080 1312 2111 1327'
CARGO = 'minecraft:iron_ingot'
MARK = 'belt_chute_probe'
PHASES = {'warm': 32, 'release': 19, 'running': 68}


def points(z):
    return (X, Y, z), (X+3, Y, z), (X+3, Y-1, z), (X+7, Y-1, z)


PROBES = [pos for z in LANES.values() for pos in points(z)]


def motor(command, pos):
    x, y, z = pos
    command(f'setblock {x} {y} {z-1} create:creative_motor[facing=south]{{ScrollValue:-32}}')


def setup(command, step):
    command(f'fill {ROOM} minecraft:air')
    for chute_id, z in LANES.items():
        source, chute, outlet, depot = points(z)
        command(f'setblock {xyz(depot)} create:depot')
        suffix = '[facing=down,shape=window]' if chute_id == 'chute' else '[powered=true]'
        command(f'setblock {xyz(chute)} create:{chute_id}{suffix}')
        if chute_id == 'smart_chute':
            command(f'setblock {X+3} {Y} {z+1} minecraft:redstone_block')
        for (x, y, _), parts in ((source, ('start', 'middle', 'end')),
                                 (outlet, ('start', 'middle', 'middle', 'end'))):
            for i, part in enumerate(parts):
                command(f'setblock {x+i} {y} {z} create:belt[facing=east,slope=horizontal,part={part}]')
        motor(command, source)
    step(24)
    for marker, z in enumerate(LANES.values(), 1):
        source = points(z)[0]
        command(f'data merge block {xyz(source)} {{Inventory:{{PositiveOrder:1b,Items:[{{'
                f'Item:{{id:"{CARGO}",count:7,components:{{"minecraft:custom_data":{{{MARK}:{marker}}}}}}},'
                'Pos:2.65f,PrevPos:2.65f,InDirection:5,InSegment:2,Angle:180}]}}')


def phase(command, name):
    if name == 'release':
        command(f'setblock {X+3} {Y} {LANES["smart_chute"]+1} minecraft:air')
    elif name == 'running':
        for z in LANES.values():
            motor(command, points(z)[2])


def snapshot(raw):
    out = {}
    for marker, name in enumerate(LANES, 1):
        cargo = []
        for nbt, key in zip(raw[4*(marker-1):4*marker],
                            ('Inventory', 'Item', 'Inventory', 'HeldItem'), strict=True):
            data = field(nbt, key) if f'{key}:' in nbt else '{}'
            if f'{MARK}:' not in data:
                cargo.append(None)
                continue
            assert items(nbt, key) == {CARGO: 7} and number({'nbt': data}, MARK) == marker, data
            cargo.append([number({'nbt': data}, key, 0) for key in ('Pos', 'PrevPos', 'InDirection')])
        assert sum(value is not None for value in cargo) == 1, (name, cargo)
        out[name] = dict(cargo=cargo, chute=number({'nbt': raw[4*(marker-1)+1]}, 'ItemPosition', 0)
                         if cargo[1] is not None else None)
    return out


def verify(phases):
    parked = phases['warm'][-1]
    assert parked == phases['cold'][0], (parked, phases['cold'])
    assert parked['chute']['cargo'][2] is not None
    assert parked['smart_chute']['cargo'][0][:2] == [2.75, 2.75]
    for name in LANES:
        assert phases['release'][-1][name]['cargo'][2] is not None
        assert phases['running'][-1][name]['cargo'][3] is not None


def java(work):
    host = Original()
    initial = host.call('state', {})
    if initial.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955

    def step(ticks):
        return host.call('observe_ticks', {'positions': PROBES, 'ticks': ticks})['samples']

    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {FORCE}')
        host.command(f'tp @s {X+3}.5 125 1316.5')
        step(24)
        setup(host.command, step)
        phases = {'warm': [snapshot([block['nbt'] for block in sample['blocks']])
                           for sample in step(PHASES['warm'])]}
        host.call('quit', {})
        deadline = time.monotonic() + 60
        while reference_java.process_alive(reference_java.BASE):
            if time.monotonic() >= deadline:
                raise RuntimeError('The reference Java world did not save and quit')
            time.sleep(.2)
        assert reference_java.launch(reference_java.BASE)['ready']
        host.call('tick', {'frozen': True})
        for _ in range(10):
            blocks = [host.call('block', {'pos': pos}) for pos in PROBES]
            if all(block['id'] != 'minecraft:air' for block in blocks):
                break
            step(5)
        else:
            raise RuntimeError('Saved Belt–Chute fixture did not reload')
        phases['cold'] = [snapshot([block['nbt'] for block in blocks])]
        for name in ('release', 'running'):
            phase(host.command, name)
            phases[name] = [snapshot([block['nbt'] for block in sample['blocks']])
                            for sample in step(PHASES[name])]
        return phases
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

    def read(batch, label):
        values = batch.run(session, label)
        return [snapshot(values[i:i+len(PROBES)]) for i in range(0, len(values), len(PROBES))]

    warm = Batch()
    warm.load((X+3, 124, 1316))
    setup(warm.command, warm.tick)
    observe(warm, PHASES['warm'])
    first = read(warm, 'before-restart')

    after = Batch()
    after.load((X+3, 124, 1316))
    observe(after, 0)
    for name in ('release', 'running'):
        phase(after.command, name)
        observe(after, PHASES[name])
    cold, *resumed = read(after, 'after-restart')
    return dict(warm=first, cold=[cold], release=resumed[:PHASES['release']], running=resumed[PHASES['release']:])


def incomplete_output(session):
    belt = (2105, 120, 1316)
    chute = (2105, 121, 1316)
    output = Batch()
    output.load((2105, 125, 1316))
    output.command('fill 2104 119 1315 2108 123 1317 minecraft:air')
    state = 'create:belt[facing=east,slope=horizontal,part='
    output.put(belt, state + 'middle]')
    output.put(chute, 'create:chute[facing=down,shape=window]')
    output.command(f'data merge block {xyz(chute)} {{Item:{{id:"{CARGO}",count:7,'
                   f'components:{{"minecraft:custom_data":{{{MARK}:17}}}}}},ItemPosition:0.2f}}')
    output.tick(8)
    output.data(chute)
    output.data(belt)
    output.put(belt, state + 'start]')
    output.put((2106, 120, 1316), state + 'end]')
    output.tick(12)
    output.data(chute)
    output.data(belt)
    blocked, broken, cleared, complete = output.run(session, 'incomplete-outlet')
    assert f'{MARK}:17' in blocked.replace(' ', '') and MARK not in broken, (blocked, broken)
    assert MARK not in cleared and f'{MARK}:17' in complete.replace(' ', ''), (cleared, complete)
    assert items(complete, 'Inventory') == {CARGO: 7}, complete
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'resources', 'ctl'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--reference', type=Path, action='append',
                        help='A full Java trace. Repeat for another observed ticker order.')
    args = parser.parse_args()
    if args.game:
        if not all((args.resources, args.ctl, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl and --reference')
        references = [json.loads(path.read_text()) for path in args.reference]
        assert all(row['passed'] and row['create'] == PINS['create_revision'] for row in references)
        session = NativeCheckSession(args.game, args.resources, args.ctl, None, graphics=False,
                                     name='belt-chute-native', world='BeltChute')
        work = session.scratch
        try:
            phases = native(session)
            safe_refusal = incomplete_output(session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    else:
        work = Path(tempfile.mkdtemp(prefix='belt-chute-java-', dir=ROOT / '.local'))
        phases = java(work)
        safe_refusal = None
    path = work / 'result.json'
    report = dict(passed=False, create=PINS['create_revision'], phases=phases, safe_refusal=safe_refusal)
    path.write_text(json.dumps(report, indent=2) + '\n')
    verify(phases)
    if args.game:
        matches = [path.parent.name for path, row in zip(args.reference, references, strict=True)
                   if phases == row['phases']]
        if not matches:
            differences = [
                [(name, tick) for name, rows in phases.items()
                 for tick, (actual, original) in enumerate(
                     zip(rows, reference['phases'][name], strict=True), 1) if actual != original]
                for reference in references
            ]
            raise AssertionError(('No full Java trace matched', min(differences, key=len)))
        report['matching_java'] = matches
    report['passed'] = True
    path.write_text(json.dumps(report, indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
