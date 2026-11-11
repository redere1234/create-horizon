#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare Wrench-linked Mechanical Crafter groups and ordinary hand loading."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from burner_heat_java_checks import field, items, number
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from funnel_checks import block, click, put, step, text
from native_check_session import NativeCheckSession, wait_loaded
import reference_java


X, Y, Z = 2460, 171, 1330
A, B, C = (X, Y, Z), (X + 1, Y, Z), (X, Y + 1, Z)
FORCE = '2448 1320 2479 1343'
AREA = '2457 169 1325 2464 174 1334'
CRAFT = 'create:mechanical_crafter[facing=south,pointing=up]'
WRENCH = 'create:wrench'
COVER = 'create:crafter_slot_cover'
STICK = 'minecraft:stick[minecraft:custom_data={crafter_link:17}]'


def inputs(host, positions=(A, B, C)):
    result = []
    for pos in positions:
        nbt = block(host, pos)['nbt']
        input_data = field(nbt, 'ConnectedInput')
        data = re.findall(r'\bX:\s*(-?\d+)\s*,\s*Y:\s*(-?\d+)\s*,\s*Z:\s*(-?\d+)', input_data)
        result.append({'controller': int(number({'nbt': input_data}, 'Controller')),
                       'data': [list(map(int, coordinates)) for coordinates in data],
                       'inventory': items(field(nbt, 'Inventory'), 'Items'),
                       'marked': 'crafter_link:17' in nbt.replace(' ', ''),
                       'covered': int(number({'nbt': nbt}, 'Cover', 0))})
    return result


def owner(*offsets):
    return dict(controller=1, data=[[0, 0, 0], *[list(offset) for offset in offsets]])


def member(offset):
    return dict(controller=0, data=[list(offset)])


def groups(states):
    return [{key: node[key] for key in ('controller', 'data')} for node in states]


def touch(host, work, label, pos, face, item, *, dx=.5, dy=.55):
    x, y, z = pos
    front = face == 'south'
    feet = x + dx, Y, z + (3 if front else -2.5)
    aim = x + dx, y + dy, z + (.7 if front else .3)
    click(host, work, label, pos, face, feet, aim, item)


def scenario(host, work):
    command = host.command
    command(f'fill {AREA} minecraft:air')
    command('fill 2457 170 1326 2464 170 1333 minecraft:smooth_stone')
    for pos in (A, B, C):
        put(command, pos, CRAFT)
    step(host, 4, A, B, C)
    command('gamemode survival')
    report = {}
    touch(host, work, 'center-no-edge', A, 'north', WRENCH)
    initial = inputs(host)
    assert groups(initial) == [owner(), owner(), owner()], initial
    assert block(host, A)['properties']['facing'].lower() == 'south'
    touch(host, work, 'merge-east', A, 'north', WRENCH, dx=.9)
    east = inputs(host)
    assert groups(east) == [owner((1, 0, 0)), member((-1, 0, 0)), owner()], east
    report['east'] = east
    if isinstance(host, Native):
        # An invalid reciprocal owner is never partially rewritten during an
        # otherwise valid edge click. Java accepts only the canonical fixture.
        edit = f'data merge block {xyz(B)} {{ConnectedInput:{{Controller:0b,Data:[{{X:'
        command(edit + '-5,Y:0,Z:0}]}}')
        corrupted = inputs(host)
        assert groups(corrupted)[1] == member((-5, 0, 0)), corrupted
        touch(host, work, 'invalid-owner', A, 'north', WRENCH, dy=.9)
        assert inputs(host) == corrupted
        command(edit + '-1,Y:0,Z:0}]}}')
        assert inputs(host) == east
    touch(host, work, 'merge-up', A, 'north', WRENCH, dy=.9)
    linked = inputs(host)
    assert groups(linked) == [owner((1, 0, 0), (0, 1, 0)),
                               member((-1, 0, 0)), member((0, -1, 0))], linked
    report['linked'] = linked
    if isinstance(host, Native):
        host.session.restart()
        wait_loaded(host.session.call, [A, B, C])
        command('tick freeze')
        command('gamemode survival')
        assert inputs(host) == linked
    touch(host, work, 'sorted-first', B, 'south', STICK)
    sorted_first = inputs(host)
    assert [node['inventory'] for node in sorted_first] == [{}, {}, {'minecraft:stick': 1}], sorted_first
    assert [node['marked'] for node in sorted_first] == [False, False, True], sorted_first
    report['first'] = sorted_first
    touch(host, work, 'local-empty-hand', C, 'south', 'minecraft:air')
    assert inputs(host) == linked
    touch(host, work, 'cover-top', C, 'south', COVER)
    touch(host, work, 'feed-two', B, 'south', STICK + ' 3')
    filled = inputs(host)
    assert [node['inventory'] for node in filled] == [{'minecraft:stick': 1}, {'minecraft:stick': 1}, {}], filled
    assert [node['marked'] for node in filled] == [True, True, False], filled
    assert filled[2]['covered'] == 1, filled
    held = text(host, 'data get entity @s SelectedItem')
    assert number({'nbt': held}, 'count') == 1 and 'crafter_link:17' in held.replace(' ', ''), held
    report['filled'] = filled
    touch(host, work, 'split-east', A, 'north', WRENCH, dx=.9)
    separated = inputs(host)
    assert groups(separated) == [owner((0, 1, 0)), owner(), member((0, -1, 0))], separated
    assert [node['inventory'] for node in separated] == [node['inventory'] for node in filled], separated
    report['split'] = separated
    if isinstance(host, Native):
        def sneak(down):
            host.session.call('key', 'shift', 'down' if down else 'up')
    else:
        def sneak(down):
            host.call('input', {'key': 'shift', 'down': down})
    sneak(True)
    try:
        touch(host, work, 'remove-controller', A, 'north', WRENCH)
    finally:
        sneak(False)
    assert block(host, A)['id'] == 'minecraft:air'
    survivors = inputs(host, (B, C))
    assert groups(survivors) == [owner(), owner()], survivors
    assert survivors[0]['inventory'] == {'minecraft:stick': 1}, survivors
    assert survivors[1]['covered'] == 1, survivors
    report['survivors'] = survivors
    return report


def java_run(work):
    host = Original()
    manifest = json.loads((reference_java.BASE / 'manifest.json').read_text())
    assert manifest['create_sha256'] == reference_java.CREATE_SHA256
    state = host.call('state', {})
    assert state['ready'] and state['data_version'] == 3955, state
    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {FORCE}')
        host.snapshot([A, B, C], 20)
        return scenario(host, work)
    finally:
        host.command('gamemode creative')
        host.command('item replace entity @s weapon.mainhand with minecraft:air')
        host.command(f'clear @s {STICK}')
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {FORCE}')
        host.call('camera', {'position': state['position'], 'yaw': state['yaw'], 'pitch': state['pitch']})
        host.call('tick', {'frozen': state['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='crafter-link-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        result = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon check requires --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['create'] == PINS['create_revision'] and reference['passed']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None, name='crafter-link-native',
                                     world='CreateLinkedCrafter')
        work = session.scratch
        print(work, flush=True)
        try:
            with session:
                session.call('command', f'tp @s {xyz((X + .5, Y, Z - 2.5))}')
                wait_loaded(session.call, [A, B, C])
                session.call('command', 'tick freeze')
                result = scenario(Native(session), work)
        finally:
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        assert result == reference['cases'], (result, reference)
    path = work / 'result.json'
    path.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], cases=result), indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
