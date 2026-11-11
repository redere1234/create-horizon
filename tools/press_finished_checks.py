"""Check retained Finished across two real depot pressing cycles.

Java uses normal Post-tick observations; native uses the existing ordinary
server command harness. No pressing method or replacement clock is called.
This checks canonical lifecycle fields and two consumed inputs, not render or
cross-runtime frame timing.
"""
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import tempfile

from common import ROOT, PINS
from native_check_session import NativeCheckSession
import reference_java

PRESS = [488, 66, 24]
DEPOT = [488, 64, 24]
MOTOR = [487, 66, 24]
INPUT = ('{HeldItem:{Item:{id:"minecraft:copper_ingot",count:2},'
         'Pos:0.0f,PrevPos:0.0f,Offset:0.0f,PrevOffset:0.0f,Angle:180,InDirection:3}}')
OUTPUT_CHECKS = [
    'execute if data block 488 64 24 HeldItem.Item{id:"create:copper_sheet",count:1} run say held_sheet_ok',
    'execute if data block 488 64 24 OutputBuffer.Items[{Slot:0,id:"create:copper_sheet",count:1}] run say buffered_sheet_ok',
    'execute unless data block 488 64 24 OutputBuffer.Items[1] run say no_extra_output_ok',
]
OUTPUT_MARKERS = ['held_sheet_ok', 'buffered_sheet_ok', 'no_extra_output_ok']


def lifecycle(records):
    fields = []
    for record in records:
        values = {}
        for key in ('Running', 'Ticks', 'Mode', 'Finished'):
            match = re.search(r'\b' + key + r':\s*(-?[\d.]+)', record)
            assert match, (key, record)
            values[key] = int(float(match[1]))
        fields.append(values)
    starts = [i for i in range(1, len(fields))
              if fields[i]['Running'] and not fields[i-1]['Running']]
    assert len(starts) == 2, (starts, fields)
    first, second = starts
    assert fields[first]['Finished'] == 0, fields[first]
    assert fields[second]['Finished'] == 1, fields[second]
    assert all(row['Finished'] == 1 for row in fields[second:]), fields[second:]
    assert fields[-1]['Running'] == 0 and fields[-1]['Finished'] == 1, fields[-1]
    assert all(fields[i]['Mode'] == 1 for i in starts)
    return {'starts': starts, 'observations': fields}


def slide_trace(records):
    trace = []
    for record in records[:10]:
        row = {}
        for key in ('Pos', 'PrevPos', 'Angle'):
            match = re.search(r'\b' + key + r':\s*(-?[\d.]+)', record)
            assert match, (key, record)
            row[key] = float(match[1])
        trace.append(row)
    return trace


def setup():
    return ['gamemode creative', 'forceload add 480 16 496 32',
            'fill 484 63 20 492 70 28 minecraft:air',
            'fill 484 63 20 492 63 28 minecraft:smooth_stone',
            'setblock 488 64 24 create:depot',
            'setblock 487 66 24 create:creative_motor[facing=east]',
            'setblock 488 66 24 create:mechanical_press[facing=east]',
            'data merge block 487 66 24 {ScrollValue:128}']


def run_java():
    work = Path(tempfile.mkdtemp(prefix='press-finished-java-', dir=ROOT / '.local'))
    report = {'passed': False, 'reference': PINS['create_revision'], 'scope': __doc__}
    trace = []

    def save():
        (work/'result.json').write_text(json.dumps(report, indent=2)+'\n')
        (work/'transcript.json').write_text(json.dumps(trace, indent=2)+'\n')

    def call(method, body):
        value = reference_java.call(reference_java.BASE, method, body)
        trace.append({'method': method, 'body': body, 'reply': value}); save()
        return value

    try:
        state = call('state', {})
        if state['screen'] == 'PauseScreen':
            call('input', {'kind': 'escape'})
            state = call('state', {})
        assert state['ready'], state
        call('tick', {'frozen': True})
        for command in setup():
            call('command', {'command': command})
        call('observe_ticks', {'ticks': 20, 'positions': [PRESS, DEPOT]})
        call('command', {'command': 'data merge block 488 64 24 ' + INPUT})
        initial = call('block', {'pos': PRESS})
        initial_depot = call('block', {'pos': DEPOT})
        observed = call('observe_ticks', {'ticks': 100, 'positions': [PRESS, DEPOT]})
        rows = [initial['nbt']] + [sample['blocks'][0]['nbt'] for sample in observed['samples']]
        report['lifecycle'] = lifecycle(rows)
        report['slide'] = slide_trace([initial_depot['nbt']] + [sample['blocks'][1]['nbt']
                                                               for sample in observed['samples']])
        report['samples'] = observed['samples']
        final = call('block', {'pos': DEPOT})
        assert 'minecraft:copper_ingot' not in final['nbt'], final
        for command, marker in zip(OUTPUT_CHECKS, OUTPUT_MARKERS):
            reply = call('command', {'command': command})
            assert marker in json.dumps(reply), (command, reply)
        report.update(passed=True, depot=final)
    except Exception as error:
        report['error'] = repr(error)
        raise
    finally:
        save()
        print(json.dumps({'result': str(work/'result.json'), 'passed': report['passed']}), flush=True)
    return report


def run_native(game, resources, ctl, create_jar, reference=None):
    session = NativeCheckSession(game, resources, ctl, create_jar,
                                 name='press-finished-native', graphics=False)
    report = {'passed': False, 'reference': PINS['create_revision'], 'scope': __doc__,
              'game_sha256': hashlib.sha256(session.game.read_bytes()).hexdigest()}
    script, output = session.scratch/'commands.jsonl', session.scratch/'observations.jsonl'
    operations = [{'op': 'cmd', 'cmd': 'tp @s 490.5 64 26.5', 'record': False}, {'op': 'settle'}]

    def command(text, record=False):
        operations.append({'op': 'cmd', 'cmd': text, 'record': record})

    command('tick unfreeze')
    for value in setup(): command(value)
    operations.append({'op': 'tick', 'n': 20})
    command('data merge block 488 64 24 ' + INPUT)
    command('data get block 488 66 24', True)
    command('data get block 488 64 24', True)
    for _ in range(100):
        operations.append({'op': 'tick', 'n': 1})
        command('data get block 488 66 24', True)
        command('data get block 488 64 24', True)
    command('data get block 488 64 24', True)
    for check in OUTPUT_CHECKS:
        command(check, True)
    script.write_text(''.join(json.dumps(op)+'\n' for op in operations))
    session.env.update(HORIZON_COMMAND_SCRIPT=str(script), HORIZON_COMMAND_OUTPUT=str(output),
                       HORIZON_API_DISCOVERY='http://127.0.0.1:9/')
    try:
        with session.log.open('w') as log:
            subprocess.run([str(session.game), '--headless', '--resources', str(session.resources),
                            '--world', 'CreateParity06', '--seed', '5', '--creative', '--render-distance', '2'],
                           cwd=session.scratch, env=session.env, stdout=log,
                           stderr=subprocess.STDOUT, check=True, timeout=300)
        rows = [json.loads(line) for line in output.read_text().splitlines()]
        assert len(rows) == 203 + len(OUTPUT_CHECKS), len(rows)
        text = lambda row: ' '.join(''.join(span[0] for span in message) for message in row['messages'])
        report['lifecycle'] = lifecycle([text(row) for row in rows[:202:2]])
        report['slide'] = slide_trace([text(row) for row in rows[1:202:2]])
        if reference:
            source = json.loads(Path(reference).read_text())
            assert source['passed'] and source['reference'] == report['reference']
            assert report['lifecycle'] == source['lifecycle'], (
                report['lifecycle']['starts'], source['lifecycle']['starts'])
            for native, java in zip(report['slide'], source['slide'], strict=True):
                assert all(math.isclose(native[key], java[key], abs_tol=1e-7) for key in native), (native, java)
        final = text(rows[202])
        assert 'minecraft:copper_ingot' not in final and 'create:copper_sheet' in final, final
        for row, marker in zip(rows[203:], OUTPUT_MARKERS):
            assert marker in text(row), row
        report.update(passed=True, depot=final)
    except Exception as error:
        report['error'] = repr(error)
        raise
    finally:
        (session.scratch/'result.json').write_text(json.dumps(report, indent=2)+'\n')
        session.control_temp.cleanup()
        print(json.dumps({'result': str(session.scratch/'result.json'), 'passed': report['passed']}), flush=True)
    return report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--reference', type=Path)
    for name in ('game', 'resources', 'ctl', 'create-jar'): parser.add_argument('--'+name)
    args = parser.parse_args()
    if args.java: run_java()
    else:
        assert all([args.game, args.resources, args.ctl, args.create_jar])
        run_native(args.game, args.resources, args.ctl, args.create_jar, args.reference)
