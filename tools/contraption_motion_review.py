#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Prepare a private review world for riding rotary and translating structures."""

import argparse
import json
from pathlib import Path
import shlex

from burner_heat_java_checks import items
from chain_drive_checks import xyz
from contraption_review_stations import (
    GANTRY, PISTON, PULLEY, STICKY_PISTON, glue_station, linear_stations, piston, sign,
)
from native_check_session import NativeCheckSession, wait_loaded

HORIZONTAL = (904, 82, 58)
VERTICAL = (919, 84, 58)
STAIR_BEARING = (904, 82, 123)
FILTER_SAW = (918, 82, 124)
FILTER_DEPLOYER = (923, 84, 122)
CRUSHER = (918, 84, 139)
CLUTCHES = (
    (HORIZONTAL, (903, 81, 58), 'west', (904, 83, 58), 'minecraft:slime_block'),
    (VERTICAL, (918, 84, 59), 'south', (920, 84, 58), 'minecraft:slime_block'),
)


class Plaza:
    def __init__(self, call):
        self.call = call

    def command(self, text):
        reply = self.call('command', text)
        chat = ' '.join(reply.get('chat', []))
        assert not any(error in chat.lower() for error in (
            'unknown block', 'invalid value', 'position is not loaded', 'not a block entity',
            'unknown or incomplete command',
        )), reply
        return chat

    def put(self, position, state):
        self.command(f'setblock {xyz(position)} {state}')

    def load(self, position):
        x, y, z = position
        self.command(f'tp @s {x + .5} {y + 2} {z + .5}')
        wait_loaded(self.call, [position])


def build_rotors(plaza):
    plaza.put(HORIZONTAL, 'create:mechanical_bearing[facing=up]')
    plaza.put((904, 81, 58), 'create:clutch[axis=y,powered=true]')
    plaza.put(CLUTCHES[0][1], 'minecraft:lever[face=wall,facing=west,powered=true]')
    plaza.put((904, 80, 58), 'create:creative_motor[facing=up]{ScrollValue:8}')
    plaza.command('fill 901 83 55 907 83 61 minecraft:slime_block')
    plaza.command('fill 901 83 55 901 83 61 minecraft:yellow_wool')
    plaza.command('fill 907 83 55 907 83 61 minecraft:blue_wool')
    sign(plaza, (901, 81, 63), ['HORIZONTAL ROTOR', 'Lever under deck.', 'Board at rest.', 'Walk while turning.'])
    plaza.put(VERTICAL, 'create:mechanical_bearing[facing=east]')
    plaza.put((918, 84, 58), 'create:clutch[axis=x,powered=true]')
    plaza.put(CLUTCHES[1][1], 'minecraft:lever[face=wall,facing=south,powered=true]')
    plaza.put((917, 84, 58), 'create:creative_motor[facing=east]{ScrollValue:-8}')
    plaza.command('fill 920 84 56 921 84 60 minecraft:slime_block')
    plaza.command('fill 920 84 60 921 84 60 minecraft:oak_planks')
    sign(plaza, (918, 81, 63), ['VERTICAL ROTOR', 'Lever on clutch.', 'Try the oak tip.', 'Catch floor below.'])


def check_rotors(plaza):
    for pivot, lever, facing, payload, block in CLUTCHES:
        plaza.put(lever, f'minecraft:lever[face=wall,facing={facing},powered=false]')
        plaza.call('wait', 10)
        assert 'Running: 1b' in plaza.command(f'data get block {xyz(pivot)}'), pivot
        assert plaza.call('block', *payload)['block'] == 'minecraft:air', payload
        plaza.put(lever, f'minecraft:lever[face=wall,facing={facing},powered=true]')
        plaza.call('wait', 8)
        assert plaza.call('block', *payload)['block'] == block, payload


def build_release_stations(plaza):
    plaza.load((911, 81, 123))
    plaza.put(STAIR_BEARING, 'create:mechanical_bearing[facing=up]')
    plaza.put((904, 81, 123), 'create:clutch[axis=y,powered=true]')
    plaza.put((903, 81, 123), 'minecraft:lever[face=wall,facing=west,powered=true]')
    plaza.put((904, 80, 123), 'create:creative_motor[facing=up]{ScrollValue:4}')
    plaza.put((904, 83, 123), 'minecraft:slime_block')
    plaza.put((905, 83, 123), 'minecraft:oak_stairs[facing=north,half=bottom,shape=straight,waterlogged=false]')
    sign(plaza, (906, 81, 126), ['STAIR RIDER', 'Try each tread.', 'Lever under stair.', 'Turn off flight.'])

    plaza.put(FILTER_SAW, 'create:mechanical_saw[facing=up,axis_along_first=true,flipped=false]')
    plaza.put(FILTER_DEPLOYER, 'create:deployer[facing=down,axis_along_first=true]')
    sign(plaza, (918, 81, 126), ['SAW FILTER', 'Aim at top slot.', 'Click with item.', 'Aim again.'])
    sign(plaza, (923, 81, 125), ['DEPLOYER FILTER', 'Aim at side slot.', 'Click with item.', 'Aim again.'])
    plaza.command('give @s minecraft:oak_planks 16')
    plaza.command('give @s minecraft:oak_sapling 16')

    plaza.load((911, 81, 139))
    x, y, z = CRUSHER
    for i, part in enumerate(('start', 'middle', 'middle', 'middle', 'end'), -2):
        plaza.put((x+i, y-1, z), f'create:belt[facing=east,slope=horizontal,part={part}]')
    for side, rpm in ((-1, -64), (1, 96)):
        plaza.put((x+side, y, z), 'create:crushing_wheel[axis=z]')
        plaza.put((x+side, y, z-1), f'create:creative_motor[facing=south]{{ScrollValue:{rpm}}}')
    plaza.put((x-2, y-1, z-1), 'create:clutch[axis=z,powered=true]')
    plaza.put((x-3, y-1, z-1), 'minecraft:lever[face=wall,facing=west,powered=true]')
    plaza.put((x-2, y-1, z-2), 'create:creative_motor[facing=south]{ScrollValue:-32}')
    plaza.call('wait', 20)
    plaza.put((x, y+1, z), 'create:chute[facing=down,shape=normal,waterlogged=false]')
    plaza.put((x, y+2, z), 'minecraft:hopper[facing=down]')
    sign(plaza, (918, 81, 142), ['CRUSHER TO BELT', 'Cobble in hopper.', 'Wait for gravel.', 'Lever starts belt.'])
    plaza.command('give @s minecraft:cobblestone 32')


def check_crusher_to_belt(plaza):
    x, y, z = CRUSHER
    source = xyz(CRUSHER)
    belt = xyz((x-2, y-1, z))
    lever = (x-3, y-1, z-1)

    def inventory(pos):
        data = plaza.command(f'data get block {pos}')
        return items(data, 'Inventory') if 'Inventory:' in data else {}

    plaza.command(f'item replace block {x} {y+2} {z} container.0 with minecraft:cobblestone')
    for _ in range(28):
        plaza.call('wait', 12)
        before = inventory(source)
        if before.get('minecraft:gravel') == 1:
            break
    else:
        raise AssertionError(('Crusher did not hold gravel over the stopped Belt', before))
    plaza.put(lever, 'minecraft:lever[face=wall,facing=west,powered=false]')
    for _ in range(8):
        plaza.call('wait', 3)
        crusher_items = inventory(source)
        belt_items = inventory(belt)
        if not crusher_items and belt_items.get('minecraft:gravel') == 1:
            break
    else:
        raise AssertionError(('Stopped Belt did not accept the gravel when powered', crusher_items, belt_items))
    plaza.put(lever, 'minecraft:lever[face=wall,facing=west,powered=true]')


def prepare(session, release_audit):
    with session:
        plaza = Plaza(session.call)
        plaza.command('gamemode creative')
        plaza.command('gamerule minecraft:do_mob_spawning false')
        plaza.command('gamerule minecraft:do_weather_cycle false')
        plaza.command('time set noon')
        for z in (58, 70, 82, 94, 106, 118, 132, 139):
            plaza.load((911, 81, z))
            plaza.command(f'fill 896 81 {z-7} 927 94 {z+7} minecraft:air')
            plaza.command(f'fill 896 80 {z-7} 927 80 {z+7} minecraft:smooth_stone')
        build_rotors(plaza)
        piston(plaza, PISTON, False)
        piston(plaza, STICKY_PISTON, True)
        plaza.command('fill 905 80 68 905 80 78 minecraft:yellow_concrete')
        sign(plaza, (914, 81, 68), ['PISTON', 'Lever reverses.', 'Pushes the block.', 'Watch the poles.'])
        sign(plaza, (914, 81, 75), ['STICKY PISTON', 'Lever reverses.', 'Pulls the block.', 'Compare both.'])
        linear_stations(plaza)
        sign(plaza, (919, 81, 106), ['GANTRY', 'Right: rail stop.', 'Left: reverse.', 'Glue both planks.'])
        glue_station(plaza)
        if release_audit:
            build_release_stations(plaza)
        plaza.command('give @s create:super_glue')
        plaza.command('give @s create:wrench')
        plaza.command('give @s create:goggles')

        plaza.command('tp @s 911.5 83 62.5')
        wait_loaded(session.call, [HORIZONTAL, VERTICAL, PISTON, STICKY_PISTON])
        check_rotors(plaza)
        session.call('look-at', 908, 83, 58)
        for pos, block in ((PISTON, 'create:mechanical_piston'),
                           (STICKY_PISTON, 'create:sticky_mechanical_piston')):
            assert session.call('block', *pos)['block'] == block, pos
        session.call('save')
        capture(plaza, (911.5, 92, 71.5), (911.5, 83, 58.5), session.scratch / 'rotors.png')

        session.restart()
        plaza = Plaza(session.call)
        plaza.load((911, 81, 103))
        wait_loaded(session.call, [PULLEY, GANTRY])
        assert session.call('block', *PULLEY)['block'] == 'create:rope_pulley'
        assert session.call('block', *GANTRY)['block'] == 'create:gantry_carriage'
        capture(plaza, (911.5, 90, 109.5), (912, 83, 103), session.scratch / 'linear.png')
        if release_audit:
            plaza.load((911, 81, 132))
            checks = ((CRUSHER, 'create:crushing_wheel_controller'),
                      (STAIR_BEARING, 'create:mechanical_bearing'),
                      (FILTER_SAW, 'create:mechanical_saw'),
                      (FILTER_DEPLOYER, 'create:deployer'))
            wait_loaded(session.call, [pos for pos, _ in checks])
            for pos, block in checks:
                assert session.call('block', *pos)['block'] == block, pos
            check_crusher_to_belt(plaza)
            capture(plaza, (921.5, 91, 146.5), (918.5, 84, 139.5), session.scratch / 'crusher-belt.png')
            plaza.command('tp @s 911.5 81 128.5')
            session.call('look-at', 918.5, 83, 124.5)
        else:
            plaza.command('tp @s 911.5 81 64.5')
            session.call('look-at', 907, 84, 58)
        session.call('save')


def capture(plaza, camera, target, output):
    plaza.command('gamemode spectator')
    plaza.command('tp @s ' + xyz(camera))
    plaza.call('look-at', *target)
    plaza.call('key', 'f1', 'tap')
    plaza.call('wait', 5)
    plaza.call('screenshot', output)
    plaza.call('key', 'f1', 'tap')
    plaza.command('gamemode creative')


def launch_files(session, release_audit):
    play = session.scratch / 'Play.command'
    play.write_text(
        '#!/bin/bash\nset -euo pipefail\ncd "$(dirname "$0")"\n'
        'export HORIZON_HOME="$PWD/home" HORIZON_LAUNCHER_HOME="$PWD/launcher"\n'
        'export XDG_CONFIG_HOME="$PWD/config" XDG_DATA_HOME="$PWD/data"\n'
        'export HORIZON_LAUNCHER_NO_SELF_UPDATE=1\n'
        f'exec {shlex.quote(str(session.game))} --resources "$PWD/resources" '
        f'--world {session.world} --creative --name BearingReview --render-distance 4 "$@"\n'
    )
    play.chmod(0o755)
    review = (
        '# Moving structures\n\n'
        'Open Play.command. Creative flight is useful to reach the decks. '
        'Turn flight off before checking whether a deck carries you.\n\n'
        '| Station | Coordinates | What to try |\n'
        '| --- | --- | --- |\n'
        '| Horizontal rotor | 904 82 58 | Stand on the deck and have it turn. Walk across the colour bands. |\n'
        '| Vertical rotor | 919 84 58 | Stand on the rising oak tip near 921 85 60. '
        'Watch it lift you, then step off onto the floor. |\n'
        '| Mechanical pistons | 919 83 68 and 919 83 75 | Reverse the two gearshifts. '
        'Check the pole and which piston retrieves the wood. |\n'
        '| Rope pulley and gantry | 904 85 103 and 918 83 103 | Release each stop lever, '
        'then reverse the drive. |\n'
        '| Super Glue | 904 82 136 | Glue the two wooden blocks, then release the clutch. '
        'The extra block should rotate with the bearing. |\n'
    )
    if release_audit:
        review += (
            '| Stair rider | 904 82 123 | Ride the lower and upper treads of the oak stair separately. |\n'
            '| Ghost filters | 918 82 124 and 923 84 122 | Aim at the Saw top and Deployer side slots. '
            'Check the outline and the hint before and after setting an ordinary item. |\n'
            '| Crusher to Belt | 918 84 139 | Put cobblestone in the hopper above the wheels. '
            'Look between the wheels from the side for cobblestone fragments while the stack is crushed. '
            'The fragments stop when the gravel is ready. Occasional crit sparks can still appear. '
            'Start the stopped Belt with the lever and watch the stored output transfer. |\n'
        )
    (session.scratch / 'REVIEW.md').write_text(review)
    print(json.dumps({'play': str(play), 'world': session.world, 'restart_verified': True}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'resources', 'ctl'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--jar', type=Path)
    parser.add_argument('--release-audit', action='store_true')
    args = parser.parse_args()
    name, world = ('release-audit', 'CreateReleaseAudit') if args.release_audit else (
        'motion-review', 'CreateMotionReview')
    session = NativeCheckSession(args.game, args.resources, args.ctl, args.jar,
                                 name=name, world=world,
                                 size=(1280, 720), username='BearingReview')
    print(session.scratch, flush=True)
    prepare(session, args.release_audit)
    launch_files(session, args.release_audit)


if __name__ == '__main__':
    main()
