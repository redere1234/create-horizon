#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare an upright Mechanical Bearing across two loaded columns.

Collect the original with --java, then pass its result.json to --reference.
The default check covers rotation, support and landing. --require-item-carry
also requires the tracked item's horizontal path to match the original.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import time

from bearing_native_checks import Batch
from burner_heat_java_checks import field, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession


PIVOT = (1304, 100, 600)
ANCHOR = (1304, 101, 600)
MOTOR = (1304, 99, 600)
OWNER_EDGE = 1312
NEIGHBOR = (OWNER_EDGE + 2, 101, 600)
FORCE = '1296 592 1327 607'
AIR = 'minecraft:air'
SLIME = 'minecraft:slime_block'
TIP = 'minecraft:stone'
CONTACT = (1314.35, 102.45, 600.5)
CONTROL = (1314.35, 102.45, 602.5)
TOP = 102.0
TOP_TOLERANCE = 0.000101  # Includes Create's vertical collision separation.
POSITION_TOLERANCE = 1e-6
SAMPLES = 8
LOCALS = [(x, 0) for x in range(8)] + [(7, z) for z in range(1, 8)]
TAG = 'create_bearing_sweep_'


def layout(turn):
    blocks = {}
    for index, (x, z) in enumerate(LOCALS):
        for _ in range(turn):
            x, z = z, -x
        position = (ANCHOR[0] + x, ANCHOR[1], ANCHOR[2] + z)
        assert (position[0] >> 4, position[2] >> 4) == (ANCHOR[0] >> 4, ANCHOR[2] >> 4)
        blocks[position] = TIP if index == len(LOCALS) - 1 else SLIME
    return blocks


def put(command, pos, block):
    command(f'setblock {xyz(pos)} {block}')


def item_selector(label):
    return f'@e[type=minecraft:item,tag={TAG}{label},limit=1]'


def setup(command):
    command('fill 1296 96 592 1320 108 607 minecraft:air')
    command('fill 1296 95 592 1320 95 607 minecraft:stone')
    for label in ('contact', 'control'):
        command(f'kill {item_selector(label)}')
    put(command, PIVOT, 'create:mechanical_bearing[facing=up]')
    for pos, block in layout(0).items():
        put(command, pos, block)
    put(command, MOTOR, 'create:creative_motor[facing=up]{ScrollValue:1}')


def summon_items(command):
    for label, pos in [('contact', CONTACT), ('control', CONTROL)]:
        command(f'summon minecraft:item {xyz(pos)} '
                f'{{Tags:["{TAG}{label}"],PickupDelay:32767,Motion:[0d,-0.18d,0d],'
                'Item:{id:"minecraft:stick",count:1}}')


def controller(block):
    return dict(angle=number(block, 'Angle', 0), running=int(number(block, 'Running', 0)))


def java_sweep(work):
    host = Original()
    state = host.call('state', {})
    if state.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        state = host.call('state', {})
    assert state['ready'] and state['data_version'] == 3955, state
    host.call('tick', {'frozen': True})
    host.command('gamemode creative')
    host.command('tp @s 1306.5 104 600.5')
    host.command(f'forceload add {FORCE}')

    def block(pos):
        return host.call('block', {'pos': pos})

    def tick(count):
        host.call('observe_ticks', {'ticks': count, 'positions': [PIVOT, NEIGHBOR]})

    def snapshot():
        sample = controller(block(PIVOT))
        rows = host.call('entities', {'center': CONTACT, 'radius': 12})['entities']
        for label in ('contact', 'control'):
            entities = [row for row in rows if row['type'] == 'minecraft:item'
                        and TAG + label in row['nbt']]
            assert len(entities) == 1, (label, rows)
            sample[label] = entities[0]['position']
        return sample

    try:
        for _ in range(50):
            if all(any('Test passed' in line for line in host.command(
                    f'execute if loaded {xyz(pos)}')['messages'])
                    for pos in (PIVOT, NEIGHBOR)):
                break
            time.sleep(.1)
        else:
            raise AssertionError('Java fixture columns never loaded')
        setup(host.command)
        tick(151)
        flying = all(block(pos)['id'] == AIR for pos in (*layout(0), NEIGHBOR))
        summon_items(host.command)
        samples = [snapshot()]
        for _ in range(SAMPLES):
            tick(1)
            samples.append(snapshot())
        put(host.command, MOTOR, AIR)
        tick(2)
        landed = all(block(pos)['id'] == block_id for pos, block_id in layout(1).items())
        return dict(flying=flying, samples=samples, landed=landed, stopped=controller(block(PIVOT)))
    finally:
        for label in ('contact', 'control'):
            host.command(f'kill {item_selector(label)}')
        host.command(f'forceload remove {FORCE}')
        host.call('tick', {'frozen': state['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def position(nbt):
    return [float(value.strip().rstrip('dDfF')) for value in field(nbt, 'Pos')[1:-1].split(',')]


def native_sweep(session):
    batch = Batch()
    batch.load((1306, 103, 600))
    batch.command(f'forceload add {FORCE}')
    batch.tick(20)
    for pos in (PIVOT, NEIGHBOR):
        batch.command(f'execute if loaded {xyz(pos)} run say sweep_loaded', True)
    setup(batch.command)
    batch.tick(151)
    flying = [*layout(0), NEIGHBOR]
    for pos in flying:
        batch.expect(pos, AIR)
    summon_items(batch.command)
    for index in range(SAMPLES + 1):
        if index:
            batch.tick()
        batch.data(PIVOT)
        for label in ('contact', 'control'):
            batch.command(f'data get entity {item_selector(label)}', True)
    batch.put(MOTOR, AIR)
    batch.tick(2)
    batch.data(PIVOT)
    landing = layout(1)
    for pos, block in landing.items():
        batch.expect(pos, block)
    rows = iter(batch.run(session, 'sweep'))
    loaded = [next(rows), next(rows)]
    assert all('sweep_loaded' in row for row in loaded), loaded
    flying_checks = [next(rows) for _ in flying]
    samples = [
        dict(**controller({'nbt': next(rows)}), contact=position(next(rows)), control=position(next(rows)))
        for _ in range(SAMPLES + 1)
    ]
    stopped = controller({'nbt': next(rows)})
    landing_checks = list(rows)
    assert len(landing_checks) == len(landing), landing_checks
    return dict(flying=all('bearing_check' in row for row in flying_checks), samples=samples,
                landed=all('bearing_check' in row for row in landing_checks), stopped=stopped)


def supported(samples, label):
    return [abs(sample[label][1] - TOP) <= TOP_TOLERANCE for sample in samples]


def validate(result):
    samples = result['samples']
    assert result['flying'] and result['landed'] and result['stopped']['running'] == 0, result
    assert all(sample['running'] == 1 for sample in samples), samples
    assert 44.5 <= samples[0]['angle'] <= 45.5, samples
    assert all(p[0] >= OWNER_EDGE for sample in samples for p in [sample['contact'], sample['control']]), samples
    for label, start in [('contact', CONTACT), ('control', CONTROL)]:
        assert all(abs(a - b) < POSITION_TOLERANCE for a, b in zip(samples[0][label], start)), samples
    assert supported(samples, 'contact') == [False, False] + [True] * (SAMPLES - 1), samples
    assert not any(supported(samples, 'control')), samples


def compare(actual, expected):
    samples = actual['samples']
    original = expected['samples']
    pairs = list(zip(samples, original, strict=True))
    assert all(abs(a['angle'] - b['angle']) < 1e-5 for a, b in pairs), pairs
    for a, b in pairs:
        assert all(abs(x - y) < POSITION_TOLERANCE for x, y in zip(a['control'], b['control'])), (a, b)
        assert abs(a['contact'][1] - b['contact'][1]) <= TOP_TOLERANCE, (a, b)

    differences = [
        [actual['contact'][axis] - expected['contact'][axis] for axis in (0, 2)]
        for actual, expected in pairs
    ]
    mismatches = [tick for tick, difference in enumerate(differences)
                  if any(abs(axis) > POSITION_TOLERANCE for axis in difference)]
    return dict(item_carry_matches=not mismatches, first_item_carry_mismatch=mismatches[0] if mismatches else None,
                item_horizontal_delta_xz=differences)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--require-item-carry', action='store_true')
    for name in ('game', 'resources', 'ctl', 'reference', 'build-result'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    report = dict(passed=False, create=PINS['create_revision'],
                  fixture_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    session = None
    expected = None
    if args.java:
        if args.require_item_carry:
            parser.error('--require-item-carry requires a native run')
        work = Path(tempfile.mkdtemp(prefix='bearing-chunk-sweep-java-', dir=ROOT / '.local'))
    else:
        if not all((args.game, args.resources, args.ctl, args.reference, args.build_result)):
            parser.error('Native checks need --game, --resources, --ctl, --reference and --build-result')
        expected = json.loads(args.reference.read_text())
        assert expected['passed'] and expected['create'] == report['create'], expected
        assert expected['fixture_sha256'] == report['fixture_sha256'], 'Regenerate --reference with this fixture version'
        receipt = json.loads(args.build_result.read_text())
        digest = hashlib.sha256()
        with args.game.open('rb') as game:
            for chunk in iter(lambda: game.read(1024 * 1024), b''):
                digest.update(chunk)
        assert receipt['passed'] and digest.hexdigest() == receipt['game_sha256'], receipt
        report.update(horizon=receipt['horizon'], game_sha256=receipt['game_sha256'],
                      java_reference=str(args.reference.resolve()))
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='bearing-chunk-sweep-native', graphics=False,
                                     world='CreateBearingChunkSweep')
        work = session.scratch
    print(work, flush=True)
    for turn in range(4):
        layout(turn)
    try:
        report['case'] = java_sweep(work) if args.java else native_sweep(session)
        validate(report['case'])
        if expected:
            report['comparison'] = compare(report['case'], expected['case'])
            if args.require_item_carry:
                assert report['comparison']['item_carry_matches'], report['comparison']
        else:
            samples = report['case']['samples']
            assert abs(samples[-1]['contact'][2] - samples[0]['contact'][2]) > 0.25, samples
        report['passed'] = True
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        if session:
            session.control_temp.cleanup()
            shutil.rmtree(session.resources)
    print(json.dumps(dict(result=str(work / 'result.json'), samples=SAMPLES + 1,
                          comparison=report.get('comparison'))), flush=True)


if __name__ == '__main__':
    main()
