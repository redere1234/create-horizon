#!/usr/bin/env python3
"""Capture actual original Basin goggles rows and EN/RU layout for comparison.

Uses only the prepared disposable Java instance. JSON captures are evidence of
rendered source state; PNGs still require independent visual inspection.
"""
import hashlib
import json
import shutil
import zipfile
from pathlib import Path
import tempfile
from common import ROOT,PINS
import reference_java


def languages(base):
    extra=base/'libraries/net/minecraft/client/1.21.1-20240808.144430/client-1.21.1-20240808.144430-extra.jar'
    index=json.loads((base/'assets/indexes/17.json').read_text())['objects']
    with zipfile.ZipFile(extra) as jar:
        english=json.loads(jar.read('assets/minecraft/lang/en_us.json'))
    result={}
    for language in ['en_us','ru_ru']:
        if language=='en_us': current=dict(english)
        else:
            key=index['minecraft/lang/'+language+'.json']['hash']
            data=(base/'assets/objects'/key[:2]/key).read_bytes()
            assert hashlib.sha1(data).hexdigest()==key
            current=json.loads(data)
        current.update(json.loads((base/'text-resources/assets/create/lang'/ (language+'.json')).read_text()))
        result[language]=current
    return result


def main():
    base=ROOT/'.local/java-reference'
    work=Path(tempfile.mkdtemp(prefix='basin-tooltip-java-',dir=ROOT/'.local'))
    for language,values in languages(base).items():
        (work/('lang-'+language+'.json')).write_text(json.dumps(values,ensure_ascii=False)+'\n')
    trace=[];cases=[];result={'passed':False,'reference':PINS['create_revision'],'cases':cases,'scope':__doc__}
    def call(method,body):
        value=reference_java.call(base,method,body)
        trace.append({'method':method,'body':body,'reply':value})
        (work/'transcript.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2)+'\n')
        return value
    def cmd(text):return call('command',{'command':text})
    pos=[454,64,18];xyz=' '.join(map(str,pos))
    def tank(fluid,amount):
        return '{TankContent:{Fluid:{id:"minecraft:'+fluid+'",amount:'+str(amount)+'}},Level:{Value:1.0f,Target:1.0f,Speed:0.25f}}'
    empty='{TankContent:{},Level:{Value:0.0f,Target:0.0f,Speed:0.25f}}'
    def capture(name,nbt,language='en_us',goggles=True):
        cmd('setblock '+xyz+' minecraft:air');cmd('setblock '+xyz+' create:basin')
        if nbt:cmd('data merge block '+xyz+' '+nbt)
        cmd('item replace entity @s armor.head with '+('create:goggles' if goggles else 'minecraft:air'))
        call('language',{'language':language})
        for _ in range(20):
            if call('state',{})['ready']: break
            call('capture',{'name':'resource-loading.png','frames':20})
        else: raise AssertionError('The source resource reload overlay did not finish')
        call('camera',{'position':[456.5,64,20.5],'target':[454.5,64.55,18.5],'hide_gui':False})
        image=call('capture',{'name':'basin-tooltip-'+name+'.png','frames':80})
        original=Path(image['path']); preserved=work/(name+'.png')
        shutil.copy2(original,preserved)
        image=dict(image,original_path=str(original),path=str(preserved),sha256=hashlib.sha256(preserved.read_bytes()).hexdigest())
        state=call('state',{});ui=call('ui',{})
        case={'name':name,'language':language,'seed_nbt':nbt,'goggles':goggles,'state':state,'ui':ui,'capture':image,'visually_inspected':False}
        cases.append(case);(work/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        assert state['ready'] and state['hit']['block']=='create:basin',state
        return case
    try:
        assert call('state',{})['ready'];call('tick',{'frozen':True});cmd('gamemode creative')
        cmd('forceload add 448 16 464 32');cmd('fill 450 64 14 460 70 24 minecraft:air');cmd('fill 450 63 14 460 63 24 minecraft:smooth_stone');cmd('clear @s')
        inventory='{InputItems:{Size:9,Items:[{Slot:0,id:"minecraft:copper_ingot",count:8}]},OutputItems:{Size:9,Items:[{Slot:0,id:"minecraft:gold_nugget",count:3}]}}'
        mixed=inventory[:-1]+',InputTanks:['+tank('water',1000)+','+tank('lava',500)+'],OutputTanks:['+tank('water',250)+','+empty+']}'
        capture('empty','')
        capture('items',inventory)
        capture('mixed-en',mixed)
        capture('mixed-ru',mixed,'ru_ru')
        capture('no-goggles',mixed,goggles=False)
        result['passed']=True
    finally:(work/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'captured':len(cases),'result':str(work/'result.json')}))


if __name__=='__main__':main()
