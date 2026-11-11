#!/usr/bin/env python3
"""Observe final Press/Basin behaviour through ordinary authoritative ticks.

The four 180-tick scenes use the same coordinates, creation commands and real
motor replacement as press_basin_reference.py. Canonical fixtures seed stocks;
no machine method, forced counter, trait registration or replacement clock is
used. Creation order is not asserted to determine internal BE tick order.
Absolute trace differences are retained without an alignment offset. Additional
native controls cover components, real cold reload, zero/reversed/overloaded
rotation, lava compacting and refusal of a Mixer-only alloy recipe. No render,
sound or client-particle parity claim is made.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from burner_heat_java_checks import field, items, number
from common import PINS
from native_check_session import NativeCheckSession

BASIN = '580 64 30'
PRESS = '580 66 30'
MOTOR = '578 66 30'
FIELDS = ('Running', 'Ticks', 'Mode', 'Finished', 'NeedsUpdate', 'Speed')
MARKER = 'components:{"minecraft:custom_data":{press_marker:913}}'


def text(row):
    return ' '.join(''.join(span[0] for span in message) for message in row['messages'])


def snapshot(raw, tick):
    values = {key: number({'nbt': raw['press']}, key) for key in FIELDS}
    return dict(tick=tick, time=int(re.findall(r'\b\d+\b', raw['clock'])[0]),
                fields=values, inputs=items(raw['basin'], 'InputItems'),
                outputs=items(raw['basin'], 'OutputItems'), raw=raw)


def run(game, resources, ctl, create_jar, reference, build_result):
    source = json.loads(Path(reference).read_text())
    build = json.loads(Path(build_result).read_text())
    assert source['passed'] and source['create'] == PINS['create_revision']
    assert build['passed'] and Path(build['game']).resolve() == Path(game).resolve()
    session = NativeCheckSession(game, resources, ctl, create_jar,
                                 name='press-basin-native', graphics=False, world='CreatePressBasinFinal')
    game_hash = hashlib.sha256(session.game.read_bytes()).hexdigest()
    assert game_hash == build['game_sha256']
    report = dict(passed=False, completed=False, scope=__doc__, horizon=build['horizon'],
                  create=source['create'], game=str(session.game), game_sha256=game_hash,
                  fixture_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  build_receipt_sha256=hashlib.sha256(Path(build_result).read_bytes()).hexdigest(),
                  reference_sha256=hashlib.sha256(Path(reference).read_bytes()).hexdigest(),
                  cases=[], controls={}, differences=[], process_runs=[])

    def save():
        (session.scratch / 'result.json').write_text(json.dumps(report, indent=2) + '\n')

    def execute(ops, labels, name):
        script = session.scratch / (name + '-commands.jsonl')
        output = session.scratch / (name + '-observations.jsonl')
        script.write_text(''.join(json.dumps(op) + '\n' for op in ops))
        env = session.env.copy()
        env.update(HORIZON_COMMAND_SCRIPT=str(script), HORIZON_COMMAND_OUTPUT=str(output),
                   HORIZON_API_DISCOVERY='http://127.0.0.1:9/')
        with session.log.open('a') as log:
            process = subprocess.run([str(session.game), '--headless', '--resources', str(session.resources),
                '--world', 'CreatePressBasinFinal', '--seed', '5', '--creative', '--render-distance', '2',
                '--name', 'PressBasinProbe'], cwd=session.scratch, env=env,
                stdout=log, stderr=subprocess.STDOUT, timeout=420)
        report['process_runs'].append(dict(name=name, exit=process.returncode,
                                           script_sha256=hashlib.sha256(script.read_bytes()).hexdigest()))
        save()
        assert process.returncode == 0, (name, process.returncode, str(session.log))
        rows = [json.loads(line) for line in output.read_text().splitlines()]
        assert len(rows) == len(labels), (name, len(rows), len(labels))
        groups = {}
        for label, row in zip(labels, rows):
            group, index, key = label
            assert row['results'] and all(r[0] for r in row['results']), (label, row)
            groups.setdefault(group, {}).setdefault(index, {})[key] = text(row)
        parsed = {group: [snapshot(raw, index) for index, raw in sorted(indices.items())]
                  for group, indices in groups.items()}
        for samples in parsed.values():
            assert all(b['time'] == a['time'] + 1 for a, b in zip(samples, samples[1:])), name
        return parsed

    ops, labels = [], []

    def cmd(value):
        ops.append(dict(op='cmd', cmd=value, record=False))

    def ticks(n):
        ops.append(dict(op='tick', n=n))

    def observe(group, n, start=1):
        for i in range(start, start + n):
            ticks(1)
            for key, value in [('clock', 'time query gametime'),
                               ('press', 'data get block ' + PRESS),
                               ('basin', 'data get block ' + BASIN)]:
                ops.append(dict(op='cmd', cmd=value, record=True))
                labels.append((group, i, key))

    def stock(stacks, *, lava=0, marked=False):
        entries = ['{Slot:' + str(i) + ',id:"' + item + '",count:' + str(count)
                   + (',' + MARKER if marked else '') + '}' for i, (item, count) in enumerate(stacks)]
        tanks = ''
        if lava:
            level = 'Level:{Speed:0.25f,Target:' + str(lava / 1000) + 'f,Value:' + str(lava / 1000) + 'f}'
            tanks = ',InputTanks:[{' + level + ',TankContent:{Fluid:{id:"minecraft:lava",amount:'
            tanks += str(lava) + '}}},{Level:{Speed:0.25f,Target:0.0f,Value:0.0f},TankContent:{}}]'
        cmd('data merge block ' + BASIN + ' {InputItems:{Size:9,Items:[' + ','.join(entries)
            + ']},OutputItems:{Size:9,Items:[]}' + tanks + ',fixture_unknown:{retained:913L}}')

    def setup(basin_first=True):
        cmd('fill 577 64 28 582 69 32 minecraft:air')
        actors = [(BASIN, 'create:basin[facing=down]'),
                  (PRESS, 'create:mechanical_press[facing=east]')]
        if not basin_first: actors.reverse()
        for pos, block in actors: cmd('setblock ' + pos + ' ' + block)
        cmd('setblock 579 66 30 create:shaft[axis=x]')
        cmd('setblock ' + MOTOR + ' create:creative_motor[facing=east]')
        cmd('data merge block ' + MOTOR + ' {ScrollValue:0}')
        ticks(30)

    def power(rpm):
        cmd('setblock ' + MOTOR + ' minecraft:air')
        cmd('setblock ' + MOTOR + ' create:creative_motor[facing=east]')
        cmd('data merge block ' + MOTOR + ' {ScrollValue:' + str(rpm) + '}')

    cmd('tick unfreeze'); cmd('gamemode creative'); cmd('tp @s 584.5 72 34.5')
    ops.append(dict(op='settle'))
    cmd('forceload add 576 16 591 47')
    cmd('fill 577 63 28 582 63 32 minecraft:smooth_stone')
    for index, case in enumerate(source['cases']):
        setup(case['basin_created_first']); stock(list(case['input'].items())); power(32)
        observe('reference-' + str(index), 180)
    setup(); stock([('minecraft:snowball', 8)]); observe('zero', 64)
    setup(); stock([('minecraft:snowball', 8)], marked=True); power(-32); observe('negative', 180)
    setup(); stock([('minecraft:flint', 2), ('minecraft:gravel', 1)], lava=100)
    power(32); observe('lava-andesite', 100)
    setup(); stock([('minecraft:andesite', 2), ('minecraft:iron_nugget', 2)], lava=100)
    power(32); observe('mixer-only-refusal', 100)
    setup(); stock([('minecraft:snowball', 12)], marked=True); power(32)
    observe('restart-before-pause', 50)
    power(0); observe('restart-paused', 8)
    cmd('save-all flush')
    print(json.dumps(dict(scratch=str(session.scratch))), flush=True)
    save()
    try:
        observed = execute(ops, labels, 'first-process')
        for index, case in enumerate(source['cases']):
            native = observed['reference-' + str(index)]
            differences = []
            for actual, original in zip(native, case['samples']):
                expected = {key: number(original['blocks'][1], key) for key in FIELDS}
                for key in FIELDS:
                    if actual['fields'][key] != expected[key]:
                        differences.append(dict(tick=actual['tick'], field=key,
                                                native=actual['fields'][key], original=expected[key]))
                for key, inventory in [('inputs', 'InputItems'), ('outputs', 'OutputItems')]:
                    wanted = items(original['blocks'][0]['nbt'], inventory)
                    if actual[key] != wanted:
                        differences.append(dict(tick=actual['tick'], field=key,
                                                native=actual[key], original=wanted))
            impacts, previous = [], {}
            for sample in native:
                if sample['outputs'] != previous:
                    impacts.append(dict(tick=sample['tick'], outputs=sample['outputs']))
                previous = sample['outputs']
            first_running = next((s['tick'] for s in native if s['fields']['Running']), None)
            original_first_running = next((s['tick'] for s in case['samples']
                                           if number(s['blocks'][1], 'Running')), None)
            report['cases'].append(dict(input=case['input'], basin_created_first=case['basin_created_first'],
                samples=native, impacts=impacts, original_impact_ticks=[i['tick'] for i in case['impacts']],
                first_running_tick=first_running, original_first_running_tick=original_first_running,
                strict_sequence_equal=not differences, differences=differences))
            report['differences'].extend(dict(case=index, **d) for d in differences)
            assert native[-1]['inputs'] == {} and native[-1]['outputs'] == case['expected'], native[-1]
        report['controls'] = {key: value for key, value in observed.items() if not key.startswith('reference-')}
        save()
        zero = observed['zero']
        assert all(s['fields']['Speed'] == 0 and s['fields']['Running'] == 0 and s['fields']['Ticks'] == 0
                   and s['inputs'] == {'minecraft:snowball': 8} and not s['outputs'] for s in zero)
        negative = observed['negative']
        assert negative[-1]['outputs'] == {'minecraft:snow_block': 2} and not negative[-1]['inputs']
        assert all(s['fields']['Speed'] == -32 for s in negative[5:])
        assert 'press_marker' not in field(negative[-1]['raw']['basin'], 'OutputItems')
        lava = observed['lava-andesite'][-1]
        assert lava['outputs'] == {'minecraft:andesite': 1} and not lava['inputs'], lava
        assert not re.search(r'\bamount\s*:\s*[1-9]', field(lava['raw']['basin'], 'InputTanks'))
        refused = observed['mixer-only-refusal']
        assert all(not s['outputs'] and s['fields']['Running'] == 0
                   and s['inputs'] == {'minecraft:andesite': 2, 'minecraft:iron_nugget': 2}
                   for s in refused)
        paused = observed['restart-paused'][-1]
        stopped = [s for s in observed['restart-paused'] if s['fields']['Speed'] == 0]
        assert len(stopped) >= 6 and len({s['fields']['Ticks'] for s in stopped}) == 1
        assert paused['outputs'] == {'minecraft:snow_block': 1} and paused['inputs'] == {'minecraft:snowball': 8}
        assert 'press_marker' in field(paused['raw']['basin'], 'InputItems')
        assert 'press_marker' not in field(paused['raw']['basin'], 'OutputItems')
        ops.clear(); labels.clear()
        cmd('tick unfreeze'); observe('restart-still-paused', 8)
        power(32); observe('restart-resumed', 230)
        resumed = execute(ops, labels, 'second-process')
        cold = resumed['restart-still-paused'][-1]
        assert cold['inputs'] == paused['inputs'] and cold['outputs'] == paused['outputs']
        for key in ('Running', 'Ticks', 'Mode', 'Finished'):
            assert cold['fields'][key] == paused['fields'][key], (key, cold, paused)
        assert 'press_marker' in field(cold['raw']['basin'], 'InputItems')
        assert re.search(r'\bretained:\s*913L\b', field(cold['raw']['basin'], 'fixture_unknown'))
        final = resumed['restart-resumed'][-1]
        assert not final['inputs'] and final['outputs'] == {'minecraft:snow_block': 3}, final
        assert 'press_marker' not in field(final['raw']['basin'], 'OutputItems')
        report['controls'].update(resumed)
        report['controls']['overload_ordinary_interaction'] = ordinary_overload(session)
        report['completed'] = True
        report['absolute_trace_equal'] = not report['differences']
        report['controls_passed'] = True
        report['passed'] = report['absolute_trace_equal']
        save()
        assert report['passed'], ('Absolute source trace differs; see unshifted saved fields', len(report['differences']))
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        save(); session.control_temp.cleanup()
        print(json.dumps(dict(passed=report['passed'], completed=report['completed'],
                              result=str(session.scratch / 'result.json'))), flush=True)
    return report


def ordinary_overload(session):
    """A real crank use publishes rotation; editing InUse is not a turn."""
    from native_check_session import wait_loaded
    result = dict(passed=False, ordinary_use=True, samples=[])
    session.start()
    try:
        call = session.call
        call('command', 'tick freeze')
        call('command', 'gamemode creative')
        call('command', 'tp @s 578.5 66 33')
        call('command', 'forceload add 576 16 591 47')
        call('wait-ready', 120)
        wait_loaded(call, [(578, 66, 30), (581, 66, 30)])
        call('command', 'fill 577 64 28 582 69 32 minecraft:air')
        for pos, block in [(MOTOR, 'create:hand_crank[facing=west]'),
                           ('579 66 30', 'create:shaft[axis=x]'),
                           (PRESS, 'create:mechanical_press[facing=east]'),
                           ('581 66 30', 'create:mechanical_press[facing=east]'),
                           (BASIN, 'create:basin[facing=down]')]:
            call('command', 'setblock ' + pos + ' ' + block)
        call('command', 'data merge block ' + BASIN + ' {InputItems:{Size:9,Items:[{Slot:0,id:"minecraft:snowball",count:8}]},OutputItems:{Size:9,Items:[]}}')
        call('command', 'clear @s')
        call('command', 'fill 577 65 32 579 65 34 minecraft:smooth_stone')
        call('command', 'tp @s 578.5 66 33.5')
        call('look-at', 578.5, 66.5, 30.5)
        call('interact', 578, 66, 30, 'south')
        call('wait', 2)
        for _ in range(3):
            call('command', 'tick unfreeze')
            call('wait', 1)
            call('command', 'tick freeze')
            press = ' '.join(call('command', 'data get block ' + PRESS)['chat'])
            basin = ' '.join(call('command', 'data get block ' + BASIN)['chat'])
            crank = ' '.join(call('command', 'data get block ' + MOTOR)['chat'])
            sample = dict(press=press, basin=basin, crank=crank)
            result['samples'].append(sample)
            assert number({'nbt': press}, 'Stress') > number({'nbt': press}, 'Capacity') > 0, sample
            assert number({'nbt': press}, 'Speed') == 0 and number({'nbt': press}, 'Ticks') == 0, sample
            assert items(basin, 'InputItems') == {'minecraft:snowball': 8} and items(basin, 'OutputItems') == {}, sample
            assert number({'nbt': crank}, 'InUse') > 0, sample
            call('interact', 578, 66, 30, 'south')
            call('wait', 1)
        result['passed'] = True
        return result
    finally:
        session.stop()


def startup_matrix(game, resources, ctl, create_jar, reference, build_result):
    """Compare event-driven startup without shifting either client's clock.

    The ordinary GUI callback is covered separately from this command harness;
    an isolated Speed-field seed is not a valid saved-network fixture.
    """
    source = json.loads(Path(reference).read_text())
    build = json.loads(Path(build_result).read_text())
    assert source['passed'] and source['create'] == PINS['create_revision']
    assert build['passed'] and Path(build['game']).resolve() == Path(game).resolve()
    session = NativeCheckSession(game, resources, ctl, create_jar, name='press-startup-native', graphics=False)
    report = dict(passed=False, scope=startup_matrix.__doc__, horizon=build['horizon'], cases=[], differences=[],
                  game_sha256=hashlib.sha256(session.game.read_bytes()).hexdigest(),
                  reference_sha256=hashlib.sha256(Path(reference).read_bytes()).hexdigest(),
                  fixture_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  skipped_source_cases=['isolated_speed_field_without_network', 'ordinary_gui_zero_to_32'])
    assert report['game_sha256'] == build['game_sha256']
    ops, labels = [], []

    def save():
        (session.scratch / 'result.json').write_text(json.dumps(report, indent=2) + '\n')

    def command(value):
        ops.append(dict(op='cmd', cmd=value, record=False))

    def ticks(count):
        ops.append(dict(op='tick', n=count))

    def observe(group, count):
        for tick in range(1, count + 1):
            ticks(1)
            for key, value in [('clock', 'time query gametime'), ('press', 'data get block 620 66 30'),
                               ('basin', 'data get block 620 64 30')]:
                ops.append(dict(op='cmd', cmd=value, record=True))
                labels.append((group, tick, key))

    command('tick unfreeze'); command('gamemode creative'); command('tp @s 624.5 72 34.5')
    ops.append(dict(op='settle'))
    command('forceload add 608 16 639 47')
    command('fill 617 63 28 622 63 32 minecraft:smooth_stone')
    selected = [row for row in source['cases'] if row['name'] not in report['skipped_source_cases']]
    for row in selected:
        name = row['name']
        clutch = name.startswith('clutch_open_')
        settled = name in ('replaced_motor_last', 'data_read_existing_zero') or clutch
        command('fill 617 64 28 622 69 32 minecraft:air')
        blocks = dict(B='620 64 30 create:basin[facing=down]',
                      P='620 66 30 create:mechanical_press[facing=east]',
                      M='618 66 30 create:creative_motor[facing=east]',
                      S='619 66 30 create:' + ('clutch[axis=x,powered=true]' if clutch else 'shaft[axis=x]'))
        for role in row['creation_order']:
            command('setblock ' + blocks[role])
        command('data merge block 618 66 30 {ScrollValue:' + ('32' if clutch or not settled else '0') + '}')
        if clutch:
            command('setblock 619 67 30 minecraft:lever[face=floor,facing=north,powered=true]')
        if settled:
            ticks(30)
        command('data merge block 620 64 30 {InputItems:{Size:9,Items:[{Slot:0,id:"minecraft:snowball",count:8}]},OutputItems:{Size:9,Items:[]}}')
        if name == 'replaced_motor_last':
            command('setblock 618 66 30 minecraft:air')
            command('setblock 618 66 30 create:creative_motor[facing=east]')
            command('data merge block 618 66 30 {ScrollValue:32}')
        elif name == 'data_read_existing_zero':
            command('data merge block 618 66 30 {ScrollValue:32}')
        elif clutch:
            command('setblock 619 67 30 minecraft:lever[face=floor,facing=north,powered=false]')
        observe(name, len(row['samples']))
    script, output = session.scratch / 'commands.jsonl', session.scratch / 'observations.jsonl'
    script.write_text(''.join(json.dumps(op) + '\n' for op in ops))
    env = session.env.copy()
    env.update(HORIZON_COMMAND_SCRIPT=str(script), HORIZON_COMMAND_OUTPUT=str(output),
               HORIZON_API_DISCOVERY='http://127.0.0.1:9/')
    print(json.dumps(dict(scratch=str(session.scratch))), flush=True)
    save()
    try:
        with session.log.open('w') as log:
            process = subprocess.run([str(session.game), '--headless', '--resources', str(session.resources),
                '--world', 'CreatePressStartup', '--seed', '5', '--creative', '--render-distance', '2'],
                cwd=session.scratch, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=420)
        report['exit'] = process.returncode
        assert process.returncode == 0, str(session.log)
        rows = [json.loads(line) for line in output.read_text().splitlines()]
        assert len(rows) == len(labels)
        groups = {}
        for (group, index, key), row in zip(labels, rows):
            assert row['results'] and all(r[0] for r in row['results']), (group, row)
            groups.setdefault(group, {}).setdefault(index, {})[key] = text(row)
        turns = [json.loads(line.split('Create kinetic turn: ', 1)[1])
                 for line in session.log.read_text().splitlines() if 'Create kinetic turn: ' in line]
        report['actual_first_native_turns'] = turns
        for case in selected:
            samples = [snapshot(raw, tick) for tick, raw in sorted(groups[case['name']].items())]
            assert all(b['time'] == a['time'] + 1 for a, b in zip(samples, samples[1:]))
            differences = []
            for actual, original in zip(samples, case['samples']):
                expected = {key: number(original['blocks'][1], key) for key in FIELDS}
                for key in FIELDS:
                    if actual['fields'][key] != expected[key]:
                        differences.append(dict(tick=actual['tick'], field=key, native=actual['fields'][key], original=expected[key]))
                for key, inventory in [('inputs', 'InputItems'), ('outputs', 'OutputItems')]:
                    expected = items(original['blocks'][0]['nbt'], inventory)
                    if actual[key] != expected:
                        differences.append(dict(tick=actual['tick'], field=key, native=actual[key], original=expected))
            order = [turn['pos'] for turn in turns if turn['time'] == samples[0]['time']]
            if case['name'].startswith('fresh_motor_'):
                assert [618, 66, 30] in order and [620, 66, 30] in order, order
                assert (order.index([618, 66, 30]) < order.index([620, 66, 30])) == case['motor_ticks_before_press'], order
            row = dict(name=case['name'], samples=samples, actual_first_turn_order=order,
                       source_first_turn_order=case['samples'][0]['ticker_order'], differences=differences)
            report['cases'].append(row)
            report['differences'].extend(dict(case=case['name'], **d) for d in differences)
            save()
        report['completed'] = True
        report['passed'] = not report['differences']
        assert report['passed'], ('Absolute event traces differ', len(report['differences']))
        return report
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        save()
        session.control_temp.cleanup()
        print(json.dumps(dict(passed=report['passed'], result=str(session.scratch / 'result.json'))), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'resources', 'ctl', 'create-jar', 'reference', 'build-result'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--startup-matrix', action='store_true')
    args = parser.parse_args()
    (startup_matrix if args.startup_matrix else run)(args.game, args.resources, args.ctl, args.create_jar, args.reference, args.build_result)
