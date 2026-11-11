#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare clutch and gearshift transitions across two loaded chunk columns.

Redstone transitions and shaft cuts are sampled before and after normal ticks.
The native replay includes a process restart.
"""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession
from reference_java import BASE, CREATE_SHA256


BOUNDARY = 928
CENTER = (BOUNDARY, 80, 552)
COLUMNS = [(BOUNDARY - 1, 80, CENTER[2]), CENTER]
FORCE_RANGE = '912 544 943 559'
SHAFT = 'create:shaft[axis=x]'
AIR = 'minecraft:air'


def rigs():
    for lane, (kind, sign) in enumerate((
        ('clutch', 1), ('clutch', -1), ('gearshift', 1), ('gearshift', -1),
    )):
        x = BOUNDARY - (sign > 0)
        y, z = CENTER[1], 546 + 4 * lane
        facing = 'east' if sign > 0 else 'west'
        motor = (x - 3 * sign, y, z)
        relay = (x, y, z)
        shafts = [(x + offset * sign, y, z) for offset in (-2, -1, 1, 2)]
        assert len({(p[0] >> 4, p[2] >> 4) for p in [motor, relay, *shafts]}) == 2
        assert relay[0] >> 4 != shafts[2][0] >> 4
        yield kind, facing, motor, relay, shafts


def prepare(command, tick):
    command(f'forceload add {FORCE_RANGE}')
    tick(40)
    command('fill 924 80 545 932 84 559 minecraft:air')
    command('fill 924 79 545 932 79 559 minecraft:smooth_stone')


def transitions(put, tick, sample):
    for kind, facing, motor, relay, shafts in rigs():
        put(relay, f'create:{kind}[axis=x]')
        for shaft in shafts:
            put(shaft, SHAFT)
        put(motor, f'create:creative_motor[facing={facing}]{{ScrollValue:32}}')
        tick(20)
        sample(kind, facing, 'initial', relay, shafts)
        control = (relay[0], relay[1] + 1, relay[2])
        for phase, state in [('on', 'minecraft:redstone_block'), ('off', AIR)]:
            put(control, state)
            sample(kind, facing, f'{phase}:0', relay, shafts)
            for age in range(1, 4):
                tick(1)
                sample(kind, facing, f'{phase}:{age}', relay, shafts)
        put(control, 'minecraft:redstone_block')
        put(control, AIR)
        sample(kind, facing, 'pulse:0', relay, shafts)
        tick(1)
        sample(kind, facing, 'pulse:1', relay, shafts)
        bridge = shafts[2]
        remaining = [shaft for shaft in shafts if shaft != bridge]
        put(bridge, AIR)
        sample(kind, facing, 'cut:0', relay, remaining)
        tick(1)
        sample(kind, facing, 'cut:1', relay, remaining)
        put(bridge, SHAFT)
        sample(kind, facing, 'repair:0', relay, shafts)
        tick(1)
        sample(kind, facing, 'repair:1', relay, shafts)
        put(control, 'minecraft:redstone_block')
        tick(4)
        sample(kind, facing, 'settled_powered', relay, shafts)


def run_java(work):
    host = Original()
    manifest = json.loads((BASE / 'manifest.json').read_text())
    assert manifest['create_sha256'] == CREATE_SHA256
    assert host.call('state', {})['data_version'] == 3955
    host.call('tick', {'frozen': True})
    rows = []

    def tick(n):
        host.call('observe_ticks', {'ticks': n, 'positions': COLUMNS})

    def sample(kind, facing, phase, relay, shafts):
        state = host.call('block', {'pos': relay})
        rows.append(dict(kind=kind, facing=facing, phase=phase,
                         powered=state['properties']['powered'] == 'true',
                         rpm=[number(host.call('block', {'pos': pos}), 'Speed') for pos in shafts]))

    try:
        host.command('gamemode creative')
        host.command(f'tp @s {CENTER[0]}.5 81 {CENTER[2]}.5')
        prepare(host.command, tick)
        transitions(lambda pos, state: host.command(f'setblock {xyz(pos)} {state}'), tick, sample)
    finally:
        host.command(f'forceload remove {FORCE_RANGE}')
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
    return rows


def run_native(session, *, restart=False):
    batch = Batch()
    batch.load(CENTER)
    for pos in COLUMNS:
        batch.command(f'execute if loaded {xyz(pos)} run say create_column_loaded', True)
    pending = []

    def sample(kind, facing, phase, relay, shafts):
        batch.command(f'execute if block {xyz(relay)} create:{kind}[powered=true] run say create_relay_powered', True)
        for pos in shafts:
            batch.data(pos)
        pending.append((kind, facing, phase, len(shafts)))

    if restart:
        batch.tick(20)
        for kind, facing, _, relay, shafts in rigs():
            sample(kind, facing, 'settled_powered', relay, shafts)
    else:
        prepare(batch.command, batch.tick)
        transitions(batch.put, batch.tick, sample)
    label = 'after-restart' if restart else 'before-restart'
    observations = batch.run(session, label)
    loaded = observations[:len(COLUMNS)]
    samples = iter(observations[len(COLUMNS):])
    assert len(loaded) == len(COLUMNS) and all('create_column_loaded' in row for row in loaded), loaded
    rows = []
    for kind, facing, phase, count in pending:
        powered = 'create_relay_powered' in next(samples)
        tags = [next(samples) for _ in range(count)]
        assert all('create:simple_kinetic' in tag for tag in tags), (kind, facing, phase, tags)
        # A freshly placed native shaft has no Speed field before its first turn.
        rpm = [number({'nbt': tag}, 'Speed', 0 if phase == 'repair:0' else None)
               for tag in tags]
        rows.append(dict(kind=kind, facing=facing, phase=phase, powered=powered, rpm=rpm))
    assert next(samples, None) is None
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'reference', 'build-result'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    report = dict(passed=False, create=PINS['create_revision'],
                  fixture_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='cross-chunk-kinetics-java-', dir=ROOT / '.local'))
        report['rows'] = run_java(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference, args.build_result)):
            parser.error('Native checks need --game, --resources, --ctl, --reference and --build-result')
        build = json.loads(args.build_result.read_text())
        assert build['passed'] and Path(build['game']).resolve() == args.game.resolve()
        with args.game.open('rb') as game:
            assert hashlib.file_digest(game, 'sha256').hexdigest() == build['game_sha256']
        report['horizon'] = build['horizon']
        report['game_sha256'] = build['game_sha256']
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and report['create'] == reference['create']
        assert report['fixture_sha256'] == reference['fixture_sha256']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='cross-chunk-kinetics-native', graphics=False,
                                     world='CreateCrossChunkKinetics')
        work = session.scratch
        try:
            report['rows'] = run_native(session)
            report['restarted'] = run_native(session, restart=True)
        finally:
            session.control_temp.cleanup()
        expected_restarts = [row for row in reference['rows'] if row['phase'] == 'settled_powered']
        report['mismatches'] = [
            dict(native=got, java=expected)
            for got, expected in zip(report['rows'] + report['restarted'],
                                     reference['rows'] + expected_restarts, strict=True)
            if got != expected
        ]
    report['passed'] = not report.get('mismatches')
    path = work / 'result.json'
    path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(result=str(path), samples=len(report['rows']),
                          restart_samples=len(report.get('restarted', [])),
                          mismatches=len(report.get('mismatches', [])))), flush=True)
    assert report['passed'], report['mismatches']


if __name__ == '__main__':
    main()
