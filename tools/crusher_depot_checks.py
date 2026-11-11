#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare direct downward Crushing Wheel output to an ordinary Depot."""
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
from crushing_wheel_checks import AIR, CHUTE, COBBLE, CONTROLLER, GRAVEL, X, Y, put, seed_chute, wheels
from native_check_session import NativeCheckSession
import reference_java


LANES = dict(open=929, held=934, buffer=939, multi=944)
LOAD = '2128 912 2143 959'
REGION = '2132 166 927 2136 171 947'
DROPS = '@e[type=minecraft:item,x=2132,y=166,z=927,dx=4,dy=6,dz=20]'
DEPOT = 'create:depot'
DIAMOND = 'minecraft:diamond'
SAND = 'minecraft:sand'
PHASES = dict(warm=16, cold=0, first_release=3, second_release=2)


def positions(z):
    return (X, Y, z), (X, Y - 1, z)


POINTS = [p for z in LANES.values() for p in positions(z)]


def set_buffer(command, count):
    _, depot = positions(LANES['buffer'])
    slots = f'{{Slot:0,id:"{DIAMOND}",count:{count}}}' if count else ''
    command(f'data merge block {xyz(depot)} {{OutputBuffer:{{Size:8,Items:[{slots}]}}}}')


def setup(command, advance):
    command(f'fill {REGION} {AIR}')
    command(f'kill {DROPS}')
    for z in LANES.values():
        _, depot = positions(z)
        put(command, depot, DEPOT)
        wheels(command, z)
    advance(28)
    for name, z in LANES.items():
        if name != 'multi':
            put(command, (X, Y + 1, z), CHUTE)

    _, held = positions(LANES['held'])
    command(f'data merge block {xyz(held)} {{HeldItem:{{Item:{{id:"{DIAMOND}",count:1}},'
            'Pos:0.5f,PrevPos:0.5f,Angle:180,InDirection:1}}')
    set_buffer(command, 1)
    # Chute placement while the Java world is frozen refreshes the adjacent
    # controller with zero effective speed. Let the wheels' lazy update run.
    advance(28)
    controller, _ = positions(LANES['multi'])
    components = 'components:{"minecraft:custom_data":{crusher_depot_marker:%d}}'
    slots = ','.join(f'{{Slot:{slot}b,id:"{item}",count:{count},{components % marker}}}'
                     for slot, item, count, marker in [(1, GRAVEL, 70, 51), (2, SAND, 2, 52)])
    command(f'data merge block {xyz(controller)} '
            f'{{Inventory:{{Size:32,Items:[{slots}],ProcessingTime:0f,RecipeTime:0f,AppliedRecipe:1b}}}}')
    for marker, (name, z) in enumerate(LANES.items(), 1):
        if name != 'multi':
            seed_chute(command, z, COBBLE, 1, marker)


def release(command, phase):
    if phase == 'first_release':
        _, depot = positions(LANES['held'])
        command(f'data remove block {xyz(depot)} HeldItem')
        set_buffer(command, 0)
    if phase in ('first_release', 'second_release'):
        _, depot = positions(LANES['multi'])
        command(f'data remove block {xyz(depot)} HeldItem')


def snapshot(values):
    rows = {}
    for lane, crusher, depot in zip(LANES, values[::2], values[1::2], strict=True):
        assert CONTROLLER in crusher and DEPOT in depot, (crusher, depot)
        inventory = field(crusher, 'Inventory')
        assert number({'nbt': inventory}, 'Size') == 32, inventory
        source = dict(items=items(crusher, 'Inventory'),
                      slots=[int(v) for v in re.findall(r'\bSlot\s*:\s*(\d+)', inventory)],
                      marks=[int(v) for v in re.findall(r'\bcrusher_depot_marker\s*:\s*(\d+)', inventory)],
                      timer=number({'nbt': inventory}, 'ProcessingTime'),
                      recipe_time=number({'nbt': inventory}, 'RecipeTime'),
                      applied=bool(number({'nbt': inventory}, 'AppliedRecipe')))
        held = None
        if 'HeldItem:' in depot:
            nbt = field(depot, 'HeldItem')
            held = dict(items=items(nbt, 'Item'), marker=number({'nbt': nbt}, 'crusher_depot_marker', 0),
                        direction=number({'nbt': nbt}, 'InDirection'))
            angle = number({'nbt': nbt}, 'Angle')
            assert 0 <= angle <= 359, nbt
            for key in ('Pos', 'PrevPos'):
                assert number({'nbt': nbt}, key) == .5, nbt
            for key in ('Offset', 'PrevOffset'):
                assert abs(number({'nbt': nbt}, key, 0) - (angle - 180) / 1080) < 1e-6, nbt
        rows[lane] = dict(crusher=source, held=held, buffer=items(depot, 'OutputBuffer'))
    return rows


def verify(phases):
    warm = phases['warm']
    for name in ('open', 'held', 'buffer'):
        assert warm[0][name]['crusher']['items'] == {COBBLE: 1}, warm[0]
        at_apply = warm[12][name]['crusher']
        assert at_apply['applied'] and at_apply['items'] == {GRAVEL: 1} and at_apply['slots'] == [1], at_apply
    single = dict(items={GRAVEL: 1}, marker=0, direction=0)
    settled = warm[-1]
    assert settled['open']['held'] == single and settled['open']['crusher']['applied'], settled
    assert not settled['open']['crusher']['items'], settled
    assert all(row['held'] == settled['held'] and row['buffer'] == settled['buffer'] for row in warm[12:]), warm
    assert settled['held']['held'] == dict(items={DIAMOND: 1}, marker=0, direction=1), settled
    assert settled['buffer']['held'] is None and settled['buffer']['buffer'] == {DIAMOND: 1}, settled
    assert settled['multi']['held'] == dict(items={GRAVEL: 64}, marker=51, direction=0), settled
    assert settled['multi']['crusher']['items'] == {GRAVEL: 6, SAND: 2}, settled
    assert settled['multi']['crusher']['slots'] == [1, 2] and settled['multi']['crusher']['marks'] == [51, 52], settled
    if 'cold' in phases:
        cold = phases['cold'][0]
        open_lane = dict(settled['open'], crusher=dict(settled['open']['crusher'], applied=False))
        assert cold == dict(settled, open=open_lane), cold
    first = phases['first_release'][0]
    assert first['held']['held'] == first['buffer']['held'] == single, first
    assert first['held']['crusher']['applied'] and first['buffer']['crusher']['applied'], first
    assert not first['held']['crusher']['items'] and not first['buffer']['crusher']['items'], first
    assert not first['buffer']['buffer'], first
    assert first['multi']['held'] == dict(items={GRAVEL: 6}, marker=51, direction=0), first
    assert first['multi']['crusher']['items'] == {SAND: 2} and first['multi']['crusher']['slots'] == [2], first
    second = phases['second_release'][0]
    assert second['multi']['held'] == dict(items={SAND: 2}, marker=52, direction=0), second
    assert second['multi']['crusher']['applied'] and not second['multi']['crusher']['items'], second
    for samples in phases.values():
        for row in samples:
            assert all(lane['crusher']['recipe_time'] == 0 for lane in row.values()), row


def java_run(work):
    host = Original()
    base = reference_java.BASE
    assert json.loads((base / 'manifest.json').read_text())['create_sha256'] == reference_java.CREATE_SHA256
    state = host.call('state', {})
    assert state['ready'] and state['data_version'] == 3955, state
    host.call('tick', {'frozen': True})

    def advance(ticks):
        return host.call('observe_ticks', {'positions': POINTS, 'ticks': ticks})['samples']

    try:
        host.command(f'forceload add {LOAD}')
        host.call('observe_ticks', {'positions': [list(map(int, state['position']))], 'ticks': 40})
        setup(host.command, advance)
        phases = {}
        for name, ticks in PHASES.items():
            if name == 'cold':
                host.call('quit', {})
                deadline = time.monotonic() + 60
                while reference_java.process_alive(base):
                    if time.monotonic() >= deadline:
                        raise RuntimeError('The isolated Java client did not stop after saving')
                    time.sleep(.2)
                resumed = reference_java.launch(base)
                assert resumed['ready'], resumed
                host.call('tick', {'frozen': True})
                for _ in range(10):
                    blocks = [host.call('block', {'pos': pos}) for pos in POINTS]
                    if all(block['id'] in (CONTROLLER, DEPOT) for block in blocks):
                        break
                    host.call('observe_ticks', {'positions': [list(map(int, resumed['position']))], 'ticks': 5})
                else:
                    raise RuntimeError('Saved crusher and depot columns did not reload')
                samples = [dict(blocks=blocks)]
            else:
                release(host.command, name)
                samples = advance(ticks)
            phases[name] = [snapshot([b['nbt'] for b in row['blocks']]) for row in samples]
            drops = host.command(f'execute if entity {DROPS} run say loose_crusher_depot')
            assert not any('loose_crusher_depot' in line for line in drops['messages']), drops
        return phases
    finally:
        host.command(f'fill {REGION} {AIR}')
        host.command(f'kill {DROPS}')
        host.command(f'forceload remove {LOAD}')
        host.call('tick', {'frozen': state['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    phases = {}
    n = len(POINTS)
    for label, names in [('before-restart', ('warm',)), ('after-restart', tuple(PHASES)[1:])]:
        batch = Batch()
        batch.load((X, Y + 4, 937))
        if label == 'before-restart':
            setup(batch.command, batch.tick)
        for name in names:
            release(batch.command, name)
            for _ in range(PHASES[name] or 1):
                if PHASES[name]:
                    batch.tick()
                for pos in POINTS:
                    batch.data(pos)
            batch.command(f'execute if entity {DROPS} run say loose_crusher_depot', True)
        values = batch.run(session, label)
        offset = 0
        for name in names:
            end = offset + n * (PHASES[name] or 1)
            phases[name] = [snapshot(values[i:i + n]) for i in range(offset, end, n)]
            assert 'loose_crusher_depot' not in values[end], values[end]
            offset = end + 1
        assert offset == len(values), (offset, len(values))
    return phases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='crusher-depot-java-', dir=ROOT / '.local'))
        phases = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon runs require --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None, graphics=False,
                                     name='crusher-depot-native', world='CreateCrusherDepot')
        work = session.scratch
        try:
            phases = native_run(session)
        finally:
            session.control_temp.cleanup()
            for path in (session.resources, work / '.horizon-cache'):
                shutil.rmtree(path, ignore_errors=True)
    (work / 'observed.json').write_text(json.dumps(phases, indent=2) + '\n')
    verify(phases)
    if not args.java:
        for name, expected in reference['phases'].items():
            for tick, (got, wanted) in enumerate(zip(phases[name], expected, strict=True), 1):
                assert got == wanted, (name, tick, got, wanted)
    path = work / 'result.json'
    path.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], phases=phases), indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
