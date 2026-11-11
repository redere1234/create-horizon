#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Exercise the ordinary recipe-filter slot on all upward Saw poses."""
import argparse
import json
from pathlib import Path
import re

from chain_drive_checks import xyz
from common import PINS
from native_check_session import NativeCheckSession, wait_loaded


SAW = (1160, 103, 101)
FEET = (1160.5, 105.0, 104.5)
OUTSIDE = (1160.1, 103.75, 101.1)
ABOVE = (1160, 104, 101)


def center(first, flipped):
    side = (-3 if flipped else 3) / 16
    return (SAW[0] + .5 + (side if first else 0), SAW[1] + 12.5 / 16,
            SAW[2] + .5 + (0 if first else side))


def saw(first, flipped, facing='up'):
    return (f'create:mechanical_saw[facing={facing},axis_along_first={str(first).lower()},'
            f'flipped={str(flipped).lower()}]')


def read_filter(nbt):
    stored = re.search(r'\bFilter:\s*\{([^}]*)\}', nbt)
    if stored is None or not stored[1]:
        return None
    item = re.search(r'\bid:\s*"([a-z_:]+)"', stored[1])
    count = re.search(r'\bcount:\s*(\d+)', stored[1])
    assert item and count, stored[1]
    return [item[1], int(count[1])]


def native(session, reference, report):
    if reference:
        assert reference['passed'] and reference['create'] == PINS['create_revision']
    call = session.call

    def cmd(command):
        return ' '.join(call('command', command)['chat'])

    def put(pos, state):
        return cmd(f'setblock {xyz(pos)} {state}')

    def hand(state):
        cmd(f'item replace entity @s weapon.mainhand with {state}')
        call('wait', 5)

    def nbt():
        return cmd(f'data get block {xyz(SAW)}')

    def aim(point):
        cmd('tp @s ' + xyz(FEET))
        call('wait', 5)
        call('look-at', *point)
        call('wait', 4)
        hit = call('looking-at')['block']
        assert hit and hit['pos'] == list(SAW), hit
        return hit

    def click():
        call('mouse', 'right', 'click')
        call('wait', 8)

    def snap(name):
        call('screenshot', session.scratch / f'{name}.png')

    with session:
        cmd('gamemode creative')
        cmd('tp @s ' + xyz(FEET))
        wait_loaded(call, [SAW])
        cmd('fill 1158 102 99 1163 106 106 minecraft:air')
        put((1160, 104, 104), 'minecraft:smooth_stone')
        cmd('gamemode survival')
        for first, flipped in [(False, False), (False, True), (True, False), (True, True)]:
            key = f'{int(first)}-{int(flipped)}'
            put(SAW, 'minecraft:air')
            put(SAW, saw(first, flipped))
            hand('minecraft:oak_planks 9')
            at = center(first, flipped)
            hit = aim(at)
            snap(key + '-empty')
            click()
            after = nbt()
            assert read_filter(after) == ['minecraft:oak_planks', 9], after
            assert re.search(r'\bFilterAmount:\s*64\b', after)
            assert re.search(r'\bUpTo:\s*1b\b', after)
            held = cmd('data get entity @s SelectedItem')
            assert 'minecraft:oak_planks' in held and re.search(r'\bcount:\s*9\b', held), held
            if reference:
                original = reference['cases'][key]
                assert read_filter(original['current']['nbt']) == read_filter(after), (original, after)
                assert hit['face'] == original['before']['hit']['face'], (original, hit)
            snap(key + '-filled')
            report[key] = dict(hit=hit, filter=read_filter(after), held=held)

        at = center(True, True)
        hand('create:wrench')
        aim(at)
        before = call('block', *SAW)['state']
        click()
        assert call('block', *SAW)['state'] == before
        assert read_filter(nbt()) == ['minecraft:oak_planks', 9]
        hand('minecraft:stick 7')
        aim(at)
        click()
        assert read_filter(nbt()) == ['minecraft:stick', 7]
        snap('replacement-stick')

        hand('minecraft:dirt 3')
        assert aim(OUTSIDE)['face'] == 'up'
        click()
        assert call('block', *ABOVE)['block'] == 'minecraft:dirt'
        assert read_filter(nbt()) == ['minecraft:stick', 7]
        put(ABOVE, 'minecraft:air')
        call('save')
        session.restart()
        wait_loaded(call, [SAW])
        assert read_filter(nbt()) == ['minecraft:stick', 7]
        aim(at)
        snap('cold-sticky-slot')

        hand('minecraft:air')
        click()
        cleared = nbt()
        assert read_filter(cleared) is None and re.search(r'\bFilter:\s*\{\}', cleared), cleared
        snap('cleared')

        cmd(f'data merge block {xyz(SAW)} {{Filter:{{count:1,id:"create:filter"}}}}')
        hand('minecraft:stick 7')
        aim(at)
        click()
        assert read_filter(nbt()) == ['create:filter', 1]
        put(SAW, 'minecraft:air')
        put(SAW, saw(True, True, facing='north'))
        aim(at)
        click()
        assert read_filter(nbt()) is None
        report.update(wrench_preserved=True, outside_vanilla_placement=True,
                      cold_reload_preserved=True, cleared=True, advanced_preserved=True,
                      horizontal_ignored=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'resources', 'ctl'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--create-jar', type=Path)
    parser.add_argument('--reference', type=Path)
    args = parser.parse_args()
    reference = json.loads(args.reference.read_text()) if args.reference else None
    session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                 name='saw-filter-native', world='CreateSawFilter', username='SawFilterCheck')
    (session.scratch / 'options.txt').write_text('lang:en_us\ntutorialStep:none\nchatVisibility:2\n')
    result = session.scratch / 'result.json'
    report = dict(passed=False, original_assets=args.create_jar is not None)
    print(session.scratch, flush=True)
    try:
        native(session, reference, report)
        report['passed'] = True
    finally:
        result.write_text(json.dumps(report, indent=2) + '\n')
        session.control_temp.cleanup()
        print(result)


if __name__ == '__main__':
    main()
