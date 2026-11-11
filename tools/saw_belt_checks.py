#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare upward Saw output to a bare belt in Java Create and Horizon."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession
from reference_java import BASE, CREATE_SHA256


Y = 168
CENTER = (1858, 170, 732)
REGION = '1853 167 720 1865 175 747'
LOAD = '1853 720 1865 747'
DROPS = '@e[type=minecraft:item,x=1853,y=167,z=720,dx=12,dy=8,dz=27]'
BUCKET = 'minecraft:water_bucket'
LANES = dict(inline=724, perpendicular=730, reverse=735, stopped=739, occupied=744)
PHASES = dict(travel=18, blind=0, parked=4, reloaded=2, resumed=4)


def positions(name):
    z = LANES[name]
    saw = (1855, Y, z)
    controller = (1856, Y, z - int(name == 'perpendicular'))
    motor = (1857, Y, z - 1) if name == 'perpendicular' else (1856, Y, z - 1)
    return saw, controller, motor


def put(command, pos, state):
    command(f'setblock {xyz(pos)} {state}')


def power(command, name):
    _, _, motor = positions(name)
    facing, speed = dict(perpendicular=('west', -32), reverse=('south', 32),
                         occupied=('south', -1)).get(name, ('south', -32))
    put(command, motor, f'create:creative_motor[facing={facing}]{{ScrollValue:{speed}}}')


def prepare(command):
    command(f'fill {REGION} minecraft:air')
    command('fill 1853 167 720 1865 167 747 minecraft:smooth_stone')
    command(f'kill {DROPS}')
    for name in LANES:
        saw, (x, y, z), _ = positions(name)
        sideways = name == 'perpendicular'
        facing = 'south' if sideways else 'east'
        for index, part in enumerate(('start', 'middle', 'middle', 'middle', 'end')):
            put(command, (x + index * (not sideways), y, z + index * sideways),
                f'create:belt[facing={facing},slope=horizontal,part={part}]')
        put(command, saw, 'create:mechanical_saw[facing=up,axis_along_first=false]')
        put(command, (saw[0], saw[1], saw[2] - 1),
            'create:creative_motor[facing=south]{ScrollValue:128}')
        if name != 'stopped':
            power(command, name)


def phase(command, name):
    if name == 'travel':
        command(f'data merge block {xyz(positions("occupied")[1])} '
                '{Inventory:{PositiveOrder:1b,Items:[{Item:{id:"minecraft:stone",count:1},'
                'Pos:0.4f,PrevPos:0.4f,Offset:0f,PrevOffset:0f,InSegment:0,InDirection:5,Angle:180}]}}')
        for marker, lane in enumerate(LANES, 1):
            (x, y, z), _, _ = positions(lane)
            command(f'summon minecraft:item {x + .5} {y + 1.3} {z + .5} '
                    f'{{PickupDelay:32767s,Item:{{id:"{BUCKET}",count:1,'
                    f'components:{{"minecraft:custom_data":{{saw_belt_marker:{marker}}}}}}}}}')
    elif name == 'parked':
        for lane in ('inline', 'perpendicular', 'occupied'):
            put(command, positions(lane)[2], 'minecraft:air')
    elif name == 'resumed':
        power(command, 'stopped')


def probes(name):
    if name == 'blind':
        return [('perpendicular', 'belt', positions('perpendicular')[1])]
    # During all 18 travel ticks the perpendicular belt controller is never
    # serialized by the observer. Java's BeltInventory.write flushes queues.
    return [(lane, kind, pos) for lane in LANES
            for kind, pos in zip(('saw', 'belt'), positions(lane)[:2], strict=True)
            if name != 'travel' or (lane, kind) != ('perpendicular', 'belt')]


def item(raw):
    if raw == '[]':
        return None
    nbt = field(raw, 'Item') if 'Item:' in raw else raw
    return dict(id=nbt.split('id:', 1)[1].lstrip().split('"')[1],
                count=int(number({'nbt': nbt}, 'count')),
                marker=int(number({'nbt': nbt}, 'saw_belt_marker', 0)))


def sample(probe, raw):
    result = {}
    for (name, kind, _), nbt in zip(probe, raw, strict=True):
        assert f'create:{kind}' in nbt, nbt
        inventory = field(nbt, 'Inventory') if 'Inventory:' in nbt else '{Items:[]}'
        entries = field(inventory, 'Items') if 'Items:' in inventory else '[]'
        stack = item(entries)
        if kind == 'saw':
            pose = [number({'nbt': inventory}, key, default) for key, default in
                    [('ProcessingTime', -1), ('RecipeTime', 0), ('AppliedRecipe', 0)]]
        elif stack:
            pose = [number({'nbt': entries}, key) for key in
                    ('Pos', 'PrevPos', 'Offset', 'PrevOffset', 'InSegment', 'InDirection', 'Angle')]
        else:
            pose = []
        result[name + '/' + kind] = dict(stack=stack, pose=pose, rpm=number({'nbt': nbt}, 'Speed', 0))
    return result


def verify(phases):
    travel = phases['travel']
    settled = travel[-1]
    inline = next(i for i, row in enumerate(travel, 1) if row['inline/belt']['stack'])
    assert inline == 9, travel
    assert travel[inline - 1]['inline/belt']['pose'][4:] == [0, 5, 180], travel[inline - 1]
    assert settled['inline/belt']['stack'] == dict(id=BUCKET, count=1, marker=1), settled
    assert settled['inline/saw']['stack'] is None and settled['perpendicular/saw']['stack'] is None, settled
    blind = phases['blind'][0]['perpendicular/belt']
    assert blind['stack'] == dict(id=BUCKET, count=1, marker=2), blind
    assert blind['pose'][4:] == [1, 5, 180] and -0.675 < blind['pose'][2] < 0.0, blind
    for marker, name in enumerate(('reverse', 'stopped', 'occupied'), 3):
        assert settled[name + '/saw']['stack'] == dict(id=BUCKET, count=1, marker=marker), settled
        assert settled[name + '/saw']['pose'] == [0, 20, 1], settled
    assert settled['reverse/belt']['stack'] is None and settled['stopped/belt']['stack'] is None, settled
    assert settled['occupied/belt']['stack'] == dict(id='minecraft:stone', count=1, marker=0), settled
    assert all(row == phases['parked'][-1] for row in phases['reloaded']), phases
    resumed = phases['resumed'][-1]
    assert resumed['stopped/saw']['stack'] is None, resumed
    assert resumed['stopped/belt']['stack'] == dict(id=BUCKET, count=1, marker=4), resumed


def compare(native, java):
    for name, expected in java.items():
        for tick, (actual, reference) in enumerate(zip(native[name], expected, strict=True), 1):
            assert actual.keys() == reference.keys(), (name, tick)
            for key, got in actual.items():
                want = reference[key]
                assert got['stack'] == want['stack'] and got['rpm'] == want['rpm'], (name, tick, key, got, want)
                assert all(abs(x - y) < 1e-5 for x, y in zip(got['pose'], want['pose'], strict=True)), (
                    name, tick, key, got, want)


def java_run(work):
    host = Original()
    assert json.loads((BASE / 'manifest.json').read_text())['create_sha256'] == CREATE_SHA256
    state = host.call('state', {})
    assert state['ready'] and state['data_version'] == 3955, state
    host.call('tick', {'frozen': True})
    phases = {}
    try:
        host.command(f'forceload add {LOAD}')
        host.call('observe_ticks', {'positions': [list(map(int, state['position']))], 'ticks': 40})
        prepare(host.command)
        host.command(f'tp @s {CENTER[0]}.5 {CENTER[1]} {CENTER[2]}.5')
        host.call('observe_ticks', {'positions': [positions(lane)[0] for lane in LANES], 'ticks': 12})
        for name, ticks in PHASES.items():
            phase(host.command, name)
            probe = probes(name)
            points = [row[2] for row in probe]
            if ticks:
                observed = host.call('observe_ticks', {'positions': points, 'ticks': ticks})['samples']
            else:
                observed = [{'blocks': [host.call('block', {'pos': pos}) for pos in points]}]
            phases[name] = [sample(probe, [block['nbt'] for block in row['blocks']]) for row in observed]
            reply = host.command(f'execute if entity {DROPS} run say loose_saw_belt')
            assert not any('loose_saw_belt' in message for message in reply['messages']), reply
        return phases
    finally:
        host.command(f'fill {REGION} minecraft:air')
        host.command(f'kill {DROPS}')
        host.command(f'forceload remove {LOAD}')
        host.command(f'tp @s {xyz(state["position"])} {state["yaw"]} {state["pitch"]}')
        host.call('tick', {'frozen': state['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    phases = {}
    for part, names in [('before-restart', ('travel', 'blind', 'parked')),
                        ('after-restart', ('reloaded', 'resumed'))]:
        batch = Batch()
        batch.load(CENTER)
        for lane in LANES:
            for pos in positions(lane)[:2]:
                batch.command(f'execute if loaded {xyz(pos)} run say loaded_saw_belt', True)
        if part == 'before-restart':
            prepare(batch.command)
            batch.tick(12)
        for name in names:
            phase(batch.command, name)
            for _ in range(PHASES[name] or 1):
                if PHASES[name]:
                    batch.tick()
                for _, _, pos in probes(name):
                    batch.data(pos)
            batch.command(f'execute if entity {DROPS} run say loose_saw_belt', True)
        values = batch.run(session, part)
        offset = len(LANES) * 2
        assert all('loaded_saw_belt' in line for line in values[:offset]), values[:offset]
        for name in names:
            probe = probes(name)
            end = offset + len(probe) * (PHASES[name] or 1)
            phases[name] = [sample(probe, values[i:i + len(probe)]) for i in range(offset, end, len(probe))]
            assert 'loose_saw_belt' not in values[end], values[end]
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
        work = Path(tempfile.mkdtemp(prefix='saw-belt-java-', dir=ROOT / '.local'))
        phases = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon runs require --game, --resources, --ctl and --reference')
        expected = json.loads(args.reference.read_text())
        assert expected['passed'] and expected['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='saw-belt-native', graphics=False, world='CreateSawBelt')
        work = session.scratch
        try:
            phases = native_run(session)
        finally:
            session.control_temp.cleanup()
            for path in (session.resources, work / '.horizon-cache'):
                shutil.rmtree(path, ignore_errors=True)
        (work / 'observed.json').write_text(json.dumps(phases, indent=2) + '\n')
        compare(phases, expected['phases'])
    verify(phases)
    path = work / 'result.json'
    path.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], phases=phases), indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
