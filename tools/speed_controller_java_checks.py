#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Record Create 6.0.10 speed controller ports, source order and live settings.

The isolated Java bridge captures actual block state and kinetic NBT during
ordinary server ticks. The report retains commands, probe coordinates and tick
indices for replay when the native controller is available. Distinguish saved
ScrollValue, a raw NBT edit and a real setting from the value board.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tempfile

from burner_heat_java_checks import number
from chain_drive_checks import Original, offset, xyz
from common import PINS, ROOT
from reference_java import BASE, CREATE_SHA256


CENTER = (1655, 180, 647)
FORCE_RANGE = '1648 640 1663 655'
CLEAR = 'fill 1650 179 642 1660 184 652 minecraft:air'
CONTROLLER = 'create:rotation_speed_controller'
AIR = 'minecraft:air'


def put(pos, state):
    return f'setblock {xyz(pos)} {state}'


def motor(axis, speed):
    facing = ('east', 'down', 'south')[axis]
    return f'create:creative_motor[facing={facing}]{{ScrollValue:{-speed if axis == 1 else speed}}}'


def summarize(block, positions):
    nbt = block.get('nbt', '') or ''
    found = re.search(r'\bSource: *\[I; *(-?\d+), *(-?\d+), *(-?\d+)\]', nbt)
    source = tuple(map(int, found.groups())) if found else None
    network = re.search(r'\bNetwork: *\{([^{}]+)\}', nbt)
    scroll = int(number(block, 'ScrollValue')) if 'ScrollValue:' in nbt else None
    return dict(block=block['id'], properties=block['properties'],
                rpm=number(block, 'Speed', 0), scroll=scroll,
                source=positions.get(source, source),
                network=network.group(1) if network else None)


def fixture(axis, *, wheel='large_cogwheel', wheel_axis=None, shifted=False, target=None):
    cross_axis = 2 - axis
    wheel_axis = cross_axis if wheel_axis is None else wheel_axis
    wheel_pos = offset(CENTER, 1, 1)
    if shifted:
        wheel_pos = offset(wheel_pos, axis, 1)
    wheel_input = offset(wheel_pos, wheel_axis, 1 if wheel_axis == 1 else -1)
    positions = dict(controller=CENTER, shaft_in=offset(CENTER, axis, -1), shaft_out=offset(CENTER, axis, 1),
                     motor_shaft=offset(CENTER, axis, -2), cog=wheel_pos, motor_cog=wheel_input,
                     wrong_face=offset(CENTER, cross_axis, 1))
    assert len(set(positions.values())) == len(positions)
    axis_name = 'xyz'[axis]
    setting = '' if target is None else f'{{ScrollValue:{target}}}'
    layout = [CLEAR, put(CENTER, f'{CONTROLLER}[axis={axis_name}]{setting}'),
              put(positions['shaft_in'], f'create:shaft[axis={axis_name}]'),
              put(positions['shaft_out'], f'create:shaft[axis={axis_name}]'),
              put(positions['wrong_face'], f'create:shaft[axis={"xyz"[cross_axis]}]')]
    if wheel is not None:
        layout.append(put(wheel_pos, f'create:{wheel}[axis={"xyz"[wheel_axis]}]'))
    return positions, layout, axis, wheel_axis


def sample(host, positions, commands, *, ticks=12, immediate=False):
    for command in commands:
        reply = host.command(command)
        assert not any('Unknown' in message or '<--[HERE]' in message for message in reply['messages']), reply
    coordinates = list(positions.values())
    roles = {pos: name for name, pos in positions.items()}
    states = []
    if immediate:
        states.append(dict(tick=0, blocks=[host.call('block', {'pos': pos}) for pos in coordinates]))
    observed = host.call('observe_ticks', {'ticks': ticks, 'positions': coordinates})
    states.extend(state for state in observed['samples'] if state['tick'] in (1, 2, 4, ticks))
    return dict(commands=commands, ticks=ticks, samples=[
        dict(tick=state['tick'], blocks={name: summarize(block, roles) for name, block in
                                        zip(positions, state['blocks'], strict=True)})
        for state in states])


def cases(host):
    for name, axis, side, speed, target in (
        ('default_cog', 0, 'cog', 32, None),
        ('slower_cog', 0, 'cog', 8, 24),
        ('faster_cog', 0, 'cog', 64, 24),
        ('negative_target_cog', 0, 'cog', 32, -24),
        ('negative_input_cog', 0, 'cog', -32, 24),
        ('zero_target_cog', 0, 'cog', 32, 0),
        ('default_shaft', 0, 'shaft', 32, None),
        ('slower_shaft', 0, 'shaft', 8, 24),
        ('faster_shaft', 0, 'shaft', 64, 24),
        ('negative_target_shaft', 0, 'shaft', 32, -24),
        ('negative_input_shaft', 0, 'shaft', -32, 24),
        ('zero_target_shaft', 0, 'shaft', 32, 0),
        ('other_horizontal_axis', 2, 'cog', 32, 24),
    ):
        positions, layout, shaft_axis, wheel_axis = fixture(axis, target=target)
        input_pos = positions['motor_' + side]
        power = put(input_pos, motor(wheel_axis if side == 'cog' else shaft_axis, speed))
        phases = {'unpowered': sample(host, positions, layout, ticks=4),
                  'connect': sample(host, positions, [power])}
        if name in ('default_cog', 'default_shaft', 'zero_target_cog', 'zero_target_shaft'):
            phases['cut'] = sample(host, positions, [put(input_pos, AIR)], immediate=True)
            phases['reconnect'] = sample(host, positions, [power], immediate=True)
        yield dict(name=name, positions=positions, phases=phases)

    for name, options in (
        ('parallel_cog', {'wheel_axis': 0}),
        ('vertical_cog', {'wheel_axis': 1}),
        ('small_cog', {'wheel': 'cogwheel'}),
        ('offset_cog', {'shifted': True}),
        ('no_cog', {'wheel': None}),
    ):
        positions, layout, shaft_axis, wheel_axis = fixture(0, target=24, **options)
        if name != 'no_cog':
            layout.append(put(positions['motor_cog'], motor(wheel_axis, 32)))
        phases = {'cog_side': sample(host, positions, layout),
                  'shaft_side': sample(host, positions, [put(positions['motor_shaft'], motor(shaft_axis, 64))])}
        yield dict(name=name, positions=positions, phases=phases)

    for first in ('cog', 'shaft'):
        second = 'shaft' if first == 'cog' else 'cog'
        for shaft_speed in (8, 64, -64):
            positions, layout, shaft_axis, wheel_axis = fixture(0, target=24)
            drives = dict(cog=put(positions['motor_cog'], motor(wheel_axis, 32)),
                          shaft=put(positions['motor_shaft'], motor(shaft_axis, shaft_speed)))
            phases = {'first': sample(host, positions, [*layout, drives[first]]),
                      'second': sample(host, positions, [drives[second]], immediate=True),
                      'remove_first': sample(host, positions, [put(positions['motor_' + first], AIR)], immediate=True),
                      'restore_first': sample(host, positions, [drives[first]], immediate=True)}
            yield dict(name=f'{first}_first_shaft_{shaft_speed}', positions=positions, phases=phases)


def latest(phase):
    return phase['samples'][-1]['blocks']


def network_field(block, name):
    return number({'nbt': block['network'] or ''}, name)


def network_id(block):
    return re.search(r'\bId:(-?\d+)L', block['network']).group(1)


def check_shared_stress(phase, powered, shaft_rpm, cog_rpm, previous_stress=None):
    for sample in phase['samples']:
        blocks = sample['blocks']
        controller = blocks['controller']
        group = network_id(controller)
        stress = (abs(shaft_rpm) + abs(cog_rpm)) * 4
        if sample['tick'] == 0 and previous_stress is not None:
            stress = previous_stress
        assert controller['rpm'] == shaft_rpm and blocks['cog']['rpm'] == cog_rpm, blocks
        assert network_field(controller, 'Stress') == stress, blocks
        assert network_field(controller, 'Capacity') == 32 * 16384, blocks
        assert controller['source'] == ('cog' if powered == 'cog' else 'shaft_in'), blocks
        for side, rpm in [('shaft', shaft_rpm), ('cog', cog_rpm)]:
            load = blocks['load_' + side]
            assert load['rpm'] == rpm, (side, blocks)
            if rpm:
                assert network_id(load) == group and network_field(load, 'Stress') == stress, blocks
            else:
                assert load['network'] is None, blocks


def set_live_value(host, work, row, raw):
    x, y, z = CENTER
    host.command('gamemode creative')
    host.command('item replace entity @s weapon.mainhand with minecraft:air')
    host.call('camera', {'position': [x + .5, y, z + 3.7], 'target': [x + .5, y + 11 / 16, z + 1]})
    host.call('capture', {'name': f'{work.name}/controller-aim-{row}-{raw}.png', 'frames': 6})
    hit = host.call('state', {})['hit']
    assert hit['pos'] == list(CENTER) and hit['face'] == 'south', hit
    host.call('input', {'key': 'use', 'down': True})
    try:
        for _ in range(6):
            host.call('capture', {'name': f'{work.name}/controller-board-{row}-{raw}.png', 'frames': 12})
            ui = host.call('ui', {})
            if 'value_settings' in ui:
                break
        board = ui['value_settings']
        assert board['title']['text'] == 'Targeted Speed in RPM', board
        assert board['max_value'] == 256 and board['milestone_interval'] == 32, board
        assert [option['text'] for option in board['rows']] == ['⟳', '⟲'], board
        point = next(value for value in board['sample_coordinates']
                     if (value['row'], value['value']) == (row, raw))
        x, y = point['gui_coordinate']
        host.call('input', {'kind': 'move', 'x': x, 'y': y})
        host.call('capture', {'name': f'{work.name}/controller-setting-{row}-{raw}.png', 'frames': 6})
        hovered = host.call('ui', {})['value_settings']['hovered']
        assert (hovered['row'], hovered['value']) == (row, raw), hovered
        host.call('input', {'kind': 'mouse', 'button': 1, 'x': x, 'y': y, 'down': False})
    finally:
        host.call('input', {'key': 'use', 'down': False})
    expected = max(1, raw) * (1 if row == 1 else -1)
    for _ in range(4):
        host.call('capture', {'name': f'{work.name}/controller-saved-{row}-{raw}.png', 'frames': 8})
        saved = host.call('block', {'pos': CENTER})
        if number(saved, 'ScrollValue') == expected:
            break
    else:
        raise AssertionError(saved)
    return {'title': board['title'], 'max_value': board['max_value'], 'rows': board['rows'],
            'initial': board['initial'], 'selected': hovered}


def stress_cases(host, work, report):
    for side in ('cog', 'shaft'):
        for setting in (24, 0):
            positions, layout, shaft_axis, cog_axis = fixture(0, target=setting)
            positions['load_shaft'] = offset(CENTER, shaft_axis, 2)
            positions['load_cog'] = offset(positions['cog'], cog_axis, 1)
            layout.extend([
                put(positions['load_shaft'], 'create:mechanical_drill[facing=east]'),
                put(positions['load_cog'], 'create:mechanical_drill[facing=south]'),
            ])
            use_board = side == 'shaft' and setting == 24
            if use_board:
                layout.extend([
                    put(positions['wrong_face'], AIR),
                    'fill 1654 179 648 1656 179 651 minecraft:smooth_stone',
                ])
            power_axis = cog_axis if side == 'cog' else shaft_axis
            setup = [*layout, put(positions['motor_' + side], motor(power_axis, 32))]
            phases = {}
            active = dict(name=f'{side}_load_target_{setting}', positions=positions, phases=phases)
            report['active'] = active
            phases['connected'] = sample(host, positions, setup)
            shaft_rpm, cog_rpm = (setting, 32) if side == 'cog' else (32, setting)
            check_shared_stress(phases['connected'], side, shaft_rpm, cog_rpm)
            if use_board:
                phases['raw_edit'] = sample(host, positions, [
                    f'data merge block {xyz(CENTER)} {{ScrollValue:64}}',
                ], immediate=True)
                for observed in phases['raw_edit']['samples']:
                    edited = observed['blocks']
                    assert edited['controller']['scroll'] == 64, edited
                    assert edited['controller']['rpm'] == 0 and edited['controller']['source'] is None, edited
                    assert edited['controller']['network'] is None, edited
                    assert (edited['load_shaft']['rpm'], edited['load_cog']['rpm']) == (32, 24), edited
                phases['reset_after_raw_edit'] = sample(host, positions, setup)
                check_shared_stress(phases['reset_after_raw_edit'], side, 32, 24)
                phases['gui_reverse'] = dict(board=set_live_value(host, work, 0, 32),
                                             **sample(host, positions, [], immediate=True))
                reverse = latest(phases['gui_reverse'])
                assert reverse['controller']['scroll'] == -32, reverse
                check_shared_stress(phases['gui_reverse'], side, 32, -32, previous_stress=224)
                phases['gui_minimum'] = dict(board=set_live_value(host, work, 1, 0),
                                             **sample(host, positions, [], immediate=True))
                minimum = latest(phases['gui_minimum'])
                assert minimum['controller']['scroll'] == 1, minimum
                check_shared_stress(phases['gui_minimum'], side, 32, 1, previous_stress=256)
            yield active
            report.pop('active')

    positions, layout, _, cog_axis = fixture(0, wheel=None, target=24)
    phases = {'connected': sample(host, positions, [
        *layout, put(positions['cog'], 'create:andesite_encased_large_cogwheel[axis=z,bottom_shaft=true]'),
        put(positions['motor_cog'], motor(cog_axis, 32)),
    ])}
    connected = latest(phases['connected'])
    assert connected['controller']['source'] == 'cog', connected
    assert [connected[key]['rpm'] for key in ('cog', 'controller', 'shaft_out')] == [32, 24, 24], connected
    yield dict(name='encased_large_cog_input', positions=positions, phases=phases)


def verify(results):
    def at(name, phase, tick=-1):
        samples = results[name]['phases'][phase]['samples']
        return (samples[-1] if tick < 0 else next(s for s in samples if s['tick'] == tick))['blocks']

    def rpm(blocks, *roles):
        return tuple(blocks[role]['rpm'] for role in roles)

    for case in results.values():
        for phase in case['phases'].values():
            for sample in phase['samples']:
                block = sample['blocks']['wrong_face']
                assert block['block'] == 'create:shaft' and block['rpm'] == 0 and block['source'] is None, case

    for name, scroll, cog_rpm, shaft_rpm, owner in (
        ('default_cog', 16, 32, 16, 'cog'),
        ('slower_cog', 24, 8, 24, 'cog'),
        ('faster_cog', 24, 64, 24, 'cog'),
        ('negative_target_cog', -24, 32, -24, 'cog'),
        ('negative_input_cog', 24, -32, 24, 'cog'),
        ('zero_target_cog', 0, 32, 0, 'cog'),
        ('default_shaft', 16, 16, 32, 'shaft_in'),
        ('slower_shaft', 24, 24, 8, 'shaft_in'),
        ('faster_shaft', 24, 24, 64, 'shaft_in'),
        ('negative_target_shaft', -24, -24, 32, 'shaft_in'),
        ('negative_input_shaft', 24, 24, -32, 'shaft_in'),
        ('zero_target_shaft', 0, 0, 32, 'shaft_in'),
        ('other_horizontal_axis', 24, 32, 24, 'cog'),
    ):
        blocks = at(name, 'connect', 1)
        controller = blocks['controller']
        assert controller['scroll'] == scroll and controller['source'] == owner, (name, blocks)
        expected = (cog_rpm, shaft_rpm, shaft_rpm, shaft_rpm)
        assert rpm(blocks, 'cog', 'controller', 'shaft_in', 'shaft_out') == expected, (name, blocks)
        assert network_id(controller) == network_id(blocks['cog']), (name, blocks)
        assert ('Size:3,' if shaft_rpm == 0 else 'Size:5,') in controller['network'], (name, blocks)
        assert (blocks['shaft_out']['network'] is None) == (shaft_rpm == 0), (name, blocks)
        if 'cut' in results[name]['phases']:
            for tick in (0, 1, 2, 4, 12):
                cut = at(name, 'cut', tick)
                assert rpm(cut, 'cog', 'controller', 'shaft_in', 'shaft_out') == (0, 0, 0, 0), (name, cut)
                assert cut['controller']['source'] is None, (name, cut)
            assert at(name, 'reconnect', 0)['controller']['source'] is None, name
            assert at(name, 'reconnect', 1) == blocks, name

    for name in ('parallel_cog', 'vertical_cog', 'small_cog', 'offset_cog', 'no_cog'):
        cog_rpm = 0 if name == 'no_cog' else 32
        assert rpm(at(name, 'cog_side'), 'cog', 'controller', 'shaft_out') == (cog_rpm, 0, 0), name
        assert rpm(at(name, 'shaft_side'), 'cog', 'controller', 'shaft_out') == (cog_rpm, 64, 64), name

    for name, phase, owner, motor_owner, speeds in (
        ('cog_first_shaft_8', 'second', 'cog', 'shaft_in', (32, 24, 24)),
        ('cog_first_shaft_8', 'remove_first', 'shaft_in', None, (24, 8, 8)),
        ('cog_first_shaft_64', 'second', 'shaft_in', None, (32, 64, 64)),
        ('cog_first_shaft_-64', 'second', 'cog', 'shaft_in', (32, 24, 24)),
        ('cog_first_shaft_-64', 'remove_first', 'shaft_in', None, (24, -64, -64)),
        ('shaft_first_shaft_8', 'second', 'cog', 'shaft_in', (32, 24, 24)),
        ('shaft_first_shaft_64', 'second', 'cog', 'shaft_in', (32, 64, 64)),
        ('shaft_first_shaft_64', 'remove_first', 'cog', None, (32, 64, 0)),
    ):
        blocks = at(name, phase)
        assert blocks['controller']['source'] == owner, (name, phase, blocks)
        assert blocks['motor_shaft']['source'] == motor_owner, (name, phase, blocks)
        assert rpm(blocks, 'cog', 'controller', 'motor_shaft') == speeds, (name, phase, blocks)
    for name, phase in (('cog_first_shaft_-64', 'restore_first'), ('shaft_first_shaft_-64', 'second')):
        assert at(name, phase)['controller']['block'] == AIR, (name, phase)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stress-only', action='store_true', help='Run the live stress and settings cases')
    args = parser.parse_args()
    host = Original()
    work = Path(tempfile.mkdtemp(prefix='speed-controller-java-', dir=ROOT / '.local'))
    report = dict(passed=False, scope=__doc__, create_revision=PINS['create_revision'],
                  create_sha256=CREATE_SHA256,
                  fixture_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), cases=[])
    try:
        manifest = json.loads((BASE / 'manifest.json').read_text())
        assert manifest['create_sha256'] == CREATE_SHA256
        state = host.call('state', {})
        assert state['ready'] and state['data_version'] == 3955, state
        host.call('tick', {'frozen': True})
        host.command(f'forceload add {FORCE_RANGE}')
        try:
            host.call('observe_ticks', {'ticks': 40, 'positions': [list(map(int, state['position']))]})
            if not args.stress_only:
                for case in cases(host):
                    report['cases'].append(case)
                verify({case['name']: case for case in report['cases']})
            for case in stress_cases(host, work, report):
                report['cases'].append(case)
        finally:
            host.command(CLEAR)
            host.command(f'forceload remove {FORCE_RANGE}')
            host.call('camera', {'position': state['position'], 'yaw': state['yaw'], 'pitch': state['pitch']})
            host.call('tick', {'frozen': state['server']['frozen']})
        report['passed'] = True
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        # Keep command/bridge diagnostics without duplicating the full tick trace.
        transcript = [entry for entry in host.trace if entry['method'] != 'observe_ticks']
        (work / 'transcript.json').write_text(json.dumps(transcript, indent=2) + '\n')
        print(json.dumps({'passed': report['passed'], 'cases': len(report['cases']),
                          'result': str(work / 'result.json')}), flush=True)


if __name__ == '__main__':
    main()
