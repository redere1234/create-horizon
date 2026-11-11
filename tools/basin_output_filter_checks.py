#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare actual Basin recipe-filter clicks and Mixer consumption in both clients."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from burner_heat_java_checks import items, number
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded

BASIN = (456, 98, 18)
MIXER = (456, 100, 18)
MOTOR = (455, 99, 18)
AREA = '452 98 14 460 104 22'
WRONG = 'minecraft:andesite'
ALLOY = 'create:andesite_alloy'
NUGGET = 'minecraft:iron_nugget'
VIEWS = {
    'south': ((456.5, 98, 21.5), (456.5, 98.75, 19)),
    'north': ((456.5, 98, 15.5), (456.5, 98.75, 18)),
    'east': ((459.5, 98, 18.5), (457, 98.75, 18.5)),
}


def place(host, pos, block):
    host.command(f'setblock {xyz(pos)} {block}')


def setup(host):
    host.command(f'fill {AREA} minecraft:air')
    host.command('fill 452 97 14 460 97 22 minecraft:smooth_stone')
    place(host, BASIN, 'create:basin[facing=down]')
    place(host, MIXER, 'create:mechanical_mixer')
    place(host, (455, 100, 18), 'create:cogwheel[axis=y,waterlogged=false]')


def observe(host, ticks):
    basin, mixer = host.snapshot([BASIN, MIXER], ticks)
    nbt = basin['nbt']
    return dict(filter=items(nbt, 'Filter'),
                input=items(nbt, 'InputItems'), output=items(nbt, 'OutputItems'),
                running=bool(number(mixer, 'Running')))


def set_hand(host, item, count=1):
    stack = f'{item} {count}' if item else 'minecraft:air'
    host.command(f'item replace entity @s weapon.mainhand with {stack}')


def exercise(host, click, restart=None):
    rows = {}
    set_hand(host, WRONG, 3)
    click('south')
    rows['set'] = observe(host, 5)
    assert rows['set']['filter'] == {WRONG: 3}, rows
    host.command(f'data merge block {xyz(BASIN)} {{InputItems:{{Size:9,Items:'
                 f'[{{Slot:0b,id:"{WRONG}",count:2}},{{Slot:1b,id:"{NUGGET}",count:2}}]}}}}')
    place(host, MOTOR, 'create:creative_motor[facing=up]{ScrollValue:32}')
    rows['blocked'] = observe(host, 140)
    assert rows['blocked'] == dict(filter={WRONG: 3}, input={WRONG: 2, NUGGET: 2},
                                   output={}, running=False), rows
    if restart is not None:
        restart()
        assert observe(host, 8) == rows['blocked']

    set_hand(host, ALLOY)
    click('north')
    for _ in range(4):
        rows['started'] = observe(host, 7)
        if rows['started']['running']:
            break
    assert rows['started'] == dict(filter={ALLOY: 1}, input={WRONG: 2, NUGGET: 2},
                                   output={}, running=True), rows
    set_hand(host, WRONG)
    click('south')
    rows['completed_current'] = observe(host, 150)
    assert rows['completed_current'] == dict(filter={WRONG: 1}, input={WRONG: 1, NUGGET: 1},
                                             output={ALLOY: 1}, running=False), rows

    set_hand(host, None)
    click('east')
    rows['cleared'] = observe(host, 150)
    assert rows['cleared'] == dict(filter={}, input={}, output={ALLOY: 2}, running=False), rows
    return rows


def original(work):
    host = Original()
    initial = host.call('state', {})
    if initial.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955
    region = '448 0 463 31'

    def click(side):
        feet, aim = VIEWS[side]
        host.call('camera', {'position': feet, 'target': aim, 'hide_gui': False})
        for _ in range(5):
            host.snapshot([BASIN], 2)
            hit = host.call('state', {})['hit']
            if tuple(hit['pos']) == BASIN and hit['face'] == side:
                break
        assert tuple(hit['pos']) == BASIN and hit['face'] == side, hit
        host.call('input', {'key': 'use'})
        host.snapshot([BASIN], 2)
        host.call('input', {'key': 'use', 'down': False})

    try:
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        host.command('forceload add ' + region)
        host.snapshot([BASIN], 25)
        setup(host)
        return exercise(host, click)
    finally:
        host.call('input', {'key': 'use', 'down': False})
        host.command(f'fill {AREA} minecraft:air')
        host.command('forceload remove ' + region)
        host.call('camera', {'position': initial['position'], 'yaw': initial['yaw'],
                             'pitch': initial['pitch'], 'hide_gui': False})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session):
    host = Native(session)
    call = session.call

    def move(side):
        feet, aim = VIEWS[side]
        host.command('tp @s ' + xyz(feet))
        wait_loaded(call, [BASIN, (452, 98, 14)])
        call('look-at', *aim)

    def click(side):
        move(side)
        call('wait', 2)
        hit = call('looking-at')['block']
        assert tuple(hit['pos']) == BASIN and hit['face'] == side, hit
        call('mouse', 'right', 'click')

    def restart():
        call('save')
        session.restart()
        move('south')

    try:
        with session:
            host.command('gamemode creative')
            move('south')
            setup(host)
            return exercise(host, click, restart)
    finally:
        session.control_temp.cleanup()
        for folder in (session.resources, session.scratch / '.horizon-cache', session.scratch / 'horizon-mods'):
            shutil.rmtree(folder, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='basin-output-filter-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        rows = original(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon runs require --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='basin-output-filter-native', world='BasinOutputFilter')
        work = session.scratch
        print(work, flush=True)
        rows = native(session)
        assert rows == reference['rows'], (rows, reference['rows'])
    result = dict(passed=True, create=PINS['create_revision'], rows=rows)
    (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
