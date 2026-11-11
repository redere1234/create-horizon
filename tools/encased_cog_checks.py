#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Exercise ordinary casing and wrench clicks on all four Encased Cogwheel blocks."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from burner_heat_java_checks import number
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from funnel_checks import block, click, put, step, text
from native_check_session import NativeCheckSession, wait_loaded
import reference_java

LOAD = '2384 1168 2415 1199'
REGION = '2396 165 1170 2405 171 1198'
WRENCH = 'create:wrench'
SHAFT = 'create:shaft[axis=x]'


def state(host, positions, ticks=4):
    return [dict(id=row['id'], properties={k: v.lower() for k, v in row['properties'].items()},
                 entity=re.findall(r'\bid:\s*"(create:[a-z_]+)"', row.get('nbt', '')),
                 rpm=number(row, 'Speed', 0)) for row in step(host, ticks, *positions)]


def scenario(host, work, material, large, z):
    x, y = 2400, 167
    pos = x, y, z
    west, east = (x - 1, y, z), (x + 1, y, z)
    cog = 'large_cogwheel' if large else 'cogwheel'
    target = f'create:{material}_encased_{cog}'
    feeder = x, y + large, z + 1
    motor = x - 1, y + large, z + 1
    positions = pos, west, east, feeder
    command = host.command
    command(f'fill 2396 166 {z-3} 2405 166 {z+2} minecraft:smooth_stone')
    put(command, pos, f'create:{cog}[axis=x]')
    put(command, west, SHAFT)
    put(command, east, SHAFT)
    put(command, feeder, 'create:cogwheel[axis=x]')
    put(command, motor, 'create:creative_motor[facing=east]{ScrollValue:32}')
    initial = state(host, positions, 12)
    speed = -16 if large else -32
    assert [node['rpm'] for node in initial] == [speed, speed, speed, 32], initial
    north_feet, north_aim = (x + .5, y, z - 2), (x + .5, y + .55, z + .5)
    east_feet, east_aim = (x + 2.7, y, z + .5), (x + 1, y + .55, z + .5)
    command('gamemode survival')
    click(host, work, f'{material}-{cog}-case', pos, 'north', north_feet, north_aim,
          f'create:{material}_casing 3')
    selected = text(host, 'data get entity @s SelectedItem')
    assert f'create:{material}_casing' in selected
    consumption = int(number({'nbt': selected}, 'count'))
    assert consumption == 3, selected
    encased = state(host, positions)
    expected = dict(id=target, properties={'axis': 'x', 'top_shaft': 'true', 'bottom_shaft': 'true'},
                    entity=[f'create:encased_{cog}'], rpm=speed)
    assert encased == [expected, *initial[1:]], encased
    put(command, east, 'minecraft:air')
    click(host, work, f'{material}-{cog}-close', pos, 'east', east_feet, east_aim, WRENCH)
    put(command, east, SHAFT)
    closed = state(host, positions)
    expected['properties'] = {**expected['properties'], 'top_shaft': 'false'}
    assert closed == [expected, initial[1], {**initial[2], 'rpm': 0.0}, initial[3]], closed
    put(command, east, 'minecraft:air')
    if isinstance(host, Native):
        host.session.call('key', 'f1', 'tap')
        try:
            image = work / f'{material}-{cog}-closed.png'
            host.session.call('screenshot', image)
            assert image.stat().st_size > 1024, image
        finally:
            host.session.call('key', 'f1', 'tap')
    click(host, work, f'{material}-{cog}-open', pos, 'east', east_feet, east_aim, WRENCH)
    put(command, east, SHAFT)
    reopened = state(host, positions)
    assert reopened == encased, reopened
    put(command, east, 'minecraft:air')
    click(host, work, f'{material}-{cog}-close-again', pos, 'east', east_feet, east_aim, WRENCH)
    click(host, work, f'{material}-{cog}-rotate', pos, 'north', north_feet, north_aim, WRENCH)
    rotated = state(host, positions)
    assert rotated[0] == {**expected, 'properties': {'axis': 'y', 'top_shaft': 'true', 'bottom_shaft': 'false'},
                          'rpm': 0.0}, rotated
    def set_sneak(down):
        if isinstance(host, Native):
            host.session.call('key', 'shift', 'down' if down else 'up')
        else:
            host.call('input', {'key': 'shift', 'down': down})

    set_sneak(True)
    try:
        click(host, work, f'{material}-{cog}-uncase', pos, 'north', north_feet, north_aim, WRENCH)
    finally:
        set_sneak(False)
    removed = state(host, positions)
    assert removed[0] == {**initial[0], 'properties': {'axis': 'y', 'waterlogged': 'false'},
                          'rpm': 0.0}, removed
    return dict(held_count=consumption, initial=initial, encased=encased, closed=closed,
                reopened=reopened, rotated=rotated, removed=removed)


def scenarios(host, work, report, save):
    host.command(f'forceload add {LOAD}')
    step(host, 20, (2400, 167, 1173))
    host.command(f'fill {REGION} minecraft:air')
    for index, (material, large) in enumerate([('andesite', False), ('brass', False),
                                              ('andesite', True), ('brass', True)]):
        key = material + ('_large' if large else '_small')
        report['cases'][key] = scenario(host, work, material, large, 1173 + index * 7)
        save()
    support = (2404, 167, 1197)
    placement = (2404, 167, 1196)
    put(host.command, support, 'create:cogwheel[axis=x]')
    host.command('fill 2403 166 1194 2405 166 1198 minecraft:smooth_stone')
    faces = (support, 'north', (2404.5, 167, 1195.0), (2404.5, 167.55, 1197.5))
    for size, count in [('large_cogwheel', 3), ('cogwheel', 2)]:
        item = f'create:andesite_encased_{size}'
        click(host, work, f'place-{size}', *faces, f'{item} 3')
        selected = text(host, 'data get entity @s SelectedItem')
        assert item in selected and int(number({'nbt': selected}, 'count')) == count, selected
        [placed] = state(host, [placement])
        expected = (dict(id=item, properties={'axis': 'x', 'top_shaft': 'false', 'bottom_shaft': 'false'},
                         entity=['create:encased_cogwheel'], rpm=0.0)
                    if size == 'cogwheel' else dict(id='minecraft:air', properties={}, entity=[], rpm=0.0))
        assert placed == expected, placed
        report['cases'][f'place_{size}'] = dict(state=placed, held_count=count)
        save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    session = None
    if args.java:
        pinned = json.loads((reference_java.BASE / 'manifest.json').read_text())
        assert pinned['create_sha256'] == reference_java.CREATE_SHA256
        work = Path(tempfile.mkdtemp(prefix='encased-cog-java-', dir=ROOT / '.local'))
        host = Original()
        previous = host.call('state', {})
        assert previous['ready'] and previous['data_version'] == 3955, previous
        host.call('tick', {'frozen': True})
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon check requires --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['create'] == PINS['create_revision'] and reference['passed']
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='encased-cog-native', world='CreateEncasedCog')
        work, host = session.scratch, Native(session)
    path = work / 'result.json'
    report = dict(passed=False, create=PINS['create_revision'], cases={})

    def save():
        path.write_text(json.dumps(report, indent=2) + '\n')
        if args.java:
            (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')

    print(path, flush=True)
    try:
        if session:
            session.start()
            host.command('tp @s 2400.5 169 1173.5')
            wait_loaded(session.call, [(2400, 167, 1173)])
            host.command('tick freeze')
        scenarios(host, work, report, save)
        if session:
            assert report['cases'] == reference['cases'], (report, reference)
        report['passed'] = True
    finally:
        if session:
            try:
                session.stop()
            finally:
                session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        else:
            host.command('gamemode creative')
            host.command('item replace entity @s weapon.mainhand with minecraft:air')
            host.command(f'fill {REGION} minecraft:air')
            host.command(f'forceload remove {LOAD}')
            host.call('camera', {'position': previous['position'], 'yaw': previous['yaw'], 'pitch': previous['pitch']})
            host.call('tick', {'frozen': previous['server']['frozen']})
        save()


if __name__ == '__main__':
    main()
