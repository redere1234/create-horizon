#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Run a grounded oak farm with a glued, lowered Saw in native Horizon."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from shlex import quote
from shutil import copytree, ignore_patterns

from deployer_farm_checks import DEPLOYER, MOTOR, PIVOT, ROTOR, SAPLING, number, xyz
from deployer_refill_checks import CHEST, chest_slots
from native_check_session import NativeCheckSession, wait_loaded


TREE = (1158, 98, 56)
SOIL = (1158, 97, 56)
LOW_SAW = (1158, 98, 55)
STRUT = ((1158, 100, 55), (1158, 99, 55))
GLUE = 'create:super_glue'
LOG = 'minecraft:oak_log'
LEAVES = 'minecraft:oak_leaves'
BOX = (1148, 98, 47, 1168, 118, 64)
CHEST_TARGETS = (CHEST, (1160, 100, 55), (1159, 100, 54), (1158, 100, 55))
REVIEW_WORLD = 'GroundedTreeFarmReview'


def tree_cells(tree):
    return {(*row[:3], row[3].split('[', 1)[0]) for row in tree}


def make_review_copy(session):
    session.stop()
    saves = session.scratch / 'saves'
    copytree(saves / session.world, saves / REVIEW_WORLD, ignore=ignore_patterns('session.lock'))
    command = session.scratch / 'Open Grounded Tree Farm Review.command'
    launch = [str(session.game), '--resources', str(session.resources), '--home',
              str(session.scratch / 'home'), '--world', REVIEW_WORLD, '--name', session.username,
              '--creative', '--width', '1440', '--height', '900', '--render-distance', '4']
    command.write_text('#!/bin/zsh\ncd ' + quote(str(session.scratch)) + ' || exit 1\n'
                       + 'exec ' + ' '.join(map(quote, launch)) + '\n')
    command.chmod(0o755)
    session.start()
    return {'save': str(saves / REVIEW_WORLD), 'launcher': str(command)}


def run(session, report):
    call = session.call

    def command(line):
        return call('command', line)['chat']

    def put(pos, block):
        return command(f'setblock {xyz(pos)} {block}')

    def block(pos):
        return call('block', *pos)['block']

    def nbt(pos):
        return ' '.join(command(f'data get block {xyz(pos)}'))

    def active():
        return number({'nbt': nbt(PIVOT)}, 'Running', 0) == 1

    def near_pose(expected=0):
        angle = number({'nbt': nbt(PIVOT)}, 'Angle', 0)
        return abs((angle - expected + 180) % 360 - 180) <= 18

    def field():
        return call('blocks', *BOX)

    def wait_for(predicate, steps=130, interval=3):
        for _ in range(steps):
            if predicate():
                return
            call('wait', interval)
        raise AssertionError(('world did not reach expected condition', nbt(PIVOT), block(TREE)))

    def aim_click(pos):
        call('look-at', *(v + .5 for v in pos))
        call('wait', 4)
        hit = call('looking-at')['block']
        assert hit and hit['pos'] == list(pos), hit
        call('mouse', 'right', 'click')
        call('wait', 8)
        return hit

    def glue_corner(pos, viewpoint):
        command('tp @s ' + xyz(viewpoint))
        call('wait', 5)
        return aim_click(pos)

    def screenshot(name, target):
        command('tp @s 1155.5 98 60.5')
        call('wait', 5)
        call('look-at', *target)
        call('key', 'f1', 'tap')
        try:
            image = session.scratch / name
            call('screenshot', image)
            assert image.stat().st_size > 1024, image
        finally:
            call('key', 'f1', 'tap')

    def grow_seedling():
        command('tp @s 1155.5 98 56.5')
        call('wait', 4)
        call('select', 1)
        command('item replace entity @s hotbar.0 with minecraft:bone_meal 64')
        call('wait', 5)
        assert call('inventory')['hotbar'][0]['item'] == 'minecraft:bone_meal'
        for _ in range(64):
            if block(TREE) == LOG:
                return
            aim_click(TREE)
        raise AssertionError('ordinary bone meal did not grow the grounded oak')

    def tree_snapshot():
        return [row for row in field()['blocks'] if row[3].split('[', 1)[0] in (LOG, LEAVES)]

    def clear_tree():
        for kind in (LOG, LEAVES):
            command(f'fill {xyz(BOX)} minecraft:air replace {kind}')

    def generate_clear_oak():
        for _ in range(8):
            chat = command(f'place feature minecraft:fancy_oak {xyz(TREE)}')
            report.setdefault('tree_generation', []).extend(chat)
            call('wait', 4)
            tree = tree_snapshot()
            if block(TREE) == LOG:
                return tree
            clear_tree()
        raise AssertionError('fancy oak feature did not produce a tree clear of the moving assembly')

    def start():
        put(MOTOR, 'create:creative_motor[facing=up]{ScrollValue:16}')
        wait_for(active, steps=10)

    def stop():
        put(MOTOR, 'minecraft:air')
        wait_for(lambda: not active(), steps=10)

    def chest():
        landed = [p for p in CHEST_TARGETS if block(p) == 'minecraft:chest']
        assert len(landed) == 1, landed
        inventory = chest_slots(nbt(landed[0]))
        return {'position': landed[0], 'slots': inventory,
                'logs': sum(count for item, count in inventory.values() if item == LOG)}

    with session:
        command('gamemode creative')
        command('tp @s 1155.5 98 60.5')
        wait_loaded(call, [PIVOT, DEPLOYER, TREE])
        command('gamerule minecraft:random_tick_speed 0')
        command(f'fill {xyz(BOX)} minecraft:air')
        command('fill 1152 97 50 1167 97 62 minecraft:stone')
        put(SOIL, 'minecraft:dirt')
        put(PIVOT, 'create:mechanical_bearing[facing=up]')
        for pos in ROTOR:
            put(pos, 'minecraft:oak_planks')
        for pos in STRUT:
            put(pos, 'minecraft:oak_planks')
        put(LOW_SAW, 'create:mechanical_saw[facing=south,axis_along_first=false,flipped=false]')
        put(DEPLOYER, 'create:deployer[facing=down,axis_along_first=false]{Mode:"USE",Inventory:[]}')
        command(f'data merge block {xyz(DEPLOYER)} '
                f'{{Filter:{{id:"{SAPLING}",count:1}},FilterAmount:64,UpTo:1b}}')
        put(CHEST, f'minecraft:chest[facing=north]{{Items:['
                   f'{{Slot:0b,id:"{LOG}",count:4}},{{Slot:3b,id:"{SAPLING}",count:2}}]}}')

        command('gamemode survival')
        command('tp @s 1158.5 98 52.5')
        call('wait', 4)
        call('select', 1)
        command(f'item replace entity @s weapon.mainhand with {GLUE}')
        call('wait', 5)
        report['glue_clicks'] = [glue_corner(LOW_SAW, (1158.5, 98, 52.5)),
                                 glue_corner(STRUT[0], (1155.5, 98, 55.5)),
                                 glue_corner(STRUT[0], (1155.5, 98, 55.5)),
                                 glue_corner(DEPLOYER, (1161.5, 98, 52.5)),
                                 glue_corner(ROTOR[0], (1159.5, 98, 52.5)),
                                 glue_corner(CHEST, (1156.5, 98, 56.5))]
        damage = ' '.join(command('data get entity @s SelectedItem'))
        assert GLUE in damage and re.search(r'"?minecraft:damage"?:\s*6\b', damage), damage
        report['glue_held_after'] = damage
        initial = report['tree_before'] = generate_clear_oak()
        log_count = sum(row[3].split('[', 1)[0] == LOG for row in initial)
        leaf_count = len(initial) - log_count
        assert block(SOIL) == 'minecraft:dirt'
        assert log_count >= 4 and leaf_count >= 8, initial
        screenshot('grounded-oak-before.png', (1158.5, 102.5, 56.5))
        if report['review_copy_requested']:
            command('gamemode creative')
            command('item replace entity @s hotbar.1 with minecraft:bone_meal 32')
            command('item replace entity @s hotbar.2 with create:creative_motor')
            call('select', 2)
            call('save')
            report['review'] = make_review_copy(session)
            wait_loaded(call, [PIVOT, TREE])
            assert block(MOTOR) == 'minecraft:air' and not active()
            assert tree_cells(tree_snapshot()) == tree_cells(initial)
        report['initial_entities'] = {str(pos): nbt(pos) for pos in (DEPLOYER, LOW_SAW, CHEST)}
        start()
        wait_for(lambda: all(block(pos) == 'minecraft:air' for pos in (*STRUT, LOW_SAW, DEPLOYER, CHEST)), steps=10)
        report['lowered_saw_captured'] = True
        wait_for(lambda: block(TREE) == 'minecraft:air')
        assert not tree_snapshot(), tree_snapshot()
        assert block(SOIL) == 'minecraft:dirt'
        report['cut_before_replant'] = {'base': block(TREE), 'logs_removed': log_count, 'leaves_removed': leaf_count}

        call('save')
        session.restart()
        wait_loaded(call, [PIVOT, TREE])
        assert active(), nbt(PIVOT)
        wait_for(lambda: block(TREE) == SAPLING)
        assert not tree_snapshot() and block(SOIL) == 'minecraft:dirt'
        report['replanted_after_restart'] = block(TREE)
        wait_for(near_pose)
        stop()
        call('save')
        cargo = report['landed_chest'] = chest()
        assert cargo['position'] == CHEST and cargo['logs'] == 4 + log_count, cargo
        report['landed_chest_initial_log_count'] = 4
        screenshot('grounded-oak-replanted.png', (1158.5, 98.5, 56.5))

        if report['regrow_requested']:
            # Park the low saw and strut clear of the sapling so ordinary
            # oak features have room regardless of the worldgen draw.
            start()
            wait_for(lambda: near_pose(180))
            stop()
            parked = report['growth_parking'] = chest()
            assert parked['position'] != CHEST and parked['logs'] == cargo['logs'], parked
            grow_seedling()
            second = report['tree_after_bone_meal'] = tree_snapshot()
            second_logs = sum(row[3].split('[', 1)[0] == LOG for row in second)
            assert second_logs >= 4 and len(second) > second_logs, second
            command('tp @s 1155.5 98 60.5')
            start()
            wait_for(lambda: block(TREE) == 'minecraft:air')
            wait_for(lambda: not tree_snapshot(), steps=10)
            wait_for(lambda: block(TREE) == SAPLING)
            wait_for(near_pose)
            stop()
            second_cargo = report['second_landed_chest'] = chest()
            assert second_cargo['logs'] == cargo['logs'] + second_logs, second_cargo
            report['second_cut'] = {'logs_removed': second_logs, 'leaves_removed': len(second) - second_logs}
            report['replanted_after_bone_meal_cycle'] = block(TREE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'resources', 'ctl'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--regrow', action='store_true')
    parser.add_argument('--review-copy', action='store_true', help='save an unpowered copy for manual play')
    args = parser.parse_args()
    meta = json.loads((args.game.resolve().parent / 'native-mods.json').read_text())
    create = next(mod for mod in meta['mods'] if mod['id'] == 'create')
    with args.game.open('rb') as game:
        game_sha256 = hashlib.file_digest(game, 'sha256').hexdigest()
    report = dict(passed=False, regrow_requested=args.regrow, review_copy_requested=args.review_copy,
                  create_version=create['version'], game_sha256=game_sha256,
                  tree_base=TREE, saw=LOW_SAW, strut=STRUT)
    session = NativeCheckSession(args.game, args.resources, args.ctl, None, name='grounded-tree-farm',
                                 world='GroundedTreeFarm', username='BearingReview')
    print(session.scratch, flush=True)
    try:
        run(session, report)
        report['passed'] = True
    finally:
        (session.scratch / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        session.control_temp.cleanup()
        print(json.dumps(dict(result=str(session.scratch / 'result.json'), passed=report['passed'])))


if __name__ == '__main__':
    main()
