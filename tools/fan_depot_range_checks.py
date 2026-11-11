#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare an upward fan directly below wet and dry depots in both games."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import items, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession
from reference_java import BASE, CREATE_SHA256


CENTER = (952, 80, 568)
FORCE = '944 560 959 575'
DEPOTS = {'wet': CENTER, 'dry': (CENTER[0] + 4, *CENTER[1:])}
STOCK = '{HeldItem:{Item:{id:"create:wheat_flour",count:1},Pos:0.5f,PrevPos:0.5f,Angle:180,InDirection:1}}'


def below(pos, distance=1):
    x, y, z = pos
    return x, y - distance, z


def scenario(command, tick, sample):
    command(f'forceload add {FORCE}')
    tick(40)
    command('fill 950 77 566 958 82 570 minecraft:air')
    for name, pos in DEPOTS.items():
        x, y, z = pos
        for dx, dz in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            command(f'fill {x + dx} {y - 1} {z + dz} {x + dx} {y} {z + dz} minecraft:glass')
        wet = str(name == 'wet').lower()
        command(f'setblock {xyz(pos)} create:depot[waterlogged={wet}]')
        command(f'setblock {xyz(below(pos))} create:encased_fan[facing=up]')
        command(f'setblock {xyz(below(pos, 2))} create:creative_motor[facing=up]{{ScrollValue:256}}')
    tick(40)
    for pos in DEPOTS.values():
        command(f'data merge block {xyz(pos)} {STOCK}')
    previous = 0
    for age in [0, 1, 151, 152, 153, 165]:
        if age > previous:
            tick(age - previous)
        previous = age
        for name, pos in DEPOTS.items():
            sample(age, name, pos)


def row(age, name, fan, depot):
    assert 'create:depot' in depot and 'HeldItem:' in depot, depot
    medium = re.search(r'\bFanProcessingType:\s*"([^"]+)"', depot)
    timer = number({'nbt': depot}, 'FanProcessingTime', -2)
    return dict(age=age, station=name, rpm=number({'nbt': fan}, 'Speed'),
                held=items(depot, 'HeldItem'), medium=medium[1] if medium else None,
                timer=None if timer == -2 else timer)


def run_java(work):
    host = Original()
    manifest = json.loads((BASE / 'manifest.json').read_text())
    assert manifest['create_sha256'] == CREATE_SHA256
    assert host.call('state', {})['data_version'] == 3955
    host.call('tick', {'frozen': True})
    rows = []

    def tick(n):
        host.call('observe_ticks', {'ticks': n, 'positions': list(DEPOTS.values())})

    def sample(age, name, pos):
        rows.append(row(age, name, host.call('block', {'pos': below(pos)})['nbt'],
                        host.call('block', {'pos': pos})['nbt']))

    try:
        host.command(f'tp @s {CENTER[0]}.5 {CENTER[1] + 1} {CENTER[2]}.5')
        scenario(host.command, tick, sample)
    finally:
        host.command(f'forceload remove {FORCE}')
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
    return rows


def run_native(session):
    batch = Batch()
    batch.load(CENTER)
    pending = []

    def sample(age, name, pos):
        pending.append((age, name))
        batch.data(below(pos))
        batch.data(pos)

    scenario(batch.command, batch.tick, sample)
    observations = iter(batch.run(session, 'short-range-depots'))
    rows = [row(age, name, next(observations), next(observations)) for age, name in pending]
    assert next(observations, None) is None
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'reference', 'build-result'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    report = dict(create=PINS['create_revision'],
                  fixture_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='fan-depot-range-java-', dir=ROOT / '.local'))
        report['rows'] = run_java(work)
        assert report['rows'][-2]['held'] == {'create:dough': 1}, report['rows']
        assert report['rows'][-1]['held'] == {'create:wheat_flour': 1}, report['rows']
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
                                     name='fan-depot-range-native', graphics=False,
                                     world='CreateFanDepotRange')
        work = session.scratch
        try:
            report['rows'] = run_native(session)
        finally:
            session.control_temp.cleanup()
        report['mismatches'] = [dict(native=got, java=expected)
                                for got, expected in zip(report['rows'], reference['rows'], strict=True)
                                if got != expected]
    report['passed'] = not report.get('mismatches')
    path = work / 'result.json'
    path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(result=str(path), samples=len(report['rows']),
                          mismatches=len(report.get('mismatches', [])))), flush=True)
    assert report['passed'], report['mismatches']


if __name__ == '__main__':
    main()
