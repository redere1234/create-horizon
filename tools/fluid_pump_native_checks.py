#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare live native straight-line Pump flow with the pinned Java fixture."""

import argparse
import json
from pathlib import Path
import shutil
from zipfile import ZipFile

from chain_drive_checks import Native, xyz
from common import PINS
from fluid_pump_java_checks import (
    CASES, PIPE, POSITIONS, PUMP, TANK, X, Y, Z, amount, fluid_kind, lane, measure, put, seed, setup,
)
from fluid_tank_checks import BUCKET, click
from funnel_checks import block
from native_check_session import NativeCheckSession, wait_loaded


def native_trace(session):
    prefix = 'Create fluid pump: '
    rows = {}
    for line in session.log.read_text().splitlines():
        if prefix not in line:
            continue
        record = json.loads(line.split(prefix, 1)[1])
        rows.setdefault(tuple(record['pos']), {})[record['time']] = record
    return rows


def verify_startup(session, java_path):
    rows = native_trace(session)
    java_rows = json.loads(java_path.read_text())
    results = {}
    offset = 0
    for name, (count, rpm, _) in CASES.items():
        positions = lane(name)
        first_device = positions[1]
        clock = next(t for t, row in rows[first_device].items() if row['inlet'] is not None)
        targets = []
        for phase in java_rows:
            tick = phase['tick']
            expected = phase['blocks'][offset:offset + len(positions)]
            native_t = clock + tick - 1
            first = rows[first_device][native_t]
            targets.append(first['storage'][1])
            assert first['storage'] == [amount(expected[0]), amount(expected[-1])], (name, tick, first, expected)
            for pos, source in zip(positions[1:-1], expected[1:-1], strict=True):
                native = rows[pos][native_t]
                assert native['pressure'] == abs(rpm) and native['front'] == 'east', (name, tick, native)
                for direction, key in [('west', 'inlet'), ('east', 'outlet')]:
                    flow = source['connections'][direction]['flow']
                    observed = native[key]
                    if flow is None:
                        assert observed is None, (name, tick, native, flow)
                    else:
                        assert observed and observed[0] == flow['fluid']['id'], (name, tick, native, flow)
                        wanted = flow['progress'] if flow['progress'] is not None else 1.0
                        assert abs(observed[1] - wanted) < 1e-7, (name, tick, native, flow)
        results[name] = dict(first=next(i for i, m in enumerate(targets, 1) if m),
                             ticks=len(targets), total=targets[-1], pipes_per_side=count)
        offset += len(positions)
    return results


def snapshot(host, positions):
    return [measure(block(host, pos)) for pos in positions]


def stored_together(session, source_device, front):
    rows = native_trace(session)[source_device]
    latest = max(tick for tick, row in rows.items() if row['front'] == front and row['storage'])
    return rows[latest]['storage']


def run_backpressure(host):
    positions = lane('single')
    source, target = positions[0], positions[-1]
    values = {}
    for name, fluid, tank_amount in [('incompatible', 'lava', 1000), ('full', 'water', 8000), ('room', 'water', 7997)]:
        # Park the line before reading its source amount. It must stay parked
        # when a different fluid or a full same-fluid tank is present.
        if name == 'room':
            start = amount(snapshot(host, [source])[0])
        host.command(seed(target, fluid, tank_amount))
        host.session.call('wait', 10)
        a, b = map(amount, snapshot(host, [source, target]))
        if name == 'room':
            assert [a, b] == [start - 3, 8000], (name, start, a, b)
        else:
            host.session.call('wait', 6)
            assert list(map(amount, snapshot(host, [source, target]))) == [a, b], name
            assert b == tank_amount, (name, a, b)
        values[name] = [a, b]
    return values


def resume_and_reverse(host, work):
    positions = lane('single')
    source, pump, target = positions[0], positions[2], positions[-1]
    before = snapshot(host, positions)
    host.session.restart()
    wait_loaded(host.session.call, positions)
    after = snapshot(host, positions)
    assert before == after, (before, after)
    ax, ay, az = target
    a, b = amount(after[0]), amount(after[-1])
    click(host, work, 'reopen-target', BUCKET, feet=(ax + .5, ay, az + 2.4),
          aim=(ax + .5, ay + .6, az + 1), pos=target)
    host.session.call('wait', 15)
    c, d = stored_together(host.session, positions[1], 'east')
    assert c < a and d > b - 1000 and c + d == a + b - 1000, (before, c, d)
    px, py, pz = pump
    click(host, work, 'reverse-pump', 'create:wrench', feet=(px + .5, py, pz + 2.4),
          aim=(px + .5, py + .6, pz + .875), pos=pump)
    host.session.call('wait', 24)
    reversed_flow = snapshot(host, positions)
    f, e = stored_together(host.session, positions[-2], 'west')
    # More eastward transfer can occur while aiming before the wrench is used.
    # Compare the final complete reverse path and the total fluid directly.
    assert e + f == c + d and e > c, (c, d, e, f)
    assert reversed_flow[2]['props']['facing'] == 'west' and reversed_flow[2]['speed'] == -32, reversed_flow
    for state in reversed_flow[1:-1]:
        assert state['connections']['east']['pressure'] == [32, 0], state
        assert state['connections']['west']['pressure'] == [0, 32], state
    return {'cold': True, 'before': [a, b], 'resumed': [c, d], 'reversed': [e, f]}


def place_by_hand(host, work):
    x, y, z = X - 2, Y, Z + 2
    tank = (x, y, z)
    pipe = (x + 1, y, z)
    pump = (x + 2, y, z)
    put(host, tank, TANK)
    click(host, work, 'place-pipe', PIPE, feet=(x + 3.4, y, z + .5),
          aim=(x + 1, y + .5, z + .5), pos=tank, face='east')
    assert block(host, pipe)['properties'] == dict(down='false', up='false', north='false', south='false',
                                                  east='true', west='true', waterlogged='false')
    click(host, work, 'place-pump', PUMP, feet=(x + 4.4, y, z + .5),
          aim=(x + 2, y + .5, z + .5), pos=pipe, face='east')
    placed = block(host, pump)
    assert placed['id'] == PUMP and placed['properties'] == dict(facing='east', waterlogged='false'), placed
    return True


def verify_stopped(host):
    positions = lane('double')
    z = positions[0][2]
    put(host, (X - 1, Y, z - 1), 'minecraft:air')
    host.session.call('wait', 15)
    still = snapshot(host, positions)
    assert still[3]['speed'] == 0, still[3]
    assert all(not face['pressure'] and face['flow'] is None
               for entry in still[1:-1] for face in entry['connections'].values()), still
    amounts = [amount(still[0]), amount(still[-1])]
    host.session.call('wait', 15)
    assert list(map(amount, snapshot(host, [positions[0], positions[-1]]))) == amounts
    return amounts


def original_assets(session, jar):
    if jar is None:
        return {'fallback': True}
    import_record, = (session.scratch / '.horizon-cache/create-assets/imports').glob('*/import.json')
    pack = import_record.parent / 'pack'
    paths = ['assets/create/blockstates/fluid_pipe.json', 'assets/create/blockstates/mechanical_pump.json',
             'assets/create/models/block/mechanical_pump/cog.json', 'assets/create/models/item/fluid_pipe.json',
             'assets/create/models/item/mechanical_pump.json']
    paths += [f'assets/create/models/block/fluid_pipe/{part}/{side}.json'
              for part in ('connection', 'rim_connector', 'rim', 'drain') for side in ('east', 'west')]
    with ZipFile(jar) as archive:
        assert all((pack / path).read_bytes() == archive.read(path) for path in paths)
    return {'original_files': paths}


def visible_attachments(session):
    prefix = 'Create fluid attachment: '
    draws = [json.loads(line.split(prefix, 1)[1]) for line in session.log.read_text().splitlines() if prefix in line]
    models = {record['model'] for record in draws}
    expected = {f'create:block/fluid_pipe/{part}/{side}'
                for part in ('rim_connector', 'drain', 'connection') for side in ('east', 'west')}
    assert expected <= models, expected - models
    return sorted(expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + flag, type=Path, required=flag != 'create-jar')
    args = parser.parse_args()
    reference = json.loads(args.reference.read_text())
    assert reference['passed'] and reference['create'] == PINS['create_revision'], reference
    session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                 name='fluid-pump-native', world='CreateFluidPump')
    session.env['CREATE_TRACE_FLUID_PUMP'] = '1'
    work = session.scratch
    print(work, flush=True)
    try:
        with session:
            session.call('command', f'tp @s {X}.5 {Y+4} {Z+10}.5')
            wait_loaded(session.call, POSITIONS)
            session.call('command', 'gamemode creative')
            host = Native(session)
            setup(host)
            session.call('wait', 45)
            for name in CASES:
                host.command(seed(lane(name)[0], fluid_kind(name), 8000))
            session.call('wait', 135)
            startup = verify_startup(session, args.reference.with_name('observed.json'))
            pressure = run_backpressure(host)
            saved = resume_and_reverse(host, work)
            stopped = verify_stopped(host)
            placement = place_by_hand(host, work)
            assets = original_assets(session, args.create_jar)
            if args.create_jar:
                session.call('command', f'tp @s {X + 4.5} {Y} {Z + 12.7}')
                session.call('look-at', X + .5, Y + .5, Z + 10.5)
                session.call('wait', 6)
            session.call('command', f'tp @s {X + 3.7} {Y} {Z + 8.8}')
            session.call('look-at', X + .5, Y + .5, Z + 5.5)
            session.call('key', 'f1', 'tap')
            session.call('wait', 6)
            session.call('screenshot', work / 'pump-line.png')
            if args.create_jar:
                assets['drawn'] = visible_attachments(session)
    finally:
        for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
            shutil.rmtree(folder, ignore_errors=True)
    output = work / 'result.json'
    output.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], startup=startup,
                                      pressure=pressure, saved=saved, stopped=stopped,
                                      placement=placement, assets=assets), indent=2) + '\n')
    print(output)


if __name__ == '__main__':
    main()
