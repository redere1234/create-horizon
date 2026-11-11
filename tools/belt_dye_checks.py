#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Check Survival dye and water clicks on a whole occupied Belt, then reload."""

import argparse
import errno
import json
import math
from pathlib import Path
import re
import shutil
import tempfile
import time

from belt_pulley_checks import BELT, CAMERA, FORCE, MIDDLE, MOTOR, ROOM, TARGET, setup
from burner_heat_java_checks import field, items, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded
from reference_java import BASE, launch, process_alive
from schematic_belt_checks import controller


WATER = 'minecraft:water_bucket'
BOTTLE = 'minecraft:potion[minecraft:potion_contents={potion:"minecraft:water"}]'
MARK = 'belt_dye_probe'


def dye(raw):
    match = re.search(r'\bDye:\s*"([A-Z_]+)"', raw)
    if match:
        return match[1]
    assert not re.search(r'\bDye:', raw), raw
    return None


def check_chain(read, color):
    for i, pos in enumerate(BELT):
        block = read(pos)
        raw = block['nbt']
        assert block['block'] == 'create:belt' and block['properties']['waterlogged'] == 'false', block
        assert dye(raw) == color, (pos, raw)
        assert controller(raw) == list(BELT[0]) and number(block, 'Length') == len(BELT), raw
        assert number(block, 'Index') == i, raw


def check_item(read):
    raw = field(read(BELT[0])['nbt'], 'Inventory')
    assert items(raw, 'Items') == {'minecraft:copper_ingot': 4}, raw
    assert f'{MARK}:43' in raw.replace(' ', ''), raw
    return [number({'nbt': raw}, key) for key in ('Pos', 'PrevPos')]


def exercise(command, step, read, click, restart, screenshot):
    setup(command)
    step(15)
    check_chain(read, None)
    command(f'data merge block {xyz(BELT[0])} {{Inventory:{{Items:[{{'
            f'Item:{{id:"minecraft:copper_ingot",count:4,components:{{"minecraft:custom_data":{{{MARK}:43}}}}}},'
            'Pos:3.25f,PrevPos:3.25f,Offset:0.125f,PrevOffset:0.125f,InSegment:2,InDirection:1,Angle:315}],'
            'PositiveOrder:0b}}')
    step(3)
    check_chain(read, None)
    before = check_item(read)
    pictures = {}

    def use(item, count, color):
        command(f'item replace entity @s weapon.mainhand with {item} {count}')
        click()
        check_chain(read, color)
        held = command('data get entity @s SelectedItem')
        assert item.split('[', 1)[0] in held and number({'nbt': held}, 'count') == count, held
        if item == BOTTLE:
            assert 'minecraft:water' in held, held

    use('minecraft:red_dye', 3, 'RED')
    assert check_item(read) == before
    step(3)
    pos, previous = check_item(read)
    assert math.isclose(pos - previous, -32 / 480, abs_tol=2e-6)
    command(f'setblock {xyz(MOTOR)} minecraft:air')
    step(3)
    parked = check_item(read)
    assert number(read(BELT[0]), 'Speed', 0) == 0, parked
    assert abs(parked[0] - 2.5) < .55, parked
    step(1)
    assert check_item(read) == parked
    restart()
    check_chain(read, 'RED')
    assert check_item(read) == parked
    pictures['red_after_restart'] = screenshot('red-after-restart')
    use('minecraft:blue_dye', 2, 'BLUE')
    use('minecraft:blue_dye', 2, 'BLUE')
    assert check_item(read) == parked
    pictures['blue_still'] = screenshot('blue-still')
    use(WATER, 1, None)
    pictures['water_bucket_cleared'] = screenshot('water-bucket-cleared')
    use('minecraft:yellow_dye', 2, 'YELLOW')
    use(BOTTLE, 1, None)
    assert check_item(read) == parked
    restart()
    check_chain(read, None)
    assert check_item(read) == parked
    return dict(colors=['RED', 'BLUE', 'BLUE', None, 'YELLOW', None],
                held_counts=[3, 2, 2, 1, 2, 1], item_count=4, marker=43,
                colored_restart=True, clear_restart=True), pictures


def java(work):
    host = Original()
    initial = host.call('state', {})
    if initial.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})

    def command(text):
        return ' '.join(host.command(text)['messages'])

    def step(ticks):
        host.snapshot([BELT[0]], ticks)

    def read(pos):
        raw = host.call('block', {'pos': pos})
        return dict(block=raw['id'], nbt=raw['nbt'], properties=raw['properties'])

    def click():
        host.call('camera', {'position': CAMERA, 'target': TARGET})
        for _ in range(25):
            hit = host.call('state', {})['hit']
            if hit and hit.get('pos') == list(MIDDLE) and hit.get('face') == 'south':
                break
            time.sleep(.025)
        else:
            raise AssertionError((MIDDLE, hit))
        host.call('input', {'key': 'use'})
        try:
            time.sleep(.15)
        finally:
            host.call('input', {'key': 'use', 'down': False})

    def restart():
        host.call('quit', {})
        deadline = time.monotonic() + 60
        while process_alive(BASE):
            if time.monotonic() >= deadline:
                raise RuntimeError('The isolated Java client did not save and quit')
            time.sleep(.2)
        state = launch(BASE)
        assert state['ready'], state
        host.call('tick', {'frozen': True})
        for _ in range(10):
            if all(read(pos)['block'] == 'create:belt' for pos in BELT):
                return
            step(5)
        raise AssertionError('Saved Belt did not reload')

    def screenshot(label):
        host.call('camera', {'position': (CAMERA[0], CAMERA[1], CAMERA[2] + 1),
                             'target': TARGET, 'hide_gui': True})
        return host.call('capture', {'name': f'{work.name}/{label}.png', 'frames': 6})['path']

    try:
        command('gamemode creative')
        command('tp @s ' + xyz(CAMERA))
        command('forceload add ' + FORCE)
        step(25)
        return exercise(command, step, read, click, restart, screenshot)
    finally:
        command('fill ' + ROOM + ' minecraft:air')
        command('forceload remove ' + FORCE)
        host.call('camera', {'position': initial['position'], 'hide_gui': False})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session):
    call = session.call

    def command(text):
        return ' '.join(call('command', text)['chat'])

    def step(ticks):
        command('tick unfreeze')
        call('wait', ticks)
        command('tick freeze')

    def read(pos):
        raw = call('block', *pos)
        return dict(block=raw['block'], properties=dict(re.findall(r'(\w+)=(\w+)', raw['state'])),
                    nbt=command('data get block ' + xyz(pos)))

    def click():
        command('tp @s ' + xyz(CAMERA))
        call('look-at', 'block', *MIDDLE, 'south')
        call('interact', *MIDDLE, 'south')

    def restart():
        session.restart()
        wait_loaded(call, BELT)
        command('tick freeze')

    def screenshot(label):
        path = session.scratch / (label + '.png')
        command('tp @s ' + xyz((CAMERA[0], CAMERA[1], CAMERA[2] + 1)))
        call('look-at', *TARGET)
        call('wait', 4)
        call('key', 'f1', 'tap')
        call('screenshot', path)
        call('key', 'f1', 'tap')
        assert path.stat().st_size > 1024, path
        return str(path)

    with session:
        command('tp @s ' + xyz(CAMERA))
        wait_loaded(call, BELT)
        command('tick freeze')
        return exercise(command, step, read, click, restart, screenshot)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for key in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + key, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='belt-dye-java-', dir=ROOT / '.local'))
        checks, pictures = java(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon needs --game, --resources, --ctl and --reference')
        expected = json.loads(args.reference.read_text())
        assert expected['passed'] and expected['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     world='BeltDye', name='belt-dye-native')
        work = session.scratch
        try:
            checks, pictures = native(session)
            assert checks == expected['checks'], (checks, expected)
            if args.create_jar:
                assert 'local resources from Create' in session.log.read_text()
            assert Path(pictures['blue_still']).read_bytes() != Path(pictures['water_bucket_cleared']).read_bytes()
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                if folder.exists():
                    try:
                        shutil.rmtree(folder)
                    except OSError as error:
                        if error.errno != errno.ENOTEMPTY:
                            raise
                        shutil.rmtree(folder)
    output = work / 'result.json'
    output.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], checks=checks,
                                     pictures=pictures), indent=2) + '\n')
    print(output)


if __name__ == '__main__':
    main()
