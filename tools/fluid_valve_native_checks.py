#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Replay the pinned Java inline Fluid Valve fixture in the live native client."""

import argparse
import json
from pathlib import Path
import shutil
from zipfile import ZipFile

from chain_drive_checks import Native, xyz
from common import PINS
from fluid_pump_java_checks import amount, put, seed
from fluid_pump_native_checks import native_trace
from fluid_valve_java_checks import (
    POSITIONS, PUMP_MOTOR, SIGNAL, SOURCE, VALVE, VALVE_MOTOR, VALVE_POS, X, Y, Z, drive, setup, state,
)
from funnel_checks import block
from native_check_session import NativeCheckSession, wait_loaded


def snap(host):
    return [state(block(host, pos)) for pos in POSITIONS]


def drive_valve(host, rpm):
    host.command(drive(VALVE_MOTOR, rpm, 'south') if rpm else f'setblock {xyz(VALVE_MOTOR)} minecraft:air')


def valve_trace(session):
    prefix = 'Create fluid valve: '
    return {row['time']: row for line in session.log.read_text().splitlines()
            if prefix in line and (row := json.loads(line.split(prefix, 1)[1]))['pos'] == list(VALVE_POS)}


def compare(host, args):
    call = host.session.call
    reference = json.loads(args.reference.read_text())
    assert reference['passed'] and reference['create'] == PINS['create_revision']
    original = json.loads(args.reference.with_name('observed.json').read_text())
    setup(host)
    call('wait', 40)
    host.command(seed(SOURCE, 'water', 8000))
    call('wait', 36)
    closed = snap(host)
    assert closed[3] == original['closed'][-1]['blocks'][3] and amount(closed[-1]) == 0, closed

    drive_valve(host, 32)
    call('wait', 46)
    assert snap(host)[3] == original['opening'][-1]['blocks'][3]
    opening = valve_trace(host.session)
    opened = next(t for t, row in opening.items() if row['enabled'])
    start = next(t for t, row in opening.items() if row['pointer'][0] > 0)
    expect = next(row['tick'] for row in original['opening'] if row['blocks'][3]['props']['enabled'] == 'true')
    original_start = next(row['tick'] for row in original['opening'] if row['blocks'][3]['pointer']['value'] > 0)
    assert opened - start == expect - original_start, (opened, start, expect, original_start)
    for t in range(start, opened + 1):
        pointer = original['opening'][original_start + t - start - 1]['blocks'][3]['pointer']['value']
        assert abs(opening[t]['pointer'][0] - pointer) < 1e-7, (t, opening[t], pointer)
    pumping = native_trace(host.session)[POSITIONS[1]]
    first = next(t for t, row in pumping.items() if row['storage'][1] > 0)
    original_first = next(row['tick'] for row in original['opening'] if amount(row['blocks'][-1]) > 0)
    assert first - opened == original_first - expect, (first - opened, original_first - expect)
    assert all(a + b == 8000 for a, b in (row['storage'] for row in pumping.values() if row['time'] >= first))

    host.command(f'setblock {xyz(SIGNAL)} minecraft:redstone_block')
    call('wait', 3)
    drive_valve(host, 0)
    call('wait', 14)
    stalled = snap(host)[3]
    assert stalled['speed'] == 0 and stalled['props']['enabled'] == 'true' and 0 < stalled['pointer']['value'] < 1, stalled
    assert stalled['pointer']['target'] == stalled['pointer']['speed'] == 0, stalled
    stalled_target = amount(snap(host)[-1])
    call('wait', 6)
    assert snap(host)[3] == stalled and amount(snap(host)[-1]) > stalled_target

    put(host, PUMP_MOTOR, 'minecraft:air')
    call('wait', 18)
    before = snap(host)
    host.session.restart()
    wait_loaded(call, POSITIONS)
    after = snap(host)
    assert before == after, (before, after)
    host.command(drive(PUMP_MOTOR, 32, 'east'))
    drive_valve(host, 32)
    call('wait', 44)
    shut = snap(host)
    assert shut[3] == original['finish-close'][-1]['blocks'][3], shut
    assert amount(shut[-1]) == amount(before[-1]), (before, shut)
    put(host, SIGNAL, 'minecraft:air')
    call('wait', 45)
    reopened = snap(host)
    assert reopened[3] == original['reopen'][-1]['blocks'][3] and amount(reopened[-1]) > amount(shut[-1]), reopened
    close_transfer = None
    if 'running-close' in original:
        last_tick = max(valve_trace(host.session))
        host.command(f'setblock {xyz(SIGNAL)} minecraft:redstone_block')
        call('wait', 32)
        movement = valve_trace(host.session)
        close_start = next(t for t, row in movement.items() if t > last_tick and row['pointer'][0] < 1)
        close_end = next(t for t, row in movement.items() if t >= close_start and not row['enabled'])
        pump = native_trace(host.session)[POSITIONS[1]]
        before_close = pump[close_start - 1]['storage'][1]
        original_baseline = amount(original['reopen'][-1]['blocks'][-1])
        for t in range(close_start, close_end + 1):
            expected = original['running-close'][t - close_start]
            valve = expected['blocks'][3]
            assert abs(movement[t]['pointer'][0] - valve['pointer']['value']) < 1e-7
            assert movement[t]['enabled'] == (valve['props']['enabled'] == 'true')
            assert pump[t]['storage'][1] - before_close == amount(expected['blocks'][-1]) - original_baseline
        stopped = snap(host)
        assert stopped[3] == original['running-close'][-1]['blocks'][3], stopped
        assert amount(stopped[-1]) == pump[close_end]['storage'][1], stopped
        close_transfer = amount(stopped[-1]) - before_close
        put(host, SIGNAL, 'minecraft:air')
        call('wait', 40)
    return dict(open_ticks=opened - start + 1, first_transfer=first - opened, stalled_pointer=stalled['pointer']['value'],
                cold=True, reopens=True, close_transfer=close_transfer)


def assets(session, jar):
    if jar:
        receipt, = (session.scratch / '.horizon-cache/create-assets/imports').glob('*/import.json')
        pack = receipt.parent / 'pack'
        paths = [f'assets/create/{part}.json' for part in ('blockstates/fluid_valve', 'models/item/fluid_valve',
                 'models/block/fluid_valve/pointer', 'models/block/fluid_valve/block_horizontal_open',
                 'models/block/fluid_valve/block_horizontal_closed')]
        with ZipFile(jar) as archive:
            assert all((pack / path).read_bytes() == archive.read(path) for path in paths)
    call = session.call
    call('command', f'tp @s {X + 3.5} {Y} {Z + 3.1}')
    call('look-at', X + 3.5, Y + .65, Z + .5)
    call('key', 'f1', 'tap')
    call('wait', 8)
    call('screenshot', session.scratch / 'valve-open.png')
    assert '"model":"create:block/fluid_valve/pointer"' in session.log.read_text(), 'pointer model was never submitted'
    return {'original': bool(jar), 'pointer_drawn': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + flag, type=Path, required=flag != 'create-jar')
    args = parser.parse_args()
    session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                 name='fluid-valve-native', world='CreateFluidValve')
    session.env['CREATE_TRACE_FLUID_PUMP'] = '1'
    print(session.scratch, flush=True)
    try:
        with session:
            session.call('command', f'tp @s {X}.5 {Y+4} {Z+2}.5')
            wait_loaded(session.call, POSITIONS)
            session.call('command', 'gamemode creative')
            result = compare(Native(session), args)
            result['assets'] = assets(session, args.create_jar)
    finally:
        for folder in (session.resources, session.scratch / '.horizon-cache', session.scratch / 'horizon-mods'):
            shutil.rmtree(folder, ignore_errors=True)
    output = session.scratch / 'result.json'
    output.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], **result), indent=2) + '\n')
    print(output)


if __name__ == '__main__':
    main()
