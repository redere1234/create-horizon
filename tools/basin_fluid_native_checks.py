"""Normal bucket/fluid recipe checks on an owned NativeCheckSession world.

The nine bucket transitions mirror the authored original-Java fixture. Simulation
is covered separately by the generic real-Game capability and canonical codec
checks. This runner does not claim exact client/render or serialization parity.
"""
import json
from pathlib import Path
import re

from common import ROOT, PINS
from native_check_session import wait_loaded
from native_motors import replace_motor

POS = (416, 64, 16)


def run(call, graphics=False, log=None, scratch=None):
    """Use real motor replacement for power; retain inventories and existing waits."""
    scratch = Path(scratch).resolve()
    scratch.relative_to((ROOT / '.local').resolve())
    assert call('state')['world'] == 'CreateParity06'
    x, y, z = POS
    report = {'passed': False, 'source': PINS['create_revision'], 'checks': [], 'cases': [], 'images': [],
              'known_differences': ['Level.Force one-shot serialization boundary',
                  'opaque fluid patches preserved in tanks but unsupported by plain bucket/render APIs',
                  'heated recipes, side spouts, filters and falling intake remain separate features']}
    result = scratch / 'basin-fluid-native-result.json'
    transcript = scratch / 'basin-fluid-native-transcript.jsonl'
    transcript.write_text('')

    def save(): result.write_text(json.dumps(report, indent=2) + '\n')
    def ctl(*args):
        reply = call(*args)
        with transcript.open('a') as f:
            f.write(json.dumps({'command': list(map(str, args)), 'reply': reply}) + '\n')
        return reply
    def cmd(text): return ctl('command', text)
    def text(command): return ' '.join(cmd(command)['chat'])
    def data(path=''): return text(f'data get block {x} {y} {z} ' + path)
    def tanks():
        values=[]
        for half in ['InputTanks', 'OutputTanks']:
            for i in range(2):
                current=data(f'{half}[{i}].TankContent')
                fluid=re.search(r'\bid:\s*"(minecraft:(?:water|lava))"',current)
                amount=re.search(r'\bamount:\s*(\d+)',current)
                assert bool(fluid)==bool(amount),(current,fluid,amount)
                values.append((fluid[1],int(amount[1])) if fluid else None)
        return values
    def held(item):
        cmd('clear @s')
        cmd('item replace entity @s weapon.mainhand with minecraft:'+item+' 1')
        ctl('wait',5)
    def counts():
        totals={}
        for item in ctl('container',x,y,z)['slots']:
            if item: totals[item['item']]=totals.get(item['item'],0)+item['count']
        return totals
    def passed(label): report['checks'].append(label);save()
    def click(name,expected,inventory):
        before={'tanks':tanks(),'inventory':ctl('inventory'),'nbt':data()}
        support=text(f'execute if block {x+2} {y-1} {z+2} minecraft:smooth_stone run say fluid_support_ok')
        assert 'fluid_support_ok' in support,support
        cmd(f'tp @s {x+2.5} {y} {z+2.5}')
        ctl('wait',3)
        state=ctl('state')['player']
        assert state['on_ground'] and abs(state['position'][1]-y)<.001,state
        ctl('look-at','block',x,y,z,'south')
        ctl('wait',2)
        ctl('interact',x,y,z,'south')
        ctl('wait',5)
        after={'tanks':tanks(),'inventory':ctl('inventory'),'nbt':data()}
        report['cases'].append({'name':name,'before':before,'after':after});save()
        assert after['tanks']==expected,(name,after['tanks'],expected)
        assert after['inventory']['counts']==inventory,(name,after['inventory'],inventory)
        assert ctl('state')['menu'] is None

    save()
    try:
        cmd('tick unfreeze')
        cmd('gamemode creative')
        cmd(f'tp @s {x+2.5} {y} {z+2.5}')
        ctl('wait-ready',120);ctl('wait',8)
        wait_loaded(ctl,[(px,y,pz) for px in [x-3,x+4] for pz in [z-3,z+4]])
        cmd(f'fill {x-3} {y-1} {z-3} {x+4} {y+5} {z+4} minecraft:air')
        cmd(f'fill {x-3} {y-1} {z-3} {x+4} {y-1} {z+4} minecraft:smooth_stone')
        cmd(f'setblock {x} {y} {z} create:basin[facing=down]')
        ctl('wait',5)
        empty=[None]*4
        held('water_bucket');click('creative-water-first',[('minecraft:water',1000),None,None,None],{'minecraft:water_bucket':1})
        held('lava_bucket');click('creative-lava-second',[('minecraft:water',1000),('minecraft:lava',1000),None,None],{'minecraft:lava_bucket':1})
        held('bucket');click('creative-drain-first',[None,('minecraft:lava',1000),None,None],{'minecraft:bucket':1})
        click('creative-drain-second',empty,{'minecraft:bucket':1})
        cmd('gamemode survival')
        held('water_bucket');click('survival-water-first',[('minecraft:water',1000),None,None,None],{'minecraft:bucket':1})
        held('bucket');click('survival-drain-first',empty,{'minecraft:water_bucket':1})
        cmd('gamemode creative')
        held('water_bucket')
        for label in ['creative-water-1000','creative-water-2000','creative-full-no-spill']:
            click(label,[('minecraft:water',1000),None,None,None],{'minecraft:water_bucket':1})
        assert 'fluid_no_spill' in text(f'execute if block {x+1} {y} {z} minecraft:air run say fluid_no_spill')
        passed('same nine ordinary bucket transitions as original Java: creative retention/draining, survival containers, repeat-water variety refusal and no adjacent spill')

        cmd(f'setblock {x-1} {y+1} {z} create:creative_motor[facing=up]')
        cmd(f'setblock {x-1} {y+2} {z} create:cogwheel[axis=y]')
        cmd(f'setblock {x} {y+2} {z} create:mechanical_mixer')
        replace_motor(ctl, (x-1, y+1, z), 0, 'up')
        cmd(f'data merge block {x} {y} {z} '+ '{InputItems:{Size:9,Items:[{Slot:0,id:"create:wheat_flour",count:2,components:{"minecraft:custom_data":{fluid_fixture:71}}}]},OutputItems:{Size:9,Items:[]}}')
        replace_motor(ctl, (x-1, y+1, z), 32, 'up')
        ctl('wait',180)
        assert counts()=={'create:wheat_flour':1,'create:dough':1},counts()
        assert tanks()==empty,tanks()
        assert 'fluid_fixture: 71' in data(),data()
        passed('flour +1000mB plain water produces one dough; remaining component-bearing flour retained; no bucket invented')

        # Freeze the drive before refilling: otherwise the remaining flour can
        # start another genuine dough cycle while the next fixture is prepared.
        replace_motor(ctl, (x-1, y+1, z), 0, 'up')
        ctl('wait',45)
        held('water_bucket');click('water-for-four-mud',[('minecraft:water',1000),None,None,None],{'minecraft:water_bucket':1})
        cmd(f'data merge block {x} {y} {z} '+ '{InputItems:{Size:9,Items:[{Slot:0,id:"minecraft:dirt",count:2},{Slot:1,id:"minecraft:coarse_dirt",count:1},{Slot:2,id:"minecraft:rooted_dirt",count:1}]},OutputItems:{Size:9,Items:[]}}')
        replace_motor(ctl, (x-1, y+1, z), 32, 'up')
        ctl('wait',350)
        assert counts()=={'minecraft:mud':4},counts()
        assert tanks()==empty,tanks()
        passed('actual source block tag matches dirt/coarse_dirt/rooted_dirt; +250mB water repeats four times, producing exactly four mud and draining1000mB')
        if graphics:
            replace_motor(ctl, (x-1, y+1, z), 0, 'up')
            held('water_bucket');click('render-water',[('minecraft:water',1000),None,None,None],{'minecraft:water_bucket':1})
            held('lava_bucket');click('render-lava',[('minecraft:water',1000),('minecraft:lava',1000),None,None],{'minecraft:lava_bucket':1})
            ctl('wait',35)
            cmd(f'setblock {x+2} {y} {z+2} minecraft:smooth_stone')
            cmd(f'tp @s {x+2.5} {y+1} {z+2.5}');ctl('wait',3)
            state=ctl('state')['player']
            assert state['on_ground'] and abs(state['position'][1]-y-1)<.001,state
            ctl('look-at',x+.5,y+.7,z+.5);ctl('wait',3)
            image=scratch/'basin-water-lava-native.png'
            ctl('key','f1','tap')
            try:
                ctl('wait',3);ctl('screenshot',image)
            finally:
                ctl('key','f1','tap')
            report['images'].append(str(image))
        report['passed']=True;save()
        return report
    except Exception as error:
        report['error']=repr(error);save();raise


def prepare_restart(call,scratch):
    """Stop by replacing only the motor before the existing persistence fixture."""
    x,y,z=POS
    assert call('state')['world']=='CreateParity06'
    replace_motor(call, (x-1, y+1, z), 0, 'up')
    call('wait',45)
    call('command',f'data merge block {x} {y} {z} '+ '{InputTanks:[{Level:{Value:.5f,Target:.5f,Speed:.25f},TankContent:{Fluid:{id:"minecraft:water",amount:500,components:{"!minecraft:custom_name":{},"minecraft:custom_data":{marker:919}}}}},{Level:{Value:1f,Target:1f,Speed:.25f},TankContent:{Fluid:{id:"minecraft:lava",amount:1000}}}],OutputTanks:[{Level:{Value:.25f,Target:.25f,Speed:.25f},TankContent:{Fluid:{id:"minecraft:water",amount:250,components:{"minecraft:custom_data":{marker:920}}}}},{Level:{Value:0f,Target:0f,Speed:.25f},TankContent:{}}]}')
    call('wait',5)
    fields=[call('command',f'data get block {x} {y} {z} {half}[{i}].TankContent')['chat']
            for half in ['InputTanks','OutputTanks'] for i in range(2)]
    call('save-all')
    result={'passed':False,'before':fields,'requires_actual_process_restart':True}
    (Path(scratch)/'basin-fluid-restart-result.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def verify_restart(call,scratch,before):
    x,y,z=POS
    assert call('state')['world']=='CreateParity06'
    call('command',f'tp @s {x+2.5} {y} {z+2.5}');call('wait-ready',120);call('wait',8)
    after=[call('command',f'data get block {x} {y} {z} {half}[{i}].TankContent')['chat']
           for half in ['InputTanks','OutputTanks'] for i in range(2)]
    assert after==before['before'],(before,after)
    result=dict(before,passed=True,after=after)
    (Path(scratch)/'basin-fluid-restart-result.json').write_text(json.dumps(result,indent=2)+'\n')
    return result
