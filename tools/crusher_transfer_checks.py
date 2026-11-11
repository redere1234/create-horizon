#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare Crushing Wheel output to a Belt, Chute, Millstone, Funnel and Saw."""
import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field, items, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from crushing_wheel_checks import AIR, CHUTE, CONTROLLER, GRAVEL, X, Y, put, wheels
from native_check_session import NativeCheckSession
from reference_java import BASE, CREATE_SHA256


BELT_Z, CHUTE_Z, MILL_Z, FUNNEL_Z, SAW_Z = 1030, 1035, 1041, 1046, 1051
LOAD = '2128 1024 2143 1055'
REGION = '2131 165 1028 2137 172 1053'
DROPS = '@e[type=minecraft:item,x=2131,y=165,z=1028,dx=6,dy=7,dz=25]'
WHEAT = 'minecraft:wheat'
DIAMOND = 'minecraft:diamond'
SIGNAL = (X + 1, Y - 1, FUNNEL_Z)
POINTS = [(X, Y, BELT_Z), (X - 2, Y - 1, BELT_Z),
          (X, Y, CHUTE_Z), (X, Y - 1, CHUTE_Z),
          (X, Y, MILL_Z), (X, Y - 1, MILL_Z),
          (X, Y, FUNNEL_Z), (X, Y - 2, FUNNEL_Z),
          (X, Y, SAW_Z), (X, Y - 1, SAW_Z)]


def stack(item, count, marker):
    return f'id:"{item}",count:{count},components:{{"minecraft:custom_data":{{crusher_transfer:{marker}}}}}'


def mill_input(command, count):
    slots = f'{{Slot:0,{stack(WHEAT, count, 43)}}}' if count else ''
    command(f'data merge block {xyz(POINTS[5])} {{InputInventory:{{Size:1,Items:[{slots}]}}}}')


def seed(command, z, stacks):
    slots = ','.join(f'{{Slot:{index}b,{stack(*item)}}}'
                     for index, item in enumerate(stacks, 1))
    command(f'data merge block {X} {Y} {z} {{Inventory:{{Size:32,Items:[{slots}],'
            'ProcessingTime:0f,RecipeTime:0f,AppliedRecipe:1b}}')


def setup(command, advance):
    command(f'fill {REGION} {AIR}')
    command(f'kill {DROPS}')
    for index, part in enumerate(('start', 'middle', 'middle', 'middle', 'end')):
        put(command, (X - 2 + index, Y - 1, BELT_Z),
            f'create:belt[facing=east,slope=horizontal,part={part}]')
    put(command, POINTS[5], 'create:millstone')
    put(command, POINTS[7], 'minecraft:barrel')
    put(command, SIGNAL, 'minecraft:redstone_block')
    put(command, (X, Y - 1, FUNNEL_Z),
        'create:brass_funnel[facing=up,extracting=false,powered=true,waterlogged=false]'
        '{Filter:{id:"minecraft:wheat",count:1}}')
    put(command, POINTS[9], 'create:mechanical_saw[facing=up,axis_along_first=false]')
    for z in (BELT_Z, CHUTE_Z, MILL_Z, FUNNEL_Z, SAW_Z):
        wheels(command, z)
    advance(28)
    # The crusher's ticker runs before this Chute. A blocked outlet keeps the
    # stack in the chute while the next crusher output waits.
    put(command, (X, Y - 2, CHUTE_Z), 'minecraft:stone')
    put(command, POINTS[3], CHUTE.replace('shape=normal', 'shape=window'))
    advance(28)
    mill_input(command, 63)
    seed(command, BELT_Z, [(GRAVEL, 2, 41)])
    seed(command, CHUTE_Z, [(GRAVEL, 3, 42), (DIAMOND, 1, 44)])
    seed(command, MILL_Z, [(WHEAT, 3, 43), (DIAMOND, 1, 45)])
    seed(command, FUNNEL_Z, [(WHEAT, 3, 46), (DIAMOND, 1, 47)])
    seed(command, SAW_Z, [(GRAVEL, 2, 48)])


def release(command):
    put(command, (X - 2, Y - 1, BELT_Z - 1), 'create:creative_motor[facing=south]{ScrollValue:-32}')
    mill_input(command, 0)
    put(command, SIGNAL, AIR)


def contents(raw, key):
    body = field(raw, key) if key + ':' in raw else ''
    return {'stacks': items(raw, key) if body else {},
            'markers': [int(marker) for marker in re.findall(r'\bcrusher_transfer\s*:\s*(\d+)', body)]}


def sample(values):
    assert len(values) == len(POINTS), values
    crusher_belt, belt, crusher_chute, chute, crusher_mill, mill, crusher_funnel, barrel, crusher_saw, saw = values
    assert all(CONTROLLER in raw for raw in values[::2]), values
    assert 'create:belt' in belt and 'create:chute' in chute and 'create:millstone' in mill, values
    assert 'minecraft:barrel' in barrel and 'create:saw' in saw, values
    belt_data = contents(belt, 'Inventory')
    belt_data['entered_from'] = re.findall(r'\bInDirection\s*:\s*(\d+)', field(belt, 'Inventory'))
    return dict(crusher_belt=contents(crusher_belt, 'Inventory'), belt=belt_data,
                crusher_chute=contents(crusher_chute, 'Inventory'), chute=contents(chute, 'Item'),
                crusher_mill=contents(crusher_mill, 'Inventory'), mill=contents(mill, 'InputInventory'),
                crusher_funnel=contents(crusher_funnel, 'Inventory'), barrel=contents(barrel, 'Items'),
                crusher_saw=contents(crusher_saw, 'Inventory'), saw=contents(saw, 'Inventory'))


def verify(phases):
    def stack_state(item, count, marker):
        return dict(stacks={item: count}, markers=[marker])

    for row in phases['blocked']:
        assert row['crusher_belt'] == stack_state(GRAVEL, 2, 41), row
        assert not row['belt']['stacks'], row
        assert row['chute'] == stack_state(GRAVEL, 3, 42), row
        assert row['crusher_chute'] == stack_state(DIAMOND, 1, 44), row
        assert row['mill'] == stack_state(WHEAT, 64, 43), row
        assert row['crusher_mill'] == dict(stacks={WHEAT: 2, DIAMOND: 1}, markers=[43, 45]), row
        assert row['crusher_funnel'] == dict(stacks={WHEAT: 3, DIAMOND: 1}, markers=[46, 47]), row
        assert not row['barrel']['stacks'], row
    for row in phases['blocked'] + phases['released']:
        assert row['crusher_saw'] == stack_state(GRAVEL, 2, 48) and not row['saw']['stacks'], row
    if 'cold' in phases:
        assert phases['cold'][0] == phases['blocked'][-1], phases
    final = phases['released'][-1]
    assert final['belt'] == dict(**stack_state(GRAVEL, 2, 41), entered_from=['0']), final
    assert not final['crusher_belt']['stacks'], final
    assert final['mill'] == stack_state(WHEAT, 2, 43), final
    assert final['crusher_mill'] == stack_state(DIAMOND, 1, 45), final
    assert final['barrel'] == stack_state(WHEAT, 3, 46), final
    assert final['crusher_funnel'] == stack_state(DIAMOND, 1, 47), final


def java_run(work):
    host = Original()
    assert json.loads((BASE / 'manifest.json').read_text())['create_sha256'] == CREATE_SHA256
    prior = host.call('state', {})
    if prior['screen'] == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        prior = host.call('state', {})
    assert prior['ready'] and prior['data_version'] == 3955, prior
    host.call('tick', {'frozen': True})

    def advance(ticks):
        return host.call('observe_ticks', {'positions': POINTS, 'ticks': ticks})['samples']

    try:
        host.command(f'forceload add {LOAD}')
        host.command(f'tp @s {X}.5 {Y + 4} {CHUTE_Z}.5')
        advance(35)
        setup(host.command, advance)
        blocked = advance(5)
        release(host.command)
        released = advance(5)
        drops = host.command(f'execute if entity {DROPS} run say loose_crusher_transfer')
        assert not any('loose_crusher_transfer' in line for line in drops['messages']), drops
        return {name: [sample([block['nbt'] for block in row['blocks']]) for row in rows]
                for name, rows in [('blocked', blocked), ('released', released)]}
    finally:
        host.command(f'fill {REGION} {AIR}')
        host.command(f'kill {DROPS}')
        host.command(f'forceload remove {LOAD}')
        host.call('camera', {key: prior[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': prior['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    phases = {}
    for run, names in [('before-restart', ('blocked',)), ('after-restart', ('cold', 'released'))]:
        batch = Batch()
        batch.load((X, Y + 4, CHUTE_Z))
        if run == 'before-restart':
            setup(batch.command, batch.tick)
        for name in names:
            if name == 'released':
                release(batch.command)
            for _ in range(1 if name == 'cold' else 5):
                if name != 'cold':
                    batch.tick()
                for point in POINTS:
                    batch.data(point)
        batch.command(f'execute if entity {DROPS} run say loose_crusher_transfer', True)
        values = batch.run(session, run)
        assert 'loose_crusher_transfer' not in values[-1], values[-1]
        offset = 0
        for name in names:
            end = offset + len(POINTS) * (1 if name == 'cold' else 5)
            phases[name] = [sample(values[i:i + len(POINTS)]) for i in range(offset, end, len(POINTS))]
            offset = end
        assert offset == len(values) - 1, values
    return phases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='crusher-transfer-java-', dir=ROOT / '.local'))
        phases = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon runs require --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None, graphics=False,
                                     name='crusher-transfer-native', world='CreateCrusherTransfer')
        work = session.scratch
        try:
            phases = native_run(session)
        finally:
            session.control_temp.cleanup()
            for path in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(path, ignore_errors=True)
    (work / 'observed.json').write_text(json.dumps(phases, indent=2) + '\n')
    verify(phases)
    if not args.java:
        assert {name: phases[name] for name in reference['phases']} == reference['phases'], phases
    result = work / 'result.json'
    result.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], phases=phases), indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
