#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare free-falling ore and raw iron in real Create and Horizon clients."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field, items, number
from chain_drive_checks import Original
from common import PINS, ROOT
from crushing_wheel_checks import AIR, CONTROLLER, X, Y, wheels
from native_check_session import NativeCheckSession
import reference_java


ORE = 'minecraft:diamond_ore'
RAW = 'minecraft:raw_iron'
XP = 'create:experience_nugget'
LANES = ((1002, ORE, 1, 350), (1009, RAW, 4, 400))
REGION = f'{X - 2} {Y - 2} 1000 {X + 2} {Y + 4} 1012'
LOAD = '2128 992 2143 1023'
CAMERA = (X, Y + 4, 1005)
POINTS = [(X, Y, z) for z, *_ in LANES]
DROPS = f'@e[type=minecraft:item,x={X-2},y={Y-2},z=1000,dx=4,dy=6,dz=12]'
OUTPUTS = ('minecraft:diamond', 'minecraft:cobblestone', 'create:crushed_raw_iron', XP)
TICKS = 200


def setup(command, advance):
    command(f'fill {REGION} {AIR}')
    command(f'fill {X - 2} {Y - 2} 1000 {X + 2} {Y - 2} 1012 minecraft:smooth_stone')
    command(f'kill {DROPS}')
    for z, *_ in LANES:
        wheels(command, z)
    advance(28)
    for z, item, count, _ in LANES:
        command(f'summon minecraft:item {X + .5} {Y + 2.25} {z + .5} '
                f'{{Motion:[0d,0d,0d],PickupDelay:40s,Item:{{id:"{item}",count:{count},'
                f'components:{{"minecraft:custom_data":{{crusher_probe:{z}}}}}}}}}')


def state(raw):
    inventory = field(raw, 'Inventory')
    return {
        'entity': 'Entity:' in raw.replace(' ', ''),
        'speed': number({'nbt': raw}, 'Speed'),
        'remaining': number({'nbt': inventory}, 'ProcessingTime'),
        'applied': bool(number({'nbt': inventory}, 'AppliedRecipe')),
        'items': items(raw, 'Inventory'),
        'marker': int(number({'nbt': inventory}, 'crusher_probe', 0)),
    }


def java(work):
    host = Original()
    manifest = json.loads((reference_java.BASE / 'manifest.json').read_text())
    assert manifest['create_sha256'] == reference_java.CREATE_SHA256
    prior = host.call('state', {})
    assert prior['ready'] and prior['data_version'] == 3955, prior
    host.call('tick', {'frozen': True})
    command = host.command

    def observe(ticks):
        return host.call('observe_ticks', {'positions': POINTS, 'ticks': ticks})['samples']

    try:
        command(f'tp @s {CAMERA[0]}.5 {CAMERA[1]} {CAMERA[2]}.5')
        command(f'forceload add {LOAD}')
        observe(30)
        setup(command, observe)
        trace = []
        while len(trace) < TICKS:
            for tick in observe(min(TICKS - len(trace), 60)):
                assert all(block['id'] == CONTROLLER for block in tick['blocks']), tick
                trace.append([state(block['nbt']) for block in tick['blocks']])
        results = []
        for z, *_ in LANES:
            found = host.call('entities', {'center': [X + .5, Y - .5, z + .5], 'radius': 1.4})['entities']
            results.append([items(entity['nbt'], 'Item') for entity in found if entity['type'] == 'minecraft:item'])
        return trace, results
    finally:
        command(f'kill {DROPS}')
        command(f'fill {REGION} {AIR}')
        command(f'forceload remove {LOAD}')
        host.call('camera', {key: prior[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': prior['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session):
    batch = Batch()
    batch.load(CAMERA)
    setup(batch.command, batch.tick)
    for _ in range(TICKS):
        batch.tick()
        for pos in POINTS:
            batch.data(pos)
    for z, *_ in LANES:
        area = f'type=minecraft:item,x={X - 1},y={Y - 2},z={z - 1},dx=2,dy=3,dz=2'
        for item in OUTPUTS:
            batch.command(f'data get entity @e[{area},nbt={{Item:{{id:"{item}"}}}},limit=1]', True)
    rows = batch.run(session, 'free-falling-ore')
    count = TICKS * len(LANES)
    trace = [[state(raw) for raw in rows[i:i+len(LANES)]] for i in range(0, count, len(LANES))]
    results = [[items(raw, 'Item') for raw in rows[i:i+len(OUTPUTS)] if 'Item:' in raw]
               for i in range(count, len(rows), len(OUTPUTS))]
    return trace, results


def summarize(trace, results):
    cases = []
    for lane, (z, item, count, duration) in enumerate(LANES):
        observations = [row[lane] for row in trace]
        assert all(row['speed'] == 1.28 for row in observations), observations[:4]
        entered = next(tick for tick, row in enumerate(observations, 1) if row['entity'])
        stored = next(tick for tick, row in enumerate(observations, 1) if item in row['items'])
        applied = next(tick for tick, row in enumerate(observations, 1) if row['applied'])
        ejected = next(tick for tick, row in enumerate(observations[applied:], applied + 1)
                       if not row['applied'] and not row['items'])
        assert entered < stored < applied < ejected, (entered, stored, applied, ejected)
        first = observations[stored - 1]
        assert first['items'] == {item: count} and first['remaining'] == duration and first['marker'] == z, first
        total = {}
        for output in results[lane]:
            for key, amount in output.items():
                total[key] = total.get(key, 0) + amount
        expected = 'minecraft:diamond' if item == ORE else 'create:crushed_raw_iron'
        assert count <= total.get(expected, 0) <= (2 * count if item == ORE else count), total
        assert total.get(XP, 0) <= count, total
        allowed = {expected, XP}
        if item == ORE:
            allowed.add('minecraft:cobblestone')
            assert total.get('minecraft:cobblestone', 0) <= count, total
        assert total.keys() <= allowed, total
        cases.append(dict(input=item, count=count, entered=entered, stored=stored,
                          applied=applied, ejected=ejected, outputs=total))
    return cases


def compare(trace, reference):
    for tick, (actual, expected) in enumerate(zip(trace, reference, strict=True), 1):
        for lane, (got, wanted) in enumerate(zip(actual, expected, strict=True)):
            assert abs(got['remaining'] - wanted['remaining']) < 1e-5, (tick, lane, got, wanted)
            observed = dict(got, remaining=wanted['remaining'])
            if wanted['applied']:
                # Chance outputs come from independent world random streams.
                observed['items'] = wanted['items']
            assert observed == wanted, (tick, lane, got, wanted)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.game:
        if not all((args.resources, args.ctl)):
            parser.error('Horizon requires --resources and --ctl')
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='crusher-drop-native', world='CrusherDrop')
        work = session.scratch
        try:
            trace, results = native(session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    else:
        work = Path(tempfile.mkdtemp(prefix='crusher-drop-java-', dir=ROOT / '.local'))
        trace, results = java(work)
    report = dict(passed=False, create=PINS['create_revision'], trace=trace, results=results)
    path = work / 'result.json'
    path.write_text(json.dumps(report, indent=2) + '\n')
    print(path, flush=True)
    report['cases'] = summarize(trace, results)
    if args.reference:
        source = json.loads(args.reference.read_text())
        assert source['passed'] and source['create'] == report['create']
        compare(trace, source['trace'])
    report['passed'] = True
    path.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
