#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Verify two-click Super Glue selection and disk persistence in Horizon."""
import argparse
import json
import math
from pathlib import Path
import re

from native_check_session import NativeCheckSession, wait_loaded
from saved_block_checks import read_saved_chunk_tag


A = (1002, 100, 55)
B = (1003, 100, 55)
DISCONNECTED = (1005, 100, 55)
ITEM = 'create:super_glue'
KEYS = ('horizon:attachments', 'create', 'super_glue', 'value')
MOUNTED_KEYS = ('horizon:attachments', 'create', 'mounted_super_glue', 'value')


def xyz(pos):
    return ' '.join(map(str, pos))


def run(session, transfer=False):
    call = session.call
    report = dict(passed=False, cases={})

    def command(text):
        return call('command', text)['chat']

    def selected_damage():
        text = ' '.join(command('data get entity @s SelectedItem'))
        assert ITEM in text, text
        damage = re.search(r'"?minecraft:damage"?:\s*(\d+)', text)
        return int(damage[1]) if damage else 0

    def click(pos, button='right', air=False, vantage=None):
        x, y, z = pos
        command('tp @s ' + xyz(vantage or (x+.5, 99, z-2.5)))
        call('wait', 5)
        call('look-at', x+.5, y+.5, z+.5)
        call('wait', 4)
        hit = call('looking-at')['block']
        if air:
            assert hit is None, hit
        else:
            assert hit['pos'] == list(pos), hit
        call('mouse', button, 'click')
        call('wait', 8)

    def saved(keys=KEYS):
        call('save')
        return read_saved_chunk_tag(session.scratch, A, keys, session.world)['nbt']

    def block(pos):
        return call('block', *pos)['block']

    def put(pos, state):
        command(f'setblock {xyz(pos)} {state}')

    def tick_time():
        found = re.findall(r'\b\d+\b', ' '.join(command('time query gametime')))
        assert len(found) == 1, found
        return int(found[0])

    def step(ticks):
        before = tick_time()
        command(f'tick step {ticks}')
        for _ in range(50):
            after = tick_time()
            if after == before + ticks:
                return
            assert after < before + ticks, (before, after, ticks)
            call('wait', 2)
        raise AssertionError(('tick step did not complete', before, ticks))

    def bearing_angle(pivot):
        text = ' '.join(command(f'data get block {xyz(pivot)} Angle'))
        angle = re.search(r'([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)f\s*$', text)
        assert angle, text
        return float(angle[1])

    try:
        session.start()
        command('tp @s 1002.5 99 52.5')
        wait_loaded(call, [A])
        command('fill 1000 98 51 1007 98 60 minecraft:smooth_stone')
        command('fill 1000 99 51 1007 106 60 minecraft:air')
        for pos in (A, B, DISCONNECTED):
            command(f'setblock {xyz(pos)} minecraft:stone')
        command('gamemode survival')
        call('select', 1)
        command(f'item replace entity @s weapon.mainhand with {ITEM} 1')
        assert selected_damage() == 0

        click(A)
        click(DISCONNECTED)
        assert selected_damage() == 0 and saved() is None
        call('select', 2)
        call('wait', 6)
        call('select', 1)
        click(B)
        assert selected_damage() == 0 and saved() is None
        call('key', 'shift', 'down')
        try:
            click(A)
        finally:
            call('key', 'shift', 'up')
        click(B)
        assert selected_damage() == 0 and saved() is None
        click(A)
        assert selected_damage() == 2
        value = saved()
        assert value['value']['Version'] == {'type': 'int', 'value': 1}, value
        boxes = value['value']['Volumes']['value']
        assert boxes == [{'type': 'int-array', 'value': [*A, *B]}], boxes
        report['cases']['survival'] = {'damage': 2, 'volume': boxes[0]['value']}

        session.restart()
        assert saved() == value
        command('gamemode survival')
        call('select', 1)
        assert selected_damage() == 2
        click(B, 'left')
        assert saved() is None and selected_damage() == 2
        assert call('block', *B)['block'] == 'minecraft:stone'
        report['cases']['restart_and_remove'] = {'damage': 2, 'restored': value, 'removed': True}

        command('gamemode creative')
        click(A)
        click(B)
        assert selected_damage() == 2 and saved() == value
        report['cases']['creative'] = {'damage': 2}

        if transfer:
            pivot = (A[0], A[1]-1, A[2])
            motor = (A[0], A[1]-2, A[2])
            command('tick freeze')
            command('clear @s')
            put(pivot, 'create:mechanical_bearing[facing=up]')
            put(motor, 'create:creative_motor[facing=up]{ScrollValue:32}')
            step(10)
            assert block(A) == block(B) == 'minecraft:air'
            assert saved() is None
            moving = saved(MOUNTED_KEYS)
            entries = moving['value']['Entries']['value']
            assert len(entries) == 1, moving
            entry = entries[0]['value']
            assert entry['Controller']['value'] == list(pivot), moving
            assert entry['Bounds']['value']['Volumes']['value'] == [
                {'type': 'int-array', 'value': [0, 0, 0, 1, 0, 0]}], moving
            # The Horizon adapter exposes zero effective RPM during frozen
            # steps. Advance the actual kinetics at a slower live tick rate.
            command('tick rate 5')
            command('tick unfreeze')
            angles = []
            for _ in range(100):
                angle = bearing_angle(pivot)
                angles.append(angle)
                if 65.0 < angle % 360.0 < 115.0 or 245.0 < angle % 360.0 < 295.0:
                    break
                call('wait', 1)
            else:
                raise AssertionError(('bearing did not reach a different snapped pose', angles))
            command('tick freeze')
            angle = bearing_angle(pivot)
            command('tick rate 20')
            put(motor, 'minecraft:air')
            step(2)
            positions = [(A[0]+dx, A[1], A[2]+dz) for dx, dz in ((1, 0), (0, 1), (-1, 0), (0, -1))]
            targets = [pos for pos in positions if block(pos) == 'minecraft:stone']
            expected = positions[-math.floor(angle / 90.0 + .5) % 4]
            assert block(A) == 'minecraft:stone' and targets == [expected], (angle, targets, expected)
            target = targets[0]
            bounds = [*map(min, zip(A, target)), *map(max, zip(A, target))]
            landed = saved()
            assert landed['value']['Volumes']['value'] == [{'type': 'int-array', 'value': bounds}], landed
            assert saved(MOUNTED_KEYS) is None
            report['cases']['rotation'] = {'mounted': moving, 'angle': angle, 'landed': bounds, 'target': target}

            put(motor, 'create:creative_motor[facing=up]{ScrollValue:32}')
            step(10)
            assert block(A) == block(target) == 'minecraft:air'
            put(A, 'minecraft:obsidian')
            put(pivot, 'minecraft:air')
            step(2)
            parked = saved(MOUNTED_KEYS)
            assert parked and saved() is None and block(A) == 'minecraft:obsidian'
            session.restart()
            command('tick freeze')
            assert saved(MOUNTED_KEYS) == parked and saved() is None
            assert block(A) == 'minecraft:obsidian'
            put(A, 'minecraft:air')
            step(3)
            assert saved(MOUNTED_KEYS) is None and block(A) == 'minecraft:stone'
            targets = [pos for pos in positions if block(pos) == 'minecraft:stone']
            assert len(targets) == 1, targets
            recovered = [*map(min, zip(A, targets[0])), *map(max, zip(A, targets[0]))]
            restored = saved()
            assert restored['value']['Volumes']['value'] == [{'type': 'int-array', 'value': recovered}], restored
            report['cases']['orphan_restart'] = {'parked': parked, 'restored': recovered}

            # An external controller is in this volume but excluded from
            # capture. Starting the bearing must leave the whole volume and
            # source block in place.
            split_pivot = (1005, 99, 59)
            split_payload = (1005, 100, 59)
            split_motor = (1005, 98, 59)
            put(split_pivot, 'create:mechanical_bearing[facing=up]')
            put(split_payload, 'minecraft:stone')
            command(f'item replace entity @s weapon.mainhand with {ITEM} 1')
            click(split_pivot)
            assert saved() == restored, saved()
            click(split_payload, vantage=(1002.5, 99, 59.5))
            before = saved()
            volumes = before['value']['Volumes']['value']
            assert len(volumes) == 2 and volumes[-1] == {
                'type': 'int-array', 'value': [*split_pivot, *split_payload]}, before
            command('clear @s')
            put(split_motor, 'create:creative_motor[facing=up]{ScrollValue:32}')
            step(10)
            assert block(split_payload) == 'minecraft:stone'
            assert saved() == before and saved(MOUNTED_KEYS) is None
            report['cases']['split_rejected'] = True

        previous = saved()['value']['Volumes']['value']
        last_a, last_b = (1006, 100, 57), (1007, 100, 57)
        put(last_a, 'minecraft:stone')
        put(last_b, 'minecraft:stone')
        command('gamemode survival')
        command(f'item replace entity @s hotbar.0 with {ITEM}[minecraft:damage=98] 1')
        command(f'item replace entity @s hotbar.1 with {ITEM} 1')
        assert selected_damage() == 98
        click(last_a)
        click(last_b)
        assert call('inventory')['hotbar'][0]['item'] is None
        call('select', 2)
        volumes = saved()['value']['Volumes']['value']
        assert selected_damage() == 1 and volumes == previous + [
            {'type': 'int-array', 'value': [*last_a, *last_b]}], volumes
        report['cases']['last_use'] = {'selected_broke': True, 'next_item_damage': 1}

        put(last_b, 'minecraft:air')
        click(last_b, 'left', air=True)
        assert selected_damage() == 1 and saved()['value']['Volumes']['value'] == previous
        report['cases']['attack_through_air'] = {'damage': 1, 'removed': True}

        if transfer:
            # The source search can reach a sticky neighbor even when the
            # selection bounds are one cell. That box joins no faces.
            single = (1003, 100, 57)
            sticky = (1004, 100, 57)
            put(single, 'minecraft:stone')
            put(sticky, 'minecraft:slime_block')
            click(single)
            assert saved()['value']['Volumes']['value'] == previous
            click(single)
            stationary = previous + [{'type': 'int-array', 'value': [*single, *single]}]
            assert saved()['value']['Volumes']['value'] == stationary
            session.restart()
            command('tick freeze')
            assert saved()['value']['Volumes']['value'] == stationary
            put((1003, 99, 57), 'create:mechanical_bearing[facing=up]')
            put((1003, 98, 57), 'create:creative_motor[facing=up]{ScrollValue:16}')
            step(10)
            assert block(single) == block(sticky) == 'minecraft:air'
            assert saved()['value']['Volumes']['value'] == stationary
            report['cases']['single_cell_survives_restart'] = True

        report['passed'] = True
    finally:
        session.stop()
        (session.scratch / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        print(session.scratch / 'result.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('game', 'resources', 'ctl'):
        parser.add_argument('--' + flag, type=Path, required=True)
    parser.add_argument('--create-jar', type=Path)
    parser.add_argument('--transfer', action='store_true')
    args = parser.parse_args()
    run(NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar, name='super-glue-native'), args.transfer)
