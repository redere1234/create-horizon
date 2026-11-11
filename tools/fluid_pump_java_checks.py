#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Measure straight, closed Fluid Pipe and Mechanical Pump lines in Create 6.0.10."""

import argparse
import json
from pathlib import Path
import re
import struct
import tempfile
import time

from burner_heat_java_checks import field, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from fluid_tank_checks import BUCKET
import reference_java as java


X, Y, Z = 2511, 140, 1363
TANK, PIPE, PUMP = 'create:fluid_tank', 'create:fluid_pipe', 'create:mechanical_pump'
LOAD = '2496 1360 2527 1391'
AREA = '2506 139 1360 2516 144 1390'
CASES = {
    'direct': (0, 32, False), 'single': (1, 32, False), 'double': (2, 32, False),
    'reverse-placement': (1, 32, True), 'slow': (1, 4, False), 'reverse-rpm': (1, -64, False),
}


def lane(name):
    count, _, _ = CASES[name]
    z = Z + 5 * list(CASES).index(name)
    return [(x, Y, z) for x in range(X - count - 1, X + count + 2)]


POSITIONS = [p for name in CASES for p in lane(name)]


def fluid(nbt):
    fluid = re.search(r'\bid:\s*"(minecraft:(?:water|lava))"', nbt)
    return dict(id=fluid[1], amount=int(number({'nbt': nbt}, 'amount'))) if fluid else None


def measure(block):
    raw = block['nbt']
    if block['id'] == TANK:
        return dict(block=TANK, tank=fluid(field(raw, 'TankContent')))
    assert block['id'] in (PIPE, PUMP), block
    connections = {}
    for face in ('west', 'east'):
        record = field(raw, face) if re.search(r'\b' + face + r'\s*:', raw) else '{}'
        pressure = []
        if 'Pressure:' in record:
            pressure = [float(v) for v in re.findall(r'(-?\d+(?:\.\d+)?)f', field(record, 'Pressure'))]
            assert len(pressure) == 2, record
        flow = None
        if 'Flow:' in record:
            payload = field(record, 'Flow')
            flow = dict(fluid=fluid(field(payload, 'Fluid')), inbound=bool(number({'nbt': payload}, 'In')),
                        progress=number({'nbt': field(payload, 'Progress')}, 'Value') if 'Progress:' in payload else None)
        connections[face] = dict(pressure=pressure, flow=flow)
    return dict(block=block['id'], speed=number(block, 'Speed', 0),
                props={key: value.lower() for key, value in block['properties'].items()}, connections=connections)


def put(host, pos, block):
    host.command(f'setblock {xyz(pos)} {block}')


def seed(pos, kind, amount):
    inner = f'Fluid:{{id:"minecraft:{kind}",amount:{amount}}}'
    return f'data merge block {xyz(pos)} {{TankContent:{{{inner}}}}}'


def observed(host, positions, ticks, commands=()):
    rows = host.call('observe_ticks', {'positions': positions, 'ticks': ticks, 'commands': list(commands),
                                       'ticker_order': True})['samples']
    return [dict(tick=row['tick'], ticker_order=row['ticker_order'], blocks=[measure(b) for b in row['blocks']])
            for row in rows]


def setup(host):
    host.command(f'fill {AREA} minecraft:air')
    host.command(f'fill 2506 {Y-1} 1360 2516 {Y-1} 1390 minecraft:smooth_stone')
    for name, (count, rpm, reverse) in CASES.items():
        positions = lane(name)
        for pos in (positions[::-1] if reverse else positions):
            if pos[0] == X:
                block = PUMP + '[facing=east,waterlogged=false]'
            elif abs(pos[0] - X) == count + 1:
                block = TANK
            else:
                block = PIPE + '[east=true,west=true,waterlogged=false]'
            put(host, pos, block)
        z = positions[0][2]
        put(host, (X, Y, z - 1), 'create:cogwheel[axis=x]')
        put(host, (X - 1, Y, z - 1), f'create:creative_motor[facing=east]{{ScrollValue:{rpm}}}')


def row_for(rows, name):
    first = sum(len(lane(other)) for other in list(CASES)[:list(CASES).index(name)])
    size = len(lane(name))
    return [row['blocks'][first:first + size] for row in rows]


def amount(block):
    return (block['tank'] or {}).get('amount', 0)


def fluid_kind(name):
    return 'lava' if name == 'direct' else 'water'


def f32(value):
    return struct.unpack('>f', struct.pack('>f', value))[0]


def model_startup(segments, order, pressure, ticks):
    """PipeConnection with two faces, one source, and one final endpoint."""
    flows = [[None, None] for _ in range(segments)]
    progress_per_tick = f32(1 / 32 + min(pressure / 128, 1) * 31 / 32)
    rate = max(1, int(pressure / 2))
    target = 0
    # FluidNetwork is created on the source face's second active tick and
    # waits for two observations, even if the last face has already filled.
    pause_until = 4
    for tick in range(1, ticks + 1):
        for i in order:
            if i == 0 and tick >= pause_until and all(face == 1 for pair in flows for face in pair):
                target += rate
            incoming, outgoing = flows[i]
            if outgoing is None and incoming == 1:
                outgoing = 0
            if incoming is None and (i == 0 or flows[i - 1][1] == 1):
                incoming = 0
            flows[i] = [min(1, f32(face + progress_per_tick)) if face is not None else None
                        for face in (incoming, outgoing)]
        yield [pair.copy() for pair in flows], target


def verify(rows):
    results = {}
    for name, (count, rpm, _) in CASES.items():
        lane_rows = row_for(rows, name)
        assert all(row[count + 1]['speed'] == -rpm for row in lane_rows), (name, lane_rows[0])
        for row in lane_rows:
            assert amount(row[0]) + amount(row[-1]) == 8000, (name, row)
            for block in row[1:-1]:
                assert block['connections']['west']['pressure'] == [abs(rpm), 0], (name, block)
                assert block['connections']['east']['pressure'] == [0, abs(rpm)], (name, block)
                for face in ('west', 'east'):
                    flow = block['connections'][face]['flow']
                    if flow:
                        assert flow['fluid'] == dict(id='minecraft:' + fluid_kind(name), amount=1), flow
                        assert flow['inbound'] == (face == 'west'), flow
        target = [amount(row[-1]) for row in lane_rows]
        first = next(i for i, amount in enumerate(target, 1) if amount)
        rate = max(1, int(abs(rpm) / 2))
        assert target == [max(0, tick - first + 1) * rate for tick in range(1, len(target) + 1)], (name, target)
        devices = lane(name)[1:-1]
        order = [devices.index(pos) for ticker in rows[0]['ticker_order']['blockEntityTickers']
                 if (pos := tuple(ticker['pos'])) in devices]
        assert sorted(order) == list(range(len(devices))), (name, order)
        expected = model_startup(len(devices), order, abs(rpm), len(target))
        for tick, (row, (flows, transferred)) in enumerate(zip(lane_rows, expected, strict=True), 1):
            assert amount(row[-1]) == transferred, (name, tick, row[-1], transferred)
            for i, (pair, block) in enumerate(zip(flows, row[1:-1], strict=True)):
                for j, face in enumerate(('west', 'east')):
                    flow = block['connections'][face]['flow']
                    got = (flow['progress'] if flow['progress'] is not None else 1) if flow else None
                    assert (got is None and pair[j] is None or got is not None and pair[j] is not None
                            and abs(got - pair[j]) < 1e-7), (name, tick, i, face, got, pair[j])
        flow_started = [next(i for i, row in enumerate(lane_rows, 1) if row[segment]['connections'][face]['flow'])
                        for segment in range(1, len(lane_rows[0]) - 1) for face in ('west', 'east')]
        results[name] = dict(pressure=abs(rpm), first_transfer=first, per_tick=rate, flow_started=flow_started)
    return results


def backpressure(host):
    positions = lane('single')
    source, target = positions[0], positions[-1]
    phases = {}
    for label, kind, target_amount in [('wrong-fluid', 'lava', 1000), ('full', 'water', 8000), ('room', 'water', 7997)]:
        initial_source = amount(measure(host.call('block', {'pos': source})))
        # Rewriting the active source's NBT invalidates Java's cached handler.
        # Only change the destination in this pressure scenario.
        rows = observed(host, positions, 45 if label == 'room' else 5, (seed(target, kind, target_amount),))
        moved = 3 if label == 'room' else 0
        amounts = [[amount(row['blocks'][0]), amount(row['blocks'][-1])] for row in rows]
        assert amounts[-1] == [initial_source - moved, target_amount + moved], (label, amounts)
        assert all(a + b == initial_source + target_amount for a, b in amounts), (label, amounts)
        assert all(before[0] >= after[0] and before[1] <= after[1]
                   for before, after in zip(amounts, amounts[1:])), (label, amounts)
        phases[label] = dict(amounts=amounts[-1], first_move=next((i for i, pair in enumerate(amounts, 1)
                                                                  if pair[1] > target_amount), None))
    return phases


def cold_restart(host, positions):
    before = [measure(host.call('block', {'pos': p})) for p in positions]
    host.call('quit', {})
    deadline = time.monotonic() + 60
    while java.process_alive(java.BASE):
        if time.monotonic() >= deadline:
            raise RuntimeError('The private Java client did not save and exit')
        time.sleep(.2)
    assert java.launch(java.BASE)['ready']
    host.call('tick', {'frozen': True})
    after = [measure(host.call('block', {'pos': p})) for p in positions]
    return {'before': before, 'after': after}


def click_once(host, work, name, held, pos, face_offset):
    x, y, z = pos
    host.command(f'item replace entity @s weapon.mainhand with {held}')
    host.call('camera', {'position': (x + .5, y, z + 2.4), 'target': (x + .5, y + .6, z + face_offset)})
    host.call('capture', {'name': f'{work.name}/{name}-aim.png', 'frames': 4})
    hit = host.call('state', {})['hit']
    assert hit['pos'] == list(pos) and hit['face'] == 'south', hit
    host.call('input', {'key': 'use'})
    host.call('capture', {'name': f'{work.name}/{name}-after.png', 'frames': 6})


def wrench_reversal(host, work):
    positions = lane('single')
    source, pump, target = positions[0], positions[2], positions[-1]
    a, b = [amount(measure(host.call('block', {'pos': pos}))) for pos in (source, target)]
    click_once(host, work, 'reverse-pump', 'create:wrench', pump, .875)
    rows = observed(host, positions, 28)
    reverse = rows[-1]['blocks']
    assert reverse[2]['props']['facing'] == 'west' and reverse[2]['speed'] == -32, reverse
    assert all(amount(row['blocks'][0]) + amount(row['blocks'][-1]) == a + b for row in rows), rows[-1]
    assert amount(reverse[0]) > a and amount(reverse[-1]) < b, (a, b, reverse)
    for block in reverse[1:-1]:
        assert block['connections']['west']['pressure'] == [0, 32], block
        assert block['connections']['east']['pressure'] == [32, 0], block
    return {'before': [a, b], 'after': [amount(reverse[0]), amount(reverse[-1])]}


def drain_target(host, work, positions):
    target = positions[-1]
    a, b = [amount(measure(host.call('block', {'pos': pos}))) for pos in (positions[0], target)]
    click_once(host, work, 'reopen-target', BUCKET, target, 1)
    rows = observed(host, positions, 28)
    resumed = rows[-1]['blocks']
    assert all(amount(row['blocks'][0]) + amount(row['blocks'][-1]) == a + b - 1000 for row in rows), rows[-1]
    assert amount(resumed[0]) < a and amount(resumed[-1]) > b - 1000, (a, b, resumed)
    return {'before': [a, b], 'after': [amount(resumed[0]), amount(resumed[-1])]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cold', action='store_true', help='Restart the private reference with the full outlet parked')
    args = parser.parse_args()
    host = Original()
    work = Path(tempfile.mkdtemp(prefix='fluid-pump-java-', dir=ROOT / '.local'))
    print(work, flush=True)
    assert json.loads((java.BASE / 'manifest.json').read_text())['create_sha256'] == java.CREATE_SHA256
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {LOAD}')
        host.command('gamemode creative')
        host.call('observe_ticks', {'positions': [list(map(int, initial['position']))], 'ticks': 20})
        host.command(f'tp @s {X}.5 {Y+4} {Z+5}.5')
        setup(host)
        observed(host, POSITIONS, 16)
        rows = observed(host, POSITIONS, 115, [seed(lane(name)[0], fluid_kind(name), 8000) for name in CASES])
        (work / 'observed.json').write_text(json.dumps(rows, indent=2) + '\n')
        phases = verify(rows)
        (work / 'startup.json').write_text(json.dumps(phases, indent=2) + '\n')
        blocked = backpressure(host)
        restart = cold_restart(host, lane('single')) if args.cold else None
        if restart:
            assert restart['before'] == restart['after'], restart
            restart['resumed'] = drain_target(host, work, lane('single'))
        result = dict(passed=True, create=PINS['create_revision'], phases=phases, blocked=blocked, restart=restart,
                      reversal=wrench_reversal(host, work))
        (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result, indent=2), flush=True)
    finally:
        host.command('item replace entity @s weapon.mainhand with minecraft:air')
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('camera', {'position': initial['position'], 'yaw': initial['yaw'], 'pitch': initial['pitch']})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


if __name__ == '__main__':
    main()
