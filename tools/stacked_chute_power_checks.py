#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare redstone edges between a Chute and a Smart Chute in both ticker orders."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import items, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession


X, Y, Z = 2181, 126, 1512
CARGO = 'minecraft:iron_ingot'
POSITIONS = [(X, y, z) for z in (Z, Z + 3) for y in (Y + 1, Y, Y - 1)]
AREA = '2179 124 1510 2184 130 1516'
FORCE = '2176 1504 2191 1519'


def setup(command, advance, *, native=False):
    command(f'fill {AREA} minecraft:air')
    for index in range(2):
        upper, lower, receiver = POSITIONS[index * 3 : index * 3 + 3]
        chutes = [
            (upper, 'create:chute[facing=down,shape=window]'),
            (lower, 'create:smart_chute[powered=false]'),
        ]
        command(f'setblock {xyz(receiver)} minecraft:barrel')
        for pos, state in (reversed(chutes) if index else chutes):
            command(f'setblock {xyz(pos)} {state}')
    advance(15)
    for index, z in enumerate((Z, Z + 3), 1):
        stack = (
            f'id:"{CARGO}",count:7,'
            f'components:{{"minecraft:custom_data":{{stacked_signal:{index}}}}}'
        )
        live = f',Items:[{{Slot:0b,{stack}}}]' if native else ''
        command(f'data merge block {X} {Y+1} {z} {{Item:{{{stack}}},ItemPosition:0.1f{live}}}')
    signal(command, True)


def signal(command, power):
    block = 'redstone_block' if power else 'air'
    for z in (Z, Z + 3):
        command(f'setblock {X+1} {Y} {z} minecraft:{block}')


def measure(rows):
    result = []
    for index in range(2):
        lane = rows[index * 3 : index * 3 + 3]
        counts = [
            items(nbt, key).get(CARGO, 0)
            for nbt, key in zip(lane, ('Item', 'Item', 'Items'), strict=True)
        ]
        assert sum(counts) == 7, lane
        for count, nbt in zip(counts, lane, strict=True):
            if count:
                assert number({'nbt': nbt}, 'stacked_signal') == index + 1, nbt
        poses = [
            number({'nbt': nbt}, 'ItemPosition') if count else None
            for nbt, count in zip(lane[:2], counts[:2], strict=True)
        ]
        result.append(dict(counts=counts, poses=poses))
    return result


def java(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955
    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {FORCE}')
        host.command(f'tp @s {X}.5 130 {Z}.5')

        def advance(ticks):
            return host.call('observe_ticks', {'positions': POSITIONS, 'ticks': ticks})['samples']

        advance(24)
        setup(host.command, advance)
        parked = advance(3)
        signal(host.command, False)
        return [measure([block['nbt'] for block in row['blocks']]) for row in parked + advance(16)]
    finally:
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {FORCE}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session):
    batch = Batch()
    batch.load((X, 130, Z))
    setup(batch.command, batch.tick, native=True)
    for phase, ticks in enumerate((3, 16)):
        if phase:
            signal(batch.command, False)
        for _ in range(ticks):
            batch.tick()
            for pos in POSITIONS:
                batch.data(pos)
    rows = batch.run(session, 'stacked-power')
    return [
        measure(rows[index : index + len(POSITIONS)])
        for index in range(0, len(rows), len(POSITIONS))
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.game:
        if not all((args.resources, args.ctl, args.reference)):
            parser.error('Horizon needs --resources, --ctl and --reference')
        source = json.loads(args.reference.read_text())
        assert source['passed'] and source['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None, graphics=False,
                                     name='stacked-chute-native', world='StackedPower')
        work = session.scratch
        try:
            samples = native(session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    else:
        work = Path(tempfile.mkdtemp(prefix='stacked-chute-java-', dir=ROOT / '.local'))
        samples = java(work)
    path = work / 'result.json'
    report = dict(passed=False, create=PINS['create_revision'], samples=samples)
    path.write_text(json.dumps(report, indent=2) + '\n')
    assert samples[:3] == [[dict(counts=[7, 0, 0], poses=[.5, None])] * 2] * 3, samples[:3]
    assert all(lane['counts'] == [0, 0, 7] for lane in samples[-1]), samples[-1]
    if args.game:
        for tick, (row, expected) in enumerate(zip(samples, source['samples'], strict=True), 1):
            assert row == expected, (tick, row, expected)
    report['passed'] = True
    path.write_text(json.dumps(report, indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
