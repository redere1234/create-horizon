#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Check actual dropped-item support and optional local rider transfer."""
import argparse
import json
import math
from pathlib import Path
import re

from bearing_native_checks import Batch
from burner_heat_java_checks import number
from native_check_session import NativeCheckSession, wait_loaded


def item_height(observation):
    match = re.search(r'entity data: (-?\d+(?:\.\d+)?)d\b', observation)
    assert match, observation
    return float(match[1])


def drop_copper(batch, position, tag):
    coords = ' '.join(map(str, position))
    batch.command(f'summon minecraft:item {coords} '
                  + '{Tags:["' + tag + '"],PickupDelay:32767,Motion:[0d,0d,0d],'
                  + 'Item:{id:"minecraft:copper_ingot",count:1}}')


def observe_height(batch, tag):
    batch.command(f'data get entity @e[type=minecraft:item,tag={tag},limit=1] Pos[1]', True)


def test_item_support(session):
    batch = Batch()
    batch.load((910, 104, 52))
    batch.command('fill 897 96 43 924 109 61 minecraft:air')
    batch.command('fill 899 96 46 912 96 54 minecraft:stone')
    pivot = (903, 100, 50)
    anchor = (903, 101, 50)
    batch.put(pivot, 'create:mechanical_bearing[facing=up]')
    batch.put(anchor, 'minecraft:slime_block')
    batch.put((904, 101, 50), 'minecraft:oak_planks')
    batch.put((903, 99, 50), 'create:creative_motor[facing=up]{ScrollValue:32}')
    batch.tick(6)
    batch.data(pivot)
    batch.expect(anchor, 'minecraft:air')

    drop_copper(batch, (903.5, 104.5, 50.5), 'contraption_collision')
    drop_copper(batch, (909.5, 104.5, 50.5), 'empty_collision_control')
    batch.tick(30)
    for tag in ('contraption_collision', 'empty_collision_control'):
        observe_height(batch, tag)
    batch.data(pivot)

    before, air, moving_item, control_item, after = batch.run(session, 'item-collision')
    assert number({'nbt': before}, 'Running') == number({'nbt': after}, 'Running') == 1
    assert number({'nbt': before}, 'Angle') != number({'nbt': after}, 'Angle')
    assert 'bearing_check' in air, air
    moving_height, control_height = item_height(moving_item), item_height(control_item)
    # The pinned Java collider separates the item by another 1e-4 blocks.
    assert abs(moving_height - 102) <= 0.000101, moving_item
    assert abs(control_height - 97) < 1e-6, control_item
    return dict(moving_height=moving_height, control_height=control_height)


def test_piston_pole(session):
    batch = Batch()
    pivot = (919, 100, 60)
    batch.load(pivot)
    batch.command('fill 913 96 56 925 109 63 minecraft:air')
    batch.command('fill 914 96 57 925 96 63 minecraft:stone')
    batch.put(pivot, 'create:mechanical_piston[facing=east,axis_along_first=true,state=retracted]')
    for x in (916, 917, 918):
        batch.put((x, 100, 60), 'create:piston_extension_pole[facing=east]')
    batch.put((919, 99, 60), 'create:creative_motor[facing=up]{ScrollValue:-8}')
    batch.tick(6)
    batch.data(pivot)
    batch.expect((918, 100, 60), 'minecraft:air')
    drop_copper(batch, (918.75, 103.5, 60.5), 'centered_pole')
    drop_copper(batch, (918.75, 103.5, 60.1), 'offaxis_pole')
    batch.tick(30)
    observe_height(batch, 'centered_pole')
    observe_height(batch, 'offaxis_pole')
    batch.data(pivot)
    before, air, center, off_axis, after = batch.run(session, 'piston-pole-collision')
    assert number({'nbt': before}, 'Running') == number({'nbt': after}, 'Running') == 1
    assert number({'nbt': before}, 'Offset') < number({'nbt': after}, 'Offset')
    assert 'bearing_check' in air, air
    pole_height, off_axis_height = item_height(center), item_height(off_axis)
    assert pole_height == 100.625 and off_axis_height == 97.0, (center, off_axis)
    return dict(piston_pole_height=pole_height, piston_pole_control_height=off_axis_height)


def test_linear_riders(session):
    def command(text):
        return session.call('command', text)

    def move_to(position):
        command('tp @s ' + ' '.join(map(str, position)))

    def sample(start_position, axis):
        move_to(start_position)
        session.call('wait', 27)
        start = session.call('state')
        session.call('wait', 18)
        end = session.call('state')
        a, b = start['player'], end['player']
        assert a['on_ground'] and b['on_ground'], (a, b)
        delta = [b['position'][i] - a['position'][i] for i in range(3)]
        expected = (end['ticks'] - start['ticks']) * (8.0 / 512.0)
        assert abs(delta[axis] - expected) < 0.05, (a, b, delta, expected)
        assert all(abs(d) < 1e-6 for i, d in enumerate(delta) if i != axis), delta
        return delta[axis]

    command('tick unfreeze')
    move_to((922.2, 104.5, 75.5))
    wait_loaded(session.call, [(919, 100, 75)])
    command('fill 913 96 70 925 109 79 minecraft:air')
    command('fill 914 96 70 925 96 79 minecraft:stone')
    command('setblock 919 100 75 create:mechanical_piston[facing=east,axis_along_first=true]')
    for x in (916, 917, 918):
        command(f'setblock {x} 100 75 create:piston_extension_pole[facing=east]')
    command('fill 920 100 74 923 100 76 minecraft:slime_block')
    command('setblock 919 99 75 create:creative_motor[facing=up]{ScrollValue:-8}')
    horizontal = sample((922.2, 104.5, 75.5), 0)
    command('fill 924 101 73 924 104 77 minecraft:stone')
    move_to((923.4, 101.0, 75.5))
    session.call('wait', 30)
    stopped = session.call('state')['player']
    assert stopped['on_ground'] and abs(stopped['position'][0] - 923.7) < 1e-5, stopped

    move_to((905.5, 104.5, 75.5))
    wait_loaded(session.call, [(905, 100, 75)])
    command('fill 900 95 70 910 109 79 minecraft:air')
    command('fill 901 95 70 910 95 79 minecraft:stone')
    command('setblock 905 100 75 create:mechanical_piston[facing=up,axis_along_first=true]')
    for y in (97, 98, 99):
        command(f'setblock 905 {y} 75 create:piston_extension_pole[facing=up]')
    command('setblock 905 101 75 minecraft:stone')
    command('setblock 904 100 75 create:creative_motor[facing=east]{ScrollValue:-8}')
    vertical = sample((905.5, 104.5, 75.5), 1)
    return dict(linear_rider_horizontal_delta=horizontal, linear_rider_vertical_delta=vertical,
                linear_rider_stopped_at_wall=stopped['position'][0])


def test_side_push(session):
    call = session.call

    def command(line):
        return call('command', line)

    def side(z, expected_z):
        pivot = (903, 100, 102)
        command('tick unfreeze')
        command(f'tp @s 905.45 100 {z}')
        wait_loaded(call, [pivot])
        command('fill 898 100 98 910 107 107 minecraft:air')
        command('fill 898 99 98 910 99 107 minecraft:stone')
        command('setblock 903 100 102 create:mechanical_piston[facing=east,axis_along_first=false]')
        for x in (900, 901, 902):
            command(f'setblock {x} 100 102 create:piston_extension_pole[facing=east]')
        command('setblock 904 100 102 minecraft:stone')
        command(f'tp @s 905.45 100 {z}')
        call('wait', 8)
        before = call('state')['player']
        assert before['on_ground'], before
        command('setblock 903 100 101 create:creative_motor[facing=south]{ScrollValue:-32}')
        call('wait', 20)
        after = call('state')['player']
        assert after['position'][0] > before['position'][0] + 0.45, (before, after)
        assert abs(after['position'][1] - 100.0) < 1e-6 and after['on_ground'], after
        assert abs(after['position'][2] - z) < 1e-6, after
        command('fill 907 101 101 907 104 103 minecraft:stone')
        call('wait', 40)
        at_wall = call('state')['player']
        assert abs(at_wall['position'][2] - expected_z) < 1e-5, at_wall
        assert abs(at_wall['position'][0] - 906.7) < 1e-5, at_wall
        assert abs(at_wall['position'][1] - 100.0) < 1e-6 and at_wall['on_ground'], at_wall
        return dict(before=before['position'], free=after['position'], obstructed=at_wall['position'])

    return dict(side_push_south=side(102.65, 103.30010011192093),
                side_push_north=side(102.35, 101.69989988807907))


def test_player_carry(session, pistons, side):
    batch = Batch()
    pivot = (920, 100, 52)
    batch.load(pivot)
    batch.command('fill 916 96 48 924 110 56 minecraft:air')
    batch.command('fill 916 96 48 924 96 56 minecraft:stone')
    batch.put(pivot, 'create:mechanical_bearing[facing=up]')
    batch.command('fill 918 101 50 922 101 54 minecraft:slime_block')
    batch.put((920, 99, 52), 'create:creative_motor[facing=up]{ScrollValue:8}')
    batch.tick(6)
    batch.data(pivot)
    batch.expect((920, 101, 52), 'minecraft:air')
    running, empty = batch.run(session, 'rider-platform')
    assert number({'nbt': running}, 'Running') == 1 and 'bearing_check' in empty

    with session:
        session.call('command', 'tp @s 921.9 104.5 52.5')
        wait_loaded(session.call, [pivot])
        session.call('command', 'gamemode survival')
        session.call('wait', 27)
        start_state = session.call('state')
        session.call('wait', 18)
        end_state = session.call('state')
        session.call('command', 'tick freeze')
        session.call('wait', 4)
        frozen = session.call('state')['player']
        session.call('wait', 15)
        frozen_end = session.call('state')['player']
        linear = test_linear_riders(session) if pistons else {}
        if side:
            linear.update(test_side_push(session))

    def relative(player):
        x, y, z = player['position']
        assert player['on_ground'] and abs(y - 102.0) < 1e-6, player
        return (x - 920.5, z - 52.5)

    start, end = start_state['player'], end_state['player']
    first, last = relative(start), relative(end)
    assert abs(math.hypot(*first) - 1.4) < 0.04, start
    assert abs(math.hypot(*last) - 1.4) < 0.04, end
    assert math.dist(first, last) > 0.45, (start, end)
    yaw = math.degrees(math.atan2(first[0] * last[1] - first[1] * last[0],
                                  first[0] * last[0] + first[1] * last[1]))
    # At 8 RPM, the reference bearing turns 2.4 degrees per tick. Allow the
    # client snapshot to be a few ticks behind the authoritative attachment.
    expected_yaw = -2.4 * (end_state['ticks'] - start_state['ticks'])
    assert abs(yaw - expected_yaw) < 7.21, (yaw, expected_yaw, start, end)
    assert math.dist(relative(frozen), relative(frozen_end)) < 1e-6, (frozen, frozen_end)
    return dict(rider_start=start['position'], rider_end=end['position'],
                rider_frozen=frozen_end['position'], rider_yaw_delta=yaw, **linear)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('game', 'resources', 'ctl'):
        parser.add_argument('--' + flag, type=Path, required=True)
    parser.add_argument('--player', action='store_true', help='Also test client-side rider transfer')
    parser.add_argument('--piston', action='store_true', help='Also test moving Mechanical Piston parts')
    parser.add_argument('--side', action='store_true', help='Test a translating face pushing a player')
    args = parser.parse_args()
    if args.side and not args.player:
        parser.error('--side requires --player')
    session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                 name='contraption-collision', graphics=args.player,
                                 world='CreateContraptionCollisionChecks', size=(800, 450),
                                 username='BearingReview')
    print(session.scratch, flush=True)
    try:
        result = test_item_support(session)
        if args.piston:
            result.update(test_piston_pole(session))
        if args.player:
            result.update(test_player_carry(session, args.piston, args.side))
    finally:
        session.control_temp.cleanup()
    print(json.dumps(dict(passed=True, world=str(session.scratch), **result)))


if __name__ == '__main__':
    main()
