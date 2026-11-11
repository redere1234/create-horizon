#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare dry slab capture, moving support and landed states in real clients.

Collect the original with --java and pass its result.json to --reference.
The native check also verifies landing after a cold restart and wet refusal.
Use --require-contact-timing to require the full item height trace to match.
"""

import argparse
import errno
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile
import time

from bearing_chunk_sweep_checks import controller, position, put
from bearing_native_checks import Batch
from bearing_reference_checks import offset
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession


FORCE = '1344 592 1407 607'
AIR = 'minecraft:air'
SLIME = 'minecraft:slime_block'
STATES = [('oak_slab', 'bottom'), ('smooth_stone_slab', 'top'), ('oak_slab', 'double')]
UP = (0, 1, 0)
EAST = (1, 0, 0)
NORTH = (0, 0, -1)
SOUTH = (0, 0, 1)
WEST = (-1, 0, 0)
DROP_TICK = 151
HALF_TURN_TICKS = 76
FRAMES = 12
HEIGHT_TOLERANCE = .000101  # Includes Java's contact separation offset.
WET_PIVOT = (1400, 100, 600)
WET = 'minecraft:oak_slab[type=bottom,waterlogged=true]'


class Rig:
    def __init__(self, x, facing, axis, arms):
        self.pivot = (x, 100, 600)
        self.motor = offset(self.pivot, axis, -1)
        self.anchor = offset(self.pivot, axis)
        self.facing = facing
        self.arms = arms

    def layout(self, landed=False):
        result = {self.anchor: SLIME}
        for side, (name, half) in zip(self.arms, STATES, strict=True):
            if landed and self.facing == 'up':
                side = (side[2], 0, -side[0])
            elif landed:
                side = tuple(-v for v in side)
                half = {'top': 'bottom', 'bottom': 'top', 'double': 'double'}[half]
            result[offset(self.anchor, side)] = SLIME
            result[offset(self.anchor, side, 2)] = f'minecraft:{name}[type={half},waterlogged=false]'
        return result

    def set_power(self, command, powered):
        rpm = 1 if self.facing == 'up' else 8
        motor = f'create:creative_motor[facing={self.facing}]{{ScrollValue:{rpm}}}' if powered else AIR
        put(command, self.motor, motor)


RIGS = [Rig(1352, 'up', UP, (EAST, NORTH, WEST)), Rig(1368, 'east', EAST, (SOUTH, UP, NORTH)),
        Rig(1384, 'south', SOUTH, (EAST, UP, WEST))]
AX, AY, AZ = RIGS[0].anchor
DROP_POS = {
    'bottom': (AX + .5 + math.sqrt(2), AY + 1.45, AZ + .5 - math.sqrt(2)),
    'top': (AX + .5 - math.sqrt(2), AY + 1.45, AZ + .5 - math.sqrt(2)),
    'control': (AX + 4.5, AY + 1.45, AZ + .5),
}


def selector(label):
    return f'@e[type=minecraft:item,tag=create_slab_{label},limit=1]'


def build(command):
    command('fill 1347 96 596 1404 108 604 minecraft:air')
    command('fill 1347 95 596 1404 95 604 minecraft:stone')
    for label in DROP_POS:
        command(f'kill {selector(label)}')
    for rig in RIGS:
        put(command, rig.pivot, f'create:mechanical_bearing[facing={rig.facing}]')
        for pos, state in rig.layout().items():
            put(command, pos, state)


def start(command, tick):
    RIGS[0].set_power(command, True)
    # Start the faster horizontal rotors late so all three fixtures can be
    # frozen in the same running world before the native process exits.
    delay = DROP_TICK + FRAMES - HALF_TURN_TICKS
    tick(delay)
    for rig in RIGS[1:]:
        rig.set_power(command, True)
    tick(DROP_TICK - delay)


def drop(command):
    for label, pos in DROP_POS.items():
        command(f'summon minecraft:item {xyz(pos)} '
                f'{{Tags:["create_slab_{label}"],PickupDelay:32767,Motion:[0d,-0.18d,0d],'
                'Item:{id:"minecraft:stick",count:1}}')


def stop(command, tick):
    for rig in RIGS:
        rig.set_power(command, False)
    tick(2)


def java(work):
    host = Original()
    state = host.call('state', {})
    if state.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        state = host.call('state', {})
    assert state['ready'] and state['data_version'] == 3955, state
    host.call('tick', {'frozen': True})
    host.command('gamemode creative')
    host.command('tp @s 1370.5 104 602.5')
    host.command(f'forceload add {FORCE}')

    def block(pos):
        return host.call('block', {'pos': pos})

    def tick(count):
        host.call('observe_ticks', {'ticks': count, 'positions': [rig.pivot for rig in RIGS]})

    def sample():
        entities = host.call('entities', {'center': DROP_POS['control'], 'radius': 12})['entities']
        observed = {}
        for label in DROP_POS:
            rows = [row for row in entities if row['type'] == 'minecraft:item'
                    and f'create_slab_{label}' in row['nbt']]
            assert len(rows) == 1, rows
            observed[label] = rows[0]['position'][1]
        return observed

    try:
        for _ in range(50):
            if all(any('Test passed' in line for line in host.command(
                    f'execute if loaded {xyz(rig.pivot)}')['messages']) for rig in RIGS):
                break
            time.sleep(.1)
        else:
            raise AssertionError('Java fixture columns did not load')
        build(host.command)
        start(host.command, tick)
        for rig in RIGS:
            assert all(block(pos)['id'] == AIR for pos in rig.layout()), rig.facing
        drop(host.command)
        heights = [sample()]
        for _ in range(FRAMES):
            tick(1)
            heights.append(sample())
        angles = [controller(block(rig.pivot)) for rig in RIGS]
        stop(host.command, tick)
        for rig in RIGS:
            assert controller(block(rig.pivot))['running'] == 0, rig.facing
            for pos, wanted in rig.layout(landed=True).items():
                actual = block(pos)
                if '[' in wanted:
                    name, properties = wanted[:-1].split('[')
                    expected = dict(property.split('=') for property in properties.split(','))
                    assert actual['id'] == name and actual['properties'] == expected, (pos, actual, wanted)
                else:
                    assert actual['id'] == wanted, (pos, actual, wanted)
        return dict(heights=heights, angles=angles)
    finally:
        for label in DROP_POS:
            host.command(f'kill {selector(label)}')
        host.command(f'forceload remove {FORCE}')
        host.call('tick', {'frozen': state['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session):
    batch = Batch()
    batch.load((1370, 103, 602))
    batch.command(f'forceload add {FORCE}')
    batch.tick(25)
    build(batch.command)
    batch.put(WET_PIVOT, 'create:mechanical_bearing[facing=up]')
    batch.put(offset(WET_PIVOT, UP), WET)
    batch.put(offset(WET_PIVOT, UP, -1), 'create:creative_motor[facing=up]{ScrollValue:1}')
    start(batch.command, batch.tick)
    positions = [pos for rig in RIGS for pos in rig.layout()]
    for pos in positions:
        batch.expect(pos, AIR)
    batch.data(WET_PIVOT)
    batch.expect(offset(WET_PIVOT, UP), WET)
    drop(batch.command)
    for frame in range(FRAMES + 1):
        if frame:
            batch.tick()
        for label in DROP_POS:
            batch.command(f'data get entity {selector(label)}', True)
    for rig in RIGS:
        batch.data(rig.pivot)
    rows = iter(batch.run(session, 'slabs-before-restart'))
    assert all('bearing_check' in next(rows) for _ in positions), positions
    assert controller({'nbt': next(rows)})['running'] == 0
    assert 'bearing_check' in next(rows)
    heights = [{label: position(next(rows))[1] for label in DROP_POS} for _ in range(FRAMES + 1)]
    angles = [controller({'nbt': next(rows)}) for _ in RIGS]
    assert next(rows, None) is None

    restart = Batch()
    restart.load((1370, 103, 602))
    for rig in RIGS:
        restart.data(rig.pivot)
    for pos in positions:
        restart.expect(pos, AIR)
    stop(restart.command, restart.tick)
    targets = []
    for rig in RIGS:
        restart.data(rig.pivot)
        for pos, block in rig.layout(landed=True).items():
            restart.expect(pos, block)
            targets.append(pos)
    resumed = iter(restart.run(session, 'slabs-after-restart'))
    restarted = [controller({'nbt': next(resumed)}) for _ in RIGS]
    assert all('bearing_check' in next(resumed) for _ in positions), positions
    for rig in RIGS:
        assert controller({'nbt': next(resumed)})['running'] == 0, rig.facing
        assert all('bearing_check' in next(resumed) for _ in rig.layout()), rig.facing
    assert next(resumed, None) is None
    return dict(heights=heights, angles=angles, restarted=restarted, landed=targets,
                refused_waterlogged=True)


def validate(case):
    for label, expected in [('bottom', AY + .5), ('top', AY + 1)]:
        assert abs(case['heights'][-1][label] - expected) < HEIGHT_TOLERANCE, case
    assert case['heights'][-1]['control'] < AY + .5, case
    assert all(snapshot['running'] == 1 for snapshot in case['angles']), case
    vertical_angle = (DROP_TICK + FRAMES - 1) * .3
    for snapshot, target in zip(case['angles'], (vertical_angle, 180, 180), strict=True):
        assert abs(snapshot['angle'] - target) < .001, case


def compare(actual, original):
    assert actual['angles'] == original['angles'], (actual, original)
    assert all(snapshot['running'] == 1 for snapshot in actual['restarted']), actual
    frames = list(zip(actual['heights'], original['heights'], strict=True))
    assert all(a['control'] == b['control'] for a, b in frames), frames
    assert all(abs(a['top'] - b['top']) < HEIGHT_TOLERANCE for a, b in frames), frames
    bottom_deltas = [a['bottom'] - b['bottom'] for a, b in frames]
    assert abs(bottom_deltas[-1]) < HEIGHT_TOLERANCE, frames
    different = [tick for tick, delta in enumerate(bottom_deltas) if abs(delta) >= HEIGHT_TOLERANCE]
    first_support = {
        engine: next(tick for tick, frame in enumerate(case['heights'])
                     if abs(frame['bottom'] - (AY + .5)) < HEIGHT_TOLERANCE)
        for engine, case in [('horizon', actual), ('java', original)]
    }
    return dict(contact_timing_matches=not different, bottom_different_frames=different,
                bottom_height_deltas=bottom_deltas, bottom_first_support=first_support)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--require-contact-timing', action='store_true')
    for arg in ('game', 'resources', 'ctl', 'reference', 'build-result'):
        parser.add_argument('--' + arg, type=Path)
    args = parser.parse_args()
    report = dict(passed=False, create=PINS['create_revision'],
                  fixture_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    session = expected = None
    if args.java:
        if args.require_contact_timing:
            parser.error('--require-contact-timing requires a native run')
        work = Path(tempfile.mkdtemp(prefix='bearing-slabs-java-', dir=ROOT / '.local'))
    else:
        if not all((args.game, args.resources, args.ctl, args.reference, args.build_result)):
            parser.error('Native checks need --game, --resources, --ctl, --reference and --build-result')
        expected = json.loads(args.reference.read_text())
        assert expected['passed'] and expected['create'] == report['create'], expected
        assert expected['fixture_sha256'] == report['fixture_sha256'], 'Regenerate --reference with this fixture version'
        receipt = json.loads(args.build_result.read_text())
        digest = hashlib.sha256()
        with args.game.open('rb') as binary:
            for chunk in iter(lambda: binary.read(1024 * 1024), b''):
                digest.update(chunk)
        game_hash = digest.hexdigest()
        assert receipt['passed'] and receipt['game_sha256'] == game_hash, receipt
        report.update(horizon=receipt['horizon'], game_sha256=game_hash,
                      java_reference=str(args.reference.resolve()))
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='bearing-slabs-native', graphics=False, world='CreateBearingSlabs')
        work = session.scratch
    print(work, flush=True)
    try:
        case = report['case'] = native(session) if session else java(work)
        validate(case)
        if expected:
            report['comparison'] = compare(case, expected['case'])
            if args.require_contact_timing:
                assert report['comparison']['contact_timing_matches'], report['comparison']
        report['passed'] = True
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        if session:
            session.control_temp.cleanup()
            try:
                shutil.rmtree(session.resources)
            except OSError as error:
                if error.errno != errno.ENOTEMPTY:
                    raise
                shutil.rmtree(session.resources)
    print(json.dumps(dict(result=str(work / 'result.json'), comparison=report.get('comparison'))), flush=True)


if __name__ == '__main__':
    main()
