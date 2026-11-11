#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare ordinary Belt casing, side-Wrench and cold-save behavior."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile
import time

from belt_pulley_checks import BELT, CAMERA, DROPS, MIDDLE, MOTOR, ROOM, TARGET, check_transport, seed, setup
from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded
from reference_java import BASE, launch, process_alive
from schematic_belt_checks import controller


FORCE = '2224 1472 2239 1519'
EXTRA = '2225 114 1487 2234 121 1516'
SLOPES = {
    'upward': ('east', [(2229 + i, 116 + i, 1490) for i in range(3)]),
    'downward': ('east', [(2229 + i, 118 - i, 1497) for i in range(3)]),
    'vertical': ('south', [(2231, 116 + i, 1504) for i in range(3)]),
    'sideways': ('east', [(2229 + i, 116, 1511) for i in range(3)]),
}
ANDESITE, BRASS = 'create:andesite_casing', 'create:brass_casing'
SHAFT, WRENCH = 'create:shaft', 'create:wrench'
AIR = 'minecraft:air'


def aim(pos):
    x, y, z = pos
    return (x + .5, y, z + 3.5), (x + .5, y + .5, z + .5)


def layout(read, chain):
    result = []
    for i, pos in enumerate(chain):
        row = read(pos)
        nbt = row['nbt']
        assert row['block'] == 'create:belt' and controller(nbt) == list(chain[0]), row
        assert number(row, 'Index') == i and number(row, 'Length') == len(chain), row
        material = re.search(r'\bCasing\s*:\s*"([A-Z]+)"', nbt)
        assert material, row
        assert (row['properties']['casing'] == 'true') == (material[1] != 'NONE'), row
        result.append([material[1], bool(number(row, 'Covered')), row['properties']['part']])
    return result


def exercise(command, step, read, click, restart, screenshot):
    setup(command)
    command(f'fill {EXTRA} {AIR}')
    for slope, (face, chain) in SLOPES.items():
        for part, pos in zip(('start', 'middle', 'end'), chain, strict=True):
            command(f'setblock {xyz(pos)} create:belt[facing={face},slope={slope},part={part}]')
        x, y, z = chain[1]
        command(f'setblock {x} {y - 1} {z + 3} minecraft:stone')
    step(15)
    seed(command)
    step(3)

    def use(pos, item, count=1):
        command(f'item replace entity @s weapon.mainhand with {item} {count}')
        click(pos)
        held = command('data get entity @s SelectedItem')
        assert item in held and number({'nbt': held}, 'count') == count, held

    command(f'item replace entity @s weapon.mainhand with {SHAFT}')
    click(MIDDLE)
    assert SHAFT not in command('data get entity @s SelectedItem')
    step(3)
    parked = check_transport(read)
    use(MIDDLE, ANDESITE, 3)
    assert layout(read, BELT)[2] == ['ANDESITE', False, 'pulley']
    use(MIDDLE, BRASS, 2)
    assert layout(read, BELT)[2] == ['BRASS', False, 'pulley']
    use(MIDDLE, ANDESITE, 3)
    use(MIDDLE, ANDESITE, 3)
    use(BELT[3], BRASS, 2)
    assert check_transport(read) == parked
    step(3)
    assert check_transport(read, moving=True) < parked
    command(f'setblock {xyz(MOTOR)} {AIR}')
    step(4)
    parked = check_transport(read)
    above = (BELT[3][0], BELT[3][1] + 1, BELT[3][2])
    command(f'setblock {xyz(above)} minecraft:stone_slab[type=top]')
    step(2)
    assert layout(read, BELT)[3] == ['BRASS', False, 'middle']
    command(f'setblock {xyz(above)} minecraft:stone_slab[type=bottom]')
    step(2)
    before = layout(read, BELT)
    assert [row[0] for row in before] == ['NONE', 'NONE', 'ANDESITE', 'BRASS', 'NONE', 'NONE'], before
    assert before[3] == ['BRASS', True, 'middle'], before
    restart()
    assert layout(read, BELT) == before and check_transport(read) == parked
    pictures = {'mixed_after_restart': screenshot('mixed-after-restart')}
    use(MIDDLE, WRENCH)
    assert layout(read, BELT)[2] == ['NONE', False, 'pulley']
    assert SHAFT not in command('data get entity @s Inventory')
    use(MIDDLE, WRENCH)
    step(2)
    assert layout(read, BELT)[2] == ['NONE', False, 'middle']
    inventory = command('data get entity @s Inventory')
    assert inventory.count(SHAFT) == 1, inventory
    command(f'setblock {xyz(above)} {AIR}')
    step(2)
    assert layout(read, BELT)[3] == ['BRASS', False, 'middle']
    use(BELT[3], WRENCH)
    assert all(row[0] == 'NONE' for row in layout(read, BELT))
    assert check_transport(read) == parked
    assert 'casing_loose' not in command(f'execute if entity {DROPS} run say casing_loose')

    slopes = {}
    for slope, (_, chain) in SLOPES.items():
        use(chain[1], BRASS, 2)
        slopes[slope] = layout(read, chain)
        assert [row[0] for row in slopes[slope]] == ['NONE', 'BRASS', 'NONE'], slopes[slope]
        use(chain[1], WRENCH)
        assert all(row[0] == 'NONE' for row in layout(read, chain))
    return dict(horizontal=before, slopes=slopes, conserved_copper=5, marker=19), pictures


def original(work):
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
        row = host.call('block', {'pos': pos})
        return dict(block=row['id'], properties={key: val.lower() for key, val in row['properties'].items()},
                    nbt=row['nbt'])

    def click(pos):
        camera, target = aim(pos)
        host.call('camera', {'position': camera, 'target': target})
        for _ in range(25):
            hit = host.call('state', {})['hit']
            if hit and hit['pos'] == list(pos) and hit['face'] == 'south':
                break
            time.sleep(.025)
        else:
            raise AssertionError((pos, hit))
        host.call('input', {'key': 'use'})
        try:
            time.sleep(.15)
        finally:
            host.call('input', {'key': 'use', 'down': False})

    def restart():
        host.call('quit', {})
        deadline = time.monotonic() + 60
        while process_alive(BASE):
            if time.monotonic() > deadline:
                raise RuntimeError('Java did not exit after saving the test Belt')
            time.sleep(.2)
        assert launch(BASE)['ready']
        host.call('tick', {'frozen': True})
        for _ in range(10):
            if all(read(pos)['block'] == 'create:belt' for pos in BELT):
                return
            step(5)
        raise AssertionError('Saved Belt did not reload')

    def screenshot(label):
        host.call('camera', {'position': (CAMERA[0] + 1, CAMERA[1], CAMERA[2] + 1),
                             'target': TARGET, 'hide_gui': True})
        return host.call('capture', {'name': f'{work.name}/{label}.png', 'frames': 8})['path']

    try:
        command('gamemode creative')
        command('tp @s ' + xyz(CAMERA))
        command('forceload add ' + FORCE)
        step(25)
        return exercise(command, step, read, click, restart, screenshot)
    finally:
        command(f'item replace entity @s weapon.mainhand with {AIR}')
        command(f'kill {DROPS}')
        for area in (ROOM, EXTRA):
            command(f'fill {area} {AIR}')
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
        row = call('block', *pos)
        return dict(block=row['block'], properties=dict(re.findall(r'(\w+)=(\w+)', row['state'])),
                    nbt=command(f'data get block {xyz(pos)}'))

    def click(pos):
        camera, target = aim(pos)
        command('tp @s ' + xyz(camera))
        call('look-at', *target)
        call('wait', 3)
        hit = call('looking-at')['block']
        assert hit and hit['pos'] == list(pos) and hit['face'] == 'south', hit
        # A casing swap only changes the segment entity, not the block state.
        assert call('interact', *pos, 'south')['ok']

    def restart():
        session.restart()
        wait_loaded(call, BELT)
        command('tick freeze')

    def screenshot(label):
        path = session.scratch / (label + '.png')
        command('tp @s ' + xyz((CAMERA[0] + 1, CAMERA[1], CAMERA[2] + 1)))
        call('look-at', *TARGET)
        call('wait', 5)
        call('key', 'f1', 'tap')
        call('screenshot', path)
        call('key', 'f1', 'tap')
        assert path.stat().st_size > 1024, path
        return str(path)

    with session:
        command('tp @s ' + xyz(CAMERA))
        wait_loaded(call, BELT)
        command('forceload add ' + FORCE)
        command('tick freeze')
        return exercise(command, step, read, click, restart, screenshot)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for key in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + key, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='belt-casing-java-', dir=ROOT / '.local'))
        checks, pictures = original(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon needs --game, --resources, --ctl and --reference')
        expected = json.loads(args.reference.read_text())
        assert expected['passed'] and expected['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='belt-casing-native', world='BeltCasing')
        work = session.scratch
        try:
            checks, pictures = native(session)
            assert checks == expected['checks'], (checks, expected)
            if args.create_jar:
                assert 'local resources from Create' in session.log.read_text()
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    output = work / 'result.json'
    output.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], checks=checks,
                                     pictures=pictures), indent=2) + '\n')
    print(output)


if __name__ == '__main__':
    main()
