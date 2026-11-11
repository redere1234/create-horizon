#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Check slab cargo on regular and sticky pistons against the pinned Java client."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import time

from bearing_chunk_sweep_checks import position, put
from bearing_native_checks import Batch
from bearing_slab_checks import HEIGHT_TOLERANCE
from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from gantry_chassis_checks import observed_java, translate
from native_check_session import NativeCheckSession
from piston_checks import rig


X, Y = 1432, 100
REGULAR_Z, STICKY_Z = 630, 646
CASES = [(z, ('east', (X, Y, z), 0, 1, (0, 0, -1), sticky, False))
         for z, sticky in ((REGULAR_Z, False), (STICKY_Z, True))]
FORCE = '1424 624 1439 655'
AIR = 'minecraft:air'
BOTTOM = 'minecraft:oak_slab[type=bottom,waterlogged=false]'
TOP = 'minecraft:smooth_stone_slab[type=top,waterlogged=false]'
FRAMES = 12
DROP_POS = {
    'bottom': (X + 1.65, Y + 1.45, REGULAR_Z - .5),
    'top': (X + 1.65, Y + 1.45, REGULAR_Z + 1.5),
    'control': (X + 1.65, Y + 1.45, REGULAR_Z + 3.5),
}


def controller(nbt):
    return dict(running=int(number(nbt, 'Running', 0)), offset=number(nbt, 'Offset', 0))


def slab_cells(z):
    return {(X + 1, Y, z - 1): BOTTOM, (X + 1, Y, z + 1): TOP}


def selectors(label):
    return f'@e[type=minecraft:item,tag=create_piston_slab_{label},limit=1]'


def setup(command):
    command(f'fill 1427 96 627 1438 108 650 {AIR}')
    command('fill 1427 95 627 1438 95 650 minecraft:stone')
    for label in DROP_POS:
        command(f'kill {selectors(label)}')
    for z, case in CASES:
        power, _, _ = rig(case, lambda pos, state: put(command, pos, state), magnitude=8)
        put(command, (X + 1, Y, z), 'minecraft:slime_block')
        for pos, state in slab_cells(z).items():
            put(command, pos, state)
        power(False)


def moving_cells():
    return {pos: AIR for z, _ in CASES for pos in slab_cells(z)}


def final_cells(retracted):
    expected = {}
    for z, case in CASES:
        initial = slab_cells(z)
        extended = translate(initial, 3)
        expected.update(dict.fromkeys(initial | extended, AIR))
        expected.update(initial if retracted and case[5] else extended)
    return expected


def drop(command):
    for label, pos in DROP_POS.items():
        command(f'summon minecraft:item {xyz(pos)} '
                f'{{Tags:["create_piston_slab_{label}"],PickupDelay:32767,Motion:[0d,-0.18d,0d],'
                'Item:{id:"minecraft:stick",count:1}}')


def item(nbt, point):
    return dict(pos=point, grounded=bool(number({'nbt': nbt}, 'OnGround', 0)))


def reverse(command, tick):
    for z, _ in CASES:
        put(command, (X, Y, z - 1), AIR)
    tick(2)
    for z, _ in CASES:
        put(command, (X, Y, z - 1), 'create:creative_motor[facing=south]{ScrollValue:128}')


def java(work):
    host = Original()
    initial = host.call('state', {})
    if initial.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    host.command('gamemode creative')
    host.command(f'tp @s {X}.5 {Y + 5} 637.5')
    host.command(f'forceload add {FORCE}')
    pivots = [case[1] for _, case in CASES]

    def tick(count):
        host.call('observe_ticks', {'ticks': count, 'positions': pivots})

    def drivers():
        return [controller(host.call('block', {'pos': p})) for p in pivots]

    def sample():
        entities = host.call('entities', {'center': DROP_POS['top'], 'radius': 10})['entities']
        result = {}
        for label in DROP_POS:
            [row] = [entity for entity in entities if entity['type'] == 'minecraft:item'
                     and f'create_piston_slab_{label}' in entity['nbt']]
            result[label] = item(row['nbt'], row['position'])
        return result

    try:
        for _ in range(50):
            if all(any('Test passed' in line for line in host.command(
                    f'execute if loaded {xyz(pos)}')['messages']) for pos in pivots):
                break
            time.sleep(.1)
        else:
            raise AssertionError('Java fixture columns did not load')
        setup(host.command)
        observed_java(host, moving_cells(), 20)
        before = drivers()
        drop(host.command)
        samples = [sample()]
        for _ in range(FRAMES):
            tick(1)
            samples.append(sample())
        saved = drivers()
        observed_java(host, final_cells(False), 205)
        reverse(host.command, tick)
        observed_java(host, final_cells(True), 25)
        return dict(before=before, saved=saved, items=samples)
    finally:
        for label in DROP_POS:
            host.command(f'kill {selectors(label)}')
        host.command(f'forceload remove {FORCE}')
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session):
    pivots = [case[1] for _, case in CASES]
    batch = Batch()
    batch.load((X, Y + 4, 637))
    batch.command(f'forceload add {FORCE}')
    batch.tick(20)
    setup(batch.command)
    batch.tick(20)
    for pos in pivots:
        batch.data(pos)
    for pos in moving_cells():
        batch.expect(pos, AIR)
    drop(batch.command)
    for frame in range(FRAMES + 1):
        if frame:
            batch.tick()
        for label in DROP_POS:
            batch.command(f'data get entity {selectors(label)}', True)
    for pos in pivots:
        batch.data(pos)
    rows = iter(batch.run(session, 'slab-piston-before-restart'))
    before = [controller({'nbt': next(rows)}) for _ in pivots]
    assert all('bearing_check' in next(rows) for _ in moving_cells())
    samples = []
    for _ in range(FRAMES + 1):
        observations = {label: next(rows) for label in DROP_POS}
        samples.append({label: item(nbt, position(nbt)) for label, nbt in observations.items()})
    saved = [controller({'nbt': next(rows)}) for _ in pivots]
    assert next(rows, None) is None
    restart = Batch()
    restart.load((X, Y + 4, 637))
    for pos in pivots:
        restart.data(pos)
    for pos in moving_cells():
        restart.expect(pos, AIR)
    restart.tick(205)
    for pos, state in final_cells(False).items():
        restart.expect(pos, state)
    reverse(restart.command, restart.tick)
    restart.tick(25)
    for pos, state in final_cells(True).items():
        restart.expect(pos, state)
    resumed = iter(restart.run(session, 'slab-piston-after-restart'))
    restarted = [controller({'nbt': next(resumed)}) for _ in pivots]
    remaining = list(resumed)
    assert len(remaining) == len(moving_cells()) + len(final_cells(False)) + len(final_cells(True))
    assert all('bearing_check' in row for row in remaining), remaining
    return dict(before=before, saved=saved, restarted=restarted, items=samples)


def verify(case):
    for start, end in zip(case['before'], case['saved'], strict=True):
        assert start['running'] == end['running'] == 1 and 0 < start['offset'] < end['offset'] < 1, case
    final = case['items'][-1]
    for label, height in [('bottom', Y + .5), ('top', Y + 1)]:
        assert final[label]['grounded'] and abs(final[label]['pos'][1] - height) < HEIGHT_TOLERANCE, final
    assert not final['control']['grounded'] and final['control']['pos'][1] < Y + .5, final


def compare(actual, original):
    assert actual['before'] == original['before'] and actual['saved'] == original['saved'], (actual, original)
    assert actual['restarted'] == actual['saved'], actual
    frames = list(zip(actual['items'], original['items'], strict=True))
    assert all(a['control'] == b['control'] for a, b in frames), frames
    return dict(height_different_frames={
        label: [i for i, (a, b) in enumerate(frames)
                if abs(a[label]['pos'][1] - b[label]['pos'][1]) >= HEIGHT_TOLERANCE]
        for label in ('bottom', 'top')},
        final_x_difference={label: frames[-1][0][label]['pos'][0] - frames[-1][1][label]['pos'][0]
                            for label in ('bottom', 'top')})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for key in ('game', 'resources', 'ctl', 'reference', 'build-result'):
        parser.add_argument('--' + key, type=Path)
    args = parser.parse_args()
    report = dict(passed=False, create=PINS['create_revision'],
                  fixture_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    session = expected = None
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='piston-slabs-java-', dir=ROOT / '.local'))
    else:
        if not all((args.game, args.resources, args.ctl, args.reference, args.build_result)):
            parser.error('Native checks need --game, --resources, --ctl, --reference and --build-result')
        expected = json.loads(args.reference.read_text())
        assert expected['passed'] and expected['create'] == report['create'], expected
        assert expected['fixture_sha256'] == report['fixture_sha256'], 'Regenerate --reference with this fixture version'
        receipt = json.loads(args.build_result.read_text())
        with args.game.open('rb') as game:
            digest = hashlib.file_digest(game, 'sha256').hexdigest()
        assert receipt['passed'] and digest == receipt['game_sha256'], receipt
        report.update(horizon=receipt['horizon'], game_sha256=digest,
                      java_reference=str(args.reference.resolve()))
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='piston-slabs-native', graphics=False, world='CreatePistonSlabs')
        work = session.scratch
    print(work, flush=True)
    try:
        case = report['case'] = native(session) if session else java(work)
        verify(case)
        if expected:
            report['comparison'] = compare(case, expected['case'])
        report['passed'] = True
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        if session:
            session.control_temp.cleanup()
            shutil.rmtree(session.resources)
    print(json.dumps(dict(result=str(work / 'result.json'), comparison=report.get('comparison'))), flush=True)


if __name__ == '__main__':
    main()
