#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare live Crusher particle kinds, counts and visibility against Create 6.0.10."""

import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import tempfile

from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from crusher_drop_checks import state as crusher_state
from crushing_wheel_checks import AIR, COBBLE, CONTROLLER, GRAVEL, WHEEL, X, Y, put, wheels
from native_check_session import NativeCheckSession, wait_loaded
from reference_java import BASE, CREATE_SHA256


BLOCK_Z, ITEM_Z, FINISHED_Z, INVALID_Z = 1074, 1078, 1082, 1086
POSITIONS = [(X, Y, z) for z in (BLOCK_Z, ITEM_Z, FINISHED_Z, INVALID_Z)]
LOAD = '2128 1072 2143 1087'
REGION = '2131 166 1072 2137 174 1087'
DROPS = '@e[type=minecraft:item,x=2131,y=166,z=1072,dx=6,dy=8,dz=15]'
CAMERA = (X + 0.5, Y + 2.0, BLOCK_Z + 3.5)
RAW = 'minecraft:raw_iron'
TRACE = 'Create crusher particle: '
CLASSES = {'TerrainParticle': 'block', 'BreakingItemParticle': 'item', 'CritParticle': 'crit'}
VIEWS = {
    'block': (CAMERA, (X + .5, Y + .5, BLOCK_Z + .5)),
    'item': ((X + .5, Y + 2, ITEM_Z + 3.5), (X + .5, Y + .5, ITEM_Z + .5)),
}


def setup(command):
    command(f'fill {REGION} {AIR}')
    command(f'kill {DROPS}')
    command('fill 2131 166 1072 2137 166 1087 minecraft:smooth_stone')
    for z in (BLOCK_Z, ITEM_Z, FINISHED_Z, INVALID_Z):
        for x in (X - 2, X + 2):
            put(command, (x, Y, z), 'minecraft:light[level=15]')
    for z in (BLOCK_Z, ITEM_Z, FINISHED_Z):
        put(command, (X, Y - 1, z), 'create:depot')
        command(f'data merge block {X} {Y - 1} {z} '
                '{HeldItem:{Item:{id:"minecraft:diamond",count:1},Pos:0.5f,PrevPos:0.5f,Angle:180,InDirection:1}}')
        wheels(command, z)
    for x in (X - 1, X + 1):
        put(command, (x, Y, INVALID_Z), WHEEL)
        put(command, (x, Y, INVALID_Z - 1), 'create:creative_motor[facing=south]{ScrollValue:-64}')


def feed(command):
    command(f'data merge block {X} {Y} {FINISHED_Z} {{Inventory:{{Size:32,'
            f'Items:[{{Slot:1b,id:"{GRAVEL}",count:64}}],'
            'ProcessingTime:0f,RecipeTime:0f,AppliedRecipe:1b}}')
    for z, item in ((BLOCK_Z, COBBLE), (ITEM_Z, RAW)):
        command(f'summon minecraft:item {X + .5} {Y + 2.25} {z + .5} '
                f'{{Motion:[0d,0d,0d],PickupDelay:40s,Item:{{id:"{item}",count:16}}}}')


def completed(values):
    for raw, source, result in zip(values, (COBBLE, RAW), (GRAVEL, 'create:crushed_raw_iron'), strict=True):
        state = crusher_state(raw)
        assert state['applied'] and not state['entity'], state
        assert source not in state['items'] and result in state['items'], state


def particle_lane(position):
    x, y, z = position
    if X - 1 <= x <= X + 2 and Y - 1.5 <= y <= Y + 2:
        for lane in (BLOCK_Z, ITEM_Z, FINISHED_Z, INVALID_Z):
            if lane - 1 <= z <= lane + 2:
                return lane
    return None


def summarize_java(report):
    rows = []
    for observation in report:
        particles = []
        for particle in observation['samples']:
            kind = CLASSES.get(particle['class'].rsplit('.', 1)[-1])
            lane = particle_lane(particle['position'])
            if kind is None or lane is None:
                continue
            particles.append(dict(lane=lane, kind=kind, position=particle['position'],
                                  age=particle['fields']['age'], sprite=particle.get('sprite'),
                                  id=particle['instance_id']))
        rows.append(dict(tick=observation['game_time'], particles=particles))
    return rows


def verify_java(rows):
    expected = {
        BLOCK_Z: ('block', 'minecraft:block/cobblestone'),
        ITEM_Z: ('item', 'minecraft:item/raw_iron'),
    }
    counters = {}
    for lane, (kind, sprite) in expected.items():
        particles = [particle for row in rows for particle in row['particles']
                     if particle['lane'] == lane and particle['kind'] == kind]
        assert len({p['id'] for p in particles}) >= 24, (lane, particles)
        assert {p['sprite'] for p in particles} == {sprite}, (lane, particles[:5])
        counts = Counter(sum(p['lane'] == lane and p['kind'] == kind and p['age'] == 0
                             for p in row['particles']) for row in rows)
        assert counts[4] >= 5, (lane, counts)
        for p in particles:
            if p['age'] == 0:
                assert within_cell(p['position'], (X, Y, lane)), p
        counters[str(lane)] = dict(kind=kind, sprite=sprite, zero_age_counts=dict(counts))
    observed = [particle for row in rows for particle in row['particles']]
    assert any(p['kind'] == 'crit' and p['lane'] != INVALID_Z for p in observed)
    assert not any(p['kind'] != 'crit' and p['lane'] == FINISHED_Z for p in observed)
    assert not any(p['lane'] == INVALID_Z and p['age'] == 0
                   and within_cell(p['position'], (X, Y, INVALID_Z)) for p in observed)
    return counters


def java_run(work):
    host = Original()
    assert json.loads((BASE / 'manifest.json').read_text())['create_sha256'] == CREATE_SHA256
    initial = host.call('state', {})
    if initial.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial

    def advance(ticks, positions=POSITIONS):
        return host.call('observe_ticks', {'positions': positions, 'ticks': ticks})['samples']

    try:
        host.call('tick', {'frozen': True})
        host.command('gamemode spectator')
        host.command(f'forceload add {LOAD}')
        advance(40, [list(map(int, initial['position']))])
        host.call('camera', {'position': CAMERA, 'target': VIEWS['block'][1], 'hide_gui': True,
                             'window_size': [1280, 720], 'fov': 70})
        setup(host.command)
        settled = advance(56)[-1]['blocks']
        assert all(block['id'] == CONTROLLER and block['properties']['valid'] == 'true'
                   for block in settled[:3]), settled
        feed(host.command)
        advance(40)
        observations = []
        for _ in range(16):
            advance(8)
            observations.append(host.call('particles', {'limit': 384}))
        frames = {}
        for name, (position, target) in VIEWS.items():
            host.call('camera', {'position': position, 'target': target, 'hide_gui': True})
            advance(6)
            captured = Path(host.call('capture', {'name': f'{work.name}/{name}.png', 'frames': 6})['path'])
            assert captured.stat().st_size > 1024, captured
            frames[name] = str(captured)
        done = advance(205)[-1]['blocks'][:2]
        completed([block['nbt'] for block in done])
        after = summarize_java([host.call('particles', {'limit': 384})])[0]['particles']
        assert not any(p['kind'] in ('block', 'item') for p in after), after
        return summarize_java(observations), frames
    finally:
        host.command(f'fill {REGION} {AIR}')
        host.command(f'kill {DROPS}')
        host.command(f'forceload remove {LOAD}')
        host.command('gamemode creative')
        host.call('camera', {'position': initial['position'], 'yaw': initial['yaw'],
                             'pitch': initial['pitch'], 'hide_gui': False})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    with session:
        call = session.call

        def command(text):
            return call('command', text)

        def camera(position, target):
            command('tp @s ' + xyz(position))
            call('look-at', *target)

        command('gamemode spectator')
        camera(*VIEWS['block'])
        wait_loaded(call, POSITIONS)
        command('tick freeze')
        setup(command)
        command('tick unfreeze')
        call('wait', 65)
        for pos in POSITIONS[:3]:
            block = call('block', *pos)
            assert block['block'] == CONTROLLER and 'valid=true' in block['state'], block
        before = call('status')['particles']
        offset = session.log.stat().st_size
        feed(command)
        call('wait', 145)
        call('key', 'f1', 'tap')
        frames = {}
        for name, (position, target) in VIEWS.items():
            camera(position, target)
            call('wait', 6)
            frame = session.scratch / f'{name}.png'
            call('screenshot', frame)
            assert frame.stat().st_size > 1024, frame
            frames[name] = str(frame)
        end = session.log.stat().st_size
        after = call('status')['particles']
        call('wait', 210)
        completed([' '.join(command('data get block ' + xyz(pos))['chat']) for pos in POSITIONS[:2]])
        late = session.log.stat().st_size
        call('wait', 12)
        late_end = session.log.stat().st_size
    lines = session.log.read_bytes()[offset:end].decode(errors='replace').splitlines()
    rows = [json.loads(line.split(TRACE, 1)[1]) for line in lines if TRACE in line]
    late_rows = session.log.read_bytes()[late:late_end].decode(errors='replace').splitlines()
    assert not any(json.loads(line.split(TRACE, 1)[1])['event'] == 'material'
                   for line in late_rows if TRACE in line), late_rows
    counts = {kind: after.get(kind, 0) - before.get(kind, 0) for kind in ('block', 'item', 'crit')}
    return rows, frames, counts


def within_cell(position, controller):
    # Java adds its random float before widening to double. At large
    # coordinates the largest draws can round to the far edge of the cell.
    return all(cell <= coordinate <= cell + 1
               for cell, coordinate in zip(controller, position, strict=True))


def verify_native(rows, counts, reference):
    materials = [row for row in rows if row['event'] == 'material']
    ambient = [row for row in rows if row['event'] == 'crit']
    expected = {BLOCK_Z: COBBLE, ITEM_Z: RAW}
    assert {row['controller'][2] for row in materials} == expected.keys(), materials[:5]
    assert ambient and all(row['controller'] in [list(pos) for pos in POSITIONS[:3]] for row in ambient)
    assert all(row['accepted'] == 1 and within_cell(row['position'], row['controller'])
               for row in ambient), ambient[:5]
    assert counts['crit'] >= len(ambient), (counts, ambient[:5])
    result = {}
    for lane, item in expected.items():
        java = reference['summary'][str(lane)]
        assert java['zero_age_counts'].get('4', 0) >= 5, java
        lane_rows = [row for row in materials if row['controller'][2] == lane]
        assert len(lane_rows) >= 100, (lane, len(lane_rows))
        assert len({row['game_time'] for row in lane_rows}) == len(lane_rows), (lane, lane_rows[:5])
        sprites = {sprite.removeprefix('minecraft:') for row in lane_rows for sprite in row['sprite']}
        assert sprites == {java['sprite'].removeprefix('minecraft:')}, (lane, sprites)
        for row in lane_rows:
            assert row['kind'] == java['kind'] and row['input'] == item, row
            assert row['velocity'] == [0.0] * 3 and row['accepted'] == 4, row
            assert len(row['positions']) == 4 and all(within_cell(position, row['controller'])
                                                       for position in row['positions']), row
        assert counts[java['kind']] >= len(lane_rows) * 4, (counts, lane_rows[-3:])
        result[str(lane)] = dict(kind=java['kind'], sprite=java['sprite'],
                                 bursts=len(lane_rows), particles=len(lane_rows) * 4)
    result['ambient'] = len(ambient)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='crusher-particles-java-', dir=ROOT / '.local'))
        rows, frames = java_run(work)
        (work / 'observed.json').write_text(json.dumps(rows, indent=2) + '\n')
        summary = verify_java(rows)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon runs require --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert (reference['passed'] and reference['create'] == PINS['create_revision']
                and reference['finished_stops_material'])
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='crusher-particles-native', world='CreateCrusherParticles')
        work = session.scratch
        session.env.pop('CREATE_HORIZON_TRACE', None)
        session.env.pop('CREATE_HORIZON_TRACE_POSES', None)
        try:
            rows, frames, counts = native_run(session)
        finally:
            session.control_temp.cleanup()
            for path in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(path, ignore_errors=True)
        (work / 'observed.json').write_text(json.dumps(dict(rows=rows, counts=counts), indent=2) + '\n')
        summary = verify_native(rows, counts, reference)
    result = work / 'result.json'
    result.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'],
                                      summary=summary, frames=frames, finished_stops_material=True), indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
