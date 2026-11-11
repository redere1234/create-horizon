#!/usr/bin/env python3
"""Exercise the real belt connector and capture its valid and invalid previews."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tempfile

from chain_drive_checks import Native, Original, xyz
from common import ROOT
from native_check_session import NativeCheckSession, wait_loaded

FIRST = (720, 80, 40)
SECOND = (720, 80, 44)
PLAYER = (723.5, 80, 42.5)
WORLD = 'CreateBeltPreview'
TRACE = re.compile(r'Create belt preview: .*?valid=(true|false) spawned=([1-9][0-9]*)')


def center(pos):
    return [v + 0.5 for v in pos]


def scenario(host, session, work):
    cmd = host.command
    cmd('gamemode creative')
    cmd('forceload add 704 32 735 55')
    cmd('fill 716 79 36 725 79 47 minecraft:smooth_stone')
    cmd('fill 716 80 36 725 85 47 minecraft:air')
    cmd('time set noon')
    cmd('weather clear')
    cmd('tp @s ' + xyz(PLAYER))
    cmd('clear @s')
    cmd('item replace entity @s weapon.mainhand with create:belt_connector 4')
    cmd('setblock ' + xyz(FIRST) + ' create:shaft[axis=x]')
    cmd('setblock ' + xyz(SECOND) + ' create:shaft[axis=x]')

    def aim(pos):
        if session:
            session.call('look-at', *center(pos))
            session.call('wait', 8)
        else:
            host.call('camera', {'position': PLAYER, 'target': center(pos), 'hide_gui': True})
            host.call('capture', {'name': 'belt-preview-aim.png', 'frames': 16})
            hit = host.call('state', {})['hit']
            assert hit['pos'] == list(pos), hit

    def click():
        if session:
            session.call('mouse', 'right', 'down')
            session.call('wait', 3)
            session.call('mouse', 'right', 'up')
            session.call('wait', 7)
        else:
            host.call('input', {'key': 'use'})
            host.call('capture', {'name': 'belt-preview-click.png', 'frames': 16})
            host.call('input', {'key': 'use', 'down': False})

    def block(pos):
        return session.call('block', *pos)['block'] if session else host.call('block', {'pos': pos})['id']

    def capture(label, valid=None):
        name = f'belt-preview-{label}.png'
        if session:
            start = session.log.stat().st_size
            session.call('wait', 20)
            path = work / name
            session.call('screenshot', path)
            with session.log.open('rb') as log:
                log.seek(start)
                matches = TRACE.findall(log.read().decode())
            if valid is None:
                assert not matches, (label, matches)
            else:
                assert matches and all(kind == str(valid).lower() for kind, _ in matches), (label, matches)
        else:
            path = Path(host.call('capture', {'name': name, 'frames': 28})['path'])
        assert path.stat().st_size > 1024, path
        return str(path)

    if session:
        session.call('key', 'f1', 'tap')
    aim(SECOND)
    images = {'before': capture('before')}
    aim(FIRST)
    click()
    aim(SECOND)
    images['valid'] = capture('valid', True)
    cmd('setblock ' + xyz(SECOND) + ' create:shaft[axis=y]')
    aim(SECOND)
    images['invalid'] = capture('invalid', False)
    click()
    assert block(SECOND) == 'create:shaft'
    assert block((720, 80, 42)) == 'minecraft:air'
    cmd('setblock ' + xyz(SECOND) + ' create:shaft[axis=x]')
    aim(SECOND)
    click()
    assert block(FIRST) == block(SECOND) == block((720, 80, 42)) == 'create:belt'
    images['after'] = capture('after')
    if session:
        session.call('key', 'f1', 'tap')
        cmd('setblock 719 80 40 create:creative_motor[facing=east]{ScrollValue:32}')
        cmd('tp @s 723.5 80 51.5')
        shafts = [(47, 'y'), (51, 'x'), (55, 'x')]
        wait_loaded(session.call, [(720, 80, z) for z, _ in shafts])
        cmd('fill 716 79 47 725 79 57 minecraft:smooth_stone')
        for z, axis in shafts:
            cmd(f'setblock 720 80 {z} create:shaft[axis={axis}]')
        session.call('wait', 8)
        assert all(block((720, 80, z)) == 'create:shaft' for z, _ in shafts)
        session.call('look-at', 720.5, 80.5, 51.5)
        cmd('spawnpoint @s 723 80 51')
        cmd('save-all flush')
    return images


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'build-result', 'resources', 'ctl', 'create-jar'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    session = None
    if args.java:
        host = Original()
        assert host.call('state', {})['data_version'] == 3955
        host.call('tick', {'frozen': False})
        work = Path(tempfile.mkdtemp(prefix='belt-preview-java-', dir=ROOT / '.local'))
    else:
        if not all((args.game, args.build_result, args.resources, args.ctl)):
            parser.error('the Horizon comparison needs game, build-result, resources and ctl')
        build = json.loads(args.build_result.read_text())
        assert build['passed'] and Path(build['game']).resolve() == args.game.resolve()
        with args.game.open('rb') as executable:
            assert hashlib.file_digest(executable, 'sha256').hexdigest() == build['game_sha256']
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='belt-preview-native', world=WORLD)
        host, work = Native(session), session.scratch
    print(json.dumps({'work': str(work)}), flush=True)
    try:
        if session:
            session.start()
            host.command('tp @s ' + xyz(PLAYER))
            wait_loaded(session.call, [FIRST, SECOND])
        images = scenario(host, session, work)
        report = {'passed': True, 'images': images}
        if session:
            report['game_sha256'] = build['game_sha256']
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report), flush=True)
    finally:
        if session:
            session.stop()
        else:
            host.call('camera', {'position': PLAYER, 'target': center(SECOND), 'hide_gui': False})
            (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


if __name__ == '__main__':
    main()
