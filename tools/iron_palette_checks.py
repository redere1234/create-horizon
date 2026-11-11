#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare the two iron building blocks in actual Java Create and Horizon."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from andesite_palette_checks import imported_assets, menu_input, pinned
from burner_heat_java_checks import field, items
from catalog import IRON_PALETTE
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded


X, Y, Z = 1328, 118, 420
STONECUTTER = (X, Y, Z)
PLAYER = (X + 0.5, Y, Z - 2.5)
IRON = 'minecraft:iron_ingot'
WRENCH = 'create:wrench'
INDUSTRIAL, WEATHERED = (f'create:{name}' for name in IRON_PALETTE)
RECIPES = [f'{block}_from_ingots_iron_stonecutting' for block in (INDUSTRIAL, WEATHERED)]
DEPOT = (X + 6, Y, Z + 4)
FLOOR = (X - 3, Y - 1, Z - 4, X + 8, Y - 1, Z + 6)
ROOM = (X - 3, Y, Z - 4, X + 8, Y + 4, Z + 6)


def source_checks():
    for block, recipe in zip((INDUSTRIAL, WEATHERED), RECIPES, strict=True):
        path = f'create/recipe/{recipe.split(":")[1]}.json'
        original = pinned(path)
        assert original == {'type': 'minecraft:stonecutting', 'ingredient': {'tag': 'c:ingots/iron'},
                            'result': {'count': 2, 'id': block}}, original
        assert json.loads((ROOT / 'content/data' / path).read_text()) == dict(original, ingredient='#c:ingots/iron')
    assert pinned('create/recipe/splashing/industrial_iron_block.json') == {
        'type': 'create:splashing', 'ingredients': [{'item': INDUSTRIAL}], 'results': [{'id': WEATHERED}],
    }


def fill(command, region, block):
    command(f'fill {xyz(region)} {block}')


def setblock(command, pos, block):
    command(f'setblock {xyz(pos)} {block}')


def aim(pos):
    return [v + 0.5 for v in pos]


def java_click(host, pos, sneaking=False):
    host.call('camera', {'position': PLAYER, 'target': aim(pos)})
    host.call('capture', {'name': 'iron-aim.png', 'frames': 16})
    assert host.call('state', {})['hit']['pos'] == list(pos), pos
    if sneaking:
        host.call('input', {'key': 'shift', 'down': True})
    try:
        host.call('input', {'key': 'use', 'down': True})
        host.call('capture', {'name': 'iron-use.png', 'frames': 16})
    finally:
        host.call('input', {'key': 'use', 'down': False})
        if sneaking:
            host.call('input', {'key': 'shift', 'down': False})


def native_click(call, pos, sneaking=False):
    call('look-at', *aim(pos))
    assert call('looking-at')['block']['pos'] == list(pos), pos
    if sneaking:
        call('key', 'shift', 'down')
    try:
        call('mouse', 'right', 'click')
        call('wait', 3)
    finally:
        if sneaking:
            call('key', 'shift', 'up')


def java_inventory(host):
    raw = ' '.join(host.command('data get entity @s Inventory')['messages'])
    return items('Inventory:' + raw.partition(': ')[2], 'Inventory')


def java_stonecutter(host, block, index):
    host.command(f'item replace entity @s weapon.mainhand with {IRON}')
    slot = int(''.join(host.command('data get entity @s SelectedItemSlot')['messages']).split()[-1])
    java_click(host, STONECUTTER)
    state = host.call('state', {})
    assert state['screen'] == 'StonecutterScreen', state
    width, height = state['gui_size']
    left, top = (width - 176) // 2, (height - 166) // 2

    def mouse(x, y):
        host.call('input', {'kind': 'mouse', 'button': 0, 'x': left + x, 'y': top + y})

    mouse(16 + 18 * slot, 150)
    mouse(28, 41)
    mouse(60 + index * 16, 22)
    mouse(151, 41)
    mouse(16 + 18 * slot, 150)
    host.call('input', {'kind': 'escape'})
    count = java_inventory(host)
    assert count == {block: 2}, count
    return count


def native_stonecutter(host, call, block, recipe):
    host.command(f'item replace entity @s weapon.mainhand with {IRON}')
    call('interact', *STONECUTTER)
    recipes = menu_input(call, IRON, set(RECIPES))
    index = recipes.index(recipe)
    x, y, _, _ = next(widget['bounds'] for widget in call('ui')['widgets'] if widget['id'] == 'slot-600')
    call('click-at', x - 20 + 60 + index % 4 * 16, y - 33 + 22 + index // 4 * 18)
    assert call('menu')['info']['result'] == f'{block} x2'
    call('click-slot', 650, 'shift')
    call('wait', 3)
    call('close')
    call('wait', 3)
    count = call('inventory')['counts']
    assert count == {block: 2}, count
    return count


def scenario(host, call=None):
    command = host.command
    command('gamemode survival')
    command('tick unfreeze')
    fill(command, FLOOR, 'minecraft:smooth_stone')
    fill(command, ROOM, 'minecraft:air')
    command(f'tp @s {xyz(PLAYER)}')
    click = (lambda pos, sneak=False: native_click(call, pos, sneak)) if call else (
        lambda pos, sneak=False: java_click(host, pos, sneak))
    outcome = {}
    for index, (block, recipe) in enumerate(zip((INDUSTRIAL, WEATHERED), RECIPES, strict=True)):
        command('clear @s')
        setblock(command, STONECUTTER, 'minecraft:stonecutter')
        crafted = native_stonecutter(host, call, block, recipe) if call else java_stonecutter(host, block, index)
        command('clear @s')
        command(f'item replace entity @s weapon.mainhand with {WRENCH}')
        setblock(command, STONECUTTER, block)
        click(STONECUTTER)
        read = (lambda: call('block', *STONECUTTER)['block']) if call else (
            lambda: host.call('block', {'pos': STONECUTTER})['id'])
        assert read() == block
        click(STONECUTTER, True)
        assert read() == 'minecraft:air'
        inventory = call('inventory')['counts'] if call else java_inventory(host)
        assert inventory == {WRENCH: 1, block: 1}, inventory
        outcome[block] = {'stonecutting': crafted, 'picked_up': inventory[block]}

    # Seed the ordinary Depot from its canonical held stack, then let the
    # original fan and the port process it with ordinary running ticks.
    command('gamemode creative')
    command('tick freeze')
    for pos, block in (
        ((X + 2, Y + 1, Z + 4), 'create:creative_motor[facing=east]{ScrollValue:256}'),
        ((X + 3, Y + 1, Z + 4), 'create:encased_fan[facing=east]'),
        ((X + 4, Y + 1, Z + 4), 'minecraft:oak_fence[waterlogged=true]'),
        (DEPOT, 'create:depot'),
    ):
        setblock(command, pos, block)
    command(f'data merge block {xyz(DEPOT)} {{HeldItem:{{Item:{{id:"{INDUSTRIAL}",count:2}}}}}}')
    if call:
        command('tick unfreeze')
        call('wait', 185)
        raw = ' '.join(command(f'data get block {xyz(DEPOT)}')['chat'])
    else:
        raw = host.snapshot([DEPOT], 185)[0]['nbt']
    outcome['washing'] = items(field(raw, 'HeldItem'), 'Item')
    assert outcome['washing'] == {WEATHERED: 2}, raw
    return outcome


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    source_checks()
    if not args.java and not args.game:
        return
    session = None
    if args.java:
        host = Original()
        work = Path(tempfile.mkdtemp(prefix='iron-palette-java-', dir=ROOT / '.local'))
        previous = host.call('state', {})
        assert previous['ready'] and previous['data_version'] == 3955, previous
    else:
        if not all((args.resources, args.ctl, args.reference)):
            parser.error('Native comparison requires --resources, --ctl and --reference')
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='iron-palette-native', world='CreateIronPalette')
        work, host = session.scratch, Native(session)
    print(work, flush=True)
    try:
        if session:
            session.start()
            host.command(f'tp @s {xyz(PLAYER)}')
            wait_loaded(session.call, [STONECUTTER, DEPOT])
        else:
            host.command(f'tp @s {xyz(PLAYER)}')
            host.call('capture', {'name': 'iron-loaded.png', 'frames': 20})
        outcome = scenario(host, session.call if session else None)
        receipt = {'passed': True, 'create': PINS['create_revision'], 'observations': outcome}
        if session:
            assert outcome == json.loads(args.reference.read_text())['observations']
            session.stop()
            if args.create_jar:
                receipt['original_palette_files'] = imported_assets(session, args.create_jar)
        (work / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(work / 'result.json')
    finally:
        if session:
            session.stop()
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                if folder.exists():
                    shutil.rmtree(folder)
        else:
            host.call('tick', {'frozen': previous['server']['frozen']})
            (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


if __name__ == '__main__':
    main()
