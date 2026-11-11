#!/usr/bin/env python3
"""Check the review map's physical washing enclosure with ordinary fluid ticks.

No supplied save is opened: standalone mode authors three tiny fan lanes in a
fresh NativeCheckSession. Both map inspection and this fixture reject escaped
water, including newly waterlogged campfires. No fluid/fan simulation is mocked.
"""
import argparse
import hashlib
import json
from pathlib import Path

from native_check_session import NativeCheckSession, wait_loaded
from review_world_06 import FANS, fan_enclosure


def inspect(call):
    """Read-only map check: dry surroundings and the real open gate/medium."""
    source=(4,65,20)
    expected=[*fan_enclosure(20,FANS[0][1]),(source,FANS[0][1]),
              ((4,65,24),'minecraft:campfire[lit=true,waterlogged=false]'),
              ((4,65,28),'minecraft:soul_campfire[lit=true,waterlogged=false]')]
    geometry=[]
    for pos,state in expected:
        got=call('block',*pos);name=state.split('[',1)[0]
        assert got['loaded'] and got['block']==name,(pos,state,got)
        properties=state.partition('[')[2].rstrip(']').split(',') if '[' in state else []
        assert all(p in got['state'] for p in properties),(pos,state,got)
        geometry.append(got)
    leaks=[]
    for y in [64,65,66]:
        for x in range(0,11):
            for z in range(18,31):
                pos=(x,y,z);got=call('block',*pos)
                assert got['loaded'],got
                if pos!=source and (got['block']=='minecraft:water' or 'waterlogged=true' in got['state']):
                    leaks.append(got)
    assert not leaks,('Washing medium escaped its physical enclosure',leaks)
    return {'passed':True,'geometry':geometry,'dry_cells_checked':3*11*13-1,
            'scope':'No water/waterlogged cells around washing/smoking/haunting lanes except original washing medium'}


def run(call,scratch):
    """Fresh three-lane normal-tick integration; no /tick freeze or fake timers."""
    scratch=Path(scratch)
    assert call('state')['world']=='CreateWashing06'
    def cmd(line):
        reply=call('command',line)
        assert not any(any(error in text for error in ['Incorrect argument','Unknown block','Unknown or incomplete','not loaded']) for text in reply.get('chat',[])),(line,reply)
        return reply
    def put(pos,block):cmd('setblock '+' '.join(map(str,pos))+' '+block)
    def counts(pos):
        result={}
        for s in call('container',*pos)['slots']:
            if s:result[s['item']]=result.get(s['item'],0)+s['count']
        return result
    cmd('tick unfreeze');cmd('tick rate 20');cmd('gamemode creative')
    cmd('gamerule minecraft:spawn_mobs false')
    cmd('tp @s 8.5 80 24.5');cmd('forceload add -16 0 16 48');call('wait-ready',120)
    wait_loaded(call,[(-2,64,16),(12,64,32)])
    cmd('fill -2 64 16 12 85 32 minecraft:air');cmd('fill -2 63 16 12 63 32 minecraft:smooth_stone')
    # Local boundary excludes any pre-existing terrain water outside this
    # fixture. It is beyond the inspected lanes and does not contain the source.
    for x in range(-2,13):
        for z in [16,32]:
            for y in range(64,67):put((x,y,z),'minecraft:glass')
    for z in range(17,32):
        for x in [-2,12]:
            for y in range(64,67):put((x,y,z),'minecraft:glass')
    cmd('tp @s 9.5 64 22.5');call('wait-ready',120);call('wait',8)
    player=call('state')['player'];assert player['on_ground'] and not player['flying'],player
    for z,medium,item,_,_ in FANS[:3]:
        for x,block in [(1,'create:creative_motor[facing=east]'),(2,'create:shaft[axis=x]'),(3,'create:encased_fan[facing=east]')]:
            put((x,65,z),block)
        cmd(f'data merge block 1 65 {z} {{ScrollValue:0}}')
        put((6,64,z),'create:depot');put((8,65,z),'minecraft:glass')
        for pos,block in fan_enclosure(z,medium):put(pos,block)
        put((4,65,z),medium)
        slots=call('container',6,64,z,item,8)['slots']
        assert slots[0]=={'item':item,'count':8} and all(s is None for s in slots[1:]),slots
    start=call('status')['ticks'];call('wait',240)
    before=inspect(call)
    assert all(counts((6,64,z))=={item:8} for z,_,item,_,_ in FANS[:3])
    for z,_,_,_,_ in FANS[:3]:cmd(f'data merge block 1 65 {z} {{ScrollValue:32}}')
    expected={z:{out:8} for z,_,_,out,_ in FANS[:3]}
    for _ in range(160):
        if all(counts((6,64,z))==items for z,items in expected.items()):break
        call('wait',10)
    else:raise AssertionError(('Three fan lanes did not complete',expected,{z:counts((6,64,z)) for z in expected}))
    for z in expected:cmd(f'data merge block 1 65 {z} {{ScrollValue:0}}')
    call('wait',240);after=inspect(call)
    assert all(counts((6,64,z))==items for z,items in expected.items())
    end=call('status')['ticks']
    report={'passed':True,'before':before,'after':after,'outputs':expected,'ordinary_client_ticks_elapsed':end-start,
            'unpowered_settle_ticks':240,'post_processing_settle_ticks':240,'no_tick_freeze':True}
    (scratch/'washing-result.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ['game','resources','ctl','create-jar']:parser.add_argument('--'+key,required=True,type=Path)
    args=parser.parse_args()
    session=NativeCheckSession(args.game,args.resources,args.ctl,args.create_jar,name='review06-washing',graphics=False,
                               world='CreateWashing06',username='Delete228')
    for key in ['CREATE_HORIZON_TRACE','CREATE_HORIZON_TRACE_POSES','CREATE_HORIZON_PARTICLE_TRACE']:session.env.pop(key,None)
    session.env.update(HORIZON_API_DISCOVERY='http://127.0.0.1:9/',HORIZON_NO_DISCORD='1')
    result={'passed':False,'game':str(session.game),'game_sha256':hashlib.sha256(session.game.read_bytes()).hexdigest(),
            'scratch':str(session.scratch)}
    print(session.scratch,flush=True)
    try:
        with session:result['checks']=run(session.call,session.scratch)
        result['passed']=True
    finally:
        (session.scratch/'aggregate-result.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({'passed':result['passed'],'result':str(session.scratch/'aggregate-result.json')}),flush=True)


if __name__=='__main__':main()
