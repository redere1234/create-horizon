#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Observe the launch and control cases for a moving Mechanical Plough."""

import argparse
import json
import math
from pathlib import Path
import re
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession

PIVOT = (1448, 148, 150)
MOTOR = (1448, 147, 150)
SWEPT = (1451, 149, 149)
TAG = 'create_plough_throw_probe'
PIG = f'@e[type=minecraft:pig,tag={TAG},limit=1]'
MOTION = f'data get entity {PIG} Motion'
POSITION = f'data get entity {PIG} Pos'
TICKS = 10
CASES = {
    # The pig's center is outside the visited cell. Its left edge overlaps it.
    'overlap': ((1452.15, 149.72, 149.5), 32, False),
    'outside': ((1452.60, 149.72, 149.5), 32, False),
    'conductor': ((1452.15, 149.72, 149.5), 32, True),
    'backwards': ((1452.15, 149.72, 151.5), -32, False),
}


def put(command, pos, state):
    command(f'setblock {xyz(pos)} {state}')


def motor(rpm):
    return f'create:creative_motor[facing=up]{{ScrollValue:{rpm}}}'


def setup(command, position, conductor):
    command(f'kill {PIG}')
    command('fill 1444 147 145 1454 153 155 minecraft:air')
    put(command, PIVOT, 'create:mechanical_bearing[facing=up]')
    for x in range(1448, 1451):
        put(command, (x, 149, 150), 'minecraft:slime_block')
    put(command, (1451, 149, 150),
        'create:mechanical_plough[facing=north,waterlogged=false]')
    if conductor:
        put(command, SWEPT, 'minecraft:stone')
    nbt = f'{{NoAI:1b,NoGravity:1b,PersistenceRequired:1b,Tags:["{TAG}"]}}'
    command(f'summon minecraft:pig {xyz(position)} {nbt}')


def vector(message):
    match = re.search(r'\[([^\[\]]+)\]\s*$', message)
    assert match, message
    result = tuple(float(word.strip().rstrip('dDfF')) for word in match[1].split(','))
    assert len(result) == 3, message
    return result


def verify(cases):
    rows = cases['overlap']
    assert math.hypot(rows[0]['motion'][0], rows[0]['motion'][2]) < 1e-6, rows[0]
    launch = next((row for row in rows[1:] if math.hypot(row['motion'][0], row['motion'][2]) > 0.1), None)
    assert launch, rows
    x, y, z = launch['motion']
    assert x < -0.1 and y > 0.05 and z < -0.2, launch
    for case in ('outside', 'conductor', 'backwards'):
        assert all(math.hypot(*row['motion']) < 1e-6 for row in cases[case]), (case, cases[case])
    return launch


def native(args):
    session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                 name='plough-throw-native', graphics=False, world='CreatePloughThrow')
    try:
        cases = {}
        for case, (position, rpm, conductor) in CASES.items():
            batch = Batch()
            batch.load((PIVOT[0], PIVOT[1] + 8, PIVOT[2]))
            setup(batch.command, position, conductor)
            for tick in range(TICKS + 1):
                batch.command(MOTION, True)
                batch.command(POSITION, True)
                batch.data(PIVOT)
                if tick == 0:
                    batch.put(MOTOR, motor(rpm))
                batch.tick()
            batch.put(MOTOR, 'minecraft:air')
            batch.command(f'kill {PIG}')
            batch.tick(25)
            rows = batch.run(session, case)
            cases[case] = [dict(tick=tick, motion=vector(rows[3 * tick]),
                                pos=vector(rows[3 * tick + 1]),
                                angle=number({'nbt': rows[3 * tick + 2]}, 'Angle', 0))
                           for tick in range(TICKS + 1)]
        return session.scratch, cases
    finally:
        session.control_temp.cleanup()


def original():
    host = Original()
    scratch = Path(tempfile.mkdtemp(prefix='plough-throw-java-', dir=ROOT / '.local'))
    cases = {}
    frozen = False
    try:
        assert host.call('state', {})['data_version'] == 3955
        host.call('tick', {'frozen': True})
        frozen = True
        host.command('gamemode creative')
        host.command(f'tp @s {PIVOT[0]}.5 {PIVOT[1] + 8} {PIVOT[2]}.5')
        host.command('forceload add 1440 144 1455 159')
        host.snapshot([PIVOT], 22)
        for case, (position, rpm, conductor) in CASES.items():
            setup(host.command, position, conductor)
            rows = cases[case] = []
            angle = 0.0
            for tick in range(TICKS + 1):
                rows.append(dict(tick=tick, angle=angle,
                                 motion=vector(' '.join(host.command(MOTION)['messages'])),
                                 pos=vector(' '.join(host.command(POSITION)['messages']))))
                if tick == 0:
                    put(host.command, MOTOR, motor(rpm))
                angle = number(host.snapshot([PIVOT], 1)[0], 'Angle', 0)
            put(host.command, MOTOR, 'minecraft:air')
            host.command(f'kill {PIG}')
            host.snapshot([PIVOT], 25)
        return scratch, cases
    finally:
        if frozen:
            host.command(f'kill {PIG}')
            put(host.command, MOTOR, 'minecraft:air')
            host.command('forceload remove 1440 144 1455 159')
            host.call('tick', {'frozen': False})
        (scratch / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--reference', type=Path)
    for key in ('game', 'resources', 'ctl', 'create-jar'):
        parser.add_argument('--' + key, type=Path)
    args = parser.parse_args()
    if args.java:
        scratch, cases = original()
    elif args.game and args.resources and args.ctl:
        scratch, cases = native(args)
    else:
        parser.error('Horizon runs require --game, --resources and --ctl')
    path = scratch / 'result.json'
    report = dict(passed=False, create=PINS['create_revision'], cases=cases)
    try:
        report['launch'] = verify(cases)
        if args.reference:
            source = json.loads(args.reference.read_text())
            assert source['passed'] and source['create'] == PINS['create_revision'], source
            # The host rotates the same active point using a double quaternion;
            # the original bearing's float rotation leaves a small difference.
            error = math.dist(source['launch']['motion'], report['launch']['motion'])
            assert error < 0.0002, error
            report['motion_error'] = error
            report['launch_tick_delta'] = report['launch']['tick'] - source['launch']['tick']
            assert report['launch_tick_delta'] == 0, report['launch_tick_delta']
        report['passed'] = True
    finally:
        path.write_text(json.dumps(report, indent=2) + '\n')
        print(path)


if __name__ == '__main__':
    main()
