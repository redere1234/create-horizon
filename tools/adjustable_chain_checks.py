#!/usr/bin/env python3
"""Compare all settled analog chain ratios with real Java Create and Horizon."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import tempfile

from burner_heat_java_checks import number
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded


GEARSHIFT = (640, 80, 40)
DRIVE = (640, 80, 41)
OUTPUTS = [(641, 80, 40), (641, 80, 41)]
PROBES = [GEARSHIFT, DRIVE, *OUTPUTS]
WORLD = 'CreateAdjustableChain08'
STRENGTHS = [0, *range(1, 16), 7, 0]


def put(host, pos, block):
    host.command(f'setblock {xyz(pos)} {block}')


def setup(host):
    host.command('gamemode creative')
    host.command('forceload add 624 16 655 55')
    host.command('fill 635 80 22 646 85 46 minecraft:air')
    host.command('fill 635 79 22 646 79 46 minecraft:smooth_stone')
    put(host, GEARSHIFT, 'create:adjustable_chain_gearshift[axis=x]')
    put(host, DRIVE, 'create:encased_chain_drive[axis=x]')
    for pos in OUTPUTS:
        put(host, pos, 'create:shaft[axis=x]')
    host.command('fill 640 80 24 640 80 39 minecraft:redstone_wire')


def signal_source(host, before, after):
    # A direct block provides 15. Moving it along this dust line lets the
    # game's redstone simulator provide the other 14 nonzero strengths.
    if before:
        put(host, (640, 80, 23 + before if before < 15 else 39), 'minecraft:redstone_wire')
    if after:
        put(host, (640, 80, 23 + after if after < 15 else 39), 'minecraft:redstone_block')


def read_state(host, strength, adjustable_drives, ticks=20):
    blocks = host.snapshot(PROBES, ticks)
    adjustable, plain, *shafts = blocks
    assert adjustable['block'] == 'create:adjustable_chain_gearshift', blocks
    assert plain['block'] == 'create:encased_chain_drive', blocks
    assert [b['block'] for b in shafts] == ['create:shaft'] * 2, blocks
    assert [adjustable['properties']['part'], plain['properties']['part']] == ['start', 'end'], blocks
    assert adjustable['properties']['powered'] == str(strength > 0).lower(), (strength, blocks)
    assert number(adjustable, 'Signal') == strength, (strength, blocks)
    modifier = 1 + (strength + 1) / 16 if strength else 1
    expected = (32, 32 * modifier) if adjustable_drives else (32 / modifier, 32)
    for block, rpm in zip(blocks, expected * 2, strict=True):
        assert math.isclose(block['speed'], rpm, rel_tol=2e-6), (strength, blocks, expected)
    return blocks


def compare(actual, expected):
    for a, b in zip(actual, expected, strict=True):
        assert all(a[key] == b[key] for key in ('block', 'properties')), (a, b)
        assert math.isclose(a['speed'], b['speed'], rel_tol=2e-6), (a, b)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for arg in ['game', 'resources', 'ctl', 'create-jar', 'reference', 'build-result']:
        parser.add_argument('--' + arg, type=Path)
    args = parser.parse_args()
    session = None
    reference = None
    script_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result = dict(passed=False, create=PINS['create_revision'], fixture_sha256=script_hash,
                  cases=[], scope=__doc__)
    if args.java:
        host = Original()
        assert host.call('state', {})['data_version'] == 3955
        host.call('tick', {'frozen': True})
        work = Path(tempfile.mkdtemp(prefix='adjustable-chain-java-', dir=ROOT / '.local'))
    else:
        if not all((args.game, args.resources, args.ctl, args.reference, args.build_result)):
            parser.error('the Horizon comparison needs game, resources, ctl, reference and build-result')
        build = json.loads(args.build_result.read_text())
        assert build['passed'] and Path(build['game']).resolve() == args.game.resolve()
        assert hashlib.file_digest(args.game.open('rb'), 'sha256').hexdigest() == build['game_sha256']
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == result['create']
        assert reference['fixture_sha256'] == script_hash
        result.update(game_sha256=build['game_sha256'], horizon=build['horizon'],
                      reference_sha256=hashlib.sha256(args.reference.read_bytes()).hexdigest())
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='adjustable-chain-native', graphics=False, world=WORLD)
        host, work = Native(session), session.scratch
    print(json.dumps({'work': str(work)}), flush=True)
    try:
        if session:
            session.start()
        host.command('tp @s 644.5 81 43.5')
        if session:
            wait_loaded(session.call, [(635, 80, 22), (646, 80, 46)])
        setup(host)
        previous = 0
        for adjustable_drives in (True, False):
            if not adjustable_drives:
                put(host, (639, 80, 40), 'minecraft:air')
            put(host, (639, 80, 40 if adjustable_drives else 41),
                'create:creative_motor[facing=east]{ScrollValue:32}')
            for strength in STRENGTHS:
                signal_source(host, previous, strength)
                blocks = read_state(host, strength, adjustable_drives)
                row = dict(adjustable_drives=adjustable_drives, strength=strength, blocks=blocks)
                if reference:
                    original = reference['cases'][len(result['cases'])]
                    assert (original['adjustable_drives'], original['strength']) == (adjustable_drives, strength)
                    compare(blocks, original['blocks'])
                result['cases'].append(row)
                previous = strength
        signal_source(host, previous, 11)
        before = read_state(host, 11, False)
        if session:
            host.command('save-all flush')
            session.restart()
            wait_loaded(session.call, PROBES)
            after = read_state(host, 11, False)
            compare(after, before)
            compare(after, reference['saved'])
            result['restarted'] = after
        result['saved'] = before
        result['passed'] = True
    except BaseException as error:
        result['error'] = repr(error)
        raise
    finally:
        if session:
            session.stop()
        else:
            (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
        (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({'passed': result['passed'], 'cases': len(result['cases']),
                          'result': str(work / 'result.json')}), flush=True)


if __name__ == '__main__':
    main()
