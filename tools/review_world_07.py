#!/usr/bin/env python3
"""Plan or author a fresh private CreateFactory07 review world.

The default --plan creates no world and starts no client. --build requires an
explicit successful build receipt and binary/resources/control/JAR paths. The
builder verifies its own scene; an independent clone audit is a separate step.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded

WORLD = 'CreateFactory07'
# Frozen inventory for reproducing the 0.7 review save.
CATALOG = '''
creative_motor shaft cogwheel large_cogwheel mechanical_press depot gearbox clutch
gearshift hand_crank andesite_encased_shaft brass_encased_shaft encased_chain_drive
andesite_casing brass_casing andesite_alloy_block brass_block zinc_block speedometer
stressometer water_wheel large_water_wheel millstone encased_fan mechanical_drill basin
mechanical_mixer blaze_burner iron_sheet golden_sheet copper_sheet andesite_alloy
brass_ingot brass_nugget zinc_ingot zinc_nugget wrench brass_sheet vertical_gearbox
goggles propeller wheat_flour dough belt_connector whisk empty_blaze_burner blaze_cake
creative_blaze_cake
'''.split()
FLOOR_Y = 127
PLAYER_Y = 128
BOUNDS = ((0, 127, 0), (55, 145, 39))
CATALOG_BARRELS = [(2, 128, 2), (4, 128, 2)]
MATERIAL_BARREL = (6, 128, 2)
CRAFTING_TABLE = (8, 128, 2)
PRESS = (8, 130, 34)
DEPOT = (8, 128, 34)
BASIN = (18, 128, 34)
AXES = 'xyz'
FACES = ('east', 'up', 'south')
FANS = [
    {'id': 'ordinary', 'z': 32, 'protected': False},
    {'id': 'full-fire', 'z': 36, 'protected': True},
]
MATERIALS = [
    ('minecraft:andesite', 32), ('minecraft:iron_ingot', 32),
    ('minecraft:iron_nugget', 32), ('minecraft:copper_ingot', 32),
    ('create:zinc_ingot', 32), ('create:brass_ingot', 16),
    ('minecraft:oak_log', 32), ('minecraft:cobblestone', 32),
    ('minecraft:redstone', 32), ('minecraft:snowball', 16),
    ('minecraft:flint', 16), ('minecraft:gravel', 16),
    ('minecraft:diamond', 6), ('minecraft:water_bucket', 1),
    ('minecraft:lava_bucket', 1), ('minecraft:bucket', 4),
    ('create:andesite_alloy', 32), ('create:shaft', 16),
    ('create:encased_chain_drive', 16), ('minecraft:hopper', 4),
    ('create:andesite_casing', 8), ('create:zinc_nugget', 16),
]


def xyz(pos):
    return ' '.join(map(str, pos))


def offset(pos, axis, distance):
    return tuple(value + (distance if index == axis else 0)
                 for index, value in enumerate(pos))


def rigs():
    result = []
    for shaft_axis in range(3):
        for chain_axis in range(3):
            if shaft_axis == chain_axis:
                continue
            index = len(result)
            base = (10 + 16 * (index % 3), 130, 8 + 16 * (index // 3))
            nodes = [offset(base, chain_axis, step) for step in range(3)]
            result.append({
                'id': index + 1, 'shaft_axis': AXES[shaft_axis],
                'connection_axis': AXES[chain_axis], 'nodes': nodes,
                'motor': offset(base, shaft_axis, -1),
                'motor_facing': FACES[shaft_axis],
                'output': offset(nodes[-1], shaft_axis, 1),
                'sign': (base[0], PLAYER_Y, base[2] + 5),
                'visit': (base[0] + 4.5, PLAYER_Y, base[2] + 5.5),
            })
    return result


def plan():
    catalog = ['create:' + name for name in CATALOG]
    assert len(catalog) == len(set(catalog)) == 48, catalog
    return {
        'world': WORLD, 'source': PINS['create_revision'],
        'floor_y': FLOOR_Y, 'player_y': PLAYER_Y, 'bounds': BOUNDS,
        'catalog_ids': catalog, 'catalog_barrels': [
            {'pos': pos, 'ids': catalog[index * 24:(index + 1) * 24]}
            for index, pos in enumerate(CATALOG_BARRELS)
        ],
        'materials': {'barrel': MATERIAL_BARREL, 'crafting_table': CRAFTING_TABLE,
                      'stacks': MATERIALS},
        'chain_rigs': rigs(),
        'single_press': {'press': PRESS, 'depot': DEPOT, 'motor': (6, 130, 34),
                         'input': 'minecraft:copper_ingot', 'count': 8, 'rpm': 0},
        'basin_press': {'basin': BASIN, 'press': (18, 130, 34),
                        'motor': (16, 130, 34), 'input': 'minecraft:snowball',
                        'count': 8, 'rpm': 0},
        'blasting': [{'id': row['id'], 'motor': (30, 129, row['z']),
                     'fan': (31, 129, row['z']), 'lava': (32, 129, row['z']),
                     'bars': (33, 129, row['z']), 'depot': (34, 128, row['z']),
                     'input': 'minecraft:diamond', 'count': 3, 'rpm': 0,
                     'components': ({'minecraft:damage_resistant':
                                     {'types': '#minecraft:is_fire'}}
                                    if row['protected'] else {})}
                    for row in FANS],
        'limits': [
            'Authoring checks are not an independent clone audit.',
            'No original asset bytes are written into public files.',
            'Partial/custom damage-resistance selectors are not demonstrated.',
            'The settings GUI clamps zero to one; stop a drive by disconnecting its shaft.',
        ],
    }


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(call, scratch, *, graphics=False, log=None):
    """NativeCheckSession callback; accepts only this builder's fresh private home."""
    scratch = Path(scratch).resolve()
    scratch.relative_to((ROOT / '.local').resolve())
    marker = json.loads((scratch / '.review07-fresh.json').read_text())
    assert marker['world'] == WORLD and marker['fresh_private_home'] == str(scratch)
    assert call('state')['world'] == WORLD
    scene = plan()
    result = {'passed': False, 'plan': scene, 'checks': [], 'images': [],
              'images_reviewed': False,
              'independent_clone_audit': 'not performed by this authoring callback'}

    def save():
        (scratch / 'review07-build-result.json').write_text(
            json.dumps(result, indent=2) + '\n')

    def cmd(text):
        reply = call('command', text)
        errors = ('not loaded', 'Unknown block', 'Unknown item', 'Unknown command')
        assert not any(error in line for line in reply.get('chat', [])
                       for error in errors), (text, reply)
        return reply

    def put(pos, state):
        return cmd('setblock ' + xyz(pos) + ' ' + state)

    def data(pos, nbt):
        return cmd('data merge block ' + xyz(pos) + ' ' + nbt)

    def read(pos, path=''):
        return ' '.join(cmd('data get block ' + xyz(pos) + ' ' + path)['chat'])

    def speed(pos):
        value = read(pos)
        found = re.search(r'\bSpeed:\s*(-?[\d.]+)', value)
        assert found, value
        return float(found[1])

    def stock(pos, slot, item, count):
        assert 0 <= slot < 27, (pos, slot)
        cmd('item replace block ' + xyz(pos)
            + f' container.{slot} with {item} {count}')

    def sign(pos, lines):
        assert len(lines) <= 4
        put(pos, 'minecraft:oak_sign[rotation=0]')
        data(pos, '{front_text:{messages:' + json.dumps(lines)
             + ',color:"black"},is_waxed:1b}')

    def depot_stock(pos, count, protected=False):
        component = (',components:{"minecraft:damage_resistant":'
                     '{types:"#minecraft:is_fire"}}' if protected else '')
        item = 'minecraft:diamond' if pos != DEPOT else 'minecraft:copper_ingot'
        data(pos, '{HeldItem:{Item:{id:"' + item + '",count:' + str(count)
             + component + '},Pos:.25f,PrevPos:.25f,Offset:0f,PrevOffset:0f,'
             'InSegment:0,Angle:0,InDirection:3},OutputBuffer:{Size:8,Items:[]}}')

    def check(name, **values):
        result['checks'].append(dict(name=name, **values))
        save()
        if callable(log):
            log(name)

    def container_counts(pos):
        counts = {}
        for slot in call('container', *pos)['slots']:
            if slot:
                counts[slot['item']] = counts.get(slot['item'], 0) + slot['count']
        return counts

    save()
    (scratch / 'review07-plan.json').write_text(json.dumps(scene, indent=2) + '\n')
    try:
        cmd('tick unfreeze')
        cmd('gamemode spectator')
        cmd('gamerule minecraft:spawn_mobs false')
        cmd('forceload add 0 0 55 39')
        for x in range(0, 56, 16):
            for z in range(0, 40, 16):
                right, back = min(x + 15, 55), min(z + 15, 39)
                cmd(f'tp @s {x + .5} 148 {z + .5}')
                call('wait-ready', 120)
                wait_loaded(call, [(x, PLAYER_Y, z), (right, PLAYER_Y, back)])
                cmd(f'fill {x} 128 {z} {right} 145 {back} minecraft:air')
                cmd(f'fill {x} 127 {z} {right} 127 {back} minecraft:smooth_stone')
        for start, end in [((0, 128, 0), (55, 128, 0)),
                           ((0, 128, 39), (55, 128, 39)),
                           ((0, 128, 1), (0, 128, 38)),
                           ((55, 128, 1), (55, 128, 38))]:
            cmd('fill ' + xyz(start) + ' ' + xyz(end) + ' minecraft:glass')
        check('Fresh elevated tiled floor and glass boundary created')

        for barrel in scene['catalog_barrels']:
            assert len(barrel['ids']) <= 27
            put(barrel['pos'], 'minecraft:barrel')
            for slot, item in enumerate(barrel['ids']):
                stock(barrel['pos'], slot, item, 1)
        put(MATERIAL_BARREL, 'minecraft:barrel')
        put(CRAFTING_TABLE, 'minecraft:crafting_table')
        for slot, (item, count) in enumerate(MATERIALS):
            stock(MATERIAL_BARREL, slot, item, count)
        sign((3, 128, 4), ['CATALOG: 48 IDs', 'Two barrels: 24 each', 'Materials + table', 'Goggles equipped'])

        default = (2, 130, 5)
        put(default, 'create:encased_chain_drive')
        call('wait', 8)
        state = call('block', *default)['state']
        assert 'axis=y' in state and 'axis_along_first=true' in state and 'part=none' in state, state
        check('Bare chain default has axis Y / first=true / part=none', state=state)
        put(default, 'minecraft:air')
        for rig in scene['chain_rigs']:
            for pos in rig['nodes']:
                put(pos, 'create:encased_chain_drive[axis=' + rig['shaft_axis'] + ']')
            put(rig['output'], 'create:shaft[axis=' + rig['shaft_axis'] + ']')
            put(rig['motor'], 'create:creative_motor[facing=' + rig['motor_facing'] + ']{ScrollValue:32}')
            sign(rig['sign'], [f'CHAIN {rig["id"]}: shaft {rig["shaft_axis"].upper()}',
                               'Link ' + rig['connection_axis'].upper() + ' / 32 RPM',
                               'Wrench middle; restore', 'Motor UI: reverse -32'])

        for pos, state in [((6, 130, 34), 'create:creative_motor[facing=east]{ScrollValue:0}'),
                           ((7, 130, 34), 'create:shaft[axis=x]'),
                           (PRESS, 'create:mechanical_press[facing=east]'),
                           (DEPOT, 'create:depot'),
                           ((16, 130, 34), 'create:creative_motor[facing=east]{ScrollValue:0}'),
                           ((17, 130, 34), 'create:shaft[axis=x]'),
                           ((18, 130, 34), 'create:mechanical_press[facing=east]'),
                           (BASIN, 'create:basin[facing=down]')]:
            put(pos, state)
        sign((8, 128, 37), ['PRESS / 8 COPPER', 'Motor UI: start 32', '8 sheets, one per hit', 'Empty hand: collect'])
        sign((18, 128, 37), ['PRESS + BASIN', '8 snowballs -> 2 blocks', 'Motor UI: start 32', 'Disconnect shaft: stop'])

        for row in FANS:
            z = row['z']
            # Full neighbors prevent world lava flow; iron bars preserve the
            # requested air path without replacing the source medium.
            for pos in [(32, 128, z), (32, 130, z), (32, 129, z - 1),
                        (32, 129, z + 1), (33, 128, z)]:
                put(pos, 'minecraft:glass')
            put((33, 129, z), 'minecraft:iron_bars')
            put((34, 128, z), 'create:depot')
            put((31, 129, z), 'create:encased_fan[facing=east]')
            put((30, 129, z), 'create:creative_motor[facing=east]{ScrollValue:0}')
            put((32, 129, z), 'minecraft:lava')
            sign((37, 128, z), [row['id'].upper() + ' / 3 DIAMONDS',
                                'Motor UI: start 32',
                                'Full fire tag: retained' if row['protected'] else 'Ordinary: destroyed',
                                'Do not open lava walls'])

        # Seed only canonical inventories after debris cleanup; do not replenish
        # mechanisms later to make authoring checks pass.
        cmd('kill @e[type=minecraft:item]')
        depot_stock(DEPOT, 8)
        data(BASIN, '{InputItems:{Size:9,Items:[{Slot:0,id:"minecraft:snowball",count:8}]},OutputItems:{Size:9,Items:[]}}')
        for row in FANS:
            depot_stock((34, 128, row['z']), 3, row['protected'])
        call('wait', 35)
        for rig in scene['chain_rigs']:
            readings = []
            for pos, part in zip(rig['nodes'], ['start', 'middle', 'end']):
                block = call('block', *pos)
                assert block['block'] == 'create:encased_chain_drive', block
                assert 'part=' + part in block['state'], block
                nbt = read(pos)
                assert 'id: "create:encased_shaft"' in nbt, nbt
                readings.append({'pos': pos, 'state': block['state'], 'rpm': speed(pos)})
            speeds = [entry['rpm'] for entry in readings] + [speed(rig['output']), speed(rig['motor'])]
            assert speeds == [32] * 5, (rig, speeds)
            check('Chain rig canonical topology and 32 RPM', rig=rig['id'], readings=readings)
        assert container_counts(DEPOT) == {'minecraft:copper_ingot': 8}
        assert container_counts(BASIN) == {'minecraft:snowball': 8}
        assert re.search(r'\[\s*\]', read(DEPOT, 'OutputBuffer.Items'))
        assert re.search(r'\[\s*\]', read(BASIN, 'OutputItems.Items'))
        for pos in [(6, 130, 34), PRESS, (16, 130, 34), (18, 130, 34)]:
            assert speed(pos) == 0, (pos, read(pos))
        for row in FANS:
            z = row['z']
            assert speed((30, 129, z)) == speed((31, 129, z)) == 0
            assert container_counts((34, 128, z)) == {'minecraft:diamond': 3}
            nbt = read((34, 128, z), 'HeldItem.Item')
            assert 'minecraft:diamond' in nbt and re.search(r'\bcount:\s*3\b', nbt), nbt
            assert ('minecraft:damage_resistant' in nbt) == row['protected'], nbt
            if row['protected']:
                assert '#minecraft:is_fire' in nbt, nbt
            assert re.search(r'\[\s*\]', read((34, 128, z), 'OutputBuffer.Items'))
            assert call('block', 32, 129, z)['block'] == 'minecraft:lava'
            for pos in [(32, 130, z), (32, 129, z - 1), (32, 129, z + 1), (33, 128, z)]:
                assert call('block', *pos)['block'] == 'minecraft:glass', pos
            assert call('block', 33, 129, z)['block'] == 'minecraft:iron_bars'
            for outside in [(31, 128, z), (34, 129, z),
                            (32, 128, z - 2), (32, 128, z + 2),
                            (32, 129, z - 2), (32, 129, z + 2)]:
                assert call('block', *outside)['block'] != 'minecraft:lava', outside
        check('Stopped press/Basin stocks and two contained lava/fan lanes verified')

        catalog = {item for pos in CATALOG_BARRELS for item in container_counts(pos)}
        assert catalog == set(scene['catalog_ids']), catalog
        assert all(len([slot for slot in call('container', *pos)['slots'] if slot]) == 24
                   for pos in CATALOG_BARRELS)
        order = ['wrench', 'encased_chain_drive', 'creative_motor', 'shaft', 'cogwheel',
                 'mechanical_press', 'depot', 'basin', 'encased_fan']
        order.extend(item for item in CATALOG if item not in order)
        cmd('gamemode creative')
        cmd('clear @s')
        for item in order[:36]:
            cmd('give @s create:' + item + ' 1')
        cmd('item replace entity @s armor.head with create:goggles')
        call('wait', 5)
        inventory = call('inventory')['counts']
        assert all(inventory.get('create:' + item, 0) >= 1 for item in order[:36]), inventory
        check('All 48 catalog IDs in 24-slot halves; carried items fit 36 slots',
              catalog_ids=sorted(catalog), carried=order[:36])
        cmd('time set day')
        cmd('weather clear')
        call('options-set', 'lang', 'en_us')
        call('options-set', 'chatVisibility', '2')
        call('options-set', 'tutorialStep', 'none')
        if graphics:
            cmd('gamemode spectator')
            call('key', 'f1', 'tap')
            try:
                for rig in scene['chain_rigs']:
                    center = tuple(sum(pos[axis] for pos in rig['nodes']) / 3 + .5 for axis in range(3))
                    cmd(f'tp @s {center[0] + 6} 136 {center[2] + 7}')
                    call('wait-ready', 120)
                    call('look-at', *center)
                    call('wait', 8)
                    image = scratch / f'chain-{rig["id"]}.png'
                    call('screenshot', image)
                    result['images'].append(str(image))
                cmd('tp @s 28.5 148 44.5')
                call('look-at', 28, 129, 20)
                call('wait', 8)
                image = scratch / 'overview.png'
                call('screenshot', image)
                result['images'].append(str(image))
            finally:
                call('key', 'f1', 'tap')
        cmd('gamemode survival')
        cmd('tp @s 4.5 128 6.5')
        call('wait', 8)
        assert call('state')['player']['on_ground']
        cmd('gamemode creative')
        cmd('spawnpoint @s 4 128 6')
        call('select', 'create:wrench')
        call('look-at', 10.5, 130.5, 8.5)
        result['save_reply'] = call('save-all')
        result['passed'] = True
        save()
        return result
    except BaseException as error:
        result['error'] = repr(error)
        save()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--plan', action='store_true')
    mode.add_argument('--build', action='store_true')
    parser.add_argument('--graphics', action='store_true')
    for name in ['game', 'resources', 'ctl', 'create-jar', 'build-receipt']:
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if not args.build:
        print(json.dumps(plan(), indent=2))
        return
    if not all([args.game, args.resources, args.ctl, args.create_jar, args.build_receipt]):
        parser.error('--build requires game/resources/ctl/create-jar/build-receipt')
    receipt = json.loads(args.build_receipt.read_text())
    assert receipt['passed'] and Path(receipt['game']).resolve() == args.game.resolve()
    assert sha(args.game) == receipt['game_sha256']
    session = NativeCheckSession(
        args.game, args.resources, args.ctl, args.create_jar,
        name='review07-source', graphics=args.graphics, world=WORLD, username='Delete228',
    )
    assert not (session.scratch / 'saves' / WORLD).exists()
    marker = {'world': WORLD, 'fresh_private_home': str(session.scratch),
              'username': 'Delete228', 'builder': 'tools/review_world_07.py'}
    (session.scratch / '.review07-fresh.json').write_text(json.dumps(marker) + '\n')
    (session.scratch / 'options.txt').write_text('tutorialStep:none\nchatVisibility:2\nlang:en_us\n')
    session.env.update(HORIZON_API_DISCOVERY='http://127.0.0.1:9/', HORIZON_NO_DISCORD='1')
    report = {'passed': False, 'world': WORLD, 'scratch': str(session.scratch),
              'game': str(session.game), 'game_sha256': sha(args.game),
              'build_receipt': str(args.build_receipt.resolve()),
              'build_receipt_sha256': sha(args.build_receipt),
              'authoring_checks_only': True}
    print(json.dumps(report), flush=True)
    try:
        with session:
            report['authoring'] = build(session.call, session.scratch, graphics=args.graphics)
        report['world_closed'] = True
        world = session.scratch / 'saves' / WORLD
        report['closed_world_files'] = {
            path.relative_to(world).as_posix(): sha(path)
            for path in sorted(world.rglob('*')) if path.is_file()
        }
        report['passed'] = True
    finally:
        (session.scratch / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(session.scratch / 'result.json', flush=True)


if __name__ == '__main__':
    main()
