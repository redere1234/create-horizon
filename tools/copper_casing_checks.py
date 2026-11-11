#!/usr/bin/env python3
"""Compare manual Copper Casing recipes in the two real clients."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tempfile

from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded


TARGET = (642, 80, 46)
PLAYER = (642.5, 80, 43.5)
AIM = (642.5, 80.5, 46.5)
CASING = 'create:copper_casing'
COPPER = 'minecraft:copper_ingot'
CASES = [
    ('stripped_oak_log[axis=x]', 'survival', CASING, 1),
    ('stripped_oak_wood[axis=z]', 'survival', CASING, 1),
    ('stripped_bamboo_block[axis=x]', 'survival', CASING, 1),
    ('stripped_warped_stem[axis=z]', 'survival', CASING, 1),
    ('stripped_crimson_hyphae[axis=y]', 'survival', CASING, 1),
    ('stripped_spruce_log', 'creative', CASING, 2),
    ('oak_log', 'survival', 'minecraft:oak_log', 2),
]


def scenario(host, session):
    host.command('forceload add 624 32 655 55')
    host.command('fill 640 79 42 645 79 49 minecraft:smooth_stone')
    host.command('fill 640 80 42 645 84 49 minecraft:air')
    host.command('tp @s ' + xyz(PLAYER))
    for start, mode, expected_block, expected_count in CASES:
        host.command('gamemode ' + mode)
        host.command('setblock ' + xyz(TARGET) + ' minecraft:' + start)
        host.command('clear @s')
        host.command('item replace entity @s weapon.mainhand with ' + COPPER + ' 2')
        if session:
            session.call('look-at', *AIM)
            session.call('wait', 8)
            session.call('mouse', 'right', 'down')
            session.call('wait', 3)
            session.call('mouse', 'right', 'up')
            block = session.call('block', *TARGET)['block']
            count = session.call('inventory')['counts'].get(COPPER, 0)
        else:
            host.call('camera', {'position': PLAYER, 'target': AIM})
            host.call('capture', {'name': 'copper-casing-before.png', 'frames': 16})
            hit = host.call('state', {})['hit']
            assert hit['pos'] == list(TARGET), hit
            host.call('input', {'key': 'use'})
            host.call('capture', {'name': 'copper-casing-after.png', 'frames': 10})
            host.call('input', {'key': 'use', 'down': False})
            block = host.call('block', {'pos': TARGET})['id']
            selected = ' '.join(host.command('data get entity @s SelectedItem')['messages'])
            count_match = re.search(r'\bcount\s*:\s*(\d+)', selected)
            assert COPPER in selected and count_match, selected
            count = int(count_match[1])
        assert (block, count) == (expected_block, expected_count), (start, mode, block, count)
        yield dict(input=start, mode=mode, block=block, copper_left=count)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for arg in ['game', 'resources', 'ctl', 'create-jar', 'reference', 'build-result']:
        parser.add_argument('--' + arg, type=Path)
    args = parser.parse_args()
    session = None
    reference = None
    script_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result = dict(passed=False, create=PINS['create_revision'], fixture_sha256=script_hash, cases=[])
    if args.java:
        host = Original()
        assert host.call('state', {})['data_version'] == 3955
        host.call('tick', {'frozen': True})
        work = Path(tempfile.mkdtemp(prefix='copper-casing-java-', dir=ROOT / '.local'))
    else:
        if not all((args.game, args.resources, args.ctl, args.reference, args.build_result)):
            parser.error('the Horizon comparison needs game, resources, ctl, reference and build-result')
        build = json.loads(args.build_result.read_text())
        assert build['passed'] and Path(build['game']).resolve() == args.game.resolve()
        with args.game.open('rb') as binary:
            assert hashlib.file_digest(binary, 'sha256').hexdigest() == build['game_sha256']
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == result['create']
        assert reference['fixture_sha256'] == script_hash
        result.update(game_sha256=build['game_sha256'], horizon=build['horizon'])
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='copper-casing-native', world='CreateCopperCasing08')
        host, work = Native(session), session.scratch
    print(json.dumps({'work': str(work)}), flush=True)
    try:
        if session:
            session.start()
            host.command('tp @s ' + xyz(PLAYER))
            wait_loaded(session.call, [TARGET])
        result['cases'].extend(scenario(host, session))
        if reference:
            assert result['cases'] == reference['cases']
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
