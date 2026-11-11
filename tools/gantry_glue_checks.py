#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Move the same two-block Super Glue selection on a mid-rail Gantry."""

import argparse
import json
from pathlib import Path
import re
import tempfile

from bearing_native_checks import Batch
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from gantry_chassis_checks import LEFT, RAIL_Y, RIGHT, observed_java, phases, rig, verify
from native_check_session import NativeCheckSession, wait_loaded
from saved_block_checks import read_saved_chunk_tag
from super_glue_native_checks import ITEM, KEYS, MOUNTED_KEYS


Z = 105
START = LEFT + 1
A, B = [(x, RAIL_Y + 2, Z) for x in (START, START - 1)]
CARGO = {A: 'minecraft:stone', B: 'minecraft:oak_log[axis=z]'}
MOTOR = (LEFT - 1, RAIL_Y, Z)
CLEAR = f'fill {LEFT - 3} {RAIL_Y} {Z - 3} {RIGHT + 2} {RAIL_Y + 5} {Z + 3} minecraft:air'
SCENE = phases(Z, START, RIGHT, CARGO, {})


def java_glue_clicks(host, work, selection, view):
    host.command(f'item replace entity @s weapon.mainhand with {ITEM}')
    for index, pos in enumerate(selection):
        target = [v + .5 for v in pos]
        host.call('camera', {'position': [p + offset for p, offset in zip(target, view)],
                             'target': target})
        host.call('capture', {'name': f'{work.name}/glue-{index}-before.png', 'frames': 8})
        hit = host.call('state', {})['hit']
        assert hit['type'] == 'BLOCK' and hit['pos'] == list(pos), hit
        host.call('input', {'key': 'use'})
        try:
            host.call('capture', {'name': f'{work.name}/glue-{index}-after.png', 'frames': 6})
        finally:
            host.call('input', {'key': 'use', 'down': False})


def java_volumes(host, center):
    rows = host.call('entities', {'center': center, 'radius': 8})['entities']
    bounds = []
    for row in rows:
        if row['type'] != ITEM:
            continue
        values = dict(re.findall(r'(From|To):\s*\[([^]]+)\]', row['nbt']))
        assert values.keys() == {'From', 'To'}, row
        bounds.append([tuple(pos + float(diff.removesuffix('d'))
                             for pos, diff in zip(row['position'], values[key].split(','), strict=True))
                       for key in ('From', 'To')])
    return bounds


def java_reference():
    host = Original()
    work = Path(tempfile.mkdtemp(prefix='gantry-glue-java-', dir=ROOT / '.local'))
    chunk = f'{START} {Z}'
    try:
        assert host.call('state', {})['data_version'] == 3955
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        host.command(f'tp @s {START}.5 {RAIL_Y + 8} {Z}.5')
        host.command(f'forceload add {chunk}')
        host.call('observe_ticks', {'ticks': 30, 'positions': [A]})
        selector = f'@e[type=create:super_glue,x={START},y={A[1]},z={Z},distance=..8]'
        host.command(f'kill {selector}')
        host.command(CLEAR)
        power = rig(lambda pos, state: host.command(f'setblock {xyz(pos)} {state}'),
                    Z, START, -128, CARGO, {})
        host.command(f'fill {LEFT} {RAIL_Y} {Z - 3} {RIGHT} {RAIL_Y} {Z - 3} minecraft:stone')
        java_glue_clicks(host, work, (A, B), (0, -1.5, -3))
        observed_java(host, SCENE[0], 1)
        [initial] = java_volumes(host, A)
        assert initial == [B, (START + 1, A[1] + 1, Z + 1)], initial
        power()
        observed_java(host, SCENE[1], 3)
        assert not java_volumes(host, A)
        observed_java(host, SCENE[2], 10)
        [landed] = java_volumes(host, A)
        assert landed == [(START, A[1], Z), (RIGHT + 1, A[1] + 1, Z + 1)], landed
        result = work / 'result.json'
        result.write_text(json.dumps(dict(create=PINS['create_revision'], initial=initial,
                                          landed=landed), indent=2) + '\n')
        return result
    finally:
        host.command(f'forceload remove {chunk}')
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_glue_clicks(session, selection, feet):
    call = session.call
    call('command', f'item replace entity @s weapon.mainhand with {ITEM}')
    for pos in selection:
        call('command', 'tp @s ' + xyz(feet(pos)))
        call('wait', 5)
        call('look-at', *(v + .5 for v in pos))
        assert call('looking-at')['block']['pos'] == list(pos)
        call('mouse', 'right', 'click')
        call('wait', 8)
    call('save')


def native(session):
    call = session.call

    def command(value):
        return call('command', value)

    def saved(keys):
        return read_saved_chunk_tag(session.scratch, A, keys, session.world)['nbt']

    with session:
        command(f'tp @s {START}.5 {RAIL_Y + 1} {Z - 2}.5')
        wait_loaded(call, [A])
        command(f'fill {LEFT - 3} {RAIL_Y - 1} {Z - 3} {RIGHT + 2} {RAIL_Y - 1} {Z + 3} minecraft:stone')
        command(CLEAR)
        rig(lambda pos, state: command(f'setblock {xyz(pos)} {state}'), Z, START, -128, CARGO, {})
        native_glue_clicks(session, (A, B), lambda p: (p[0] + .5, RAIL_Y + 1, Z - 2.5))
        assert saved(KEYS)['value']['Volumes']['value'] == [{'type': 'int-array', 'value': [*B, *A]}]

    def check_state(label, states, edits=(), ticks=0):
        batch = Batch()
        batch.load((START, RAIL_Y + 6, Z))
        for pos, state in edits:
            batch.put(pos, state)
        if ticks:
            batch.tick(ticks)
        for pos, state in states.items():
            batch.expect(pos, state)
        return verify(batch, session, label)

    moving = check_state('gantry-glue-moving', SCENE[1],
                         [(MOTOR, 'create:creative_motor[facing=east]{ScrollValue:-128}')], 3)
    assert saved(KEYS) is None
    [entry] = saved(MOUNTED_KEYS)['value']['Entries']['value']
    assert entry['value']['Controller']['value'] == [START, RAIL_Y + 1, Z], entry
    assert entry['value']['Bounds']['value']['Volumes']['value'] == [
        {'type': 'int-array', 'value': [-1, 1, 0, 0, 1, 0]}], entry

    landed = check_state('gantry-glue-cold-landing', SCENE[2], ticks=12)
    assert saved(MOUNTED_KEYS) is None
    [volume] = saved(KEYS)['value']['Volumes']['value']
    assert volume['value'] == [START, A[1], Z, RIGHT, A[1], Z], volume
    return dict(moving=moving, landed=landed, local=entry, restored=volume)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for key in ('game', 'resources', 'ctl'):
        parser.add_argument('--' + key, type=Path)
    args = parser.parse_args()
    if args.java:
        print(java_reference())
        return
    if not all((args.game, args.resources, args.ctl)):
        parser.error('Specify --java or all of --game, --resources and --ctl')
    session = NativeCheckSession(args.game, args.resources, args.ctl, None, name='gantry-glue-native',
                                 graphics=False, world='CreateGantryGlueChecks')
    path = session.scratch / 'result.json'
    path.write_text(json.dumps(native(session), indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
