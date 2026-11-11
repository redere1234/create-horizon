"""Original-Java half of the nine authored Basin bucket transitions.

Requires exclusive ownership of the already-running isolated reference bridge.
Does not launch Java, read accounts, or access any player's Prism world.
"""
import json
from pathlib import Path
import re
import tempfile

from common import ROOT, PINS
import reference_java as java


def run(base=java.BASE, scratch=None):
    base=Path(base).resolve()
    assert base==java.BASE.resolve(), 'Only the prepared private reference is authorized'
    manifest=json.loads((base/'manifest.json').read_text())
    assert manifest['data_version']==3955 and manifest['create']=='6.0.10'
    assert manifest['create_sha256']==java.CREATE_SHA256
    scratch=Path(scratch).resolve() if scratch else Path(tempfile.mkdtemp(prefix='basin-java-fluids-',dir=ROOT/'.local'))
    scratch.relative_to((ROOT/'.local').resolve());scratch.mkdir(parents=True,exist_ok=True)
    pos=[454,64,18]
    report={'passed':False,'source':PINS['create_revision'],'cases':[],
            'scope':'nine normal single-use bucket transitions; no exact timing/render/component-override claim'}
    trace=[]
    def save():
        (scratch/'java-result.json').write_text(json.dumps(report,indent=2)+'\n')
        (scratch/'java-transcript.json').write_text(json.dumps(trace,indent=2)+'\n')
    def call(method,body):
        reply=java.call(base,method,body)
        trace.append({'method':method,'body':body,'reply':reply});save();return reply
    def cmd(command):return call('command',{'command':command})
    def text(command):return ' '.join(cmd(command)['messages'])
    def tanks():
        out=[]
        for half in ['InputTanks','OutputTanks']:
            for i in range(2):
                nbt=text(f'data get block 454 64 18 {half}[{i}].TankContent')
                fluid=re.search(r'\bid:\s*"(minecraft:(?:water|lava))"',nbt)
                amount=re.search(r'\bamount:\s*(\d+)',nbt)
                assert bool(fluid)==bool(amount),nbt
                out.append((fluid[1],int(amount[1])) if fluid else None)
        return out
    def snapshot():return {'basin':call('block',{'pos':pos}),
                           'inventory':cmd('data get entity @s Inventory'),'tanks':tanks()}
    def held(item):
        cmd('clear @s');cmd('item replace entity @s weapon.mainhand with minecraft:'+item+' 1')
    def click(name,expected,item):
        before=snapshot();before['state']=call('state',{})
        assert before['state']['hit']['pos']==list(map(float,pos)),before['state']['hit']
        call('tick',{'step':7})
        call('input',{'key':'use'}) # bridge's single pulse releases at ClientTick
        call('capture',{'name':'basin-fluid-'+name+'.png','frames':5})
        call('input',{'key':'use','down':False})
        call('capture',{'name':'basin-fluid-after.png','frames':4})
        after=snapshot();report['cases'].append({'name':name,'before':before,'after':after});save()
        assert after['tanks']==expected,(name,after['tanks'],expected)
        inv=' '.join(after['inventory']['messages'])
        assert re.findall(r'\bid:\s*"([^"]+)"',inv)==['minecraft:'+item],inv
        assert re.findall(r'\bcount:\s*(\d+)',inv)==['1'],inv
    initial=call('state',{});assert initial['ready'] and initial['data_version']==3955
    try:
        call('tick',{'frozen':True});cmd('gamemode creative')
        cmd('forceload add 448 16 464 32')
        cmd('fill 450 63 14 460 70 24 minecraft:air')
        cmd('fill 450 63 14 460 63 24 minecraft:smooth_stone')
        cmd('setblock 454 64 18 create:basin')
        call('camera',{'position':[456.5,64,20.5],'target':[454.5,64.5,18.5],'hide_gui':False})
        empty=[None]*4
        held('water_bucket');click('creative-water-first',[('minecraft:water',1000),None,None,None],'water_bucket')
        held('lava_bucket');click('creative-lava-second',[('minecraft:water',1000),('minecraft:lava',1000),None,None],'lava_bucket')
        held('bucket');click('creative-drain-first',[None,('minecraft:lava',1000),None,None],'bucket')
        click('creative-drain-second',empty,'bucket')
        cmd('gamemode survival')
        held('water_bucket');click('survival-water-first',[('minecraft:water',1000),None,None,None],'bucket')
        held('bucket');click('survival-drain-first',empty,'water_bucket')
        cmd('gamemode creative');held('water_bucket')
        for name in ['creative-water-1000','creative-water-2000','creative-full-no-spill']:
            click(name,[('minecraft:water',1000),None,None,None],'water_bucket')
        report['adjacent']=call('block',{'pos':[455,64,18]})
        assert report['adjacent']['id']=='minecraft:air',report['adjacent']
        report['passed']=True;save();return report
    except Exception as error:
        report['error']=repr(error);save();raise
    finally:
        call('input',{'key':'use','down':False})
        call('tick',{'frozen':initial['server']['frozen']})
