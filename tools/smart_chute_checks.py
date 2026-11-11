#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare Smart Chute's plain filter, 64-item pull and powered parking."""

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


CHUTE = (1767, 110, 845)
SOURCE = (1767, 111, 845)
TARGET = (1767, 109, 845)
SIGNAL = (1768, 110, 845)
BLOCK = 'create:smart_chute'
AREA = '1763 109 841 1771 116 847'
COLUMN = '1760 832 1775 847'
STICK = 'minecraft:stick'
FILTER = f'{STICK}[minecraft:custom_data={{sample_marker:7}}] 3'
CARGO = f'{STICK}[minecraft:custom_data={{chute_marker:19}}]'


def click(host, work, name, facing, item):
    x, y, z = CHUTE
    dx, dz = {'south': (0, 1), 'north': (0, -1), 'east': (1, 0), 'west': (-1, 0)}[facing]
    feet = [x + .5 + dx * 2.4, y, z + .5 + dz * 2.4]
    aim = [x + .5 + dx * .5, y + 11 / 16, z + .5 + dz * .5]
    host.command(f'item replace entity @s weapon.mainhand with {item}')
    if isinstance(host, Native):
        call = host.session.call
        host.command(f'tp @s {xyz(feet)}')
        call('look-at', *aim)
        call('wait', 4)
        hit = call('looking-at')['block']
        assert hit['pos'] == list(CHUTE) and hit['face'] == facing, hit
        call('mouse', 'right', 'down')
        call('wait', 2)
        call('mouse', 'right', 'up')
        step(host, 1, CHUTE)
        return
    host.call('camera', {'position': feet, 'target': aim})
    host.call('capture', {'name': f'{work.name}/{name}-aim.png', 'frames': 8})
    hit = host.call('state', {})['hit']
    assert hit['pos'] == list(CHUTE) and hit['face'] == facing, hit
    host.call('input', {'kind': 'tap', 'key': 'use'})
    host.call('capture', {'name': f'{work.name}/{name}-after.png', 'frames': 10})


def inspect(chute, source, target):
    return {'powered': chute['properties']['powered'].lower() == 'true',
            'position': number(chute, 'ItemPosition'), 'cargo': items(chute['nbt'], 'Item'),
            'marked': 'chute_marker:19' in re.sub(r'\s+', '', chute['nbt']),
            'source': items(source['nbt'], 'Items'), 'target': items(target['nbt'], 'Items'),
            'target_marked': 'chute_marker:19' in re.sub(r'\s+', '', target['nbt'])}


def observe(host, count):
    if isinstance(host, Native):
        return [inspect(*step(host, 1, CHUTE, SOURCE, TARGET)) for _ in range(count)]
    result = host.call('observe_ticks', {'ticks': count, 'positions': [CHUTE, SOURCE, TARGET]})
    return [inspect(*sample['blocks']) for sample in result['samples']]


def setup(host):
    cmd = host.command
    cmd(f'fill {AREA} minecraft:air')
    cmd('fill 1764 109 842 1770 109 847 minecraft:stone')
    put(cmd, SIGNAL, 'minecraft:redstone_block')
    put(cmd, SOURCE, 'minecraft:chest')
    put(cmd, TARGET, 'minecraft:chest')
    put(cmd, CHUTE, BLOCK)
    if isinstance(host, Native):
        host.session.call('wait', 4)
    assert block(host, CHUTE)['properties'] == {'powered': 'true'}


def filter_clicks(host, work):
    host.command('gamemode survival')
    for side in ['south', 'north', 'west']:
        click(host, work, 'filter-' + side, side, FILTER)
        saved = block(host, CHUTE)
        assert items(saved['nbt'], 'Filter') == {STICK: 3}, saved
        assert 'sample_marker:7' in re.sub(r'\s+', '', saved['nbt']), saved
        assert number(saved, 'FilterAmount') == 64 and number(saved, 'UpTo') == 1, saved
        held = text(host, 'data get entity @s SelectedItem')
        assert STICK in held and number({'nbt': held}, 'count') == 3, held
    host.command('gamemode creative')


def transport(host, work, cold_restart=None):
    cmd = host.command
    for slot, stack in [(0, 'minecraft:wheat 8'), (1, CARGO + ' 30'),
                        (2, f'{STICK}[minecraft:custom_data={{chute_marker:99}}] 2'), (5, CARGO + ' 40')]:
        cmd(f'item replace block {xyz(SOURCE)} container.{slot} with {stack}')
    [idle] = observe(host, 4)[-1:]
    put(cmd, SIGNAL, 'minecraft:air')
    [loaded] = observe(host, 1)
    put(cmd, SIGNAL, 'minecraft:redstone_block')
    paused = observe(host, 5)
    if cold_restart:
        cold_restart()
        assert observe(host, 1) == paused[-1:], paused
        assert items(block(host, CHUTE)['nbt'], 'Filter') == {STICK: 3}
    put(cmd, SIGNAL, 'minecraft:air')
    resumed = observe(host, 3)
    put(cmd, SIGNAL, 'minecraft:redstone_block')
    assert idle['powered'] and not idle['cargo'] and idle['source'] == {STICK: 72, 'minecraft:wheat': 8}, idle
    assert loaded['cargo'] == {STICK: 64} and loaded['marked'] and loaded['position'] == 1, loaded
    assert loaded['source'] == {STICK: 8, 'minecraft:wheat': 8}, loaded
    assert [row['position'] for row in paused] == [.8, .6, .5, .5, .5], paused
    assert all(row['powered'] and row['cargo'] == {STICK: 64} and not row['target'] for row in paused), paused
    assert [row['position'] for row in resumed[:2]] == [.3, .10000001], resumed
    assert not resumed[-1]['cargo'] and resumed[-1]['target'] == {STICK: 64} and resumed[-1]['target_marked'], resumed
    cmd('gamemode survival')
    click(host, work, 'clear', 'south', 'minecraft:air')
    assert not items(block(host, CHUTE)['nbt'], 'Filter')
    return {'idle': idle, 'loaded': loaded, 'paused': paused, 'resumed': resumed, 'filter_cleared': True}


def open_outlet(host, work):
    setup(host)
    cmd = host.command
    put(cmd, TARGET, 'minecraft:air')
    click(host, work, 'open-outlet-filter', 'south', FILTER)
    cmd(f'data merge block {xyz(CHUTE)} {{FilterAmount:4,UpTo:0b}}')
    cmd(f'item replace block {xyz(SOURCE)} container.1 with {CARGO} 3')
    put(cmd, SIGNAL, 'minecraft:air')

    def sample():
        chute, source = step(host, 1, CHUTE, SOURCE)
        assert number(chute, 'FilterAmount') == 4 and number(chute, 'UpTo') == 0, chute
        return dict(cargo=items(chute['nbt'], 'Item'), source=items(source['nbt'], 'Items'),
                    position=number(chute, 'ItemPosition'))

    waiting = sample()
    assert not waiting['cargo'] and waiting['source'] == {STICK: 3}, waiting
    cmd(f'item replace block {xyz(SOURCE)} container.2 with {CARGO} 4')
    loaded = sample()
    assert loaded == dict(cargo={STICK: 4}, source={STICK: 3}, position=1), loaded
    return dict(waiting=waiting, loaded=loaded)


def run_java(host, work, report):
    assert json.loads((java.BASE / 'manifest.json').read_text())['create_sha256'] == java.CREATE_SHA256
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    host.command('gamemode creative')
    host.command('tp @s 1767.5 118 845.5')
    host.command(f'forceload add {COLUMN}')
    try:
        host.snapshot([CHUTE], 24)
        setup(host)
        host.snapshot([CHUTE], 4)
        filter_clicks(host, work)
        report.update(transport(host, work))
        report['open_outlet'] = open_outlet(host, work)
    finally:
        host.command('gamemode creative')
        host.command('item replace entity @s weapon.mainhand with minecraft:air')
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {COLUMN}')
        host.call('tick', {'frozen': initial['server']['frozen']})


def run_native(session, reference, report):
    host = Native(session)

    def cold_restart():
        session.restart()
        host.command('tp @s 1767.5 118 845.5')
        wait_loaded(session.call, [CHUTE])
        host.command('tick freeze')

    with session:
        host.command('tp @s 1767.5 118 845.5')
        wait_loaded(session.call, [CHUTE])
        host.command('tick freeze')
        setup(host)
        step(host, 4, CHUTE)
        filter_clicks(host, session.scratch)
        observed = transport(host, session.scratch, cold_restart)
        observed['open_outlet'] = open_outlet(host, session.scratch)
        assert observed == {key: reference[key] for key in observed}, (observed, reference)
        report.update(observed, cold_restart=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    report = {'passed': False, 'create': PINS['create_revision']}
    session = None
    if args.game:
        if not all((args.resources, args.ctl, args.reference)):
            parser.error('Native checks require --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == report['create'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='smart-chute-native', world='CreateSmartChute')
        work = session.scratch
        report.update(game=str(args.game.resolve()), reference=str(args.reference.resolve()))
    else:
        host = Original()
        work = Path(tempfile.mkdtemp(prefix='smart-chute-java-', dir=ROOT / '.local'))
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
