#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Craft Deployer in Horizon and check Sand Paper use against Create 6.0.10."""
import argparse
import json
from pathlib import Path
import re

from native_check_session import NativeCheckSession, wait_loaded


PAPER = 'create:sand_paper'
RED_PAPER = 'create:red_sand_paper'
QUARTZ = 'create:rose_quartz'
POLISHED = 'create:polished_rose_quartz'
COMPONENT = 'create:sand_paper_polishing'


def run(session):
    call = session.call
    result = dict(passed=False, cases={})

    def command(text):
        return ' '.join(call('command', text)['chat'])

    def put(slot, item, count=1):
        text = command(f'item replace entity @s {slot} with {item} {count}')
        assert 'Replaced 1 slot' in text, text
        call('wait', 3)

    def inventory():
        return command('data get entity @s Inventory')

    def count(item):
        return call('inventory')['counts'].get(item, 0)

    def hold(down):
        call('mouse', 'right', 'down' if down else 'up')

    def until(predicate, observe=inventory, ticks=40):
        for _ in range(ticks):
            data = observe()
            if predicate(data):
                return data
            call('wait', 1)
        raise AssertionError(data)

    def craft(grid, item):
        call('look-at', 1005.5, 100.5, 55.5)
        call('wait', 2)
        hit = call('looking-at')['block']
        assert hit and hit['pos'] == [1005, 100, 55], (hit, call('state')['player'])
        call('mouse', 'right', 'click')
        call('wait', 4)
        screen = call('screen')
        assert screen.get('craft_size') == 3, screen
        for ingredient in dict.fromkeys(grid.values()):
            slots = call('screen')['slots']
            source = next(s['slot'] for s in slots if s.get('item') == ingredient and s['slot'] < 36)
            call('click-slot', source)
            call('wait', 2)
            for target, wanted in grid.items():
                if wanted == ingredient:
                    call('click-slot', target + 100, 'right')
                    call('wait', 2)
            if next(s['count'] for s in slots if s['slot'] == source) > list(grid.values()).count(ingredient):
                call('click-slot', source)
                call('wait', 2)
        output = next(s for s in call('screen')['slots'] if s['slot'] == 200)
        assert output.get('item') == item and output['count'] == 1, output
        call('click-slot', 200, 'shift')
        call('wait', 3)
        call('close')
        call('wait', 3)
        assert count(item) == 1, inventory()

    def damage(text, amount):
        match = re.search(r'"?minecraft:damage"?:\s*(\d+)', text)
        assert (int(match[1]) if match else 0) == amount, text

    try:
        session.start()
        command('tp @s 1002.5 100 55.5')
        wait_loaded(call, [(1002, 100, 55), (1006, 100, 59)])
        command('fill 1000 99 51 1008 99 60 minecraft:smooth_stone')
        command('fill 1000 100 51 1008 105 60 minecraft:air')
        command('setblock 1005 100 55 minecraft:crafting_table')
        command('tp @s 1002.5 100 55.5')
        call('wait', 8)
        command('gamemode survival')
        command('clear @s')
        call('select', 1)
        materials = {
            'minecraft:quartz': 1, 'minecraft:redstone': 8, 'minecraft:paper': 2,
            'minecraft:sand': 1, 'minecraft:red_sand': 1, 'create:iron_sheet': 1,
            'create:brass_sheet': 4, 'create:andesite_alloy': 1, 'create:andesite_casing': 1,
        }
        for slot, (item, amount) in enumerate(materials.items(), 9):
            put(f'inventory.{slot - 9}', item, amount)
        craft({4: 'minecraft:quartz', **{n: 'minecraft:redstone' for n in range(9) if n != 4}}, QUARTZ)
        craft({0: 'minecraft:paper', 1: 'minecraft:sand'}, PAPER)
        craft({0: 'minecraft:paper', 1: 'minecraft:red_sand'}, RED_PAPER)

        call('open-inventory')
        slots = call('screen')['slots']
        for item, target in [(PAPER, 0), (QUARTZ, 504)]:
            source = next(s['slot'] for s in slots if s.get('item') == item)
            if source != target:
                call('click-slot', source)
                call('wait', 2)
                call('click-slot', target)
                call('wait', 2)
        call('close')
        call('look-at', 1002.5, 102, 52.5)
        hold(True)
        started = until(lambda s: COMPONENT in s)
        assert POLISHED not in started, started
        finished = until(lambda s: POLISHED in s)
        hold(False)
        assert COMPONENT not in finished and QUARTZ not in finished.replace(POLISHED, ''), finished
        damage(finished, 1)

        craft({1: POLISHED, 4: 'create:iron_sheet'}, 'create:electron_tube')
        craft({1: 'create:andesite_alloy', **{i: 'create:brass_sheet' for i in (3, 4, 5, 7)}}, 'create:brass_hand')
        craft({1: 'create:electron_tube', 4: 'create:andesite_casing', 7: 'create:brass_hand'}, 'create:deployer')
        result['cases']['survival_chain'] = {'started': started, 'polished': finished, 'end': inventory()}

        command('clear @s')
        put('weapon.mainhand', PAPER)
        put('weapon.offhand', QUARTZ + '[minecraft:custom_data={marked:19}]', 2)
        call('look-at', 1002.5, 102, 52.5)
        hold(True)
        started = until(lambda s: COMPONENT in s)
        assert 'marked: 19' in started and POLISHED not in started, started
        hold(False)
        released = until(lambda s: COMPONENT not in s)
        offhand = until(lambda slot: slot.get('item') == QUARTZ and slot['count'] == 2,
                        lambda: call('inventory')['offhand'])
        assert re.search(r'\bmarked\s*:\s*19\b', offhand['components']), offhand
        assert count(QUARTZ) == 2 and POLISHED not in released, released
        damage(released, 0)
        result['cases']['release'] = {'started': started, 'after': released, 'offhand': offhand}

        command('clear @s')
        put('weapon.offhand', RED_PAPER)
        put('weapon.mainhand', QUARTZ, 2)
        hold(True)
        started = until(lambda slot: COMPONENT in slot.get('components', ''),
                        lambda: call('inventory')['offhand'])
        assert POLISHED not in started['components'], started
        finished = until(lambda s: POLISHED in s)
        hold(False)
        offhand = until(lambda slot: slot.get('damage') == 1 and COMPONENT not in slot.get('components', ''),
                        lambda: call('inventory')['offhand'])
        assert count(QUARTZ) == 1 and count(POLISHED) == 1, finished
        result['cases']['offhand'] = {'started': started, 'after': finished, 'offhand': offhand}

        command('clear @s')
        put('weapon.mainhand', PAPER)
        command('setblock 1005 100 55 minecraft:stone')
        command('summon minecraft:item 1004.5 100.5 55.5 '
                '{Item:{id:"create:rose_quartz",count:2},PickupDelay:32767s,NoGravity:1b}')
        call('look-at', 1005.5, 100.5, 55.5)
        call('wait', 4)
        hold(True)
        started = until(lambda s: COMPONENT in s)
        hold(False)
        released = until(lambda s: COMPONENT not in s and QUARTZ in s)
        items = [entry['item'] for entry in call('entities', 8, 'minecraft:item')['entities']
                 if entry['item']['item'] == QUARTZ]
        assert count(QUARTZ) == 1 and len(items) == 1 and items[0]['count'] == 1, (released, items)
        damage(released, 0)
        result['cases']['ground'] = {'started': started, 'after': released, 'remaining': items}

        command('kill @e[type=minecraft:item]')
        command('clear @s')
        put('weapon.mainhand', PAPER + '[minecraft:damage=7]')
        put('weapon.offhand', QUARTZ)
        call('look-at', 1002.5, 102, 52.5)
        hold(True)
        until(lambda s: COMPONENT in s)
        finished = until(lambda s: POLISHED in s)
        hold(False)
        assert count(PAPER) == 0 and count(POLISHED) == 1, finished
        result['cases']['last_use'] = finished

        command('clear @s')
        put('weapon.mainhand', PAPER)
        put('weapon.offhand', 'minecraft:quartz')
        hold(True)
        call('wait', 38)
        hold(False)
        unchanged = inventory()
        assert COMPONENT not in unchanged and count('minecraft:quartz') == 1 and count(POLISHED) == 0, unchanged
        damage(unchanged, 0)
        result['cases']['wrong_input'] = unchanged
        result['passed'] = True
    finally:
        session.stop()
        (session.scratch / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(session.scratch / 'result.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'resources', 'ctl'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--create-jar', type=Path)
    args = parser.parse_args()
    run(NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar, name='sandpaper-native'))
