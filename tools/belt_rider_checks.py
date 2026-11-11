#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare the local player's grounded horizontal Belt displacement with Java."""

import argparse
import json
import math
from pathlib import Path
import re
import shutil
import tempfile
import time

from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded


X, Y, Z = 2356, 116, 1546
ROOT_X, ROOT_Z = (X, Y, Z), (X + 17, Y, Z - 3)
MOTOR_X, MOTOR_Z = (X, Y, Z - 1), (X + 16, Y, Z - 3)
AREA = '2353 115 1540 2375 121 1561'
FORCE = '2352 1536 2383 1567'
HEIGHT = Y + 13 / 16
AIR = 'minecraft:air'
EPSILON = 2e-5


def setblock(command, pos, state):
    command(f'setblock {xyz(pos)} {state}')


def setup(command, cased):
    command(f'fill {AREA} {AIR}')
    command('fill 2353 115 1540 2375 115 1561 minecraft:stone')
    for origin, axis, facing in ((ROOT_X, 0, 'east'), (ROOT_Z, 2, 'south')):
        # Reverse travel crosses a bare segment on the cased Andesite
        # chain. The Brass chain instead has a bare controller.
        material, bare_index = ('ANDESITE', 12) if axis == 0 else ('BRASS', 0)
        for index in range(14):
            part = 'start' if index == 0 else 'end' if index == 13 else 'middle'
            pos = tuple(value + (index if i == axis else 0) for i, value in enumerate(origin))
            casing = ',casing=true' if cased and index != bare_index else ''
            nbt = f'{{Casing:"{material}"}}' if casing else ''
            setblock(command, pos, f'create:belt[facing={facing},slope=horizontal,part={part}{casing}]{nbt}')
    command('gamemode survival')


def verify_casing(read_block):
    fixtures = ((ROOT_X, 'ANDESITE'), ((X + 7, Y, Z), 'ANDESITE'), ((X + 12, Y, Z), 'NONE'),
                (ROOT_Z, 'NONE'), ((ROOT_Z[0], Y, ROOT_Z[2] + 6), 'BRASS'))
    for pos, material in fixtures:
        state, nbt = read_block(pos)
        assert state['casing'] == str(material != 'NONE').lower(), (pos, state)
        assert re.search(r'\bCasing:\s*"' + material + '"', nbt), (pos, nbt)


def wait_for(read, predicate, limit=12):
    deadline = time.monotonic() + limit
    while True:
        row = read()
        if predicate(row):
            return row
        if time.monotonic() >= deadline:
            raise AssertionError(('Player did not reach expected state', row))
        time.sleep(.014)


def near(a, b):
    return abs(a - b) <= EPSILON


def height(row):
    assert near(row['position'][1], HEIGHT) and row.get('grounded', True), row


def server_position(command, client):
    reply = command('data get entity @s Pos')
    text = ' '.join(reply.get('messages', reply.get('chat', [])))
    coords = re.search(r'\[([-+0-9.eEdD, ]+)\]\s*$', text)
    assert coords, text
    position = [float(value.strip().rstrip('dD')) for value in coords[1].split(',')]
    assert all(near(a, b) for a, b in zip(position, client['position'], strict=True)), (position, client)
    return position


def verify_motion(rows, axis, signed_rpm, centered):
    speed = signed_rpm / 480
    cross = 2 if axis == 0 else 0
    center = math.floor(rows[0]['position'][cross]) + .5
    seen = []
    for first, second in zip(rows, rows[1:]):
        height(first)
        height(second)
        a, b = first['position'], second['position']
        ticks = round((b[axis] - a[axis]) / speed)
        assert 1 <= ticks <= 4 and near(b[axis] - a[axis], ticks * speed), (axis, speed, first, second)
        if centered:
            expected = center + (a[cross] - center) * (1 - min(abs(speed), .1) * 4) ** ticks
            assert near(b[cross], expected), (expected, first, second)
        else:
            assert near(b[cross], a[cross]), (first, second)
        seen.append((b[axis] - a[axis]) / ticks)
    return sum(seen) / len(seen)


def exercise(command, read, read_block, aim, key, cased):
    setup(command, cased)
    trace = {}

    def power(pos, facing, rpm):
        setblock(command, pos, f'create:creative_motor[facing={facing}]{{ScrollValue:{rpm}}}' if rpm else AIR)

    def stand(x, z, yaw=90):
        aim((x, HEIGHT + .25, z), yaw)
        return wait_for(read, lambda row: near(row['position'][0], x) and near(row['position'][2], z)
                        and near(row['position'][1], HEIGHT) and row.get('grounded', True))

    def moving(axis, first, samples=7):
        rows = [first]
        for _ in range(samples):
            rows.append(wait_for(read, lambda row: abs(row['position'][axis] - rows[-1]['position'][axis]) > EPSILON))
        return rows

    def settled(last=None):
        same_since = None
        def stable(row):
            nonlocal last, same_since
            if last is None or any(not near(a, b) for a, b in zip(row['position'], last['position'])):
                same_since = row['time']
            elif same_since is None:
                same_since = last['time']
            last = row
            return row['time'] - same_since >= 5
        end = wait_for(read, stable)
        height(end)
        return end

    east = stand(X + 7.5, Z + .72)
    power(MOTOR_X, 'south', 32)
    trace['forward'] = moving(0, east)
    forward = verify_motion(trace['forward'], 0, -32, True)
    if cased:
        verify_casing(read_block)
    key('shift', True)
    trace['crouch'] = settled(trace['forward'][-1])
    key('shift', False)
    wait_for(read, lambda row: row['position'][0] < trace['crouch']['position'][0] - .04)
    power(MOTOR_X, 'south', 0)
    trace['stopped'] = settled()
    trace['stopped']['server_position'] = server_position(command, trace['stopped'])

    reverse = stand(X + 11.5, Z + .5)
    power(MOTOR_X, 'south', -64)
    trace['reverse'] = moving(0, reverse)
    backwards = verify_motion(trace['reverse'], 0, 64, False)
    assert (math.floor(trace['reverse'][-1]['position'][0]) >> 4) == (math.floor(reverse['position'][0]) >> 4) + 1
    power(MOTOR_X, 'south', 0)
    settled()

    south = stand(ROOT_Z[0] + .5, ROOT_Z[2] + 6.5, 0)
    power(MOTOR_Z, 'east', 32)
    trace['north_south'] = moving(2, south)
    longitudinal = verify_motion(trace['north_south'], 2, 32, False)
    power(MOTOR_Z, 'east', 0)
    settled()

    walking = stand(X + 8.5, Z + .72)
    key('forward', True)
    walking = moving(0, walking, 2)[-1]
    power(MOTOR_X, 'south', 32)
    trace['walking'] = moving(0, walking, 8)
    assert all(near(row['position'][2], Z + .72) for row in trace['walking']), trace['walking']
    assert trace['walking'][-1]['position'][0] < walking['position'][0] - .5
    key('forward', False)
    power(MOTOR_X, 'south', 0)
    settled()

    command(f'fill {X + 5} {Y + 1} {Z - 1} {X + 5} {Y + 3} {Z + 1} minecraft:stone')
    start = stand(X + 6.75, Z + .5)
    power(MOTOR_X, 'south', 32)
    trace['wall'] = settled(start)
    wall = trace['wall']['position'][0]
    assert near(wall, X + 6.3), trace['wall']
    trace['wall']['server_position'] = server_position(command, trace['wall'])
    return dict(forward=forward, reverse=backwards, north_south=longitudinal,
                wall_gap=wall - X - 6, trace=trace)


def java(work, cased):
    host = Original()
    initial = host.call('state', {})
    if initial.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})

    def read():
        state = host.call('state', {})
        return dict(position=state['position'], time=state['server']['game_time'])

    def read_block(pos):
        block = host.call('block', {'pos': pos})
        return block['properties'], block['nbt']

    def aim(feet, yaw):
        host.call('camera', {'position': feet, 'yaw': yaw, 'pitch': 0})

    def key(name, down):
        host.call('input', {'key': name, 'down': down})

    try:
        host.command('gamemode creative')
        host.command('tp @s ' + xyz((X + 7.5, Y + 4, Z + .5)))
        host.command('forceload add ' + FORCE)
        host.snapshot([ROOT_X, ROOT_Z], 18)
        host.command('tick rate 8')
        host.call('tick', {'frozen': False})
        return exercise(host.command, read, read_block, aim, key, cased)
    finally:
        for name in ('shift', 'forward'):
            key(name, False)
        host.call('tick', {'frozen': True})
        host.command(f'fill {AREA} {AIR}')
        host.command('forceload remove ' + FORCE)
        host.command('gamemode creative')
        host.command('tick rate 20')
        host.call('camera', {name: initial[name] for name in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session, cased):
    call = session.call

    def command(text):
        return call('command', text)

    def read():
        state = call('state')
        player = state['player']
        return dict(position=player['position'], time=state['ticks'], grounded=player['on_ground'])

    def read_block(pos):
        state = dict(re.findall(r'(\w+)=(\w+)', call('block', *pos)['state']))
        return state, ' '.join(command(f'data get block {xyz(pos)}')['chat'])

    def aim(feet, yaw):
        command('tp @s ' + xyz(feet) + f' {yaw} 0')

    def key(name, down):
        call('key', 'w' if name == 'forward' else name, 'down' if down else 'up')

    with session:
        command('tp @s ' + xyz((X + 7.5, Y + 4, Z + .5)))
        wait_loaded(call, [ROOT_X, ROOT_Z])
        command('tick rate 8')
        command('tick unfreeze')
        return exercise(command, read, read_block, aim, key, cased)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--cased', action='store_true', help='exercise Andesite, Brass and bare segments together')
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    report = dict(passed=False, create=PINS['create_revision'], cased=args.cased)
    session = None
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='belt-rider-java-', dir=ROOT / '.local'))
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl and --reference')
        source = json.loads(args.reference.read_text())
        assert source['passed'] and source['create'] == report['create']
        assert source.get('cased', False) == args.cased
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     world='BeltRider', name='belt-rider-native')
        work = session.scratch
    try:
        report['cases'] = native(session, args.cased) if session else java(work, args.cased)
        if session:
            for key in ('forward', 'reverse', 'north_south', 'wall_gap'):
                assert near(report['cases'][key], source['cases'][key]), (key, report, source)
        report['passed'] = True
    finally:
        if session:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        output = work / 'result.json'
        output.write_text(json.dumps(report, indent=2) + '\n')
        print(output, flush=True)


if __name__ == '__main__':
    main()
