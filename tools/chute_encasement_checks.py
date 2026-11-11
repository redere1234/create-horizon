#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare survival encasement and loaded cargo on a dry vertical Chute.

The native run additionally closes and reopens its disposable world. Diagonal
and waterlogged Chutes are outside the current native transport scope.
"""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from burner_heat_java_checks import items, number
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded
import reference_java as java


CHUTE = (1496, 110, 770)
INLET = (1496, 111, 770)
OUTLET = (1496, 109, 770)
PLAYER = (1496.5, 109, 773.5)
AIM = (1496.5, 110.5, 770.5)
COLUMN = '1488 768 1503 783'
AREA = '1493 109 768 1499 113 775'
CASING = 'create:industrial_iron_block'
WRENCH = 'create:wrench'
MARKER = 'encase_probe:43'
STICKS = {'minecraft:stick': 7}


def setup(command):
    command(f'fill {AREA} minecraft:air')
    command('fill 1493 108 768 1499 108 775 minecraft:stone')
    command(f'setblock {xyz(OUTLET)} minecraft:stone')
    command(f'setblock {xyz(CHUTE)} create:chute[facing=down,shape=normal,waterlogged=false]')
    command(f'setblock {xyz(INLET)} minecraft:chest')
    command(f'item replace block {xyz(INLET)} container.0 with '
            'minecraft:stick[minecraft:custom_data={encase_probe:43}] 7')
    command(f'tp @s {xyz(PLAYER)}')
    command('gamemode survival')


def cargo(chute):
    nbt = chute['nbt']
    properties = chute['properties']
    assert chute['block'] == 'create:chute' and properties['facing'] == 'down', chute
    assert properties['waterlogged'] == 'false', chute
    return {'shape': properties['shape'], 'items': items(nbt, 'Item'),
            'marker': MARKER in re.sub(r'\s+', '', nbt), 'position': number(chute, 'ItemPosition')}


def expect_cargo(chute, shape):
    observed = cargo(chute)
    expected = {'shape': shape, 'items': STICKS, 'marker': True, 'position': 0.5}
    assert observed == expected, (expected, observed, chute)
    return observed


def exercise(host, click, selected):
    before, = host.snapshot([CHUTE], 16)
    cases = [expect_cargo(before, 'normal')]
    for item, count, shape in [(CASING, 2, 'encased'), (WRENCH, 1, 'normal'),
                               (WRENCH, 1, 'window'), (CASING, 2, 'encased')]:
        host.command(f'item replace entity @s weapon.mainhand with {item} {count}')
        click()
        observed, = host.snapshot([CHUTE], 3)
        held = selected()
        assert item in held and re.search(rf'\bcount\s*:\s*{count}\b', held), held
        cases.append(expect_cargo(observed, shape) | {'tool': item, 'held_count': count})
    return cases


def release(host):
    host.command(f'setblock {xyz(OUTLET)} minecraft:chest')
    chute, chest = host.snapshot([CHUTE, OUTLET], 18)
    result = {'shape': chute['properties']['shape'], 'remaining': items(chute['nbt'], 'Item'),
              'delivered': items(chest['nbt'], 'Items'),
              'marker': MARKER in re.sub(r'\s+', '', chest['nbt'])}
    assert result == {'shape': 'encased', 'remaining': {}, 'delivered': STICKS, 'marker': True}, result
    return result


def run_java(host, work):
    manifest = json.loads((java.BASE / 'manifest.json').read_text())
    assert manifest['create_sha256'] == java.CREATE_SHA256
    before = host.call('state', {})
    if before.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        before = host.call('state', {})
    assert before['ready'] and before['data_version'] == 3955, before
    captures = iter(range(4))

    def click():
        n = next(captures)
        host.call('camera', {'position': PLAYER, 'target': AIM})
        host.call('capture', {'name': f'{work.name}/before-{n}.png', 'frames': 8})
        hit = host.call('state', {})['hit']
        assert hit['pos'] == list(CHUTE) and hit['face'] == 'south', hit
        host.call('input', {'key': 'use'})
        try:
            host.call('capture', {'name': f'{work.name}/after-{n}.png', 'frames': 6})
        finally:
            host.call('input', {'key': 'use', 'down': False})

    host.call('tick', {'frozen': True})
    host.command('gamemode creative')
    host.command(f'tp @s {xyz(PLAYER)}')
    host.command(f'forceload add {COLUMN}')
    try:
        host.snapshot([CHUTE], 24)
        setup(host.command)
        cases = exercise(host, click, lambda: ' '.join(
            host.command('data get entity @s SelectedItem')['messages']))
        return {'cases': cases, 'release': release(host)}
    finally:
        host.command('gamemode creative')
        host.command('item replace entity @s weapon.mainhand with minecraft:air')
        host.command(f'fill {AREA} minecraft:air')
        host.command('fill 1493 108 768 1499 108 775 minecraft:air')
        host.command(f'forceload remove {COLUMN}')
        host.call('tick', {'frozen': before['server']['frozen']})


def run_native(session, reference):
    host, call = Native(session), session.call

    def click():
        call('look-at', *AIM)
        call('wait', 3)
        call('mouse', 'right', 'click')
        call('wait', 4)

    with session:
        host.command(f'tp @s {xyz(PLAYER)}')
        wait_loaded(call, [CHUTE])
        setup(host.command)
        cases = exercise(host, click, lambda: ' '.join(
            host.command('data get entity @s SelectedItem')['chat']))
        assert cases == reference['cases'], (cases, reference['cases'])
        session.restart()
        host.command(f'tp @s {xyz(PLAYER)}')
        wait_loaded(call, [CHUTE])
        [restarted] = host.snapshot([CHUTE], 3)
        persisted = expect_cargo(restarted, 'encased')
        result = release(host)
        assert result == reference['release'], (result, reference['release'])
        return {'cases': cases, 'release': result, 'cold_restart': persisted}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    report = dict(passed=False, create=PINS['create_revision'])
    session = None
    if args.java:
        host = Original()
        work = Path(tempfile.mkdtemp(prefix='chute-encasement-java-', dir=ROOT / '.local'))
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon checks require --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == report['create'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='chute-encasement-native', world='CreateChuteEncasement')
        work = session.scratch
        report['reference'] = str(args.reference.resolve())
        report['game'] = str(args.game.resolve())
    print(work, flush=True)
    try:
        result = run_java(host, work) if args.java else run_native(session, reference)
        report.update(result, passed=True)
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        if not session:
            (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        print(work / 'result.json', flush=True)
        if session:
            for generated in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(generated, ignore_errors=True)
                if generated.exists():
                    shutil.rmtree(generated)


if __name__ == '__main__':
    main()
