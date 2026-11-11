#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Capture the same stationary sapling poses in pinned Create and native Horizon."""

import argparse
import json
from pathlib import Path
import shutil
import time

from chain_drive_checks import Original, xyz
from common import PINS
from deployer_stationary_native_checks import snapshot
from native_check_session import NativeCheckSession, wait_loaded
import reference_java as java

DEPLOYER = (1131, 104, 100)
MOTOR = (1130, 104, 100)
LOCK = (1132, 104, 100)
SOIL = (1131, 101, 100)
DOWN_VIEW = (1133.7, 101, 103.6)
UP_VIEW = (1133.7, 104, 103.6)
SAPLING = 'minecraft:oak_sapling'
AIR = 'minecraft:air'
FOV = 40
CASES = (
    dict(name='01-down-empty', facing='down', stock=0, state='WAITING', rpm=0),
    dict(name='02-down-fixed', facing='down', stock=2, state='WAITING', rpm=0),
    dict(name='03-down-expanding', facing='down', stock=2, state='EXPANDING', rpm=0),
    dict(name='04-up-ground', facing='up', stock=2, state='WAITING', rpm=0),
    dict(name='05-up-fixed', facing='up', stock=2, state='WAITING', rpm=32),
)


def put(pos, block):
    return f'setblock {xyz(pos)} {block}'


def station(case):
    item = f'id:"{SAPLING}",count:{case["stock"]}'
    inventory = f'Inventory:[{{Slot:0b,{item}}}]' if case['stock'] else 'Inventory:[]'
    if case['stock'] and case['facing'] == 'up':
        inventory += f',HeldItem:{{{item}}}'
    # Upward sapling gameplay is outside the native stationary implementation.
    # Seed the lock for the visual-only powered pose; its shaft gets real RPM.
    powered = 1 if case['rpm'] else 0
    return (f'create:deployer[facing={case["facing"]},axis_along_first=true]'
            + f'{{Mode:"USE",State:"WAITING",Timer:0,Powered:{powered}b,' + inventory + '}')


def background(command):
    command('fill 1128 99 98 1135 109 107 minecraft:air')
    command('fill 1133 100 103 1134 100 104 minecraft:smooth_stone')
    command('fill 1133 103 103 1134 103 104 minecraft:smooth_stone')
    command(put(SOIL, 'minecraft:dirt'))


def setup(command, case):
    for pos in (MOTOR, LOCK, DEPLOYER):
        command(put(pos, AIR))
    command(put(DEPLOYER, station(case)))
    if case['rpm']:
        command(put(LOCK, 'minecraft:redstone_block'))


def needs_motor(case):
    return case['rpm'] != 0 or case['state'] == 'EXPANDING'


def start_motor(command):
    command(put(MOTOR, 'create:creative_motor[facing=east]{ScrollValue:32}'))


def remove_dropped_stacks(command):
    command(f"execute positioned {xyz(DEPLOYER)} run kill @e[type=minecraft:item,distance=..8]")


def validate(nbt, case):
    observed = snapshot(nbt)
    assert observed['held'] == case['stock'], (case, nbt)
    assert all(observed[k] == case[k] for k in ('rpm', 'state')), (case, nbt, observed)
    if case['state'] == 'EXPANDING':
        assert 0 < observed['timer'] < 1000, observed
    return observed


def view(case):
    up = case['facing'] == 'up'
    return UP_VIEW if up else DOWN_VIEW, (1131.5, 105.0 if up else 103.5, 100.5)


def run_java(base, output):
    assert base.resolve() == java.BASE.resolve()
    manifest = json.loads((base / 'manifest.json').read_text())
    assert manifest['create_sha256'] == java.CREATE_SHA256 and manifest['data_version'] == 3955
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955
    report = dict(passed=False, source=PINS['create_revision'], cases=[])
    try:
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        host.command('tp @s ' + xyz(DOWN_VIEW))
        host.command('forceload add 1131 100')
        host.call('observe_ticks', {'ticks': 16, 'positions': [DEPLOYER]})
        host.command('clear @s')
        background(host.command)
        for case in CASES:
            setup(host.command, case)
            host.call('observe_ticks', {'ticks': 3, 'positions': [DEPLOYER]})
            if needs_motor(case):
                start_motor(host.command)
                host.call('observe_ticks', {'ticks': 13 if case['state'] == 'EXPANDING' else 3,
                                            'positions': [DEPLOYER]})
            if case['state'] == 'EXPANDING':
                host.command(put(MOTOR, AIR))
                host.call('observe_ticks', {'ticks': 2, 'positions': [DEPLOYER]})
            remove_dropped_stacks(host.command)
            nbt = host.call('block', {'pos': DEPLOYER})['nbt']
            observed = validate(nbt, case)
            position, target = view(case)
            host.call('camera', dict(position=position, target=target, fov=FOV, hide_gui=True))
            if case['rpm']:
                host.call('tick', {'frozen': False})
            capture = host.call('capture', {'name': f'{output.name}/{case["name"]}.png', 'frames': 18})
            if case['rpm']:
                host.call('tick', {'frozen': True})
            assert capture['client']['held'] == AIR, capture
            path = output / (case['name'] + '.png')
            shutil.copy2(capture['path'], path)
            row = dict(case=case, nbt=nbt, observed=observed, camera=capture['client'], image=str(path))
            if case['name'] == '04-up-ground':
                spin = host.call('capture', {'name': f'{output.name}/04-up-ground-spun.png', 'frames': 60})
                path = output / '04-up-ground-spun.png'
                shutil.copy2(spin['path'], path)
                row['spun'] = str(path)
            report['cases'].append(row)
        report['passed'] = True
    finally:
        host.command('forceload remove 1131 100')
        host.call('camera', dict(position=initial['position'], yaw=initial['yaw'], pitch=initial['pitch'],
                                 fov=initial['fov'], gui_scale=initial['gui_scale'], hide_gui=False))
        host.call('tick', {'frozen': False})
        save(output, report)
        (output / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def run_native(args):
    reference = json.loads(args.reference.read_text())
    assert reference['passed'] and reference['source'] == PINS['create_revision']
    session = NativeCheckSession(args.game, args.resources, args.ctl, args.jar,
                                 name='deployer-held', world='DeployerHeld', graphics=True, size=(1710, 1045))
    print(session.scratch, flush=True)
    report = dict(passed=False, source=reference['source'], cases=[])
    try:
        with session as client:
            call = client.call
            def command(cmd):
                return call('command', cmd)
            def step(count):
                command('tick step ' + str(count))
                call('wait', count + 2)
            command('gamemode creative')
            command('tp @s ' + xyz(DOWN_VIEW))
            wait_loaded(call, [DEPLOYER])
            command('clear @s')
            command('gamerule minecraft:advance_time false')
            command('time set 6000')
            command('weather clear')
            background(command)
            call('options-set', 'fov', FOV)
            call('options-set', 'bobView', 'false')
            call('key', 'f1', 'tap')
            command('tick freeze')
            for row in reference['cases']:
                case = row['case']
                setup(command, case)
                step(3)
                if needs_motor(case):
                    start_motor(command)
                    step(3)
                if case['state'] == 'EXPANDING':
                    # A debug step updates the kinetic network while getSpeed is zero.
                    # Run normal simulation slowly enough to catch the Java timer.
                    command('tick rate 1')
                    command('tick unfreeze')
                    deadline = time.monotonic() + 35
                    desired = row['observed']['timer']
                    while time.monotonic() < deadline:
                        current = snapshot(' '.join(command('data get block ' + xyz(DEPLOYER))['chat']))
                        # The control packet is applied on the next server turn.
                        if (current['state'] == 'EXPANDING'
                                and current['timer'] <= desired + 2 * abs(current['rpm'])):
                            break
                    else:
                        raise AssertionError(('No ordinary Deployer stroke', current))
                    command('tick freeze')
                    command(put(MOTOR, AIR))
                    command('tick rate 20')
                    step(2)
                remove_dropped_stacks(command)
                nbt = ' '.join(command('data get block ' + xyz(DEPLOYER))['chat'])
                observed = validate(nbt, case)
                assert observed == row['observed'], (row['observed'], observed, nbt)
                pose = row['camera']
                command('tp @s ' + xyz(pose['position']))
                call('look', pose['yaw'], pose['pitch'])
                call('wait', 15)
                camera = call('state')
                assert camera['held'] is None and camera['player']['on_ground'], camera
                assert all(abs(a-b) < .001 for a, b in zip(camera['player']['position'], pose['position'])), camera
                path = session.scratch / (case['name'] + '.png')
                if case['rpm']:
                    command('tick unfreeze')
                    call('wait', 6)
                call('screenshot', path)
                if case['rpm']:
                    command('tick freeze')
                result = dict(case=case, nbt=nbt, observed=observed, image=str(path))
                if case['name'] == '04-up-ground':
                    call('wait', 40)
                    path = session.scratch / '04-up-ground-spun.png'
                    call('screenshot', path)
                    result['spun'] = str(path)
                report['cases'].append(result)
            report['passed'] = True
    finally:
        save(session.scratch, report)


def save(directory, report):
    path = directory / 'result.json'
    path.write_text(json.dumps(report, indent=2) + '\n')
    print(path, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest='mode', required=True)
    original = modes.add_parser('java')
    original.add_argument('--java', type=Path, required=True)
    original.add_argument('--output', type=Path, required=True)
    native = modes.add_parser('native')
    for option in ('game', 'resources', 'ctl', 'reference', 'jar'):
        native.add_argument('--' + option, type=Path, required=True)
    args = parser.parse_args()
    if args.mode == 'java':
        args.output.mkdir(parents=True, exist_ok=True)
        run_java(args.java, args.output.resolve())
    else:
        run_native(args)


if __name__ == '__main__':
    main()
