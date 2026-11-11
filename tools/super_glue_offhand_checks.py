#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Replay pinned Java Super Glue in the offhand during ordinary block placement."""

import argparse
import json
from pathlib import Path
import re

from chain_drive_checks import Original, xyz
from common import PINS
import reference_java as java

AIR = 'minecraft:air'
STONE = 'minecraft:stone'
GRASS = 'minecraft:short_grass'
GLUE = 'create:super_glue'
SUPPORT = (1257, 105, 105)
TARGET = (1258, 105, 105)
VIEW = (1261.3, 104, 105.5)
WIDE = (1263, 105, 109)
WIDE_TARGET = (1264, 105, 109)


def place(position, state):
    return f'setblock {xyz(position)} {state}'


def run(output):
    manifest = json.loads((java.BASE / 'manifest.json').read_text())
    assert manifest['data_version'] == 3955 and manifest['create_sha256'] == java.CREATE_SHA256
    host = Original()
    initial = host.call('state', {})
    assert initial['ready']
    report = dict(passed=False, source=PINS['create_revision'], cases={})

    def cmd(command):
        return host.command(command)

    def state(pos):
        return host.call('block', {'pos': pos})['id']

    def observe():
        entities = host.call('entities', {'center': TARGET, 'radius': 14})['entities']
        return [entity for entity in entities if entity['type'] == GLUE]

    def damage():
        raw = ' '.join(cmd('data get entity @s Inventory')['messages'])
        _, separator, glue = raw.partition('Slot: -106b,')
        if not separator:
            return None
        assert GLUE in glue, raw
        value = re.search(r'"minecraft:damage":\s*(\d+)', glue)
        return int(value[1]) if value else 0

    def equip(*, creative=False, wear=0):
        cmd('clear @s')
        cmd('gamemode ' + ('creative' if creative else 'survival'))
        cmd('item replace entity @s weapon.mainhand with minecraft:stone 16')
        if wear is not None:
            data = f'[minecraft:damage={wear}]' if wear else ''
            cmd('item replace entity @s weapon.offhand with ' + GLUE + data)

    def tap(name, *, position=VIEW, aimed=SUPPORT, face='east'):
        target = (aimed[0] + 0.5, 105.62, aimed[2] + 0.5)
        host.call('camera', dict(position=position, target=target, hide_gui=False))
        host.call('capture', {'name': f'{output.name}/{name}-aim.png', 'frames': 8})
        hit = host.call('state', {})['hit']
        assert hit and tuple(hit['pos']) == aimed and hit['face'] == face, hit
        host.call('input', {'key': 'use'})
        host.call('capture', {'name': f'{output.name}/{name}.png', 'frames': 8})
        host.call('input', {'key': 'use', 'down': False})
        return hit

    def check(name, block, expected, count, wear, *, pos=TARGET, **aim):
        hit = tap(name, **aim)
        entities = observe()
        actual = dict(block=state(pos), entities=entities, damage=damage(), hit=hit)
        report['cases'][name] = actual
        assert actual['block'] == block and len(entities) == count and actual['damage'] == wear, actual
        if expected is not None:
            assert entities[-1]['position'] == expected, actual

    try:
        host.call('tick', {'frozen': True})
        cmd('gamemode creative')
        cmd('tp @s ' + xyz(VIEW))
        cmd('forceload add 1248 96 1279 111')
        host.call('observe_ticks', {'ticks': 20, 'positions': [TARGET, WIDE_TARGET]})
        cmd('fill 1252 104 102 1269 110 111 minecraft:air')
        cmd('fill 1252 103 102 1269 103 111 minecraft:smooth_stone')
        cmd('kill @e[type=create:super_glue,distance=..14]')
        cmd(place(SUPPORT, STONE))
        equip()
        check('survival', STONE, [1258.0, 105.0, 105.5], 1, 1)
        cmd(place(TARGET, AIR))
        check('already_glued', STONE, [1258.0, 105.0, 105.5], 1, 1)
        cmd('kill @e[type=create:super_glue,distance=..14]')
        cmd(place(TARGET, AIR))
        equip(creative=True)
        check('creative', STONE, [1258.0, 105.0, 105.5], 1, 0)
        cmd('kill @e[type=create:super_glue,distance=..14]')
        cmd(place(TARGET, AIR))
        equip(wear=98)
        check('breaks_offhand', STONE, [1258.0, 105.0, 105.5], 1, None)
        cmd('kill @e[type=create:super_glue,distance=..14]')
        cmd(place(TARGET, AIR))
        cmd(place(SUPPORT, 'create:mechanical_drill[facing=east]'))
        equip()
        check('invalid_drill_front', STONE, None, 0, 0)
        cmd(place(SUPPORT, AIR))
        cmd(place((1258, 104, 105), 'minecraft:dirt'))
        cmd(place(TARGET, GRASS))
        cmd(place((1256, 105, 105), STONE))
        equip(wear=None)
        check('replace_plant_control', STONE, None, 0, None, aimed=TARGET)
        cmd(place(TARGET, GRASS))
        equip()
        check('nonadjacent_cancels_placement', GRASS, None, 0, 0, aimed=TARGET)
        cmd(place((1256, 105, 105), AIR))
        check('miss_allows_placement', STONE, None, 0, 0, aimed=TARGET)

        cmd(place(WIDE, STONE))
        equip()
        check('crosses_column_boundary', STONE, [1264.0, 105.0, 109.5], 1, 1,
              pos=WIDE_TARGET, position=(1267.4, 104, 109.5), aimed=WIDE)
        report['passed'] = True
    finally:
        host.call('input', {'key': 'use', 'down': False})
        cmd('forceload remove 1248 96 1279 111')
        host.call('camera', dict(position=initial['position'], yaw=initial['yaw'], pitch=initial['pitch'],
                                 fov=initial['fov'], gui_scale=initial['gui_scale'], hide_gui=False))
        host.call('tick', {'frozen': False})
        (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        (output / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
        print(output / 'result.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    run(args.output.resolve())
