#!/usr/bin/env python3
"""Observe real fan/Depot processing of effective fire-resistant item stacks.

The original 1.21.1 unit component maps to the target's canonical full-fire tag.
Other damage selectors have no original unit-component counterpart and remain
separately labelled target-policy controls. This compares eventual conversion
and conservation, not exact airflow presentation or first processing tick.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tempfile

from burner_heat_java_checks import field, items
from chain_drive_checks import Original
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded

X, Y, Z = 672, 80, 4
CASES = [
    ('diamond-default', 'minecraft:diamond', 'default', {}),
    ('diamond-full-fire', 'minecraft:diamond', 'full', {'minecraft:diamond': 3}),
    ('scrap-default', 'minecraft:netherite_scrap', 'default', {'minecraft:netherite_scrap': 3}),
    ('scrap-removal', 'minecraft:netherite_scrap', 'removed', {}),
    ('iron-recipe-full-fire', 'minecraft:raw_iron', 'full', {'minecraft:iron_ingot': 3}),
    ('food-recipe-full-fire', 'minecraft:beef', 'full', {}),
]


def xyz(pos):
    return ' '.join(map(str, pos))


def stock(item, mode, original):
    components = {'minecraft:custom_data': {'resistance_fixture': 717}}
    if mode == 'full':
        components['minecraft:fire_resistant' if original else 'minecraft:damage_resistant'] = (
            {} if original else {'types': '#minecraft:is_fire'})
    elif mode == 'removed':
        components['!minecraft:fire_resistant' if original else '!minecraft:damage_resistant'] = {}
    elif mode == 'partial':
        components['minecraft:damage_resistant'] = {'types': 'minecraft:lava'}
    elif mode == 'unsupported':
        components['minecraft:damage_resistant'] = {'types': '#fixture:unknown_fire_group'}
    return '{id:"' + item + '",count:3,components:' + json.dumps(components, separators=(',', ':')) + '}'


def held(raw):
    if not re.search(r'\bHeldItem\s*:', raw):
        return {}
    return items(raw, 'HeldItem')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for arg in ['game', 'resources', 'ctl', 'create-jar', 'reference', 'build-result']:
        parser.add_argument('--' + arg, type=Path)
    args = parser.parse_args()
    session = None
    if args.java:
        host = Original()
        state = host.call('state', {})
        assert state['ready'] and state['data_version'] == 3955
        host.call('tick', {'frozen': True})
        work = Path(tempfile.mkdtemp(prefix='fan-resistance-java-', dir=ROOT / '.local'))
        command = host.command
        cases = CASES
    else:
        assert all(getattr(args, n) for n in ['game', 'resources', 'ctl', 'create_jar', 'reference', 'build_result'])
        build = json.loads(args.build_result.read_text())
        assert build['passed'] and Path(build['game']).resolve() == args.game.resolve()
        assert hashlib.sha256(args.game.read_bytes()).hexdigest() == build['game_sha256']
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='fan-resistance-native', graphics=False, world='CreateFanResistance07')
        work = session.scratch
        command = lambda value: session.call('command', value)
        cases = CASES + [('target-partial', 'minecraft:diamond', 'partial', {}),
                         ('target-unsupported', 'minecraft:diamond', 'unsupported', {'minecraft:diamond': 3})]
    report = dict(passed=False, scope=__doc__, create=PINS['create_revision'], cases=[],
                  fixture_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())

    def save():
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        if args.java:
            (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')

    print(json.dumps({'work': str(work)}), flush=True)
    try:
        if session:
            session.start()
            command('tp @s 676.5 85 16.5')
            command('forceload add 656 -12 687 47')
            wait_loaded(session.call, [(668, Y, 2), (680, Y, 35)])
            command('tick freeze')
            report['game_sha256'] = build['game_sha256']
            report['horizon'] = build['horizon']
        else:
            command('forceload add 656 -12 687 47')
        command('gamemode creative')
        command('fill 668 78 2 680 78 35 minecraft:smooth_stone')
        command('fill 668 79 2 680 85 35 minecraft:air')
        depots = []
        for index, (name, item, mode, expected) in enumerate(cases):
            z = Z + index * 4
            depot = [X + 3, Y - 1, z]
            depots.append(depot)
            for pos, block in [
                ([X, Y, z], 'create:encased_fan[facing=east]'),
                (depot, 'create:depot'),
                ([X + 1, Y - 1, z], 'minecraft:glass'),
                ([X + 1, Y + 1, z], 'minecraft:glass'),
                ([X + 1, Y, z - 1], 'minecraft:glass'),
                ([X + 1, Y, z + 1], 'minecraft:glass'),
                ([X + 2, Y, z], 'minecraft:iron_bars'),
                ([X + 1, Y, z], 'minecraft:lava'),
                ([X - 1, Y, z], 'create:creative_motor[facing=east]{ScrollValue:256}'),
            ]:
                command('setblock ' + xyz(pos) + ' ' + block)
            command('data merge block ' + xyz(depot) + ' {HeldItem:{Item:' + stock(item, mode, args.java) + '}}')
        if session:
            command('tick unfreeze')
            session.call('wait', 220)
            command('tick freeze')
            raw = [' '.join(command('data get block ' + xyz(pos))['chat']) for pos in depots]
        else:
            observations = host.call('observe_ticks', {'ticks': 220, 'positions': depots})
            raw = [block['nbt'] for block in observations['samples'][-1]['blocks']]
        for (name, item, mode, expected), nbt in zip(cases, raw):
            actual = held(nbt)
            row = dict(name=name, input=item, mode=mode, expected=expected, actual=actual, nbt=nbt,
                       scope='original unit-component mapping' if name in {c[0] for c in CASES} else 'target-only selector policy')
            report['cases'].append(row)
            save()
            assert actual == expected, row
            if mode == 'default' and actual or mode in ('full', 'unsupported') and actual == {item: 3}:
                assert 'resistance_fixture' in field(nbt, 'HeldItem'), row
        if session:
            source = json.loads(args.reference.read_text())
            assert source['passed'] and source['create'] == report['create']
            assert [(r['name'], r['actual']) for r in report['cases'][:6]] == [(r['name'], r['actual']) for r in source['cases']]
            report['reference_sha256'] = hashlib.sha256(args.reference.read_bytes()).hexdigest()
            command('save-all flush')
            session.restart()
            session.call('wait', 5)
            retained = ' '.join(command('data get block ' + xyz(depots[-1]))['chat'])
            assert held(retained) == {'minecraft:diamond': 3} and 'fixture:unknown_fire_group' in retained, retained
            report['unsupported_retained_after_restart'] = retained
        report['passed'] = True
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        if session:
            session.stop()
        else:
            host.call('tick', {'frozen': True})
        save()
        print(json.dumps({'passed': report['passed'], 'cases': len(report['cases']), 'result': str(work / 'result.json')}), flush=True)


if __name__ == '__main__':
    main()
