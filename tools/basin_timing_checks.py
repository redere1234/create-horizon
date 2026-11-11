"""Observe real Mixer cycles through Horizon's existing command harness.

The harness advances the ordinary authoritative server with tick_server(false),
then runs read-only commands between ticks. It does not call Mixer methods or
replace the clock. This avoids control-socket races and /tick sprint's extra tick.
Intake is seeded through canonical NBT: falling-item Basin intake is a separate,
unsupported adapter and is not asserted here. Rendering is not observed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from basin_native_checks import write_shared_fixture
from common import ROOT, PINS
from native_check_session import NativeCheckSession
from native_motors import replace_motor


def run(game, resources, ctl, create_jar):
    session = NativeCheckSession(game, resources, ctl, create_jar,
                                 name='basin-timing', graphics=False)
    report = {'passed': False, 'game': str(session.game),
              'game_sha256': hashlib.sha256(session.game.read_bytes()).hexdigest(),
              'reference': PINS['create_revision'],
              'scope': __doc__}
    script = session.scratch / 'commands.jsonl'
    output = session.scratch / 'observations.jsonl'
    fixture = session.scratch / 'schematics/own-basin-mixer.nbt'
    report['fixture'] = write_shared_fixture(fixture)
    operations = []

    def command(text, record=False):
        operations.append({'op': 'cmd', 'cmd': text, 'record': record})

    def motor_command(operation, text):
        """Record the helper's ordinary commands without advancing harness ticks."""
        assert operation == 'command', operation
        command(text)

    command('tick unfreeze')
    command('gamemode creative')
    command('tp @s 4.5 64 4.5')
    operations.append({'op': 'settle'})
    command('fill -2 63 -2 8 70 8 minecraft:air')
    # Native /create is a player command adapter; this engine harness runs
    # vanilla console commands. Place the shared fixture's40 authored blocks
    # normally and label that boundary rather than pretending to paste a file.
    for x in range(6):
        for z in range(6):
            command(f'setblock {x} 63 {z} minecraft:smooth_stone', True)
    for pos, block in [('1 65 2', 'create:creative_motor[facing=up]'),
                       ('1 66 2', 'create:cogwheel[axis=y]'),
                       ('2 64 2', 'create:basin[facing=down]'),
                       ('2 66 2', 'create:mechanical_mixer')]:
        command('setblock '+pos+' '+block, True)
    report['fixture']['placement'] = '40 ordinary setblock commands from the shared authored fixture; no schematic-import claim'
    replace_motor(motor_command, (1, 65, 2), 0, 'up')
    operations.append({'op': 'tick', 'n': 20})
    command('data merge block 2 64 2 {InputItems:{Size:9,Items:['
            '{Slot:0,id:"minecraft:andesite",count:2},'
            '{Slot:1,id:"minecraft:iron_nugget",count:2}]},'
            'OutputItems:{Size:9,Items:[]}}')
    replace_motor(motor_command, (1, 65, 2), 32, 'up')
    setup_records = sum(op.get('record', True) for op in operations if op['op'] == 'cmd')
    for _ in range(200):
        operations.append({'op': 'tick', 'n': 1})
        command('time query gametime', True)
        command('data get block 2 66 2', True)
        command('data get block 2 64 2 OutputItems', True)
    command('data get block 2 64 2 InputItems', True)
    script.write_text(''.join(json.dumps(op)+'\n' for op in operations))
    session.env.update({'HORIZON_COMMAND_SCRIPT': str(script),
                        'HORIZON_COMMAND_OUTPUT': str(output),
                        'HORIZON_API_DISCOVERY': 'http://127.0.0.1:9/'})
    print(json.dumps({'scratch': str(session.scratch)}), flush=True)
    try:
        with session.log.open('w') as log:
            process = subprocess.run([str(session.game), '--headless', '--resources', str(session.resources),
                '--world', 'CreateParity06', '--seed', '5', '--creative', '--render-distance', '2'],
                cwd=session.scratch, env=session.env, stdout=log, stderr=subprocess.STDOUT,
                timeout=300)
        assert process.returncode == 0, (process.returncode, str(session.log))
        rows = [json.loads(line) for line in output.read_text().splitlines()]
        assert len(rows) == setup_records+601, len(rows)

        def text(row):
            return ' '.join(''.join(span[0] for span in message) for message in row['messages'])

        assert all(row['results'] == [[True, 1]] for row in rows[:setup_records]), rows[:setup_records]
        snapshots = []
        for index in range(200):
            clock, mixer, items = rows[setup_records+index*3:setup_records+index*3+3]
            timestamp = re.findall(r'\b\d+\b', text(clock))
            assert len(timestamp) == 1, clock
            fields = {key: re.search(r'\b'+key+r':\s*(-?[\d.]+)', text(mixer))
                      for key in ['Running', 'Ticks', 'Speed']}
            assert all(fields.values()), mixer
            count = re.findall(r'\bcount:\s*(\d+)', text(items))
            assert len(count) <= 1, items
            amount = int(count[0]) if count else 0
            if amount:
                assert 'create:andesite_alloy' in text(items), items
            snapshots.append({'time': int(timestamp[0]),
                'running': int(float(fields['Running'][1])),
                'ticks': int(float(fields['Ticks'][1])),
                'speed': float(fields['Speed'][1]), 'alloy': amount})
        assert all(b['time'] == a['time']+1 for a,b in zip(snapshots,snapshots[1:])), snapshots
        starts = [i for i,s in enumerate(snapshots) if s['running'] == 1 and s['ticks'] == 1]
        assert starts, snapshots[:10]
        start = starts[0]
        first = next(i for i,s in enumerate(snapshots) if s['alloy'] == 1)
        second = next(i for i,s in enumerate(snapshots) if s['alloy'] == 2)
        assert first-start == 82 and second-first == 62, (start, first, second)
        assert all(s['alloy'] == (0 if i < first else 1 if i < second else 2)
                   for i,s in enumerate(snapshots)), snapshots
        assert all(abs(s['speed']) == 32 for s in snapshots[start:second+1])
        assert re.search(r'\bItems:\s*\[\]', text(rows[-1])), rows[-1]
        report.update({'passed': True, 'snapshots': snapshots, 'start_index': start,
                       'first_index': first, 'second_index': second,
                       'first_cycle_inclusive_ticks': first-start+1,
                       'repeat_ticks': second-first})
    finally:
        (session.scratch / 'result.json').write_text(json.dumps(report, indent=2)+'\n')
        session.control_temp.cleanup()
    print(json.dumps({'passed': True, 'result': str(session.scratch/'result.json')}), flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['game', 'resources', 'ctl', 'create-jar']:
        parser.add_argument('--'+name, required=True)
    args = parser.parse_args()
    run(args.game, args.resources, args.ctl, args.create_jar)
