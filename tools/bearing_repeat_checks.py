#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare five Mechanical Bearing clutch cycles with a chest and a barrel."""

import argparse
import json
from pathlib import Path
import re
import shutil
import struct
import tempfile

from bearing_barrel_checks import check_blocks, pose
from bearing_mounted_pair_checks import (
    AIR, EAST, FORCE, SOUTH, STORAGE, WEST, Rig, verify_inventory,
)
from bearing_native_checks import Batch
from bearing_reference_checks import offset
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from funnel_checks import step
from native_check_session import NativeCheckSession
from saved_block_checks import read_saved_chunk_tag


RIG = Rig(130, ('chest', 'barrel'), SOUTH)
NORTH = (0, 0, -1)
POINTS = (RIG.pivot, RIG.anchor, *(offset(RIG.anchor, side) for side in (WEST, SOUTH, EAST, NORTH)))
CAMERA = (1160, 134, 247)
ROOM = '1157 127 244 1164 134 250'
CLUTCH = offset(RIG.pivot, (0, -1, 0))
POWER = offset(CLUTCH, EAST)
MOTOR = offset(CLUTCH, (0, -1, 0))
SOURCE_ORDER = ([WEST, SOUTH], [SOUTH, EAST], [NORTH, EAST], [NORTH, WEST], [WEST, SOUTH])
SCENE = ('horizon:attachments', 'create', 'moving_structures', 'value')
POSES = ('horizon:attachments', 'create', 'moving_structure_poses', 'value')


def put(host, pos, state):
    host.command(f'setblock {xyz(pos)} {state}')


def original_order(host):
    x, y, z = RIG.anchor
    selector = f'@e[type=create:stationary_contraption,x={x},y={y},z={z},distance=..3,limit=1]'
    raw = ' '.join(host.command(f'data get entity {selector} Contraption.items')['messages'])
    return [list(map(int, match)) for match in re.findall(r'pos:\s*\[I;\s*(-?\d+),\s*(-?\d+),\s*(-?\d+)\]', raw)]


def setup(command, place):
    command(f'fill {ROOM} {AIR}')
    place(POWER, 'minecraft:redstone_block')
    place(CLUTCH, 'create:clutch[axis=y,powered=true]')
    RIG.setup(command, lambda pos, state: place(pos, state) if pos != CLUTCH else None)
    place(MOTOR, 'create:creative_motor[facing=up]{ScrollValue:16}')


def original_cycles(host):
    setup(host.command, lambda pos, state: put(host, pos, state))
    assert pose(step(host, 4, RIG.pivot)[0]['nbt']) == [0, 0]

    observations = []
    for expected_order in SOURCE_ORDER:
        put(host, POWER, AIR)
        moving = step(host, 20, *POINTS)
        moving_pose = pose(moving[0]['nbt'])
        # Java and Horizon can publish the clutch transition in different phases of a tick.
        assert moving_pose[0] == 1 and 85 < moving_pose[1] < 105, moving
        assert all(cell['id'] == AIR for cell in moving[1:]), moving
        order = original_order(host)
        assert order == [list(pos) for pos in expected_order], order

        put(host, POWER, 'minecraft:redstone_block')
        landed = step(host, 4, *POINTS)
        assert pose(landed[0]['nbt']) == [0, 0] and landed[1]['id'] == 'minecraft:slime_block', landed
        assert sorted(cell['id'] for cell in landed[2:]) == [
            AIR, AIR, 'minecraft:barrel', 'minecraft:chest',
        ], landed
        cells = []
        for cell in landed[2:]:
            kind = cell['id']
            items = verify_inventory(cell['nbt'], int(kind == 'minecraft:barrel')) if kind != AIR else []
            cells.append(dict(id=kind, properties=cell['properties'], items=items))
        observations.append(dict(order=order, moving_angle=moving_pose[1], landed=cells))
    return observations


def original(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    try:
        host.command('tp @s 1160.5 135 247.5')
        host.command(f'forceload add {FORCE}')
        step(host, 25, RIG.pivot)
        return original_cycles(host)
    finally:
        put(host, MOTOR, AIR)
        step(host, 3, RIG.pivot)
        host.command(f'fill {ROOM} {AIR}')
        host.command(f'forceload remove {FORCE}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_cycles(session, source):
    def saved(keys):
        return read_saved_chunk_tag(session.scratch, RIG.pivot, keys, session.world)['nbt']

    results = []
    for index, expected in enumerate(source, 1):
        batch = Batch()
        batch.load(CAMERA)
        if index == 1:
            setup(batch.command, batch.put)
            batch.tick(4)
        batch.put(POWER, AIR)
        batch.tick(20)
        batch.data(RIG.pivot)
        for pos in POINTS[1:]:
            batch.expect(pos, AIR)
        moving, *empty = batch.run(session, f'clutch-{index}-moving')
        moving_pose = pose(moving)
        assert moving_pose[0] == 1 and 85 < moving_pose[1] < 105, (index, moving)
        check_blocks(empty)

        geometry = saved(SCENE)['value']
        poses = saved(POSES)['value']
        assert geometry['Version']['value'] == 2 and poses['Version']['value'] == 1
        assert geometry['Generation'] == poses['Generation']
        [geometry_entry] = [tag['value'] for tag in geometry['Entries']['value']]
        [pose_entry] = [tag['value'] for tag in poses['Entries']['value']]
        assert len(geometry_entry['Blocks']['value']) == 3 and 'Angle' not in geometry_entry
        assert 'Blocks' not in pose_entry and pose_entry['Controller'] == geometry_entry['Controller']
        saved_angle, = struct.unpack('>f', struct.pack('>I', pose_entry['Angle']['value']))
        assert abs(saved_angle - moving_pose[1]) < 0.0001, (saved_angle, moving_pose)

        storage = saved(STORAGE)['value']
        assert storage['Version']['value'] == 2, storage
        entries = [tag['value'] for tag in storage['Chests']['value']]
        assert all(entry['Controller']['value'] == list(RIG.pivot) for entry in entries), entries
        order = [entry['Pos']['value'] for entry in entries]
        assert order == expected['order'], (index, order, expected['order'])

        batch = Batch()
        batch.load(CAMERA)
        batch.put(POWER, 'minecraft:redstone_block')
        batch.tick(4)
        batch.data(RIG.pivot)
        batch.expect(RIG.anchor, 'minecraft:slime_block')
        for pos, cell in zip(POINTS[2:], expected['landed'], strict=True):
            props = ','.join(f'{name}={value}' for name, value in cell['properties'].items())
            batch.expect(pos, f"{cell['id']}[{props}]" if props else cell['id'])
        for pos, cell in zip(POINTS[2:], expected['landed'], strict=True):
            if cell['id'] != AIR:
                batch.data(pos)
        landed, *rows = batch.run(session, f'clutch-{index}-landed')
        assert pose(landed) == [0, 0], (index, landed)
        assert saved(SCENE) is None and saved(POSES) is None
        check_blocks(rows[:5])
        banks = (cell for cell in expected['landed'] if cell['id'] != AIR)
        for cell, raw in zip(banks, rows[5:], strict=True):
            assert verify_inventory(raw, int(cell['id'] == 'minecraft:barrel')) == cell['items']
        results.append(dict(order=order, moving_angle=moving_pose[1], saved_angle=saved_angle,
                            landed=expected['landed']))
    return results


def native(session, source):
    try:
        return native_cycles(session, source)
    finally:
        session.control_temp.cleanup()
        for folder in (session.resources, session.scratch / '.horizon-cache', session.scratch / 'horizon-mods'):
            shutil.rmtree(folder, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='bearing-repeat-java-', dir=ROOT / '.local'))
        cases = original(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon needs --game, --resources, --ctl and --reference')
        source = json.loads(args.reference.read_text())
        assert source['passed'] and source['create'] == PINS['create_revision'], source
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='bearing-repeat-native', world='BearingRepeat', graphics=False)
        work = session.scratch
        assert len(source['cases']) == len(SOURCE_ORDER), source
        cases = native(session, source['cases'])
    output = work / 'result.json'
    output.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], cases=cases), indent=2) + '\n')
    print(output)


if __name__ == '__main__':
    main()
