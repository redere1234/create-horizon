#!/usr/bin/env python3
"""Exercise only the delivered station13 machines on a marked disposable clone.

The authored source is never opened or repaired. No ingredients, fluid, output,
machine counters, geometry or recipes are supplied by this helper. Motor scroll
values, ordinary ticks and empty-hand interactions operate the three real rigs.
Screenshots are actual native frames and require separate human review.
"""
import collections
import json
from pathlib import Path
import re

from burner_heat_java_checks import field, items
from native_check_session import wait_loaded

BASINS = ((60,64,20),(66,64,20),(72,64,20))
CASES = (
    ('snowblocks', {'minecraft:snowball':8}, {'minecraft:snow_block':2}),
    ('ice', {'minecraft:snow_block':9}, {'minecraft:ice':1}),
    ('andesite', {'minecraft:flint':2,'minecraft:gravel':1}, {'minecraft:andesite':1}),
)
STOCK = (72,64,24)


def _counts(slots):
    result=collections.Counter()
    for stack in slots:
        if stack and stack.get('item'):result[stack['item']]+=stack['count']
    return dict(result)


def _fluids(nbt,key):
    tanks=field(nbt,key);result=[]
    for match in re.finditer(r'\bTankContent\s*:',tanks):
        content=field(tanks[match.start():],'TankContent')
        if not re.search(r'\bFluid\s*:',content):
            assert content.strip()=='{}',content
            result.append(None);continue
        fluid=field(content,'Fluid')
        ids=re.findall(r'\bid\s*:\s*"([^"]+)"',fluid)
        amounts=re.findall(r'\bamount\s*:\s*(\d+)',fluid)
        assert len(ids)==len(amounts)==1,fluid
        result.append([ids[0],int(amounts[0])])
    assert len(result)==2,(key,tanks)
    return result


def _number(nbt,key):
    match=re.search(r'\b'+re.escape(key)+r'\s*:\s*(-?[\d.]+)',nbt)
    assert match,(key,nbt)
    return float(match[1])


def _snapshot(call,pos):
    raw=' '.join(call('command','data get block '+' '.join(map(str,pos)))['chat'])
    slots=call('container',*pos)['slots']
    assert len(slots)==18,(pos,slots)
    result={'input':items(raw,'InputItems'),'output':items(raw,'OutputItems'),
            'input_tanks':_fluids(raw,'InputTanks'),'output_tanks':_fluids(raw,'OutputTanks'),
            'slots':slots,'canonical_nbt':raw}
    assert _counts(slots[:9])==result['input'] and _counts(slots[9:])==result['output'],result
    assert re.search(r'\bSize\s*:\s*9\b',field(raw,'InputItems')),raw
    assert re.search(r'\bSize\s*:\s*9\b',field(raw,'OutputItems')),raw
    return result


def _contents(snapshot,inputs,outputs,lava=0):
    assert snapshot['input']==inputs and snapshot['output']==outputs,snapshot
    assert snapshot['input_tanks']==([['minecraft:lava',lava],None] if lava else [None,None]),snapshot
    assert snapshot['output_tanks']==[None,None],snapshot


def inspect(call,scratch):
    """Strict read-only initial stocks; this must run before any pickup/repair."""
    from review_map_06_checks import _clone
    _,marker=_clone(scratch)
    assert marker.get('include_compacting'),'The completed authored plan must contain station13'
    assert call('state')['world']=='CreateFactory06'
    wait_loaded(call,[*BASINS,*[(x,66,z) for x,_,z in BASINS],STOCK])
    rows=[]
    for pos,(name,inputs,_) in zip(BASINS,CASES):
        x,y,z=pos
        for block_pos,block,property in [(pos,'create:basin','facing=down'),
            ((x,y+2,z),'create:mechanical_press','facing=east'),
            ((x-1,y+2,z),'create:shaft','axis=x'),
            ((x-2,y+2,z),'create:creative_motor','facing=east')]:
            got=call('block',*block_pos)
            assert got['loaded'] and got['block']==block and property in got['state'],got
        motor=' '.join(call('command',f'data get block {x-2} {y+2} {z}')['chat'])
        assert _number(motor,'ScrollValue')==0 and _number(motor,'Speed')==0,motor
        snapshot=_snapshot(call,pos)
        _contents(snapshot,inputs,{},1000 if name=='andesite' else 0)
        rows.append({'name':name,'pos':pos,'initial':snapshot,'motor_nbt':motor})
    assert call('block',*STOCK)['block']=='minecraft:barrel'
    stock=call('container',*STOCK)['slots']
    assert _counts(stock)=={'minecraft:snowball':16,'minecraft:snow_block':64,
        'minecraft:flint':64,'minecraft:gravel':64,'minecraft:lava_bucket':1,'minecraft:bucket':4},stock
    sign=' '.join(call('command','data get block 66 64 24 front_text.messages')['chat'])
    assert 'УПЛОТНЕНИЕ' in sign,sign
    return {'passed':True,'machines':rows,'stock_slots':stock,'station_sign':sign}


def run(call,graphics=False,log=None,scratch=None):
    from review_map_06_checks import _clone, _grounded, _source_unchanged
    scratch,marker=_clone(scratch)
    report={'passed':False,'scope':__doc__,'source':marker['source'],'clone':marker['clone'],
            'images':[],'source_world_modified':False,'human_visual_review':'pending' if graphics else 'not captured'}
    output=scratch/'review06-compacting-result.json'
    def save():output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    def ctl(*words):
        reply=call(*words)
        with (scratch/'review06-compacting-transcript.jsonl').open('a') as stream:
            stream.write(json.dumps({'command':list(words),'reply':reply},ensure_ascii=False)+'\n')
        return reply
    def cmd(line):return ctl('command',line)
    def game_time():
        values=re.findall(r'\b\d+\b',' '.join(cmd('time query gametime')['chat']))
        assert len(values)==1,values
        return int(values[0])
    def motor(pos,value):
        x,y,z=pos;cmd(f'data merge block {x-2} {y+2} {z} {{ScrollValue:{value}}}')
    def snapshots():return [_snapshot(ctl,pos) for pos in BASINS]
    def expected(rows):
        return all(row['input']=={} and row['output']==case[2] for row,case in zip(rows,CASES))
    try:
        report['initial']=inspect(ctl,scratch);save()
        cmd('gamemode survival');cmd('clear @s');ctl('wait',5)
        _grounded(ctl,(68.5,64,27.5))
        assert ctl('state')['held'] is None and ctl('inventory')['counts']=={}
        cmd('tick rate 20');cmd('tick unfreeze')
        for pos in BASINS:motor(pos,32)
        rows=None
        for _ in range(160):
            rows=snapshots()
            if expected(rows):break
            ctl('wait',10)
        else:raise AssertionError(('Delivered compacting machines did not complete',rows))
        for row,case in zip(rows,CASES):_contents(row,{},case[2],900 if case[0]=='andesite' else 0)
        report['processed']=rows;save()
        # Remain normally powered long enough for another cycle if stale input
        # or an invalid repeat existed. No timer/counter/debug-step mutation.
        stable_start=game_time()
        for _ in range(180):
            ctl('wait',10)
            if game_time()-stable_start>=180:break
        else:raise AssertionError('Ordinary server time did not advance for the repeat-output check')
        stable=snapshots()
        for row,case in zip(stable,CASES):_contents(row,{},case[2],900 if case[0]=='andesite' else 0)
        report['powered_no_second_produce']=stable
        report['powered_no_second_produce_game_ticks']=game_time()-stable_start
        for pos in BASINS:motor(pos,0)
        ctl('wait',25)
        for x,y,z in BASINS:
            motor_nbt=' '.join(cmd(f'data get block {x-2} {y+2} {z}')['chat'])
            press_nbt=' '.join(cmd(f'data get block {x} {y+2} {z}')['chat'])
            assert _number(motor_nbt,'ScrollValue')==0 and _number(press_nbt,'Speed')==0,(motor_nbt,press_nbt)
        if graphics:
            for pos,case in zip(BASINS,CASES):
                x,y,z=pos;_grounded(ctl,(x+3.5,y,z+4.5))
                ctl('look-at',x+.5,y+1.1,z+.5);ctl('wait',25)
                assert ctl('state')['held'] is None
                path=scratch/('review06-compacting-'+case[0]+'.png')
                ctl('screenshot',str(path));assert path.is_file() and path.stat().st_size>1024,path
                report['images'].append(str(path))
        collected=collections.Counter();pickups=[]
        for pos,case in zip(BASINS,CASES):
            x,y,z=pos;_grounded(ctl,(x+.5,y,z+2.5))
            hotbar=ctl('inventory')['hotbar']
            empty=next(i for i,stack in enumerate(hotbar) if not stack.get('item'))
            ctl('key',str(empty+1),'tap')
            ctl('wait',4);assert ctl('state')['held'] is None
            ctl('look-at','block',*pos,'south');ctl('wait',3)
            hit=ctl('state').get('looking_at')
            assert hit and hit.get('kind')=='block' and hit['block']['pos']==list(pos),hit
            ctl('interact',*pos,'south');ctl('wait',8)
            collected.update(case[2])
            inventory=ctl('inventory')
            assert inventory['counts']==dict(collected),(case,inventory,collected)
            row=_snapshot(ctl,pos);_contents(row,{},{},900 if case[0]=='andesite' else 0)
            pickups.append({'name':case[0],'inventory':inventory,'basin':row})
        report['manual_pickups']=pickups
        assert ctl('container',*STOCK)['slots']==report['initial']['stock_slots'],'Delivered stock barrel changed'
        _source_unchanged(marker)
        report['passed']=True;save();return report
    except BaseException as error:
        report['error']=repr(error);save();raise
