#!/usr/bin/env python3
"""Actual rendered Depot clearing after ordinary hopper extraction.

Container control queries are authoritative server reads. Client acceptance uses
the real draw callback's stack trace and captures, while the level is frozen
after extraction. No cold reopen or later machine tick may repair a ghost.
"""
import argparse
import hashlib
import json
from pathlib import Path

from native_check_session import NativeCheckSession, wait_loaded

DEPOT = (660, 65, 0)
HOPPER = (660, 64, 0)
CHEST = (661, 64, 0)
POWER = (659, 64, 0)


def run(session):
    call = session.call
    cmd = lambda text: call('command', text)
    xyz = lambda pos: ' '.join(map(str, pos))
    def counts(pos):
        totals = {}
        for stack in call('container', *pos)['slots']:
            if stack:
                totals[stack['item']] = totals.get(stack['item'], 0) + stack['count']
        return totals
    def received(after, stack):
        for _ in range(40):
            with session.log.open('rb') as stream:
                stream.seek(after)
                lines = stream.read().decode('utf-8', errors='replace').splitlines(keepends=True)
            for line in lines:
                prefix = 'Create render depot: '
                if prefix not in line or not line.endswith('\n'):
                    continue
                row = json.loads(line.split(prefix, 1)[1])
                if row['pos'] == list(DEPOT) and row['stack'] == stack:
                    return row
            call('wait', 2)
        raise AssertionError(('Actual Depot draw did not receive the expected stack', stack, lines[-8:]))

    cmd('gamemode survival'); cmd('gamemode creative')
    cmd('tp @s 662.5 69 3.5'); call('wait-ready', 120)
    wait_loaded(call, [DEPOT, HOPPER, CHEST, POWER])
    cmd('fill 656 63 -3 665 70 6 minecraft:air')
    cmd('fill 656 63 -3 665 63 6 minecraft:smooth_stone')
    cmd('setblock 662 64 3 minecraft:smooth_stone')
    cmd('tp @s 662.5 65 3.5'); call('wait', 10)
    assert call('state')['player']['on_ground']
    cmd('clear @s')
    for pos, block in [(POWER, 'minecraft:redstone_block'),
                       (CHEST, 'minecraft:chest'),
                       (HOPPER, 'minecraft:hopper[facing=east,enabled=false]'),
                       (DEPOT, 'create:depot')]:
        cmd('setblock '+xyz(pos)+' '+block)
    call('look-at', 'block', *DEPOT, 'up'); call('wait', 5)
    before = session.log.stat().st_size
    cmd('data merge block '+xyz(DEPOT)+
        ' {HeldItem:{Item:{id:"create:copper_sheet",count:1}},OutputBuffer:{Size:8,Items:[]}}')
    visible = received(before, {'item': 'create:copper_sheet', 'count': 1})
    assert counts(DEPOT) == {'create:copper_sheet': 1}
    assert counts(CHEST) == {}
    call('screenshot', session.scratch/'depot-before-extraction.png')
    after = session.log.stat().st_size
    cmd('setblock '+xyz(POWER)+' minecraft:air')
    for _ in range(60):
        if counts(CHEST) == {'create:copper_sheet': 1} and not counts(HOPPER) and not counts(DEPOT):
            break
        call('wait', 2)
    else:
        raise AssertionError(('Hopper extraction did not finish', counts(DEPOT), counts(HOPPER), counts(CHEST)))
    cmd('tick freeze')
    raw = cmd('data get block '+xyz(DEPOT))['chat']
    assert 'HeldItem' not in ' '.join(raw), raw
    try:
        cleared = received(after, None)
    finally:
        call('screenshot', session.scratch/'depot-after-extraction.png')
    return dict(passed=True, server_depot=raw, server_chest=counts(CHEST),
                actual_client_draw_before=visible, actual_client_draw_after=cleared,
                scope=__doc__, screenshots_visually_inspected=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['game', 'resources', 'ctl', 'create-jar']:
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--expected-sha', required=True)
    args = parser.parse_args()
    digest = hashlib.sha256(Path(args.game).read_bytes()).hexdigest()
    if digest != args.expected_sha:
        raise SystemExit('Game SHA256 does not match the selected build')
    session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                 name='depot-sync-native', graphics=True)
    (session.scratch/'options.txt').write_text('tutorialStep:none\nchatVisibility:2\n')
    session.env.update(HORIZON_API_DISCOVERY='http://127.0.0.1:9/', HORIZON_NO_DISCORD='1')
    report = dict(passed=False, game_sha256=digest, scratch=str(session.scratch))
    print(json.dumps(dict(status='starting', **report)), flush=True)
    try:
        with session:
            report['checks'] = run(session)
        report['passed'] = True
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        output = session.scratch/'aggregate-result.json'
        output.write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps(dict(passed=report['passed'], result=str(output))), flush=True)


if __name__ == '__main__':
    main()
