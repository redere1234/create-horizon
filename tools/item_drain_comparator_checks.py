#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare real comparator output after a Belt cycle and a direct Item Drain pour."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field, number
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from funnel_checks import step
from item_drain_checks import DRAIN, FULL, LANES, LOAD, X, Y, points, setup
from item_drain_hand_checks import FEET, POS, capture_click, held
from native_check_session import NativeCheckSession, wait_loaded
import reference_java


AREA = '2186 166 976 2194 173 991'
BELTS = ((points(LANES['open'])[1], 1), (points(LANES['blocked'])[1], 2))
MANUAL = (POS, 1)


def positions(sensor):
    (x, y, z), length = sensor
    return (x, y, z), (x, y, z + length), (x, y, z + length + 1)


def install(command, sensor):
    (x, y, z), length = sensor
    command(f'fill {x} {y - 1} {z} {x} {y - 1} {z + length + 1} minecraft:stone')
    if length == 2:
        command(f'setblock {x} {y} {z + 1} minecraft:stone')
    _, comparator, wire = positions(sensor)
    command(f'setblock {xyz(comparator)} minecraft:comparator[facing=north]')
    command(f'setblock {xyz(wire)} minecraft:redstone_wire')


def drain_state(raw):
    fluid = field(field(raw, 'Tanks'), 'TankContent')
    return int(number({'nbt': fluid}, 'amount', 0))


def snapshot(blocks):
    drain, comparator, wire = blocks
    return [drain_state(drain['nbt']), int(comparator['properties']['powered'].lower() == 'true'),
            int(wire['properties']['power'])]


def java_observe(host, sensors, ticks):
    result = host.call('observe_ticks', {'positions': [p for s in sensors for p in positions(s)],
                                         'ticks': ticks})
    return [[snapshot(row['blocks'][i:i+3]) for i in range(0, len(row['blocks']), 3)]
            for row in result['samples']]


def manual(host, work, advance):
    command = host.command
    command(f'fill {AREA} minecraft:air')
    command('fill 2187 167 978 2191 167 985 minecraft:smooth_stone')
    command(f'setblock {xyz(POS)} {DRAIN}')
    command(f'data merge block {xyz(POS)} {{Tanks:[{{TankContent:{{Fluid:{{id:"minecraft:water",amount:500}}}},'
            'Level:{Value:.3333333f,Target:.3333333f,Speed:.25f}}]}')
    install(command, MANUAL)
    before = advance(12)[-1]
    command('gamemode survival')
    command(f'item replace entity @s weapon.mainhand with {FULL}')
    capture_click(host, work, 'comparator-pour')
    assert held(host)['item'] == 'minecraft:bucket'
    return [before, *advance(5)]


def java_run(work):
    host = Original()
    manifest = json.loads((reference_java.BASE / 'manifest.json').read_text())
    assert manifest['create_sha256'] == reference_java.CREATE_SHA256
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955
    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {LOAD}')
        host.snapshot([POS], 20)
        host.command(f'fill {AREA} minecraft:air')
        setup(host.command, lambda ticks: host.snapshot([POS], ticks))
        for sensor in BELTS:
            install(host.command, sensor)
        auto = java_observe(host, BELTS, 28)
        pour = manual(host, work, lambda ticks: [row[0] for row in java_observe(host, (MANUAL,), ticks)])
        return dict(belt=auto, hand=pour)
    finally:
        host.command('gamemode creative')
        host.command('item replace entity @s weapon.mainhand with minecraft:air')
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('camera', {'position': initial['position'], 'yaw': initial['yaw'], 'pitch': initial['pitch']})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session, reference):
    batch = Batch()
    batch.load((X, Y + 4, 983))
    setup(batch.command, batch.tick)
    for sensor in BELTS:
        install(batch.command, sensor)
    for expected in reference['belt']:
        batch.tick()
        for sensor, (_, powered, power) in zip(BELTS, expected, strict=True):
            drain, comparator, wire = positions(sensor)
            batch.data(drain)
            batch.expect(comparator, f'minecraft:comparator[powered={str(bool(powered)).lower()}]')
            batch.expect(wire, f'minecraft:redstone_wire[power={power}]')
    rows = iter(batch.run(session, 'belt-comparator'))
    for tick, expected in enumerate(reference['belt'], 1):
        for sample in expected:
            raw, comparator, wire = next(rows), next(rows), next(rows)
            assert drain_state(raw) == sample[0] and 'bearing_check' in comparator and 'bearing_check' in wire, (
                tick, sample, raw, comparator, wire)
    assert next(rows, None) is None
    with session:
        host = Native(session)
        host.command(f'tp @s {xyz(FEET)}')
        wait_loaded(session.call, [POS])
        host.command('tick freeze')
        pour = manual(host, session.scratch, lambda ticks: [snapshot(step(host, 1, *positions(MANUAL)))
                                                          for _ in range(ticks)])
    assert pour == reference['hand'], (pour, reference['hand'])
    return reference


def verify(result):
    auto = result['belt']
    assert auto[:19] == [[[0, 0, 0]] * 2] * 19, auto
    assert auto[19:21] == [[[1000, 0, 0]] * 2] * 2, auto
    assert auto[21:] == [[[1000, 1, 10]] * 2] * 7, auto
    assert result['hand'][0] == [500, 1, 5], result['hand']
    assert result['hand'][1:] == [[1500, 1, 5]] + [[1500, 1, 15]] * 4, result['hand']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='drain-comparator-java-', dir=ROOT / '.local'))
        result = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon checks require --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='drain-comparator-native', world='CreateDrainComparator')
        work = session.scratch
        try:
            result = native_run(session, reference['samples'])
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    (work / 'observed.json').write_text(json.dumps(result, indent=2) + '\n')
    verify(result)
    path = work / 'result.json'
    path.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], samples=result), indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
