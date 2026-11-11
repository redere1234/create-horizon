#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Replay the ordinary Deployer ghost filter with real Java block clicks."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded
from saw_filter_checks import read_filter
import reference_java as java

POS = (1230, 109, 101)
MOTOR = (1229, 109, 101)
VIEWS = {
    'south': (1230.5, 108, 104.5),
    'north': (1230.5, 108, 98.5),
    'east': (1233.5, 108, 101.5),
    'up': (1230.35, 111, 104.5),
    'down': (1230.5, 106, 101.5),
}
AXES = {
    'down': (0, -1, 0), 'up': (0, 1, 0),
    'north': (0, 0, -1), 'south': (0, 0, 1),
    'west': (-1, 0, 0), 'east': (1, 0, 0),
}
AIR = 'minecraft:air'
SAPLING = 'minecraft:oak_sapling'
MEAL = 'minecraft:bone_meal'


def block(facing='down', first=True):
    return f'create:deployer[facing={facing},axis_along_first={str(first).lower()}]'


def point(facing, side, filter_slot=True):
    return tuple(p + .5 + d * 7.5/16 - (f * 2/16 if filter_slot else 0)
                 for p, d, f in zip(POS, AXES[side], AXES[facing], strict=True))


def item_in(raw, key):
    if key == 'Filter':
        return read_filter(raw)
    found = re.search(rf'\b{key}\s*:\s*\{{([^}}]*)\}}', raw)
    if found is None or not found[1]:
        return None
    item = re.search(r'\bid\s*:\s*"([^"]+)"', found[1])
    count = re.search(r'\bcount\s*:\s*(\d+)', found[1])
    assert item and count, found[1]
    return [item[1], int(count[1])]


def java_reference():
    manifest = json.loads((java.BASE / 'manifest.json').read_text())
    assert manifest['data_version'] == 3955 and manifest['create_sha256'] == java.CREATE_SHA256
    host = Original()
    initial = host.call('state', {})
    assert initial['ready']
    work = Path(tempfile.mkdtemp(prefix='deployer-filter-java-', dir=ROOT / '.local'))
    report = dict(passed=False, source=PINS['create_revision'], cases={})

    def cmd(command):
        return host.command(command)

    def put(pos, state):
        cmd(f'setblock {xyz(pos)} {state}')

    def replace(facing='down', first=True):
        put(POS, AIR)
        put(POS, block(facing, first))
        host.call('observe_ticks', {'ticks': 3, 'positions': [POS]})

    def inventory():
        raw = ' '.join(cmd('data get entity @s SelectedItem')['messages'])
        return item_in('Selected:' + raw[raw.find('{'):], 'Selected') if '{' in raw else None

    def tap(name, held, face, facing='down', filter_slot=True):
        cmd('item replace entity @s weapon.mainhand with ' + held)
        host.call('camera', dict(position=VIEWS[face], target=point(facing, face, filter_slot),
                                 fov=40, hide_gui=True))
        host.call('capture', {'name': f'{work.name}/aim.png', 'frames': 8})
        hit = host.call('state', {})['hit']
        assert tuple(hit['pos']) == POS and hit['face'] == face, hit
        before = inventory()
        host.call('input', {'key': 'use'})
        capture = host.call('capture', {'name': f'{work.name}/{name}.png', 'frames': 8})
        host.call('input', {'key': 'use', 'down': False})
        nbt = host.call('block', {'pos': POS})['nbt']
        path = work / (name + '.png')
        if name in ('set_oak', 'opposite_bone_meal', 'vertical_face'):
            shutil.copy2(capture['path'], path)
        row = dict(hit=hit, before=before, player=inventory(), filter=item_in(nbt, 'Filter'),
                   held=item_in(nbt, 'HeldItem'), nbt=nbt, camera=capture['client'])
        report['cases'][name] = row
        return row

    try:
        host.call('tick', {'frozen': True})
        cmd('gamemode creative')
        cmd('tp @s ' + xyz(VIEWS['south']))
        cmd('forceload add 1216 96 1231 111')
        host.call('observe_ticks', {'ticks': 20, 'positions': [POS]})
        cmd('fill 1227 105 97 1235 115 106 minecraft:air')
        for name, (x,y,z) in VIEWS.items():
            put((int(x), y - 1, int(z)), 'minecraft:smooth_stone')
        cmd('clear @s')
        cmd('gamemode survival')
        replace()
        row = tap('set_oak', SAPLING + ' 9', 'south')
        assert row['before'] == row['player'] == row['filter'] == [SAPLING, 9] and not row['held'], row
        row = tap('opposite_bone_meal', MEAL + ' 7', 'north')
        assert row['before'] == row['player'] == row['filter'] == [MEAL, 7], row
        row = tap('shaft_ignored', SAPLING + ' 4', 'east')
        assert row['filter'] == [MEAL, 7] and not row['held'], row
        row = tap('wrench_preserved', 'create:wrench', 'south')
        assert row['filter'] == [MEAL, 7], row
        row = tap('clear', AIR, 'south')
        assert row['filter'] is None and row['held'] is None, row

        row = tap('front_stock', SAPLING + ' 3', 'down', filter_slot=False)
        assert row['held'] == [SAPLING, 3] and not row['player'], row
        row = tap('mismatched_filter', MEAL + ' 7', 'south')
        assert row['filter'] == [MEAL, 7] and row['held'] == [SAPLING, 3] and row['player'] == [MEAL, 7], row

        replace('down', False)
        row = tap('alternate_shaft', SAPLING + ' 8', 'east')
        assert row['filter'] == row['player'] == [SAPLING, 8] and not row['held'], row

        replace('east', False)
        row = tap('vertical_face', MEAL + ' 11', 'up', facing='east')
        assert row['filter'] == row['player'] == [MEAL, 11] and not row['held'], row
        report['passed'] = True
    finally:
        host.call('input', {'key': 'use', 'down': False})
        cmd('forceload remove 1216 96 1231 111')
        host.call('camera', dict(position=initial['position'], yaw=initial['yaw'], pitch=initial['pitch'],
                                 fov=initial['fov'], gui_scale=initial['gui_scale'], hide_gui=False))
        host.call('tick', {'frozen': False})
        (work/'result.json').write_text(json.dumps(report, indent=2)+'\n')
        (work/'transcript.json').write_text(json.dumps(host.trace, indent=2)+'\n')
        print(work/'result.json', flush=True)


def native(session, reference):
    report = dict(passed=False, source=PINS['create_revision'], cases={})
    path = session.scratch/'result.json'
    try:
        with session:
            call = session.call

            def cmd(command):
                return ' '.join(call('command', command)['chat'])

            def put(pos, state):
                cmd(f'setblock {xyz(pos)} {state}')

            def read():
                nbt = cmd('data get block ' + xyz(POS))
                raw = cmd('data get entity @s SelectedItem')
                player = item_in('Selected:' + raw[raw.find('{'):], 'Selected') if '{' in raw else None
                return dict(filter=item_in(nbt, 'Filter'), held=item_in(nbt, 'HeldItem'),
                            player=player, nbt=nbt)

            def replace(facing='down', first=True):
                put(POS, AIR)
                put(POS, block(facing, first))
                call('wait', 6)

            cmd('tp @s ' + xyz(VIEWS['south']))
            wait_loaded(call, [POS])
            cmd('gamemode creative')
            cmd('fill 1227 105 97 1235 115 106 minecraft:air')
            for x, y, z in VIEWS.values():
                put((int(x), y - 1, int(z)), 'minecraft:smooth_stone')
            cmd('clear @s')
            cmd('gamemode survival')
            call('options-set', 'fov', 40)
            call('options-set', 'bobView', 'false')
            call('key', 'f1', 'tap')
            replace()
            for name, expected in reference.items():
                if name == 'alternate_shaft':
                    replace('down', False)
                if name == 'vertical_face':
                    replace('east', False)
                input_item = expected['before']
                held = AIR if input_item is None else f'{input_item[0]} {input_item[1]}'
                cmd('item replace entity @s weapon.mainhand with ' + held)
                pose = expected['camera']
                cmd('tp @s ' + xyz(pose['position']))
                call('look', pose['yaw'], pose['pitch'])
                call('wait', 7)
                hit = call('looking-at')['block']
                assert hit and hit['pos'] == list(POS) and hit['face'] == expected['hit']['face'], hit
                call('mouse', 'right', 'click')
                call('wait', 8)
                row = read()
                assert all(row[k] == expected[k] for k in ('filter', 'held', 'player')), (name, row, expected)
                if name in ('set_oak', 'opposite_bone_meal', 'vertical_face'):
                    image = session.scratch/(name+'.png')
                    call('screenshot', image)
                    row['image'] = str(image)
                report['cases'][name] = row

            session.restart()
            wait_loaded(call, [POS])
            assert read()['filter'] == [MEAL, 11]
            report['cold_reload'] = read()
        report['passed'] = True
    finally:
        path.write_text(json.dumps(report, indent=2)+'\n')
        print(path, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for arg in ('game', 'resources', 'ctl', 'jar', 'reference'):
        parser.add_argument('--'+arg, type=Path)
    args = parser.parse_args()
    if args.java:
        java_reference()
        return
    if not all((args.game, args.resources, args.ctl, args.reference)):
        parser.error('Specify --java or --game, --resources, --ctl and --reference')
    report = json.loads(args.reference.read_text())
    assert report['passed'] and report['source'] == PINS['create_revision']
    native(NativeCheckSession(args.game, args.resources, args.ctl, args.jar,
                               name='deployer-filter', graphics=True, world='DeployerFilter',
                               size=(1710, 1045)), report['cases'])


if __name__ == '__main__':
    main()
