#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Check straight dry stairs on Java Create and Horizon bearings and pistons."""

import argparse
import errno
import json
from pathlib import Path
import shutil
import tempfile

from bearing_barrel_checks import check_blocks, pose
from bearing_chunk_sweep_checks import position, put
from bearing_native_checks import Batch
from bearing_reference_checks import offset
from bearing_slab_checks import HEIGHT_TOLERANCE
from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession
from piston_checks import rig as piston_rig


X, Z = 1544, 1032
CAMERA = (X, 144, Z)
ROOM = '1538 97 1026 1550 142 1038'
FORCE = '1536 1024 1551 1039'
AIR, SLIME = 'minecraft:air', 'minecraft:slime_block'
EAST, UP, SOUTH = (1, 0, 0), (0, 1, 0), (0, 0, 1)
TICKS = (10, 20, 29)
PISTON = ('east', (X, 132, Z), 0, 1, (0, 0, -1), True, False)
PARKED = (X, 119, Z)
PARKED_ANCHOR = offset(PARKED, UP)
PARKED_TREAD = offset(PARKED_ANCHOR, EAST)
CONTACTS = {'low': (X + 1.5, 121.45, Z + .75), 'high': (X + 1.5, 121.45, Z + .25)}


def stair(material, facing, half, shape='straight', wet='false'):
    return f'minecraft:{material}_stairs[facing={facing},half={half},shape={shape},waterlogged={wet}]'


def rotate(local, axis, turns):
    for _ in range(turns):
        x, y, z = local
        local = ((x, -z, y), (z, y, -x), (-y, x, z))[axis]
    return local


class Bearing:
    def __init__(self, axis, facing, direction, radial, states):
        self.axis, self.facing = axis, facing
        self.pivot = (X, 103 + 5 * axis, Z)
        self.anchor = offset(self.pivot, direction)
        self.motor = offset(self.pivot, direction, -1)
        self.locals = (radial, tuple(-part for part in radial))
        self.states = states
        self.sources = tuple(offset(self.anchor, local) for local in self.locals)

    def setup(self, command):
        put(command, self.pivot, f'create:mechanical_bearing[facing={self.facing}]')
        put(command, self.anchor, SLIME)
        for pos, block in zip(self.sources, self.states, strict=True):
            put(command, pos, block)
        put(command, self.motor, f'create:creative_motor[facing={self.facing}]{{ScrollValue:32}}')

    def targets(self, turns):
        return tuple(offset(self.anchor, rotate(local, self.axis, turns)) for local in self.locals)

    def points(self, turns):
        return tuple(dict.fromkeys((self.pivot, self.anchor, *self.sources, *self.targets(turns))))


BEARINGS = (
    Bearing(0, 'east', EAST, SOUTH, (stair('oak', 'north', 'bottom'), stair('stone', 'east', 'top'))),
    Bearing(1, 'up', UP, EAST, (stair('oak', 'east', 'bottom'), stair('stone', 'south', 'top'))),
    Bearing(2, 'south', SOUTH, EAST, (stair('oak', 'west', 'bottom'), stair('stone', 'south', 'top'))),
)
PISTON_SOURCES = ((X + 1, 132, Z - 1), (X + 1, 132, Z + 1))
PISTON_STATES = (stair('oak', 'north', 'bottom'), stair('stone', 'south', 'top'))
PISTON_TARGETS = tuple(offset(pos, EAST, 3) for pos in PISTON_SOURCES)


def prepare_piston(command):
    power, _, _ = piston_rig(PISTON, lambda pos, block: put(command, pos, block))
    put(command, (X + 1, 132, Z), SLIME)
    for pos, block in zip(PISTON_SOURCES, PISTON_STATES, strict=True):
        put(command, pos, block)
    power(False)


def prepare_parked(command):
    put(command, PARKED, 'create:mechanical_bearing[facing=up]{ScrollValue:2}')
    put(command, PARKED_ANCHOR, SLIME)
    put(command, PARKED_TREAD, stair('oak', 'north', 'bottom'))
    put(command, offset(PARKED, UP, -1), 'create:creative_motor[facing=up]{ScrollValue:1}')


def selector(label):
    return f'@e[type=minecraft:item,tag=mounted_stair_{label},limit=1]'


def drop(command):
    for (label, pos), item in zip(CONTACTS.items(), ('stick', 'feather'), strict=True):
        command(f'summon minecraft:item {xyz(pos)} {{Tags:["mounted_stair_{label}"],PickupDelay:32767s,'
                f'Motion:[0d,-0.18d,0d],Item:{{id:"minecraft:{item}",count:1}}}}')


def contact(nbt):
    return [position(nbt)[1], int(number({'nbt': nbt}, 'OnGround', 0))]


def verify_contacts(samples):
    low, high = samples['low'], samples['high']
    assert low[1] == high[1] == 1, samples
    assert abs(low[0] - (PARKED_TREAD[1] + .5)) < HEIGHT_TOLERANCE, samples
    assert abs(high[0] - (PARKED_TREAD[1] + 1)) < HEIGHT_TOLERANCE, samples


def java_run(work):
    host = Original()
    initial = host.call('state', {})
    if initial.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})

    def observe(points, ticks):
        return dict(zip(points, host.snapshot(points, ticks), strict=True))

    try:
        host.command('gamemode creative')
        host.command(f'tp @s {X}.5 {CAMERA[1] + 1} {Z}.5')
        host.command('forceload add ' + FORCE)
        observe([BEARINGS[0].pivot], 25)
        rotations = []
        for turns, ticks in enumerate(TICKS, 1):
            host.command('fill ' + ROOM + ' ' + AIR)
            for rig in BEARINGS:
                rig.setup(host.command)
            points = [pos for rig in BEARINGS for pos in rig.points(turns)]
            captured = observe(points, ticks)
            for rig in BEARINGS:
                assert all(captured[pos]['block'] == AIR for pos in rig.points(turns)[1:]), captured
                put(host.command, rig.motor, AIR)
            landed = observe(points, 1)
            group = []
            for rig in BEARINGS:
                assert pose(captured[rig.pivot]['nbt'])[0] == 1 and pose(landed[rig.pivot]['nbt']) == [0, 0]
                assert landed[rig.anchor]['block'] == SLIME
                targets = rig.targets(turns)
                assert all(landed[pos]['block'] == AIR for pos in set(rig.sources) - set(targets)), landed
                states = []
                for pos, source in zip(targets, rig.states, strict=True):
                    result = landed[pos]
                    assert result['block'] == source.split('[')[0], result
                    assert result['properties']['shape'] == 'straight' and result['properties']['waterlogged'] == 'false', result
                    states.append(result['block'] + '[' + ','.join(f'{k}={v}' for k, v in result['properties'].items()) + ']')
                group.append(dict(pose=pose(captured[rig.pivot]['nbt']), states=states))
            rotations.append(group)

        prepare_parked(host.command)
        captured = observe([PARKED, PARKED_TREAD], 2)
        assert pose(captured[PARKED]['nbt']) == [1, .3] and captured[PARKED_TREAD]['block'] == AIR, captured
        put(host.command, offset(PARKED, UP, -1), AIR)
        drop(host.command)
        settled = observe([PARKED, PARKED_TREAD], 9)
        assert pose(settled[PARKED]['nbt'])[0] == 1 and settled[PARKED_TREAD]['block'] == AIR, settled
        samples = {label: contact(' '.join(host.command(f'data get entity {selector(label)}')['messages']))
                   for label in CONTACTS}
        verify_contacts(samples)

        prepare_piston(host.command)
        points = [PISTON[1], *PISTON_SOURCES, *PISTON_TARGETS]
        captured = observe(points, 4)
        assert number(captured[PISTON[1]], 'Running', 0) == 1, captured
        assert all(captured[pos]['block'] == AIR for pos in PISTON_SOURCES), captured
        landed = observe(points, 20)
        for pos, source in zip(PISTON_TARGETS, PISTON_STATES, strict=True):
            result = landed[pos]
            assert result['block'] == source.split('[')[0], result
            expected = dict(entry.split('=') for entry in source.split('[')[1].rstrip(']').split(','))
            assert result['properties'] == expected, result
        return dict(rotations=rotations, contacts=samples, parked_pose=pose(settled[PARKED]['nbt']))
    finally:
        for label in CONTACTS:
            host.command(f'kill {selector(label)}')
        host.command(f'kill @e[type=create:stationary_contraption,x={X},y=118,z={Z},distance=..32]')
        host.command('fill ' + ROOM + ' ' + AIR)
        host.command('forceload remove ' + FORCE)
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def refusal_checks(batch):
    # A dry source can only be captured if it stands apart from other stairs.
    wet = (X, 124, Z)
    wet_source = offset(offset(wet, UP), EAST)
    batch.put(wet, 'create:mechanical_bearing[facing=up]')
    batch.put(offset(wet, UP), SLIME)
    batch.put(wet_source, stair('oak', 'north', 'bottom', wet='true'))
    batch.put(offset(wet, UP, -1), 'create:creative_motor[facing=up]{ScrollValue:32}')
    batch.tick(4)
    batch.data(wet)
    batch.expect(wet_source, stair('oak', 'north', 'bottom', wet='true'))

    # A stair next to the eventual landing is not part of the moving payload.
    # Ordinary terrain at that same neighbor does not prevent a retry.
    pivot = (X, 124, Z + 4)
    anchor = offset(pivot, UP)
    motor = offset(pivot, UP, -1)
    source = offset(anchor, EAST)
    target = offset(anchor, (0, 0, -1))
    neighbor = offset(target, EAST, -1)
    batch.put(pivot, 'create:mechanical_bearing[facing=up]')
    batch.put(anchor, SLIME)
    batch.put(source, stair('oak', 'north', 'bottom'))
    batch.put(motor, 'create:creative_motor[facing=up]{ScrollValue:32}')
    batch.tick(10)
    batch.put(neighbor, stair('stone', 'east', 'bottom'))
    batch.put(motor, AIR)
    batch.tick()
    batch.data(pivot)
    batch.expect(source, AIR)
    batch.expect(anchor, AIR)
    batch.expect(target, AIR)
    batch.put(neighbor, 'minecraft:stone')
    batch.tick()
    batch.data(pivot)
    batch.expect(target, stair('oak', 'west', 'bottom'))
    batch.expect(neighbor, 'minecraft:stone')

    # These stairs begin vertically stacked. Turning sideways would make them
    # horizontal neighbors within one landing plan, which must stay atomic.
    pivot = (X, 137, Z)
    anchor = offset(pivot, EAST)
    motor = offset(pivot, EAST, -1)
    sources = (offset(anchor, SOUTH), offset(offset(anchor, SOUTH), UP))
    targets = (offset(anchor, UP, -1), offset(offset(anchor, UP, -1), SOUTH))
    batch.put(pivot, 'create:mechanical_bearing[facing=east]')
    batch.put(anchor, SLIME)
    batch.put(offset(anchor, UP), SLIME)
    for pos in sources:
        batch.put(pos, stair('oak', 'north', 'bottom'))
    batch.put(motor, 'create:creative_motor[facing=east]{ScrollValue:32}')
    batch.tick(10)
    batch.data(pivot)
    for pos in sources:
        batch.expect(pos, AIR)
    batch.put(motor, AIR)
    batch.tick()
    batch.data(pivot)
    for pos in (anchor, *targets):
        batch.expect(pos, AIR)


def native_run(session, reference):
    batch = Batch()
    batch.load(CAMERA)
    for turns, ticks in enumerate(TICKS, 1):
        batch.command('fill ' + ROOM + ' ' + AIR)
        for rig in BEARINGS:
            rig.setup(batch.command)
        batch.tick(ticks)
        for rig in BEARINGS:
            batch.data(rig.pivot)
            for pos in rig.points(turns)[1:]:
                batch.expect(pos, AIR)
            batch.put(rig.motor, AIR)
        batch.tick()
        for rig, case in zip(BEARINGS, reference['rotations'][turns - 1], strict=True):
            batch.data(rig.pivot)
            batch.expect(rig.anchor, SLIME)
            targets = rig.targets(turns)
            for pos in set(rig.sources) - set(targets):
                batch.expect(pos, AIR)
            for pos, state in zip(targets, case['states'], strict=True):
                batch.expect(pos, state)

    prepare_parked(batch.command)
    batch.tick(2)
    batch.data(PARKED)
    batch.expect(PARKED_TREAD, AIR)
    batch.put(offset(PARKED, UP, -1), AIR)
    drop(batch.command)
    batch.tick(9)
    batch.data(PARKED)
    batch.expect(PARKED_TREAD, AIR)
    for label in CONTACTS:
        batch.command(f'data get entity {selector(label)}', True)

    prepare_piston(batch.command)
    batch.tick(4)
    batch.data(PISTON[1])
    for pos in PISTON_SOURCES:
        batch.expect(pos, AIR)
    batch.tick(20)
    for pos, state in zip(PISTON_TARGETS, PISTON_STATES, strict=True):
        batch.expect(pos, state)
    refusal_checks(batch)

    rows = iter(batch.run(session, 'stair-transform-and-collision'))
    for turns, group in enumerate(reference['rotations'], 1):
        for rig, case in zip(BEARINGS, group, strict=True):
            assert pose(next(rows)) == case['pose'], case
            check_blocks([next(rows) for _ in rig.points(turns)[1:]])
        for rig in BEARINGS:
            assert pose(next(rows)) == [0, 0]
            targets = rig.targets(turns)
            checks = 1 + len(set(rig.sources) - set(targets)) + len(targets)
            check_blocks([next(rows) for _ in range(checks)])
    assert pose(next(rows)) == [1, .3]
    check_blocks([next(rows)])
    parked = pose(next(rows))
    assert parked[0] == 1
    check_blocks([next(rows)])
    actual = {label: contact(next(rows)) for label in CONTACTS}
    verify_contacts(actual)
    assert all(abs(actual[label][0] - reference['contacts'][label][0]) < HEIGHT_TOLERANCE for label in CONTACTS)
    assert number({'nbt': next(rows)}, 'Running', 0) == 1
    check_blocks([next(rows) for _ in (*PISTON_SOURCES, *PISTON_TARGETS)])
    assert pose(next(rows)) == [0, 0]
    check_blocks([next(rows)])
    assert pose(next(rows))[0] == 1
    check_blocks([next(rows) for _ in range(3)])
    assert pose(next(rows)) == [0, 0]
    check_blocks([next(rows) for _ in range(2)])
    assert pose(next(rows))[0] == 1
    check_blocks([next(rows) for _ in range(2)])
    assert pose(next(rows))[0] == 1
    check_blocks([next(rows) for _ in range(3)])
    assert next(rows, None) is None
    return dict(contacts=actual, parked_pose=parked)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='contraption-stairs-java-', dir=ROOT / '.local'))
        report = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon runs require --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='contraption-stairs-native', graphics=False, world='CreateStairs')
        work = session.scratch
        try:
            report = dict(rotations=reference['rotations'], **native_run(session, reference),
                          refusal=['waterlogged', 'terrain stair neighbor', 'planned stair neighbors'])
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                if not folder.exists():
                    continue
                try:
                    shutil.rmtree(folder)
                except OSError as error:
                    if error.errno != errno.ENOTEMPTY:
                        raise
                    shutil.rmtree(folder)
    output = work / 'result.json'
    output.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], **report), indent=2) + '\n')
    print(output)


if __name__ == '__main__':
    main()
