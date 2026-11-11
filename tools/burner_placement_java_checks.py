#!/usr/bin/env python3
"""Normal original-client placement of both burner item aliases, four yaws.

Uses only the owned disposable reference instance. No direct block write creates
the tested burner: the real survival player's ordinary keyUse places each one.
"""
import argparse
import json
from pathlib import Path
import re
import tempfile

from common import ROOT, PINS
import reference_java as java


def run(base=java.BASE):
    base = Path(base).resolve()
    assert base == java.BASE.resolve(), 'Only the owned disposable reference is authorized'
    manifest = json.loads((base / 'manifest.json').read_text())
    assert manifest['data_version'] == 3955 and manifest['create_sha256'] == java.CREATE_SHA256
    work = Path(tempfile.mkdtemp(prefix='burner-placement-java-', dir=ROOT / '.local'))
    report = {'passed': False, 'reference': PINS['create_revision'], 'cases': [], 'scope': __doc__}
    trace = []
    def save():
        (work / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        (work / 'transcript.json').write_text(json.dumps(trace, ensure_ascii=False, indent=2) + '\n')
    def call(method, body):
        reply = java.call(base, method, body)
        trace.append({'method': method, 'body': body, 'reply': reply}); save(); return reply
    def cmd(text): return call('command', {'command': text})
    pos = [468, 63, 18]
    initial = call('state', {})
    try:
        assert initial['ready']
        call('tick', {'frozen': True})
        cmd('gamemode creative'); cmd('forceload add 464 16 480 32')
        cmd('fill 464 63 14 472 70 22 minecraft:air')
        cmd('fill 464 62 14 472 62 22 minecraft:smooth_stone')
        for alias, heat in [('create:blaze_burner', 'smouldering'), ('create:empty_blaze_burner', 'none')]:
            for yaw, facing, player in [(0, 'north', [468.5,63,15.5]), (90, 'east', [471.5,63,18.5]),
                                        (180, 'south', [468.5,63,21.5]), (270, 'west', [465.5,63,18.5])]:
                # Original right-click delay advances on client ticks while
                # frozen; the capture below also lets setup packets arrive.
                call('input', {'key': 'use', 'down': False})
                cmd('setblock 468 63 18 minecraft:air'); cmd('gamemode survival'); cmd('clear @s')
                cmd('item replace entity @s weapon.mainhand with ' + alias + ' 2')
                call('camera', {'position': player, 'target': [468.5,63,18.5], 'hide_gui': False})
                call('capture', {'name': 'burner-placement-before.png', 'frames': 16})
                before = call('state', {})
                assert before['hit']['pos'] == [468,62,18] and before['hit']['face'] == 'up', before
                call('input', {'key': 'use'})
                call('capture', {'name': 'burner-placement-after.png', 'frames': 10})
                call('input', {'key': 'use', 'down': False})
                placed = call('block', {'pos': pos})
                assert placed['id'] == 'create:blaze_burner', placed
                assert placed['properties']['blaze'].lower() == heat and placed['properties']['facing'].lower() == facing, placed
                held = cmd('data get entity @s SelectedItem')['messages']
                assert any(alias in line and re.search(r'\bcount\s*:\s*1\b', line) for line in held), held
                raw = placed.get('nbt', '')
                if heat == 'none': assert not raw, placed
                else:
                    assert 'create:blaze_heater' in raw and re.search(r'\bfuelLevel\s*:\s*0\b', raw), placed
                    assert re.search(r'\bburnTimeRemaining\s*:\s*0\b', raw), placed
                report['cases'].append({'alias': alias, 'approach_yaw': yaw, 'expected_facing': facing,
                    'before': before, 'placed': placed, 'held': held}); save()
        report['passed'] = True; save(); return report
    except BaseException as error:
        report['error'] = repr(error); save(); raise
    finally:
        call('input', {'key': 'use', 'down': False}); call('tick', {'frozen': True}); cmd('gamemode creative')
        cmd('item replace entity @s armor.head with ' + initial['head'])
        print(json.dumps({'passed': report['passed'], 'cases': len(report['cases']), 'result': str(work / 'result.json')}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, default=java.BASE)
    run(parser.parse_args().base)
