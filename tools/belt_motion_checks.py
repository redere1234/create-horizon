#!/usr/bin/env python3
"""Compare belt item steps and capture matched layouts in Java and Horizon."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import tempfile

from burner_heat_java_checks import number
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded

ORIGIN = (768, 85, 40)
LENGTH = 6
WORLD = 'CreateBeltMotion'
AXES = [('east', (1, 0, 0), 'south', (0, 0, -1)),
        ('south', (0, 0, 1), 'east', (-1, 0, 0))]
SLOPES = [('horizontal', 0), ('upward', 1), ('downward', -1)]
RPM = 32


def add(a, b, scale=1):
    return tuple(x + scale * y for x, y in zip(a, b, strict=True))


def item_fields(block):
    fields = {name: number(block, name) for name in ('Pos', 'PrevPos', 'Offset', 'PrevOffset')}
    assert 'minecraft:copper_ingot' in block['nbt'], block
    return fields


def scenario(host, session, work):
    cmd = host.command
    cmd('forceload add 752 16 815 79')
    cmd('fill 759 79 33 805 93 61 minecraft:air')
    cmd('fill 759 79 33 805 93 61 minecraft:air')
    cmd('time set noon')
    cmd('weather clear')
    cmd('fill 759 78 33 805 78 61 minecraft:smooth_stone')

    def step(ticks, origin):
        if session:
            session.call('wait', ticks)
        else:
            host.call('observe_ticks', {'ticks': ticks, 'positions': [origin]})

    def put(pos, state):
        cmd(f'setblock {xyz(pos)} {state}')

    def build_belt(origin, end, facing, axis):
        cmd('gamemode creative')
        cmd('item replace entity @s weapon.mainhand with create:belt_connector')
        for endpoint in (origin, end):
            put(endpoint, f'create:shaft[axis={axis}]')
        step(8, origin)
        pads = []
        for endpoint in (origin, end):
            approach = (0, 0, 3) if facing == 'east' else (3, 0, 0)
            stand = add(endpoint, approach)
            pad = add(stand, (0, -1, 0))
            pads.append(pad)
            put(pad, 'minecraft:smooth_stone')
            camera_pos = add(stand, (0.5, 0, 0.5))
            target = add(endpoint, (0.5, 0.5, 0.5))
            cmd('tp @s ' + xyz(camera_pos))
            if session:
                session.call('look-at', *target)
                session.call('wait', 4)
                session.call('mouse', 'right', 'down')
                session.call('wait', 2)
                session.call('mouse', 'right', 'up')
            else:
                host.call('camera', {'position': camera_pos, 'target': target, 'hide_gui': True})
                host.call('capture', {'name': 'belt-motion-aim.png', 'frames': 10})
                hit = host.call('state', {})['hit']
                assert hit['pos'] == list(endpoint), hit
                host.call('input', {'key': 'use'})
                host.call('capture', {'name': 'belt-motion-click.png', 'frames': 14})
                host.call('input', {'key': 'use', 'down': False})
            step(10, origin)
        cmd('gamemode spectator')
        for pad in pads:
            put(pad, 'minecraft:air')
        assert host.snapshot([origin, end], 4)[-1]['block'] == 'create:belt'

    def seed(origin, offset):
        cmd('data merge block ' + xyz(origin) + ' {Inventory:{Items:[{'
            'Item:{id:"minecraft:copper_ingot",count:4},'
            f'Pos:{offset}f,PrevPos:{offset}f,Offset:0.125f,PrevOffset:0.125f,'
            'InSegment:2,InDirection:1,Angle:315}],PositiveOrder:1b}}')

    def camera(origin, facing, elevation, phase):
        camera_pos = (773.7, 90, 47.7) if facing == 'south' else (775.7, 90, 45.7)
        target = (768.5, 86 + elevation * 2.5, 43) if facing == 'south' else (771, 86 + elevation * 2.5, 40.5)
        delta = tuple(a - b for a, b in zip(origin, ORIGIN, strict=True))
        camera_pos, target = add(camera_pos, delta), add(target, delta)
        name = f'{facing}-{elevation}-{phase}.png'
        if session:
            cmd('tp @s ' + xyz(camera_pos))
            session.call('look-at', *target)
            session.call('wait', 3)
            path = work / name
            session.call('screenshot', path)
        else:
            host.call('camera', {'position': camera_pos, 'target': target, 'hide_gui': True})
            path = Path(host.call('capture', {'name': work.name + '-' + name, 'frames': 8})['path'])
        assert path.stat().st_size > 1024
        return str(path)

    for row_index, (facing, horizontal, motor_face, motor_offset) in enumerate(AXES):
        for lane, (slope, elevation) in enumerate(SLOPES):
            origin = add(ORIGIN, (lane * 13, 0, row_index * 13))
            cmd('tp @s ' + xyz(add(origin, (5.5, 5, 5.5))))
            if session:
                wait_loaded(session.call, [origin, add(origin, (6, 0, 6))])
            clutch = add(origin, motor_offset)
            gearshift = add(origin, motor_offset, 2)
            motor = add(origin, motor_offset, 3)
            control = [add(pos, (0, 1, 0)) for pos in (clutch, gearshift)]
            vector = (horizontal[0], elevation, horizontal[2])
            forward = RPM if facing == 'south' else -RPM
            shaft_axis = 'x' if facing == 'south' else 'z'
            build_belt(origin, add(origin, vector, LENGTH - 1), facing, shaft_axis)
            put(clutch, f'create:clutch[axis={shaft_axis}]')
            put(gearshift, f'create:gearshift[axis={shaft_axis}]')
            put(motor, f'create:creative_motor[facing={motor_face}]{{ScrollValue:{forward}}}')
            step(16, origin)
            row = {'facing': facing, 'slope': slope, 'origin': origin, 'phases': {}}
            for label, rpm in [('forward', forward), ('stop', 0), ('reverse', -forward)]:
                if label == 'stop':
                    put(control[0], 'minecraft:redstone_block')
                elif label == 'reverse':
                    put(control[1], 'minecraft:redstone_block')
                    put(control[0], 'minecraft:air')
                step(10, origin)
                seed(origin, 2.5)
                block = host.snapshot([origin], 8)[0]
                assert block['block'] == 'create:belt', (label, block)
                assert (block['properties']['facing'], block['properties']['slope']) == (facing, slope), block
                actual = block['speed']
                fields = item_fields(block)
                step_rpm = -actual if facing == 'east' else actual
                assert math.isclose(fields['Pos'] - fields['PrevPos'], step_rpm / 480, abs_tol=2e-6), (row, fields)
                if not actual:
                    assert fields['Pos'] == 2.5 and fields['Offset'] == 0.125
                image = camera(origin, facing, elevation, label)
                phase = dict(rpm=actual, expected_rpm=rpm, fields=fields, image=image)
                if actual != rpm:
                    phase['source_observation'] = block['nbt']
                row['phases'][label] = phase
            yield row

    if session:
        # Leave each lane stocked and stopped. The closer lever releases its
        # Clutch and the farther lever reverses its Gearshift.
        for row_index, (_, _, _, motor_offset) in enumerate(AXES):
            for lane in range(len(SLOPES)):
                origin = add(ORIGIN, (lane * 13, 0, row_index * 13))
                for index in (1, 2):
                    control = add(add(origin, motor_offset, index), (0, 1, 0))
                    powered = 'true' if index == 1 else 'false'
                    put(control, f'minecraft:lever[face=floor,facing=north,powered={powered}]')
                step(8, origin)
                seed(origin, 2.5)
        stopped = host.snapshot([ORIGIN], 8)[0]
        assert stopped['speed'] == 0 and item_fields(stopped)['Pos'] == 2.5
        cmd('fill 768 84 43 776 84 49 minecraft:smooth_stone')
        put((772, 85, 46), 'create:depot')
        put((772, 87, 46), 'create:mechanical_press[facing=east]')
        put((771, 87, 46), 'create:clutch[axis=x]')
        put((770, 87, 46), 'create:creative_motor[facing=east]{ScrollValue:128}')
        put((771, 88, 46), 'minecraft:lever[face=floor,facing=north,powered=true]')
        cmd('gamemode creative')
        cmd('tp @s 772.5 85 43.5')
        cmd('spawnpoint @s 772 85 43')
        cmd('give @s minecraft:copper_ingot 8')
        session.call('wait', 8)
        session.call('select', 'minecraft:copper_ingot')
        session.call('look-at', 772.5, 85.75, 46.5)
        session.call('key', 'f1', 'tap')
        cmd('save-all flush')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'build-result', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    session = None
    if args.java:
        host = Original()
        assert host.call('state', {})['data_version'] == 3955
        host.call('tick', {'frozen': True})
        work = Path(tempfile.mkdtemp(prefix='belt-motion-java-', dir=ROOT / '.local'))
    else:
        if not all((args.game, args.build_result, args.resources, args.ctl)):
            parser.error('the Horizon run needs game, build-result, resources and ctl')
        build = json.loads(args.build_result.read_text())
        assert build['passed'] and Path(build['game']).resolve() == args.game.resolve()
        with args.game.open('rb') as executable:
            assert hashlib.file_digest(executable, 'sha256').hexdigest() == build['game_sha256']
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='belt-motion-native', world=WORLD)
        work, host = session.scratch, Native(session)
    print(json.dumps({'work': str(work)}), flush=True)
    result = {'passed': False, 'create': PINS['create_revision'], 'cases': []}
    try:
        if session:
            session.start()
        host.command('gamemode spectator')
        host.command('tp @s 773.7 90 47.7')
        if session:
            wait_loaded(session.call, [(761, 78, 33), (779, 92, 52)])
            session.call('key', 'f1', 'tap')
            result['game_sha256'] = build['game_sha256']
        result['cases'].extend(scenario(host, session, work))
        if session:
            assert all(phase['rpm'] == phase['expected_rpm'] for row in result['cases']
                       for phase in row['phases'].values())
        if args.reference:
            reference = json.loads(args.reference.read_text())
            assert reference['passed'] and reference['create'] == result['create']
            matched = 0
            differences = []
            for row, original in zip(result['cases'], reference['cases'], strict=True):
                assert (row['facing'], row['slope'], list(row['origin'])) == (
                    original['facing'], original['slope'], original['origin'])
                for label, phase in row['phases'].items():
                    reference_phase = original['phases'][label]
                    if phase['rpm'] != reference_phase['rpm']:
                        differences.append(dict(facing=row['facing'], slope=row['slope'],
                                                phase=label, horizon=phase['rpm'],
                                                java=reference_phase['rpm']))
                        continue
                    fields, want = phase['fields'], reference_phase['fields']
                    assert math.isclose(fields['Pos'] - fields['PrevPos'],
                                        want['Pos'] - want['PrevPos'], abs_tol=2e-6)
                    assert all(fields[key] == want[key] for key in ('Offset', 'PrevOffset'))
                    matched += 1
            result['matching_motion_phases'] = matched
            result['source_speed_differences'] = differences
        result['passed'] = True
    finally:
        (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        if session:
            session.stop()
        else:
            (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
        print(json.dumps({'passed': result['passed'], 'cases': len(result['cases']),
                          'result': str(work / 'result.json')}), flush=True)


if __name__ == '__main__':
    main()
