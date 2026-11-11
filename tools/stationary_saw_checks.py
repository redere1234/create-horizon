#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare a stationary horizontal Saw's breaking ticks and tree drops."""
import argparse
import json
from pathlib import Path
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession

SAW = (908, 100, 86)
MOTOR = (907, 100, 86)
TRUNK = [(909, y, 86) for y in range(100, 103)]
CANOPY = (910, 102, 86)
CONTROL = (913, 100, 87)
TICKS = 32
REGION = '898 96 82 915 109 94'
POINTS = [SAW, *TRUNK, CANOPY, CONTROL]


def rig(put):
    put(SAW, 'create:mechanical_saw[facing=east]')
    for p in TRUNK:
        put(p, 'minecraft:oak_log[axis=y]')
    put(CANOPY, 'minecraft:oak_leaves[distance=1,persistent=true]')
    put(CONTROL, 'minecraft:oak_log[axis=y]')
    put(MOTOR, 'create:creative_motor[facing=east]{ScrollValue:128}')


def trace(nbt):
    return [number(nbt, key, 0) for key in ('Speed', 'Progress', 'NextTick')]


def java_reference():
    host = Original()
    host.call('tick', {'frozen': True})
    host.command('gamemode creative')
    host.command('tp @s 902.5 103 89.5')
    host.command('forceload add 896 80 927 95')
    host.call('observe_ticks', {'ticks': 35, 'positions': [SAW]})
    host.command('fill ' + REGION + ' minecraft:air')
    rig(lambda pos, state: host.command(f'setblock {xyz(pos)} {state}'))
    rows = host.call('observe_ticks', {'ticks': TICKS, 'positions': POINTS})['samples']
    last = [b['id'] for b in rows[-1]['blocks']]
    assert last == ['create:mechanical_saw', *['minecraft:air'] * 4, 'minecraft:oak_log'], last
    samples = [trace(row['blocks'][0]) for row in rows]
    assert max(row[1] for row in samples) == 9, samples
    work = Path(tempfile.mkdtemp(prefix='stationary-saw-java-', dir=ROOT / '.local'))
    path = work / 'result.json'
    path.write_text(json.dumps(dict(create=PINS['create_revision'], trace=samples, final=last), indent=2) + '\n')
    print(path)


def horizon(session, reference):
    batch = Batch()
    batch.load((902, 102, 89))
    batch.command('fill ' + REGION + ' minecraft:air')
    rig(batch.put)
    for _ in range(TICKS):
        batch.tick()
        batch.data(SAW)
    for p, state in zip(POINTS, reference['final'], strict=True):
        batch.expect(p, state)
    batch.command('execute if entity @e[type=minecraft:item,nbt={Item:{id:"minecraft:oak_log"}},limit=1] run say bearing_check', True)
    rows = batch.run(session, 'stationary-saw')
    assert all('bearing_check' in row for row in rows[TICKS:]), rows[TICKS:]
    actual = [trace({'nbt': row}) for row in rows[:TICKS]]
    assert actual == reference['trace'], (actual, reference['trace'])
    return dict(passed=True, ticks=TICKS, world=str(session.scratch))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        java_reference()
        return
    if not all((args.game, args.resources, args.ctl, args.reference)):
        parser.error('--game, --resources, --ctl and --reference are required without --java')
    reference = json.loads(args.reference.read_text())
    assert reference['create'] == PINS['create_revision']
    session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                 name='stationary-saw-native', graphics=False, world='CreateSawChecks')
    try:
        result = horizon(session, reference)
        (session.scratch / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result))
    finally:
        session.control_temp.cleanup()


if __name__ == '__main__':
    main()
