#!/usr/bin/env python3
"""Actual original burner/Basin heat decisions on normal observed server ticks.

Only the prepared private reference is used. Inventories and the two fuel-expiry
boundaries are canonical fixture seeds; fuel admission itself uses real keyUse.
No falling-intake, schematic-import or Java/Horizon pixel-parity claim is made.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

from common import ROOT, PINS
import reference_java as java

BASIN = [454, 64, 18]
MIXER = [454, 66, 18]
BURNER = [454, 63, 18]
MOTOR = [453, 65, 18]


def field(nbt, name):
    """Extract a balanced compound field without relying on SNBT key order."""
    match = re.search(r'\b' + re.escape(name) + r'\s*:\s*([\[{])', nbt)
    assert match, (name, nbt)
    start = match.end() - 1
    depth = 0
    quoted = escaped = False
    for i in range(start, len(nbt)):
        c = nbt[i]
        if quoted:
            if escaped: escaped = False
            elif c == '\\': escaped = True
            elif c == '"': quoted = False
        elif c == '"': quoted = True
        elif c in '[{': depth += 1
        elif c in ']}':
            depth -= 1
            if depth == 0: return nbt[start:i + 1]
    raise AssertionError(('Unterminated fixture field', name, nbt))


def items(nbt, name):
    raw = field(nbt, name)
    ids = re.findall(r'\bid\s*:\s*"([^"]+)"', raw)
    counts = list(map(int, re.findall(r'\bcount\s*:\s*(\d+)', raw)))
    assert len(ids) == len(counts), raw
    result = {}
    for item, count in zip(ids, counts): result[item] = result.get(item, 0) + count
    return result


def number(block, key, default=None):
    match = re.search(r'\b' + key + r'\s*:\s*(-?[\d.]+(?:[eE][+-]?\d+)?)', block.get('nbt', ''))
    if default is not None and not match: return default
    assert match, (key, block)
    return float(match[1])


def run(base=java.BASE):
    base = Path(base).resolve()
    assert base == java.BASE.resolve(), 'Only the owned disposable reference is authorized'
    manifest = json.loads((base / 'manifest.json').read_text())
    assert manifest['data_version'] == 3955 and manifest['create_sha256'] == java.CREATE_SHA256
    work = Path(tempfile.mkdtemp(prefix='burner-heat-java-', dir=ROOT / '.local'))
    report = {'passed': False, 'reference': PINS['create_revision'], 'cases': [], 'scope': __doc__}
    trace = []
    def save():
        (work / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        (work / 'transcript.json').write_text(json.dumps(trace, ensure_ascii=False, indent=2) + '\n')
    def call(method, body):
        reply = java.call(base, method, body)
        trace.append({'method': method, 'body': body, 'reply': reply}); save(); return reply
    def cmd(command): return call('command', {'command': command})
    def block(pos): return call('block', {'pos': pos})
    def observe(n):
        before = call('state', {})['server']['game_time']
        reply = call('observe_ticks', {'ticks': n, 'positions': [BASIN, MIXER, BURNER]})
        times = [s['game_time'] for s in reply['samples']]
        assert times == list(range(before + 1, before + n + 1)), (before, reply)
        state = call('state', {})
        assert state['server']['frozen'] and state['server']['game_time'] == before + n, state
        return reply['samples']
    def inventories(n):
        cmd('data merge block 454 64 18 {InputItems:{Size:9,Items:['
            '{Slot:0,id:"minecraft:copper_ingot",count:' + str(n) + ',components:{"minecraft:custom_data":{heat_marker:71}}},'
            '{Slot:1,id:"create:zinc_ingot",count:' + str(n) + ',components:{"minecraft:custom_data":{heat_marker:72}}}]},'
            'OutputItems:{Size:9,Items:[]}}')
    def click_fuel():
        cmd('gamemode survival'); cmd('clear @s')
        cmd('item replace entity @s weapon.mainhand with minecraft:coal 3')
        call('camera', {'position': [456.5, 63, 20.5], 'target': [454.5, 63.5, 18.5], 'hide_gui': False})
        call('capture', {'name': 'burner-heat-before.png', 'frames': 12})
        state = call('state', {})
        assert state['hit']['block'] == 'create:blaze_burner', state
        call('input', {'key': 'use'})
        call('capture', {'name': 'burner-heat-after.png', 'frames': 8})
        call('input', {'key': 'use', 'down': False})
        call('capture', {'name': 'burner-heat-after.png', 'frames': 4})
        b = block(BURNER)
        assert number(b, 'fuelLevel') == 1 and number(b, 'burnTimeRemaining') == 1600, b
        assert b['properties']['blaze'].lower() == 'kindled', b
        selected = cmd('data get entity @s SelectedItem')['messages']
        assert any(re.search(r'\bcount\s*:\s*2\b', line) and 'minecraft:coal' in line for line in selected), selected
        cmd('gamemode creative')
    def prepare(n, fuel=True):
        call('tick', {'frozen': True}); cmd('gamemode creative')
        cmd('fill 450 63 14 460 70 24 minecraft:air')
        # Floor y62, feet y63: the actual burner side at y63 stays exposed.
        # A y63 floor occludes diagonal rays before they reach this lower block.
        cmd('fill 450 62 14 460 62 24 minecraft:smooth_stone')
        for pos, state in [(BURNER, 'create:blaze_burner[blaze=smouldering,facing=north]'),
            (BASIN, 'create:basin'), (MOTOR, 'create:creative_motor[facing=up]'),
            ([453, 66, 18], 'create:cogwheel[axis=y]'), (MIXER, 'create:mechanical_mixer')]:
            cmd('setblock ' + ' '.join(map(str, pos)) + ' ' + state)
        cmd('data merge block 453 65 18 {ScrollValue:32}')
        cmd('execute positioned 454 64 18 run kill @e[type=minecraft:item,distance=..10]')
        observe(20)
        assert abs(number(block(MIXER), 'Speed')) == 32
        inventories(n)
        if fuel: click_fuel()
    def start():
        rows = []
        for _ in range(300):
            row = observe(1)[0]; rows.append(row)
            if number(row['blocks'][1], 'Running'):
                assert number(row['blocks'][1], 'Ticks') == 1, row
                return rows
        raise AssertionError(('No heated recipe started', block(BASIN), block(MIXER), block(BURNER)))
    def mark(name, **data): report['cases'].append(dict(name=name, **data)); save()
    initial = call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955
    try:
        call('tick', {'frozen': True}); cmd('forceload add 448 16 464 32')
        prepare(2)
        begun = start(); rows = [begun[-1], *observe(144)]
        counts = [items(r['blocks'][0]['nbt'], 'OutputItems').get('create:brass_ingot', 0) for r in rows]
        assert counts == [0] * 82 + [2] * 62 + [4], counts
        assert not items(rows[-1]['blocks'][0]['nbt'], 'InputItems')
        assert 'heat_marker' not in field(rows[-1]['blocks'][0]['nbt'], 'OutputItems')
        mark('heated-brass-83-62', first_inclusive_ticks=83, repeat_ticks=62, startup=begun, samples=rows)

        prepare(1); begun = start()
        cmd('data merge block 454 63 18 {burnTimeRemaining:1}')
        loss = observe(1)[0]
        assert loss['blocks'][2]['properties']['blaze'].lower() == 'smouldering', loss
        assert number(loss['blocks'][1], 'Running') == 1 and number(loss['blocks'][1], 'Ticks') == 2, loss
        rows = observe(120); last = rows[-1]
        assert not items(last['blocks'][0]['nbt'], 'OutputItems')
        assert items(last['blocks'][0]['nbt'], 'InputItems') == {'minecraft:copper_ingot': 1, 'create:zinc_ingot': 1}
        assert 'heat_marker:71' in last['blocks'][0]['nbt'] and 'heat_marker:72' in last['blocks'][0]['nbt']
        assert any(number(r['blocks'][1], 'Ticks') == 20 for r in rows)
        mark('heat-loss-during-first-cycle', start=begun[-1], loss=loss, samples=rows)

        prepare(2); begun = start(); first = observe(82)[-1]
        assert items(first['blocks'][0]['nbt'], 'OutputItems') == {'create:brass_ingot': 2}
        cmd('data merge block 454 63 18 {burnTimeRemaining:1}')
        before = observe(61)[-1]
        assert number(before['blocks'][1], 'Ticks') == 20, before
        failed = observe(1)[0]
        assert number(failed['blocks'][1], 'Ticks') == 22, failed
        assert items(failed['blocks'][0]['nbt'], 'OutputItems') == {'create:brass_ingot': 2}
        assert items(failed['blocks'][0]['nbt'], 'InputItems') == {'minecraft:copper_ingot': 1, 'create:zinc_ingot': 1}
        mark('heat-loss-between-repeat-batches', start=begun[-1], first=first, before=before, rejected_completion=failed)

        prepare(1); begun = start(); cmd('setblock 453 66 18 minecraft:air')
        stopped = observe(20)[-1]
        assert number(stopped['blocks'][1], 'Speed') == 0
        assert not items(stopped['blocks'][0]['nbt'], 'OutputItems')
        assert items(stopped['blocks'][0]['nbt'], 'InputItems') == {'minecraft:copper_ingot': 1, 'create:zinc_ingot': 1}
        cmd('setblock 453 66 18 create:cogwheel[axis=y]')
        resumed = observe(300)[-1]
        assert items(resumed['blocks'][0]['nbt'], 'OutputItems') == {'create:brass_ingot': 2}
        mark('power-loss-and-resume', start=begun[-1], stopped=stopped, resumed=resumed)

        cmd('item replace entity @s armor.head with create:goggles')
        call('camera', {'position': [456.5, 63, 20.5], 'target': [454.5, 63.5, 18.5], 'hide_gui': False})
        capture = call('capture', {'name': 'burner-no-goggles-hud-java.png', 'frames': 40})
        retained = work / 'burner-no-goggles-hud-java.png'
        shutil.copy2(capture['path'], retained)
        capture['retained_path'] = str(retained)
        capture['sha256'] = hashlib.sha256(retained.read_bytes()).hexdigest()
        ui = call('ui', {})
        assert ui['hit']['block'] == 'create:blaze_burner' and ui['goggles']['wearing']
        assert ui['goggles']['lines'] == [], ui
        mark('burner-has-no-goggles-tooltip', ui=ui, capture=capture)
        report['passed'] = True; save(); return report
    except BaseException as error:
        report['error'] = repr(error); save(); raise
    finally:
        call('input', {'key': 'use', 'down': False}); call('tick', {'frozen': True})
        print(json.dumps({'passed': report['passed'], 'result': str(work / 'result.json')}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, default=java.BASE)
    run(parser.parse_args().base)
