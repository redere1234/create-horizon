#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Exercise a moving Harvester and Saw through the real Horizon server."""
import argparse
import json
from pathlib import Path

from bearing_native_checks import Batch
from burner_heat_java_checks import number
from native_check_session import NativeCheckSession


def matched(row):
    return row == '[BearingReview] bearing_check'


def bearing(batch, pivot, actor, reach):
    x, y, z = pivot
    batch.put(pivot, 'create:mechanical_bearing[facing=up]')
    for radial in range(reach):
        batch.put((x + radial, y + 1, z), 'minecraft:slime_block')
    batch.put((x + reach, y + 1, z), actor)
    return (x, y - 1, z)


def powered(batch, motor, speed):
    batch.put(motor, f'create:creative_motor[facing=up]{{ScrollValue:{speed}}}')


def expect_drop(batch, item):
    selector = f'@e[type=minecraft:item,nbt={{Item:{{id:"minecraft:{item}"}}}},limit=1]'
    batch.command(f'execute if entity {selector} run say bearing_check', True)


def check_harvester(session):
    batch = Batch()
    pivot = (904, 100, 58)
    batch.load(pivot)
    batch.command('fill 900 96 53 908 108 62 minecraft:air')
    batch.command('gamerule minecraft:random_tick_speed 0')
    motor = bearing(batch, pivot, 'create:mechanical_harvester[facing=north,waterlogged=false]', 3)
    # Each mature crop intersects a different active-point cell on the turn.
    crops = [
        ((907, 101, 57), 'wheat', 7, 'wheat'),
        ((906, 101, 56), 'carrots', 7, 'carrot'),
        ((905, 101, 55), 'potatoes', 7, 'potato'),
        ((904, 101, 55), 'beetroots', 3, 'beetroot'),
        ((903, 101, 55), 'wheat', 3, None),
    ]
    for (x, y, z), crop, age, _ in crops:
        batch.put((x, y - 1, z), 'minecraft:farmland[moisture=7]')
        batch.put((x, y, z), f'minecraft:{crop}[age={age}]')
    powered(batch, motor, 32)
    batch.tick(14)
    batch.data(pivot)
    for pos, crop, age, item in crops:
        batch.expect(pos, f'minecraft:{crop}[age={0 if item else age}]')
        if item:
            expect_drop(batch, item)
    rows = batch.run(session, 'harvester')
    assert len(rows) == 10, rows
    assert number({'nbt': rows[0]}, 'Running') == 1, rows
    assert all(map(matched, rows[1:])), rows
    return rows


def check_other_crops(session):
    batch = Batch()
    pivot = (920, 100, 58)
    batch.load(pivot)
    batch.command('fill 916 96 53 925 108 62 minecraft:air')
    motor = bearing(batch, pivot, 'create:mechanical_harvester[facing=north]', 3)
    crops = [
        ((923, 101, 57), 'nether_wart[age=3]', 'nether_wart[age=0]', 'soul_sand', 'nether_wart'),
        ((922, 101, 56), 'sweet_berry_bush[age=3]', 'sweet_berry_bush[age=1]', 'dirt', 'sweet_berries'),
        ((921, 101, 55), 'cocoa[age=2,facing=north]', 'cocoa[age=0,facing=north]', 'stone', 'cocoa_beans'),
        ((920, 101, 55), 'oak_leaves[distance=7,persistent=true]', 'air', 'stone', 'oak_leaves'),
        ((919, 101, 55), 'sugar_cane[age=0]', 'air', 'sand', 'sugar_cane'),
    ]
    batch.put((921, 101, 54), 'minecraft:jungle_log[axis=y]')
    batch.put((918, 100, 55), 'minecraft:water')
    for (x, y, z), plant, _, soil, _ in crops:
        batch.put((x, y - 1, z), 'minecraft:' + soil)
        batch.put((x, y, z), 'minecraft:' + plant)
        batch.expect((x, y, z), 'minecraft:' + plant)
    powered(batch, motor, 32)
    batch.tick(15)
    for pos, _, expected, _, item in crops:
        batch.expect(pos, 'minecraft:' + expected)
        expect_drop(batch, item)
    rows = batch.run(session, 'other-crops')
    assert len(rows) == 15 and all(row == '[BearingReview] bearing_check' for row in rows), rows
    return rows


def check_saw(session):
    batch = Batch()
    pivot = (904, 100, 51)
    batch.load((900, 100, 55))
    batch.command('fill 900 96 48 909 108 52 minecraft:air')
    batch.command('fill 904 96 49 908 96 51 minecraft:smooth_stone')
    motor = bearing(batch, pivot, 'create:mechanical_saw[facing=north,axis_along_first=false,flipped=false]', 1)
    logs = [(905, y, 50) for y in range(101, 104)]
    for pos in logs:
        batch.put(pos, 'minecraft:oak_log[axis=y]')
    leaf = (906, 103, 50)
    batch.put(leaf, 'minecraft:oak_leaves[distance=1,persistent=true]')
    unconnected = (908, 102, 50)
    batch.put(unconnected, 'minecraft:oak_log[axis=y]')
    powered(batch, motor, 32)
    for _ in range(10):
        batch.tick()
        batch.data(pivot)
    batch.tick(100)
    batch.data(pivot)
    for pos in [*logs, leaf]:
        batch.expect(pos, 'minecraft:air')
    batch.expect(unconnected, 'minecraft:oak_log[axis=y]')
    expect_drop(batch, 'oak_log')
    rows = batch.run(session, 'saw')
    assert len(rows) == 17, rows
    angles = [number({'nbt': row}, 'Angle', 0) for row in rows[:10]]
    assert any(angles[i] > 0 and angles[i] == angles[i + 1] for i in range(9)), angles
    resumed_angle = number({'nbt': rows[10]}, 'Angle', 0)
    assert resumed_angle not in (0, angles[-1]), (resumed_angle, angles)
    assert all(map(matched, rows[11:])), rows
    return {'angles': angles, 'observations': rows}


def check_drill(session):
    batch = Batch()
    pivot = (904, 100, 74)
    batch.load((903, 104, 79))
    batch.command('fill 900 96 69 911 108 78 minecraft:air')
    motor = bearing(batch, pivot, 'create:mechanical_drill[facing=north]', 1)
    target = (905, 101, 73)
    control = (908, 101, 73)
    batch.put(target, 'minecraft:oak_planks')
    batch.put(control, 'minecraft:bedrock')
    powered(batch, motor, 32)
    for _ in range(10):
        batch.tick()
        batch.data(pivot)
    batch.tick(100)
    batch.data(pivot)
    batch.expect(target, 'minecraft:air')
    batch.expect(control, 'minecraft:bedrock')
    expect_drop(batch, 'oak_planks')
    rows = batch.run(session, 'drill')
    assert len(rows) == 14 and all('[BearingReview] bearing_check' == row for row in rows[11:]), rows
    angles = [number({'nbt': row}, 'Angle', 0) for row in rows[:11]]
    assert any(angles[i] > 0 and angles[i] == angles[i + 1] for i in range(9)), angles
    assert angles[-1] != angles[9], angles
    return {'angles': angles, 'observations': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('game', 'resources', 'ctl'):
        parser.add_argument('--' + flag, type=Path, required=True)
    parser.add_argument('--create-jar', type=Path)
    args = parser.parse_args()
    session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                 name='actors-native', graphics=False, world='CreateActorChecks')
    print(session.scratch, flush=True)
    try:
        result = {'harvester': check_harvester(session), 'other_crops': check_other_crops(session),
                  'saw': check_saw(session), 'drill': check_drill(session)}
        (session.scratch / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    finally:
        session.control_temp.cleanup()
    print(json.dumps({'passed': True, 'world': str(session.scratch)}))


if __name__ == '__main__':
    main()
