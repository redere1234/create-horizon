#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare ordinary redstone transitions on isolated Clutch and Gearshift lines."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession


WORLD = 'CreateTransmissionReview'
LEVER = 'minecraft:lever[face=floor,facing=north,powered=false]'
START = (850, 80, 40)


def fixtures():
    for kind_index, kind in enumerate(('clutch', 'gearshift')):
        for sign in (1, -1):
            x, y, z = START
            z += 9 * (kind_index * 2 + (sign < 0))
            relay = (x, y, z)
            motor = (x - sign * 3, y, z)
            control = (x, y + 1, z)
            shafts = [(x + n * sign, y, z) for n in (-2, -1, 1, 2)]
            facing = 'east' if sign > 0 else 'west'
            yield kind, facing, relay, motor, control, shafts


def put(pos, block):
    return f'setblock {xyz(pos)} {block}'


def schedule(command, step, sample):
    command('gamemode creative')
    command('tp @s 850.5 81 43.5')
    command('forceload add 832 32 863 79')
    step(40)
    command('fill 844 80 37 856 85 70 minecraft:air')
    command('fill 844 79 37 856 79 70 minecraft:smooth_stone')
    for kind, facing, relay, motor, control, shafts in fixtures():
        command(put(relay, f'create:{kind}[axis=x]'))
        for shaft in shafts:
            command(put(shaft, 'create:shaft[axis=x]'))
        command(put(motor, f'create:creative_motor[facing={facing}]{{ScrollValue:32}}'))
        step(20)
        sample(kind, facing, 'initial', relay, shafts)
        for phase, block in (('power_on', 'minecraft:redstone_block'), ('power_off', 'minecraft:air')):
            command(put(control, block))
            sample(kind, facing, phase + ':0', relay, shafts)
            for age in (1, 2, 3):
                step(1)
                sample(kind, facing, f'{phase}:{age}', relay, shafts)
        # The second change lands before the reattachment tick.
        command(put(control, 'minecraft:redstone_block'))
        command(put(control, 'minecraft:air'))
        sample(kind, facing, 'pulse:0', relay, shafts)
        step(1)
        sample(kind, facing, 'pulse:1', relay, shafts)
        command(put(control, LEVER))
    command('time set noon')
    command('weather clear')
    command('tp @s 850.5 81 43.5')
    command('save-all flush')


def run_java():
    host = Original()
    assert host.call('state', {})['data_version'] == 3955
    host.call('tick', {'frozen': True})
    work = Path(tempfile.mkdtemp(prefix='transmission-java-', dir=ROOT / '.local'))
    rows = []

    def step(ticks):
        host.call('observe_ticks', {'ticks': ticks, 'positions': [START]})

    def sample(kind, facing, phase, relay, shafts):
        powered = host.call('block', {'pos': relay})['properties']['powered'] == 'true'
        rpm = [number(host.call('block', {'pos': shaft}), 'Speed', 0) for shaft in shafts]
        rows.append(dict(kind=kind, facing=facing, phase=phase, powered=powered, rpm=rpm))

    schedule(host.command, step, sample)
    (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
    return work, rows


def run_native(args):
    session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                 name='transmission-native', graphics=False, world=WORLD)
    work = session.scratch
    script, output = work / 'commands.jsonl', work / 'observations.jsonl'
    operations = []
    rows = []

    def command(text, record=False):
        operations.append(dict(op='cmd', cmd=text, record=record))

    def step(ticks):
        operations.append(dict(op='tick', n=ticks))

    def sample(kind, facing, phase, relay, shafts):
        command(f'execute if block {xyz(relay)} create:{kind}[powered=true] run say relay_powered', True)
        for shaft in shafts:
            command(f'data get block {xyz(shaft)}', True)
        rows.append(dict(kind=kind, facing=facing, phase=phase))

    command(f'tp @s {START[0]}.5 81 {START[2]}.5')
    operations.append(dict(op='settle'))
    schedule(command, step, sample)
    script.write_text(''.join(json.dumps(op) + '\n' for op in operations))
    session.env.update(HORIZON_COMMAND_SCRIPT=str(script), HORIZON_COMMAND_OUTPUT=str(output),
                       HORIZON_API_DISCOVERY='http://127.0.0.1:9/')
    try:
        with session.log.open('w') as log:
            subprocess.run([str(session.game), '--headless', '--resources', str(session.resources),
                            '--world', WORLD, '--seed', '5', '--creative', '--render-distance', '4'],
                           cwd=work, env=session.env, stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=240)
    finally:
        session.control_temp.cleanup()

    texts = [' '.join(''.join(span[0] for span in message) for message in json.loads(line)['messages'])
             for line in output.read_text().splitlines()]
    assert len(texts) == 5 * len(rows), len(texts)
    for index, row in enumerate(rows):
        powered, *shafts = texts[5 * index:5 * index + 5]
        row.update(powered='relay_powered' in powered, rpm=[number({'nbt': text}, 'Speed') for text in shafts])
    return work, rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'create-jar', 'reference', 'build-result'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if not args.java and not all((args.game, args.resources, args.ctl, args.build_result)):
        parser.error('Horizon needs --game, --resources, --ctl and --build-result')
    result = dict(create=PINS['create_revision'],
                  fixture_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    if not args.java:
        build = json.loads(args.build_result.read_text())
        assert build['passed'] and build['horizon'] == PINS['horizon_revision']
        assert Path(build['game']).resolve() == args.game.resolve()
        with args.game.open('rb') as binary:
            assert build['game_sha256'] == hashlib.file_digest(binary, 'sha256').hexdigest()
        result['game_sha256'] = build['game_sha256']
    work, rows = run_java() if args.java else run_native(args)
    result['rows'] = rows
    mismatches = []
    if args.reference:
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and result['create'] == reference['create']
        assert result['fixture_sha256'] == reference['fixture_sha256']
        mismatches = [dict(native=got, java=expected)
                      for got, expected in zip(rows, reference['rows'], strict=True) if got != expected]
    result.update(passed=not mismatches, mismatches=mismatches)
    path = work / 'result.json'
    path.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(dict(result=str(path), samples=len(rows), mismatches=len(mismatches))), flush=True)
    assert not mismatches, mismatches


if __name__ == '__main__':
    main()
