#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Open and edit a contraption's chest and barrel through each real client."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile
import time

from bearing_barrel_checks import pose
from bearing_mounted_pair_checks import BANK_ITEMS, Rig
from bearing_repeat_checks import AIR, CLUTCH, MOTOR, POWER, ROOM, SOUTH, setup
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded


RIG = Rig(130, ('chest', 'barrel'), SOUTH)
FLOOR = '1155 129 242 1165 129 253'
CENTRE = (1160.5, 130, 247.5)
CAMERAS = ((1157.5, 130, 247.5), (1160.5, 130, 250.5))
TITLES = ('Moving Chest', 'Moving Barrel')
SLOTS = ((0, 1), (3, 4))


def prepare(command):
    command('gamemode creative')
    command('clear @s')
    setup(command, lambda pos, state: command(f'setblock {xyz(pos)} {state}'))
    command(f'fill {FLOOR} minecraft:stone replace air')
    command(f'data merge block {xyz(RIG.pivot)} {{ScrollValue:2}}')
    command(f'data merge block {xyz(MOTOR)} {{ScrollValue:1}}')


def powered(command, enabled):
    command(f'setblock {xyz(POWER)} ' + (AIR if enabled else 'minecraft:redstone_block'))


def target(index):
    return tuple(value + .5 for value in RIG.sources[index])


def contents(command):
    observations = []
    for index, pos in enumerate(RIG.sources):
        nbt = command('data get block ' + xyz(pos))
        pairs = re.findall(r'Slot:\s*(\d+)b|count:\s*(\d+)', nbt)
        assert pairs, (pos, nbt)
        values = [int(a or b) for a, b in pairs]
        # Normalize field order between the two SNBT writers.
        if pairs[0][0]:
            slots = dict(zip(values[::2], values[1::2], strict=True))
        else:
            slots = dict(zip(values[1::2], values[::2], strict=True))
        old, new = SLOTS[index]
        count = BANK_ITEMS[index][0][2]
        assert slots == {old: count // 2, new: (count + 1) // 2, 26: BANK_ITEMS[index][1][2]}, nbt
        assert ('first_bank:31' if index == 0 else '"minecraft:damage":37') in nbt.replace(' ', ''), nbt
        observations.append(sorted([slot, value] for slot, value in slots.items()))
    return observations


def java(work):
    host = Original()
    if host.call('state', {}).get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
    command = lambda text: ' '.join(host.command(text)['messages'])
    host.call('camera', {'position': CENTRE, 'target': target(0), 'gui_scale': 2})
    command('forceload add 1152 240 1167 255')
    host.call('tick', {'frozen': True, 'step': 10})
    prepare(command)
    host.call('tick', {'step': 4})
    powered(command, True)
    host.call('tick', {'step': 9})
    powered(command, False)
    host.call('tick', {'step': 4})
    assert pose(command('data get block ' + xyz(RIG.pivot)))[0] == 1

    def screen(wanted):
        for _ in range(30):
            state = host.call('state', {})
            if state['screen'] == wanted:
                return state
            time.sleep(.05)
        raise AssertionError((wanted, state))

    def click(index, button):
        width, height = screen('ContainerScreen')['gui_size']
        # AbstractContainerScreen image is 176 x 168 for a 3-row ChestMenu.
        x, y = (width - 176) // 2 + 16 + index * 18, (height - 168) // 2 + 26
        host.call('input', {'kind': 'mouse', 'x': x, 'y': y, 'button': button})
        time.sleep(.12)

    try:
        host.call('tick', {'frozen': False})
        for index, title in enumerate(TITLES):
            host.call('camera', {'position': CAMERAS[index], 'target': target(index)})
            host.call('input', {'kind': 'key', 'key': 'use'})
            assert screen('ContainerScreen')['screen_title'] == title
            image = host.call('capture', {'name': f'mounted-container-{index}.png'})
            shutil.copy2(image['path'], work / f'container-{index}.png')
            old, new = SLOTS[index]
            click(old, 1)
            click(new, 0)
            host.call('input', {'kind': 'escape'})
            screen('playing')
        powered(command, True)
        host.call('camera', {'position': CAMERAS[0], 'target': target(0)})
        host.call('input', {'kind': 'key', 'key': 'use'})
        screen('ContainerScreen')
        before = pose(command('data get block ' + xyz(RIG.pivot)))[1]
        time.sleep(.35)
        assert pose(command('data get block ' + xyz(RIG.pivot)))[1] > before
        powered(command, False)
        host.call('input', {'kind': 'escape'})
        screen('playing')
        host.call('camera', {'position': CAMERAS[0], 'target': target(0)})
        host.call('input', {'kind': 'key', 'key': 'use'})
        screen('ContainerScreen')
        command(f'setblock {xyz(RIG.pivot)} minecraft:air')
        screen('playing')
        return {'titles': list(TITLES), 'landed_slots': contents(command), 'auto_close': True,
                'while_rotating': True}
    finally:
        if host.call('state', {})['screen'] == 'ContainerScreen':
            host.call('input', {'kind': 'escape'})
        command('fill ' + ROOM + ' ' + AIR)
        command('forceload remove 1152 240 1167 255')
        host.call('tick', {'frozen': True})


def native(session, expected):
    call = session.call
    command = lambda text: ' '.join(call('command', text)['chat'])

    def step(count):
        command(f'tick step {count}')
        call('wait', count + 3)

    def screen(wanted):
        for _ in range(12):
            result = call('screen')
            if result['screen'] == wanted:
                return result
            call('wait', 1)
        raise AssertionError((wanted, result, call('state')))

    def aim(index):
        command('tp @s ' + xyz(CAMERAS[index]))
        call('look-at', *target(index))
        call('wait', 2)

    def open_bank(index):
        aim(index)
        call('mouse', 'right', 'click')
        shown = screen('container')
        assert ''.join(span['text'] for span in shown['title']) == expected['titles'][index], shown

    def observed_slot(slot):
        return next(row for row in screen('container')['slots'] if row['slot'] == slot + 300)

    with session:
        command('tp @s ' + xyz(CENTRE))
        wait_loaded(call, [RIG.pivot, CLUTCH, *RIG.sources])
        command('tick freeze')
        prepare(command)
        step(4)
        powered(command, True)
        step(9)
        powered(command, False)
        step(4)
        assert pose(command('data get block ' + xyz(RIG.pivot)))[0] == 1
        command('tick unfreeze')
        for index in range(len(TITLES)):
            open_bank(index)
            call('screenshot', session.scratch / f'container-{index}.png')
            old, new = SLOTS[index]
            call('click-slot', old + 300, 'right')
            call('wait', 4)
            assert observed_slot(old)['count'] == BANK_ITEMS[index][0][2] // 2
            assert call('inventory')['carried']['count'] == (BANK_ITEMS[index][0][2] + 1) // 2
            call('click-slot', new + 300)
            call('close')
            screen('playing')
            open_bank(index)
            assert observed_slot(new)['count'] == (BANK_ITEMS[index][0][2] + 1) // 2
            call('close')
            screen('playing')
        powered(command, True)
        open_bank(0)
        before = pose(command('data get block ' + xyz(RIG.pivot)))[1]
        call('wait', 6)
        assert pose(command('data get block ' + xyz(RIG.pivot)))[1] > before
        powered(command, False)
        call('close')
        screen('playing')
        call('save')
        session.restart()
        wait_loaded(call, [RIG.pivot, *RIG.sources])
        aim(0)
        call('screenshot', session.scratch / 'after-cold-restart.png')
        command('setblock 1158 131 247 minecraft:stone')
        aim(0)
        call('mouse', 'right', 'click')
        call('wait', 4)
        screen('playing')
        command('setblock 1158 131 247 minecraft:air')
        open_bank(0)
        call('click-slot', 300, 'right')
        call('wait', 4)
        assert call('inventory')['carried']['count'] == 2
        command('tp @s 1151.5 130 247.5')
        screen('playing')
        call('wait', 4)
        inventory = call('inventory')
        assert inventory['carried'] is None and inventory['counts'].get('minecraft:diamond') == 2, inventory
        source = next(row['slot'] for row in inventory['hotbar'] + inventory['main']
                      if row['item'] == 'minecraft:diamond')
        open_bank(0)
        call('click-slot', source)
        call('wait', 4)
        call('click-slot', 300)
        call('wait', 4)
        assert observed_slot(0)['count'] == 3
        command(f'setblock {xyz(RIG.pivot)} minecraft:air')
        screen('playing')
        landed = contents(command)
        assert landed == expected['landed_slots'], landed

        command(f'setblock {xyz(RIG.pivot)} create:mechanical_bearing[facing=up]{{ScrollValue:2}}')
        powered(command, True)
        call('wait', 6)
        powered(command, False)
        call('wait', 5)
        command('gamemode survival')
        open_bank(0)
        call('click-slot', 300, 'right')
        call('wait', 4)
        assert call('inventory')['carried']['count'] == 2
        command('kill @s')
        screen('dead')
        call('wait', 26)
        dropped = [row['item']['count'] for row in call('entities', 8, 'minecraft:item')['entities']
                   if row['item']['item'] == 'minecraft:diamond']
        assert dropped == [2], dropped
        return {'titles': expected['titles'], 'landed_slots': landed, 'auto_close': True,
                'cold_restart': True, 'terrain_occlusion': True, 'range_close_returns_cursor': True,
                'while_rotating': expected['while_rotating'], 'click_then_close': True,
                'death_drops_cursor': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='mounted-menu-java-', dir=ROOT / '.local'))
        result = java(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon runs require --game, --resources, --ctl and --reference')
        expected = json.loads(args.reference.read_text())
        assert expected['passed'] and expected['create'] == PINS['create_revision'], expected
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='mounted-menu-native', world='CreateMountedMenu')
        session.env['CREATE_TRACE_CONTRAPTION_FRAMES'] = '1'
        work = session.scratch
        print(work, flush=True)
        try:
            result = native(session, expected)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    result.update(passed=True, create=PINS['create_revision'])
    output = work / 'result.json'
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(output)


if __name__ == '__main__':
    main()
