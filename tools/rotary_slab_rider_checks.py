#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare a grounded player's travel on a moving bottom slab."""

import argparse
import json
import math
from pathlib import Path
import shutil
import tempfile
import time

from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded


PIVOT = (1509, 100, 280)
FEET = (1510.5, 101.6, 280.5)
CENTER = (1509.5, 280.5)
MOTOR = 'setblock 1509 99 280 create:creative_motor[facing=up]{ScrollValue:16}'
LOAD = '1504 272 1519 287'


def setup(command):
    command('fill 1506 99 276 1514 106 284 minecraft:air')
    command('fill 1506 99 276 1514 99 284 minecraft:stone')
    command('setblock 1509 100 280 create:mechanical_bearing[facing=up]')
    command('setblock 1509 101 280 minecraft:slime_block')
    command('setblock 1510 101 280 minecraft:oak_slab[type=bottom,waterlogged=false]')
    command('gamemode survival')


def observe(read, pause):
    trace = []
    for _ in range(150):
        row = read()
        if not trace or row['angle'] != trace[-1]['angle']:
            trace.append(row)
        if row['angle'] >= 58:
            return trace
        pause()
    raise AssertionError(('No complete sweep', trace))


def verify(before, trace):
    assert abs(before[1] - 101.5) < 0.001, before
    assert len(trace) >= 7 and 58 <= trace[-1]['angle'] < 75, trace
    assert all(abs(row['position'][1] - 101.5) < 0.001 for row in trace), trace
    final = trace[-1]['position']
    radial_errors = [abs(math.hypot(x - CENTER[0], z - CENTER[1]) - 1)
                     for x, _, z in (row['position'] for row in trace)]
    # Radial error is independent of when the observation reads the angle.
    # The old native contact clipped the tangent and drifted by 0.06 blocks.
    assert max(radial_errors) < 0.002 and before[2] - final[2] > 0.65, trace
    return radial_errors[-1], max(radial_errors)


def java_run(work):
    host = Original()
    state = host.call('state', {})
    assert state['ready'] and state['data_version'] == 3955, state
    def read():
        bearing = host.call('block', {'pos': PIVOT})
        return dict(angle=number(bearing, 'Angle', 0), position=host.call('state', {})['position'])
    try:
        host.call('tick', {'frozen': True})
        host.command('forceload add ' + LOAD)
        host.command('tp @s 1509.5 105 280.5')
        host.snapshot([PIVOT], 24)
        setup(host.command)
        host.call('camera', {'position': FEET, 'target': [1509.5, 101.5, 280.5]})
        host.snapshot([PIVOT], 8)
        before = host.call('state', {})['position']
        host.command('tick rate 8')
        host.command(MOTOR)
        host.call('tick', {'frozen': False})
        return before, observe(read, lambda: time.sleep(.04))
    finally:
        host.call('tick', {'frozen': True})
        host.command('tick rate 20')
        host.command('fill 1506 99 276 1514 106 284 minecraft:air')
        host.command('forceload remove ' + LOAD)
        host.call('camera', {'position': state['position'], 'yaw': state['yaw'], 'pitch': state['pitch']})
        host.call('tick', {'frozen': state['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    call = session.call
    def command(text):
        return call('command', text)['chat']
    def read():
        bearing = {'nbt': ' '.join(command('data get block ' + xyz(PIVOT)))}
        return dict(angle=number(bearing, 'Angle', 0), position=call('state')['player']['position'])
    try:
        session.start()
        command('tp @s 1509.5 105 280.5')
        wait_loaded(call, [PIVOT])
        setup(command)
        command('tp @s ' + xyz(FEET))
        call('wait', 12)
        player = call('state')['player']
        assert player['on_ground'], player
        command('tick freeze')
        command('tick rate 8')
        command(MOTOR)
        command('tick unfreeze')
        return player['position'], observe(read, lambda: call('wait', 1))
    finally:
        session.stop()
        session.control_temp.cleanup()
        (session.scratch / 'transcript.json').write_text(json.dumps(session.transcript, indent=2) + '\n')
        for path in (session.resources, session.scratch / '.horizon-cache', session.scratch / 'horizon-mods'):
            shutil.rmtree(path, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='rotary-slab-rider-java-', dir=ROOT / '.local'))
        before, trace = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Native test requires --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='rotary-slab-rider-native', world='CreateRotarySlabRider')
        work = session.scratch
        before, trace = native_run(session)
    result = dict(passed=False, create=PINS['create_revision'], before=before, trace=trace)
    path = work / 'result.json'
    try:
        result['final_radius_error'], result['maximum_radius_error'] = verify(before, trace)
        if not args.java:
            java = {round(row['angle'], 1): row['position'] for row in reference['trace']}
            distances = [math.dist(row['position'], java[round(row['angle'], 1)]) for row in trace
                         if round(row['angle'], 1) in java]
            # The two client samples can be separated by an attachment or
            # entity update. Preserve the measured distance in the receipt.
            assert len(distances) >= 5 and max(distances) < 0.23, distances
            result['maximum_matched_angle_distance'] = max(distances)
        result['passed'] = True
    finally:
        path.write_text(json.dumps(result, indent=2) + '\n')
        print(path)


if __name__ == '__main__':
    main()
