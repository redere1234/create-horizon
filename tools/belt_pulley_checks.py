#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Check ordinary Survival shaft and side-Wrench edits on an occupied Belt."""

import argparse
import json
import math
from pathlib import Path
import re
import shutil
import tempfile
import time

from burner_heat_java_checks import field, items, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded
from schematic_belt_checks import controller


Y, Z = 116, 1480
BELT = [(2227 + i, Y, Z) for i in range(6)]
MIDDLE = BELT[2]
SIDE = (MIDDLE[0], Y, Z - 1)
MOTOR = (BELT[0][0], Y, Z - 1)
CAMERA = (MIDDLE[0] + .5, Y, Z + 3.5)
TARGET = (MIDDLE[0] + .5, Y + .5, Z + .5)
ROOM = '2224 115 1476 2236 120 1485'
FORCE = '2224 1472 2239 1487'
SHAFT = 'create:shaft'
MARK = 'pulley_probe'
DROPS = '@e[type=minecraft:item,x=2224,y=115,z=1476,dx=12,dy=5,dz=9]'


def expected_part(index, attached):
    if index == 0:
        return 'start'
    if index == len(BELT) - 1:
        return 'end'
    if index == 2 and attached:
        return 'pulley'
    return 'middle'


def setup(command):
    command('gamemode survival')
    command('clear @s ' + SHAFT)
    command('fill ' + ROOM + ' minecraft:air')
    command('fill 2224 115 1476 2236 115 1485 minecraft:stone')
    for i, pos in enumerate(BELT):
        command(f'setblock {xyz(pos)} create:belt[facing=east,slope=horizontal,part={expected_part(i, False)}]')
    command(f'setblock {xyz(SIDE)} {SHAFT}[axis=z]')
    command(f'setblock {xyz(MOTOR)} create:creative_motor[facing=south]{{ScrollValue:32}}')
    command('tp @s ' + xyz(CAMERA))


def seed(command):
    command(f'data merge block {xyz(BELT[0])} {{Inventory:{{Items:[{{'
            f'Item:{{id:"minecraft:copper_ingot",count:5,components:{{"minecraft:custom_data":{{{MARK}:19}}}}}},'
            'Pos:3.5f,PrevPos:3.5f,Offset:0.125f,PrevOffset:0.125f,InSegment:2,InDirection:1,Angle:315}],'
            'PositiveOrder:0b}}')


def check_layout(read, attached):
    for index, pos in enumerate(BELT):
        block = read(pos)
        assert block['block'] == 'create:belt' and block['properties']['part'] == expected_part(index, attached), block
        assert controller(block['nbt']) == list(BELT[0]), block
        assert number(block, 'Index') == index and number(block, 'Length') == len(BELT), block
        assert number(block, 'Speed') == 32, block
    shaft = read(SIDE)
    assert shaft['block'] == SHAFT and number(shaft, 'Speed', 0) == 32 * attached, shaft


def check_transport(read, moving=False):
    raw = field(read(BELT[0])['nbt'], 'Inventory')
    assert items(raw, 'Items') == {'minecraft:copper_ingot': 5}, raw
    assert f'{MARK}:19' in raw.replace(' ', ''), raw
    pos = number({'nbt': raw}, 'Pos')
    if moving:
        previous = number({'nbt': raw}, 'PrevPos')
        assert math.isclose(pos - previous, -32 / 480, abs_tol=2e-6), raw
    return pos


def exercise(command, step, read, click):
    setup(command)
    step(15)
    check_layout(read, False)
    seed(command)
    start = check_transport(read)
    command(f'item replace entity @s weapon.mainhand with {SHAFT}')
    click()
    assert SHAFT not in command('data get entity @s SelectedItem'), 'Survival shaft was not consumed'
    assert check_transport(read) == start
    step(3)
    check_layout(read, True)
    attached = check_transport(read, True)
    assert attached < start
    command('item replace entity @s weapon.mainhand with create:wrench')
    click()
    inventory = command('data get entity @s Inventory')
    returned = [entry for entry in re.findall(r'\{[^{}]*\}', inventory) if SHAFT in entry]
    assert len(returned) == 1 and number({'nbt': returned[0]}, 'count') == 1, inventory
    assert check_transport(read) == attached
    step(3)
    check_layout(read, False)
    assert check_transport(read, True) < attached
    assert 'pulley_loose' not in command(f'execute if entity {DROPS} run say pulley_loose')
    return dict(parts=['middle', 'pulley', 'middle'], side_rpm=[0, 32, 0],
                shafts_consumed=1, shafts_returned=1, copper=5, mark=19)


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
        return dict(block=raw['id'], nbt=raw['nbt'],
                    properties={key: value.lower() for key, value in raw['properties'].items()})

    def click():
        wanted = list(MIDDLE)
        host.call('camera', {'position': CAMERA, 'target': TARGET})
        for _ in range(25):
            hit = host.call('state', {})['hit']
            if hit and hit.get('pos') == wanted and hit.get('face') == 'south':
                break
            time.sleep(.025)
        else:
            raise AssertionError((wanted, hit))
        before = read(MIDDLE)['properties']['part']
        host.call('input', {'key': 'use'})
        try:
            for _ in range(25):
                if read(MIDDLE)['properties']['part'] != before:
                    return
                time.sleep(.025)
            raise AssertionError(('Belt use did not update part', read(MIDDLE)))
        finally:
            host.call('input', {'key': 'use', 'down': False})

    try:
        command('gamemode creative')
        command('tp @s ' + xyz(CAMERA))
        command('forceload add ' + FORCE)
        step(25)
        return exercise(command, step, read, click)
    finally:
        command('fill ' + ROOM + ' minecraft:air')
        command(f'kill {DROPS}')
        command('forceload remove ' + FORCE)
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
        call('look-at', 'block', *MIDDLE, 'south')
        reply = call('interact', *MIDDLE, 'south')
        assert reply['changed'], reply

    with session:
        command('tp @s ' + xyz(CAMERA))
        wait_loaded(call, BELT)
        command('tick freeze')
        return exercise(command, step, read, click)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for key in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + key, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='belt-pulley-java-', dir=ROOT / '.local'))
        result = java(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon needs --game, --resources, --ctl and --reference')
        expected = json.loads(args.reference.read_text())
        assert expected['passed'] and expected['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None, graphics=False,
                                     world='BeltPulley', name='belt-pulley-native')
        work = session.scratch
        try:
            result = native(session)
            assert result == expected['checks'], (result, expected)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                if folder.exists():
                    shutil.rmtree(folder)
    output = work / 'result.json'
    output.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], checks=result), indent=2) + '\n')
    print(output)


if __name__ == '__main__':
    main()
