#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Observe original Sand Paper reservation, release, completion and item pickup."""
import json
from pathlib import Path
import tempfile
import time

from chain_drive_checks import Original
from common import PINS, ROOT


COMPONENT = 'create:sand_paper_polishing'
QUARTZ = 'create:rose_quartz'
POLISHED = 'create:polished_rose_quartz'


def run():
    host = Original()
    work = Path(tempfile.mkdtemp(prefix='sandpaper-java-', dir=ROOT / '.local'))
    result = dict(create=PINS['create_revision'], passed=False, cases={})

    def command(text):
        return host.command(text)['messages']

    def inventory():
        return ' '.join(command('data get entity @s Inventory'))

    def using(down):
        host.call('input', {'key': 'use', 'down': down})

    def wait_until(predicate):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            text = inventory()
            if predicate(text):
                return text
            time.sleep(.04)
        raise AssertionError(text)

    def put(hand, item):
        assert command(f'item replace entity @s weapon.{hand} with {item}'), item

    old = host.call('state', {})
    assert old['ready'] and old['data_version'] == 3955
    try:
        host.call('tick', {'frozen': True})
        command('gamemode creative')
        command('tp @s 1031.5 100 140.5')
        command('forceload add 1024 128 1055 159')
        host.call('observe_ticks', {'ticks': 25, 'positions': [(1031, 100, 140)]})
        command('kill @e[type=minecraft:item,x=1027,y=98,z=137,dx=10,dy=6,dz=8]')
        command('fill 1027 100 137 1037 105 145 minecraft:air')
        command('fill 1027 99 137 1037 99 145 minecraft:stone')
        command('clear @s')
        command('gamemode survival')
        command('tick rate 8')
        host.call('tick', {'frozen': False})
        host.call('camera', {'position': [1031.5, 100, 140.5], 'target': [1035.5, 101.5, 140.5]})

        put('mainhand', 'create:sand_paper 1')
        put('offhand', QUARTZ + '[minecraft:custom_name=\'"Marked Quartz"\'] 2')
        using(True)
        reserved = wait_until(lambda text: COMPONENT in text)
        assert 'Marked Quartz' in reserved and POLISHED not in reserved, reserved
        using(False)
        released = wait_until(lambda text: COMPONENT not in text and 'count: 2' in text and QUARTZ in text)
        assert 'Marked Quartz' in released and 'minecraft:damage' not in released, released
        result['cases']['release'] = {'reserved': reserved, 'after': released}

        command('clear @s')
        put('offhand', 'create:red_sand_paper 1')
        put('mainhand', QUARTZ + ' 2')
        using(True)
        reserved = wait_until(lambda text: COMPONENT in text)
        finished = wait_until(lambda text: POLISHED in text)
        using(False)
        assert COMPONENT not in finished and '"minecraft:damage": 1' in finished, finished
        assert QUARTZ in finished, finished
        result['cases']['offhand'] = {'reserved': reserved, 'after': finished}

        command('clear @s')
        put('mainhand', 'create:sand_paper 1')
        command('setblock 1034 100 140 minecraft:stone')
        command('summon minecraft:item 1033.5 100.5 140.5 '
                '{Item:{id:"create:rose_quartz",count:2},PickupDelay:32767s,NoGravity:1b}')
        host.call('camera', {'position': [1031.5, 100, 140.5], 'target': [1034.5, 100.5, 140.5]})
        using(True)
        reserved = wait_until(lambda text: COMPONENT in text)
        using(False)
        released = wait_until(lambda text: COMPONENT not in text and QUARTZ in text)
        items = host.call('entities', {'center': [1033.5, 100.5, 140.5], 'radius': 4})['entities']
        items = [item for item in items if item['type'] == 'minecraft:item' and QUARTZ in item['nbt']]
        assert len(items) == 1 and 'count:1' in items[0]['nbt'], items
        result['cases']['ground'] = {'reserved': reserved, 'after': released, 'remaining': items}
        result['passed'] = True
    finally:
        using(False)
        command('tick rate 20')
        host.call('tick', {'frozen': old['server']['frozen']})
        (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
        print(work / 'result.json')


if __name__ == '__main__':
    run()
