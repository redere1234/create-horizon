#!/usr/bin/env python3
"""Observe original Create intake through normal ItemEntity landing ticks.

Requires exclusive ownership of the existing disposable reference bridge. No
launch, account access, external implementation inspection or callback substitute.
Canonical inventory fixtures use the public /data command; intake is ordinary
movement. Native active-owner and two-process tests are separate evidence.
"""
import json
from pathlib import Path
import re
import tempfile
from common import ROOT, PINS
import reference_java as java
from burner_heat_java_checks import field, items

POS = [526, 64, 30]
MARKER = 'components:{"minecraft:custom_data":{retained:907}}'


def run(base=java.BASE):
    base = Path(base).resolve()
    assert base == java.BASE.resolve()
    manifest = json.loads((base / 'manifest.json').read_text())
    assert manifest['data_version'] == 3955 and manifest['create_sha256'] == java.CREATE_SHA256
    work = Path(tempfile.mkdtemp(prefix='item-contact-java-', dir=ROOT / '.local'))
    report = dict(passed=False, source=PINS['create_revision'], cases=[],
                  scope='Original Create normal observed server ticks and canonical public NBT fixtures; no client-prediction, pixel, unknown-size or process-restart parity claim')
    trace = []
    def save():
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        (work / 'transcript.json').write_text(json.dumps(trace, indent=2) + '\n')
    def call(method, body):
        reply = java.call(base, method, body)
        trace.append(dict(method=method, body=body, reply=reply)); save(); return reply
    def command(value): return call('command', {'command': value})
    def clear_items(): command('kill @e[type=minecraft:item,x=523,y=62,z=27,dx=8,dy=10,dz=8]')
    def setup(machine):
        command('fill 524 64 28 530 69 34 minecraft:air')
        command('setblock 526 64 30 create:' + machine)
        clear_items()
    def inventory(machine, slot, count, marker=True):
        ik, size = ('InputItems', 9) if machine == 'basin' else ('InputInventory', 1)
        ok = 'OutputItems' if machine == 'basin' else 'OutputInventory'
        stack = ('{Slot:' + str(slot) + ',id:"minecraft:wheat",count:' + str(count)
                 + (',' + MARKER if marker else '') + '}') if count else ''
        command('data merge block 526 64 30 {' + ik + ':{Size:' + str(size)
                + ',Items:[' + stack + ']},' + ok + ':{Size:9,Items:[]}}')
    def snapshot(machine):
        block = call('block', {'pos': POS})
        rows = call('entities', {'center': [526.5, 65, 30.5], 'radius': 4})
        rows = [row for row in rows['entities'] if row['type'] == 'minecraft:item' and 'contact_ref' in row['nbt']]
        return dict(block=block, entities=rows,
                    input=items(block['nbt'], 'InputItems' if machine == 'basin' else 'InputInventory'))
    def land(name, machine, at, expected_input, remainder, *, item='minecraft:wheat', count=13, marker=True):
        component = ',' + MARKER if marker else ''
        command('summon minecraft:item ' + ' '.join(map(str, at))
                + ' {Tags:["contact_ref"],PickupDelay:32767,Motion:[0d,-0.3d,0d],Item:{id:"'
                + item + '",count:' + str(count) + component + '}}')
        before = snapshot(machine)
        tick_before = call('state', {})['server']['game_time']
        observation = call('observe_ticks', {'ticks': 8, 'positions': [POS, [526,65,30]]})
        assert [row['game_time'] for row in observation['samples']] == list(range(tick_before + 1, tick_before + 9))
        after = snapshot(machine)
        report['cases'].append(dict(name=name, before=before, observation=observation, after=after)); save()
        assert after['input'] == expected_input, (name, after['input'], expected_input)
        assert len(after['entities']) == int(remainder > 0), (name, after['entities'])
        if remainder:
            stack_nbt = field(after['entities'][0]['nbt'], 'Item')
            assert re.search(r'\bcount:\s*' + str(remainder) + r'\b', stack_nbt), (name, stack_nbt)
            if marker: assert re.search(r'\bretained:\s*907\b', stack_nbt), stack_nbt
        if count > remainder and marker: assert 'retained:907' in after['block']['nbt'].replace(' ', '')
        if name == 'basin-distinct-components':
            raw = field(after['block']['nbt'], 'InputItems')
            assert re.findall(r'\bSlot:\s*(\d+)', raw) == ['0', '1'], raw
            assert re.findall(r'\bcount:\s*(\d+)', raw) == ['1', '13'], raw
    initial = call('state', {})
    if initial.get('screen') == 'PauseScreen': call('input', {'kind': 'escape'}); initial = call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    try:
        call('tick', {'frozen': True}); command('gamemode creative')
        command('forceload add 512 16 543 47')
        command('fill 524 63 28 530 63 34 minecraft:smooth_stone')
        for machine, at in [('basin', [526.5,64.5,30.5]), ('millstone', [526.5,65.1,30.5])]:
            setup(machine); land(machine+'-fresh', machine, at, {'minecraft:wheat':13}, 0)
            setup(machine); inventory(machine, 0, 63)
            land(machine+'-partial', machine, at, {'minecraft:wheat':64}, 12)
            setup(machine); inventory(machine, 0, 64)
            land(machine+'-full', machine, at, {'minecraft:wheat':64}, 13)
            setup(machine); inventory(machine, 0, 1, False)
            expected = {'minecraft:wheat':14 if machine == 'basin' else 1}
            land(machine+'-distinct-components', machine, at, expected, 0 if machine == 'basin' else 13)
            setup(machine); command('setblock 526 65 30 minecraft:stone_slab[type=bottom]')
            land(machine+'-separate-support', machine, [526.5,65.7,30.5], {}, 13)
        setup('basin'); inventory('basin',5,63)
        land('basin-existing-after-hole','basin',[526.5,64.5,30.5],{'minecraft:wheat':64},12)
        assert re.search(r'\bSlot:\s*5\b', field(snapshot('basin')['block']['nbt'],'InputItems'))
        setup('basin'); land('basin-inside-rim','basin',[526.05,64.95,30.5],{'minecraft:wheat':13},0)
        setup('basin'); land('basin-outside-center-rim','basin',[527.05,64.95,30.5],{},13)
        setup('millstone'); land('millstone-base-here','millstone',[526.0,64.5,30.5],{'minecraft:wheat':13},0)
        setup('millstone'); command('setblock 526 65 30 create:millstone')
        command('data merge block 526 65 30 {InputInventory:{Size:1,Items:[{Slot:0,id:"minecraft:wheat",count:64,'+MARKER+'}]},OutputInventory:{Size:9,Items:[]}}')
        land('millstone-first-here-full-no-below-fallback','millstone',[526.0,65.5,30.5],{},13)
        setup('millstone'); land('millstone-forbidden','millstone',[526.5,65.1,30.5],{},1,item='minecraft:diamond_sword',count=1,marker=False)
        report['passed'] = True; save(); print(json.dumps({'passed':True,'cases':len(report['cases']),'result':str(work/'result.json')})); return report
    except Exception as error:
        report['error'] = repr(error); save(); raise
    finally:
        clear_items(); call('tick', {'frozen': initial['server']['frozen']})


if __name__ == '__main__':
    run()
