#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare upright Mechanical Bearing side contact in isolated Java and Horizon worlds."""
import argparse
import json
from pathlib import Path
import tempfile
import time

from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded


PIVOT = (1235, 100, 118)
SWEEP_END = 158.399
CASES = (
    ('north', 16, 117.6, False),
    ('south', -16, 119.4, False),
    ('wall', 16, 117.6, True),
    ('clear', 16, 120.1, False),
)


def rig(command, pivot, rpm, wall):
    command('gamemode creative')
    x, _, _ = pivot
    command(f'fill {x - 3} 100 113 {x + 6} 107 124 minecraft:air')
    command(f'fill {x - 3} 99 113 {x + 6} 99 124 minecraft:stone')
    command(f'setblock {x} 100 118 create:mechanical_bearing[facing=up]')
    command(f'setblock {x} 101 118 minecraft:slime_block')
    command(f'setblock {x + 1} 101 118 minecraft:stone')
    if wall:
        command(f'fill {x} 100 116 {x + 3} 103 116 minecraft:stone')
    return f'setblock {x} 99 118 create:creative_motor[facing=up]{{ScrollValue:{rpm}}}'


def measure(command, load, aim, prepare, sweep):
    cases = {}
    for index, (name, rpm, z, wall) in enumerate(CASES):
        # Use separate columns to prevent landing one fixture into the next.
        # Offset the wall case toward the axle for an unambiguous nearer exit.
        pivot = (PIVOT[0] + 16 * index, *PIVOT[1:])
        feet = (pivot[0] + (1.35 if wall else 1.5), 100, z)
        load(pivot)
        motor = rig(command, pivot, rpm, wall)
        aim(pivot, feet)
        command('gamemode survival')
        before = prepare(pivot)
        assert all(abs(a - b) < 1e-6 for a, b in zip(before['pos'], feet)), before
        trace = sweep(pivot, motor)
        assert trace[-1]['running'] == 1 and abs(trace[-1]['angle']) >= 90, trace
        assert all(abs(sample['pos'][1] - 100) < 1e-6 for sample in trace), trace
        final = trace[-1]['pos']
        cases[name] = {'before': before, 'trace': trace, 'final': final,
                       'delta': [a - b for a, b in zip(final, before['pos'])]}
    return cases


def observe_sweep(snapshot, pause):
    trace = []
    for _ in range(220):
        sample = snapshot()
        if not trace or sample['angle'] != trace[-1]['angle']:
            trace.append(sample)
        if abs(sample['angle']) >= SWEEP_END:
            return trace
        pause()
    raise AssertionError(('Bearing did not complete its sweep', trace))


def java_measure(host):
    state = host.call('state', {})
    assert state['ready'] and state['data_version'] == 3955

    def step(pivot, count):
        trace = host.call('observe_ticks', {'ticks': count, 'positions': [pivot]})['samples']
        # Give the ordinary client synchronization one frame after the server observation.
        time.sleep(.075)
        block = trace[-1]['blocks'][0]
        return dict(angle=number(block, 'Angle', 0), running=number(block, 'Running', 0),
                    pos=host.call('state', {})['position'])

    def snapshot(pivot):
        block = host.call('block', {'pos': pivot})
        return dict(angle=number(block, 'Angle', 0), running=number(block, 'Running', 0),
                    pos=host.call('state', {})['position'])

    def sweep(pivot, motor):
        host.command(motor)
        host.call('tick', {'frozen': False})
        try:
            return observe_sweep(lambda: snapshot(pivot), lambda: time.sleep(.03))
        finally:
            host.call('tick', {'frozen': True})

    def aim(pivot, feet):
        host.call('camera', {'position': feet, 'target': [pivot[0] + 1.5, 101.5, 118.5]})

    def load(pivot):
        host.command(f'tp @s {pivot[0]}.5 108 118.5')
        step(pivot, 8)

    try:
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        host.command('tp @s 1236.5 100 117.6')
        host.command('forceload add 1232 112 1295 127')
        step(PIVOT, 24)
        host.command('tick rate 8')
        return measure(host.command, load, aim, lambda pivot: step(pivot, 5), sweep)
    finally:
        host.command('tick rate 20')
        host.call('tick', {'frozen': state['server']['frozen']})


def native_measure(session):
    call = session.call

    def command(text):
        return call('command', text)['chat']

    def snapshot(pivot):
        block = dict(nbt=' '.join(command('data get block ' + xyz(pivot))))
        player = call('state')['player']
        return dict(angle=number(block, 'Angle', 0), running=number(block, 'Running', 0),
                    pos=player['position'], eye_y=player['eye'][1])

    def prepare(pivot):
        command('tick unfreeze')
        call('wait', 5)
        command('tick freeze')
        return snapshot(pivot)

    def sweep(pivot, motor):
        command(motor)
        # /tick step advances the vanilla clock while the frozen mod block
        # entity dispatcher remains paused. Observe a normal running sweep.
        command('tick unfreeze')
        try:
            return observe_sweep(lambda: snapshot(pivot), lambda: call('wait', 1))
        finally:
            command('tick freeze')

    def aim(pivot, feet):
        command(f'tp @s {xyz(feet)}')
        call('wait', 5)
        call('look-at', pivot[0] + 1.5, 101.5, 118.5)

    def load(pivot):
        command(f'tp @s {pivot[0]}.5 108 118.5')
        wait_loaded(call, [pivot])

    session.start()
    command('tp @s 1236.5 100 117.6')
    wait_loaded(call, [PIVOT])
    command('tick rate 8')
    command('tick freeze')
    return measure(command, load, aim, prepare, sweep)


def validate(cases):
    assert cases['north']['final'][2] < 116.95, cases['north']
    assert cases['south']['final'][2] > 120.05, cases['south']
    wall = cases['wall']
    clipped = [sample['pos'] for sample in wall['trace'] if abs(sample['pos'][2] - 117.3) < 1e-6]
    assert len(clipped) >= 2 and clipped[0][0] - clipped[-1][0] > .9, wall
    assert wall['delta'][0] < -.9, wall
    assert cases['clear']['final'] == cases['clear']['before']['pos'], cases['clear']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    result = dict(passed=False, create=PINS['create_revision'])
    if args.java:
        host = Original()
        work = Path(tempfile.mkdtemp(prefix='rotary-side-java-', dir=ROOT / '.local'))
        try:
            result['cases'] = java_measure(host)
            validate(result['cases'])
            result['passed'] = True
        finally:
            (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
            (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Native comparison requires --game, --resources, --ctl and --reference')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='rotary-side-native')
        work = session.scratch
        try:
            result['cases'] = native_measure(session)
            validate(result['cases'])
            assert all(sample['eye_y'] > 101.6 for case in result['cases'].values()
                       for sample in case['trace']), 'A moving side forced an artificial crawl pose'
            reference = json.loads(args.reference.read_text())
            assert reference['passed'] and reference['create'] == result['create']
            # Java applies contact on its local client with a separately
            # chased bearing angle. Compare settled positions at a common
            # completed sweep, not unsynchronized instantaneous snapshots.
            result['max_final_delta'] = max(
                abs(a - b) for name, case in result['cases'].items()
                for a, b in zip(case['delta'], reference['cases'][name]['delta']))
            assert result['max_final_delta'] < .2, result['max_final_delta']
            result['passed'] = True
        finally:
            session.stop()
            (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(work / 'result.json')


if __name__ == '__main__':
    main()
