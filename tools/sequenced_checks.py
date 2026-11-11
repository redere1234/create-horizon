#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Run all Precision Mechanism Deployer steps in the Java and Horizon games."""

import argparse
import json
from pathlib import Path
import re
import shutil
import struct
import tempfile
import time

from burner_heat_java_checks import field, number
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from funnel_checks import block, text
from native_check_session import NativeCheckSession, wait_loaded
import reference_java as java


DEPOT = (1987, 126, 1193)
DEPLOYER = (1987, 128, 1193)
MOTOR = (1986, 128, 1193)
PROBES = (DEPOT, DEPLOYER)
FEET = (1988.5, 126, 1193.5)
AIM = (1987.5, 128.00001, 1193.5)
DEPOT_AIM = (1987.5, 126.9, 1193.5)
AREA = '1984 124 1190 1991 131 1196'
LOAD = '1987 1193'
DROPS = '@e[type=minecraft:item,x=1984,y=124,z=1190,dx=7,dy=7,dz=6]'
AIR = 'minecraft:air'
SHEET = 'create:golden_sheet'
INCOMPLETE = 'create:incomplete_precision_mechanism'
RECIPE = 'create:sequenced_assembly/precision_mechanism'
SMALL, LARGE, NUGGET = 'create:cogwheel', 'create:large_cogwheel', 'minecraft:iron_nugget'
TOOLS = (SMALL, LARGE, NUGGET)
TOTAL = 15
COLD_STEP = 7
RESULTS = {
    'create:precision_mechanism': 120, SHEET: 8, 'create:andesite_alloy': 8, SMALL: 5,
    'minecraft:gold_nugget': 3, 'create:shaft': 2, 'create:crushed_raw_gold': 2,
    'minecraft:iron_ingot': 1, 'minecraft:clock': 1,
}
COMPONENT = re.compile(r'"create:sequenced_assembly"\s*:\s*(\{[^{}]*\})')


def put(command, pos, block):
    command(f'setblock {xyz(pos)} {block}')


def motor(command, on):
    put(command, MOTOR, 'create:creative_motor[facing=east]{ScrollValue:256}' if on else AIR)


def item_nbt(item, components=None):
    patch = f',components:{{{components}}}' if components else ''
    return f'{{id:"{item}",count:1{patch}}}'


def click(host, pos, face, target):
    if isinstance(host, Native):
        call = host.session.call
        host.command(f'tp @s {xyz(FEET)}')
        call('wait', 2)
        call('look-at', *target)
        call('wait', 3)
        hit = call('looking-at')['block']
        assert hit['pos'] == list(pos) and hit['face'] == face, hit
        call('mouse', 'right', 'click')
        call('wait', 4)
    else:
        host.call('camera', {'position': FEET, 'target': target})
        for _ in range(12):
            hit = host.call('state', {})['hit']
            if hit and hit['pos'] == list(pos) and hit['face'] == face:
                break
            time.sleep(.02)
        else:
            raise AssertionError(('The reference crosshair did not reach the requested face', pos, face, hit))
        host.call('input', {'key': 'use'})


def feed(host, item):
    host.command(f'item replace entity @s weapon.mainhand with {item} 1')
    click(host, DEPLOYER, 'down', AIM)


def cargo(command, item, components=None):
    stack = item_nbt(item, components)
    command(f'data modify block {xyz(DEPOT)} HeldItem set value '
            f'{{Item:{stack},Pos:.5f,PrevPos:.5f,Angle:180,InDirection:1}}')


def stack(raw):
    assembly = COMPONENT.search(raw)
    progress = None
    if assembly:
        record = assembly[1]
        progress = dict(id=re.search(r'\bid\s*:\s*"([^"]+)"', record)[1],
                        step=int(number({'nbt': record}, 'step')),
                        progress=number({'nbt': record}, 'progress'))
        raw = raw[:assembly.start()] + raw[assembly.end():]
    identity = re.search(r'\bid\s*:\s*"([^"]+)"', raw)
    return None if identity is None else dict(id=identity[1], count=int(number({'nbt': raw}, 'count')),
                                              assembly=progress, marked='sequenced_probe:19' in re.sub(r'\s+', '', raw))


def snapshot(depot, deployer):
    payload = field(depot, 'HeldItem') if re.search(r'\bHeldItem\s*:', depot) else '{}'
    hand = field(deployer, 'HeldItem') if re.search(r'\bHeldItem\s*:', deployer) else '{}'
    buffer = field(depot, 'OutputBuffer')
    assert not re.search(r'\bcount\s*:', buffer), buffer
    return dict(cargo=stack(payload), hand=stack(hand))


def install(command):
    command(f'fill {AREA} {AIR}')
    command(f'kill {DROPS}')
    command('fill 1985 125 1192 1990 125 1195 minecraft:stone')
    put(command, DEPOT, 'create:depot')
    put(command, DEPLOYER, 'create:deployer[facing=down,axis_along_first=true]')


def first_half(host, wait, observe):
    command = host.command
    install(command)
    wait(8)
    cargo(command, SHEET, '"minecraft:custom_data":{sequenced_probe:19}')
    feed(host, LARGE)
    motor(command, True)
    observe('wrong_start', 16)
    for completed in range(1, COLD_STEP + 1):
        feed(host, TOOLS[(completed - 1) % len(TOOLS)])
        observe(f'step_{completed}', 16)
    feed(host, SMALL)  # At step 7 the next tool must be the large cog.
    observe('wrong_next', 16)
    motor(command, False)
    observe('before_restart', 4)


def second_half(host, observe):
    command = host.command
    observe('after_restart', 1)
    motor(command, True)
    for completed in range(COLD_STEP + 1, TOTAL + 1):
        feed(host, TOOLS[(completed - 1) % len(TOOLS)])
        observe(f'step_{completed}', 16)
    cargo(command, INCOMPLETE, '"create:sequenced_assembly":'
                               '{id:"create:sequenced_assembly/not_precision",step:1,progress:0.2f}')
    feed(host, LARGE)
    observe('foreign_recipe', 16)
    cargo(command, INCOMPLETE)
    observe('missing_component', 16)
    loose = text(host, f'execute if entity {DROPS} run say sequenced_loose_stack')
    assert 'sequenced_loose_stack' not in loose, loose


def full_stack(item, assembly=None, marked=False):
    return dict(id=item, count=1, assembly=assembly, marked=marked)


def player_round_trip(host, wait, observe, rows):
    command = host.command
    install(command)
    wait(8)
    cargo(command, SHEET)
    feed(host, SMALL)
    motor(command, True)
    observe('formed', 16)
    motor(command, False)
    wait(3)
    command('gamemode survival')
    command('clear @s')
    slot = int(text(host, 'data get entity @s SelectedItemSlot').split()[-1])
    # Inventory.placeItemBackInInventory puts the result in the first free
    # slot. Reserve the earlier hotbar slots so normal use can place it back.
    for index in range(slot):
        command(f'item replace entity @s hotbar.{index} with minecraft:stick')
    try:
        click(host, DEPOT, 'up', DEPOT_AIM)
        observe('empty', 4)
        rows['picked'] = stack(text(host, 'data get entity @s SelectedItem'))
        click(host, DEPOT, 'up', DEPOT_AIM)
        observe('replaced', 8)
        rows['hand_after_place'] = stack(text(host, 'data get entity @s SelectedItem'))
        feed(host, LARGE)
        motor(command, True)
        observe('resumed', 16)
    finally:
        command('clear @s minecraft:stick')
        command('gamemode creative')


def verify_round_trip(rows):
    formed = rows['formed']['cargo']
    assert formed['id'] == INCOMPLETE and formed['assembly']['step'] == 1, rows
    assert rows['picked'] == formed == rows['replaced']['cargo'], rows
    assert not rows['empty']['cargo'] and not rows['hand_after_place'], rows
    resumed = rows['resumed']
    assert not resumed['hand'] and resumed['cargo']['assembly']['id'] == RECIPE, resumed
    assert resumed['cargo']['assembly']['step'] == 2, resumed


def verify(rows):
    assert rows['wrong_start'] == dict(cargo=full_stack(SHEET, marked=True), hand=full_stack(LARGE)), rows['wrong_start']
    for completed in range(1, TOTAL):
        row = rows[f'step_{completed}']
        assert not row['hand'], (completed, row)
        expected = row['cargo']
        assert expected and expected['id'] == INCOMPLETE and expected['count'] == 1 and not expected['marked'], row
        progress = expected['assembly']
        assert progress and progress['id'] == RECIPE and progress['step'] == completed, row
        assert struct.pack('>f', progress['progress']) == struct.pack('>f', completed / TOTAL), row
    parked = dict(cargo=rows[f'step_{COLD_STEP}']['cargo'], hand=full_stack(SMALL))
    for label in ('wrong_next', 'before_restart', 'after_restart'):
        assert rows[label] == parked, (label, rows[label])
    final = rows[f'step_{TOTAL}']
    assert not final['hand'] and final['cargo']['id'] in RESULTS, final
    assert final['cargo'] == full_stack(final['cargo']['id']), final
    foreign = full_stack(INCOMPLETE, dict(id='create:sequenced_assembly/not_precision', step=1, progress=0.2))
    assert rows['foreign_recipe'] == dict(cargo=foreign, hand=full_stack(LARGE)), rows['foreign_recipe']
    assert rows['missing_component'] == dict(cargo=full_stack(INCOMPLETE), hand=full_stack(LARGE)), rows['missing_component']


def run_java(work, rows, round_trip):
    host = Original()
    base = java.BASE
    manifest = json.loads((base / 'manifest.json').read_text())
    assert manifest['create_sha256'] == java.CREATE_SHA256 and manifest['data_version'] == 3955
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})

    def advance(ticks):
        return host.call('observe_ticks', {'ticks': ticks, 'positions': PROBES})['samples'][-1]['blocks']

    def observe(label, ticks):
        rows[label] = snapshot(*(block['nbt'] for block in advance(ticks)))

    try:
        host.command('gamemode creative')
        host.command(f'forceload add {LOAD}')
        host.command('tp @s 1987.5 130 1195.5')
        advance(24)
        if round_trip:
            player_round_trip(host, advance, observe, rows)
            return
        first_half(host, advance, observe)
        host.call('quit', {})
        deadline = time.monotonic() + 60
        while java.process_alive(base):
            if time.monotonic() >= deadline:
                raise RuntimeError('The isolated Java client did not stop after saving')
            time.sleep(0.2)
        resumed = java.launch(base)
        assert resumed['ready'] and resumed['data_version'] == 3955, resumed
        host.call('tick', {'frozen': True})
        for _ in range(10):
            if [block['id'] for block in advance(4)] == ['create:depot', 'create:deployer']:
                break
        else:
            raise AssertionError('Saved Depot/Deployer did not reload')
        second_half(host, observe)
    finally:
        host.command('item replace entity @s weapon.mainhand with minecraft:air')
        host.command(f'fill {AREA} {AIR}')
        host.command(f'kill {DROPS}')
        host.command(f'forceload remove {LOAD}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def run_native(session, rows, round_trip):
    host = Native(session)

    def ready():
        host.command('tp @s 1987.5 130 1195.5')
        wait_loaded(session.call, PROBES)

    def advance(ticks):
        # Native running_speed suppresses processing while tick-frozen, even
        # during a step. Use ordinary simulation for the settled-state parity.
        session.call('wait', ticks)
        return [block(host, pos) for pos in PROBES]

    def observe(label, ticks):
        rows[label] = snapshot(*(block['nbt'] for block in advance(ticks)))

    with session:
        ready()
        if round_trip:
            player_round_trip(host, advance, observe, rows)
            return
        first_half(host, advance, observe)
        session.restart()
        ready()
        second_half(host, observe)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--player-round-trip', action='store_true',
                        help='Run only the separate Survival pickup and place check')
    args = parser.parse_args()
    mode = 'player-round-trip' if args.player_round_trip else 'assembly'
    session = None
    if args.game:
        if not all((args.resources, args.ctl, args.reference)):
            parser.error('Horizon needs --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        assert reference.get('mode', 'assembly') == mode, reference.get('mode')
        session = NativeCheckSession(args.game, args.resources, args.ctl, None, name='sequenced-native',
                                     world='CreatePrecisionMechanism')
        work = session.scratch
    else:
        work = Path(tempfile.mkdtemp(prefix='sequenced-java-', dir=ROOT / '.local'))
    report = dict(passed=False, create=PINS['create_revision'], mode=mode, weights=RESULTS, rows={})
    if session:
        report.update(game=str(args.game.resolve()), reference=str(args.reference.resolve()))
    print(work, flush=True)
    try:
        if session:
            run_native(session, report['rows'], args.player_round_trip)
        else:
            run_java(work, report['rows'], args.player_round_trip)
        (verify_round_trip if args.player_round_trip else verify)(report['rows'])
        if session:
            for name, row in report['rows'].items():
                # The two games use independently seeded world RNGs.
                if name != f'step_{TOTAL}':
                    assert row == reference['rows'][name], (name, row, reference['rows'][name])
        report['passed'] = True
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        path = work / 'result.json'
        path.write_text(json.dumps(report, indent=2) + '\n')
        if session:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        print(path, flush=True)


if __name__ == '__main__':
    main()
