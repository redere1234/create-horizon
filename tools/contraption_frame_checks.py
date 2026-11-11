#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Check that native rendered contraptions advance without replaying a pose."""

import argparse
import json
from pathlib import Path
import shutil

from bearing_capacity_checks import PIVOT as LARGE_ROTOR, setup as setup_large_rotor
from chain_drive_checks import xyz
from native_check_session import NativeCheckSession, wait_loaded
from piston_checks import rig

ROTARY = (904, 100, 74)
LINEAR = (903, 100, 84)
PISTON = ('east', LINEAR, 0, 1, (0, 0, -1), False, False)
MARKER = 'Create contraption frame: '


def run(session):
    with session:
        call = session.call

        def command(value):
            return call('command', value)

        def put(pos, state):
            command(f'setblock {xyz(pos)} {state}')

        command('gamemode spectator')
        command('tp @s 908.5 108 78.5')
        call('look-at', 904.5, 101.0, 79.5)
        wait_loaded(call, [ROTARY, LINEAR])
        command('tick freeze')
        command('fill 897 95 71 911 109 89 minecraft:air')
        put(ROTARY, 'create:mechanical_bearing[facing=up]')
        put((904, 101, 74), 'minecraft:slime_block')
        put((905, 101, 74), 'minecraft:red_wool')
        put((906, 101, 74), 'minecraft:oak_planks')
        power, _, _ = rig(PISTON, put, magnitude=16)
        put((904, 99, 74), 'create:creative_motor[facing=up]{ScrollValue:32}')
        power(False)
        call('wait', 4)
        command('tick unfreeze')
        call('wait', 38)
        command('tick freeze')
        call('wait', 6)
        call('screenshot', session.scratch / 'contraptions.png')


def run_large(session):
    with session:
        call = session.call

        def command(value):
            return call('command', value)

        command('gamemode spectator')
        command('tp @s 1269.5 149 263.5')
        call('look-at', 1256.5, 138.5, 263.5)
        wait_loaded(call, [LARGE_ROTOR])
        command('tick freeze')
        setup_large_rotor(command, 2048)
        command('tick unfreeze')
        call('wait', 38)
        command('tick freeze')
        call('wait', 6)
        call('screenshot', session.scratch / 'rotor-2048.png')


def metrics(rows, pos, linear, minimum=45):
    rows = [row for row in rows if row['controller'] == list(pos)]
    assert rows, pos
    start = rows[0]['time']
    moving = [r for r in rows if start + 4 <= r['time'] <= start + 29]
    assert len(moving) >= minimum, (pos, len(moving))

    def delta(before, after):
        if linear:
            return after['origin'][0] - before['origin'][0]
        return (after['angle'] - before['angle'] + 180) % 360 - 180

    steps = [delta(before, after) for before, after in zip(moving, moving[1:])]
    backwards = [value for value in steps if value < -1e-5]
    return {
        'frames': len(moving),
        'changed': sum(abs(value) > 1e-5 for value in steps),
        'backwards': len(backwards),
        'largest_reverse': min(backwards, default=0),
        'largest_forward': max(steps),
        'net_motion': sum(steps),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('game', 'resources', 'ctl'):
        parser.add_argument('--' + flag, type=Path, required=True)
    parser.add_argument('--observe-only', action='store_true')
    parser.add_argument('--large', action='store_true', help='Observe a 2,048-block rotary payload')
    args = parser.parse_args()
    session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                 name='contraption-frame', world='ContraptionFrame', size=(640, 360))
    session.env['CREATE_TRACE_CONTRAPTION_FRAMES'] = '1'
    print(session.scratch, flush=True)
    try:
        (run_large if args.large else run)(session)
    finally:
        session.control_temp.cleanup()
        for folder in (session.resources, session.scratch / '.horizon-cache', session.scratch / 'horizon-mods'):
            shutil.rmtree(folder, ignore_errors=True)
    rows = [json.loads(line.split(MARKER, 1)[1]) for line in session.log.read_text().splitlines()
            if MARKER in line]
    if args.large:
        report = {'large_rotary': metrics(rows, LARGE_ROTOR, linear=False, minimum=20)}
    else:
        report = {'rotary': metrics(rows, ROTARY, linear=False),
                  'linear': metrics(rows, LINEAR, linear=True)}
    (session.scratch / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    if not args.observe_only:
        assert all(observed['backwards'] == 0 for observed in report.values()), report
        if args.large:
            assert 106 < report['large_rotary']['net_motion'] < 128, report
        else:
            assert 220 < report['rotary']['net_motion'] < 250, report
            assert .72 < report['linear']['net_motion'] < .82, report
    print(report)


if __name__ == '__main__':
    main()
