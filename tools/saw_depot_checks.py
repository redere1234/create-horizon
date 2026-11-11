#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare Saw-to-Depot output and backpressure in Java Create and Horizon."""

import argparse
import errno
import json
from pathlib import Path
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field, items, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession
from saw_processing_checks import row as saw_row


EAST = ((1087, 130, 254), (1088, 130, 254))
WEST = ((1120, 130, 254), (1119, 130, 254))
BUFFER = ((1100, 130, 254), (1101, 130, 254))
POINTS = [*EAST, *WEST, *BUFFER]
LOAD = '1072 240 1135 255'
REGION = '1083 127 250 1124 134 255'
DROPS = '@e[type=minecraft:item,x=1083,y=127,z=250,dx=41,dy=10,dz=5]'
PHASE_TICKS = (27, 4, 4, 4)
STACK_LANES = (
    ((1093, 130, 254), (1094, 130, 254), 'minecraft:stripped_oak_log', 12),
    ((1113, 130, 254), (1114, 130, 254), 'minecraft:diamond', 70),
)
STACK_POINTS = [pos for saw, depot, _, _ in STACK_LANES for pos in (saw, depot)]
STACK_TICKS = (6, 16)
REMAINDERS = [
    (f'@e[type=minecraft:item,x={x + .5},y={y + 1},z={z + .5},distance=..1,limit=1]', item, count - 1)
    for (x, y, z), _, item, count in STACK_LANES
]


def command_at(command, verb, pos, text):
    command(f'{verb} {xyz(pos)} {text}')


def setup(command, native=False):
    command('fill ' + REGION + ' minecraft:air')
    command(f'kill {DROPS}')
    for saw, depot in (EAST, WEST, BUFFER):
        command_at(command, 'setblock', saw, 'create:mechanical_saw[facing=up,axis_along_first=false]')
        command_at(command, 'setblock', depot, 'create:depot')
    command_at(command, 'data merge block', EAST[1],
               '{HeldItem:{Item:{id:"minecraft:diamond",count:1},Pos:0.5f,PrevPos:0.5f,InDirection:1}}')
    command_at(command, 'data merge block', BUFFER[1],
               '{OutputBuffer:{Size:8,Items:[{Slot:0,id:"minecraft:diamond",count:1}]}}')
    # Load a completed cycle before connecting power. Reading Java's full
    # kinetic NBT into a live Saw would clear its established source.
    outputs = '[{Slot:1b,id:"minecraft:oak_planks",count:70},{Slot:2b,id:"minecraft:oak_stairs",count:2}]'
    # Horizon's data command uses native item slots for a Saw. The cycle
    # and Java fixture both use its canonical Create Inventory tag.
    generic_items = f',Items:{outputs}' if native else ''
    command_at(command, 'data merge block', BUFFER[0],
               '{Inventory:{Size:32,Items:' + outputs +
               ',ProcessingTime:0f,RecipeTime:20f,AppliedRecipe:1b}' + generic_items + '}')
    for (saw, _), speed in ((EAST, 128), (WEST, -128), (BUFFER, 128)):
        x, y, z = saw
        command_at(command, 'setblock', (x, y, z - 1),
                   f'create:creative_motor[facing=south]{{ScrollValue:{speed}}}')


def phase(command, index):
    if index == 0:
        for (x, y, z), _ in (EAST, WEST):
            command(f'summon minecraft:item {x + .5} {y + 1.3} {z + .5} '
                    '{PickupDelay:32767s,Item:{id:"minecraft:oak_log",count:1}}')
    elif index == 1:
        command_at(command, 'data remove block', EAST[1], 'HeldItem')
        command_at(command, 'data merge block', BUFFER[1], '{OutputBuffer:{Size:8,Items:[]}}')
    else:
        command_at(command, 'data remove block', BUFFER[1], 'HeldItem')


def depot_row(raw):
    held = None
    if 'HeldItem' in raw:
        nbt = field(raw, 'HeldItem')
        held = [items(nbt, 'Item'), int(number({'nbt': nbt}, 'InDirection'))]
    output = items(raw, 'OutputBuffer') if 'OutputBuffer' in raw else {}
    return [held, output]


def sample(raw):
    return [saw_row(nbt) if i % 2 == 0 else depot_row(nbt) for i, nbt in enumerate(raw)]


def verify(phases):
    stripped = 'minecraft:stripped_oak_log'
    planks = 'minecraft:oak_planks'
    stairs = 'minecraft:oak_stairs'
    diamond = 'minecraft:diamond'
    blocked = phases[0][-1]
    assert blocked == [
        [0, 20, 1, 0, [[1, stripped, 1]]], [[{diamond: 1}, 1], {}],
        [0, 20, 1, 0, []], [[{stripped: 1}, 4], {}],
        [0, 20, 1, 0, [[1, planks, 70], [2, stairs, 2]]], [None, {diamond: 1}],
    ], blocked
    assert all(row[3][0] is None for row in phases[0][:16]), phases[0]
    assert phases[0][16][3][0] == [{stripped: 1}, 4], phases[0][16]
    assert all(row[0] == blocked[0] and row[1] == blocked[1] for row in phases[0][16:]), phases[0]
    assert phases[1][0] == [
        [0, 20, 1, 0, []], [[{stripped: 1}, 5], {}],
        [0, 20, 1, 0, []], [[{stripped: 1}, 4], {}],
        [0, 20, 1, 0, [[1, planks, 6], [2, stairs, 2]]], [[{planks: 64}, 5], {}],
    ], phases[1][0]
    assert phases[2][0][-2:] == [
        [0, 20, 1, 0, [[2, stairs, 2]]], [[{planks: 6}, 5], {}],
    ], phases[2][0]
    assert phases[3][0][-2:] == [
        [0, 20, 1, 0, []], [[{stairs: 2}, 5], {}],
    ], phases[3][0]


def stack_setup(command):
    command('fill ' + REGION + ' minecraft:air')
    command(f'kill {DROPS}')
    for (x, y, z), depot, _, _ in STACK_LANES:
        command_at(command, 'setblock', (x, y, z), 'create:mechanical_saw[facing=up,axis_along_first=false]')
        command_at(command, 'setblock', depot, 'create:depot')
        command_at(command, 'setblock', (x, y, z - 1), 'create:creative_motor[facing=south]{ScrollValue:128}')


def stack_drop(command):
    for (x, y, z), _, item, count in STACK_LANES:
        command(f'summon minecraft:item {x + .5} {y + 1.3} {z + .5} '
                f'{{PickupDelay:32767s,Item:{{id:"{item}",count:{count}}}}}')


def verify_stacks(phases):
    stripped = 'minecraft:stripped_oak_log'
    planks = 'minecraft:oak_planks'
    diamond = 'minecraft:diamond'
    assert all(row[0][-1] == row[2][-1] == [] for row in phases[0][:4]), phases[0]
    first = phases[0][4]
    assert first[0][1:] == [50, 0, 0, [[0, stripped, 1]]], first
    assert first[2] == [20, 20, 1, 0, [[0, diamond, 1]]], first
    assert abs(first[0][0] - (50 - 128 / 24)) < 1e-5, first
    assert phases[1][-1] == [
        [0, 20, 1, 0, []], [[{planks: 6}, 5], {}],
        [0, 20, 1, 0, []], [[{diamond: 1}, 5], {}],
    ], phases[1][-1]


def java_run(stacks):
    host = Original()
    scratch = Path(tempfile.mkdtemp(prefix='saw-depot-java-', dir=ROOT / '.local'))
    before = host.call('state', {})
    if before.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        before = host.call('state', {})
    assert before['ready'] and before['data_version'] == 3955, before
    host.call('tick', {'frozen': True})
    try:
        host.command('gamemode creative')
        host.command('tp @s 1101.5 138 250.5')
        host.command('forceload add ' + LOAD)
        points = STACK_POINTS if stacks else POINTS
        host.snapshot(points, 25)
        if stacks:
            stack_setup(host.command)
        else:
            setup(host.command)
        host.snapshot(points, 12)
        phases = []
        for i, ticks in enumerate(STACK_TICKS if stacks else PHASE_TICKS):
            if stacks and i == 0:
                stack_drop(host.command)
            elif not stacks:
                phase(host.command, i)
            observed = host.call('observe_ticks', {'positions': points, 'ticks': ticks})['samples']
            phases.append([sample([block['nbt'] for block in row['blocks']]) for row in observed])
            if stacks and i == 0:
                for selector, item, count in REMAINDERS:
                    remainder = ' '.join(host.command(f'data get entity {selector} Item')['messages'])
                    assert item in remainder and number({'nbt': remainder}, 'count') == count, remainder
                    host.command(f'kill {selector}')
            reply = host.command(f'execute if entity {DROPS} run say saw_depot_loose')
            assert not any('saw_depot_loose' in row for row in reply['messages']), reply
        (verify_stacks if stacks else verify)(phases)
        return scratch, phases
    finally:
        host.command('fill ' + REGION + ' minecraft:air')
        host.command(f'kill {DROPS}')
        host.command('forceload remove ' + LOAD)
        host.call('tick', {'frozen': before['server']['frozen']})
        (scratch / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    phases = []
    for i, ticks in enumerate(PHASE_TICKS):
        batch = Batch()
        batch.load((1101, 137, 250))
        if i == 0:
            setup(batch.command, native=True)
            batch.tick(12)
        phase(batch.command, i)
        for _ in range(ticks):
            batch.tick()
            for pos in POINTS:
                batch.data(pos)
        batch.command(f'execute if entity {DROPS} run say saw_depot_loose', True)
        values = batch.run(session, f'saw-depot-{i}')
        assert len(values) == len(POINTS) * ticks + 1 and 'saw_depot_loose' not in values[-1], values
        phases.append([sample(values[j:j + len(POINTS)]) for j in range(0, len(values) - 1, len(POINTS))])
    verify(phases)
    return phases


def native_stacks(session):
    batch = Batch()
    batch.load((1101, 137, 250))
    stack_setup(batch.command)
    batch.tick(12)
    stack_drop(batch.command)
    for phase_no, ticks in enumerate(STACK_TICKS):
        for _ in range(ticks):
            batch.tick()
            for pos in STACK_POINTS:
                batch.data(pos)
        if phase_no == 0:
            for selector, _, _ in REMAINDERS:
                batch.command(f'data get entity {selector} Item', True)
                batch.command(f'kill {selector}')
        batch.command(f'execute if entity {DROPS} run say saw_depot_loose', True)
    values = batch.run(session, 'saw-stack-landing')
    phases = []
    start = 0
    for phase_no, ticks in enumerate(STACK_TICKS):
        stop = start + len(STACK_POINTS) * ticks
        phases.append([sample(values[i:i + len(STACK_POINTS)]) for i in range(start, stop, len(STACK_POINTS))])
        if phase_no == 0:
            for _, item, count in REMAINDERS:
                remainder = values[stop]
                assert item in remainder and number({'nbt': remainder}, 'count') == count, remainder
                stop += 1
        assert 'saw_depot_loose' not in values[stop], values[stop]
        start = stop + 1
    assert start == len(values), (start, len(values))
    verify_stacks(phases)
    return phases


def compare(actual, expected, points):
    for phase_no, (received, source) in enumerate(zip(actual, expected, strict=True)):
        for tick, (a, b) in enumerate(zip(received, source, strict=True), 1):
            for i, (got, want) in enumerate(zip(a, b, strict=True)):
                if i % 2:
                    assert got == want, (phase_no, tick, points[i], got, want)
                else:
                    assert abs(got[0] - want[0]) < 1e-5 and got[1:] == want[1:], (
                        phase_no, tick, points[i], got, want)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--stacks', action='store_true', help='check the default single-item input limit')
    for flag in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        scratch, phases = java_run(args.stacks)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon runs require --game, --resources, --ctl and --reference')
        expected = json.loads(args.reference.read_text())
        assert expected['passed'] and expected['create'] == PINS['create_revision'], expected
        assert expected.get('stacks', False) == args.stacks, expected
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='saw-depot-native', graphics=False, world='CreateSawDepot')
        scratch = session.scratch
        try:
            phases = (native_stacks if args.stacks else native_run)(session)
            compare(phases, expected['phases'], STACK_POINTS if args.stacks else POINTS)
        finally:
            session.control_temp.cleanup()
            try:
                shutil.rmtree(session.resources)
            except OSError as error:
                if error.errno != errno.ENOTEMPTY:
                    raise
                shutil.rmtree(session.resources)
    path = scratch / 'result.json'
    result = dict(passed=True, create=PINS['create_revision'], stacks=args.stacks, phases=phases)
    path.write_text(json.dumps(result, indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
