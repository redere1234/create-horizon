#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare tilling, snow clearing and crop protection in both game clients."""
import argparse
import json
from pathlib import Path
import tempfile

from actor_native_checks import matched
from bearing_native_checks import Batch
from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession

PIVOT = (904, 100, 58)
MOTOR = (904, 99, 58)
PLOUGH = 'create:mechanical_plough[facing=north,waterlogged=false]'
SCENES = [
    ((907, 101, 57), 'grass_block', 'air', 'farmland', 'air'),
    ((906, 101, 56), 'coarse_dirt', 'air', 'dirt', 'air'),
    ((905, 101, 55), 'rooted_dirt', 'air', 'dirt', 'air'),
    ((904, 101, 55), 'stone', 'snow[layers=3]', 'stone', 'air'),
    ((903, 101, 55), 'farmland[moisture=7]', 'wheat[age=3]',
     'farmland', 'wheat[age=3]'),
]
LOOT = {'snowball': 3, 'hanging_roots': 1}


def setup(command, backwards):
    def put(pos, state):
        command(f'setblock {xyz(pos)} {state}')

    command('fill 900 96 53 908 108 62 minecraft:air')
    command('kill @e[type=minecraft:item,x=904,y=101,z=58,distance=..12]')
    put(PIVOT, 'create:mechanical_bearing[facing=up]')
    for x in range(904, 907):
        put((x, 101, 58), 'minecraft:slime_block')
    put((907, 101, 58), PLOUGH.replace('north', 'south') if backwards else PLOUGH)
    for (x, y, z), soil, cover, _, _ in SCENES:
        put((x, y - 1, z), 'minecraft:' + soil)
        if cover != 'air':
            put((x, y, z), 'minecraft:' + cover)
    put(MOTOR, 'create:creative_motor[facing=up]{ScrollValue:32}')


def expectations(backwards):
    for (x, y, z), initial_soil, initial_cover, soil, cover in SCENES:
        yield (x, y - 1, z), 'minecraft:' + (initial_soil if backwards else soil)
        yield (x, y, z), 'minecraft:' + (initial_cover if backwards else cover)


def loot_command(item):
    selector = (f'@e[type=minecraft:item,x=904,y=101,z=58,distance=..12,'
                f'nbt={{Item:{{id:"minecraft:{item}"}}}},limit=1]')
    return f'data get entity {selector} Item'


def verify_loot(messages):
    for (item, count), message in zip(LOOT.items(), messages, strict=True):
        assert f'minecraft:{item}' in message, message
        assert number({'nbt': message}, 'count') == count, message


def native(args):
    session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                 name='plough-native', graphics=False, world='CreatePloughChecks')
    try:
        report = dict(passed=True)
        for backwards in (False, True):
            label = 'backwards' if backwards else 'forward'
            batch = Batch()
            batch.load(PIVOT)
            batch.command('gamerule minecraft:random_tick_speed 0')
            setup(batch.command, backwards)
            batch.tick(32)
            for pos, state in expectations(backwards):
                batch.expect(pos, state)
            if not backwards:
                for item in LOOT:
                    batch.command(loot_command(item), True)
            batch.put(MOTOR, 'minecraft:air')
            batch.tick(20)
            rows = batch.run(session, 'plough-' + label)
            assert len(rows) == (10 if backwards else 12), (session.scratch, rows)
            assert all(map(matched, rows[:10])), (session.scratch, rows)
            if not backwards:
                verify_loot(rows[10:])
            report[label] = rows
        path = session.scratch / 'result.json'
        path.write_text(json.dumps(report, indent=2) + '\n')
        print(path)
    finally:
        session.control_temp.cleanup()


def original():
    host = Original()
    host.call('tick', {'frozen': True})
    host.command('gamemode creative')
    host.command('tp @s 904.5 102 58.5')
    host.command('forceload add 896 48 911 63')
    host.command('gamerule randomTickSpeed 0')
    host.snapshot([PIVOT], 32)
    report = dict(passed=True, create=PINS['create_revision'])
    for backwards in (False, True):
        setup(host.command, backwards)
        expected = list(expectations(backwards))
        observed = host.snapshot([pos for pos, _ in expected], 32)
        for (_, state), block in zip(expected, observed, strict=True):
            name, _, properties = state.partition('[')
            assert block['block'] == name, (state, observed)
            if properties:
                assert all(block['properties'][k] == v for k, v in
                           (p.split('=') for p in properties.rstrip(']').split(','))), block
        report['backwards' if backwards else 'forward'] = observed
        if not backwards:
            replies = [host.command(loot_command(item)) for item in LOOT]
            verify_loot([' '.join(reply['messages']) for reply in replies])
            report['loot'] = replies
        host.command(f'setblock {xyz(MOTOR)} minecraft:air')
        host.snapshot([PIVOT], 20)
    work = Path(tempfile.mkdtemp(prefix='plough-java-', dir=ROOT / '.local'))
    path = work / 'result.json'
    path.write_text(json.dumps(report, indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'create-jar'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        original()
    elif args.game and args.resources and args.ctl:
        native(args)
    else:
        parser.error('Horizon runs require --game, --resources and --ctl')
