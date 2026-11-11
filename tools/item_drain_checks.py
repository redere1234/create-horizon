#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare ordinary Belt to Item Drain to Depot, including cold restart."""
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
from native_check_session import NativeCheckSession, wait_loaded
import reference_java


X, Y = 2191, 168
LOAD = '2176 976 2207 991'
REGION = '2186 166 976 2194 173 990'
DROPS = '@e[type=minecraft:item,x=2186,y=166,z=976,dx=8,dy=7,dz=14]'
LANES = dict(open=978, full=983, blocked=988)
PHASES = dict(warm=34, cold=0, resumed=30)
DRAIN = 'create:item_drain'
DEPOT = 'create:depot'
BUCKET = 'minecraft:bucket'
FULL = 'minecraft:water_bucket'
DIAMOND = 'minecraft:diamond'
VIEW_Z = 981


def points(z):
    return (X - 4, Y, z), (X, Y, z), (X + 1, Y, z)


PROBES = [pos for z in LANES.values() for pos in points(z)]


def tank(command, amount):
    _, drain, _ = points(LANES['full'])
    fluid = f'Fluid:{{id:"minecraft:water",amount:{amount}}}' if amount else ''
    level = f'{amount / 1500}f'
    command(f'data merge block {xyz(drain)} {{Tanks:[{{TankContent:{{{fluid}}},'
            f'Level:{{Value:{level},Target:{level},Speed:0.25f}}}}]}}')


def setup(command, advance, lava=False):
    command(f'fill {REGION} minecraft:air')
    command(f'kill {DROPS}')
    for z in LANES.values():
        (x, y, _), drain, depot = points(z)
        command(f'setblock {xyz(depot)} {DEPOT}')
        command(f'setblock {xyz(drain)} {DRAIN}')
        for i, part in enumerate(('start', 'middle', 'middle', 'end')):
            command(f'setblock {x+i} {y} {z} create:belt[facing=east,slope=horizontal,part={part}]')
        command(f'setblock {x} {y} {z-1} create:creative_motor[facing=south]{{ScrollValue:-32}}')
    advance(24)
    tank(command, 500 if lava else 1000)
    _, _, depot = points(LANES['blocked'])
    command(f'data merge block {xyz(depot)} {{HeldItem:{{Item:{{id:"{DIAMOND}",count:1}},'
            'Pos:0.5f,PrevPos:0.5f,Angle:180,InDirection:1}}')
    full_bucket = 'minecraft:lava_bucket' if lava else FULL
    for marker, z in enumerate(LANES.values(), 1):
        belt, _, _ = points(z)
        command(f'data merge block {xyz(belt)} {{Inventory:{{PositiveOrder:1b,Items:[{{Item:{{id:"{full_bucket}",count:1,'
                f'components:{{"minecraft:custom_data":{{drain_marker:{marker}}}}}}},'
                'Pos:3.74f,PrevPos:3.74f,Offset:0f,PrevOffset:0f,InSegment:3,InDirection:5,Angle:180}]}}')


def release(command):
    tank(command, 0)
    _, _, depot = points(LANES['blocked'])
    command(f'data remove block {xyz(depot)} HeldItem')


def held(raw, *, pose):
    if 'HeldItem:' not in raw:
        return None
    record = field(raw, 'HeldItem')
    values = dict(items=items(record, 'Item'), marker=int(number({'nbt': record}, 'drain_marker', 0)),
                  from_side=int(number({'nbt': record}, 'InDirection')))
    if pose:
        values['pose'] = [number({'nbt': record}, key) for key in ('Pos', 'PrevPos', 'Offset', 'PrevOffset', 'Angle')]
    return values


def snapshot(values, lava=False):
    out = {}
    for name, belt, drain, depot in zip(LANES, values[::3], values[1::3], values[2::3], strict=True):
        assert 'create:belt' in belt and DRAIN in drain and DEPOT in depot, (belt, drain, depot)
        tank = field(drain, 'Tanks')
        fluid = field(tank, 'TankContent')
        amount = int(number({'nbt': fluid}, 'amount', 0))
        expected_fluid = 'minecraft:lava' if lava and amount != 500 else 'minecraft:water'
        assert not amount or expected_fluid in fluid, fluid
        out[name] = dict(belt=items(belt, 'Inventory'), tank=amount,
                         ticks=int(number({'nbt': drain}, 'ProcessingTicks')),
                         drain=held(drain, pose=True), depot=held(depot, pose=False))
    return out


def verify(phases, lava=False):
    warm = phases['warm']
    first = warm[0]['open']
    full_bucket = 'minecraft:lava_bucket' if lava else FULL
    assert not first['belt'] and first['drain'] == dict(items={full_bucket: 1}, marker=1, from_side=5,
                                                       pose=[0, 0, 0, 0, 180]), first
    assert warm[4]['open']['ticks'] == 20 and warm[4]['open']['drain']['pose'][0] == .5, warm[4]
    assert warm[18]['open']['tank'] == 0 and warm[18]['open']['ticks'] == 6, warm[18]
    exchanged = warm[19]['open']
    assert exchanged['tank'] == 1000 and exchanged['ticks'] == 5, exchanged
    assert exchanged['drain']['items'] == {BUCKET: 1} and exchanged['drain']['marker'] == 0, exchanged
    result = dict(items={BUCKET: 1}, marker=0, from_side=5)
    assert warm[28]['open']['drain']['pose'][0] == 1 and warm[28]['open']['depot'] is None, warm[28]
    assert warm[29]['open']['drain'] is None and warm[29]['open']['depot'] == result, warm[29]
    parked = warm[-1]
    assert parked['full']['ticks'] == 20 and parked['full']['tank'] == (500 if lava else 1000), parked
    assert parked['full']['drain']['items'] == {full_bucket: 1} and parked['full']['drain']['marker'] == 2, parked
    assert parked['blocked']['drain']['items'] == {BUCKET: 1} and parked['blocked']['drain']['pose'][:2] == [1, 1], parked
    assert parked['blocked']['depot']['items'] == {DIAMOND: 1}, parked
    assert phases['cold'][0] == parked, phases['cold']
    first_resume = phases['resumed'][0]
    assert first_resume['blocked']['drain'] is None and first_resume['blocked']['depot'] == result, first_resume
    assert first_resume['full']['ticks'] == 19 and first_resume['full']['tank'] == 0, first_resume
    assert phases['resumed'][-1]['full']['depot'] == result, phases['resumed'][-1]


def java_run(work, lava=False):
    host = Original()
    base = reference_java.BASE
    assert json.loads((base / 'manifest.json').read_text())['create_sha256'] == reference_java.CREATE_SHA256
    state = host.call('state', {})
    assert state['ready'] and state['data_version'] == 3955, state
    host.call('tick', {'frozen': True})

    def advance(ticks):
        return host.call('observe_ticks', {'positions': PROBES, 'ticks': ticks})['samples']

    try:
        host.command(f'forceload add {LOAD}')
        host.call('observe_ticks', {'positions': [list(map(int, state['position']))], 'ticks': 40})
        setup(host.command, advance, lava)
        warm = advance(PHASES['warm'])
        host.call('quit', {})
        deadline = time.monotonic() + 60
        while reference_java.process_alive(base):
            if time.monotonic() >= deadline:
                raise RuntimeError('The isolated Java client did not stop after saving')
            time.sleep(.2)
        state_after = reference_java.launch(base)
        assert state_after['ready'], state_after
        host.call('tick', {'frozen': True})
        for _ in range(10):
            blocks = [host.call('block', {'pos': p}) for p in PROBES]
            if all(block['id'] in ('create:belt', DRAIN, DEPOT) for block in blocks):
                break
            host.call('observe_ticks', {'positions': [list(map(int, state_after['position']))], 'ticks': 5})
        else:
            raise RuntimeError('Saved Item Drain fixture did not reload')
        release(host.command)
        phases = dict(warm=warm, cold=[dict(blocks=blocks)], resumed=advance(PHASES['resumed']))
        drops = host.command(f'execute if entity {DROPS} run say loose_item_drain')
        assert not any('loose_item_drain' in line for line in drops['messages']), drops
        return {name: [snapshot([b['nbt'] for b in row['blocks']], lava) for row in rows]
                for name, rows in phases.items()}
    finally:
        host.command(f'fill {REGION} minecraft:air')
        host.command(f'kill {DROPS}')
        host.command(f'forceload remove {LOAD}')
        host.call('tick', {'frozen': state['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session, lava=False):
    phases = {}
    n = len(PROBES)
    for label, names in [('before-restart', ('warm',)), ('after-restart', ('cold', 'resumed'))]:
        batch = Batch()
        batch.load((X, Y + 4, 983))
        if label == 'before-restart':
            setup(batch.command, batch.tick, lava)
        for name in names:
            if name == 'resumed':
                release(batch.command)
            for _ in range(PHASES[name] or 1):
                if PHASES[name]:
                    batch.tick()
                for pos in PROBES:
                    batch.data(pos)
        batch.command(f'execute if entity {DROPS} run say loose_item_drain', True)
        values = batch.run(session, label)
        offset = 0
        for name in names:
            end = offset + n * (PHASES[name] or 1)
            phases[name] = [snapshot(values[i:i+n], lava) for i in range(offset, end, n)]
            offset = end
        assert len(values) == offset + 1 and 'loose_item_drain' not in values[-1], values[-1]
    return phases


def visual_scenario(command, capture, settle):
    position = (X, Y, VIEW_Z)
    block = xyz(position)
    camera = (X + 1.7, Y, VIEW_Z + 2.25)
    target = (X + .5, Y + .7, VIEW_Z + .5)
    command(f'fill {REGION} minecraft:air')
    command(f'fill {X-3} {Y-1} {VIEW_Z-3} {X+3} {Y-1} {VIEW_Z+5} minecraft:smooth_stone')
    command(f'setblock {block} {DRAIN}')
    settle()
    captures = {}
    for name, fraction, ticks in [('dry', 0, 0), ('tilted', .375, 0), ('jet', .5, 10), ('tank', 0, 0)]:
        if name in ('tilted', 'jet'):
            command(f'data merge block {block} {{ProcessingTicks:{ticks},HeldItem:{{'
                    f'Item:{{id:"{FULL}",count:1}},Pos:{fraction}f,PrevPos:{fraction}f,'
                    'Offset:0f,PrevOffset:0f,InDirection:5,Angle:180}}')
        elif name == 'tank':
            command(f'data remove block {block} HeldItem')
            command(f'data merge block {block} {{ProcessingTicks:0,Tanks:[{{'
                    'TankContent:{Fluid:{id:"minecraft:water",amount:1000}},'
                    'Level:{Value:.6666667f,Target:.6666667f,Speed:.25f,Force:1b}}]}')
            settle()
        image = capture(name, camera, target)
        assert image.stat().st_size > 1024, image
        captures[name] = str(image)
    return captures


def java_visual(work):
    host = Original()
    assert json.loads((reference_java.BASE / 'manifest.json').read_text())['create_sha256'] == reference_java.CREATE_SHA256
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial

    def capture(name, camera, target):
        host.call('camera', {'position': camera, 'target': target, 'hide_gui': True})
        return Path(host.call('capture', {'name': f'{work.name}/{name}.png', 'frames': 20})['path'])

    def settle():
        before = host.call('state', {})['server']['game_time']
        host.call('tick', {'frozen': False})
        deadline = time.monotonic() + 15
        while host.call('state', {})['server']['game_time'] < before + 32:
            if time.monotonic() > deadline:
                raise RuntimeError('Item Drain render state did not settle')
            time.sleep(.1)
        host.call('tick', {'frozen': True})

    try:
        host.call('tick', {'frozen': True})
        host.command(f'forceload add {LOAD}')
        host.call('observe_ticks', {'positions': [(X, Y, VIEW_Z)], 'ticks': 24})
        return visual_scenario(host.command, capture, settle)
    finally:
        host.command(f'fill {REGION} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('camera', {'position': initial['position'], 'yaw': initial['yaw'],
                             'pitch': initial['pitch'], 'hide_gui': False})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_visual(session):
    def capture(name, camera, target):
        session.call('command', f'tp @s {xyz(camera)}')
        session.call('look-at', *target)
        session.call('wait', 6)
        path = session.scratch / (name + '.png')
        session.call('screenshot', path)
        return path

    def settle():
        session.call('command', 'tick unfreeze')
        session.call('wait', 40)
        session.call('command', 'tick freeze')

    with session:
        session.call('command', f'tp @s {X + 1.7} {Y} {VIEW_Z + 2.25}')
        wait_loaded(session.call, [(X, Y, VIEW_Z)])
        session.call('command', 'time set noon')
        session.call('command', 'tick freeze')
        session.call('key', 'f1', 'tap')
        return visual_scenario(lambda command: session.call('command', command), capture, settle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--lava', action='store_true', help='Use lava and test the rejection of mixed fluids')
    parser.add_argument('--screenshots', action='store_true', help='Capture four poses instead of running the timing fixture')
    for flag in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.screenshots:
        if args.lava:
            parser.error('--lava is only available for the gameplay fixture')
        if args.java:
            work = Path(tempfile.mkdtemp(prefix='drain-visual-java-', dir=ROOT / '.local'))
            captures = java_visual(work)
        else:
            if not all((args.game, args.resources, args.ctl, args.create_jar)):
                parser.error('Horizon captures require --game, --resources, --ctl and --create-jar')
            session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                         size=(905, 1045), name='drain-visual-native', world='CreateItemDrainVisual')
            work = session.scratch
            try:
                captures = native_visual(session)
            finally:
                for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                    shutil.rmtree(folder, ignore_errors=True)
        path = work / 'captures.json'
        path.write_text(json.dumps(captures, indent=2) + '\n')
        print(path)
        return
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='item-drain-java-', dir=ROOT / '.local'))
        phases = java_run(work, args.lava)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon runs require --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        assert reference.get('lava', False) == args.lava
        session = NativeCheckSession(args.game, args.resources, args.ctl, None, graphics=False,
                                     name='item-drain-native', world='CreateItemDrain')
        work = session.scratch
        try:
            phases = native_run(session, args.lava)
        finally:
            session.control_temp.cleanup()
            for path in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(path, ignore_errors=True)
    (work / 'observed.json').write_text(json.dumps(phases, indent=2) + '\n')
    verify(phases, args.lava)
    if not args.java:
        for name, expected in reference['phases'].items():
            for tick, (got, wanted) in enumerate(zip(phases[name], expected, strict=True), 1):
                assert got == wanted, (name, tick, got, wanted)
    path = work / 'result.json'
    path.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], lava=args.lava, phases=phases), indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
