#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare when an Encased Fan first finds items and mobs after a change."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import number
from chain_drive_checks import Original
from common import PINS, ROOT
from native_check_session import NativeCheckSession
from reference_java import BASE, CREATE_SHA256


X, Y = 884, 100
LANES = dict(steady=820, neighbor=824, blocked=828, restart=832)
LOAD = '880 816 895 847'
FANS = [(X, Y, z) for z in LANES.values()]
MOTOR = 'create:creative_motor[facing=east]{ScrollValue:256}'
ENTITIES = ('item', 'sheep')


def motion_query(lane, kind):
    return f'data get entity @e[tag=fan_search_{lane}_{kind},limit=1] Motion'


def clear(command):
    command('kill @e[tag=fan_search_probe]')
    command(f'fill {X-1} {Y} 819 {X+9} {Y+2} 833 minecraft:air')


def scenario(command, tick, sample):
    command(f'forceload add {LOAD}')
    tick(40)
    clear(command)
    command(f'fill {X-1} {Y-1} 819 {X+9} {Y-1} 833 minecraft:smooth_stone')
    command(f'setblock {X+1} {Y} {LANES["blocked"]} minecraft:stone')
    for z in LANES.values():
        command(f'setblock {X-1} {Y} {z} {MOTOR}')
        command(f'setblock {X} {Y} {z} create:encased_fan[facing=east]')
    tick(3)

    # Pause one fan for a non-multiple of six. Its entity search should
    # resume from the preceding active tick, regardless of wall-clock ticks.
    restart = LANES['restart']
    command(f'setblock {X-1} {Y} {restart} minecraft:air')
    for age in range(1, 12):
        if age in (1, 11):
            tick(1)
            sample('paused' if age == 1 else 'resumed', age, ('restart',), False)
        else:
            tick(1)
        if age == 10:
            summon(command, 'restart')
            command(f'setblock {X-1} {Y} {restart} {MOTOR}')

    # The other fans have just taken their 14th powered tick. Keep the
    # entities outside the search set until the next ordinary search.
    for lane in ('steady', 'neighbor', 'blocked'):
        summon(command, lane)
    command(f'setblock {X} {Y} {LANES["neighbor"]-1} minecraft:stone')
    command(f'setblock {X+1} {Y} {LANES["blocked"]} minecraft:air')
    for age in range(1, 9):
        tick(1)
        sample('search', age, LANES, True)


def summon(command, lane):
    z = LANES[lane]
    for kind in ENTITIES:
        height = 0.125 if kind == 'item' else 0.625
        extra = ',PickupDelay:32767s,Item:{id:"minecraft:stick",count:1}' if kind == 'item' else ',NoAI:1b'
        command(f'summon minecraft:{kind} {X+3.5} {Y+height} {z+.5} '
                f'{{Tags:["fan_search_probe","fan_search_{lane}_{kind}"],'
                f'NoGravity:1b,Motion:[0d,0d,0d]{extra}}}')


def row(phase, age, lane, fan, motions):
    rpm = number({'nbt': fan}, 'Speed', 0)
    caught = {}
    for kind, motion in zip(ENTITIES, motions, strict=False):
        axis = re.search(r'\[\s*([-+\d.eE]+)[dDfF]?\s*,', motion)
        assert axis, (kind, motion)
        caught[kind] = float(axis[1]) > 0.001
    return dict(phase=phase, age=age, lane=lane, rpm=rpm, caught=caught)


def java_run(work):
    host = Original()
    manifest = json.loads((BASE / 'manifest.json').read_text())
    assert manifest['create_sha256'] == CREATE_SHA256
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    rows = []

    def sample(phase, age, lanes, include_motions):
        for lane in lanes:
            fan = host.call('block', {'pos': (X, Y, LANES[lane])})['nbt']
            motions = [' '.join(host.command(motion_query(lane, kind))['messages'])
                       for kind in ENTITIES] if include_motions else []
            rows.append(row(phase, age, lane, fan, motions))

    try:
        host.command(f'tp @s {X+4}.5 {Y+4} 826.5')
        host.command(f'forceload add {LOAD}')
        host.call('observe_ticks', {'ticks': 40, 'positions': [(X, Y, 826)]})
        scenario(host.command,
                 lambda n: host.call('observe_ticks', {'ticks': n, 'positions': FANS}), sample)
    finally:
        clear(host.command)
        host.command(f'forceload remove {LOAD}')
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
    return rows


def native_run(session):
    batch = Batch()
    batch.load((X + 4, Y + 3, 826))
    pending = []

    def sample(phase, age, lanes, include_motions):
        for lane in lanes:
            pending.append((phase, age, lane, include_motions))
            batch.data((X, Y, LANES[lane]))
            if include_motions:
                for kind in ENTITIES:
                    batch.command(motion_query(lane, kind), True)

    scenario(batch.command, batch.tick, sample)
    observations = iter(batch.run(session, 'fan-search'))
    rows = [row(phase, age, lane, next(observations),
                [next(observations) for _ in ENTITIES] if include_motions else [])
            for phase, age, lane, include_motions in pending]
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
        work = Path(tempfile.mkdtemp(prefix='fan-search-java-', dir=ROOT / '.local'))
        report['rows'] = java_run(work)
        assert report['rows'][0]['rpm'] == 0 and report['rows'][1]['rpm'] == 256
        for lane in LANES:
            for kind in ENTITIES:
                states = [entry['caught'][kind] for entry in report['rows']
                          if entry['lane'] == lane and entry['phase'] == 'search']
                assert states[0] is False and any(states[1:]), (lane, kind, states)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference, args.build_result)):
            parser.error('Native checks need --game, --resources, --ctl, --reference and --build-result')
        build = json.loads(args.build_result.read_text())
        assert build['passed'] and Path(build['game']).resolve() == args.game.resolve()
        with args.game.open('rb') as game:
            assert hashlib.file_digest(game, 'sha256').hexdigest() == build['game_sha256']
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == report['create']
        assert reference['fixture_sha256'] == report['fixture_sha256']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None, name='fan-search-native',
                                     graphics=False, world='CreateFanSearch')
        work = session.scratch
        try:
            report['rows'] = native_run(session)
        finally:
            session.control_temp.cleanup()
            for path in (session.resources, work / '.horizon-cache'):
                shutil.rmtree(path, ignore_errors=True)
        report['horizon'] = build['horizon']
        report['game_sha256'] = build['game_sha256']
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
