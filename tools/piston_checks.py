#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare the pinned Java and Horizon piston strokes and their final blocks."""
import argparse
import json
from pathlib import Path
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession


CASES = (
    ('east', (904, 100, 68), 0, 1, (0, 0, -1), False, False),
    ('west', (904, 100, 74), 0, -1, (0, 0, -1), True, False),
    ('south', (920, 100, 71), 2, 1, (-1, 0, 0), True, True),
    ('up', (913, 100, 75), 1, 1, (-1, 0, 0), False, False),
)
TICKS = 22


def axis_offset(pos, axis, delta):
    return tuple(p + (delta if i == axis else 0) for i, p in enumerate(pos))


def rig(case, put, magnitude=128):
    facing, pos, axis, sign, motor, sticky, obstacle = case
    at = lambda n: axis_offset(pos, axis, sign * n)
    motor_at = tuple(p + d for p, d in zip(pos, motor, strict=True))
    controller = 'create:' + ('sticky_' if sticky else '') + 'mechanical_piston'
    put(pos, controller + f'[facing={facing},axis_along_first={str(axis != 0).lower()}]')
    for n in (-3, -2, -1):
        put(at(n), f'create:piston_extension_pole[facing={facing}]')
    put(at(1), 'minecraft:oak_planks')
    if obstacle:
        put(at(4), 'minecraft:obsidian')
    toward = 'south' if motor[2] else 'east'
    rpm = (-sign if axis != 2 else sign) * magnitude

    def power(reverse):
        put(motor_at, f'create:creative_motor[facing={toward}]{{ScrollValue:{rpm * (-1 if reverse else 1)}}}')

    def clear_power():
        put(motor_at, 'minecraft:air')

    return power, clear_power, [pos, *(at(i) for i in (-3, -2, -1, 1, 2, 3, 4))]


def observation(sample):
    state = sample['properties'].get('state', '').lower()
    return (state, int(number(sample, 'Running', 0)), float(number(sample, 'Offset', 0)))


def block(block):
    properties = block['properties']
    return block['id'] + ('[' + ','.join(f'{k}={v.lower()}' for k, v in sorted(properties.items())) + ']'
                          if properties else '')


def java_reference():
    host = Original()
    host.call('tick', {'frozen': True})
    host.command('gamemode creative')
    host.command('tp @s 913.5 107 73.5')
    host.command('forceload add 896 64 927 79')
    host.call('observe_ticks', {'ticks': 40, 'positions': [(913, 100, 73)]})
    host.command('fill 897 94 65 925 110 78 minecraft:air')
    all_rows = []
    for case in CASES:
        power, clear_power, points = rig(case, lambda p, s: host.command(f'setblock {xyz(p)} {s}'))
        traces = []
        for reverse in (False, True):
            if reverse:
                clear_power()
                host.call('observe_ticks', {'ticks': 2, 'positions': points})
            power(reverse)
            rows = host.call('observe_ticks', {'ticks': TICKS, 'positions': points})['samples']
            traces.append(dict(trace=[observation(row['blocks'][0]) for row in rows],
                               landing=[block(b) for b in rows[-1]['blocks']]))
        assert any(r[1] for r in traces[0]['trace']), (case, traces)
        assert all(rows['trace'][-1][1] == 0 for rows in traces), (case, traces)
        all_rows.append(traces)
    work = Path(tempfile.mkdtemp(prefix='piston-java-', dir=ROOT / '.local'))
    path = work / 'result.json'
    path.write_text(json.dumps(dict(create=PINS['create_revision'], cases=all_rows), indent=2) + '\n')
    (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
    print(path)


def horizon(session, reference):
    batch = Batch()
    batch.load((913, 100, 73))
    batch.command('fill 897 94 65 925 110 78 minecraft:air')
    for case, expected in zip(CASES, reference, strict=True):
        power, clear_power, points = rig(case, batch.put)
        for reverse, expect in zip((False, True), expected, strict=True):
            if reverse:
                clear_power()
                batch.tick(2)
            power(reverse)
            for _ in range(TICKS):
                batch.tick()
                batch.data(points[0])
            for pos, state in zip(points, expect['landing'], strict=True):
                batch.expect(pos, state)
    rows = batch.run(session, 'pistons')
    n = TICKS + 8
    for i, expect in enumerate(row for case in reference for row in case):
        window = rows[i*n:(i+1)*n]
        assert len(window) == n, window
        run = [(number({'nbt': row}, 'Running', 0), number({'nbt': row}, 'Offset', 0)) for row in window[:TICKS]]
        want = [tuple(row[1:]) for row in expect['trace']]
        assert run == want, (CASES[i // 2], i % 2, run, want)
        assert all('bearing_check' in row for row in window[TICKS:]), (CASES[i // 2], i % 2, window[TICKS:])
    print(json.dumps(dict(passed=True, samples=TICKS * 2 * len(CASES), world=str(session.scratch))))


def restart_and_recover(session):
    pos = (935, 104, 70)
    case = ('east', pos, 0, 1, (0, 0, -1), True, False)
    target = (936, 104, 70)
    batch = Batch()
    batch.load(pos)
    batch.command('fill 929 99 66 942 110 74 minecraft:air')
    power, _, _ = rig(case, batch.put, magnitude=8)
    power(False)
    batch.tick(20)
    batch.data(pos)
    batch.expect(target, 'minecraft:air')
    row, empty = batch.run(session, 'piston-before-restart')
    before = number({'nbt': row}, 'Offset', 0)
    assert number({'nbt': row}, 'Running', 0) == 1 and 0 < before < 0.5 and 'bearing_check' in empty

    batch = Batch()
    batch.load(pos)
    batch.tick(5)
    batch.data(pos)
    batch.put(target, 'minecraft:obsidian')
    batch.put(pos, 'minecraft:air')
    batch.tick(5)
    batch.expect(target, 'minecraft:obsidian')
    batch.expect(pos, 'minecraft:air')
    row, obstruction, empty = batch.run(session, 'piston-remove-controller')
    after = number({'nbt': row}, 'Offset', 0)
    assert number({'nbt': row}, 'Running', 0) == 1 and before < after < 0.5
    assert 'bearing_check' in obstruction and 'bearing_check' in empty

    batch = Batch()
    batch.load(pos)
    batch.expect(target, 'minecraft:obsidian')
    batch.put(target, 'minecraft:air')
    batch.tick(5)
    batch.expect(pos, 'create:mechanical_piston_head[facing=east,type=sticky]')
    for x in (932, 933, 934):
        batch.expect((x, 104, 70), 'create:piston_extension_pole[facing=east]')
    batch.expect(target, 'minecraft:oak_planks')
    batch.expect((937, 104, 70), 'minecraft:air')
    rows = batch.run(session, 'piston-orphan-recovery')
    assert all('bearing_check' in r for r in rows), rows
    return {'offset_before_restart': before, 'offset_after_restart': after}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        java_reference()
        return
    if not all((args.game, args.resources, args.ctl, args.reference)):
        parser.error('--game, --resources, --ctl and --reference are required without --java')
    ref = json.loads(args.reference.read_text())
    assert ref['create'] == PINS['create_revision']
    session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                 name='piston-native', graphics=False, world='CreatePistonChecks')
    print(session.scratch, flush=True)
    try:
        horizon(session, ref['cases'])
        print(json.dumps(restart_and_recover(session)))
    finally:
        session.control_temp.cleanup()


if __name__ == '__main__':
    main()
