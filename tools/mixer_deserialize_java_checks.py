#!/usr/bin/env python3
"""Observe real Create Basin inventory deserialization through /data.

Requires exclusive ownership of the EXISTING disposable Java reference. The
fixture never edits Mixer NBT: a placed kinetic BE's movement guard confounds
such a control by clearing its power. Each row instead proves idle RPM 32 before
and after the real Basin read, observes six normal server ticks, then replaces
only the source motor to cause a real RPM 64 network change and admits the SAME
seeded recipe. No external implementation read or direct machine-method call.
"""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from common import ROOT, PINS
from burner_heat_java_checks import items, number
import reference_java as java

BASIN = [550, 64, 30]
MIXER = [550, 66, 30]


def run(base=java.BASE, *, noncanonical=False):
    base = Path(base).resolve()
    assert base == java.BASE.resolve()
    manifest = json.loads((base / 'manifest.json').read_text())
    assert manifest['data_version'] == 3955 and manifest['create_sha256'] == java.CREATE_SHA256
    work = Path(tempfile.mkdtemp(prefix='mixer-deserialize-java-', dir=ROOT / '.local'))
    report = {'passed': False, 'source': PINS['create_revision'], 'cases': [], 'scope': __doc__,
              'operator_flag_deserialization_isolation': 'not claimed; separate failed controls reset power',
              'fixture_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'noncanonical': noncanonical}
    trace = []
    def save():
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        (work / 'transcript.json').write_text(json.dumps(trace, indent=2) + '\n')
    def call(method, body):
        reply = java.call(base, method, body)
        trace.append({'method': method, 'body': body, 'reply': reply})
        save()
        return reply
    def command(value): return call('command', {'command': value})
    def block(pos): return call('block', {'pos': pos})
    def snapshot(): return {'basin': block(BASIN), 'mixer': block(MIXER)}
    def observe(ticks):
        before = call('state', {})['server']['game_time']
        reply = call('observe_ticks', {'ticks': ticks, 'positions': [BASIN, MIXER]})
        assert [r['game_time'] for r in reply['samples']] == list(range(before + 1, before + ticks + 1))
        state = call('state', {})
        assert state['server']['frozen'] and state['server']['game_time'] == before + ticks
        return reply
    initial = call('state', {})
    if initial.get('screen') == 'PauseScreen':
        call('input', {'kind': 'escape'})
        initial = call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955
    try:
        call('tick', {'frozen': True})
        command('gamemode creative')
        command('forceload add 544 16 559 47')
        command('fill 548 63 28 552 63 32 minecraft:smooth_stone')
        normal = '{InputItems:{Size:9,Items:[{Slot:0,id:"minecraft:andesite",count:1},{Slot:1,id:"minecraft:iron_nugget",count:1}]},OutputItems:{Size:9,Items:[]}}'
        cases = [('basin-created-first', True, normal), ('mixer-created-first', False, normal)]
        if noncanonical:
            cases = [
                ('descending-slots', True, '{InputItems:{Size:9,Items:[{Slot:1,id:"minecraft:iron_nugget",count:1},{Slot:0,id:"minecraft:andesite",count:1}]},OutputItems:{Size:9,Items:[]}}'),
                ('byte-slots', True, '{InputItems:{Size:9,Items:[{Slot:0b,id:"minecraft:andesite",count:1},{Slot:1b,id:"minecraft:iron_nugget",count:1}]},OutputItems:{Size:9,Items:[]}}'),
                ('short-size-byte-count', True, '{InputItems:{Size:9s,Items:[{Slot:0,id:"minecraft:andesite",count:1b},{Slot:1,id:"minecraft:iron_nugget",count:1b}]},OutputItems:{Size:9,Items:[]}}'),
            ]
        for name, basin_first, inventory in cases:
            row = {'name': name,
                   'creation_order_is_not_claimed_as_internal_BE_tick_order': True}
            report['active_case'] = row
            command('fill 548 64 28 552 69 32 minecraft:air')
            command('setblock 549 65 30 create:creative_motor[facing=up]')
            command('setblock 549 66 30 create:cogwheel[axis=y]')
            actors = [('550 64 30', 'create:basin'), ('550 66 30', 'create:mechanical_mixer')]
            if not basin_first: actors.reverse()
            for pos, state in actors: command('setblock ' + pos + ' ' + state)
            command('data merge block 549 65 30 {ScrollValue:32}')
            row['prime'] = observe(30)
            row['before'] = snapshot()
            assert abs(number(row['before']['mixer'], 'Speed')) == 32
            assert number(row['before']['mixer'], 'Running') == 0 and number(row['before']['mixer'], 'NeedsUpdate') == 0
            assert items(row['before']['basin']['nbt'], 'InputItems') == {}
            command('data merge block 550 64 30 ' + inventory)
            row['immediate'] = snapshot()
            inputs = {'minecraft:andesite': 1, 'minecraft:iron_nugget': 1}
            assert items(row['immediate']['basin']['nbt'], 'InputItems') == inputs
            assert abs(number(row['immediate']['mixer'], 'Speed')) == 32
            row['normal_after_read'] = observe(6)
            for sample in row['normal_after_read']['samples']:
                mixer = sample['blocks'][1]
                assert abs(number(mixer, 'Speed')) == 32
                assert number(mixer, 'Running') == 0 and number(mixer, 'NeedsUpdate') == 0
                assert items(sample['blocks'][0]['nbt'], 'InputItems') == inputs
            # Actual source replacement/reattachment supplies RPM64. This
            # changes no Mixer/Basin field or input, and invokes no machine
            # implementation directly; it is an eligibility control, not a
            # claimed player UI interaction or exact scheduling tick oracle.
            command('setblock 549 65 30 minecraft:air')
            command('setblock 549 65 30 create:creative_motor[facing=up]')
            command('data merge block 549 65 30 {ScrollValue:64}')
            row['positive_network_change'] = observe(12)
            samples = row['positive_network_change']['samples']
            first = next((sample['tick'] for sample in samples if number(sample['blocks'][1], 'Running') != 0), None)
            assert first is not None, row['name']
            assert abs(number(samples[-1]['blocks'][1], 'Speed')) == 64
            assert items(samples[-1]['blocks'][0]['nbt'], 'InputItems') == inputs
            row['positive_start_tick'] = first
            row['outcome'] = 'Basin InputItems read did not wake idle powered Mixer within 6 ticks; same inputs admitted after a real network-speed change'
            report['cases'].append(row)
            report.pop('active_case', None)
            save()
        report['passed'] = True
        save()
        print(json.dumps({'passed': True, 'cases': len(report['cases']), 'result': str(work / 'result.json')}), flush=True)
        return report
    except Exception as error:
        report['error'] = repr(error)
        save()
        raise
    finally:
        command('gamemode creative')
        call('camera', {'position': initial['position'], 'yaw': initial['yaw'], 'pitch': initial['pitch']})
        call('tick', {'frozen': initial['server']['frozen']})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--noncanonical', action='store_true', help='Observe descending Slot order and accepted numeric tag forms.')
    args = parser.parse_args()
    run(noncanonical=args.noncanonical)
