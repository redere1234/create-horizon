#!/usr/bin/env python3
"""Real native /data-load normalization versus source Basin notification.

Private command harness advances ordinary authoritative server ticks; no direct
Basin/Mixer calls, trait-hook substitute, frozen stepping, GPU or user save.
The corresponding original Java observation is mixer_deserialize_java_checks.py.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from common import PINS
from native_check_session import NativeCheckSession


def run(game, resources, ctl, create_jar, *, baseline=False):
    session = NativeCheckSession(game, resources, ctl, create_jar, name='basin-deserialize', graphics=False)
    report = {'passed': False, 'completed': False, 'source': PINS['create_revision'],
              'game': str(session.game), 'game_sha256': hashlib.sha256(session.game.read_bytes()).hexdigest(),
              'scope': __doc__, 'cases': [], 'baseline_divergence_expected': baseline}
    script = session.scratch / 'commands.jsonl'
    output = session.scratch / 'observations.jsonl'
    ops = []
    labels = []
    def cmd(text, label=None):
        ops.append({'op': 'cmd', 'cmd': text, 'record': label is not None})
        if label is not None: labels.append(label)
    def ticks(n): ops.append({'op': 'tick', 'n': n})
    def snap(case, phase, index=0):
        cmd('time query gametime', (case, phase, index, 'time'))
        cmd('data get block 2 66 2', (case, phase, index, 'mixer'))
        cmd('data get block 2 64 2 InputItems', (case, phase, index, 'input'))
    variants = [
        ('ordered', '9', [('0','1'),('1','1')], False),
        ('descending-slots', '9', [('0','1'),('1','1')], True),
        ('byte-slots', '9', [('0b','1'),('1b','1')], False),
        ('short-size-byte-count', '9s', [('0','1b'),('1','1b')], False),
    ]
    cmd('tick unfreeze'); cmd('gamemode creative'); cmd('tp @s 4.5 64 4.5')
    ops.append({'op': 'settle'})
    cmd('fill 0 63 0 5 63 5 minecraft:smooth_stone')
    for name, size, slots, reverse in variants:
        cmd('fill 0 64 0 5 70 5 minecraft:air')
        for pos, state in [('1 65 2','create:creative_motor[facing=up]'),('1 66 2','create:cogwheel[axis=y]'),
                           ('2 64 2','create:basin[facing=down]'),('2 66 2','create:mechanical_mixer')]:
            cmd('setblock '+pos+' '+state)
        cmd('data merge block 1 65 2 {ScrollValue:32}')
        ticks(30)  # Consume legitimate constructor/provisioning/network wakes.
        snap(name, 'before')
        entries = ['{Slot:'+slots[0][0]+',id:"minecraft:andesite",count:'+slots[0][1]+'}',
                   '{Slot:'+slots[1][0]+',id:"minecraft:iron_nugget",count:'+slots[1][1]+'}']
        if reverse: entries.reverse()
        cmd('data merge block 2 64 2 {InputItems:{Size:'+size+',Items:['+','.join(entries)+']},OutputItems:{Size:9,Items:[]}}', (name,'load',0,'command'))
        snap(name, 'immediate')
        for i in range(1,7): ticks(1); snap(name,'normal',i)
        # Actual graph change, with no edit to Mixer or Basin NBT.
        cmd('setblock 1 65 2 minecraft:air'); cmd('setblock 1 65 2 create:creative_motor[facing=up]')
        cmd('data merge block 1 65 2 {ScrollValue:64}')
        for i in range(1,13): ticks(1); snap(name,'positive',i)
    script.write_text(''.join(json.dumps(op)+'\n' for op in ops))
    session.env.update(HORIZON_COMMAND_SCRIPT=str(script), HORIZON_COMMAND_OUTPUT=str(output),
                       HORIZON_API_DISCOVERY='http://127.0.0.1:9/')
    print(json.dumps({'scratch':str(session.scratch), 'game':str(session.game)}), flush=True)
    try:
        with session.log.open('w') as log:
            process = subprocess.run([str(session.game),'--headless','--resources',str(session.resources),
                '--world','CreateParity06','--seed','5','--creative','--render-distance','2'],
                cwd=session.scratch,env=session.env,stdout=log,stderr=subprocess.STDOUT,timeout=300)
        assert process.returncode == 0, (process.returncode,str(session.log))
        rows = [json.loads(line) for line in output.read_text().splitlines()]
        assert len(rows) == len(labels), (len(rows),len(labels))
        records = {}
        def text(row): return ' '.join(''.join(span[0] for span in message) for message in row['messages'])
        def number(text,key):
            value = re.search(r'\b'+key+r':\s*(-?[\d.]+)',text)
            assert value,(key,text)
            return float(value[1])
        for label,row in zip(labels,rows): records[label] = {'raw':row,'text':text(row)}
        def state(name,phase,i=0):
            row = {key:records[(name,phase,i,key)] for key in ['time','mixer','input']}
            return {'time':int(re.findall(r'\b\d+\b',row['time']['text'])[0]),
                    'running':int(number(row['mixer']['text'],'Running')),
                    'pending':int(number(row['mixer']['text'],'NeedsUpdate')),
                    'rpm':number(row['mixer']['text'],'Speed'), 'input':row['input']['text'],
                    'raw':row}
        for name,_,_,_ in variants:
            before = state(name,'before'); immediate = state(name,'immediate')
            normal = [state(name,'normal',i) for i in range(1,7)]
            positive = [state(name,'positive',i) for i in range(1,13)]
            assert before['running'] == before['pending'] == 0 and abs(before['rpm']) == 32, before
            assert abs(immediate['rpm']) == 32 and immediate['running'] == 0, immediate
            assert all(abs(s['rpm']) == 32 for s in normal)
            assert [s['time'] for s in normal] == list(range(immediate['time']+1,immediate['time']+7))
            assert all('minecraft:andesite' in s['input'] and 'minecraft:iron_nugget' in s['input'] for s in [immediate,*normal,*positive])
            assert all(re.findall(r'\bcount:\s*(\d+)',s['input']) == ['1','1'] for s in [immediate,*normal,*positive])
            assert any(s['running'] for s in positive) and abs(positive[-1]['rpm']) == 64
            unexpected = [i+1 for i,s in enumerate(normal) if s['running'] or s['pending']]
            report['cases'].append({'name':name,'before':before,'immediate':immediate,'normal':normal,
                                    'positive':positive,'unexpected_wake_ticks':unexpected})
        report['completed'] = True
        report['passed'] = not any(row['unexpected_wake_ticks'] for row in report['cases'])
        if baseline:
            assert not report['passed'], 'Expected historical divergence was absent'
        else:
            assert report['passed'], 'Native normalization synthesized a Basin wake; see saved cases'
    finally:
        (session.scratch/'result.json').write_text(json.dumps(report,indent=2)+'\n')
        session.control_temp.cleanup()
    print(json.dumps({'passed':report['passed'],'baseline_proof':baseline and report['completed'],
                      'outcomes':{r['name']:r['unexpected_wake_ticks'] for r in report['cases']},
                      'result':str(session.scratch/'result.json')}),flush=True)
    return report


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['game','resources','ctl','create-jar']: p.add_argument('--'+name,required=True)
    p.add_argument('--baseline',action='store_true')
    a=p.parse_args();run(a.game,a.resources,a.ctl,a.create_jar,baseline=a.baseline)
