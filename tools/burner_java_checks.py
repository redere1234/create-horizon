#!/usr/bin/env python3
"""Original Create6.0.10 actual single-click burner and frozen fuel lifecycle.

Run only against the disposable reference_java instance. It changes a private
fixture and writes the full command/response trace; it never opens a user save.
The source-method oracle checks transition notifications independently.
"""
import argparse
import json
from pathlib import Path
import re
import tempfile
from common import ROOT, PINS
import reference_java


def run(base):
    scratch = Path(tempfile.mkdtemp(prefix='burner-java-clicks-', dir=ROOT/'.local'))
    result = {'passed':False,'reference':PINS['create_revision'],'checks':[],
              'scope':__doc__}
    trace = []
    def call(method, body):
        value = reference_java.call(base, method, body)
        trace.append({'method':method,'body':body,'reply':value})
        (scratch/'transcript.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2)+'\n')
        return value
    def cmd(command):
        return call('command', {'command':command})
    pos = [454,64,18]
    xyz = ' '.join(map(str,pos))
    def block(): return call('block',{'pos':pos})
    def number(data, key):
        found = re.search(r'\b'+key+r'\s*:\s*(-?\d+)',data.get('nbt',''))
        return int(found[1]) if found else 0
    def mark(name, data, fuel, time, heat, count, item):
        assert number(data,'fuelLevel') == fuel and number(data,'burnTimeRemaining') == time, (name,data)
        assert data['properties']['blaze'].lower() == heat, (name,data)
        state = call('state',{})
        inventory = cmd('data get entity @s SelectedItem')
        raw = ' '.join(inventory.get('messages', []))
        amount = re.search(r'\bcount\s*:\s*(\d+)', raw)
        held = {'id':state.get('held'),'count':int(amount[1]) if amount else 0,'server':inventory}
        assert held['id'] == item and held['count'] == count and ('"'+item+'"') in raw, (name,held)
        result['checks'].append({'name':name,'block':data,'held':held})
        (scratch/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    def prepare(heat='smouldering', fuel=0, time=0, item='minecraft:coal', count=3, creative=False, extra=''):
        call('tick',{'step':7}) # client use cooldown; reset canonical fixture AFTER these ticks
        cmd('gamemode '+('creative' if creative else 'survival'))
        cmd('setblock '+xyz+' minecraft:air')
        cmd('setblock '+xyz+' create:blaze_burner[blaze='+heat+',facing=north]')
        cmd('data merge block '+xyz+' {fuelLevel:'+str(fuel)+',burnTimeRemaining:'+str(time)+extra+'}')
        cmd('clear @s')
        if count: cmd('item replace entity @s weapon.mainhand with '+item+' '+str(count))
    def click():
        # Wait client frames after the server setup commands, so inventory and
        # chunk updates arrive before the real click. No server tick advances.
        call('capture',{'name':'burner-before.png','frames':24})
        ready = call('state',{})
        assert ready['ready'] and ready['hit']['block']=='create:blaze_burner', ready
        call('input',{'key':'use'})
        call('capture',{'name':'burner-check.png','frames':8})
        call('input',{'key':'use','down':False})
        call('capture',{'name':'burner-check.png','frames':8})
        return block()
    try:
        assert call('state',{})['ready']
        call('tick',{'frozen':True})
        cmd('gamemode creative')
        cmd('forceload add 448 16 464 32')
        cmd('fill 450 64 14 460 70 24 minecraft:air')
        cmd('fill 450 63 14 460 63 24 minecraft:smooth_stone')
        call('camera',{'position':[456.5,64,20.5],'target':[454.5,64.4,18.5],'hide_gui':False})
        prepare();mark('survival-coal',click(),1,1600,'kindled',2,'minecraft:coal')
        prepare(fuel=1,time=9999,heat='kindled');mark('overflow-cap',click(),1,10000,'kindled',2,'minecraft:coal')
        prepare(fuel=1,time=10000,heat='kindled');mark('cap-still-consumes',click(),1,10000,'kindled',2,'minecraft:coal')
        prepare(fuel=1,time=500,heat='kindled');mark('threshold-extends',click(),1,2100,'kindled',2,'minecraft:coal')
        prepare(item='create:blaze_cake');mark('special-upgrade',click(),2,3200,'seething',2,'create:blaze_cake')
        prepare(fuel=2,time=501,heat='seething',item='create:blaze_cake');mark('special-over-threshold-refused',click(),2,501,'seething',3,'create:blaze_cake')
        prepare(fuel=2,time=500,heat='seething',item='create:blaze_cake');mark('special-at-threshold',click(),2,3700,'seething',2,'create:blaze_cake')
        prepare(fuel=2,time=300,heat='seething');mark('fuel-downgrade-refused',click(),2,300,'seething',3,'minecraft:coal')
        prepare(creative=True);mark('creative-keeps-coal',click(),1,1600,'kindled',3,'minecraft:coal')
        prepare(item='minecraft:lava_bucket',count=1)
        mark('fuel-container-remainder',click(),1,20000,'kindled',1,'minecraft:bucket')
        prepare(item='create:creative_blaze_cake')
        data=click(); assert number(data,'isCreative')==1 and 'fuelLevel' not in data['nbt'] and 'burnTimeRemaining' not in data['nbt'],data
        mark('creative-cake-not-consumed',data,0,0,'kindled',3,'create:creative_blaze_cake')
        # The source burner still ticks when a debug step advances a frozen
        # world: unlike kinetic getSpeed, fuel tick does not gate on clock freeze.
        prepare(heat='seething',fuel=2,time=1)
        call('tick',{'step':1});data=block()
        assert (number(data,'fuelLevel'),number(data,'burnTimeRemaining'),data['properties']['blaze'].lower())==(1,5000,'kindled'),data
        result['checks'].append({'name':'special-expiry-frozen-step','block':data})
        prepare(heat='kindled',fuel=1,time=1)
        call('tick',{'step':1});data=block()
        assert (number(data,'fuelLevel'),number(data,'burnTimeRemaining'),data['properties']['blaze'].lower())==(0,0,'smouldering'),data
        result['checks'].append({'name':'normal-expiry-frozen-step','block':data})
        result['passed']=True
    finally:
        (scratch/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'passed':result['passed'],'checks':len(result['checks']),'result':str(scratch/'result.json')}))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',type=Path,default=ROOT/'.local/java-reference')
    args=parser.parse_args();run(args.base)


if __name__=='__main__':main()
