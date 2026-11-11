#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Check survival slime application and wrench actions through the Horizon client."""
import argparse
import json
from pathlib import Path
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded

PISTON = (935, 100, 88)
EXTENDED = (939, 100, 88)
CREATIVE = (935, 100, 91)
BASE, FIRST, SECOND, HEAD, REAR = [(x, 100, 90) for x in (938, 939, 940, 941, 937)]
PARTS = [
    (BASE, 'mechanical_piston[facing=east,state=extended]{Offset:3f}'),
    (FIRST, 'piston_extension_pole[facing=east]'),
    (SECOND, 'piston_extension_pole[facing=east]'),
    (HEAD, 'mechanical_piston_head[facing=east,type=normal]'),
    (REAR, 'piston_extension_pole[facing=east]'),
]


def review(session):
    batch = Batch()
    batch.load((936, 101, 89))
    batch.command('fill 929 100 83 942 106 95 minecraft:air')
    batch.command('fill 929 99 83 942 99 95 minecraft:stone')
    batch.put(PISTON, 'create:mechanical_piston[facing=south,axis_along_first=false]')
    batch.put(EXTENDED, 'create:mechanical_piston[facing=south,axis_along_first=false,state=extended]')
    batch.put(CREATIVE, 'create:mechanical_piston[facing=east,axis_along_first=true]')
    batch.run(session, 'piston-hand-actions')
    with session:
        call = session.call
        command = lambda line: call('command', line)

        def click(pos, face, vantage):
            command('tp @s ' + ' '.join(map(str, vantage)))
            call('wait', 5)
            call('look-at', 'block', *pos, face)
            looking = call('looking-at')['block']
            assert looking['pos'] == list(pos) and looking['face'] == face, looking
            call('mouse', 'right', 'click')
            call('wait', 8)

        def slime_count():
            return sum(slot.get('count', 0) for slot in call('inventory')['hotbar']
                       if slot.get('item') == 'minecraft:slime_ball')

        def expect(pos, name, **properties):
            state = call('block', *pos)
            assert state['block'] == 'create:' + name, state
            assert all(f'{key}={value}' in state['state'] for key, value in properties.items()), state

        wait_loaded(call, [PISTON, EXTENDED, CREATIVE])
        command('gamemode survival')
        command('clear @s')
        command('give @s minecraft:slime_ball 3')
        call('select', 1)
        assert slime_count() == 3
        click(PISTON, 'west', (932.5, 100, 88.5))
        expect(PISTON, 'mechanical_piston', facing='south', axis_along_first='false')
        assert slime_count() == 3
        click(PISTON, 'south', (935.5, 100, 90.5))
        expect(PISTON, 'sticky_mechanical_piston', facing='south', axis_along_first='false')
        assert slime_count() == 2
        click(EXTENDED, 'south', (939.5, 100, 90.5))
        expect(EXTENDED, 'mechanical_piston', state='extended')
        assert slime_count() == 2
        command('gamemode creative')
        click(CREATIVE, 'east', (938.5, 100, 91.5))
        expect(CREATIVE, 'sticky_mechanical_piston', facing='east', axis_along_first='true')
        assert slime_count() == 2
        command('clear @s')
        command('give @s create:wrench')
        call('select', 1)
        click(PISTON, 'south', (935.5, 100, 90.5))
        expect(PISTON, 'sticky_mechanical_piston', facing='south', axis_along_first='true')
        click(EXTENDED, 'west', (937.5, 100, 88.5))
        expect(EXTENDED, 'mechanical_piston', state='extended', facing='south', axis_along_first='false')
        assert call('inventory')['hotbar'][0]['item'] == 'create:wrench'
        assert 'the integrated server panicked' not in session.log.read_text()
        command('clear @s')
        call('select', 9)
        for pos, block in PARTS:
            command(f'setblock {xyz(pos)} create:{block}')
        command('tp @s 939.5 100 92.5')
        call('wait', 4)
        call('look-at', 'block', *FIRST, 'south')
        target = call('looking-at')['block']
        assert target['pos'] == list(FIRST), target
        call('mouse', 'left', 'click')
        call('wait', 10)
        assert call('block', *FIRST)['block'] == 'minecraft:air', 'Player did not break the pole'
        expect(BASE, 'mechanical_piston', state='retracted', facing='east')
        for pos in (SECOND, HEAD):
            assert call('block', *pos)['block'] == 'minecraft:air', pos
        expect(REAR, 'piston_extension_pole', facing='east')


def original():
    host = Original()
    work = Path(tempfile.mkdtemp(prefix='piston-hand-java-', dir=ROOT / '.local'))
    report = dict(create=PINS['create_revision'])
    host.call('tick', {'frozen': True})
    host.command('gamemode creative')
    host.command('gamerule fallDamage false')
    host.command('tp @s 936.5 100 90.5')
    host.command('forceload add 928 80 943 95')
    host.snapshot([PISTON], 24)
    host.command('fill 929 100 83 942 106 95 minecraft:air')
    host.command('fill 929 99 83 942 99 95 minecraft:stone')
    for pos, block in (
        (PISTON, 'mechanical_piston[facing=south,axis_along_first=false]'),
        (EXTENDED, 'mechanical_piston[facing=south,axis_along_first=false,state=extended]'),
        (CREATIVE, 'mechanical_piston[facing=east,axis_along_first=true]'),
    ):
        host.command(f'setblock {xyz(pos)} create:{block}')

    def click(key, pos, feet, aim):
        host.call('camera', {'position': feet, 'target': aim})
        host.call('capture', {'name': f'{work.name}/{len(host.trace)}.png', 'frames': 8})
        hit = host.call('state', {})['hit']
        assert tuple(hit['pos']) == pos, hit
        host.call('input', {'key': key})
        state = host.snapshot([pos], 6)[0]
        host.call('input', {'key': key, 'down': False})
        return state

    def slime(count):
        replies = host.command('data get entity @s SelectedItem')['messages']
        assert any('minecraft:slime_ball' in row and number({'nbt': row}, 'count') == count
                   for row in replies), replies

    host.command('gamemode survival')
    host.command('item replace entity @s weapon.mainhand with minecraft:slime_ball 3')
    side = click('use', PISTON, [932.5, 100, 88.5], [935.5, 100.5, 88.5])
    assert side['block'] == 'create:mechanical_piston', side
    slime(3)
    front = click('use', PISTON, [935.5, 100, 90.5], [935.5, 100.5, 88.5])
    assert front['block'] == 'create:sticky_mechanical_piston', front
    slime(2)
    blocked = click('use', EXTENDED, [939.5, 100, 90.5], [939.5, 100.5, 88.5])
    assert blocked['block'] == 'create:mechanical_piston', blocked
    slime(2)
    host.command('gamemode creative')
    created = click('use', CREATIVE, [938.5, 100, 91.5], [935.5, 100.5, 91.5])
    assert created['block'] == 'create:sticky_mechanical_piston', created
    slime(2)

    host.command('item replace entity @s weapon.mainhand with create:wrench')
    wrenched = click('use', PISTON, [935.5, 100, 90.5], [935.5, 100.5, 88.5])
    assert wrenched['properties']['axis_along_first'] == 'true', wrenched
    refused = click('use', EXTENDED, [937.5, 100, 88.5], [939.5, 100.5, 88.5])
    assert refused['properties']['state'] == 'extended', refused
    assert refused['properties']['facing'] == 'south', refused
    host.command('clear @s')
    for pos, block in PARTS:
        host.command(f'setblock {xyz(pos)} create:{block}')
    click('attack', FIRST, [939.5, 100, 92.5], [939.5, 100.5, 90.5])
    landing = host.snapshot([BASE, FIRST, SECOND, HEAD, REAR], 10)
    assert landing[0]['properties']['state'] == 'retracted', landing
    assert number(landing[0], 'Offset') == 0, landing
    assert [row['block'] for row in landing[1:]] == [
        'minecraft:air', 'minecraft:air', 'minecraft:air', 'create:piston_extension_pole'
    ], landing
    report.update(passed=True, sticky=[front, created], wrench=[wrenched, refused], teardown=landing)
    path = work / 'result.json'
    path.write_text(json.dumps(report, indent=2) + '\n')
    print(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        original()
        return
    if not (args.game and args.resources and args.ctl):
        parser.error('Horizon runs require --game, --resources and --ctl')
    session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                 name='piston-hand-actions', graphics=True,
                                 world='CreatePistonInteractionChecks', username='BearingReview')
    print(session.scratch, flush=True)
    try:
        review(session)
    finally:
        session.control_temp.cleanup()
    print(json.dumps(dict(passed=True, world=str(session.scratch))))


if __name__ == '__main__':
    main()
