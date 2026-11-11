#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Verify ordinary chest and barrel storage on Gantry, Rope Pulley and Mechanical Pistons."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from actor_native_checks import matched
from bearing_native_checks import Batch
from burner_heat_java_checks import field, items
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession
from saved_block_checks import read_saved_chunk_tag


X, Y = 1528, 140
AIR = 'minecraft:air'
CHEST = 'minecraft:chest[facing=north,type=single,waterlogged=false]'
BARREL = 'minecraft:barrel[facing=north,open=false]'
EAST_POWER = 'create:creative_motor[facing=east]{ScrollValue:-128}'
PISTON_OUT = 'create:creative_motor[facing=south]{ScrollValue:-128}'
PISTON_IN = 'create:creative_motor[facing=south]{ScrollValue:128}'
STORAGE = ('horizon:attachments', 'create', 'mounted_item_storage', 'value')
EXPECTED = {'minecraft:iron_ingot': 41, 'minecraft:diamond_pickaxe': 1, 'minecraft:stick': 11}


def gantry_case(z):
    return dict(z=z, controller=(X, Y + 1, z), source=(X, Y + 2, z),
                  target=(X + 2, Y + 2, z), motor=(X - 1, Y, z), power=EAST_POWER,
                  motion_ticks=7, setup={
                      **{(X + dx, Y, z): 'create:gantry_shaft[facing=east]' for dx in range(3)},
                      (X, Y + 1, z): 'create:gantry_carriage[facing=up,axis_along_first=false]',
                  })


def cases():
    z = 167
    pulley = dict(z=z, controller=(X, Y + 3, z), source=(X, Y, z),
                  target=(X, Y + 2, z), motor=(X + 1, Y + 3, z),
                  power='create:creative_motor[facing=west]{ScrollValue:128}', motion_ticks=3,
                  setup={(X, Y + 3, z): 'create:rope_pulley[axis=x]{Offset:2f}',
                         (X, Y + 2, z): 'create:rope[waterlogged=false]',
                         (X, Y + 1, z): 'create:pulley_magnet[waterlogged=false]'})
    rigs = dict(gantry=gantry_case(151), pulley=pulley)
    for z, sticky in ((183, False), (199, True)):
        base = 'sticky_mechanical_piston' if sticky else 'mechanical_piston'
        rigs['sticky' if sticky else 'piston'] = dict(
            z=z, controller=(X, Y, z), source=(X + 1, Y, z), target=(X + 3, Y, z),
            motor=(X, Y, z - 1), power=PISTON_OUT, motion_ticks=3,
            setup={(X, Y, z): f'create:{base}[facing=east,axis_along_first=false,state=retracted]',
                   **{(X + dx, Y, z): 'create:piston_extension_pole[facing=east]' for dx in (-2, -1)}},
        )
    return rigs


def farm_case():
    z, y = 247, Y + 2
    case = gantry_case(z)
    case['source'] = (X, y, z - 1)
    case['target'] = (X + 2, y, z - 1)
    crop = (X + 1, y, z + 1)
    case['setup'].update({
        (X, y, z): 'minecraft:slime_block',
        (X, y, z + 1): 'create:mechanical_harvester[facing=east,waterlogged=false]',
        (X + 1, y - 1, z + 1): 'minecraft:farmland[moisture=7]',
        crop: 'minecraft:wheat[age=7]',
    })
    return case, crop


def setup(put, command, case, storage=CHEST):
    z = case['z']
    command(f'fill {X - 4} {Y - 2} {z - 2} {X + 5} {Y + 6} {z + 2} {AIR}')
    for position, state in case['setup'].items():
        put(position, state)
    source = case['source']
    put(source, storage)
    for slot, stack in ((0, 'minecraft:iron_ingot 41'),
                        (9, 'minecraft:diamond_pickaxe[minecraft:damage=37] 1'),
                        (26, 'minecraft:stick[minecraft:custom_data={linear_cargo:73}] 11')):
        command(f'item replace block {xyz(source)} container.{slot} with {stack}')


def verify_cargo(nbt):
    assert items(nbt, 'Items') == EXPECTED, nbt
    cargo = field(nbt, 'Items').replace(' ', '')
    assert sorted(map(int, re.findall(r'Slot:(\d+)b', cargo))) == [0, 9, 26], cargo
    assert 'linear_cargo:73' in cargo and '"minecraft:damage":37' in cargo, cargo


def verify_harvest(nbt):
    contents = items(nbt, 'Items')
    assert {item: contents.get(item) for item in EXPECTED} == EXPECTED, nbt
    assert contents.get('minecraft:wheat') == 1, nbt
    cargo = field(nbt, 'Items').replace(' ', '')
    assert 'linear_cargo:73' in cargo and '"minecraft:damage":37' in cargo, cargo


def java_reference(storage):
    host = Original()
    block_id = storage.split('[', 1)[0]
    work = Path(tempfile.mkdtemp(prefix=f'linear-{block_id.split(":")[1]}-java-', dir=ROOT / '.local'))

    def put(pos, state):
        host.command(f'setblock {xyz(pos)} {state}')

    def observe(case, ticks):
        return host.call('observe_ticks', {'ticks': ticks,
                         'positions': [case['source'], case['target']]})['samples'][-1]['blocks']

    try:
        assert host.call('state', {})['data_version'] == 3955
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        observed = {}
        for name, case in cases().items():
            chunk = f'{X} {case["z"]}'
            host.command(f'forceload add {chunk}')
            try:
                host.command(f'tp @s {X}.5 {Y + 8} {case["z"]}.5')
                observe(case, 24)
                setup(put, host.command, case, storage)
                before = observe(case, 2)
                verify_cargo(before[0]['nbt'])
                put(case['motor'], case['power'])
                moving = observe(case, case['motion_ticks'])
                assert all(block['id'] == AIR for block in moving), (name, moving)
                landed = observe(case, 20)
                source_after = 'create:piston_extension_pole' if name in ('piston', 'sticky') else AIR
                assert landed[0]['id'] == source_after and landed[1]['id'] == block_id, landed
                assert landed[1]['properties']['facing'].lower() == 'north', landed
                verify_cargo(landed[1]['nbt'])
                if name in ('piston', 'sticky'):
                    put(case['motor'], AIR)
                    observe(case, 3)
                    put(case['motor'], PISTON_IN)
                    retracted = observe(case, 24)
                    moved = retracted[0 if name == 'sticky' else 1]
                    emptied = retracted[1 if name == 'sticky' else 0]
                    assert moved['id'] == block_id and emptied['id'] == AIR, (name, retracted)
                    verify_cargo(moved['nbt'])
                else:
                    retracted = []
                observed[name] = dict(before=before, moving=moving, landed=landed, retracted=retracted)
            finally:
                host.command(f'forceload remove {chunk}')
        if storage == CHEST:
            case, crop = farm_case()
            chunk = f'{X} {case["z"]}'
            host.command(f'forceload add {chunk}')
            try:
                host.command(f'tp @s {X}.5 {Y + 8} {case["z"]}.5')
                observe(case, 24)
                setup(put, host.command, case)
                observe(case, 2)
                put(case['motor'], case['power'])
                output, plant = host.call('observe_ticks', {'ticks': 20,
                    'positions': [case['target'], crop]})['samples'][-1]['blocks']
                assert output['id'] == 'minecraft:chest', output
                assert plant['id'] == 'minecraft:wheat' and plant['properties']['age'] == '0', plant
                verify_harvest(output['nbt'])
                observed['farm'] = dict(landed=output, crop=plant)
            finally:
                host.command(f'forceload remove {chunk}')
        result = work / 'result.json'
        result.write_text(json.dumps(dict(create=PINS['create_revision'], storage=block_id, cases=observed), indent=2) + '\n')
        return result
    finally:
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def saved(session, case):
    return read_saved_chunk_tag(session.scratch, case['controller'], STORAGE, session.world)['nbt']


def mounted(session, case):
    data = saved(session, case)['value']
    [chest] = data['Chests']['value']
    fields = chest['value']
    assert fields['Controller']['value'] == list(case['controller']), fields
    slots = {entry['value']['Slot']['value']: entry['value'] for entry in fields['Items']['value']}
    assert set(slots) == {0, 9, 26}, slots
    assert {item['id']['value']: item['count']['value'] for item in slots.values()} == EXPECTED, slots
    assert slots[9]['components']['value']['minecraft:damage']['value'] == 37, slots[9]
    assert slots[26]['components']['value']['minecraft:custom_data']['value']['linear_cargo']['value'] == 73
    return fields


def movement(session, name, case, reference, storage):
    source, target = case['source'], case['target']
    motor, controller = case['motor'], case['controller']
    assert all(block['id'] == AIR for block in reference['moving']), reference['moving']
    verify_cargo(reference['landed'][1]['nbt'])

    batch = Batch()
    batch.load(controller)
    setup(batch.put, batch.command, case, storage)
    batch.tick(2)
    batch.data(source)
    batch.put(motor, case['power'])
    batch.tick(case['motion_ticks'])
    batch.expect(source, AIR)
    batch.expect(target, AIR)
    before, *captured = batch.run(session, name + '-moving-save')
    verify_cargo(before)
    assert all(map(matched, captured)), captured
    cargo = mounted(session, case)

    if name == 'gantry':
        x, y, z = source
        parking = (x + 1, y, z)
        switch = (x + 1, Y, z + 1)
        batch = Batch()
        batch.load(controller)
        batch.put(parking, 'minecraft:obsidian')
        batch.put(switch, 'minecraft:redstone_block')
        batch.tick(3)
        batch.expect(parking, 'minecraft:obsidian')
        batch.expect(source, AIR)
        batch.expect(target, AIR)
        blocked = batch.run(session, 'gantry-blocked-after-restart')
        assert all(map(matched, blocked)), blocked
        assert mounted(session, case) == cargo

        batch = Batch()
        batch.load(controller)
        batch.put(parking, AIR)
        batch.tick(3)
        batch.expect(parking, storage)
        batch.data(parking)
        placed, parked = batch.run(session, 'gantry-restored-after-second-restart')
        assert matched(placed), placed
        verify_cargo(parked)
        assert saved(session, case) is None

    batch = Batch()
    batch.load(controller)
    if name == 'gantry':
        batch.put(switch, AIR)
        batch.expect(parking, storage)
    batch.tick(20)
    expected_source = reference['landed'][0]['id']
    batch.expect(source, expected_source)
    batch.expect(target, storage)
    batch.data(target)
    if name == 'gantry':
        batch.expect(parking, AIR)
    rows = batch.run(session, name + '-translated-landing')
    index = len(rows) - (2 if name == 'gantry' else 1)
    landed = rows[index]
    assert all(map(matched, rows[:index] + rows[index + 1:])), rows
    verify_cargo(landed)
    assert saved(session, case) is None

    if name not in ('piston', 'sticky'):
        return dict(cargo=cargo, landed=landed)

    batch = Batch()
    batch.load(controller)
    batch.put(motor, AIR)
    batch.tick(3)
    batch.put(motor, PISTON_IN)
    batch.tick(24)
    destination, clear = (source, target) if name == 'sticky' else (target, source)
    batch.expect(destination, storage)
    batch.expect(clear, AIR)
    batch.data(destination)
    *positions, retracted = batch.run(session, name + '-retract-after-reload')
    assert all(map(matched, positions)), positions
    verify_cargo(retracted)
    assert saved(session, case) is None
    return dict(cargo=cargo, landed=landed, retracted=retracted)


def refusals(session):
    case = gantry_case(215)
    controller, motor, source = (case[name] for name in ('controller', 'motor', 'source'))
    batch = Batch()
    batch.load(controller)
    setup(batch.put, batch.command, case)
    wet = CHEST.replace('waterlogged=false', 'waterlogged=true')
    batch.put(source, wet)
    batch.tick(2)
    batch.put(motor, case['power'])
    batch.tick(16)
    batch.expect(source, wet)
    batch.expect(case['target'], AIR)
    batch.data(source)
    *wet_rows, wet_nbt = batch.run(session, 'gantry-refuses-wet-chest')
    assert all(map(matched, wet_rows)), wet_rows
    verify_cargo(wet_nbt)
    assert saved(session, case) is None

    case = gantry_case(231)
    controller, motor, source = (case[name] for name in ('controller', 'motor', 'source'))
    batch = Batch()
    batch.load(controller)
    setup(batch.put, batch.command, case)
    x, y, z = source
    left, right = (x, y, z - 1), (x, y, z + 1)
    batch.put(source, 'minecraft:slime_block')
    batch.put(left, CHEST)
    batch.put(right, CHEST)
    batch.command(f'item replace block {xyz(left)} container.0 with minecraft:iron_ingot 3')
    batch.command(f'item replace block {xyz(right)} container.26 with minecraft:gold_ingot 5')
    batch.tick(2)
    batch.put(motor, case['power'])
    batch.tick(16)
    batch.expect(source, 'minecraft:slime_block')
    batch.expect(left, CHEST)
    batch.expect(right, CHEST)
    batch.data(left)
    batch.data(right)
    *positions, left_nbt, right_nbt = batch.run(session, 'gantry-refuses-two-chests')
    assert all(map(matched, positions)), positions
    assert items(left_nbt, 'Items') == {'minecraft:iron_ingot': 3}, left_nbt
    assert items(right_nbt, 'Items') == {'minecraft:gold_ingot': 5}, right_nbt
    assert saved(session, case) is None
    return dict(wet=wet_rows, two=[left_nbt, right_nbt])


def farm(session, reference):
    case, crop = farm_case()
    verify_harvest(reference['landed']['nbt'])
    batch = Batch()
    batch.load(case['controller'])
    setup(batch.put, batch.command, case)
    batch.tick(2)
    batch.put(case['motor'], case['power'])
    batch.tick(20)
    batch.expect(crop, 'minecraft:wheat[age=0]')
    batch.expect(case['target'], CHEST)
    batch.data(case['target'])
    reset, placed, cargo = batch.run(session, 'gantry-mounted-harvest')
    assert matched(reset) and matched(placed), (reset, placed)
    verify_harvest(cargo)
    assert saved(session, case) is None
    return dict(crop=reset, cargo=cargo)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--barrel', action='store_true', help='verify closed barrels on each linear actuator')
    for arg in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + arg, type=Path)
    parser.add_argument('--create-jar', type=Path)
    parser.add_argument('--case', action='append', choices=(*cases(), 'refusals', 'farm'))
    args = parser.parse_args()
    storage = BARREL if args.barrel else CHEST
    block_id = storage.split('[', 1)[0]
    if args.barrel and set(args.case or ()) & {'refusals', 'farm'}:
        parser.error('Refusals and farm checks use chests')
    if args.java:
        print(java_reference(storage))
        return
    if not all((args.game, args.resources, args.ctl, args.reference)):
        parser.error('Specify --java or all native arguments')
    reference = json.loads(args.reference.read_text())
    assert reference['create'] == PINS['create_revision']
    assert reference.get('storage', 'minecraft:chest') == block_id
    fixtures = cases()
    names = tuple(fixtures) if args.barrel else (*fixtures, 'refusals', 'farm')
    for name in args.case or names:
        container = block_id.split(':')[1]
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name=f'linear-{container}-{name}', graphics=False,
                                     world='CreateLinearStorageCheck')
        session.env.pop('CREATE_HORIZON_TRACE_POSES', None)
        session.env.pop('CREATE_HORIZON_PARTICLE_TRACE', None)
        try:
            if name == 'refusals':
                result = refusals(session)
            elif name == 'farm':
                result = farm(session, reference['cases']['farm'])
            else:
                result = movement(session, name, fixtures[name], reference['cases'][name], storage)
        finally:
            session.control_temp.cleanup()
            for copy in (session.resources, session.scratch / '.horizon-cache', session.scratch / 'horizon-mods'):
                shutil.rmtree(copy, ignore_errors=True)
        path = session.scratch / 'result.json'
        path.write_text(json.dumps(result, indent=2) + '\n')
        print(path, flush=True)


if __name__ == '__main__':
    main()
