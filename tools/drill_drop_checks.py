#!/usr/bin/env python3
"""Observe freshly spawned stationary Drill loot in Java Create and Horizon."""

import argparse
import errno
import json
from pathlib import Path
import re
import shutil
import tempfile

from burner_heat_java_checks import field, items, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession
import reference_java


DRILL = (1023, 130, 187)
MOTOR = (1022, 130, 187)
TARGET = (1024, 130, 187)
CENTER = tuple(axis + 0.5 for axis in TARGET)
LOADED = '1008 176 1039 191'
REGION = '1019 126 183 1028 134 191'
AREA = 'x=1019,y=126,z=183,dx=9,dy=8,dz=8'
NEARBY = 'type=minecraft:item,' + AREA
NEARBY_XP = 'type=minecraft:experience_orb,' + AREA
TICKS = 24
CASES = {
    'stone': ('minecraft:stone', ('minecraft:cobblestone',), True, False),
    'wheat': ('minecraft:wheat[age=7]', ('minecraft:wheat', 'minecraft:wheat_seeds'), True, False),
    'drops_disabled': ('minecraft:stone', (), False, False),
    'drill_placed_last': ('minecraft:stone', ('minecraft:cobblestone',), True, True),
    'diamond_ore': ('minecraft:diamond_ore', ('minecraft:diamond',), True, False),
    'ore_drops_disabled': ('minecraft:diamond_ore', (), False, False),
}


def clear(command):
    command('fill ' + REGION + ' minecraft:air')
    command(f'kill @e[{NEARBY}]')
    command(f'kill @e[{NEARBY_XP}]')


def setup(command, block, gamerule, drops, drill_last):
    command(f'gamerule {gamerule} {str(drops).lower()}')
    if block.startswith('minecraft:wheat'):
        command('setblock 1024 129 187 minecraft:farmland[moisture=7]')
    drill = f'setblock {xyz(DRILL)} create:mechanical_drill[facing=east]'
    target = f'setblock {xyz(TARGET)} {block}'
    motor = f'setblock {xyz(MOTOR)} create:creative_motor[facing=east]{{ScrollValue:256}}'
    for placement in (target, motor, drill) if drill_last else (drill, target, motor):
        command(placement)


def vec(nbt, key):
    value = tuple(float(word.strip().rstrip('dDfF'))
                  for word in field(nbt, key)[1:-1].split(','))
    assert len(value) == 3, (key, nbt)
    return value


def drop(nbt):
    inventory = items(nbt, 'Item')
    assert len(inventory) == 1, nbt
    item, count = next(iter(inventory.items()))
    return dict(item=item, count=count, position=vec(nbt, 'Pos'), motion=vec(nbt, 'Motion'),
                age=int(number({'nbt': nbt}, 'Age')),
                pickup_delay=int(number({'nbt': nbt}, 'PickupDelay')))


def verify(name, result):
    expected = CASES[name][1]
    drops = result['drops']
    assert sorted(row['item'] for row in drops) == sorted(expected), result
    xp = result['experience']
    assert (3 <= xp <= 7 if name == 'diamond_ore' else xp == 0), result
    for row in drops:
        assert row['age'] == 0 and row['pickup_delay'] == 10, row
        assert row['motion'] == (0.0, 0.0, 0.0), row
        assert all(abs(x - c) <= 0.125 for x, c in zip(row['position'], CENTER)), row
        if row['item'] == 'minecraft:wheat_seeds':
            assert 1 <= row['count'] <= 4, row
        else:
            assert row['count'] == 1, row
    if len(drops) > 1:
        assert all(row['position'] == drops[0]['position'] for row in drops[1:]), drops


def original():
    host = Original()
    scratch = Path(tempfile.mkdtemp(prefix='drill-drops-java-', dir=ROOT / '.local'))
    state = host.call('state', {})
    if state.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        state = host.call('state', {})
    assert state['ready'] and state['data_version'] == 3955, state
    manifest = json.loads((reference_java.BASE / 'manifest.json').read_text())
    assert manifest['create_sha256'] == reference_java.CREATE_SHA256
    host.call('tick', {'frozen': True})
    rule = ' '.join(host.command('gamerule doTileDrops')['messages']).lower()
    assert 'true' in rule or 'false' in rule, rule
    saved_rule = 'true' in rule
    try:
        host.command('gamemode creative')
        host.command('tp @s 1019.5 138 184.5')
        host.command('forceload add ' + LOADED)
        host.snapshot([DRILL, TARGET], 25)
        result = {}
        for name, (block, _, drops, drill_last) in CASES.items():
            clear(host.command)
            host.snapshot([DRILL, TARGET], 2)
            setup(host.command, block, 'doTileDrops', drops, drill_last)
            for tick in range(1, TICKS + 1):
                observed = host.snapshot([TARGET], 1)[0]
                if observed['block'] == 'minecraft:air':
                    break
            else:
                raise AssertionError((name, observed))
            entities = host.call('entities', {'center': CENTER, 'radius': 2})['entities']
            result[name] = dict(
                break_tick=tick,
                drops=[drop(row['nbt']) for row in entities if row['type'] == 'minecraft:item'],
                experience=sum(int(number(row, 'Value')) for row in entities
                               if row['type'] == 'minecraft:experience_orb'),
            )
            verify(name, result[name])
        return scratch, result
    finally:
        clear(host.command)
        host.command(f'gamerule doTileDrops {str(saved_rule).lower()}')
        host.command('forceload remove ' + LOADED)
        host.call('tick', {'frozen': state['server']['frozen']})
        (scratch / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session):
    from bearing_native_checks import Batch

    batch = Batch()
    batch.load((1019, 137, 184))
    for block, expected, drops, drill_last in CASES.values():
        clear(batch.command)
        batch.tick(2)
        setup(batch.command, block, 'minecraft:block_drops', drops, drill_last)
        for _ in range(TICKS):
            batch.tick()
            batch.expect(TARGET, 'minecraft:air')
            batch.command(f'execute as @e[{NEARBY}] run say drill_drop_present', True)
            batch.command(f'execute as @e[{NEARBY_XP}] run data get entity @s Value', True)
            for item in expected:
                selector = f'@e[{NEARBY},nbt={{Item:{{id:"{item}"}}}},limit=1]'
                batch.command(f'execute if entity {selector} run data get entity {selector}', True)
    rows = iter(batch.run(session, 'drill-drops'))
    result = {}
    for name, (_, expected, _, _) in CASES.items():
        for tick in range(1, TICKS + 1):
            air = next(rows)
            presence = next(rows)
            experience = next(rows)
            candidates = [next(rows) for _ in expected]
            if name not in result and 'bearing_check' in air:
                assert presence.count('drill_drop_present') == len(expected), (name, presence)
                result[name] = dict(
                    break_tick=tick,
                    drops=[drop(text) for text in candidates],
                    experience=sum(map(int, re.findall(r'entity data:\s+(\d+)', experience))),
                )
                verify(name, result[name])
        assert name in result, (name, result)
    assert next(rows, None) is None
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for key in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + key, type=Path)
    args = parser.parse_args()
    if args.java:
        scratch, cases = original()
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon runs require --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision'], reference
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='drill-drops-native', graphics=False, world='CreateDrillDrops')
        scratch = session.scratch
        try:
            cases = native(session)
        finally:
            session.control_temp.cleanup()
            # Finder can create .DS_Store while the disposable clone is removed.
            try:
                shutil.rmtree(session.resources)
            except OSError as error:
                if error.errno != errno.ENOTEMPTY:
                    raise
                shutil.rmtree(session.resources)
        for name, row in cases.items():
            assert row['break_tick'] == reference['cases'][name]['break_tick'], (name, row, reference)
    path = scratch / 'result.json'
    path.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], cases=cases), indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
