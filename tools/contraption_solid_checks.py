#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare solid Create cargo on Java and Horizon bearings and pistons."""

import argparse
import errno
import json
from pathlib import Path
import shutil
import tempfile

from bearing_barrel_checks import check_blocks, pose
from bearing_chunk_sweep_checks import put
from bearing_native_checks import Batch
from bearing_reference_checks import offset
from burner_heat_java_checks import number
from catalog import PALETTE_BLOCKS, STATIC_BLOCKS, ZINC_BLOCKS
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from contraption_stair_checks import contact
from native_check_session import NativeCheckSession, wait_loaded
from piston_checks import rig as piston_rig


X, Z = 1704, 1096
ROOM = '1698 97 1090 1710 163 1102'
FORCE = '1696 1088 1711 1103'
CAMERA = (X + 3, 144, Z + 4)
AIR, SLIME = 'minecraft:air', 'minecraft:slime_block'
EAST, UP, NORTH = (1, 0, 0), (0, 1, 0), (0, 0, -1)
CARGO = tuple('create:' + block for block in (*PALETTE_BLOCKS, *ZINC_BLOCKS, *STATIC_BLOCKS))
BEARING = (X, 100, Z)
PISTON = (X, 130, Z)
PARKED = (X, 151, Z)
PARKED_ANCHOR = offset(PARKED, UP)
CONTACTS = {
    'stone': (offset(PARKED_ANCHOR, EAST), 'create:layered_andesite'),
    'iron': (offset(PARKED_ANCHOR, EAST, -1), 'create:weathered_iron_block'),
    'zinc': (offset(PARKED_ANCHOR, NORTH), 'create:zinc_ore'),
    'casing': (offset(PARKED_ANCHOR, NORTH, -1), 'create:brass_casing'),
    'air': ((X + 2, PARKED_ANCHOR[1], Z + 2), AIR),
}


def tower(anchor, side):
    return [offset(offset(anchor, UP, index // 2), side, 1 - 2 * (index % 2))
            for index in range(len(CARGO))]


def build_tower(command, anchor, side):
    sources = tower(anchor, side)
    for level in range((len(CARGO) + 1) // 2):
        put(command, offset(anchor, UP, level), SLIME)
    for pos, state in zip(sources, CARGO, strict=True):
        put(command, pos, state)
    return sources


def motor(pivot):
    return offset(pivot, UP, -1)


def build_bearing(command, pivot, rpm, never_place=False):
    config = '{ScrollValue:2}' if never_place else ''
    put(command, pivot, 'create:mechanical_bearing[facing=up]' + config)
    put(command, motor(pivot), f'create:creative_motor[facing=up]{{ScrollValue:{rpm}}}')


def build_piston(command):
    power, _, _ = piston_rig(('east', PISTON, 0, 1, NORTH, True, False),
                             lambda pos, state: put(command, pos, state))
    power(False)


def selector(label):
    return f'@e[type=minecraft:item,tag=solid_cargo_{label},limit=1]'


def build_collision_rig(command):
    put(command, PARKED_ANCHOR, SLIME)
    for pos, state in CONTACTS.values():
        if state != AIR:
            put(command, pos, state)
    build_bearing(command, PARKED, 1, never_place=True)


def drop(command):
    for label, ((x, y, z), _) in CONTACTS.items():
        command(f'summon minecraft:item {x + .5} {y + 1.45} {z + .5}'
                f' {{Tags:["solid_cargo_{label}"],PickupDelay:32767s,'
                'Motion:[0d,-0.18d,0d],Item:{id:"minecraft:stick",count:1}}')


def check_contacts(samples):
    for label, (height, grounded) in samples.items():
        if label == 'air':
            assert grounded == 0 and height < PARKED_ANCHOR[1], samples
        else:
            assert grounded == 1 and abs(height - (PARKED_ANCHOR[1] + 1)) < .000101, samples


def java_run(work):
    host = Original()
    initial = host.call('state', {})
    if initial.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})

    def observe(c, points, ticks, expected):
        controller, *blocks = host.snapshot((c, *points), ticks)
        assert [b['block'] for b in blocks] == list(expected), (c, blocks)
        assert all(not b['properties'] and not b['nbt'] for b in blocks), blocks
        return controller['nbt']

    try:
        host.command('gamemode creative')
        host.command(f'tp @s {CAMERA[0]}.5 {CAMERA[1]} {CAMERA[2]}.5')
        host.command('forceload add ' + FORCE)
        host.snapshot([BEARING], 25)
        host.command('fill ' + ROOM + ' ' + AIR)

        anchor = offset(BEARING, UP)
        sources = build_tower(host.command, anchor, EAST)
        build_bearing(host.command, BEARING, 32)
        bearing = pose(observe(BEARING, sources, 10, [AIR] * len(CARGO)))
        assert bearing[0] == 1 and 85 < bearing[1] < 90, bearing
        put(host.command, motor(BEARING), AIR)
        assert pose(observe(BEARING, tower(anchor, NORTH), 1, CARGO)) == [0, 0]

        build_piston(host.command)
        anchor = offset(PISTON, EAST)
        sources = build_tower(host.command, anchor, NORTH)
        piston = observe(PISTON, sources, 4, [AIR] * len(CARGO))
        assert number({'nbt': piston}, 'Running', 0) == 1, piston
        landed = observe(PISTON, tower(offset(anchor, EAST, 3), NORTH), 20, CARGO)
        assert number({'nbt': landed}, 'Running', 0) == 0, landed

        build_collision_rig(host.command)
        points = [pos for pos, _ in CONTACTS.values()]
        assert pose(observe(PARKED, points, 2, [AIR] * len(points))) == [1, .3]
        put(host.command, motor(PARKED), AIR)
        drop(host.command)
        assert pose(observe(PARKED, points, 9, [AIR] * len(points)))[0] == 1
        contacts = {label: contact(' '.join(host.command(f'data get entity {selector(label)}')['messages']))
                    for label in CONTACTS}
        check_contacts(contacts)
        return dict(blocks=CARGO, bearing=bearing, piston_offset=number({'nbt': piston}, 'Offset', 0),
                    contacts=contacts)
    finally:
        for label in CONTACTS:
            host.command(f'kill {selector(label)}')
        host.command(f'kill @e[type=create:stationary_contraption,x={X},y=152,z={Z},distance=..10]')
        host.command('fill ' + ROOM + ' ' + AIR)
        host.command('forceload remove ' + FORCE)
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session, reference):
    batch = Batch()
    batch.load(CAMERA)
    batch.command('fill ' + ROOM + ' ' + AIR)

    def observe(controller, points, ticks, expected):
        batch.tick(ticks)
        batch.data(controller)
        for pos, block in zip(points, expected, strict=True):
            batch.expect(pos, block)

    anchor = offset(BEARING, UP)
    sources = build_tower(batch.command, anchor, EAST)
    build_bearing(batch.command, BEARING, 32)
    observe(BEARING, sources, 10, [AIR] * len(CARGO))
    batch.put(motor(BEARING), AIR)
    observe(BEARING, tower(anchor, NORTH), 1, CARGO)

    build_piston(batch.command)
    anchor = offset(PISTON, EAST)
    sources = build_tower(batch.command, anchor, NORTH)
    observe(PISTON, sources, 4, [AIR] * len(CARGO))
    observe(PISTON, tower(offset(anchor, EAST, 3), NORTH), 20, CARGO)

    build_collision_rig(batch.command)
    points = [pos for pos, _ in CONTACTS.values()]
    observe(PARKED, points, 2, [AIR] * len(points))
    batch.put(motor(PARKED), AIR)
    drop(batch.command)
    observe(PARKED, points, 9, [AIR] * len(points))
    for label in CONTACTS:
        batch.command(f'data get entity {selector(label)}', True)

    rows = iter(batch.run(session, 'solid-cargo'))

    def read(count):
        nbt = next(rows)
        check_blocks([next(rows) for _ in range(count)])
        return nbt

    assert pose(read(len(CARGO))) == reference['bearing']
    assert pose(read(len(CARGO))) == [0, 0]
    piston = {'nbt': read(len(CARGO))}
    assert number(piston, 'Running', 0) == 1
    assert number(piston, 'Offset', 0) == reference['piston_offset']
    assert number({'nbt': read(len(CARGO))}, 'Running', 0) == 0
    assert pose(read(len(points))) == [1, .3]
    assert pose(read(len(points)))[0] == 1
    contacts = {label: contact(next(rows)) for label in CONTACTS}
    check_contacts(contacts)
    assert all(abs(contacts[label][0] - reference['contacts'][label][0]) < .000101
               for label in CONTACTS if label != 'air'), contacts
    assert next(rows, None) is None
    return dict(blocks=CARGO, bearing=reference['bearing'], piston_offset=reference['piston_offset'],
                contacts=contacts)


def screenshot(session):
    path = session.scratch / 'moving-solid-cargo.png'
    with session:
        call = session.call
        view = f'tp @s {X + 4.5} 154 {Z + 5.5}'
        call('command', view)
        wait_loaded(call, [PARKED])
        assert pose(' '.join(call('command', f'data get block {xyz(PARKED)}')['chat']))[0] == 1
        for label, (pos, _) in CONTACTS.items():
            assert call('block', *pos)['block'] == AIR
            call('command', f'kill {selector(label)}')
        call('command', f'fill {X - 4} 149 {Z - 4} {X + 6} 149 {Z + 6} minecraft:smooth_stone')
        call('command', f'setblock {X + 4} 153 {Z + 5} minecraft:smooth_stone')
        call('command', view)
        call('wait', 4)
        call('look-at', X + .5, PARKED_ANCHOR[1] + .2, Z + .5)
        call('wait', 8)
        call('key', 'f1', 'tap')
        call('screenshot', path)
    assert path.stat().st_size > 1024
    return str(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--screenshot', action='store_true')
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='contraption-solid-java-', dir=ROOT / '.local'))
        report = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon runs require --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision'], reference
        assert reference['blocks'] == list(CARGO), reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='contraption-solid-native', graphics=args.screenshot,
                                     world='CreateSolidCargo', username='BearingReview')
        work = session.scratch
        try:
            report = native_run(session, reference)
            if args.screenshot:
                report['screenshot'] = screenshot(session)
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
