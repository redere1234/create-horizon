#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Check the Sticker redstone latch and the bond on its extended front face."""
import argparse
import json
from pathlib import Path
import tempfile

from actor_native_checks import matched
from bearing_native_checks import Batch
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded

PIVOT = (1480, 148, 150)
MOTOR = (1480, 147, 150)
ANCHOR = (1480, 149, 150)
FRONT = (1481, 149, 150)
SIDE = (1480, 149, 151)
POWER = (1480, 149, 149)
PLACEMENT_SUPPORT = (1484, 148, 152)
PLACED = (1484, 149, 152)
PLACEMENT_POWER = (1484, 149, 151)
AIR = 'minecraft:air'
STONE = 'minecraft:stone'
STICKER = 'create:sticker'


def put(command, pos, state):
    command(f'setblock {xyz(pos)} {state}')


def block(facing, extended=False, powered=False):
    return f'{STICKER}[facing={facing},extended={str(extended).lower()},powered={str(powered).lower()}]'


def latch(command, observe):
    put(command, POWER, AIR)
    put(command, ANCHOR, AIR)
    put(command, ANCHOR, STICKER)
    observe(ANCHOR, block('north'))
    for power, extended in [(True, True), (False, True), (True, False), (False, False)]:
        put(command, POWER, 'minecraft:redstone_block' if power else AIR)
        observe(ANCHOR, block('north', extended, power))


SCENES = {
    'extended': (block('east', True), STONE, AIR),
    'retracted': (block('east'), STONE, STONE),
    'reverse': (STONE, block('west', True), AIR),
    'reverse_retracted': (STONE, block('west'), block('west')),
    'unsupported_face': (block('east', True), block('west'), block('west')),
}


def bearing(command, anchor, target):
    command('fill 1477 146 147 1484 153 154 minecraft:air')
    put(command, PIVOT, 'create:mechanical_bearing[facing=up]')
    put(command, ANCHOR, anchor)
    put(command, FRONT, target)
    put(command, SIDE, STONE)
    put(command, MOTOR, 'create:creative_motor[facing=up]{ScrollValue:32}')


def original():
    host = Original()
    scratch = Path(tempfile.mkdtemp(prefix='sticker-java-', dir=ROOT / '.local'))
    report = dict(create=PINS['create_revision'], latch=[], capture={})
    recorded = report['latch']

    def observe(pos, expected):
        result = host.call('block', {'pos': pos})
        name, _, properties = expected.partition('[')
        assert result['id'] == name, (expected, result)
        if properties:
            wanted = dict(entry.split('=') for entry in properties.rstrip(']').split(','))
            assert {k: v.lower() for k, v in result['properties'].items()} == wanted, (expected, result)
        recorded.append(result)

    try:
        assert host.call('state', {})['data_version'] == 3955
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        host.command('tp @s 1480.5 156 150.5')
        host.command('forceload add 1472 144 1487 159')
        host.snapshot([PIVOT], 25)
        latch(host.command, observe)
        recorded = report['powered_placement'] = []
        put(host.command, PLACED, AIR)
        put(host.command, PLACEMENT_SUPPORT, STONE)
        put(host.command, PLACEMENT_POWER, 'minecraft:redstone_block')
        host.command(f'item replace entity @s weapon.mainhand with {STICKER}')
        host.call('camera', {'position': [1484.5, 152.7, 152.5], 'target': [1484.5, 148.75, 152.5]})
        host.call('capture', {'name': f'{scratch.name}/placement-before.png', 'frames': 10})
        hit = host.call('state', {})['hit']
        assert tuple(hit['pos']) == PLACEMENT_SUPPORT and hit['face'] == 'up', hit
        host.call('input', {'key': 'use'})
        try:
            host.call('capture', {'name': f'{scratch.name}/placement.png', 'frames': 10})
        finally:
            host.call('input', {'key': 'use', 'down': False})
        observe(PLACED, block('up', powered=True))
        put(host.command, PLACEMENT_POWER, AIR)
        observe(PLACED, block('up'))
        put(host.command, PLACEMENT_POWER, 'minecraft:redstone_block')
        observe(PLACED, block('up', True, True))
        for label, (anchor, target, expected) in SCENES.items():
            recorded = report['capture'][label] = []
            bearing(host.command, anchor, target)
            host.snapshot([PIVOT], 8)
            observe(ANCHOR, AIR)
            observe(FRONT, expected)
            observe(SIDE, STONE)
            put(host.command, MOTOR, AIR)
            host.snapshot([PIVOT], 16)
    finally:
        put(host.command, MOTOR, AIR)
        host.command('forceload remove 1472 144 1487 159')
        host.call('tick', {'frozen': False})
        (scratch / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
        path = scratch / 'result.json'
        path.write_text(json.dumps(report, indent=2) + '\n')
        print(path)


def native(args):
    session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                 name='sticker-native', graphics=False, world='CreateSticker')
    result = {}
    try:
        batch = Batch()
        batch.load((PIVOT[0], PIVOT[1] + 8, PIVOT[2]))
        latch(batch.command, batch.expect)
        rows = result['latch'] = batch.run(session, 'latch')
        assert len(rows) == 5 and all(map(matched, rows)), rows
        for label, (anchor, target, expected) in SCENES.items():
            batch = Batch()
            batch.load((PIVOT[0], PIVOT[1] + 8, PIVOT[2]))
            bearing(batch.command, anchor, target)
            batch.tick(8)
            batch.expect(ANCHOR, AIR)
            batch.expect(FRONT, expected)
            batch.expect(SIDE, STONE)
            batch.put(MOTOR, AIR)
            batch.tick(16)
            rows = result[label] = batch.run(session, label)
            assert len(rows) == 3 and all(map(matched, rows)), (label, rows)
        if args.placement:
            result['powered_placement'] = native_placement(args)
        result['passed'] = True
    finally:
        session.control_temp.cleanup()
        path = session.scratch / 'result.json'
        path.write_text(json.dumps(result, indent=2) + '\n')
        print(path)


def native_placement(args):
    session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                 name='sticker-place-native', graphics=True,
                                 world='CreateStickerPlacement')
    with session:
        call = session.call

        def command(value):
            return call('command', value)

        def check(expected):
            reply = command(f'execute if block {xyz(PLACED)} {expected} run say bearing_check')
            assert any('bearing_check' in line for line in reply['chat']), (expected, reply)
            return call('block', *PLACED)['state']

        command('tp @s 1484.5 149 153.5')
        wait_loaded(call, [PLACEMENT_SUPPORT])
        put(command, (1484, 148, 153), STONE)
        put(command, PLACEMENT_SUPPORT, STONE)
        put(command, PLACEMENT_POWER, 'minecraft:redstone_block')
        command('tp @s 1484.5 149 153.5')
        command(f'item replace entity @s weapon.mainhand with {STICKER}')
        call('wait', 8)
        call('look-at', 1484.5, 148.95, 152.5)
        call('wait', 4)
        hit = call('looking-at')['block']
        assert tuple(hit['pos']) == PLACEMENT_SUPPORT and hit['face'] == 'up', hit
        call('mouse', 'right', 'click')
        call('wait', 5)
        rows = [check(block('up', powered=True))]
        put(command, PLACEMENT_POWER, AIR)
        rows.append(check(block('up')))
        put(command, PLACEMENT_POWER, 'minecraft:redstone_block')
        rows.append(check(block('up', True, True)))
        return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--placement', action='store_true', help='also check ordinary placement offscreen')
    for key in ('game', 'resources', 'ctl'):
        parser.add_argument('--' + key, type=Path)
    args = parser.parse_args()
    if args.java:
        original()
    elif args.game and args.resources and args.ctl:
        native(args)
    else:
        parser.error('Horizon checks require --game, --resources and --ctl')
