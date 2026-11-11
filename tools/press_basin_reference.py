#!/usr/bin/env python3
"""Observe ordinary original Create press/Basin cycles in the private reference.

The caller exclusively leases the already-running disposable Java instance.
Canonical inventory seeds and a real motor replacement provide the inputs and
speed-change event. Samples are normal ServerTick.Post observations; no press
method, forced machine counter, schematic import or render comparison is used.
Creation order is recorded separately from internal block-entity tick order.
"""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import time

from common import ROOT, PINS
from burner_heat_java_checks import items, number
import reference_java as java

BASIN = [580, 64, 30]
PRESS = [580, 66, 30]
MOTOR = [578, 66, 30]


def run():
    base = java.BASE.resolve()
    manifest = json.loads((base / 'manifest.json').read_text())
    assert manifest['data_version'] == 3955 and manifest['create_sha256'] == java.CREATE_SHA256
    work = Path(tempfile.mkdtemp(prefix='press-basin-java-', dir=ROOT / '.local'))
    report = {'passed': False, 'scope': __doc__, 'create': PINS['create_revision'],
              'fixture_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'cases': []}
    transcript = []

    def save():
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        (work / 'transcript.json').write_text(json.dumps(transcript, indent=2) + '\n')

    def call(method, body):
        reply = java.call(base, method, body)
        transcript.append({'method': method, 'body': body, 'reply': reply})
        save()
        return reply

    def command(value):
        return call('command', {'command': value})

    def observe(ticks):
        before = call('state', {})['server']['game_time']
        result = call('observe_ticks', {'ticks': ticks, 'positions': [BASIN, PRESS]})
        assert [s['game_time'] for s in result['samples']] == list(range(before + 1, before + ticks + 1))
        assert call('state', {})['server']['frozen']
        return result['samples']

    print(json.dumps({'work': str(work)}), flush=True)
    initial = call('state', {})
    if initial.get('screen') == 'PauseScreen':
        call('input', {'kind': 'escape'})
        initial = call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955
    try:
        call('tick', {'frozen': True})
        command('gamemode creative')
        command('forceload add 576 16 591 47')
        command('fill 577 63 28 582 63 32 minecraft:smooth_stone')
        for item, count, output, amount in [
            ('minecraft:snowball', 8, 'minecraft:snow_block', 2),
            ('minecraft:snow_block', 9, 'minecraft:ice', 1),
        ]:
            for basin_first in [True, False]:
                row = {'input': {item: count}, 'expected': {output: amount},
                       'basin_created_first': basin_first}
                report['active_case'] = row
                command('fill 577 64 28 582 69 32 minecraft:air')
                actors = [('580 64 30', 'create:basin[facing=down]'),
                          # MechanicalPressBlock.getRotationAxis uses facing's
                          # axis; the original east/west ports face this shaft.
                          ('580 66 30', 'create:mechanical_press[facing=east]')]
                if not basin_first:
                    actors.reverse()
                for pos, block in actors:
                    command('setblock ' + pos + ' ' + block)
                command('setblock 579 66 30 create:shaft[axis=x]')
                command('setblock 578 66 30 create:creative_motor[facing=east]')
                command('data merge block 578 66 30 {ScrollValue:0}')
                row['settled'] = observe(30)[-1]
                assert number(row['settled']['blocks'][1], 'Speed') == 0
                command('data merge block 580 64 30 {InputItems:{Size:9,Items:[{Slot:0,id:"' +
                        item + '",count:' + str(count) + '}]},OutputItems:{Size:9,Items:[]}}')
                command('setblock 578 66 30 minecraft:air')
                command('setblock 578 66 30 create:creative_motor[facing=east]')
                command('data merge block 578 66 30 {ScrollValue:32}')
                row['samples'] = observe(180)
                for sample in row['samples']:
                    press = sample['blocks'][1]
                    assert abs(number(press, 'Speed')) in (0, 32)
                last = row['samples'][-1]
                assert abs(number(last['blocks'][1], 'Speed')) == 32
                assert items(last['blocks'][0]['nbt'], 'InputItems') == {}
                assert items(last['blocks'][0]['nbt'], 'OutputItems') == {output: amount}
                impacts = []
                previous = 0
                for sample in row['samples']:
                    current = items(sample['blocks'][0]['nbt'], 'OutputItems').get(output, 0)
                    if current != previous:
                        impacts.append({'tick': sample['tick'], 'time': sample['game_time'],
                                        'amount': current, 'press': sample['blocks'][1]})
                    previous = current
                assert len(impacts) == amount, impacts
                row['impacts'] = impacts
                report['cases'].append(row)
                report.pop('active_case', None)
                save()
                print(json.dumps({'input': item, 'basin_first': basin_first, 'impacts':
                                  [s['tick'] for s in impacts]}), flush=True)
        report['passed'] = True
        return report
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        call('tick', {'frozen': True})
        call('camera', {'position': initial['position'], 'yaw': initial['yaw'], 'pitch': initial['pitch']})
        call('tick', {'frozen': initial['server']['frozen']})
        save()
        print(json.dumps({'passed': report['passed'], 'result': str(work / 'result.json')}), flush=True)


def startup_matrix():
    """Observe source event timing and the actual selected vanilla ticker lists.

    A motor's setValue packet is an event; /data reading the same field is not.
    This matrix never rewrites tick lists or aligns machine samples afterward.
    """
    base = java.BASE.resolve()
    work = Path(tempfile.mkdtemp(prefix='press-startup-java-', dir=ROOT / '.local'))
    basin, press, motor, shaft, lever = [620, 64, 30], [620, 66, 30], [618, 66, 30], [619, 66, 30], [619, 67, 30]
    positions = [basin, press, motor, shaft, lever]
    report = dict(passed=False, create=PINS['create_revision'], scope=startup_matrix.__doc__, cases=[],
                  fixture_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  bridge_jar_sha256=java.digest(base / 'game/mods/create-reference-bridge.jar'))
    transcript = []

    def save():
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        (work / 'transcript.json').write_text(json.dumps(transcript, indent=2) + '\n')

    def call(method, body):
        result = java.call(base, method, body)
        transcript.append(dict(method=method, body=body, reply=result))
        save()
        return result

    def command(value):
        return call('command', dict(command=value))

    def observe(ticks):
        before = call('state', {})['server']['game_time']
        samples = call('observe_ticks', dict(ticks=ticks, positions=positions, ticker_order=True))['samples']
        assert [s['game_time'] for s in samples] == list(range(before + 1, before + ticks + 1))
        return samples

    def before():
        return dict(blocks=[call('block', dict(pos=p)) for p in positions],
                    ticker_order=call('ticker_order', dict(positions=positions)))

    def seed():
        command('data merge block 620 64 30 {InputItems:{Size:9,Items:[{Slot:0,id:"minecraft:snowball",count:8}]},OutputItems:{Size:9,Items:[]}}')

    def setup(order, clutch=False, settled=False):
        command('fill 617 64 28 622 69 32 minecraft:air')
        blocks = dict(B='620 64 30 create:basin[facing=down]',
                      P='620 66 30 create:mechanical_press[facing=east]',
                      M='618 66 30 create:creative_motor[facing=east]',
                      S='619 66 30 create:' + ('clutch[axis=x,powered=true]' if clutch else 'shaft[axis=x]'))
        for role in order:
            command('setblock ' + blocks[role])
        command('data merge block 618 66 30 {ScrollValue:' + ('32' if clutch or not settled else '0') + '}')
        if clutch:
            command('setblock 619 67 30 minecraft:lever[face=floor,facing=north,powered=true]')

    def finish(row):
        previous = 0
        row['impacts'] = []
        for sample in row['samples']:
            count = items(sample['blocks'][0]['nbt'], 'OutputItems').get('minecraft:snow_block', 0)
            if count != previous:
                row['impacts'].append(sample['tick'])
            previous = count
        report['cases'].append(row)
        save()
        print(json.dumps(dict(case=row['name'], impacts=row['impacts'], result=str(work / 'result.json'))), flush=True)

    print(json.dumps(dict(work=str(work))), flush=True)
    initial = call('state', {})
    if initial.get('screen') == 'PauseScreen':
        call('input', dict(kind='escape'))
        initial = call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955
    try:
        call('tick', dict(frozen=True))
        command('gamemode creative')
        command('forceload add 608 16 639 47')
        command('fill 617 63 28 622 63 32 minecraft:smooth_stone')
        cases = [
            ('fresh_motor_first', 'MSBP', False, False, False, [31, 93]),
            ('fresh_motor_last', 'BPSM', False, False, False, [32, 94]),
            ('isolated_speed_field_without_network', 'BPSM', True, False, False, [32, 94]),
            ('replaced_motor_last', 'MSBP', False, True, False, [32, 94]),
            ('data_read_existing_zero', 'MSBP', False, True, False, []),
            ('clutch_open_before_consumer', 'MSBP', False, True, True, [31, 93]),
            ('clutch_open_after_consumer', 'BPMS', False, True, True, [31, 93]),
        ]
        for name, order, loaded, settled, clutch, expected in cases:
            setup(order, clutch, settled)
            row = dict(name=name, creation_order=list(order), expected_impacts=expected)
            if loaded:
                command('data merge block 618 66 30 {Speed:32.0f}')
            if settled:
                row['settled'] = observe(30)[-1]
            seed()
            if name == 'replaced_motor_last':
                command('setblock 618 66 30 minecraft:air')
                command('setblock 618 66 30 create:creative_motor[facing=east]')
                command('data merge block 618 66 30 {ScrollValue:32}')
            elif name == 'data_read_existing_zero':
                command('data merge block 618 66 30 {ScrollValue:32}')
            elif clutch:
                command('setblock 619 67 30 minecraft:lever[face=floor,facing=north,powered=false]')
            row['before'] = before()
            row['samples'] = observe(128)
            finish(row)
            assert row['impacts'] == expected, row
            # Actual lists, separately from command creation order.
            active = [r['pos'] for r in row['samples'][0]['ticker_order']['blockEntityTickers'] if not r['removed']]
            row['motor_ticks_before_press'] = active.index(motor) < active.index(press)
            if name.startswith('fresh_motor_'):
                assert row['motor_ticks_before_press'] == (name == 'fresh_motor_first')
            if name == 'isolated_speed_field_without_network':
                # A lone /data Speed field was not retained by the original.
                # This is not evidence of an authentically loaded network.
                assert number(row['before']['blocks'][2], 'Speed') == 0
                assert number(row['before']['blocks'][3], 'Speed') == 0
        # Ordinary source UI sends ValueSettingsPacket/setValue while the
        # server remains frozen. No direct Java machine call is used here.
        setup('MSBP', settled=True)
        observe(30)
        seed()
        command('clear @s')
        call('camera', dict(position=[618.4375, 65.5, 33], target=[618.4375, 66.5, 31]))
        call('input', dict(kind='key', key='use', down=False))
        time.sleep(.3)
        row = dict(name='ordinary_gui_zero_to_32', before=before(), expected_impacts=[31, 93])
        call('input', dict(kind='key', key='use', down=True))
        for _ in range(50):
            time.sleep(.1)
            ui = call('ui', {})
            if 'value_settings' in ui:
                break
        else:
            raise AssertionError('The source motor value board did not open')
        row['board'] = ui
        point = next(p['gui_coordinate'] for p in ui['value_settings']['sample_coordinates']
                     if p['row'] == 1 and p['value'] == 32)
        call('input', dict(kind='mouse', button=1, down=False, x=point[0], y=point[1]))
        call('input', dict(kind='key', key='use', down=False))
        for _ in range(50):
            row['after_callback'] = before()
            if number(row['after_callback']['blocks'][1], 'Speed') == 32:
                break
            time.sleep(.1)
        assert call('state', {})['server']['frozen']
        assert number(row['after_callback']['blocks'][1], 'Speed') == 32
        assert number(row['after_callback']['blocks'][1], 'NeedsUpdate') == 1
        assert number(row['after_callback']['blocks'][1], 'Running') == 0
        row['samples'] = observe(128)
        finish(row)
        assert row['impacts'] == row['expected_impacts']
        report['passed'] = True
        return report
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        call('tick', dict(frozen=True))
        call('camera', dict(position=initial['position'], yaw=initial['yaw'], pitch=initial['pitch']))
        save()
        print(json.dumps(dict(passed=report['passed'], result=str(work / 'result.json'))), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--startup-matrix', action='store_true')
    args = parser.parse_args()
    startup_matrix() if args.startup_matrix else run()
