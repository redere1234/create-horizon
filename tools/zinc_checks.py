#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Exercise original zinc generation, mining and cooking in both games."""

import argparse
import errno
import json
from pathlib import Path
import re
import shutil
import tempfile
import time

from andesite_palette_checks import pinned
from burner_heat_java_checks import items
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from iron_palette_checks import java_inventory, setblock
from native_check_session import NativeCheckSession, wait_loaded
from reference_java import BASE as JAVA_BASE, launch as launch_java, process_alive
from reference_recipes import loot_for_horizon
from saved_block_checks import read_saved_chunk_tag


ZINC = 'create:raw_zinc'
INGOT = 'create:zinc_ingot'
ORES = ('create:zinc_ore', 'create:deepslate_zinc_ore')
X, Y, Z = 1728, 112, -928
MINE = (X + 4, Y, Z + 4)
PLAYER = (X + 4.5, Y, Z + 1.5)
FURNACES = [(X + 7 + i, Y, Z + 4 + j) for j in range(2) for i in range(3)]
ITEMS = f'@e[type=minecraft:item,x={X},y={Y-1},z={Z},dx=12,dy=6,dz=10]'


def source_checks():
    data = ROOT / 'content/data'
    for folder in ('worldgen/feature', 'worldgen/placed_feature', 'neoforge/biome_modifier'):
        path = f'create/{folder}/zinc_ore.json'
        native = json.loads((data / path).read_text())
        if folder == 'worldgen/feature':
            original = pinned('create/worldgen/configured_feature/zinc_ore.json')
            kind = native.pop('type')
            for row in native['targets']:
                row['state'] = {'Name': row['state']}
            assert dict(type=kind, config=native) == original
            continue
        original = pinned(path)
        if folder == 'worldgen/placed_feature':
            assert original['placement'].pop() == {'type': 'create:config_filter'}
        assert native == original, path
    for block in (*ORES, 'create:raw_zinc_block', 'create:zinc_block'):
        path = f'create/loot_table/blocks/{block.split(":")[1]}.json'
        assert json.loads((data / path).read_text()) == loot_for_horizon(pinned(path)), path
    for method in ('smelting', 'blasting'):
        for input_kind, tag in (('ore', 'c:ores/zinc'), ('raw_ore', 'c:raw_materials/zinc')):
            path = f'create/recipe/{method}/zinc_ingot_from_{input_kind}.json'
            original = pinned(path)
            assert original['ingredient'] == {'tag': tag}
            assert json.loads((data / path).read_text()) == dict(original, ingredient='#' + tag), path


def palette_name(entry):
    value = entry['value']
    if isinstance(value, str):
        return value
    return (value.get('Name') or value.get('id') or value[''])['value']


def generation(scratch, world):
    result = dict.fromkeys(ORES, 0)
    for dx in (-16, 0, 16):
        for dz in (-16, 0, 16):
            sections = read_saved_chunk_tag(scratch, (X + dx, Y, Z + dz), ['sections'], world)['nbt']
            for section in sections['value']:
                state_tag = section['value'].get('block_states')
                if state_tag is None:
                    continue
                block_states = state_tag['value']
                palette = [palette_name(entry) for entry in block_states['palette']['value']]
                matching = {i: name for i, name in enumerate(palette) if name in ORES}
                if not matching:
                    continue
                if len(palette) == 1:
                    result[palette[0]] += 4096
                    continue
                bits = max(4, (len(palette) - 1).bit_length())
                per_word, mask = 64 // bits, (1 << bits) - 1
                words = block_states['data']['value']
                for index in range(4096):
                    slot = (words[index // per_word] >> ((index % per_word) * bits)) & mask
                    if slot in matching:
                        result[matching[slot]] += 1
    assert all(result.values()), result
    return result


def mine(host, call, ore, tool, enchant=None):
    command = host.command
    messages = 'chat' if call else 'messages'
    command('kill ' + ITEMS)
    command('clear @s')
    command(f'item replace entity @s weapon.mainhand with minecraft:{tool}')
    if enchant:
        command(f'enchant @s minecraft:{enchant}')
    setblock(command, MINE, ore)
    target = [v + 0.5 for v in MINE]
    if call:
        call('look-at', *target)
        call('break', *MINE)
        call('wait', 4)
        assert call('block', *MINE)['block'] == 'minecraft:air', MINE
        inventory = call('inventory')['counts']
    else:
        host.call('camera', {'position': PLAYER, 'target': target})
        host.call('capture', {'name': 'zinc-mining.png', 'frames': 12})
        state = host.call('state', {})
        assert state['screen'] == 'playing' and state['hit']['pos'] == list(MINE), state
        host.call('input', {'key': 'attack', 'down': True})
        try:
            for _ in range(120):
                if host.call('block', {'pos': MINE})['id'] == 'minecraft:air':
                    break
                time.sleep(0.1)
            else:
                raise AssertionError(('Original did not break zinc', ore, tool))
        finally:
            host.call('input', {'key': 'attack', 'down': False})
        inventory = java_inventory(host)
    raw = ' '.join(command(f'data get entity {ITEMS[:-1]},limit=1] Item')[messages])
    count = dict(inventory)
    if re.search(r'\bid\s*:', raw):
        for item, quantity in items('Item:' + raw.partition(': ')[2], 'Item').items():
            count[item] = count.get(item, 0) + quantity
    assert count.pop(f'minecraft:{tool}') == 1, count
    return count


def cooking(host, call):
    command = host.command
    command('tick freeze')
    inputs = (*ORES, ZINC)
    for method, y_positions in (('furnace', FURNACES[:3]), ('blast_furnace', FURNACES[3:])):
        for pos, source in zip(y_positions, inputs, strict=True):
            setblock(command, pos, 'minecraft:' + method)
            command(f'item replace block {xyz(pos)} container.0 with {source}')
            command(f'item replace block {xyz(pos)} container.1 with minecraft:coal')
    if call:
        command('tick unfreeze')
        call('wait', 220)
        rows = [' '.join(command(f'data get block {xyz(pos)}')['chat']) for pos in FURNACES]
    else:
        rows = [row['nbt'] for row in host.snapshot(FURNACES, 220)]
    results = [items(row, 'Items') for row in rows]
    assert results == [{INGOT: 1}] * len(FURNACES), rows
    return dict(zip(('furnace', 'blast_furnace'), (results[:3], results[3:]), strict=True))


def scenario(host, scratch, world, session=None):
    command = host.command
    call = session.call if session else None
    command('gamemode spectator')
    command('tick unfreeze')
    command(f'tp @s {xyz(PLAYER)}')
    command(f'forceload add {X-16} {Z-16} {X+31} {Z+31}')
    if call:
        call('wait-ready', 120)
        wait_loaded(call, [(x, Y, z) for x in (X - 16, X + 31) for z in (Z - 16, Z + 31)])
        session.stop()
        ores = generation(scratch, world)
        session.start()
        wait_loaded(call, [MINE, FURNACES[-1]])
    else:
        host.call('capture', {'name': 'zinc-loaded.png', 'frames': 50})
        host.call('quit', {})
        deadline = time.monotonic() + 30
        while process_alive(JAVA_BASE):
            if time.monotonic() >= deadline:
                raise RuntimeError('Java reference did not close and flush its generated chunks')
            time.sleep(0.25)
        ores = generation(scratch, world)
        launch_java(JAVA_BASE, normal_world=True)
    command(f'fill {X} {Y} {Z} {X+12} {Y+4} {Z+10} minecraft:air')
    command(f'fill {X} {Y-1} {Z} {X+12} {Y-1} {Z+10} minecraft:smooth_stone')
    command(f'tp @s {xyz(PLAYER)}')
    command('gamemode survival')
    observations = {}
    for ore in ORES:
        stone = mine(host, call, ore, 'stone_pickaxe')
        iron = mine(host, call, ore, 'iron_pickaxe')
        silk = mine(host, call, ore, 'diamond_pickaxe', 'silk_touch 1')
        fortune = mine(host, call, ore, 'diamond_pickaxe', 'fortune 3')
        assert (stone, iron, silk) == ({}, {ZINC: 1}, {ore: 1}), (ore, stone, iron, silk)
        assert list(fortune) == [ZINC] and 1 <= fortune[ZINC] <= 4, fortune
        observations[ore] = dict(stone=stone, iron=iron, silk=silk, fortune=fortune)
    return dict(natural_ore=ores, mining=observations, cooking=cooking(host, call))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    source_checks()
    if not args.java and not args.game:
        return
    session = None
    if args.java:
        host = Original()
        work = Path(tempfile.mkdtemp(prefix='zinc-java-', dir=ROOT / '.local'))
        previous = host.call('state', {})
        assert previous['ready'] and previous['data_version'] == 3955, previous
    else:
        if not all((args.resources, args.ctl)):
            parser.error('Native fixture needs --resources and --ctl')
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='zinc-native', world='CreateZinc')
        work, host = session.scratch, Native(session)
    print(work, flush=True)
    try:
        if session:
            session.start()
        result = scenario(host, session.scratch if session else JAVA_BASE / 'game',
                          session.world if session else 'CreateJavaReferenceNormal',
                          session)
        if args.reference:
            reference = json.loads(args.reference.read_text())
            assert result['cooking'] == reference['cooking']
            for ore in ORES:
                for tool in ('stone', 'iron', 'silk'):
                    assert result['mining'][ore][tool] == reference['mining'][ore][tool]
        (work / 'result.json').write_text(json.dumps(dict(passed=True, create=PINS['create_revision'],
                                                        **result), indent=2) + '\n')
        print(work / 'result.json', flush=True)
    finally:
        if session:
            session.stop()
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache'):
                if folder.exists():
                    try:
                        shutil.rmtree(folder)
                    except OSError as error:
                        if error.errno != errno.ENOTEMPTY:
                            raise
                        shutil.rmtree(folder)
        else:
            try:
                if process_alive(JAVA_BASE):
                    host.command(f'forceload remove {X-16} {Z-16} {X+31} {Z+31}')
                    host.call('tick', {'frozen': previous['server']['frozen']})
            finally:
                (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


if __name__ == '__main__':
    main()
