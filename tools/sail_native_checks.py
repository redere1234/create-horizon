#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Reproduce the Java sail fixture in an isolated native Horizon instance."""
import argparse
import json
from pathlib import Path
import re

from bearing_native_checks import Batch
from burner_heat_java_checks import number
from chain_drive_checks import xyz
from native_check_session import NativeCheckSession, wait_loaded
from sail_reference_checks import AXIAL, NEIGHBOR, PIVOT, ROTOR, SAIL, SHAFT


def review(session, reference):
    batch = Batch()
    batch.load((1092, 99, 58))
    batch.command('fill 1089 95 51 1106 106 61 minecraft:air')
    batch.command('fill 1089 98 57 1096 98 61 minecraft:smooth_stone')
    batch.command('fill 1096 98 54 1100 98 56 minecraft:smooth_stone')
    batch.put(SAIL, 'create:white_sail[facing=south]')
    batch.put(NEIGHBOR, 'create:blue_sail[facing=south]')
    batch.put((1094, 100, 55), 'minecraft:smooth_stone')
    batch.put(PIVOT, 'create:windmill_bearing[facing=east]')
    batch.put(SHAFT, 'create:shaft[axis=x]')
    for pos, block in ROTOR.items():
        batch.put(pos, block)
    batch.put(AXIAL, 'create:orange_sail[facing=east]')
    batch.run(session, 'sail-fixture')
    call = session.call
    report = {}

    def command(line):
        return call('command', line)

    def select(item, count=1):
        call('select', 1)
        command(f'item replace entity @s weapon.mainhand with {item} {count}')

    def hand(item, count):
        selected = call('inventory')['hotbar'][0]
        assert selected['item'] == item and selected['count'] == count, selected

    def click(pos, eye, target):
        command(f'tp @s {xyz(eye)}')
        call('wait', 5)
        call('look-at', *target)
        call('wait', 4)
        hit = call('looking-at')['block']
        assert hit['pos'] == list(pos), hit
        if pos == SAIL:
            front = 9 / 16 if hit['block'] == 'create:sail_frame' else 10 / 16
            assert hit['face'] == 'south' and hit['point'][2] == pos[2] + front, hit
        call('mouse', 'right', 'click')
        call('wait', 8)

    def screenshot(name):
        call('key', 'f1', 'tap')
        try:
            call('screenshot', session.scratch / name)
        finally:
            call('key', 'f1', 'tap')

    def snapshot(label, points):
        states = [call('block', *p) for p in points]
        report[label] = states
        for actual, original in zip(states, reference[label], strict=True):
            assert actual['block'] == original['id'], (label, actual, original)
            actual_properties = dict(re.findall(r'(\w+)=(\w+)', actual['state']))
            for prop, expected in original['properties'].items():
                assert actual_properties.get(prop) == expected.lower(), (label, actual, original)

    def block_number(pos, field):
        result = ' '.join(command(f'data get block {xyz(pos)}')['chat'])
        return number({'nbt': result}, field, 0)

    def wait_running(value):
        for _ in range(16):
            if block_number(PIVOT, 'Running') == value:
                return
            call('wait', 5)
        raise AssertionError((PIVOT, value, block_number(PIVOT, 'Running')))

    with session:
        wait_loaded(call, [SAIL, PIVOT, AXIAL])
        command('gamemode survival')
        command('clear @s')
        eye = (1091.85, 99, 58.5)
        edge = (1091.85, 100.52, 55.5)
        select('minecraft:red_dye', 5)
        click(SAIL, eye, edge)
        snapshot('dye', [SAIL, NEIGHBOR])
        hand('minecraft:red_dye', 5)
        click(SAIL, eye, edge)
        snapshot('dye_adjacent', [SAIL, NEIGHBOR])
        screenshot('painted.png')
        select('minecraft:shears')
        click(SAIL, eye, edge)
        snapshot('shear', [SAIL, NEIGHBOR])
        hand('minecraft:shears', 1)

        command(f'setblock {xyz(NEIGHBOR)} minecraft:air')
        select('create:white_sail', 3)
        click(SAIL, eye, edge)
        snapshot('placement', [SAIL, NEIGHBOR])
        hand('create:white_sail', 2)
        click((1094, 100, 55), (1094.5, 99, 58.5), (1094.5, 100.5, 55.5))
        regular = call('block', 1094, 100, 56)
        assert regular['block'] == 'create:white_sail' and 'facing=south' in regular['state'], regular
        hand('create:white_sail', 1)

        command('gamemode creative')
        command('clear @s')
        call('select', 9)
        eye = (1097.2, 99, 55.84)
        target = (1100.5, 100.75, 55.84)
        points = [PIVOT, SHAFT, *ROTOR, AXIAL]
        click(PIVOT, eye, target)
        wait_running(1)
        snapshot('rotating', points)
        assert block_number(PIVOT, 'LastGenerated') == block_number(SHAFT, 'Speed') == 1
        assert block_number(PIVOT, 'Running') == 1
        call('look-at', 1101.5, 100.5, 55.5)
        screenshot('rotating.png')
        call('save')
        session.restart()
        wait_loaded(call, points)
        snapshot('rotating', points)
        assert block_number(PIVOT, 'LastGenerated') == block_number(SHAFT, 'Speed') == 1
        call('select', 9)
        click(PIVOT, eye, target)
        wait_running(0)
        snapshot('landed', points)
        assert block_number(PIVOT, 'Running') == 0
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + flag, type=Path, required=True)
    parser.add_argument('--create-jar', type=Path)
    args = parser.parse_args()
    reference = json.loads(args.reference.read_text())
    assert reference['passed'], args.reference
    session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                 name='sail-native', world='CreateSailChecks', username='BearingReview')
    print(session.scratch, flush=True)
    try:
        report = review(session, reference)
        (session.scratch / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    finally:
        session.control_temp.cleanup()
    print(json.dumps(dict(passed=True, world=str(session.scratch))))


if __name__ == '__main__':
    main()
