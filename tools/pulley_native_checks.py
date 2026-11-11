#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Exercise the same Rope Pulley trace in Horizon, then restart with cargo."""
import argparse
import json
from pathlib import Path

from bearing_native_checks import Batch
from common import PINS
from native_check_session import NativeCheckSession
from pulley_reference_checks import CONTROLLER, DOWN_MOTOR, PATH, UP_MOTOR, actuator_state


def matched(row):
    return row == '[BearingReview] bearing_check'


def expect_path(batch, states):
    for block in states[1:]:
        batch.expect(tuple(map(int, block['pos'])), block['id'])


def check_trace(session, reference):
    batch = Batch()
    batch.load(CONTROLLER)
    batch.command('fill 1124 112 50 1134 124 62 minecraft:air')
    batch.put(CONTROLLER, 'create:rope_pulley')
    batch.expect(CONTROLLER, 'create:rope_pulley[axis=x]')
    batch.tick()
    batch.put(PATH[3], 'minecraft:oak_log[axis=y]')
    batch.put(DOWN_MOTOR, 'create:creative_motor[facing=east]{ScrollValue:128}')
    checks = []

    def sample(phase, index, match_path=False):
        batch.tick()
        batch.data(CONTROLLER)
        blocks = reference[phase][index]['blocks']
        checks.append(('state', actuator_state(blocks[0])))
        if match_path:
            expect_path(batch, blocks)
            checks.extend(('block', block['id']) for block in blocks[1:])

    for index, _ in enumerate(reference['down']):
        sample('down', index, index in (8, 9, 10, 21))
    batch.put(DOWN_MOTOR, 'minecraft:air')
    sample('stop', 0, True)
    batch.put(UP_MOTOR, 'create:creative_motor[facing=west]{ScrollValue:128}')
    for index, _ in enumerate(reference['up']):
        sample('up', index, index in (0, 1, 16, 17, 24))
    rows = batch.run(session, 'pulley-trace')
    assert matched(rows[0]), rows[0]
    assert len(rows) == 1 + len(checks), (len(rows), len(checks))
    for index, ((kind, expected), row) in enumerate(zip(checks, rows[1:])):
        actual = actuator_state({'nbt': row}) if kind == 'state' else matched(row)
        if kind == 'state':
            assert actual == expected, (index, actual, expected, row)
        else:
            assert actual, (index, expected, row)
    return rows


def check_restart(session):
    pos = (1130, 120, 53)
    motor = (1129, 120, 53)
    original = (1130, 119, 53)
    batch = Batch()
    batch.load(pos)
    batch.put(pos, 'create:rope_pulley[axis=x]')
    batch.put(original, 'minecraft:oak_log[axis=x]')
    batch.put(motor, 'create:creative_motor[facing=east]{ScrollValue:64}')
    batch.tick(14)
    batch.data(pos)
    batch.expect(original, 'minecraft:air')
    first = batch.run(session, 'pulley-before-restart')
    offset, running, _ = actuator_state({'nbt': first[0]})
    assert 0 < offset < 3 and running and matched(first[1]), first

    batch = Batch()
    batch.load(pos)
    batch.tick(5)
    batch.data(pos)
    batch.put(pos, 'minecraft:air')
    batch.tick(2)
    batch.expect(pos, 'minecraft:air')
    for y in range(114, 120):
        batch.expect((pos[0], y, pos[2]), 'minecraft:oak_log[axis=x]')
        batch.expect((pos[0], y, pos[2]), 'minecraft:air')
    second = batch.run(session, 'pulley-after-restart')
    resumed, running, _ = actuator_state({'nbt': second[0]})
    assert resumed > offset and running, second
    assert matched(second[1]), second
    assert sum(map(matched, second[2::2])) == 1, second
    assert sum(map(matched, second[3::2])) == 5, second
    return {'before': first, 'after': second, 'offset': offset, 'resumed': resumed}


def check_rope_break(session):
    batch = Batch()
    controller = (1130, 120, 55)
    chain = [(1130, y, 55) for y in range(119, 116, -1)]
    cargo = (1130, 116, 55)
    batch.load((1131, 118, 55))
    batch.put(controller, 'create:rope_pulley[axis=x]{Offset:3f}')
    for segment in chain[:2]:
        batch.put(segment, 'create:rope[waterlogged=false]')
    batch.put(chain[2], 'create:pulley_magnet[waterlogged=false]')
    batch.put(cargo, 'minecraft:oak_log[axis=z]')
    batch.ops.append({'op': 'break', 'pos': chain[1]})
    batch.tick()
    batch.data(controller)
    for pos in chain:
        batch.expect(pos, 'minecraft:air')
    batch.expect(cargo, 'minecraft:oak_log[axis=z]')
    rows = batch.run(session, 'pulley-broken-rope')
    assert actuator_state({'nbt': rows[0]}) == [0, 0, 0], rows
    assert len(rows) == 5 and all(map(matched, rows[1:])), rows
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + flag, type=Path, required=True)
    parser.add_argument('--create-jar', type=Path)
    args = parser.parse_args()
    reference = json.loads(args.reference.read_text())
    assert reference['passed'] and reference['create'] == PINS['create_revision']
    session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                 name='pulley-native', graphics=False, world='CreatePulleyChecks')
    print(session.scratch, flush=True)
    try:
        report = {'trace': check_trace(session, reference), 'restart': check_restart(session),
                  'rope_break': check_rope_break(session)}
        (session.scratch / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    finally:
        session.control_temp.cleanup()
    print(json.dumps({'passed': True, 'world': str(session.scratch)}))


if __name__ == '__main__':
    main()
