#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Build and verify a private Horizon Mechanical Bearing review world."""
import argparse
import json
from pathlib import Path
import shlex

from bearing_native_checks import Batch
from burner_heat_java_checks import number
from chain_drive_checks import xyz
import contraption_review_stations as stations
from native_check_session import NativeCheckSession, wait_loaded


NAME = 'BearingReview'
WORLD = 'CreateBearingReview'
BEARING = (904, 84, 56)
CONTROL = (905, 83, 56)
WINDMILL = (904, 84, 72)
SAIL_PANEL = [
    ((905, 84, 72), 'sail_frame'), ((905, 83, 72), 'sail_frame'),
    ((905, 85, 72), 'white_sail'), ((905, 84, 71), 'yellow_sail'),
    ((905, 84, 73), 'white_sail'), ((905, 85, 73), 'cyan_sail'),
    ((905, 83, 71), 'blue_sail'), ((905, 85, 71), 'black_sail'),
]
AXIAL_SAIL = (906, 84, 72)
GANTRY_FARM = (904, 83, 183)
GANTRY_FARM_LEVER = (906, 82, 184)
GANTRY_FARM_CHEST = (904, 84, 182)
GANTRY_FARM_CROP = (905, 84, 184)
PISTON_CHESTS = (
    ((919, 82, 180), False, 'minecraft:iron_ingot'),
    ((919, 82, 185), True, 'minecraft:gold_ingot'),
)
DRY_CHEST = 'minecraft:chest[facing=south,type=single,waterlogged=false]'
STICKER = (904, 83, 197)
STICKER_POWER = (903, 83, 197)
STICKER_CLUTCH = (905, 81, 197)
OFFHAND_TARGET = (919, 83, 197)
MEAL_DEPLOYER = (904, 84, 213)
MEAL_CROP = (904, 82, 213)
MEAL_LEVER = (904, 84, 212)
DEPLOYER_FILTER = (910, 84, 213)
PSI_LOADER = (920, 82, 214)
PSI_LOADER_LEVER = (919, 81, 214)
PSI_LOADER_SOURCE = (920, 86, 210)
TWO_HANDS = (903, 82, 231)
TWO_HANDS_LEVER = (904, 81, 231)
TWO_HANDS_CHEST = (903, 83, 232)
TWO_HANDS_WHEAT = (901, 81, 232)
TWO_HANDS_PLANT = (905, 81, 230)
LEAF_ROTOR = (919, 82, 231)
LEAF_LEVER = (918, 81, 231)
LEAF_RING = ((920, 83, 231), (919, 83, 232), (918, 83, 231), (919, 83, 230))


def leaf_landing_station(batch):
    batch.load(LEAF_ROTOR)
    batch.command('fill 914 81 224 925 90 239 minecraft:air')
    batch.command('fill 914 80 222 925 80 239 minecraft:smooth_stone')
    batch.put(LEAF_ROTOR, 'create:mechanical_bearing[facing=up]')
    batch.put((919, 81, 231), 'create:clutch[axis=y,powered=false]')
    batch.put(LEAF_LEVER, 'minecraft:lever[face=wall,facing=west,powered=false]')
    batch.put((919, 80, 231), 'create:creative_motor[facing=up]{ScrollValue:16}')
    batch.put((919, 83, 231), 'minecraft:slime_block')
    batch.put(LEAF_RING[0], 'minecraft:oak_planks')
    stations.sign(batch, (919, 81, 235), ['LEAF LANDING', 'Stop the rotor.', 'The arm clears', 'one leaf block.'])


def two_deployer_station(batch):
    batch.load(TWO_HANDS)
    batch.command('fill 897 81 224 910 90 239 minecraft:air')
    batch.command('fill 897 80 222 910 80 239 minecraft:smooth_stone')
    batch.put(TWO_HANDS, 'create:mechanical_bearing[facing=up]')
    batch.put((903, 81, 231), 'create:clutch[axis=y,powered=true]')
    batch.put(TWO_HANDS_LEVER, 'minecraft:lever[face=wall,facing=east,powered=true]')
    batch.put((903, 80, 231), 'create:creative_motor[facing=up]{ScrollValue:32}')
    for x in range(902, 905):
        batch.put((x, 83, 231), 'minecraft:slime_block')
    for x, item in ((901, 'minecraft:bone_meal'), (905, 'minecraft:oak_sapling')):
        batch.put((x, 83, 231), 'create:deployer[facing=down,axis_along_first=false]'
                  f'{{Mode:"USE",Inventory:[],Filter:{{id:"{item}",count:1}},FilterAmount:64,UpTo:1b}}')
    batch.put(TWO_HANDS_CHEST, DRY_CHEST
              + '{Items:[{Slot:0b,id:"minecraft:oak_sapling",count:2},'
                '{Slot:1b,id:"minecraft:bone_meal",count:24},{Slot:2b,id:"minecraft:stick",count:4}]}')
    batch.put((905, 80, 230), 'minecraft:dirt')
    batch.put((901, 80, 232), 'minecraft:farmland[moisture=7]')
    batch.put(TWO_HANDS_WHEAT, 'minecraft:wheat[age=6]')
    stations.sign(batch, (903, 81, 235), ['TWO DEPLOYERS', 'Release clutch.', 'Sapling + wheat.', 'One shared chest.'])


def farm_input_stations(batch):
    batch.load(MEAL_DEPLOYER)
    batch.command('fill 899 81 207 925 91 221 minecraft:air')
    batch.command('fill 899 80 205 925 80 221 minecraft:smooth_stone')
    batch.put((904, 81, 213), 'minecraft:farmland[moisture=7]')
    batch.put(MEAL_CROP, 'minecraft:wheat[age=4]')
    batch.put(MEAL_DEPLOYER, 'create:deployer[facing=down,axis_along_first=true]'
              '{Mode:"USE",Inventory:[{Slot:0b,id:"minecraft:bone_meal",count:16}]}')
    batch.put((903, 84, 213), 'create:creative_motor[facing=east]{ScrollValue:32}')
    batch.put(MEAL_LEVER, 'minecraft:lever[face=wall,facing=north,powered=true]')
    stations.sign(batch, (904, 81, 217), ['BONE MEAL', 'Release the lever.', 'Watch wheat grow.', 'Check hand stock.'])
    batch.put(DEPLOYER_FILTER, 'create:deployer[facing=down,axis_along_first=true]')
    batch.put((910, 81, 216), DRY_CHEST + '{Items:[{Slot:0b,id:"minecraft:oak_sapling",count:4},'
              '{Slot:1b,id:"minecraft:bone_meal",count:4}]}')
    stations.sign(batch, (910, 81, 217), ['DEPLOYER FILTER', 'Use north/south.', 'Click the slot.', 'Empty to clear.'])

    x, y, z = PSI_LOADER
    interface = 'create:portable_storage_interface'
    batch.put(PSI_LOADER, 'create:mechanical_bearing[facing=up]')
    batch.put((x, y - 1, z), 'create:clutch[axis=y,powered=true]')
    batch.put(PSI_LOADER_LEVER, 'minecraft:lever[face=wall,facing=west,powered=true]')
    batch.put((x, y - 2, z), 'create:creative_motor[facing=up]{ScrollValue:32}')
    for dx in (0, 1, 2):
        batch.put((x + dx, y + 1, z), 'minecraft:slime_block')
    batch.put((x + 2, y + 2, z), interface + '[facing=east]')
    batch.put((x - 1, y + 1, z), DRY_CHEST)
    batch.put((x, y + 2, z - 4), interface + '[facing=south]')
    batch.put((x, y + 3, z - 4), stations.WINDOW_CHUTE)
    batch.put(PSI_LOADER_SOURCE, DRY_CHEST + '{Items:[{Slot:0b,id:"minecraft:oak_sapling",count:16}]}')
    stations.sign(batch, (921, 81, 217), ['LOAD THE ROTOR', 'Release clutch.', 'Watch the chute.', 'Stop; open chest.'])


def adhesive_stations(batch):
    batch.load(STICKER)
    batch.command('fill 899 81 192 925 89 204 minecraft:air')
    batch.command('fill 899 80 192 925 80 204 minecraft:smooth_stone')
    batch.put((904, 80, 197), 'create:creative_motor[facing=up]{ScrollValue:16}')
    batch.put((904, 81, 197), 'create:clutch[axis=y,powered=true]')
    batch.put(STICKER_CLUTCH, 'minecraft:lever[face=wall,facing=east,powered=true]')
    batch.put((904, 82, 197), 'create:mechanical_bearing[facing=up]')
    batch.put(STICKER, 'create:sticker[facing=east,extended=false,powered=false]')
    batch.put((905, 83, 197), 'minecraft:oak_planks')
    batch.command('fill 902 81 197 902 83 197 minecraft:stone_bricks')
    batch.put(STICKER_POWER, 'minecraft:lever[face=wall,facing=east,powered=false]')
    stations.sign(batch, (903, 81, 200), ['STICKER', 'Left lever: pulse.', 'Right: run rotor.', 'Head holds state.'])
    batch.put(OFFHAND_TARGET, 'minecraft:oak_planks')
    batch.put((919, 82, 197), 'minecraft:oak_planks')
    batch.put((917, 81, 200), DRY_CHEST + '{Items:[{Slot:0b,id:"create:super_glue",count:1},{Slot:1b,id:"minecraft:oak_planks",count:16}]}')
    stations.sign(batch, (919, 81, 200), ['OFFHAND GLUE', 'Glue in offhand.', 'Build on the side.', 'Watch the face.'])


def linear_cargo_stations(batch):
    batch.load(GANTRY_FARM)
    batch.command('fill 899 81 175 925 89 188 minecraft:air')
    batch.command('fill 899 80 175 925 80 188 minecraft:smooth_stone')
    batch.command('gamerule minecraft:random_tick_speed 0')
    x, y, z = GANTRY_FARM
    batch.put(GANTRY_FARM, 'create:gantry_carriage[facing=up,axis_along_first=false]')
    for dx, part in enumerate(('start', 'middle', 'end')):
        batch.put((x + dx, y - 1, z), f'create:gantry_shaft[facing=east,part={part},powered=true]')
    batch.put(GANTRY_FARM_LEVER, 'minecraft:lever[face=wall,facing=south,powered=true]')
    batch.put((x - 1, y - 1, z), 'create:creative_motor[facing=east]{ScrollValue:-32}')
    batch.put((x, y + 1, z), 'minecraft:slime_block')
    batch.put((x, y + 1, z + 1), 'create:mechanical_harvester[facing=east,waterlogged=false]')
    batch.put((x + 1, y, z + 1), 'minecraft:farmland[moisture=7]')
    batch.put(GANTRY_FARM_CROP, 'minecraft:wheat[age=7]')
    batch.put(GANTRY_FARM_CHEST, DRY_CHEST + '{Items:[{Slot:5b,id:"minecraft:apple",count:4}]}')
    stations.sign(batch, (904, 81, 186), ['GANTRY HARVEST', 'Release rail stop.', 'Wait for landing.', 'Open the chest.'])

    for base, sticky, item in PISTON_CHESTS:
        x, y, z = base
        stations.piston(batch, base, sticky)
        batch.put((x, y, z - 2), 'create:creative_motor[facing=south]{ScrollValue:-32}')
        batch.put((x - 1, y, z - 1), 'minecraft:lever[face=wall,facing=west,powered=true]')
        batch.put((x + 1, y, z), DRY_CHEST + f'{{Items:[{{Slot:5b,id:"{item}",count:4}}]}}')
        title, result = ('STICKY CARGO', 'Chest comes back.') if sticky else ('PISTON CARGO', 'Chest stays out.')
        stations.sign(batch, (919, 81, z + 1), [title, 'Flip to extend.', 'Flip to retract.', result])


def prepare(session, options):
    batch = Batch()
    batch.load((908, 82, 60))
    batch.command('fill 897 81 49 925 94 78 minecraft:air')
    batch.command('fill 897 80 49 925 80 78 minecraft:smooth_stone')
    batch.command('time set 7250')
    batch.command('weather clear')
    batch.put((904, 82, 56), 'create:creative_motor[facing=up]{ScrollValue:8}')
    batch.put((904, 83, 56), 'create:clutch[axis=y]')
    batch.put(CONTROL, 'minecraft:lever[face=wall,facing=east]')
    batch.put(BEARING, 'create:mechanical_bearing[facing=up]')
    batch.put((904, 85, 56), 'minecraft:slime_block')
    batch.put((905, 85, 56), 'minecraft:oak_log[axis=x]')
    batch.put((903, 85, 56), 'minecraft:oak_planks')
    batch.put((904, 85, 55), 'minecraft:oak_planks')
    batch.put((916, 85, 54), 'create:creative_motor[facing=south]{ScrollValue:8}')
    batch.put((916, 85, 55), 'create:mechanical_bearing[facing=south]')
    batch.put((916, 85, 56), 'minecraft:slime_block')
    batch.put((917, 85, 56), 'minecraft:oak_log[axis=x]')
    batch.put((915, 85, 56), 'minecraft:oak_planks')
    if options.windmill and options.sails:
        batch.put(WINDMILL, 'create:windmill_bearing[facing=east]')
        batch.put((903, 84, 72), 'create:shaft[axis=x]')
        for pos, block in SAIL_PANEL:
            batch.put(pos, f'create:{block}[facing=east]')
        batch.put(AXIAL_SAIL, 'create:orange_sail[facing=east]')
    elif options.windmill:
        batch.put(WINDMILL, 'create:windmill_bearing[facing=up]')
        batch.put((904, 83, 72), 'create:shaft[axis=y]')
        for x in range(902, 907):
            batch.put((x, 85, 72), 'minecraft:slime_block')
            batch.put((x, 85, 71), 'minecraft:white_wool')
            batch.put((x, 85, 73), 'minecraft:light_blue_wool')
    stations.sign(batch, (908, 81, 56), ['MECHANICAL', 'Flip the lever.', 'Ride the rotor.', 'Stand on top.'])
    if options.windmill:
        stations.sign(batch, (907, 81, 74), ['WINDMILL', 'Empty hand:', 'start / stop.', 'Rear shaft: 1 RPM.'])
    if options.farms:
        stations.setup(batch, options.clockwork, options.linear, options.cargo)
    if options.plough or options.deployer or options.materials:
        stations.actor_plaza(batch)
        if options.plough:
            stations.plough_station(batch, options.plough_throw)
        if options.deployer:
            stations.deployer_station(batch)
        if options.materials:
            stations.materials_station(batch)
    if options.glue:
        stations.glue_station(batch)
    if options.upward_saw:
        stations.upward_saw_station(batch)
    if options.chassis:
        stations.chassis_stations(batch)
    if options.rotary_contact:
        stations.rotary_contact_station(batch)
    if options.portable_storage:
        stations.portable_storage_station(batch, options.chute)
    if options.chute:
        stations.chute_station(batch)
    if options.stationary_deployer:
        stations.stationary_deployer_station(batch)
    if options.linear_cargo:
        linear_cargo_stations(batch)
    if options.adhesives:
        adhesive_stations(batch)
    if options.farm_inputs:
        farm_input_stations(batch)
    if options.two_deployers:
        two_deployer_station(batch)
    if options.leaf_landing:
        leaf_landing_station(batch)
    if any((options.plough, options.deployer, options.glue, options.upward_saw,
            options.chassis, options.materials, options.rotary_contact,
            options.portable_storage, options.stationary_deployer, options.linear_cargo,
            options.adhesives, options.farm_inputs, options.two_deployers,
            options.leaf_landing)):
        batch.command('tp @s 909.5 81 61.5')
    batch.tick(30 if options.farms else 12)
    batch.data(BEARING)
    rows = batch.run(session, 'prepare-review')
    assert number({'nbt': rows[0]}, 'Running') == 1, rows


def review(session, options):
    call = session.call

    def command(value):
        return call('command', value)

    def snapshot(pos):
        return {'nbt': ' '.join(command('data get block ' + xyz(pos))['chat'])}

    def interact(pos, face):
        for _ in range(6):
            call('look-at', 'block', *pos, face)
            call('wait', 4)
            hit = call('looking-at')['block']
            if hit and hit['pos'] == list(pos):
                break
        else:
            raise AssertionError(('could not aim at review block', pos, face, hit))
        call('mouse', 'right', 'click')
        call('wait', 6)

    def wait_running(pos, running):
        for _ in range(16):
            data = snapshot(pos)
            if number(data, 'Running', 0) == running:
                return data
            call('wait', 5)
        raise AssertionError((pos, running, data))

    def switch_windmill(running):
        interact(WINDMILL, 'south')
        try:
            return wait_running(WINDMILL, running)
        except AssertionError:
            # A control-socket tap can miss while the client is catching up
            # after a teleport. Retry only after the server state stayed put.
            interact(WINDMILL, 'south')
            return wait_running(WINDMILL, running)

    def wait_block(pos, block):
        for _ in range(16):
            state = call('block', *pos)
            if state['block'] == block:
                return state
            call('wait', 5)
        raise AssertionError((pos, block, state))

    def screenshot(name):
        path = session.scratch / name
        call('screenshot', path)
        assert path.stat().st_size > 1024, path
        return path

    with session:
        wait_loaded(call, [BEARING, CONTROL, (916, 85, 56)])
        assert number(snapshot(BEARING), 'Running') == 1
        command('gamemode survival')
        command('tp @s 904.5 88 56.5')
        call('wait', 35)
        supported = call('state')['player']['position']
        assert abs(supported[1] - 86) < 0.06, supported
        command('tp @s 904.5 88 60.5')
        call('wait', 35)
        control = call('state')['player']['position']
        assert abs(control[1] - 81) < 0.06, control
        command('gamemode creative')
        command('tp @s 908.5 81 56.5')
        call('wait', 6)
        interact(CONTROL, 'east')
        assert number(snapshot(BEARING), 'Running') == 0
        interact(CONTROL, 'east')
        assert number(snapshot(BEARING), 'Running') == 1

        if options.windmill:
            command('tp @s 904.5 81 75.5')
            call('wait', 6)
            wait_loaded(call, [WINDMILL])
            command('clear @s')
            call('select', 9)
            call('inventory')
            windmill_nbt = switch_windmill(1)
            assert number(windmill_nbt, 'LastGenerated') == 1, windmill_nbt
            shaft = snapshot((903, 84, 72) if options.sails else (904, 83, 72))
            assert number(shaft, 'Speed') == 1, shaft
            switch_windmill(0)
            if options.sails:
                for pos, block in SAIL_PANEL:
                    state = call('block', *pos)
                    assert state['block'] == 'create:' + block and 'facing=east' in state['state'], state
                assert call('block', *AXIAL_SAIL)['block'] == 'create:orange_sail'
            else:
                for x in range(902, 907):
                    state = call('block', x, 85, 71)
                    assert 'white_wool' in str(state), state
            switch_windmill(1)

        if options.farms:
            wait_loaded(call, [stations.PISTON, stations.STICKY_PISTON, stations.HARVESTER, stations.SAW])
            for base, sign, block in ((stations.PISTON, (914, 81, 68), 'create:mechanical_piston'),
                                      (stations.STICKY_PISTON, (914, 81, 75), 'create:sticky_mechanical_piston')):
                state = call('block', *base)
                assert state['block'] == block and 'state=extended' in state['state'], state
                assert call('block', base[0] + 4, base[1], base[2])['block'] == 'minecraft:oak_planks'
                assert call('block', *sign)['block'] == 'minecraft:oak_sign'
            for base, lever in ((stations.HARVESTER, stations.HARVESTER_LEVER), (stations.SAW, stations.SAW_LEVER)):
                assert number(snapshot(base), 'Running', 0) == 0, base
                assert 'powered=true' in call('block', *lever)['state']
            if options.cargo:
                assert call('block', *stations.FARM_CHEST)['block'] == 'minecraft:chest'
                assert number(snapshot(stations.CARGO), 'Running', 0) == 1
            if options.clockwork:
                wait_loaded(call, [stations.CLOCK])
                assert call('block', *stations.CLOCK)['block'] == 'create:clockwork_bearing'
                assert number(snapshot(stations.CLOCK), 'Running', 0) == 1
            for pos in stations.SAW_TREE:
                assert call('block', *pos)['block'] == 'minecraft:oak_log'
        if options.linear:
            command('tp @s 911.5 83 102.5')
            wait_loaded(call, [stations.PULLEY, stations.GANTRY, stations.STATIONARY_SAW])
            assert call('block', *stations.PULLEY)['block'] == 'create:rope_pulley'
            assert call('block', 904, 82, 103)['block'] == 'minecraft:oak_log'
            assert call('block', *stations.GANTRY)['block'] == 'create:gantry_carriage'
            assert call('block', *stations.GANTRY_CARGO[0])['block'] == 'minecraft:oak_planks'
            assert call('block', *stations.GANTRY_CARGO[1])['block'] == 'minecraft:spruce_planks'
            assert call('block', *stations.STATIONARY_SAW)['block'] == 'create:mechanical_saw'
            assert call('block', 920, 82, 110)['block'] == 'minecraft:oak_log'
            command('item replace entity @s weapon.mainhand with create:super_glue')
            for plank in stations.GANTRY_CARGO:
                command(f'tp @s 915.5 81 {plank[2]}.5')
                call('wait', 6)
                interact(plank, 'west')
            command('clear @s create:super_glue')
            command('tp @s 920.5 81 107.5')
            interact(stations.GANTRY_LEVER, 'south')
            wait_block((920, 83, 103), 'create:gantry_carriage')
            wait_block((920, 84, 103), 'minecraft:oak_planks')
            wait_block((920, 84, 102), 'minecraft:spruce_planks')
            command('tp @s 917.5 81 107.5')
            interact((917, 82, 104), 'south')
            wait_block(stations.GANTRY, 'create:gantry_carriage')
            wait_block(stations.GANTRY_CARGO[0], 'minecraft:oak_planks')
            wait_block(stations.GANTRY_CARGO[1], 'minecraft:spruce_planks')
            command('tp @s 920.5 81 107.5')
            interact(stations.GANTRY_LEVER, 'south')
            assert 'powered=true' in call('block', *stations.GANTRY_LEVER)['state']
            command('tp @s 917.5 81 107.5')
            interact((917, 82, 104), 'south')
            assert 'powered=false' in call('block', 917, 82, 104)['state']
        command('gamemode spectator')
        command('tp @s 910.5 88 62.5')
        call('look-at', 904.5, 85.1, 56.5)
        call('key', 'f1', 'tap')
        call('wait', 8)
        first = screenshot('bearing-first.png')
        call('wait', 15)
        second = screenshot('bearing-second.png')
        assert first.read_bytes() != second.read_bytes()
        extra = []
        if options.cargo:
            command('tp @s 908.5 87.2 65.5')
            call('look-at', 904.5, 85.5, 62.5)
            call('wait', 12)
            extra.append(str(screenshot('mounted-chest.png')))
        if options.sails:
            command('tp @s 910.5 86.2 75.5')
            call('look-at', 905.5, 84.5, 72.5)
            call('wait', 12)
            extra.append(str(screenshot('colored-sails.png')))
        if options.plough:
            command('tp @s 907.5 86 124.5')
            call('look-at', 906.5, 82.5, 119.5)
            wait_loaded(call, [stations.PLOUGH, stations.PLOUGH_LEVER])
            assert 'powered=true' in call('block', *stations.PLOUGH_LEVER)['state']
            assert call('block', 907, 83, 120)['block'] == 'create:mechanical_plough'
            assert call('block', 904, 83, 117)['block'] == 'minecraft:snow'
            call('wait', 12)
            extra.append(str(screenshot('plough.png')))
        if options.deployer:
            command('tp @s 923.5 85 125.5')
            call('look-at', 922.5, 82.5, 120.5)
            wait_loaded(call, [stations.DEPLOYER, stations.DEPLOYER_LEVER])
            assert 'powered=true' in call('block', *stations.DEPLOYER_LEVER)['state']
            assert call('block', 922, 83, 120)['block'] == 'create:deployer'
            assert 'minecraft:oak_sapling' in snapshot((922, 83, 120))['nbt']
            assert call('block', 920, 83, 121)['block'] == 'minecraft:chest'
            assert call('block', 919, 83, 120)['block'] == 'create:mechanical_saw'
            call('wait', 12)
            extra.append(str(screenshot('deployer.png')))
        if options.glue:
            command('tp @s 906.5 86 140.5')
            call('look-at', 904.5, 82.5, 136.5)
            wait_loaded(call, [stations.GLUE, stations.GLUE_LEVER])
            assert 'powered=true' in call('block', *stations.GLUE_LEVER)['state']
            assert call('block', 905, 83, 136)['block'] == 'minecraft:spruce_planks'
            call('wait', 12)
            extra.append(str(screenshot('glue.png')))
        if options.chassis:
            command('tp @s 912.5 88 155.5')
            call('look-at', 904.5, 83.5, 152.5)
            wait_loaded(call, [stations.LINEAR_CHASSIS, stations.RADIAL_CHASSIS])
            assert call('block', 904, 83, 152)['block'] == 'create:linear_chassis'
            assert call('block', 904, 83, 151)['block'] == 'create:secondary_linear_chassis'
            assert call('block', 920, 83, 152)['block'] == 'create:radial_chassis'
            call('wait', 12)
            extra.append(str(screenshot('chassis.png')))
        if options.materials:
            command('tp @s 923.5 84 125.5')
            wait_loaded(call, [stations.CRAFTING_TABLE])
            assert call('block', *stations.CRAFTING_TABLE)['block'] == 'minecraft:crafting_table'
            assert 'create:brass_sheet' in snapshot((923, 81, 125))['nbt']
        if options.rotary_contact:
            command('tp @s 910.5 86 170.5')
            wait_loaded(call, [stations.ROTARY_CONTACT])
            wait_running(stations.ROTARY_CONTACT, 1)
            assert call('block', 906, 82, 164)['block'] == 'minecraft:stone_bricks'
            call('look-at', 904.5, 82.5, 166.5)
            call('wait', 12)
            extra.append(str(screenshot('rotary-contact.png')))
        if options.portable_storage:
            command('tp @s 925.5 86 166.5')
            wait_loaded(call, [stations.PORTABLE, stations.PORTABLE_DOCK])
            assert call('block', *stations.PORTABLE_DOCK)['block'] == 'create:portable_storage_interface'
            assert call('block', *stations.PORTABLE_OUTPUT)['block'] == 'minecraft:chest'
            assert 'powered=true' in call('block', *stations.PORTABLE_LEVER)['state']
            assert call('block', *stations.PORTABLE_CROP)['state'] == 'minecraft:wheat[age=7]'
            call('look-at', 920.5, 84.0, 164.5)
            call('wait', 12)
            extra.append(str(screenshot('portable-storage.png')))
        if options.chute:
            command('tp @s 919.5 84.5 173.5')
            wait_loaded(call, [stations.CHUTE_OUTPUT])
            x, y, z = stations.CHUTE_OUTPUT
            assert call('block', x, y + 1, z)['block'] == 'create:chute'
            assert call('block', x, y + 2, z)['block'] == 'create:chute'
            call('look-at', x + .5, y + 1.8, z + .5)
            call('wait', 12)
            extra.append(str(screenshot('chutes.png')))
        if options.stationary_deployer:
            command('tp @s 911.5 85 172.5')
            wait_loaded(call, [stations.STATIONARY_DEPLOYER])
            nbt = snapshot(stations.STATIONARY_DEPLOYER)
            assert number(nbt, 'Speed') == 32 and number(nbt, 'Powered') == 1, nbt
            assert 'minecraft:oak_sapling' in nbt['nbt']
            assert call('block', *stations.DEPLOYER_TARGET)['block'] == 'minecraft:air'
            call('look-at', 908.5, 83.5, 172.5)
            call('wait', 12)
            extra.append(str(screenshot('stationary-deployer.png')))
        if options.linear_cargo:
            command('tp @s 909.5 86 187.5')
            wait_loaded(call, [GANTRY_FARM, GANTRY_FARM_CHEST, GANTRY_FARM_CROP])
            assert 'powered=true' in call('block', *GANTRY_FARM_LEVER)['state']
            assert call('block', *GANTRY_FARM_CROP)['state'] == 'minecraft:wheat[age=7]'
            assert 'minecraft:apple' in snapshot(GANTRY_FARM_CHEST)['nbt']
            call('look-at', 905, 83, 183)
            call('wait', 12)
            extra.append(str(screenshot('gantry-harvest-cargo.png')))
            command('tp @s 925.5 87 187.5')
            wait_loaded(call, [base for base, _, _ in PISTON_CHESTS])
            for (x, y, z), _, item in PISTON_CHESTS:
                assert 'state=retracted' in call('block', x, y, z)['state']
                assert item in snapshot((x + 1, y, z))['nbt']
            call('look-at', 919, 82, 182)
            call('wait', 12)
            extra.append(str(screenshot('piston-chest-cargo.png')))
        if options.adhesives:
            command('tp @s 908.5 85 201.5')
            wait_loaded(call, [STICKER, STICKER_POWER, STICKER_CLUTCH, OFFHAND_TARGET])
            assert call('block', *STICKER)['state'] == 'create:sticker[extended=false,facing=east,powered=false]'
            assert 'powered=false' in call('block', *STICKER_POWER)['state']
            assert 'powered=true' in call('block', *STICKER_CLUTCH)['state']
            assert call('block', *OFFHAND_TARGET)['block'] == 'minecraft:oak_planks'
            call('look-at', 904.5, 82.8, 197.5)
            call('wait', 12)
            extra.append(str(screenshot('sticker.png')))
        if options.farm_inputs:
            command('tp @s 909.5 86 216.5')
            wait_loaded(call, [MEAL_DEPLOYER, DEPLOYER_FILTER, PSI_LOADER])
            assert call('block', *MEAL_CROP)['state'] == 'minecraft:wheat[age=4]'
            assert 'minecraft:bone_meal' in snapshot(MEAL_DEPLOYER)['nbt']
            assert 'powered=true' in call('block', *MEAL_LEVER)['state']
            assert call('block', *DEPLOYER_FILTER)['block'] == 'create:deployer'
            call('look-at', 904.5, 83.5, 213.5)
            call('wait', 12)
            extra.append(str(screenshot('deployer-bone-meal.png')))
            command('tp @s 925.5 87 216.5')
            wait_loaded(call, [PSI_LOADER_SOURCE])
            assert 'powered=true' in call('block', *PSI_LOADER_LEVER)['state']
            assert call('block', 920, 85, 210)['block'] == 'create:chute'
            call('look-at', 920.5, 84.5, 212.5)
            call('wait', 12)
            extra.append(str(screenshot('portable-storage-input.png')))
        if options.two_deployers:
            command('tp @s 909.5 86 235.5')
            wait_loaded(call, [TWO_HANDS, TWO_HANDS_CHEST])
            assert 'powered=true' in call('block', *TWO_HANDS_LEVER)['state']
            assert call('block', *TWO_HANDS_WHEAT)['state'] == 'minecraft:wheat[age=6]'
            assert call('block', *TWO_HANDS_PLANT)['block'] == 'minecraft:air'
            assert 'minecraft:bone_meal' in snapshot((901, 83, 231))['nbt']
            assert 'minecraft:oak_sapling' in snapshot((905, 83, 231))['nbt']
            call('look-at', 903.5, 83.5, 231.5)
            call('wait', 12)
            extra.append(str(screenshot('two-moving-deployers.png')))
        if options.leaf_landing:
            command('tp @s 923.5 86 235.5')
            wait_loaded(call, [LEAF_ROTOR, LEAF_LEVER])
            wait_running(LEAF_ROTOR, 1)
            for leaf in LEAF_RING:
                command('setblock ' + xyz(leaf) + ' minecraft:oak_leaves[persistent=true]')
                wait_block(leaf, 'minecraft:oak_leaves')
            call('look-at', 919.5, 83.5, 231.5)
            call('wait', 12)
            extra.append(str(screenshot('leaf-landing.png')))
        call('key', 'f1', 'tap')
        command('gamemode creative')
        if options.glue:
            command('give @s create:super_glue')
        if options.upward_saw:
            command('give @s minecraft:oak_log 8')
            if options.portable_storage:
                command('give @s minecraft:stone 8')
                command('give @s create:andesite_alloy 4')
            if options.chute:
                command('give @s minecraft:stone_brick_wall 4')
        if options.chassis:
            command('give @s create:wrench')
        command('tp @s 909.5 81 61.5')
        call('look-at', 904.5, 85.1, 56.5)
        command('save-all flush')

    return dict(supported=supported, control=control, screenshots=[str(first), str(second), *extra])


def launcher(session):
    folder = session.scratch
    command = [session.game, '--resources', session.resources, '--home', folder / 'home',
               '--world', WORLD, '--name', NAME, '--creative', '--width', '1440',
               '--height', '900', '--render-distance', '4']
    path = folder / 'Open Create Contraptions Review.command'
    path.write_text('#!/bin/zsh\ncd ' + shlex.quote(str(folder)) +
                    ' || exit 1\nexec ' + shlex.join(map(str, command)) + '\n')
    path.chmod(0o755)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('game', 'resources', 'ctl'):
        parser.add_argument('--' + flag, type=Path, required=True)
    parser.add_argument('--create-jar', type=Path)
    parser.add_argument('--windmill', action='store_true')
    parser.add_argument('--farms', action='store_true')
    parser.add_argument('--clockwork', action='store_true')
    parser.add_argument('--linear', action='store_true')
    parser.add_argument('--linear-cargo', action='store_true')
    parser.add_argument('--cargo', action='store_true')
    parser.add_argument('--sails', action='store_true')
    parser.add_argument('--plough', action='store_true')
    parser.add_argument('--deployer', action='store_true')
    parser.add_argument('--glue', action='store_true')
    parser.add_argument('--adhesives', action='store_true')
    parser.add_argument('--farm-inputs', action='store_true')
    parser.add_argument('--two-deployers', action='store_true')
    parser.add_argument('--leaf-landing', action='store_true')
    parser.add_argument('--upward-saw', action='store_true')
    parser.add_argument('--chassis', action='store_true')
    parser.add_argument('--materials', action='store_true')
    parser.add_argument('--rotary-contact', action='store_true')
    parser.add_argument('--portable-storage', action='store_true')
    parser.add_argument('--stationary-deployer', action='store_true')
    parser.add_argument('--chute', action='store_true')
    parser.add_argument('--plough-throw', action='store_true')
    args = parser.parse_args()
    if args.sails and not args.windmill:
        parser.error('--sails requires --windmill')
    if (args.clockwork or args.linear or args.cargo) and not args.farms:
        parser.error('--clockwork, --linear and --cargo require --farms')
    if (args.chute and not args.portable_storage) or (args.plough_throw and not args.plough):
        parser.error('--chute requires --portable-storage; --plough-throw requires --plough')
    session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                 name='bearing-review', graphics=True, world=WORLD, username=NAME)
    print(session.scratch, flush=True)
    prepare(session, args)
    report = review(session, args)
    report['launcher'] = str(launcher(session))
    (session.scratch / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
