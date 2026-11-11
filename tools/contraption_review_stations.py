# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Build the actuator and farm stations in the disposable contraption world."""
import json

from chain_drive_checks import xyz

PISTON = (919, 83, 68)
PISTON_LEVER = (918, 83, 67)
STICKY_PISTON = (919, 83, 75)
STICKY_LEVER = (918, 83, 74)
HARVESTER = (904, 82, 88)
HARVESTER_LEVER = (905, 81, 88)
SAW = (919, 82, 88)
SAW_LEVER = (920, 81, 88)
CLOCK = (919, 85, 70)
CARGO = (904, 84, 62)
FARM_CHEST = (904, 83, 87)
PULLEY = (904, 85, 103)
PULLEY_CLUTCH = (903, 85, 104)
GANTRY = (918, 83, 103)
GANTRY_LEVER = (920, 82, 104)
GANTRY_CARGO = ((918, 84, 103), (918, 84, 102))
STATIONARY_SAW = (919, 82, 110)
STATIONARY_SAW_LEVER = (918, 82, 111)
PLOUGH = (904, 82, 120)
PLOUGH_LEVER = (905, 81, 120)
DEPLOYER = (920, 82, 120)
DEPLOYER_LEVER = (921, 81, 120)
GLUE = (904, 82, 136)
GLUE_LEVER = (905, 81, 136)
UPWARD_SAW = (920, 82, 136)
LINEAR_CHASSIS = (904, 82, 152)
RADIAL_CHASSIS = (920, 82, 152)
ROTARY_CONTACT = (904, 81, 166)
PORTABLE = (920, 82, 166)
PORTABLE_LEVER = (919, 81, 166)
PORTABLE_DOCK = (920, 84, 162)
PORTABLE_OUTPUT = (920, 82, 162)
PORTABLE_CROP = (923, 83, 165)
STATIONARY_DEPLOYER = (908, 84, 172)
DEPLOYER_LOCK = (908, 84, 173)
DEPLOYER_TARGET = (908, 82, 172)
WINDOW_CHUTE = 'create:chute[facing=down,shape=window,waterlogged=false]'
CHUTE_OUTPUT = (924, 81, 171)
CRAFTING_TABLE = (924, 81, 125)
SAW_TREE = ((920, 83, 87), (920, 84, 87), (920, 85, 87))


def sign(batch, pos, lines, rotation=0):
    batch.put(pos, f'minecraft:oak_sign[rotation={rotation}]')
    messages = json.dumps(lines, ensure_ascii=False)
    batch.command(f'data merge block {xyz(pos)} {{front_text:{{messages:{messages},color:"black"}},is_waxed:1b}}')


def piston(batch, pos, sticky):
    x, y, z = pos
    kind = 'sticky_mechanical_piston' if sticky else 'mechanical_piston'
    batch.put(pos, f'create:{kind}[facing=east,axis_along_first=false,state=retracted]')
    for i in (-3, -2, -1):
        batch.put((x + i, y, z), 'create:piston_extension_pole[facing=east]')
    batch.put((x + 1, y, z), 'minecraft:oak_planks')
    batch.put((x, y, z - 1), 'create:gearshift[axis=z]')
    batch.put((x - 1, y, z - 1), 'minecraft:lever[face=wall,facing=west]')
    batch.put((x, y, z - 2), 'create:creative_motor[facing=south]{ScrollValue:-64}')


def farm_drive(batch, pos):
    x, y, z = pos
    batch.put(pos, 'create:mechanical_bearing[facing=up]')
    batch.put((x, y - 1, z), 'create:clutch[axis=y]')
    batch.put((x + 1, y - 1, z), 'minecraft:lever[face=wall,facing=east,powered=true]')
    batch.put((x, y - 2, z), 'create:creative_motor[facing=up]{ScrollValue:32}')


def setup(batch, clockwork=False, linear=False, cargo=False):
    batch.load((911, 82, 82))
    batch.command('fill 897 81 79 925 90 94 minecraft:air')
    batch.command('fill 897 80 79 925 80 94 minecraft:smooth_stone')
    batch.command('gamerule minecraft:random_tick_speed 0')
    piston(batch, PISTON, False)
    piston(batch, STICKY_PISTON, True)
    sign(batch, (914, 81, 68), ['PISTON', 'Lever reverses', 'the stroke.', 'Pushes only.'], 4)
    sign(batch, (914, 81, 75), ['STICKY PISTON', 'Lever reverses', 'the stroke.', 'Pulls the block.'], 4)
    farm_drive(batch, HARVESTER)
    hx, hy, hz = HARVESTER
    for i in range(3):
        batch.put((hx + i, hy + 1, hz), 'minecraft:slime_block')
    batch.put((hx + 3, hy + 1, hz), 'create:mechanical_harvester[facing=north]')
    if cargo:
        batch.put(FARM_CHEST, 'minecraft:chest[facing=south]{Items:[{Slot:5b,id:"minecraft:apple",count:4}]}')
        cx, cy, cz = CARGO
        batch.put(CARGO, 'create:mechanical_bearing[facing=up]')
        batch.put((cx, cy + 1, cz), 'minecraft:slime_block')
        batch.put((cx + 1, cy + 1, cz), 'minecraft:chest[facing=east]{Items:[{Slot:0b,id:"minecraft:stick",count:3}]}')
        batch.put((cx, cy - 1, cz), 'create:clutch[axis=y]')
        batch.put((cx + 1, cy - 1, cz), 'minecraft:lever[face=wall,facing=east]')
        batch.put((cx, cy - 2, cz), 'create:creative_motor[facing=up]{ScrollValue:8}')
        sign(batch, (906, 81, 65), ['CARGO', 'Stop the rotor.', 'Open the chest', 'after landing.'])
    for dx, dz, crop, age in [(3, -1, 'wheat', 7), (2, -2, 'carrots', 7),
                             (1, -3, 'potatoes', 7), (0, -3, 'beetroots', 3),
                             (-1, -3, 'wheat', 3)]:
        batch.put((hx + dx, hy, hz + dz), 'minecraft:farmland[moisture=7]')
        batch.put((hx + dx, hy + 1, hz + dz), f'minecraft:{crop}[age={age}]')
    harvest_note = ['HARVESTER', 'Release clutch.', 'Stop to open', 'the cargo chest.'] if cargo else [
        'HARVESTER', 'Release clutch.', 'Watch ripe crops', 'get replanted.']
    sign(batch, (906, 81, 92), harvest_note)
    farm_drive(batch, SAW)
    sx, sy, sz = SAW
    batch.put((sx, sy + 1, sz), 'minecraft:slime_block')
    batch.put((sx + 1, sy + 1, sz), 'create:mechanical_saw[facing=north,axis_along_first=false,flipped=false]')
    for pos in SAW_TREE:
        batch.put(pos, 'minecraft:oak_log[axis=y]')
    batch.put((921, 85, 87), 'minecraft:oak_leaves[distance=1,persistent=true]')
    batch.put((923, 84, 87), 'minecraft:oak_log[axis=y]')
    sign(batch, (921, 81, 92), ['MOVING SAW', 'Release clutch.', 'Cuts the tree', 'beside the saw.'])
    if clockwork:
        batch.put(CLOCK, 'create:clockwork_bearing[facing=east]')
        batch.put((920, 85, 70), 'minecraft:oak_log[axis=y]')
        batch.put((921, 85, 70), 'minecraft:stripped_oak_log[axis=z]')
        batch.put((918, 85, 70), 'create:creative_motor[facing=east]{ScrollValue:32}')
        sign(batch, (915, 81, 71), ['CLOCKWORK', 'Two moving hands.', 'Empty hand:', 'stop / start.'], 4)
    if linear:
        linear_stations(batch)
    batch.command('tp @s 909.5 81 61.5')

def linear_stations(batch):
    batch.load((911, 82, 102))
    batch.command('fill 897 81 95 925 94 114 minecraft:air')
    batch.command('fill 897 80 95 925 80 114 minecraft:smooth_stone')
    batch.put(PULLEY, 'create:rope_pulley[axis=x]')
    batch.put((904, 82, 103), 'minecraft:oak_log[axis=y]')
    batch.put((903, 85, 103), 'create:clutch[axis=x]')
    batch.put(PULLEY_CLUTCH, 'minecraft:lever[face=wall,facing=south,powered=true]')
    batch.put((902, 85, 103), 'create:gearshift[axis=x]')
    batch.put((902, 85, 104), 'minecraft:lever[face=wall,facing=south]')
    batch.put((901, 85, 103), 'create:creative_motor[facing=east]{ScrollValue:32}')
    sign(batch, (905, 81, 105), ['ROPE PULLEY', 'Right: clutch.', 'Left: reverse.', 'Picks up the log.'])
    for x, part in ((918, 'start'), (919, 'middle'), (920, 'end')):
        batch.put((x, 82, 103), f'create:gantry_shaft[facing=east,part={part},powered=true]')
    batch.put(GANTRY_LEVER, 'minecraft:lever[face=wall,facing=south,powered=true]')
    batch.put(GANTRY, 'create:gantry_carriage[facing=up,axis_along_first=false]')
    batch.put(GANTRY_CARGO[0], 'minecraft:oak_planks')
    batch.put(GANTRY_CARGO[1], 'minecraft:spruce_planks')
    batch.put((917, 82, 103), 'create:gearshift[axis=x]')
    batch.put((917, 82, 104), 'minecraft:lever[face=wall,facing=south]')
    batch.put((916, 82, 103), 'create:creative_motor[facing=east]{ScrollValue:-32}')
    sign(batch, (919, 81, 106), ['GANTRY', 'Right: rail stop.', 'Left: reverse.', 'Two glued planks.'])
    batch.put(STATIONARY_SAW, 'create:mechanical_saw[facing=east]')
    batch.put((918, 82, 110), 'create:clutch[axis=x]')
    batch.put(STATIONARY_SAW_LEVER, 'minecraft:lever[face=wall,facing=south,powered=true]')
    batch.put((917, 82, 110), 'create:creative_motor[facing=east]{ScrollValue:64}')
    for y in range(82, 85):
        batch.put((920, y, 110), 'minecraft:oak_log[axis=y]')
    batch.put((921, 84, 110), 'minecraft:oak_leaves[persistent=true,distance=1]')
    sign(batch, (921, 81, 113), ['STATIONARY SAW', 'Release clutch.', 'Cuts the trunk', 'and canopy.'])


def actor_plaza(batch):
    batch.load(PLOUGH)
    batch.command('fill 897 81 115 925 94 126 minecraft:air')
    batch.command('fill 897 80 115 925 80 126 minecraft:smooth_stone')


def plough_station(batch, mob=False):
    farm_drive(batch, PLOUGH)
    x, y, z = PLOUGH
    for i in range(3):
        batch.put((x + i, y + 1, z), 'minecraft:slime_block')
    batch.put((x + 3, y + 1, z), 'create:mechanical_plough[facing=north]')
    for dx, dz, soil in (
        (3, -1, 'grass_block'), (2, -2, 'coarse_dirt'),
        (1, -3, 'rooted_dirt'), (0, -3, 'stone'), (-1, -3, 'farmland[moisture=7]'),
    ):
        batch.put((x + dx, y, z + dz), 'minecraft:' + soil)
    batch.put((x, y + 1, z - 3), 'minecraft:snow[layers=3]')
    batch.put((x - 1, y + 1, z - 3), 'minecraft:wheat[age=3]')
    if mob:
        batch.put((x + 4, y, z - 1), 'minecraft:grass_block')
        batch.command(f'summon minecraft:pig {x + 4.15} {y + 1} {z - .5} '
                      '{NoAI:1b,PersistenceRequired:1b,Tags:["create_review_plough"]}')
    sign(batch, (906, 81, 123), ['PLOUGH', 'Release clutch.', 'Tills soil and', 'clears snow.'])


def deployer_station(batch):
    farm_drive(batch, DEPLOYER)
    x, y, z = DEPLOYER
    batch.command('fill 917 80 117 923 80 123 minecraft:dirt')
    batch.put((x + 1, y - 2, z - 1), 'minecraft:stone')
    batch.put((x + 1, y - 1, z + 2), 'minecraft:oak_sapling')
    for i in range(2):
        batch.put((x + i, y + 1, z), 'minecraft:slime_block')
    batch.put((x + 2, y + 1, z), 'create:deployer[facing=down,axis_along_first=false]'
              '{Mode:"USE",Filter:{id:"minecraft:oak_sapling",count:1},FilterAmount:64,UpTo:1b,'
              'Inventory:[{Slot:0b,id:"minecraft:oak_sapling",count:2}]}')
    batch.put((x, y + 1, z + 1), 'minecraft:chest[facing=north]{Items:['
              '{Slot:0b,id:"minecraft:oak_log",count:4},'
              '{Slot:3b,id:"minecraft:oak_sapling",count:3},'
              '{Slot:8b,id:"minecraft:oak_sapling",count:2}]}')
    batch.put((x - 1, y + 1, z), 'create:mechanical_saw[facing=south,axis_along_first=false,flipped=false]')
    for dy in range(1, 4):
        batch.put((x - 1, y + dy, z + 1), 'minecraft:oak_log[axis=y]')
    sign(batch, (924, 81, 123), ['TREE FARM', 'Release clutch.', 'Plants and cuts.', 'Stop for chest.'])


def glue_station(batch):
    batch.load(GLUE)
    batch.command('fill 898 81 130 911 94 142 minecraft:air')
    batch.command('fill 898 80 130 911 80 142 minecraft:smooth_stone')
    farm_drive(batch, GLUE)
    x, y, z = GLUE
    batch.put((x, y + 1, z), 'minecraft:oak_planks')
    batch.put((x + 1, y + 1, z), 'minecraft:spruce_planks')
    sign(batch, (907, 81, 139), ['SUPER GLUE', 'Click two planks', 'with glue. Start', 'with the lever.'])


def upward_saw_station(batch):
    batch.load(UPWARD_SAW)
    batch.command('fill 914 81 130 927 94 142 minecraft:air')
    batch.command('fill 914 80 130 927 80 142 minecraft:smooth_stone')
    x, y, z = UPWARD_SAW
    batch.put(UPWARD_SAW, 'create:mechanical_saw[facing=up,axis_along_first=false]')
    batch.put((x, y, z - 1), 'create:creative_motor[facing=south]{ScrollValue:32}')
    sign(batch, (923, 81, 139), ['UPWARD SAW', 'Drop an oak log.', 'Strip it, then', 'cut into planks.'])


def chassis_stations(batch):
    batch.load(LINEAR_CHASSIS)
    batch.command('fill 898 81 146 926 94 158 minecraft:air')
    batch.command('fill 898 80 146 926 80 158 minecraft:smooth_stone')
    farm_drive(batch, LINEAR_CHASSIS)
    x, y, z = LINEAR_CHASSIS
    batch.put((x, y + 1, z), 'create:linear_chassis[axis=x,sticky_top=true]{ScrollValue:2}')
    for dx in (1, 2, 3):
        batch.put((x + dx, y + 1, z), 'minecraft:oak_planks')
    batch.put((x, y + 1, z - 1), 'create:secondary_linear_chassis[axis=x]')
    sign(batch, (906, 81, 155), ['LINEAR CHASSIS', 'Hold use: Wrench', 'Set the range.', 'Range 2: two move.'])
    farm_drive(batch, RADIAL_CHASSIS)
    x, y, z = RADIAL_CHASSIS
    batch.put((x, y + 1, z), 'create:radial_chassis[axis=y,sticky_east=true]{ScrollValue:2}')
    for dx, dz in ((1, 0), (2, 0), (2, 1), (2, 2)):
        batch.put((x + dx, y + 1, z + dz), 'minecraft:oak_planks')
    sign(batch, (922, 81, 155), ['RADIAL CHASSIS', 'Hold use: Wrench', 'Set the radius.', 'Far plank stays.'])


def materials_station(batch):
    batch.load(CRAFTING_TABLE)
    batch.put(CRAFTING_TABLE, 'minecraft:crafting_table')
    items = (
        ('minecraft:paper', 4), ('minecraft:sand', 4),
        ('minecraft:quartz', 4), ('minecraft:redstone', 32),
        ('create:iron_sheet', 4), ('create:brass_sheet', 16),
        ('create:andesite_casing', 4), ('create:andesite_alloy', 4),
    )
    nbt = ','.join(f'{{Slot:{slot}b,id:"{item}",count:{count}}}'
                   for slot, (item, count) in enumerate(items))
    batch.put((923, 81, 125), 'minecraft:chest[facing=south]{Items:[' + nbt + ']}')
    sign(batch, (925, 81, 125), ['CRAFT DEPLOYER', 'Chest: materials.', 'Polish Rose Quartz', 'with Sand Paper.'])


def rotary_contact_station(batch):
    batch.load(ROTARY_CONTACT)
    batch.command('fill 899 81 161 913 89 174 minecraft:air')
    batch.command('fill 899 80 161 913 80 174 minecraft:smooth_stone')
    batch.command('fill 906 80 159 910 80 160 minecraft:smooth_stone')
    x, y, z = ROTARY_CONTACT
    batch.put((x, y - 1, z), 'create:creative_motor[facing=up]{ScrollValue:16}')
    batch.put(ROTARY_CONTACT, 'create:mechanical_bearing[facing=up]')
    batch.put((x, y + 1, z), 'minecraft:slime_block')
    batch.put((x + 1, y + 1, z), 'minecraft:stone')
    batch.command(f'fill {x} {y} {z - 2} {x + 3} {y + 2} {z - 2} minecraft:stone_bricks')
    sign(batch, (906, 81, 169), ['ROTOR CONTACT', 'Walk between', 'rotor and wall.', 'Try in Survival.'])


def portable_storage_station(batch, chute=False):
    batch.load(PORTABLE)
    batch.command('fill 914 81 159 925 90 174 minecraft:air')
    batch.command('fill 914 80 159 925 80 174 minecraft:smooth_stone')
    x, y, z = PORTABLE
    block = 'create:portable_storage_interface'
    batch.put(PORTABLE, 'create:mechanical_bearing[facing=up]')
    batch.put((x, y - 1, z), 'create:clutch[axis=y]')
    batch.put(PORTABLE_LEVER, 'minecraft:lever[face=wall,facing=west,powered=true]')
    batch.put((x, y - 2, z), 'create:creative_motor[facing=up]{ScrollValue:32}')
    for dx in (0, 1, 2):
        batch.put((x + dx, y + 1, z), 'minecraft:slime_block')
    batch.put((x + 2, y + 2, z), f'{block}[facing=east]')
    batch.put((x + 3, y + 1, z), 'create:mechanical_harvester[facing=north]')
    batch.put((x - 1, y + 1, z), 'minecraft:chest[facing=north]')
    for (px, py, pz), age in [(PORTABLE_CROP, 7), ((x + 1, y + 1, z - 3), 3)]:
        batch.put((px, py - 1, pz), 'minecraft:farmland[moisture=7]')
        batch.put((px, py, pz), f'minecraft:wheat[age={age}]')
    batch.put(PORTABLE_DOCK, f'{block}[facing=south]')
    batch.put((x, y + 1, z - 4), WINDOW_CHUTE if chute else 'minecraft:hopper[facing=down]')
    batch.put((x, y - 1, z - 4), 'minecraft:smooth_stone')
    batch.put(PORTABLE_OUTPUT, 'minecraft:chest[facing=north]')
    for dz in (5, 6):
        batch.put((x, y + 1, z - dz), 'minecraft:stone')
    batch.put((x, y + 2, z - 5), 'minecraft:comparator[facing=south]')
    batch.put((x, y + 2, z - 6), 'minecraft:redstone_wire')
    sign(batch, (917, 81, 169), ['HARVEST & DOCK', 'Release clutch.', 'Watch it harvest.', 'Check dock chest.'])


def chute_station(batch):
    batch.load(CHUTE_OUTPUT)
    x, y, z = CHUTE_OUTPUT
    for dy in (0, 3):
        batch.put((x, y + dy, z), 'minecraft:chest[facing=west]')
    for dy in (1, 2):
        batch.put((x, y + dy, z), WINDOW_CHUTE)
    sign(batch, (922, 81, 173), ['CHUTES', 'Fill top chest.', 'Watch the windows.', 'Open bottom chest.'])


def stationary_deployer_station(batch):
    batch.load(STATIONARY_DEPLOYER)
    batch.command('fill 905 80 170 912 80 174 minecraft:smooth_stone')
    batch.command('fill 906 81 170 910 89 174 minecraft:air')
    x, y, z = STATIONARY_DEPLOYER
    batch.put((x, y - 3, z), 'minecraft:dirt')
    batch.put(STATIONARY_DEPLOYER, 'create:deployer[facing=down,axis_along_first=true]'
              '{Mode:"USE",Inventory:[{Slot:0b,id:"minecraft:oak_sapling",count:4}]}')
    batch.put((x - 1, y, z), 'create:creative_motor[facing=east]{ScrollValue:32}')
    batch.put(DEPLOYER_LOCK, 'minecraft:lever[face=wall,facing=south,powered=true]')
    sign(batch, (910, 81, 173), ['DEPLOYER', 'Release the lever.', 'It plants one oak.', 'Clear to repeat.'])
