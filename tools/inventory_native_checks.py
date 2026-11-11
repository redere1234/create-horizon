#!/usr/bin/env python3
"""Real Create inventory load, packet, hopper and process-restart checks.

The level stays frozen for canonical command/receipt checks, so a later machine
tick cannot repair an incorrectly decoded inventory. Hopper checks use ordinary
unfrozen simulation. Unsupported edited sizes must remain opaque and recoverable.
No production save is opened. This is inventory evidence, not rendering parity.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path

from native_check_session import NativeCheckSession, wait_loaded
from saved_block_checks import read_saved_block

SCHEMAS = [
    dict(block='create:basin', pos=(624,64,0), input='InputItems', output='OutputItems', size=9),
    dict(block='create:millstone', pos=(630,64,0), input='InputInventory', output='OutputInventory', size=1),
]
PATCH = '{"minecraft:custom_data":{inventory_marker:924},"!minecraft:custom_name":{}}'


def xyz(pos):
    return ' '.join(map(str,pos))


def canonical(schema):
    return ('{'+schema['input']+':{Size:'+str(schema['size'])+',InventoryUnknown:{keep:29L},'
        'Items:[{Slot:0,id:"minecraft:wheat",count:3,components:'+PATCH+'}]},'
        +schema['output']+':{Size:9,InventoryUnknown:{keep:[I;2,9,4]},'
        'Items:[{Slot:8,id:"create:wheat_flour",count:4}]},fixture_unknown:{keep:1b},'
        'Items:[{Slot:0b,id:"minecraft:diamond",count:99}]}')


def counts(call,pos):
    result=collections.Counter()
    for item in call('container',*pos)['slots']:
        if item and item.get('item'):
            result[item['item']]+=item['count']
    return dict(result)


def run(call,scratch):
    scratch=Path(scratch)
    report=dict(passed=False,scope=__doc__,checks=[])
    def cmd(text):
        return call('command',text)
    def raw(pos):
        return ' '.join(cmd('data get block '+xyz(pos))['chat'])
    def check(name,**details):
        report['checks'].append(dict(name=name,**details))
        (scratch/'inventory-native-result.json').write_text(json.dumps(report,indent=2)+'\n')
    def seed(schema):
        cmd('data merge block '+xyz(schema['pos'])+' '+canonical(schema))
        call('wait',6)
    cmd('gamemode creative');cmd('tp @s 627.5 70 3.5')
    call('wait-ready',120)
    wait_loaded(call,[s['pos'] for s in SCHEMAS])
    cmd('fill 620 63 -3 635 68 6 minecraft:air')
    cmd('fill 620 63 -3 635 63 6 minecraft:smooth_stone')
    cmd('tp @s 627.5 64 3.5');call('wait',8)
    cmd('tick freeze')
    for schema in SCHEMAS:
        pos=schema['pos'];name=schema['block']
        cmd('setblock '+xyz(pos)+' '+name)
        seed(schema)
        assert counts(call,pos)=={'minecraft:wheat':3,'create:wheat_flour':4},raw(pos)
        assert 'inventory_marker: 924' in raw(pos),raw(pos)
        check(name+' canonical slots are available while machine ticks are frozen')
        for key,expected in [(schema['input'],{'create:wheat_flour':4}),(schema['output'],{})]:
            cmd('data remove block '+xyz(pos)+' '+key);call('wait',6)
            assert counts(call,pos)==expected,(name,key,counts(call,pos),raw(pos))
        check(name+' canonical removals clear both authoritative halves without generic Items resurrection')

        # Merge five equivalent stacks through the normal hopper path. Neither
        # the first machine tick nor a stale bridge may overwrite the old three.
        seed(schema)
        hopper=(pos[0],pos[1]+1,pos[2])
        cmd('setblock '+xyz(hopper)+' minecraft:hopper[facing=down]')
        cmd('data merge block '+xyz(hopper)+' {Items:[{Slot:0b,id:"minecraft:wheat",count:5,components:'+PATCH+'}]}')
        cmd('tick unfreeze')
        for _ in range(80):
            call('wait',10)
            if counts(call,hopper)=={}:
                break
        else:
            raise AssertionError((name,'ordinary input hopper did not drain',counts(call,hopper)))
        cmd('tick freeze');call('wait',6)
        assert counts(call,pos)=={'minecraft:wheat':8,'create:wheat_flour':4},(name,raw(pos))
        assert 'inventory_marker: 924' in raw(pos),raw(pos)
        check(name+' real hopper preserves canonical 3 + incoming5, components and output4')
        cmd('setblock '+xyz(hopper)+' minecraft:air')

        seed(schema)
        cmd('data merge block '+xyz(pos)+' {'+schema['input']+':{Size:'+str(schema['size']+1)+'}}')
        call('wait',6);before=raw(pos)
        assert counts(call,pos)=={},(name,counts(call,pos))
        cmd('tick unfreeze');call('wait',30);cmd('tick freeze')
        assert raw(pos)==before,(before,raw(pos))
        cmd(f'tp @s {pos[0]+2.5} 64 {pos[2]+2.5}');call('wait',6)
        call('break',*pos);call('wait',4)
        assert call('block',*pos)['block']==name and raw(pos)==before,(name,raw(pos))
        cmd('item replace entity @s weapon.mainhand with create:wrench')
        call('interact',*pos,'up');call('wait',4)
        assert raw(pos)==before,(name,raw(pos))
        cmd('clear @s')
        cmd('data merge block '+xyz(pos)+' {'+schema['input']+':{Size:'+str(schema['size'])+'}}')
        call('wait',6)
        assert counts(call,pos)=={'minecraft:wheat':3,'create:wheat_flour':4},(name,raw(pos))
        check(name+' unsupported size stays opaque through ticks/break/wrench and exact size restores both halves')
    call('save-all')
    report['saved']=[read_saved_block(scratch,s['pos']) for s in SCHEMAS]
    report['passed']=True
    (scratch/'inventory-native-result.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def reloaded(call,scratch,before):
    call('command','tick freeze')
    call('command','tp @s 627.5 64 3.5');call('wait',8)
    wait_loaded(call,[s['pos'] for s in SCHEMAS])
    for schema in SCHEMAS:
        pos=schema['pos']
        assert counts(call,pos)=={'minecraft:wheat':3,'create:wheat_flour':4},(schema,counts(call,pos))
        raw=' '.join(call('command','data get block '+xyz(pos))['chat'])
        for token in ['inventory_marker: 924','!minecraft:custom_name','InventoryUnknown','fixture_unknown']:
            assert token in raw,(token,raw)
        assert 'minecraft:diamond' not in raw,raw
    return dict(passed=True,scope='true process reload restores canonical slots/components and opaque siblings')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['game','resources','ctl','create-jar']:
        parser.add_argument('--'+name,required=True)
    args=parser.parse_args()
    session=NativeCheckSession(args.game,args.resources,args.ctl,args.create_jar,
        name='inventory-native',graphics=False)
    (session.scratch/'options.txt').write_text('tutorialStep:none\nchatVisibility:2\n')
    session.env.update(HORIZON_API_DISCOVERY='http://127.0.0.1:9/',HORIZON_NO_DISCORD='1')
    report=dict(passed=False,game_sha256=hashlib.sha256(session.game.read_bytes()).hexdigest(),home=str(session.scratch))
    print(json.dumps(report),flush=True)
    try:
        with session:
            report['native']=run(session.call,session.scratch)
            session.stop()
            report['saved_closed']=[read_saved_block(session.scratch,s['pos']) for s in SCHEMAS]
            assert all(a['nbt']==b['nbt'] for a,b in zip(report['saved_closed'],report['native']['saved']))
            session.start()
            report['restart']=reloaded(session.call,session.scratch,report['native'])
        report['passed']=True
    except BaseException as error:
        report['error']=repr(error)
        raise
    finally:
        (session.scratch/'aggregate-result.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(dict(passed=report['passed'],result=str(session.scratch/'aggregate-result.json'))),flush=True)


if __name__=='__main__':
    main()
