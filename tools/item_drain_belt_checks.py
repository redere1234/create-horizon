#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare an Item Drain releasing a bucket across a column into a stopped Belt."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field, items, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from item_drain_checks import BUCKET, DRAIN, held
from native_check_session import NativeCheckSession


Y, Z = 168, 978
SOURCE, DRAIN_POS, OUTPUT = (2187, Y, Z), (2191, Y, Z), (2192, Y, Z)
PROBES = (SOURCE, DRAIN_POS, OUTPUT)
REGION = '2186 166 975 2196 173 981'
TICKETS = '2176 976 2207 991'
WARM, RESUME = 38, 12


def motor(command, pos):
    x, y, z = pos
    command(f'setblock {x} {y} {z - 1} create:creative_motor[facing=south]{{ScrollValue:-32}}')


def install(command, step):
    command(f'fill {REGION} minecraft:air')
    command(f'setblock {xyz(DRAIN_POS)} {DRAIN}')
    for x, y, z in (SOURCE, OUTPUT):
        for i, part in enumerate(('start', 'middle', 'middle', 'end')):
            command(f'setblock {x + i} {y} {z} create:belt[facing=east,slope=horizontal,part={part}]')
    motor(command, SOURCE)
    step(24)
    command(f'data merge block {xyz(SOURCE)} {{Inventory:{{PositiveOrder:1b,Items:[{{'
            'Item:{id:"minecraft:lava_bucket",count:1},Pos:3.74f,PrevPos:3.74f,'
            'InSegment:3,InDirection:5,Angle:180}]}}')


def snapshot(source, drain, output):
    tank = field(field(drain, 'Tanks'), 'TankContent')
    amount = number({'nbt': tank}, 'amount', 0)
    assert not amount or 'minecraft:lava' in tank, tank
    receiving = field(output, 'Inventory')
    return dict(source=items(source, 'Inventory'), cargo=held(drain, pose=True), lava=amount,
                output=items(receiving, 'Items'), entry=[number({'nbt': receiving}, key, 0)
                for key in ('Pos', 'PrevPos', 'InSegment', 'InDirection')])


def verify(warm, cold, resumed):
    assert warm[-1] == cold, (warm[-1], cold)
    assert cold['lava'] == 1000 and not cold['source'] and not cold['output'], cold
    assert cold['cargo']['items'] == {BUCKET: 1} and cold['cargo']['pose'][:2] == [1, 1], cold
    first = next(row for row in resumed if row['output'])
    assert first['output'] == {BUCKET: 1} and first['cargo'] is None, first
    position, previous, segment, side = first['entry']
    assert 0.0 <= position < 0.2 and 0.0 <= previous < 0.2 and segment == 0 and side == 5, first
    assert resumed[-1]['output'] == {BUCKET: 1} and resumed[-1]['cargo'] is None, resumed[-1]


def java(work):
    host = Original()
    state = host.call('state', {})
    if state.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        state = host.call('state', {})
    assert state['ready'] and state['data_version'] == 3955

    def advance(ticks):
        return host.call('observe_ticks', {'positions': PROBES, 'ticks': ticks})['samples']

    def rows(ticks):
        return [snapshot(*(block['nbt'] for block in sample['blocks'])) for sample in advance(ticks)]

    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {TICKETS}')
        host.command('tp @s 2192.5 173 979.5')
        advance(24)
        install(host.command, advance)
        warm = rows(WARM)
        motor(host.command, OUTPUT)
        return warm, warm[-1], rows(RESUME)
    finally:
        host.command(f'fill {REGION} minecraft:air')
        host.command(f'forceload remove {TICKETS}')
        host.call('camera', {key: state[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': state['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session):
    def observe(batch):
        for pos in PROBES:
            batch.data(pos)

    def read(batch, label):
        data = batch.run(session, label)
        return [snapshot(*data[i:i + len(PROBES)]) for i in range(0, len(data), len(PROBES))]

    first = Batch()
    first.load((2192, 172, 979))
    install(first.command, first.tick)
    for _ in range(WARM):
        first.tick()
        observe(first)
    warm = read(first, 'blocked')

    second = Batch()
    second.load((2192, 172, 979))
    observe(second)
    motor(second.command, OUTPUT)
    for _ in range(RESUME):
        second.tick()
        observe(second)
    cold, *resumed = read(second, 'resume-after-restart')
    return warm, cold, resumed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.game:
        if not all((args.resources, args.ctl, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None, graphics=False,
                                     name='drain-belt-native', world='CreateDrainBelt')
        work = session.scratch
        try:
            warm, cold, resumed = native(session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        for label, rows in (('warm', warm), ('resumed', resumed)):
            for tick, (row, expected) in enumerate(zip(rows, reference[label], strict=True), 1):
                assert row == expected, (label, tick, row, expected)
    else:
        work = Path(tempfile.mkdtemp(prefix='drain-belt-java-', dir=ROOT / '.local'))
        warm, cold, resumed = java(work)
    verify(warm, cold, resumed)
    path = work / 'result.json'
    path.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], warm=warm,
                                    cold=cold, resumed=resumed), indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
