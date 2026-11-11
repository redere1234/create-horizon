#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare linear chassis and glued cargo on regular and sticky pistons."""
import argparse
import json
from pathlib import Path
import tempfile

from bearing_native_checks import Batch
from chain_drive_checks import Original, xyz
from chassis_native_checks import expect_restored
from chassis_reference_checks import LINEAR, RADIAL
from common import PINS, ROOT
from gantry_chassis_checks import observed_java, translate, verify
from gantry_glue_checks import java_volumes, native_glue_clicks
from native_check_session import NativeCheckSession, wait_loaded
from saved_block_checks import read_saved_chunk_tag
from super_glue_native_checks import ITEM, KEYS, MOUNTED_KEYS
import reference_java as java


AIR = 'minecraft:air'
X, Y = 1049, 100
POLE = 'create:piston_extension_pole[facing=east]'
EXTEND = 'create:creative_motor[facing=south]{ScrollValue:-128}'
RETRACT = 'create:creative_motor[facing=south]{ScrollValue:128}'
DRIVE_TICKS = 24
CHASSIS_KEYS = ('horizon:attachments', 'create', 'mounted_chassis', 'value')
SCENE_KEYS = ('horizon:attachments', 'create', 'moving_structures', 'value')


def rig(z, sticky):
    controller = (X, Y, z)
    motor = (X, Y, z - 1)
    name = 'sticky_mechanical_piston' if sticky else 'mechanical_piston'
    chassis = (X + 1, Y, z)
    grouped = (X + 1, Y, z + 1)
    glued = (X + 1, Y, z + 2)
    outward = {(X + 2, Y, z + 1): 'minecraft:stone'}
    inward = {(X + 3, Y, z + 1): 'minecraft:oak_planks'}
    payload = {chassis: f'{LINEAR}[axis=x]{{ScrollValue:2}}',
               grouped: f'{LINEAR}[axis=x]{{ScrollValue:3}}',
               glued: f'{RADIAL}[axis=x,sticky_north=true]{{ScrollValue:4}}',
               (X + 1, Y + 1, z + 2): 'minecraft:oak_log[axis=z]'}
    base = f'create:{name}[facing=east,axis_along_first=false,state='
    drive = {controller: base + 'retracted]', **{(X + dx, Y, z): POLE for dx in (-3, -2, -1)}}
    head = f'create:mechanical_piston_head[facing=east,type={"sticky" if sticky else "normal"}]'
    extended_drive = {controller: base + 'extended]', (X + 1, Y, z): POLE,
                      (X + 2, Y, z): POLE, (X + 3, Y, z): head}
    extended = translate(payload | outward, 3)
    pulled = (payload | translate(inward, -3) | translate(outward, 3)) if sticky else extended | inward
    cells = dict.fromkeys(drive | extended_drive | payload | outward | extended | inward | pulled, AIR)
    moving = cells | {controller: base + 'moving]'}
    return {
        'controller': controller, 'motor': motor, 'selection': (chassis, glued),
        'setup': drive | payload | outward,
        'before': cells | drive | payload | outward, 'moving_out': moving,
        'extended': cells | extended_drive | extended,
        'moving_in': moving | (translate(outward, 3) if sticky else extended | inward),
        'restored': cells | drive | pulled,
        'inward': inward,
    }


def clear_z(z):
    return f'fill {X - 4} {Y - 1} {z - 2} {X + 6} {Y + 4} {z + 3} minecraft:air'


def feet(pos, second):
    x, y, z = pos
    return (x + 3.5, y - 1, z + .5) if second else (x + .5, y - 1, z - 2.5)


def java_clicks(host, work, selection):
    host.command(f'item replace entity @s weapon.mainhand with {ITEM}')
    for index, pos in enumerate(selection):
        host.call('camera', {'position': feet(pos, index == 1), 'target': [v + .5 for v in pos]})
        host.call('capture', {'name': f'{work.name}/piston-glue-{pos[2]}-{index}.png', 'frames': 8})
        assert host.call('state', {})['hit']['pos'] == list(pos)
        host.call('input', {'key': 'use'})
        try:
            host.call('capture', {'name': f'{work.name}/piston-glue-{pos[2]}-{index}-after.png', 'frames': 6})
        finally:
            host.call('input', {'key': 'use', 'down': False})


def run_java(base):
    java.BASE = base
    host = Original()
    work = Path(tempfile.mkdtemp(prefix='piston-payload-java-', dir=ROOT / '.local'))
    print(work, flush=True)
    report = dict(passed=False, create=PINS['create_revision'], scenes={})
    try:
        assert host.call('state', {})['data_version'] == 3955
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        for z, sticky in [(118, False), (134, True)]:
            case = rig(z, sticky)
            load = f'{X} {z}'
            host.command(f'forceload add {load}')
            try:
                host.command(f'tp @s {X}.5 {Y + 4} {z}.5')
                host.call('observe_ticks', {'ticks': 22, 'positions': [case['controller']]})
                host.command(f'kill @e[type=create:super_glue,x={X},y={Y},z={z},distance=..12]')
                host.command(clear_z(z))
                host.command(f'fill {X - 4} {Y - 2} {z - 3} {X + 6} {Y - 2} {z + 4} minecraft:stone')
                for pos, state in case['setup'].items():
                    host.command(f'setblock {xyz(pos)} {state}')
                java_clicks(host, work, case['selection'])
                observed_java(host, case['before'], 1)
                [initial] = java_volumes(host, case['controller'])
                host.command(f'setblock {xyz(case["motor"])} {EXTEND}')
                observed_java(host, case['moving_out'], 3)
                assert not java_volumes(host, case['controller'])
                observed_java(host, case['extended'], DRIVE_TICKS)
                [extended] = java_volumes(host, case['controller'])
                assert extended == [tuple((v + (3 if i == 0 else 0)) for i, v in enumerate(corner))
                                    for corner in initial], (initial, extended)
                host.command(f'setblock {xyz(case["motor"])} {AIR}')
                for pos, state in case['inward'].items():
                    host.command(f'setblock {xyz(pos)} {state}')
                observed_java(host, case['extended'] | case['inward'], 3)
                host.command(f'setblock {xyz(case["motor"])} {RETRACT}')
                observed_java(host, case['moving_in'], 3)
                assert java_volumes(host, case['controller']) == ([] if sticky else [extended])
                observed_java(host, case['restored'], DRIVE_TICKS)
                [restored] = java_volumes(host, case['controller'])
                assert restored == (initial if sticky else extended), restored
                report['scenes']['sticky' if sticky else 'regular'] = dict(initial=initial,
                                                                         extended=extended,
                                                                         restored=restored)
            finally:
                host.command(f'forceload remove {load}')
        report['passed'] = True
    finally:
        host.call('tick', {'frozen': False})
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def guard_rig():
    z = 150
    case = rig(z, True)
    controller = case['controller']
    a, b, c = (X + 4, Y, z), (X + 4, Y, z + 1), (X + 3, Y, z + 1)
    return {
        'controller': controller, 'motor': case['motor'], 'selection': (a, c),
        'setup': {
            controller: 'create:sticky_mechanical_piston[facing=east,axis_along_first=false,state=extended]',
            (X + 1, Y, z): POLE, (X + 2, Y, z): POLE,
            (X + 3, Y, z): 'create:mechanical_piston_head[facing=east,type=sticky]',
            a: f'{LINEAR}[axis=x]{{ScrollValue:2}}', b: 'minecraft:oak_planks', c: 'minecraft:stone',
        },
    }


def run_native(session, reference):
    assert reference['passed'] and reference['create'] == PINS['create_revision'], reference
    call = session.call
    cases = [(name, rig(z, sticky)) for name, z, sticky in [('regular', 118, False), ('sticky', 134, True)]]
    guard = guard_rig()

    def saved(case, keys):
        return read_saved_chunk_tag(session.scratch, case['controller'], keys, session.world)['nbt']

    def volumes(case, keys=KEYS):
        tag = saved(case, keys)
        if tag is None:
            return []
        if keys == MOUNTED_KEYS:
            [entry] = tag['value']['Entries']['value']
            assert entry['value']['Controller']['value'] == list(case['controller']), entry
            tag = entry['value']['Bounds']
        return [row['value'] for row in tag['value']['Volumes']['value']]

    def ranges(case):
        tag = saved(case, CHASSIS_KEYS)
        if tag is None:
            return []
        [entry] = tag['value']['Entries']['value']
        assert entry['value']['Controller']['value'] == list(case['controller']), entry
        return [r['value'] for r in entry['value']['Ranges']['value']]

    def phase(name, case, label, expected, ticks=0, edits=()):
        batch = Batch()
        batch.load(case['controller'])
        for pos, state in edits:
            batch.put(pos, state)
        if ticks:
            batch.tick(ticks)
        expect_restored(batch, expected)
        return verify(batch, session, f'piston-{name}-{label}')

    def inclusive(java_box):
        lo, hi = java_box
        return [*map(int, lo), *(int(v) - 1 for v in hi)]

    with session:
        for case in [*(case for _, case in cases), guard]:
            z = case['controller'][2]
            call('command', f'tp @s {X}.5 {Y + 2} {z}.5')
            wait_loaded(call, [case['controller']])
            call('command', clear_z(z))
            call('command', f'fill {X - 4} {Y - 2} {z - 3} {X + 6} {Y - 2} {z + 4} minecraft:stone')
            for pos, state in case['setup'].items():
                call('command', f'setblock {xyz(pos)} {state}')
            second = case['selection'][1]

            def viewpoint(pos):
                if case is guard and pos == second:
                    return (pos[0] + .5, pos[1] - 1, pos[2] + 3.5)
                return feet(pos, pos == second)

            native_glue_clicks(session, case['selection'], viewpoint)

    results = {}
    for name, case in cases:
        java_case = reference['scenes'][name]
        assert volumes(case) == [inclusive(java_case['initial'])]
        motor = case['motor']
        moving_out = phase(name, case, 'moving-out', case['moving_out'], 3, [(motor, EXTEND)])
        assert saved(case, SCENE_KEYS) is not None
        assert not volumes(case) and volumes(case, MOUNTED_KEYS) == [[0, 0, 0, 0, 0, 2]]
        assert ranges(case) == [[0, 0, 0, 2], [0, 0, 1, 3], [0, 0, 2, 4]]
        extended = phase(name, case, 'cold-extended', case['extended'], DRIVE_TICKS)
        assert volumes(case) == [inclusive(java_case['extended'])]
        assert not volumes(case, MOUNTED_KEYS) and not ranges(case)
        before_retract = case['extended'] | case['inward']
        phase(name, case, 'unpowered', before_retract, 3,
              [(motor, AIR), *case['inward'].items()])
        moving_in = phase(name, case, 'moving-in', case['moving_in'], 3, [(motor, RETRACT)])
        if name == 'sticky':
            assert not volumes(case) and volumes(case, MOUNTED_KEYS) == [[0, 0, 0, 0, 0, 2]]
            assert ranges(case) == [[0, 0, 0, 2], [0, 0, 1, 3], [0, 0, 2, 4]]
        else:
            assert volumes(case) == [inclusive(java_case['extended'])]
            assert not volumes(case, MOUNTED_KEYS) and not ranges(case)
        restored = phase(name, case, 'cold-retracted', case['restored'], DRIVE_TICKS)
        assert volumes(case) == [inclusive(java_case['restored'])]
        assert not volumes(case, MOUNTED_KEYS) and not ranges(case)
        assert saved(case, SCENE_KEYS) is None
        results[name] = dict(moving_out=moving_out, extended=extended, moving_in=moving_in,
                             restored=restored, glue=volumes(case))

    bounds = [X + 3, Y, 150, X + 4, Y, 151]
    assert volumes(guard) == [bounds]
    checks = phase('guard', guard, 'head-in-footprint', guard['setup'], 8, [(guard['motor'], RETRACT)])
    assert volumes(guard) == [bounds] and not volumes(guard, MOUNTED_KEYS) and not ranges(guard)
    assert saved(guard, SCENE_KEYS) is None
    results['drive_footprint_guard'] = dict(checks=checks, unchanged_glue=bounds)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('java', 'game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + key, type=Path)
    args = parser.parse_args()
    if args.java:
        run_java(args.java)
        return
    if not all((args.game, args.resources, args.ctl, args.reference)):
        parser.error('Specify --java or all of --game, --resources, --ctl and --reference')
    session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                 name='piston-payload-native', world='CreatePistonPayloadChecks')
    report = dict(passed=False)
    path = session.scratch / 'result.json'
    print(session.scratch, flush=True)
    try:
        report.update(run_native(session, json.loads(args.reference.read_text())))
        report['passed'] = True
    finally:
        path.write_text(json.dumps(report, indent=2) + '\n')
        session.control_temp.cleanup()
        print(path)


if __name__ == '__main__':
    main()
