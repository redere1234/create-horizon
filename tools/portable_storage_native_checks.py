#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Verify native portable item extraction, redstone, and saved inventory."""

import argparse
import json
from pathlib import Path

from actor_native_checks import matched
from bearing_native_checks import Batch
from burner_heat_java_checks import items, number
from chain_drive_checks import xyz
from common import PINS
from native_check_session import NativeCheckSession
from portable_storage_reference_checks import (
    AIR, BLOCK, COMPARATOR, HOPPER, MOTOR, MOVING, MOUNTED, OUTPUT, PIVOT, STATION,
    SWITCH, WIRE, X, Y, Z, rig,
)


POWERED_MOTOR = 'create:creative_motor[facing=up]{ScrollValue:32}'
RECEIVED = {'minecraft:wheat': 3, 'minecraft:stick': 2}


def setup(batch):
    batch.load((X, Y + 8, Z))
    batch.command(f'fill {X - 6} {Y - 3} {Z - 7} {X + 5} {Y + 5} {Z + 5} {AIR}')
    rig(batch.put, batch.command)
    batch.tick(3)


def observe(batch, reference):
    for step in reference:
        batch.tick()
        for pos in (PIVOT, STATION, HOPPER, OUTPUT):
            batch.data(pos)
        batch.expect(COMPARATOR, f'minecraft:comparator[powered={str(step["comparator"]).lower()}]')
        batch.expect(WIRE, f'minecraft:redstone_wire[power={step["wire"]}]')


def snapshots(rows):
    assert len(rows) % 6 == 0, len(rows)
    observations = []
    for i in range(0, len(rows), 6):
        bearing, psi, hopper, output, comparator, wire = rows[i:i + 6]
        observations.append(dict(
            angle=number({'nbt': bearing}, 'Angle', 0), timer=number({'nbt': psi}, 'Timer'),
            distance=number({'nbt': psi}, 'Distance'), powered=number({'nbt': psi}, 'Powered'),
            hopper=items(hopper, 'Items'), output=items(output, 'Items'),
            comparator_matches=matched(comparator), wire_matches=matched(wire), output_nbt=output,
        ))
    return observations


def compare(native, reference):
    assert len(native) == len(reference), (len(native), len(reference))
    failures = []
    for tick, (actual, expected) in enumerate(zip(native, reference), 1):
        fields = [name for name in ('timer', 'powered', 'hopper', 'output') if actual[name] != expected[name]]
        fields += [name for name in ('angle', 'distance') if abs(actual[name] - expected[name]) > 0.0002]
        fields += [name for name in ('wire', 'comparator') if not actual[f'{name}_matches']]
        if fields:
            failures.append(dict(tick=tick, fields=fields, actual=actual, expected=expected))
    return failures


def natural(session, reference):
    batch = Batch()
    setup(batch)
    batch.put(MOTOR, POWERED_MOTOR)
    observe(batch, reference)
    batch.expect(MOVING, AIR)
    batch.expect(MOUNTED, AIR)
    rows = batch.run(session, 'psi-natural')
    assert all(map(matched, rows[-2:])), rows[-2:]
    result = snapshots(rows[:-2])
    assert 'psi_probe:173' in result[-1]['output_nbt'].replace(' ', ''), result[-1]
    return result


def redstone(session, reference):
    batch = Batch()
    setup(batch)
    batch.put(MOTOR, POWERED_MOTOR)
    observe(batch, reference['initial'])
    batch.put(SWITCH, 'minecraft:redstone_block')
    observe(batch, reference['powered'])
    batch.put(SWITCH, AIR)
    observe(batch, reference['unpowered'])
    return snapshots(batch.run(session, 'psi-redstone'))


def refused(session):
    batch = Batch()
    setup(batch)
    batch.put(OUTPUT, 'minecraft:obsidian')
    for slot in range(5):
        count = 63 if slot == 4 else 64
        batch.command(f'item replace block {xyz(HOPPER)} container.{slot} with minecraft:cobblestone {count}')
    batch.put(MOTOR, POWERED_MOTOR)
    batch.tick(15)
    batch.data(STATION)
    batch.data(HOPPER)
    batch.put(MOTOR, AIR)
    batch.tick(4)
    chest = (X, Y + 1, Z + 1)
    batch.data(chest)
    interface = (X, Y + 1, Z - 2)
    batch.expect(interface, f'{BLOCK}[facing=north]')
    batch.put(interface, AIR + ' destroy')
    batch.command(f'execute if entity @e[type=minecraft:item,x={X},y={Y + 1},z={Z - 2},'
                  f'distance=..3,nbt={{Item:{{id:"{BLOCK}"}}}},limit=1] run say bearing_check', True)
    station, hopper, retained, landed, dropped = batch.run(session, 'psi-refused')
    assert 0 < number({'nbt': station}, 'Timer') < 14, station
    assert items(hopper, 'Items') == {'minecraft:cobblestone': 319}, hopper
    assert items(retained, 'Items') == RECEIVED, retained
    assert 'psi_probe:173' in retained.replace(' ', ''), retained
    assert matched(landed) and matched(dropped), (landed, dropped)
    return dict(station=station, hopper=hopper, retained=retained)


def restart(session):
    batch = Batch()
    setup(batch)
    batch.put(MOTOR, POWERED_MOTOR)
    batch.tick(23)
    batch.data(HOPPER)
    batch.data(OUTPUT)
    hopper, output = batch.run(session, 'psi-restart-moving')
    assert items(hopper, 'Items') == items(output, 'Items') == {'minecraft:wheat': 1}, (hopper, output)

    batch = Batch()
    batch.load((X, Y + 8, Z))
    batch.tick(160)
    batch.data(HOPPER)
    batch.data(OUTPUT)
    hopper, output = batch.run(session, 'psi-restart-restored')
    assert not items(hopper, 'Items') and items(output, 'Items') == RECEIVED, (hopper, output)
    assert 'psi_probe:173' in output.replace(' ', ''), output
    return dict(hopper=hopper, output=output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + flag, type=Path, required=True)
    parser.add_argument('--create-jar', type=Path)
    parser.add_argument('--case', choices=('natural', 'redstone', 'refused', 'restart'), action='append')
    args = parser.parse_args()
    reference = json.loads(args.reference.read_text())
    assert reference['create'] == PINS['create_revision']
    phases = reference['phases']
    scenarios = args.case or ('natural', 'redstone', 'refused', 'restart')
    paths = {}
    for name in scenarios:
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name=f'psi-native-{name}', graphics=False, world='CreatePSICheck')
        if name in ('natural', 'redstone'):
            result = (natural if name == 'natural' else redstone)(session, phases[name])
            java = phases[name] if name == 'natural' else [row for rows in phases[name].values() for row in rows]
            result = dict(trace=result, differences=compare(result, java))
        else:
            result = (restart if name == 'restart' else refused)(session)
        path = session.scratch / 'result.json'
        path.write_text(json.dumps(result, indent=2) + '\n')
        paths[name] = str(path)
        print(json.dumps(dict(case=name, path=str(path), differences=len(result.get('differences', [])))), flush=True)
        assert not result.get('differences'), (name, result['differences'][:5], path)
    print(json.dumps(paths))


if __name__ == '__main__':
    main()
