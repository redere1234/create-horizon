#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Lift glued cargo and chassis from the end of an extended Rope Pulley."""

import argparse
import json
from pathlib import Path
import tempfile

from bearing_native_checks import Batch
from chain_drive_checks import Original, xyz
from chassis_native_checks import expect_restored
from chassis_reference_checks import LINEAR, chassis
from common import PINS, ROOT
from gantry_chassis_checks import AIR, observed_java, verify
from gantry_glue_checks import java_glue_clicks, java_volumes, native_glue_clicks
from native_check_session import NativeCheckSession, wait_loaded
from saved_block_checks import read_saved_chunk_tag
from super_glue_native_checks import ITEM, KEYS, MOUNTED_KEYS


PULLEY = (1130, 120, 61)
MOTOR = (1131, 120, 61)
A = (1130, 117, 61)
B = (1130, 117, 62)
CLEAR = 'fill 1126 115 59 1133 124 63 minecraft:air'
POWER = 'create:creative_motor[facing=west]{ScrollValue:128}'
FLOOR = 'fill 1126 115 60 1128 115 63 minecraft:stone'
ROPE = {
    (1130, 119, 61): 'create:rope[waterlogged=false]',
    (1130, 118, 61): 'create:pulley_magnet[waterlogged=false]',
}
CARGO = {
    A: 'minecraft:stone',
    B: chassis(LINEAR, 'z', 3, 'sticky_top'),
    (1130, 117, 63): 'minecraft:oak_log[axis=z]',
}
CONTROL = {(1130, 117, 60): 'minecraft:gold_block'}
TARGET = {(x, y + 2, z): state for (x, y, z), state in CARGO.items()}
CELLS = dict.fromkeys(ROPE | CARGO | TARGET, AIR)
BEFORE = CELLS | ROPE | CARGO | CONTROL
MOVING = CELLS | CONTROL
LANDED = CELLS | TARGET | CONTROL


def setup(command):
    command(CLEAR)
    command(FLOOR)
    command(f'setblock {xyz(PULLEY)} create:rope_pulley[axis=x]{{Offset:2f}}')
    for position, state in (ROPE | CARGO | CONTROL).items():
        command(f'setblock {xyz(position)} {state}')


def java_reference():
    host = Original()
    work = Path(tempfile.mkdtemp(prefix='pulley-payload-java-', dir=ROOT / '.local'))
    chunk = f'{A[0]} {A[2]}'
    try:
        assert host.call('state', {})['data_version'] == 3955
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        host.command(f'tp @s {A[0]}.5 124 {A[2]}.5')
        host.command(f'forceload add {chunk}')
        host.call('observe_ticks', {'ticks': 30, 'positions': [A]})
        host.command(f'kill @e[type={ITEM},x={A[0]},y={A[1]},z={A[2]},distance=..8]')
        setup(host.command)
        java_glue_clicks(host, work, (A, B), (-3, -1.5, 0))
        observed_java(host, BEFORE, 1)
        initial = java_volumes(host, A)
        assert initial == [[A, (1131, 118, 63)]], initial
        host.command(f'setblock {xyz(MOTOR)} {POWER}')
        moving = observed_java(host, MOVING, 3)
        assert not java_volumes(host, A)
        landed = observed_java(host, LANDED, 20)
        volumes = java_volumes(host, A)
        assert volumes == [[(1130, 119, 61), (1131, 120, 63)]], volumes
        result = work / 'result.json'
        result.write_text(json.dumps(dict(create=PINS['create_revision'], moving=moving,
                                          landed=landed, volumes=volumes), indent=2) + '\n')
        return result
    finally:
        host.command(f'forceload remove {chunk}')
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session):
    def saved(keys):
        return read_saved_chunk_tag(session.scratch, A, keys, session.world)['nbt']

    call = session.call
    with session:
        call('command', 'tp @s 1127.5 116 61.5')
        wait_loaded(call, [A])
        setup(lambda cmd: call('command', cmd))
        native_glue_clicks(session, (A, B), lambda p: (1127.5, 116, p[2] + .5))
        assert saved(KEYS)['value']['Volumes']['value'] == [{'type': 'int-array', 'value': [*A, *B]}]

    batch = Batch()
    batch.load(PULLEY)
    expect_restored(batch, BEFORE)
    batch.put(MOTOR, POWER)
    batch.tick(3)
    expect_restored(batch, MOVING)
    moving = verify(batch, session, 'pulley-payload-moving')
    assert saved(KEYS) is None
    [entry] = saved(MOUNTED_KEYS)['value']['Entries']['value']
    assert entry['value']['Controller']['value'] == list(PULLEY), entry
    assert entry['value']['Bounds']['value']['Volumes']['value'] == [
        {'type': 'int-array', 'value': [0, 0, 0, 0, 0, 1]}], entry

    batch = Batch()
    batch.load(PULLEY)
    batch.tick(20)
    expect_restored(batch, LANDED)
    landed = verify(batch, session, 'pulley-payload-cold-landing')
    assert saved(MOUNTED_KEYS) is None
    [volume] = saved(KEYS)['value']['Volumes']['value']
    assert volume['value'] == [1130, 119, 61, 1130, 119, 62], volume
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
    session = NativeCheckSession(args.game, args.resources, args.ctl, None, name='pulley-payload-native',
                                 graphics=False, world='CreatePulleyPayloadChecks')
    result = session.scratch / 'result.json'
    result.write_text(json.dumps(native(session), indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
