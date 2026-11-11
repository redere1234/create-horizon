#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare an upward stationary Saw's dropped-item cycle and restart."""
import argparse
import json
from pathlib import Path
import re
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession

INPUTS = ('minecraft:oak_log', 'minecraft:stripped_oak_log', 'minecraft:diamond')
OUTPUTS = (('minecraft:stripped_oak_log', 1), ('minecraft:oak_planks', 6), ('minecraft:diamond', 1))
POINTS = [(1240 + i * 4, 124, 55) for i in range(len(INPUTS))]
TICKS = 24


def rig(command):
    command('fill 1236 122 49 1253 132 62 minecraft:air')
    command('fill 1236 123 49 1253 123 62 minecraft:stone')
    command('kill @e[type=minecraft:item,x=1244,y=124,z=55,distance=..12]')
    for x, y, z in POINTS:
        command(f'setblock {x} {y} {z} create:mechanical_saw[facing=up,axis_along_first=false]')
        command(f'setblock {x} {y} {z - 1} create:creative_motor[facing=south]{{ScrollValue:128}}')


def drop(command):
    for (x, y, z), item in zip(POINTS, INPUTS, strict=True):
        command(f'summon minecraft:item {x+.5} {y+1.3} {z+.5} '
                f'{{PickupDelay:32767s,Item:{{id:"{item}",count:1}}}}')


def row(raw):
    items = []
    if 'Inventory' in raw:
        inventory = field(raw, 'Inventory')
        items = [[int(slot), item, int(count)] for slot, item, count in
                 ((re.search(r'\bSlot:\s*(\d+)', stack)[1],
                   re.search(r'\bid:\s*"([^"]+)"', stack)[1],
                   re.search(r'\bcount:\s*(\d+)', stack)[1])
                  for stack in re.findall(r'\{([^{}]*\bSlot:[^{}]*)\}', inventory))]
    nbt = {'nbt': raw}
    return [number(nbt, 'ProcessingTime', -1), number(nbt, 'RecipeTime', 0),
            number(nbt, 'AppliedRecipe', 0), number(nbt, 'RecipeIndex', 0), items]


def verify_output(trace):
    for i, (item, count) in enumerate(OUTPUTS):
        assert any(state[i][2] and state[i][4] == [[0 if i == 2 else 1, item, count]]
                   for state in trace), (i, trace)
        assert trace[-1][i] == [-1, 0, 0, 0, []], trace[-1][i]


def exports():
    for (x, y, z), (item, count) in zip(POINTS, OUTPUTS, strict=True):
        selector = (f'@e[type=minecraft:item,x={x+.5},y={y+1},z={z+.5},distance=..2.5,'
                    f'nbt={{Item:{{id:"{item}",count:{count}}}}},limit=1]')
        yield f'data get entity {selector} Item', item, count


def reference():
    host = Original()
    host.call('tick', {'frozen': True})
    host.command('gamemode creative')
    host.command('tp @s 1244.5 125 60.5')
    host.command('forceload add 1232 48 1263 63')
    host.snapshot(POINTS, 28)
    rig(host.command)
    host.snapshot(POINTS, 12)
    drop(host.command)
    rows = host.call('observe_ticks', {'positions': POINTS, 'ticks': TICKS})['samples']
    trace = [[row(block['nbt']) for block in sample['blocks']] for sample in rows]
    verify_output(trace)
    for command, item, count in exports():
        raw = ' '.join(host.command(command)['messages'])
        assert item in raw and number({'nbt': raw}, 'count') == count, raw
    work = Path(tempfile.mkdtemp(prefix='saw-processing-java-', dir=ROOT / '.local'))
    path = work / 'result.json'
    path.write_text(json.dumps(dict(create=PINS['create_revision'], trace=trace), indent=2) + '\n')
    print(path)


def native(session, expected, restart):
    batch = Batch()
    batch.load((1244, 124, 60))
    rig(batch.command)
    batch.tick(12)
    drop(batch.command)

    def observe(batch, count, label, finish):
        for _ in range(count):
            batch.tick()
            for pos in POINTS:
                batch.data(pos)
        output = list(exports()) if finish else []
        for command, _, _ in output:
            batch.command(command, True)
        values = batch.run(session, label)
        samples = len(POINTS) * count
        assert len(values) == samples + len(output), (len(values), count)
        for (_, item, amount), raw in zip(output, values[samples:], strict=True):
            assert item in raw and number({'nbt': raw}, 'count') == amount, raw
        return [[row(v) for v in values[i:i+len(POINTS)]] for i in range(0, samples, len(POINTS))]

    if restart:
        trace = observe(batch, 8, 'saw-before-restart', False)
        resumed = Batch()
        resumed.load((1244, 124, 60))
        trace.extend(observe(resumed, TICKS - 8, 'saw-after-restart', True))
    else:
        trace = observe(batch, TICKS, 'saw-full', True)
    verify_output(trace)
    if not restart:
        for actual, reference in zip(trace, expected, strict=True):
            for saw, java_saw in zip(actual, reference, strict=True):
                assert abs(saw[0] - java_saw[0]) < 1e-5 and saw[1:] == java_saw[1:], (saw, java_saw)
    return trace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'ctl', 'resources', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java:
        reference()
        return
    if not all((args.game, args.ctl, args.resources, args.reference)):
        parser.error('Horizon runs require --game, --ctl, --resources and --reference')
    expected = json.loads(args.reference.read_text())
    assert expected['create'] == PINS['create_revision']
    session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                 name='saw-processing-native', graphics=False, world='CreateSawProcessing')
    print(session.scratch, flush=True)
    try:
        trace = native(session, expected['trace'], False)
        restart = native(session, expected['trace'], True)
        path = session.scratch / 'result.json'
        path.write_text(json.dumps(dict(passed=True, trace=trace, restart=restart), indent=2) + '\n')
        print(path)
    finally:
        session.control_temp.cleanup()


if __name__ == '__main__':
    main()
