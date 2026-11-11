#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare native Gantry placement phases and verify obstructed save recovery."""
import argparse
import json
from pathlib import Path

from bearing_native_checks import Batch
from burner_heat_java_checks import number
from common import PINS
from gantry_reference_checks import CASES, TRACE_TICKS, rig
from native_check_session import NativeCheckSession

MATCH = '[BearingReview] bearing_check'

def reference_cases(reference):
    assert reference['create'] == PINS['create_revision']
    cases = reference['cases']
    # Older captures recorded full Java bridge rows. Keep those usable as a
    # reference while the reproducible driver emits only the observed fields.
    return {name: case['presence'] if isinstance(case, dict) else [
        [block['id'] for block in row['blocks'][3:]] for row in case
    ] for name, case in cases.items()}


def compare(session, reference):
    batch = Batch()
    batch.load((954, 101, 104))
    batch.command('fill 944 97 97 958 107 111 minecraft:air')
    checks = []
    for name, z, initial, rpm, destination in CASES:
        rails, power = rig(batch.put, z, initial, rpm)
        batch.tick()
        for rail, part in zip(rails, ('start', 'middle', 'end')):
            batch.expect(rail, f'create:gantry_shaft[facing=east,part={part},powered=false]')
            checks.append((name, 'initial', rail, part))
        power()
        carriage = [(x, y, z) for x in range(948, 951) for y in (101, 102)]
        assert len(reference[name]) == TRACE_TICKS
        for tick, row in enumerate(reference[name]):
            if name == 'powered' and tick == 6:
                batch.put((949, 100, z + 1), 'minecraft:redstone_block')
            batch.tick()
            assert len(row) == len(carriage)
            for pos, block in zip(carriage, row):
                batch.expect(pos, block)
                checks.append((name, tick + 1, pos, block))
        for rail in rails:
            batch.expect(rail, 'create:gantry_shaft[powered=' + ('true' if name == 'powered' else 'false') + ']')
            checks.append((name, 'final rail power', rail, name == 'powered'))
        batch.expect((destination, 101, z), 'create:gantry_carriage[facing=up,axis_along_first=false]')
        checks.append((name, 'final orientation', (destination, 101, z), 'up, shaft Z'))
    rows = batch.run(session, 'gantry-reference')
    assert len(checks) == len(rows)
    failures = [(check, observed) for check, observed in zip(checks, rows) if observed != MATCH]
    assert not failures, (len(failures), failures[:12])
    return len(checks)


def blocked_reload(session):
    z = 117
    batch = Batch()
    batch.load((954, 101, z))
    batch.command('fill 944 97 112 958 107 124 minecraft:air')
    _, power = rig(batch.put, z, 948, -128)
    batch.tick()
    power()
    batch.tick(7)
    batch.expect((948, 101, z), 'minecraft:air')
    batch.expect((948, 102, z), 'minecraft:air')
    assert all(row == MATCH for row in batch.run(session, 'gantry-moving-save'))

    batch = Batch()
    batch.load((954, 101, z))
    batch.put((949, 101, z), 'minecraft:obsidian')
    batch.put((949, 100, z + 1), 'minecraft:redstone_block')
    batch.tick(3)
    batch.expect((949, 101, z), 'minecraft:obsidian')
    batch.expect((949, 102, z), 'minecraft:air')
    batch.expect((948, 101, z), 'minecraft:air')
    assert all(row == MATCH for row in batch.run(session, 'gantry-parked-save'))

    batch = Batch()
    batch.load((954, 101, z))
    batch.put((949, 101, z), 'minecraft:air')
    batch.tick(3)
    batch.expect((949, 101, z), 'create:gantry_carriage[facing=up,axis_along_first=false]')
    batch.expect((949, 102, z), 'minecraft:oak_planks')
    for x in (948, 950):
        for y in (101, 102):
            batch.expect((x, y, z), 'minecraft:air')
    rows = batch.run(session, 'gantry-parked-restored')
    assert all(row == MATCH for row in rows), rows


def powered_pinion(session):
    batch = Batch()
    batch.load((949, 100, 109))
    output = (949, 101, 110)
    batch.put(output, 'create:shaft[axis=z]')
    batch.tick(4)
    batch.data((949, 101, 109))
    batch.data(output)
    batch.put((949, 100, 110), 'minecraft:air')
    batch.tick(14)
    batch.expect((950, 101, 109), 'create:gantry_carriage[facing=up,axis_along_first=false]')
    batch.expect((950, 102, 109), 'minecraft:oak_planks')
    batch.expect((949, 101, 109), 'minecraft:air')
    carriage, shaft, *resumed = batch.run(session, 'gantry-powered-pinion')
    assert 'create:gantry_pinion' in carriage, carriage
    assert number({'nbt': carriage}, 'Speed') == number({'nbt': shaft}, 'Speed') == -128
    assert resumed == [MATCH] * 3, resumed


def other_axes(session):
    batch = Batch()
    batch.load((904, 101, 110))
    batch.command('fill 898 97 98 910 109 125 minecraft:air')
    for base, axis, facing, mount, first in [((904, 100, 117), 1, 'up', (1, 0, 0), 'false'),
                                             ((904, 100, 103), 2, 'south', (0, 1, 0), 'true')]:
        rails = [tuple(p + (distance if i == axis else 0) for i, p in enumerate(base))
                 for distance in (-1, 0, 1, 2)]
        for rail in rails[1:]:
            batch.put(rail, f'create:gantry_shaft[facing={facing}]')
        mount_face = 'east' if axis == 1 else 'up'
        carriage = f'create:gantry_carriage[facing={mount_face},axis_along_first={first}]'
        start = tuple(p + d for p, d in zip(rails[1], mount))
        payload = tuple(p + d for p, d in zip(start, mount))
        end = tuple(p + d for p, d in zip(rails[-1], mount))
        end_payload = tuple(p + d for p, d in zip(end, mount))
        batch.put(start, carriage)
        batch.put(payload, 'minecraft:oak_planks')
        batch.tick()
        batch.put(rails[0], f'create:creative_motor[facing={facing}]{{ScrollValue:-128}}')
        batch.tick(4)
        batch.expect(start, 'minecraft:air')
        batch.expect(payload, 'minecraft:air')
        batch.tick(12)
        batch.expect(end, carriage)
        batch.expect(end_payload, 'minecraft:oak_planks')
    rows = batch.run(session, 'gantry-y-and-z')
    assert rows == [MATCH] * 8, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + flag, type=Path, required=True)
    parser.add_argument('--reload', action='store_true')
    args = parser.parse_args()
    reference = reference_cases(json.loads(args.reference.read_text()))
    session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                 name='gantry-native', graphics=False,
                                 world='CreateGantryChecks')
    print(session.scratch, flush=True)
    try:
        checks = compare(session, reference)
        powered_pinion(session)
        other_axes(session)
        if args.reload:
            blocked_reload(session)
    finally:
        session.control_temp.cleanup()
    print(json.dumps(dict(passed=True, checks=checks, obstructed_reload=args.reload,
                          world=str(session.scratch))))


if __name__ == '__main__':
    main()
