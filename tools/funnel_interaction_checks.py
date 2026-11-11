#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare secondary Wrench pickup and observe Java's airborne Funnel intake."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from burner_heat_java_checks import items, number
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from funnel_checks import ALL_DROPS, AREA, BLOCK, COLUMN, INPUT, STICK, TARGET, block, put, state, text
from native_check_session import NativeCheckSession, wait_loaded
import reference_java as java


SIGNAL = (1739, 112, 823)
FEET = (1740.5, 113, 825.5)
AIM = (1740.5, 112.48, 823.5)
WRENCH = 'create:wrench'
AIRBORNE = '@e[type=minecraft:item,tag=create_funnel_airborne,limit=1]'


def sample(host, ticks):
    funnel, chest = host.call('observe_ticks', {
        'ticks': ticks, 'positions': [INPUT, TARGET],
    })['samples'][-1]['blocks']
    return {'powered': funnel['properties']['powered'] == 'true', 'items': items(chest['nbt'], 'Items')}


def airborne(host):
    cmd = host.command
    put(cmd, TARGET, 'minecraft:chest')
    put(cmd, SIGNAL, 'minecraft:redstone_block')
    put(cmd, INPUT, state('up', False, True))
    cmd('summon minecraft:item 1740.5 112.8 823.5 {NoGravity:1b,PickupDelay:32767s,'
        'Motion:[0.0d,0.0d,0.0d],Tags:["create_funnel_airborne"],'
        'Item:{id:"minecraft:stick",count:7,components:{"minecraft:custom_data":{funnel_airborne:43}}}}')
    paused = sample(host, 4)
    in_flight = text(host, f'data get entity {AIRBORNE} Pos')
    assert paused == {'powered': True, 'items': {}}, paused
    assert '112.8d' in in_flight, in_flight
    put(cmd, SIGNAL, 'minecraft:air')
    admitted = sample(host, 1)
    assert admitted == {'powered': False, 'items': {STICK: 7}}, admitted
    assert 'funnel_airborne:43' in block(host, TARGET)['nbt'].replace(' ', '')
    assert not host.call('entities', {'center': [1740.5, 112.8, 823.5], 'radius': 1})['entities'], admitted
    return {'stationary_y': 112.8, 'collision_top_y': 112.625, 'paused': paused, 'next_tick': admitted}


def sneak_click(host, work, mode):
    if isinstance(host, Native):
        call = host.session.call
        host.command(f'tp @s {xyz(FEET)}')
        call('look-at', *AIM)
        call('wait', 4)
        hit = call('looking-at')['block']
        assert hit['pos'] == list(INPUT), hit
        call('key', 'shift', 'down')
        try:
            call('mouse', 'right', 'click')
            call('wait', 4)
        finally:
            call('key', 'shift', 'up')
        return
    host.call('camera', {'position': FEET, 'target': AIM})
    host.call('capture', {'name': f'{work.name}/wrench-{mode}-before.png', 'frames': 8})
    hit = host.call('state', {})['hit']
    assert hit['pos'] == list(INPUT), hit
    host.call('input', {'key': 'shift', 'down': True})
    try:
        host.call('input', {'key': 'use', 'down': True})
        host.call('capture', {'name': f'{work.name}/wrench-{mode}-after.png', 'frames': 6})
    finally:
        host.call('input', {'key': 'use', 'down': False})
        host.call('input', {'key': 'shift', 'down': False})


def pickup(host, work):
    cmd = host.command
    cmd('fill 1738 112 825 1742 112 826 minecraft:stone')
    result = {}
    for mode, expected in [('survival', 1), ('creative', 0)]:
        cmd('gamemode ' + mode)
        cmd('clear @s')
        cmd(f'item replace entity @s weapon.mainhand with {WRENCH}')
        put(cmd, INPUT, state('up', False))
        sneak_click(host, work, mode)
        placed = block(host, INPUT)
        contents = text(host, 'data get entity @s Inventory').partition(': ')[2]
        inventory = items('{Inventory:' + contents + '}', 'Inventory')
        held = text(host, 'data get entity @s SelectedItem')
        assert placed['id'] == 'minecraft:air' and inventory.get(BLOCK, 0) == expected, (placed, inventory)
        assert WRENCH in held and number({'nbt': held}, 'count') == 1 and 'minecraft:damage' not in held, held
        assert 'funnel_duplicate_drop' not in text(host, f'execute if entity {ALL_DROPS} run say funnel_duplicate_drop')
        result[mode] = {'removed': True, 'returned': expected, 'wrench_count': 1}
    return result


def run_java(host, work, report):
    assert json.loads((java.BASE / 'manifest.json').read_text())['create_sha256'] == java.CREATE_SHA256
    original = host.call('state', {})
    assert original['ready'] and original['data_version'] == 3955, original
    host.call('tick', {'frozen': True})
    host.command('gamemode creative')
    host.command('tp @s 1740.5 118 823.5')
    host.command(f'forceload add {COLUMN}')
    try:
        host.snapshot([INPUT], 24)
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'kill {ALL_DROPS}')
        report['airborne'] = airborne(host)
        report['pickup'] = pickup(host, work)
    finally:
        host.command('gamemode creative')
        host.command('clear @s')
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'kill {ALL_DROPS}')
        host.command(f'forceload remove {COLUMN}')
        host.call('tick', {'frozen': original['server']['frozen']})


def run_native(session, reference, report):
    host = Native(session)
    with session:
        host.command('tp @s 1740.5 118 823.5')
        wait_loaded(session.call, [INPUT])
        host.command('tick freeze')
        host.command(f'fill {AREA} minecraft:air')
        report['pickup'] = pickup(host, session.scratch)
        assert report['pickup'] == reference['pickup'], (report, reference)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    session = None
    report = {'passed': False, 'create': PINS['create_revision']}
    if args.game:
        if not all((args.resources, args.ctl, args.reference)):
            parser.error('Native checks require --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == report['create'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='funnel-interactions-native', world='CreateAndesiteFunnelWrench')
        work = session.scratch
        report.update(game=str(args.game.resolve()), reference=str(args.reference.resolve()))
    else:
        host = Original()
        work = Path(tempfile.mkdtemp(prefix='funnel-interactions-java-', dir=ROOT / '.local'))
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
