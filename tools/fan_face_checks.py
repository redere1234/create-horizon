#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare living-entity effects at Create's dry-to-haunting airflow boundary."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded
import reference_java


X, Y = 262144, 172
LOAD = '262128 1120 262175 1135'
AREA = '262142 170 1122 262150 176 1135'
CASES = (('dry', 1125, 1.875), ('rounded_dry', 1129, 2.0078125), ('haunted', 1133, 2.125))
FANS = [(X, Y, z) for _, z, _ in CASES]
EXPECTED = dict(dry=[False, False], rounded_dry=[False, False], haunted=[True, True])


def selector(name):
    return f'@e[type=minecraft:sheep,tag=fan_face_{name},limit=1]'


def setup(command):
    command(f'fill {AREA} minecraft:air')
    for name, z, dx in CASES:
        command(f'kill {selector(name)}')
        command(f'fill {X-1} {Y-1} {z-1} {X+5} {Y-1} {z+1} minecraft:smooth_stone')
        command(f'setblock {X+2} {Y} {z} minecraft:soul_campfire[lit=true]')
        command(f'setblock {X-1} {Y} {z} create:creative_motor[facing=east]{{ScrollValue:256}}')
        command(f'summon minecraft:sheep {X+dx} {Y+.625} {z+.5} '
                f'{{Tags:["fan_face_{name}"],NoAI:1b,NoGravity:1b,Silent:1b}}')
        command(f'setblock {X} {Y} {z} create:encased_fan[facing=east]')


def sample(fans, entities):
    for raw in fans:
        assert abs(number({'nbt': raw}, 'Speed')) == 256, raw
    out = {}
    for (name, _, _), raw in zip(CASES, entities, strict=True):
        assert 'Health:' in raw and 'Motion:' in raw, raw
        out[name] = [f'minecraft:{effect}' in raw for effect in ('blindness', 'slowness')]
    return out


def java_run(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955
    manifest = json.loads((reference_java.BASE / 'manifest.json').read_text())
    assert manifest['create_sha256'] == reference_java.CREATE_SHA256
    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {LOAD}')
        host.snapshot(FANS, 40)
        setup(host.command)
        fans = [block['nbt'] for block in host.snapshot(FANS, 1)]
        entities = [' '.join(host.command(f'data get entity {selector(name)}')['messages'])
                    for name, _, _ in CASES]
        return sample(fans, entities)
    finally:
        for name, _, _ in CASES:
            host.command(f'kill {selector(name)}')
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {LOAD}')
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    batch = Batch()
    batch.load((X, Y + 4, CASES[1][1]))
    setup(batch.command)
    batch.tick()
    for fan in FANS:
        batch.data(fan)
    for name, _, _ in CASES:
        batch.command(f'data get entity {selector(name)}', True)
    values = batch.run(session, 'fan-face')
    return sample(values[:len(CASES)], values[len(CASES):])


def native_player(session):
    """Check the actual local player during ordinary unfrozen simulation."""
    with session:
        call = session.call

        def command(value):
            return call('command', value)['chat']

        lanes = (('push', 0, 256), ('pull', 4, -256), ('smoking', 8, 256))
        command('tp @s 206.5 173 6.5')
        wait_loaded(call, [(200, 172, z) for _, z, _ in lanes])
        command('fill 197 171 -2 220 176 10 minecraft:air')
        command('fill 197 171 -2 220 171 10 minecraft:smooth_stone')
        command('setblock 201 172 8 minecraft:campfire[lit=true]')
        for _, z, rpm in lanes:
            command(f'setblock 199 172 {z} create:creative_motor[facing=east]{{ScrollValue:{rpm}}}')
            command(f'setblock 200 172 {z} create:encased_fan[facing=east]')
        command('tick unfreeze')
        call('wait', 30)
        command('gamemode survival')
        result = {}
        for name, z, rpm in lanes:
            fan = ' '.join(command(f'data get block 200 172 {z}'))
            assert number({'nbt': fan}, 'Speed') == rpm, fan
            command(f'tp @s 203.5 172 {z+.5}')
            call('wait', 12)
            player = call('status')['player']
            result[name] = dict(dx=player['position'][0] - 203.5, health=player['health'])
        assert result['push']['dx'] > 0.02 and result['pull']['dx'] < -0.02, result
        hits = [hit for player in call('hurtlog')['players'] for hit in player['hurts']
                if hit['source'] == 'create:fan_fire' and hit['hurt']]
        assert hits and hits[0]['taken'] == 2 and result['smoking']['health'] < 20, (hits, result)
        result['first_fan_fire_damage'] = hits[0]['taken']
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--baseline', action='store_true', help='Prove the old native boundary discrepancy')
    parser.add_argument('--player', action='store_true', help='Also check push, pull and smoke in unfrozen Horizon')
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.player and args.java:
        parser.error('--player is a Horizon integration check')
    player = None
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='fan-face-java-', dir=ROOT / '.local'))
        result = java_run(work)
        expected = EXPECTED
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon checks require --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        expected = reference['effects']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None, graphics=args.player,
                                     name='fan-face-native', world='CreateFanFace')
        work = session.scratch
        try:
            result = native_run(session)
            if args.player:
                player = native_player(session)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        if args.baseline:
            expected = expected | {'rounded_dry': [True, True]}
    (work / 'observed.json').write_text(json.dumps(result, indent=2) + '\n')
    assert result == expected, (result, expected)
    path = work / 'result.json'
    receipt = dict(passed=True, create=PINS['create_revision'], effects=result)
    if player is not None:
        receipt['unfrozen_native_player'] = player
    path.write_text(json.dumps(receipt, indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
