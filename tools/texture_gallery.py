#!/usr/bin/env python3
"""Build and verify a clean world for comparing the fallback and JAR art."""

import argparse
import json
from pathlib import Path
import shutil
from textwrap import wrap

from bearing_native_checks import Batch
from catalog import BLOCKS, INTERNAL_BLOCKS, ITEMS
from common import ROOT
from contraption_review_stations import sign
from native_check_session import NativeCheckSession


Y = 160
COLUMNS = 12
BLOCK_STEP = 6
FIRST_ITEM_ROW = 68
SPAWN = (1.5, Y + 2, -7.5)
REVISED = {
    'adjustable_chain_gearshift', 'blaze_burner', 'brass_funnel', 'chute', 'clutch',
    'crushing_wheel', 'deployer', 'encased_chain_drive', 'encased_fan', 'fluid_valve',
    'gantry_carriage', 'gearshift', 'hand_crank', 'linear_chassis', 'mechanical_bearing',
    'mechanical_drill', 'mechanical_harvester', 'mechanical_piston', 'mechanical_plough', 'mechanical_pump',
    'mechanical_saw', 'radial_chassis', 'secondary_linear_chassis', 'smart_chute',
    'speedometer', 'sticky_mechanical_piston', 'sticker', 'stressometer',
    'windmill_bearing',
}

VISIBLE_INTERNAL = [
    name for name in INTERNAL_BLOCKS if name not in ('water_wheel_structure', 'crushing_wheel_controller')
]
SPECIAL = {
    'belt': 'facing=east,slope=horizontal,part=middle',
    'brass_funnel': 'facing=down',
    'fluid_pipe': 'east=true,west=true',
    'hand_crank': 'facing=south',
    'large_water_wheel': 'axis=z',
    'mechanical_harvester': 'facing=south',
    'mechanical_saw': 'facing=up',
    'sail_frame': 'facing=south',
    'shaft': 'axis=x',
    'smart_chute': 'powered=false',
    'water_wheel': 'facing=north',
}
VARIANTS = [
    ('blaze_burner', 'blaze=kindled', 'Kindled Burner'),
    ('blaze_burner', 'blaze=seething', 'Seething Burner'),
    ('fluid_tank', 'shape=plain', 'Solid Fluid Tank'),
    ('chute', 'facing=down,shape=window', 'Windowed Chute'),
    ('mechanical_piston_head', 'facing=south,type=sticky', 'Sticky Head'),
    ('smart_chute', 'powered=true', 'Powered Smart Chute'),
    ('sticker', 'facing=south,extended=true,powered=true', 'Extended Sticker'),
    ('adjustable_chain_gearshift', 'powered=true', 'Powered Chain Gearshift'),
    ('clutch', 'axis=z,powered=true', 'Powered Clutch'),
    ('gearshift', 'axis=z,powered=true', 'Powered Gearshift'),
    ('creative_motor', 'facing=up', 'Vertical Creative Motor'),
]
STATES = ROOT / 'content/data/create/horizon/block'


def coordinates(index, start_z=0):
    return (index % COLUMNS) * BLOCK_STEP, Y + 1, start_z + (index // COLUMNS) * BLOCK_STEP


def artwork_state(name):
    if name in SPECIAL:
        return SPECIAL[name]
    if name.endswith('_sail'):
        return 'facing=south'
    fields = json.loads((STATES / f'{name}.json').read_text()).get('state_properties', {})
    if 'south' in fields.get('facing', {}).get('values', []):
        return 'facing=south'
    return ''


def label(batch, pos, name, revised=False):
    lines = wrap(name, width=14)[:4]
    lines += [''] * (4 - len(lines))
    sign(batch, pos, lines)
    messages = json.dumps(lines)
    color = 'red' if revised else 'black'
    text = f'{{messages:{messages},color:"{color}"}}'
    batch.command(f'data merge block {pos[0]} {pos[1]} {pos[2]} '
                  f'{{front_text:{text},back_text:{text}}}')


def place_block(batch, index, name, state, title):
    x, y, z = coordinates(index)
    sign_height = y
    if name == 'hand_crank':
        batch.put((x, y, z - 1), 'minecraft:polished_deepslate')
    if name in ('water_wheel', 'large_water_wheel'):
        y += 2 if name == 'large_water_wheel' else 1
        batch.command(f'fill {x} {Y + 1} {z + 1} {x} {y} {z + 1} minecraft:polished_andesite')
    block = f'create:{name}'
    suffix = f'[{state}]' if state else ''
    if name == 'blaze_burner' and state:
        suffix += '{isCreative:1b}'
    batch.put((x, y, z), block + suffix)
    if 'powered=true' in state:
        batch.put((x, y - 1, z), 'minecraft:redstone_block')
    label(batch, (x, sign_height, z + 2), title, name in REVISED)
    batch.expect((x, y, z), block)


def review_bench(batch):
    y = Y + 1
    for x, block in [
        (9, 'creative_motor[facing=east]{ScrollValue:128}'),
        (10, 'speedometer[facing=south,axis_along_first=true]'),
        (11, 'stressometer[facing=south,axis_along_first=true]'),
        (12, 'mechanical_press[facing=east]'),
        (17, 'encased_chain_drive[axis=z]'),
        (18, 'adjustable_chain_gearshift[axis=z]'),
        (19, 'encased_chain_drive[axis=z]'),
        (24, 'blaze_burner[blaze=kindled]{isCreative:1b}'),
        (26, 'blaze_burner[blaze=seething]{isCreative:1b}'),
    ]:
        batch.put((x, y, -4), 'create:' + block)
    batch.put((17, y, -5), 'create:creative_motor[facing=south]{ScrollValue:32}')
    batch.put((17, y, -3), 'create:shaft[axis=z]')
    batch.put((19, y, -3), 'create:shaft[axis=z]')
    for x, name in ((10, 'Live Gauges'), (18, 'Connected Chain'), (24, 'Kindled Burner'), (26, 'Seething Burner')):
        label(batch, (x, y, -2), name, True)
    batch.command('item replace entity @s hotbar.0 with create:goggles')
    batch.command('item replace entity @s hotbar.1 with create:wrench')
    batch.command('item replace entity @s hotbar.2 with minecraft:iron_ingot')


def create_gallery(session):
    batch = Batch()
    batch.load((32, Y + 3, 39))
    batch.command('forceload add -16 -16 79 95')
    batch.tick(30)
    batch.command(f'fill -8 {Y} -10 74 {Y} 92 minecraft:smooth_stone')
    batch.command(f'fill -8 {Y} 65 74 {Y} 66 minecraft:polished_deepslate')
    batch.put((8, Y + 6, 11), 'minecraft:barrier')
    batch.put((8, Y + 3, 78), 'minecraft:barrier')
    batch.command('gamerule minecraft:advance_time false')
    batch.command('time set noon')
    batch.command('weather clear')
    for index, name in enumerate(BLOCKS + VISIBLE_INTERNAL):
        place_block(batch, index, name, artwork_state(name), name.replace('_', ' ').title())
    for index, (name, state, title) in enumerate(VARIANTS, len(BLOCKS + VISIBLE_INTERNAL)):
        place_block(batch, index, name, state, title)
    for index, name in enumerate(ITEMS):
        x, y, z = coordinates(index, FIRST_ITEM_ROW)
        batch.put((x, y + 1, z), 'minecraft:polished_deepslate')
        batch.command(f'summon minecraft:item_frame {x + .5} {y + 1.5} {z + 1.05} '
                      f'{{Facing:3b,Fixed:1b,Tags:["gallery_{index}"],Item:{{id:"create:{name}",count:1}}}}')
        label(batch, (x, y, z + 2), name.replace('_', ' ').title())
        batch.command(f'data get entity @e[type=minecraft:item_frame,tag=gallery_{index},limit=1] Item.id', True)
    label(batch, (-2, Y + 1, -5), 'Create Texture Gallery')
    label(batch, (4, Y + 1, -5), 'Blocks Ahead Items Far Side')
    label(batch, (4, Y + 1, -8), 'Red Signs Revised Samples', True)
    review_bench(batch)
    batch.command(f'setworldspawn 1 {Y + 2} -8')
    batch.command(f'spawnpoint @s 1 {Y + 2} -8')
    batch.command(f'tp @s {SPAWN[0]} {SPAWN[1]} {SPAWN[2]} 0 7')
    batch.command('forceload remove all')
    rows = batch.run(session, 'build-gallery')
    expected = len(BLOCKS + VISIBLE_INTERNAL + VARIANTS)
    assert len(rows) == expected + len(ITEMS) and all('bearing_check' in r for r in rows[:expected]), rows
    assert all(f'"create:{name}"' in row for name, row in zip(ITEMS, rows[expected:], strict=True)), rows
    return dict(blocks=len(BLOCKS), additional_samples=expected - len(BLOCKS), items=len(ITEMS))


def capture(session, name):
    call = session.call
    call('options-set', 'tutorialStep', 'none')
    call('options-set', 'chatVisibility', 2)
    call('command', 'gamemode spectator @s')
    call('key', 'f1', 'tap')
    shots = [
        ('blocks', (8.5, Y + 7, 11.5), (22, Y + 1, 8)),
        ('kinetics', (15.5, Y + 4, -6.5), (14.5, Y + 1, 1.5)),
        ('motor', (2.6, Y + 3.6, 4.0), (.5, Y + 1.5, .5)),
        ('wheels', (3.25, Y + 5.5, 6.5), (.5, Y + 3.5, 12.5)),
        ('small-wheel', (64.6, Y + 5.0, 1.8), (66.5, Y + 2.5, 6.5)),
        ('machines', (11.5, Y + 6.5, 13.5), (19.5, Y + 1, 24)),
        ('palette', (18.5, Y + 6.5, 24.5), (23.5, Y + 1, 36)),
        ('items', (8.5, Y + 4, 78.5), (21, Y + 2, 70)),
        ('gauges', (10.5, Y + .95, -1.0), (10.9, Y + 1.5, -3.5)),
        ('chain', (17.5, Y + 2.25, -1.0), (18.5, Y + 1.6, -3.5)),
        ('burners', (25.5, Y + 1.1, -0.2), (25.5, Y + 1.6, -3.5)),
    ]
    for sample in ('hand_crank', 'encased_fan', 'mechanical_drill', 'mechanical_harvester', 'mechanical_plough',
                   'mechanical_saw', 'brass_funnel', 'deployer'):
        x, y, z = coordinates(BLOCKS.index(sample))
        shots.append((sample, (x + 2, y + 1.0, z + 2.8), (x + .5, y + .48, z + .55)))
    for suffix, camera, target in shots:
        call('command', 'tp @s ' + ' '.join(str(coordinate) for coordinate in camera))
        call('wait', 10)
        call('look-at', *target)
        call('wait', 25)
        call('screenshot', session.scratch / f'{name}-{suffix}.png')
    call('key', 'f1', 'tap')
    call('command', 'gamemode creative @s')
    call('command', f'tp @s {SPAWN[0]} {SPAWN[1]} {SPAWN[2]} 0 7')
    call('open-inventory')
    call('wait', 5)
    width, height = call('ui')['gui_size']
    # The pinned creative panel is 195 x 136 GUI pixels. Page two opens
    # Create's first tab, which lets the screenshot show the actual block icons.
    call('click-at', round((width + 195) / 2 - 10), round((height - 136) / 2 - 40))
    call('wait', 5)
    inventory = call('ui')
    assert any((widget.get('stack') or {}).get('item') == 'create:mechanical_press'
               and widget['id'].startswith('slot-9') for widget in inventory['widgets']), inventory
    (session.scratch / f'{name}-inventory-ui.json').write_text(json.dumps(inventory, indent=2))
    call('screenshot', session.scratch / f'{name}-inventory.png')
    call('close')


def verify_review_bench(session):
    for x, expected in ((17, 'start'), (18, 'middle'), (19, 'end')):
        state = session.call('block', x, Y + 1, -4)['state']
        assert f'part={expected}' in state, state
    for x, heat in ((24, 'kindled'), (26, 'seething')):
        state = session.call('block', x, Y + 1, -4)['state']
        assert f'blaze={heat}' in state, state
    for key in ('front_text', 'back_text'):
        chat = session.call('command', f'data get block 18 {Y + 1} -2 {key}.color')['chat']
        assert any('red' in line for line in chat), chat
    session.call('command', f'tp @s 18.5 {Y + 4} 53.5')
    session.call('wait-ready', 60)
    for index, (block, properties, _) in enumerate(VARIANTS, len(BLOCKS + VISIBLE_INTERNAL)):
        if 'powered=true' in properties:
            result = session.call('block', *coordinates(index))
            assert result['loaded'] and 'powered=true' in result['state'], result
            if block == 'sticker':
                assert 'extended=true' in result['state'], result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('game', 'resources', 'ctl'):
        parser.add_argument('--' + arg, type=Path, required=True)
    parser.add_argument('--create-jar', type=Path)
    args = parser.parse_args()
    session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                 name='texture-gallery', world='Create Texture Gallery - Review 2',
                                 size=(1536, 960), username='BearingReview')
    print(session.scratch, flush=True)
    try:
        report = create_gallery(session)
        local_jar = session.scratch / 'horizon-mods/create-resources/create.jar'
        try:
            session.start()
            verify_review_bench(session)
            capture(session, 'fallback')
            log = session.log.read_text()
            assert 'Create: using provisional resources' in log
            assert 'bundled content could not be loaded' not in log
            if args.create_jar:
                shutil.copyfile(args.create_jar, local_jar)
                start = session.log.stat().st_size
                session.restart()
                capture(session, 'original')
                assert 'local resources from Create' in session.log.read_text()[start:]
                local_jar.unlink()
                start = session.log.stat().st_size
                session.restart()
                assert 'Create: using provisional resources' in session.log.read_text()[start:]
        finally:
            session.stop()
            local_jar.unlink(missing_ok=True)
        world = session.scratch / 'saves' / session.world
        assert (world / 'level.dat').is_file(), world
        archive = shutil.make_archive(str(session.scratch / session.world), 'zip',
                                      world.parent, world.name)
        print(json.dumps(dict(**report, archive=archive, world=str(world))))
    finally:
        session.control_temp.cleanup()
        for path in (session.resources, session.scratch / '.horizon-cache', session.scratch / 'horizon-mods'):
            shutil.rmtree(path, ignore_errors=True)


if __name__ == '__main__':
    main()
