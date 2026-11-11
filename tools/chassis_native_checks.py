#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Exercise the Java chassis fixtures, rotation and restart in Horizon."""
import argparse
import json
from pathlib import Path

from actor_native_checks import matched, powered
from bearing_native_checks import Batch
from burner_heat_java_checks import number
from chain_drive_checks import xyz
from chassis_reference_checks import LINEAR, RADIAL, SECONDARY, STONE, chassis, scenes
from common import PINS
from native_check_session import NativeCheckSession


def block_state(state):
    return state.split('{', 1)[0]


def expected_range(state):
    return int(state.split('ScrollValue:', 1)[1][:-1]) if 'ScrollValue:' in state else 8


def expect_restored(batch, blocks):
    for pos, state in blocks.items():
        batch.expect(pos, block_state(state))
        if state.startswith((LINEAR, SECONDARY, RADIAL)):
            batch.command(f'execute if data block {xyz(pos)} {{ScrollValue:{expected_range(state)}}} '
                          'run say bearing_check', True)


def geometry(session):
    fixtures = scenes()
    batch = Batch()
    for pivot, payload, controls in fixtures.values():
        x, y, z = pivot
        batch.load(pivot)
        batch.command(f'fill {x - 4} {y - 2} {z - 4} {x + 4} {y + 4} {z + 4} minecraft:air')
        batch.put(pivot, 'create:mechanical_bearing[facing=up]')
        for pos, state in {**payload, **controls}.items():
            batch.put(pos, state)
        powered(batch, (x, y - 1, z), 8)
        batch.tick(4)
        batch.data(pivot)
        for pos in payload:
            batch.expect(pos, 'minecraft:air')
        expect_restored(batch, controls)
    captured = batch.run(session, 'chassis-capture')
    cursor = 0
    for _, payload, controls in fixtures.values():
        count = len(payload) + len(controls) + sum(s.startswith((LINEAR, SECONDARY, RADIAL))
                                                    for s in controls.values())
        assert number({'nbt': captured[cursor]}, 'Running', 0) == 1, captured
        assert all(map(matched, captured[cursor + 1:cursor + 1 + count])), captured
        cursor += 1 + count
    assert len(captured) == cursor, captured

    linear_pivot, linear_payload, linear_controls = fixtures['linear']
    radial_pivot, radial_payload, radial_controls = fixtures['radial']
    lx, ly, lz = linear_pivot
    rx, ry, rz = radial_pivot
    anchor = (lx, ly + 1, lz)
    batch = Batch()
    batch.load(linear_pivot)
    batch.data(linear_pivot)
    batch.put(anchor, 'minecraft:obsidian')
    batch.put(linear_pivot, 'minecraft:air')
    batch.tick(3)
    batch.expect(anchor, 'minecraft:obsidian')
    for pos in linear_payload:
        if pos != anchor:
            batch.expect(pos, 'minecraft:air')
    expect_restored(batch, linear_controls)
    batch.load(radial_pivot)
    batch.data(radial_pivot)
    batch.put((rx, ry - 1, rz), 'minecraft:air')
    batch.tick(2)
    expect_restored(batch, {**radial_payload, **radial_controls})
    restarted = batch.run(session, 'chassis-restart-blocked')
    radial_start = 1 + len(linear_payload) + len(linear_controls) + sum(
        s.startswith((LINEAR, SECONDARY, RADIAL)) for s in linear_controls.values())
    assert number({'nbt': restarted[0]}, 'Running', 0) == 1, restarted
    assert number({'nbt': restarted[radial_start]}, 'Running', 0) == 1, restarted
    assert all(map(matched, restarted[1:radial_start] + restarted[radial_start + 1:])), restarted

    batch = Batch()
    batch.load(linear_pivot)
    batch.expect(anchor, 'minecraft:obsidian')
    batch.put(anchor, 'minecraft:air')
    batch.tick(3)
    expect_restored(batch, {**linear_payload, **linear_controls})
    recovered = batch.run(session, 'chassis-recover')
    assert all(map(matched, recovered)), recovered
    return dict(captured=captured, restarted=restarted, recovered=recovered)


def rotation(session):
    batch = Batch()
    cases = (
        ((1080, 100, 56), chassis(LINEAR, 'x', 5, 'sticky_top'),
         chassis(LINEAR, 'z', 5, 'sticky_bottom')),
        ((1080, 100, 72), chassis(RADIAL, 'y', 6, 'sticky_east'),
         chassis(RADIAL, 'y', 6, 'sticky_north')),
        ((1080, 100, 88), chassis(RADIAL, 'z', 7, 'sticky_east'),
         chassis(RADIAL, 'x', 7, 'sticky_west')),
        ((1080, 100, 104), chassis(SECONDARY, 'x', 4, 'sticky_top'),
         chassis(SECONDARY, 'z', 4, 'sticky_bottom')),
    )
    for (x, y, z), initial, landed in cases:
        pivot = (x, y, z)
        anchor = (x, y + 1, z)
        payload = (x + 1, y + 1, z)
        motor = (x, y - 1, z)
        batch.load(pivot)
        batch.command(f'fill {x - 3} {y - 2} {z - 3} {x + 3} {y + 4} {z + 3} minecraft:air')
        batch.put(pivot, 'create:mechanical_bearing[facing=up]')
        batch.put(anchor, initial)
        batch.put(payload, STONE)
        powered(batch, motor, 32)
        batch.tick(10)
        batch.expect(anchor, 'minecraft:air')
        batch.put(motor, 'minecraft:air')
        batch.tick()
        expect_restored(batch, {anchor: landed})
        batch.expect(payload, 'minecraft:air')
        batch.expect((x, y + 1, z - 1), STONE)
        batch.command(f'setblock {xyz(anchor)} minecraft:air destroy')
        item = landed.split('[', 1)[0]
        batch.command(f'execute if entity @e[type=minecraft:item,x={x},y={y},z={z},distance=..8,'
                      f'nbt={{Item:{{id:"{item}"}}}},limit=1] run say bearing_check', True)
    rows = batch.run(session, 'chassis-rotate-and-drop')
    assert len(rows) == len(cases) * 6 and all(map(matched, rows)), rows
    return rows


def hand(session):
    a, b = (1071, 100, 86), (1073, 100, 89)
    batch = Batch()
    batch.load((1073, 100, 88))
    batch.command('fill 1068 100 82 1078 106 94 minecraft:air')
    batch.command('fill 1068 99 82 1078 99 94 minecraft:stone')
    batch.put(a, f'{LINEAR}[axis=x]')
    batch.put(b, f'{RADIAL}[axis=x]')
    batch.run(session, 'chassis-hand-setup')
    with session:
        call = session.call
        call('command', 'gamemode survival')
        call('command', 'clear @s')
        call('command', 'give @s minecraft:slime_ball 3')
        call('select', 1)

        def click(pos, face, vantage):
            call('command', f'tp @s {xyz(vantage)}')
            call('wait', 6)
            call('look-at', 'block', *pos, face)
            hit = call('looking-at')['block']
            assert hit['pos'] == list(pos) and hit['face'] == face, hit
            call('mouse', 'right', 'click')
            call('wait', 8)
            return call('block', *pos)['state']

        first = click(a, 'east', (1073.5, 100, 86.5))
        assert 'sticky_top=true' in first and 'sticky_bottom=false' in first, first
        both = click(a, 'east', (1073.5, 100, 86.5))
        assert 'sticky_top=true' in both and 'sticky_bottom=true' in both, both
        radial = click(b, 'up', (1073.5, 100, 92.5))
        assert 'sticky_north=true' in radial, radial
        stack = call('inventory')['hotbar'][0]
        assert stack['item'] == 'minecraft:slime_ball' and stack['count'] == 3, stack
        call('select', 9)
        call('key', 'shift', 'down')
        try:
            cleared = click(a, 'east', (1073.5, 100, 86.5))
            assert 'sticky_top=false' in cleared and 'sticky_bottom=true' in cleared, cleared
        finally:
            call('key', 'shift', 'up')
        call('command', 'item replace entity @s hotbar.0 with create:super_glue')
        call('select', 1)
        call('wait', 6)
        assert call('inventory')['hotbar'][0]['item'] == 'create:super_glue'
        glued = click(a, 'east', (1073.5, 100, 86.5))
        assert 'sticky_top=true' in glued, glued
        hand = ' '.join(call('command', 'data get entity @s SelectedItem')['chat'])
        assert 'create:super_glue' in hand and 'minecraft:damage' not in hand, hand
        call('command', 'clear @s')
        call('command', f'give @s {LINEAR}')
        call('select', 1)
        joined = click(a, 'west', (1068.5, 100, 86.5))
        neighbor = (a[0] - 1, a[1], a[2])
        assert 'sticky_bottom=false' in joined, joined
        assert call('block', *neighbor)['state'] == f'{LINEAR}[axis=x,sticky_bottom=false,sticky_top=false]'
        range_default = call('command', f'data get block {xyz(neighbor)}')['chat']
        assert any(number({'nbt': row}, 'ScrollValue', 0) == 8 for row in range_default), range_default

        call('command', 'clear @s')
        call('command', 'give @s minecraft:iron_axe')
        call('select', 1)
        call('command', 'tp @s 1073.5 100 86.5')
        call('wait', 6)
        call('look-at', 'block', *a, 'east')
        call('mouse', 'left', 'down')
        try:
            call('wait', 32)
        finally:
            call('mouse', 'left', 'up')
        assert call('block', *a)['block'] == 'minecraft:air'
        loot = call('command', f'execute if entity @e[type=minecraft:item,'
                    f'nbt={{Item:{{id:"{LINEAR}"}}}},limit=1] run say chassis_drop')['chat']
        assert any(row == '[BearingReview] chassis_drop' for row in loot), loot
    return dict(first=first, both=both, radial=radial, cleared=cleared, glued=glued, joined=joined)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('game', 'resources', 'ctl'):
        parser.add_argument('--' + flag, type=Path, required=True)
    parser.add_argument('--create-jar', type=Path)
    parser.add_argument('--hand', action='store_true', help='Also test ordinary survival mouse input')
    args = parser.parse_args()
    session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                 name='chassis-native', graphics=args.hand,
                                 world='CreateChassisChecks', username='BearingReview')
    print(session.scratch, flush=True)
    try:
        result = dict(geometry=geometry(session), rotation=rotation(session))
        if args.hand:
            result['hand'] = hand(session)
        path = session.scratch / 'result.json'
        path.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], **result),
                                   indent=2) + '\n')
        print(json.dumps(dict(passed=True, result=str(path))))
    finally:
        session.stop()


if __name__ == '__main__':
    main()
