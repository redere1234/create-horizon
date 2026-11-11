#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare dry ordinary Andesite Funnels in real Java and Horizon clients."""

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


BLOCK = 'create:andesite_funnel'
MARKED = 'minecraft:stick[minecraft:custom_data={funnel_probe:43}]'
STICK = 'minecraft:stick'
OUT = (1735, 110, 823)
SOURCE = (1735, 111, 823)
SIGNAL = (1734, 110, 823)
INPUT = (1740, 112, 823)
TARGET = (1740, 111, 823)
AREA = '1731 108 819 1742 117 827'
COLUMN = '1728 816 1743 831'
DROPS = '@e[type=minecraft:item,x=1734,y=108,z=822,dx=2,dy=4,dz=2]'
ALL_DROPS = '@e[type=minecraft:item,x=1731,y=108,z=819,dx=11,dy=9,dz=8]'


def state(facing, extracting, powered=False):
    return (f'{BLOCK}[facing={facing},extracting={str(extracting).lower()},'
            f'powered={str(powered).lower()},waterlogged=false]')


def put(command, pos, block):
    command(f'setblock {xyz(pos)} {block}')


def text(host, command):
    reply = host.command(command)
    return ' '.join(reply.get('messages', reply.get('chat', [])))


def block(host, pos):
    if isinstance(host, Native):
        read = host.session.call('block', *pos)
        return {'id': read['block'], 'properties': dict(re.findall(r'(\w+)=(\w+)', read['state'])),
                'nbt': text(host, f'data get block {xyz(pos)}')}
    return host.call('block', {'pos': pos})


def step(host, count, *positions):
    if isinstance(host, Native):
        host.command(f'tick step {count}')
        host.session.call('wait', count + 3)
        return [block(host, pos) for pos in positions]
    return host.call('observe_ticks', {'ticks': count, 'positions': positions})['samples'][-1]['blocks']


def samples(host, count):
    if isinstance(host, Native):
        observed = [step(host, 1, OUT, SOURCE) for _ in range(count)]
    else:
        reply = host.call('observe_ticks', {'ticks': count, 'positions': [OUT, SOURCE]})
        observed = [sample['blocks'] for sample in reply['samples']]
    rows = []
    for funnel, chest in observed:
        assert funnel['id'] == BLOCK and 'id:"create:funnel"' in re.sub(r'\s+', '', funnel['nbt']), funnel
        rows.append({'powered': funnel['properties']['powered'].lower() == 'true',
                     'cooldown': int(number(funnel, 'TransferCooldown')),
                     'source': items(chest['nbt'], 'Items').get(STICK, 0)})
    return rows


def extract(host):
    cmd = host.command
    put(cmd, (1735, 108, 823), 'minecraft:stone')
    put(cmd, SIGNAL, 'minecraft:redstone_block')
    put(cmd, OUT, state('down', True, True))
    put(cmd, SOURCE, 'minecraft:barrel')
    cmd(f'item replace block {xyz(SOURCE)} container.3 with {MARKED} 3')
    [paused] = samples(host, 4)[-1:]
    put(cmd, SIGNAL, 'minecraft:air')
    cycle = samples(host, 11)
    drop = text(host, f'data get entity {DROPS[:-1]},limit=1] Item')
    assert STICK in drop and 'funnel_probe:43' in re.sub(r'\s+', '', drop), drop
    assert int(number({'nbt': drop}, 'count')) == 1, drop
    cmd(f'kill {DROPS}')
    [resumed] = samples(host, 1)
    put(cmd, SIGNAL, 'minecraft:redstone_block')
    [stopped] = samples(host, 1)
    assert paused == {'powered': True, 'cooldown': 0, 'source': 3}, paused
    assert cycle == [{'powered': False, 'cooldown': max(0, 8 - i), 'source': 2}
                     for i in range(11)], cycle
    assert resumed == {'powered': False, 'cooldown': 8, 'source': 1}, resumed
    assert stopped == {'powered': True, 'cooldown': 0, 'source': 1}, stopped
    return {'paused': paused, 'cycle': cycle, 'resumed': resumed, 'stopped': stopped}


def click(host, work, name, pos, face, feet, target, item):
    host.command(f'item replace entity @s weapon.mainhand with {item}')
    if isinstance(host, Native):
        call = host.session.call
        host.command(f'tp @s {xyz(feet)}')
        call('look-at', *target)
        call('wait', 4)
        hit = call('looking-at')['block']
        assert hit['pos'] == list(pos) and hit['face'] == face, hit
        call('mouse', 'right', 'click')
        call('wait', 4)
        return
    host.call('camera', {'position': feet, 'target': target})
    host.call('capture', {'name': f'{work.name}/{name}-before.png', 'frames': 8})
    hit = host.call('state', {})['hit']
    assert hit['pos'] == list(pos) and hit['face'] == face, hit
    host.call('input', {'key': 'use'})
    try:
        host.call('capture', {'name': f'{work.name}/{name}-after.png', 'frames': 6})
    finally:
        host.call('input', {'key': 'use', 'down': False})


def collect(host, work):
    cmd = host.command
    put(cmd, TARGET, 'minecraft:chest')
    cmd('fill 1738 112 825 1742 112 826 minecraft:stone')
    cmd('gamemode survival')
    feet, aim = (1740.5, 113, 825.5), (1740.5, 112.48, 823.5)
    click(host, work, 'place', TARGET, 'up', feet, (1740.5, 111.8, 823.5), f'{BLOCK} 2')
    placed = block(host, INPUT)
    assert placed['id'] == BLOCK and placed['properties']['facing'].lower() == 'up', placed
    assert placed['properties']['extracting'].lower() == 'true', placed
    selected = text(host, 'data get entity @s SelectedItem')
    assert BLOCK in selected and int(number({'nbt': selected}, 'count')) == 1, selected
    click(host, work, 'wrench', INPUT, 'up', feet, aim, 'create:wrench')
    wrenched = block(host, INPUT)
    assert wrenched['properties']['extracting'].lower() == 'false', wrenched
    step(host, 4, INPUT)
    cmd(f'item replace block {xyz(TARGET)} container.26 with {MARKED} 61')
    click(host, work, 'collect', INPUT, 'up', feet, aim, f'{MARKED} 5')

    def slot(index):
        data = text(host, f'data get block {xyz(TARGET)} Items[{{Slot:{index}b}}]')
        assert STICK in data and 'funnel_probe:43' in re.sub(r'\s+', '', data), data
        return int(number({'nbt': data}, 'count'))

    result = {'topped_slot_26': slot(26), 'overflow_slot_0': slot(0)}
    selected = text(host, 'data get entity @s SelectedItem')
    assert STICK not in selected, selected
    assert result == {'topped_slot_26': 64, 'overflow_slot_0': 2}, result
    result['placement'] = {'facing': 'up', 'extracting': True, 'held_count': 1}
    result['wrenched_extracting'] = False
    click(host, work, 'wrench-upward', INPUT, 'up', feet, aim, 'create:wrench')
    [up] = step(host, 1, INPUT)
    assert up['properties']['extracting'] == 'true' and number(up, 'TransferCooldown') == 8, up
    assert slot(0) == 1 and slot(26) == 64
    item = text(host, 'data get entity @e[type=minecraft:item,x=1740.5,y=112.7,z=823.5,'
                      'distance=..1,limit=1] Item')
    assert STICK in item and 'funnel_probe:43' in re.sub(r'\s+', '', item), item
    assert int(number({'nbt': item}, 'count')) == 1, item
    result['upward_output'] = {'cooldown': 8, 'remaining_slot_0': 1, 'drop': 1}
    return result


def scenarios(host, work):
    host.command(f'fill {AREA} minecraft:air')
    host.command(f'kill {ALL_DROPS}')
    put(host.command, OUT, BLOCK)
    if isinstance(host, Native):
        host.session.call('wait', 4)
    default = block(host, OUT)['properties']
    assert {k: v.lower() for k, v in default.items()} == {
        'facing': 'north', 'extracting': 'false', 'powered': 'false', 'waterlogged': 'false',
    }, default
    return {'default': default, 'extract': extract(host), 'collect': collect(host, work)}


def run_java(host, work):
    manifest = json.loads((java.BASE / 'manifest.json').read_text())
    assert manifest['create_sha256'] == java.CREATE_SHA256
    before = host.call('state', {})
    if before.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        before = host.call('state', {})
    assert before['ready'] and before['data_version'] == 3955, before
    host.call('tick', {'frozen': True})
    host.command('gamemode creative')
    host.command('tp @s 1735.5 118 823.5')
    host.command(f'forceload add {COLUMN}')
    try:
        host.snapshot([OUT], 24)
        return scenarios(host, work)
    finally:
        host.command('gamemode creative')
        host.command('item replace entity @s weapon.mainhand with minecraft:air')
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'kill {ALL_DROPS}')
        host.command(f'forceload remove {COLUMN}')
        host.call('tick', {'frozen': before['server']['frozen']})


def run_native(session, reference):
    host = Native(session)
    with session:
        host.command('tp @s 1735.5 118 823.5')
        wait_loaded(session.call, [OUT, INPUT])
        host.command('tick freeze')
        observations = scenarios(host, session.scratch)
        assert observations == {name: reference[name] for name in observations}, (observations, reference)
        # The port refuses forms it cannot operate. These are native admission
        # checks rather than comparisons with Java's broader placement support.
        command = host.command
        for pos, support in [((1732, 110, 824), 'minecraft:stone'), ((1735, 108, 824), 'minecraft:stone'),
                             ((1740, 111, 820), 'minecraft:chest'), ((1740, 112, 820), 'minecraft:water'),
                             ((1740, 112, 822), 'minecraft:stone')]:
            put(command, pos, support)
        blocked = [
            ('horizontal', (1732, 110, 824), 'east', (1735.5, 109, 824.5), (1732.5, 110.5, 824.5),
             (1733, 110, 824), 'minecraft:air'),
            ('wet', (1740, 111, 820), 'up', (1740.5, 113, 822.5), (1740.5, 111.8, 820.5),
             (1740, 112, 820), 'minecraft:water'),
        ]
        for name, target, face, feet, aim, destination, before in blocked:
            click(host, session.scratch, name, target, face, feet, aim, f'{BLOCK} 2')
            actual = block(host, destination)
            held = text(host, 'data get entity @s SelectedItem')
            assert actual['id'] == before and BLOCK in held and number({'nbt': held}, 'count') == 2, (actual, held)
        observations['refused_native'] = [row[0] for row in blocked]
        return observations


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
                                     name='funnel-native', world='CreateAndesiteFunnel')
        work = session.scratch
        report.update(game=str(args.game.resolve()), reference=str(args.reference.resolve()))
    else:
        host = Original()
        work = Path(tempfile.mkdtemp(prefix='funnel-java-', dir=ROOT / '.local'))
    print(work, flush=True)
    try:
        observations = run_native(session, reference) if session else run_java(host, work)
        report.update(observations, passed=True)
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
