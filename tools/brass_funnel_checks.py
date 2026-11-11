#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare Brass Funnel's plain filter, default and configured extraction."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from burner_heat_java_checks import items, number
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from funnel_checks import block, put, step, text
from native_check_session import NativeCheckSession, wait_loaded
import reference_java as java
import smart_chute_checks as smart


FUNNEL = (1815, 110, 865)
SOURCE = (1815, 111, 865)
SIGNAL = (1814, 110, 865)
AREA = '1812 108 862 1819 116 870'
COLUMN = '1808 864 1823 879'
BLOCK = 'create:brass_funnel'
STICK = 'minecraft:stick'
DROPS = '@e[type=minecraft:item,x=1814,y=108,z=864,dx=2,dy=4,dz=2]'
PLAYER = (1815.5, 109, 867.7)
AIM = (1815.5, 110.875, 865.969)


def marked(key, count):
    return f'{STICK}[minecraft:custom_data={{brass_probe:{key}}}] {count}'


def aim(host, work, name):
    if isinstance(host, Native):
        call = host.session.call
        host.command(f'tp @s {xyz(PLAYER)}')
        call('look-at', *AIM)
        call('wait', 4)
        hit = call('looking-at')['block']
        assert hit['pos'] == list(FUNNEL) and hit['face'] == 'south', hit
        return
    host.call('camera', {'position': PLAYER, 'target': AIM, 'gui_scale': 4})
    host.call('capture', {'name': f'{work.name}/{name}-aim.png', 'frames': 8})
    hit = host.call('state', {})['hit']
    assert hit['pos'] == list(FUNNEL) and hit['face'] == 'south', hit


def tap_filter(host, work, *, item=marked(7, 3), expected=None, case='filter'):
    original = items(block(host, FUNNEL)['nbt'], 'Filter')
    host.command(f'item replace entity @s weapon.mainhand with {item}')
    aim(host, work, case)
    if isinstance(host, Native):
        call = host.session.call
        call('mouse', 'right', 'down')
        call('wait', 2)
        assert items(block(host, FUNNEL)['nbt'], 'Filter') == original
        call('mouse', 'right', 'up')
        step(host, 1)
        call('wait', 12)
        ghost = str(work / f'{case}-ghost.png')
        call('screenshot', ghost)
    else:
        host.call('input', {'kind': 'tap', 'key': 'use'})
        ghost = host.call('capture', {'name': f'{work.name}/{case}-ghost.png', 'frames': 12})['path']
    raw = block(host, FUNNEL)['nbt']
    expected = expected if expected is not None else {STICK: 3}
    assert items(raw, 'Filter') == expected, raw
    if item.startswith(STICK):
        assert 'brass_probe:7' in re.sub(r'\s+', '', raw), raw
    held = text(host, 'data get entity @s SelectedItem')
    (key, count), = expected.items()
    assert key in held and number({'nbt': held}, 'count') == count, held
    return ghost


def board(host, work, row, *, pos=FUNNEL, aim_at=aim, maximum=64, value=16, case='', confirm=True):
    name = f'board-{row}{case}'
    aim_at(host, work, name)
    original = block(host, pos)
    original_filter = items(original['nbt'], 'Filter')
    expected_cursor = 'Any' if row == 0 and value == maximum else f'{"=" if row else "≤"}{max(value, 1)}'
    if isinstance(host, Native):
        call = host.session.call
        prefix = 'Create filter board: '

        def trace():
            rows = [json.loads(line.split(prefix, 1)[1]) for line in host.session.log.read_text().splitlines()
                    if prefix in line]
            assert rows and rows[-1]['pos'] == list(pos), rows[-1:]
            return rows[-1]

        call('mouse', 'right', 'down')
        call('wait', 9)
        assert call('screen')['screen'] == 'mod', call('screen')
        initial = trace()
        assert initial['title'] == 'Extracted Amount' and initial['size'][1] == 22, initial
        assert initial['tip'] == 'Release Right Button to Confirm', initial
        left, top = initial['origin']
        bar = (maximum + 1) * 2 + 1 + (maximum // 16 + 1) * 4
        label = initial['size'][0] - 24 - bar
        horizontal = left + ((max(1, value) - 1) // 16) * 4 + value * 2 + 1.5 + label + 18
        point = (horizontal + (2 if value % 16 == 0 else 0) + (4 if value > 0 else 0), top + row * 11 + 5.)
        call('click-at', *point)
        call('wait', 3)
        assert call('screen')['screen'] == 'mod'
        assert items(block(host, pos)['nbt'], 'Filter') == original_filter
        hovered = trace()
        assert (hovered['row'], hovered['value'], hovered['cursor']) == (row, value, expected_cursor), hovered
        call('screenshot', work / f'{name}.png')
        if confirm:
            call('click-at', *point, 'right')
        else:
            call('key', 'escape', 'tap')
        call('release')
        step(host, 1)
        call('wait', 8)
        assert call('screen')['screen'] == 'playing'
        call('screenshot', work / f'{name}-done.png')
    else:
        host.call('input', {'key': 'use', 'down': True})
        try:
            for _ in range(6):
                host.call('capture', {'name': f'{work.name}/{name}.png', 'frames': 12})
                ui = host.call('ui', {})
                if 'value_settings' in ui:
                    break
            settings = ui['value_settings']
            assert settings['max_value'] == maximum and settings['milestone_interval'] == 16, settings
            assert settings['title']['text'] == 'Extracted Amount', settings
            assert [row['text'] for row in settings['rows']] == ['Up to', 'Exactly'], settings
            point = next(r['gui_coordinate'] for r in settings['sample_coordinates']
                         if r['row'] == row and r['value'] == value)
            host.call('input', {'kind': 'move', 'x': point[0], 'y': point[1]})
            host.call('capture', {'name': f'{work.name}/{name}-{value}.png', 'frames': 6})
            hovered = host.call('ui', {})['value_settings']['hovered']
            assert hovered['row'] == row and hovered['value'] == value, hovered
            assert items(block(host, pos)['nbt'], 'Filter') == original_filter
            if confirm:
                host.call('input', {'kind': 'mouse', 'button': 1, 'x': point[0], 'y': point[1], 'down': False})
            else:
                host.call('input', {'kind': 'escape'})
        finally:
            host.call('input', {'key': 'use', 'down': False})
        host.call('capture', {'name': f'{work.name}/{name}-done.png', 'frames': 8})
    configured = block(host, pos)
    if not confirm:
        for key in ('FilterAmount', 'UpTo'):
            assert number(configured, key) == number(original, key), configured
        assert items(configured['nbt'], 'Filter') == original_filter, configured
        return {'title': 'Extracted Amount', 'cancelled': [row, value]}
    assert number(configured, 'FilterAmount') == max(1, value) and number(configured, 'UpTo') == (1 - row), configured
    assert items(configured['nbt'], 'Filter') == original_filter, configured
    return {'title': 'Extracted Amount', 'selected': [row, value]}


def samples(host, count):
    if isinstance(host, Native):
        observed = [step(host, 1, FUNNEL, SOURCE) for _ in range(count)]
    else:
        reply = host.call('observe_ticks', {'ticks': count, 'positions': [FUNNEL, SOURCE]})
        observed = [sample['blocks'] for sample in reply['samples']]
    return [{'powered': funnel['properties']['powered'] == 'true',
             'cooldown': int(number(funnel, 'TransferCooldown')),
             'source': items(chest['nbt'], 'Items')}
            for funnel, chest in observed]


def output(host, marker, count):
    data = text(host, f'data get entity {DROPS[:-1]},limit=1] Item')
    assert STICK in data and f'brass_probe:{marker}' in re.sub(r'\s+', '', data), data
    assert number({'nbt': data}, 'count') == count, data
    return [marker, count]


def default_pull(host):
    cmd = host.command
    cmd(f'kill {DROPS}')
    put(cmd, FUNNEL, 'minecraft:air')
    put(cmd, SOURCE, 'minecraft:air')
    put(cmd, SOURCE, 'minecraft:barrel')
    cmd(f'kill {DROPS}')
    put(cmd, FUNNEL, f'{BLOCK}[facing=down,extracting=true,powered=true,waterlogged=false]')
    for slot, count in [(1, 43), (4, 29)]:
        cmd(f'item replace block {xyz(SOURCE)} container.{slot} with {marked(39, count)}')
    samples(host, 4)
    put(cmd, SIGNAL, 'minecraft:air')
    [pulled] = samples(host, 1)
    assert pulled == {'powered': False, 'cooldown': 8, 'source': {STICK: 8}}, pulled
    return {'pull': pulled, 'output': output(host, 39, 64)}


def exercise(host, work, report, cold_restart=None):
    cmd = host.command
    cmd(f'fill {AREA} minecraft:air')
    cmd('fill 1813 108 863 1818 108 869 minecraft:stone')
    cmd(f'kill {DROPS}')
    put(cmd, SIGNAL, 'minecraft:redstone_block')
    put(cmd, SOURCE, 'minecraft:barrel')
    put(cmd, FUNNEL, f'{BLOCK}[facing=down,extracting=true,powered=true,waterlogged=false]')
    samples(host, 4)
    cmd('gamemode survival')
    report['filter_ghost'] = tap_filter(host, work)
    cmd('item replace entity @s weapon.mainhand with minecraft:wheat 5')
    report['exact_board'] = board(host, work, 1)
    for slot, stack in [(0, 'minecraft:wheat 8'), (1, marked(31, 6)), (4, marked(82, 18))]:
        cmd(f'item replace block {xyz(SOURCE)} container.{slot} with {stack}')
    put(cmd, SIGNAL, 'minecraft:air')
    cycle = samples(host, 11)
    assert cycle == [{'powered': False, 'cooldown': max(0, 8 - i), 'source': {STICK: 8, 'minecraft:wheat': 8}}
                     for i in range(11)], cycle
    report['exact'] = {'cycle': cycle, 'output': output(host, 82, 16)}
    cmd(f'kill {DROPS}')
    [starved] = samples(host, 1)
    assert starved == cycle[-1], starved
    report['exact']['insufficient'] = starved
    put(cmd, SIGNAL, 'minecraft:redstone_block')
    samples(host, 1)
    if cold_restart:
        cold_restart()
        restored = block(host, FUNNEL)
        assert items(restored['nbt'], 'Filter') == {STICK: 3}, restored
        assert number(restored, 'FilterAmount') == 16 and number(restored, 'UpTo') == 0, restored
        report['cold_restart'] = True
    report['up_to_board'] = board(host, work, 0)
    report['cancel_board'] = board(host, work, 1, value=32, case='-cancel', confirm=False)
    cmd(f'item replace block {xyz(SOURCE)} container.1 with {marked(31, 7)}')
    put(cmd, SIGNAL, 'minecraft:air')
    [up_to] = samples(host, 1)
    assert up_to == {'powered': False, 'cooldown': 8, 'source': {STICK: 2, 'minecraft:wheat': 8}}, up_to
    put(cmd, SIGNAL, 'minecraft:redstone_block')
    [paused] = samples(host, 1)
    assert paused == {'powered': True, 'cooldown': 0, 'source': {STICK: 2, 'minecraft:wheat': 8}}, paused
    report['up_to'] = {'pull': up_to, 'output': output(host, 31, 7), 'paused': paused}
    report['default'] = default_pull(host)
    put(cmd, SIGNAL, 'minecraft:redstone_block')
    samples(host, 1)
    report['replacement_ghost'] = tap_filter(host, work, item='minecraft:snowball 4',
                                             expected={'minecraft:snowball': 4}, case='snowball')
    report['snowball_board'] = board(host, work, 0, maximum=16, case='-snowball')


def smart_aim(host, work, name):
    x, y, z = smart.CHUTE
    feet, target = (x + .5, y, z + 2.9), (x + .5, y + 11 / 16, z + 1.)
    if isinstance(host, Native):
        call = host.session.call
        host.command(f'tp @s {xyz(feet)}')
        call('look-at', *target)
        call('wait', 4)
        hit = call('looking-at')['block']
    else:
        host.call('camera', {'position': feet, 'target': target, 'gui_scale': 4})
        host.call('capture', {'name': f'{work.name}/{name}-aim.png', 'frames': 8})
        hit = host.call('state', {})['hit']
    assert hit['pos'] == list(smart.CHUTE) and hit['face'] == 'south', hit


def smart_amounts(host, work):
    cmd = host.command
    cmd('gamemode creative')
    cmd('tp @s 1767.5 118 845.5')
    if isinstance(host, Native):
        wait_loaded(host.session.call, [smart.CHUTE])
    else:
        host.snapshot([smart.CHUTE], 16)
    smart.setup(host)
    step(host, 4, smart.CHUTE)
    cmd('gamemode survival')
    smart.click(host, work, 'smart-filter-south', 'south', smart.FILTER)
    step(host, 1, smart.CHUTE)
    assert items(block(host, smart.CHUTE)['nbt'], 'Filter') == {STICK: 3}
    cmd('item replace entity @s weapon.mainhand with minecraft:wheat 5')
    # The amount board follows the source chest even with no destination.
    put(cmd, smart.TARGET, 'minecraft:air')
    exact_board = board(host, work, 1, pos=smart.CHUTE, aim_at=smart_aim, case='-smart')
    put(cmd, smart.TARGET, 'minecraft:chest')
    for slot, stack in [(0, 'minecraft:wheat 8'), (1, marked(31, 6)), (4, marked(82, 18))]:
        cmd(f'item replace block {xyz(smart.SOURCE)} container.{slot} with {stack}')
    put(cmd, smart.SIGNAL, 'minecraft:air')
    [exact, source] = step(host, 1, smart.CHUTE, smart.SOURCE)
    assert items(exact['nbt'], 'Item') == {STICK: 16} and 'brass_probe:82' in re.sub(r'\s+', '', exact['nbt']), exact
    assert items(source['nbt'], 'Items') == {STICK: 8, 'minecraft:wheat': 8}, source
    [idle, target] = step(host, 8, smart.CHUTE, smart.TARGET)
    assert not items(idle['nbt'], 'Item'), idle
    assert items(target['nbt'], 'Items') == {STICK: 16}, target
    put(cmd, smart.SIGNAL, 'minecraft:redstone_block')
    step(host, 1, smart.CHUTE)
    up_to_board = board(host, work, 0, pos=smart.CHUTE, aim_at=smart_aim, case='-smart')
    cmd(f'item replace block {xyz(smart.SOURCE)} container.1 with {marked(31, 7)}')
    put(cmd, smart.SIGNAL, 'minecraft:air')
    [up_to, source] = step(host, 1, smart.CHUTE, smart.SOURCE)
    assert items(up_to['nbt'], 'Item') == {STICK: 7} and 'brass_probe:31' in re.sub(r'\s+', '', up_to['nbt']), up_to
    assert items(source['nbt'], 'Items') == {STICK: 2, 'minecraft:wheat': 8}, source
    return {'exact_board': exact_board, 'up_to_board': up_to_board,
            'exact': [82, 16], 'up_to': [31, 7]}


def run_java(host, work, report):
    assert json.loads((java.BASE / 'manifest.json').read_text())['create_sha256'] == java.CREATE_SHA256
    original = host.call('state', {})
    assert original['ready'] and original['data_version'] == 3955, original
    host.call('tick', {'frozen': True})
    host.command('gamemode creative')
    host.command('tp @s 1815.5 118 865.5')
    host.command(f'forceload add {COLUMN}')
    host.command(f'forceload add {smart.COLUMN}')
    try:
        host.snapshot([FUNNEL], 24)
        exercise(host, work, report)
        report['smart'] = smart_amounts(host, work)
    finally:
        if host.call('state', {})['screen'] != 'playing':
            host.call('input', {'kind': 'escape'})
        host.command('gamemode creative')
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'fill {smart.AREA} minecraft:air')
        host.command(f'kill {DROPS}')
        host.command(f'forceload remove {COLUMN}')
        host.command(f'forceload remove {smart.COLUMN}')
        host.call('camera', {key: original[key] for key in ('position', 'yaw', 'pitch', 'gui_scale')})
        host.call('tick', {'frozen': original['server']['frozen']})


def run_native(session, reference, report):
    host = Native(session)

    def cold_restart():
        session.restart()
        host.command('tp @s 1815.5 118 865.5')
        wait_loaded(session.call, [FUNNEL, SOURCE])
        host.command('tick freeze')

    with session:
        host.command('tp @s 1815.5 118 865.5')
        wait_loaded(session.call, [FUNNEL, SOURCE])
        host.command('tick freeze')
        exercise(host, session.scratch, report, cold_restart)
        report['smart'] = smart_amounts(host, session.scratch)
        for field in ('exact_board', 'up_to_board', 'cancel_board', 'snowball_board', 'exact', 'up_to', 'default', 'smart'):
            assert report[field] == reference[field], (field, report[field], reference[field])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    session = None
    report = {'passed': False, 'create': PINS['create_revision']}
    if args.game:
        if not all((args.resources, args.ctl, args.reference)):
            parser.error('Native checks require --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == report['create'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='brass-funnel-native', world='CreateBrassFunnel')
        work = session.scratch
        (work / 'options.txt').write_text('lang:en_us\nguiScale:4\ntutorialStep:none\nchatVisibility:2\n')
        report.update(game=str(args.game.resolve()), reference=str(args.reference.resolve()))
    else:
        host = Original()
        work = Path(tempfile.mkdtemp(prefix='brass-funnel-java-', dir=ROOT / '.local'))
    print(work, flush=True)
    try:
        if session:
            run_native(session, reference, report)
        else:
            run_java(host, work, report)
        report['passed'] = True
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        if session:
            for generated in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(generated, ignore_errors=True)
                if generated.exists():
                    shutil.rmtree(generated)
        else:
            (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
        print(work / 'result.json', flush=True)


if __name__ == '__main__':
    main()
