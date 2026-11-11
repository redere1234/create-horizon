"""Player/recipe/redstone checks of the 0.3 foundation in a disposable world."""
import collections
import json
import re
from common import ROOT
from native_motors import replace_motor

OFFSET = 12


def run(call, graphics, log_path, scratch):
    def setblock(x, y, z, block):
        return call('setblock', OFFSET+x,y,z,block)
    def block(x,y,z):
        return call('block',OFFSET+x,y,z)
    def tp(x=.5,y=64,z=2.5):
        call('command',f'tp @s {OFFSET+x} {y} {z}')
    def data(x,y,z):
        return ' '.join(call('command',f'data get block {OFFSET+x} {y} {z}')['chat'])
    def number(x,y,z,key):
        text=data(x,y,z)
        m=re.search(r'\b'+key+r':\s*(-?[\d.]+)',text)
        assert m, text
        return float(m[1])
    def speed(x,expected,y=64,z=0):
        actual=number(x,y,z,'Speed')
        assert actual == expected, (x,y,z,expected,actual)
    def clear():
        call('command','kill @e[type=minecraft:item]')
        call('command','clear @s');call('wait',5)
    def give(item,count=1):
        call('command',f'give @s {item} {count}');call('wait',3)
        return call('select',item)
    def reset():
        call('fill',OFFSET,64,-1,OFFSET+8,70,4,'minecraft:air')
        tp(3.5,64,-3)
    def click(x=0,y=64,z=0,face='south'):
        call('interact',OFFSET+x,y,z,face);call('wait',10)
    def motor():
        setblock(0,64,0,'create:creative_motor[facing=east]')
        setblock(1,64,0,'create:shaft[axis=x]')
    call('command',f'tp @s {OFFSET+3.5} 68 -3.5');call('wait-ready',120)
    call('fill',OFFSET-2,64,-4,OFFSET+10,73,6,'minecraft:air')
    call('fill',OFFSET-2,63,-4,OFFSET+10,63,6,'minecraft:smooth_stone')
    for kind in ['clutch','gearshift']:
        reset();motor();setblock(2,64,0,'create:'+kind+'[axis=x]');setblock(3,64,0,'create:shaft[axis=x]')
        call('wait',10);speed(3,16)
        setblock(2,64,1,'minecraft:redstone_block');call('wait',10)
        assert 'powered=true' in block(2,64,0)['state']
        speed(1,16);speed(3,0 if kind=='clutch' else -16)
        setblock(2,64,1,'minecraft:air');call('wait',10);speed(3,16)
    reset();motor();setblock(2,64,0,'create:gearbox[axis=y]');setblock(3,64,0,'create:shaft[axis=x]');setblock(2,64,1,'create:shaft[axis=z]')
    call('wait',10);speed(3,-16);speed(2,16,z=1)
    reset();motor();setblock(2,64,0,'create:large_cogwheel[axis=x]');setblock(3,64,1,'create:large_cogwheel[axis=z]');setblock(3,64,2,'create:shaft[axis=z]')
    call('wait',10);speed(3,16,z=2)
    print('Foundation: clutch, gearshift, four-port gearbox and perpendicular large gears passed',flush=True)

    reset();clear();setblock(1,64,0,'create:shaft[axis=x]');setblock(2,64,0,'create:hand_crank[facing=east]');tp(3.5,64,.5)
    call('look-at','block',OFFSET+2,64,0,'east');call('wait',3)
    call('interact',OFFSET+2,64,0,'east');call('wait',2);speed(1,32)
    call('wait',15);speed(1,0)
    call('key','shift','down');call('wait',3)
    try:
        call('interact',OFFSET+2,64,0,'east');call('wait',2);speed(1,-32)
    finally:call('release')
    call('wait',15);speed(1,0)
    print('Foundation: hand crank generates 32 RPM, reverses and stops after release',flush=True)

    reset();clear();call('command','gamemode survival');tp();setblock(0,64,0,'minecraft:stripped_oak_log')
    give('create:andesite_alloy',2);click()
    assert block(0,64,0)['block']=='create:andesite_casing'
    assert call('inventory')['counts'].get('create:andesite_alloy')==1
    setblock(0,64,0,'create:shaft[axis=z]');give('create:andesite_casing');click()
    assert block(0,64,0)['block']=='create:andesite_encased_shaft'
    assert 'axis=z' in block(0,64,0)['state']
    assert call('inventory')['counts'].get('create:andesite_casing')==1
    assert 'create:encased_shaft' in data(0,64,0)
    give('create:wrench');click(face='up')
    assert 'axis=x' in block(0,64,0)['state']
    call('key','shift','down');call('wait',3)
    try:click()
    finally:call('release')
    assert block(0,64,0)['block']=='create:shaft' and 'axis=x' in block(0,64,0)['state']
    call('key','shift','down');call('wait',3)
    try:click()
    finally:call('release')
    assert block(0,64,0)['block']=='minecraft:air'
    assert call('inventory')['counts'].get('create:shaft')==1
    clear();setblock(0,64,0,'create:depot')
    call('container',OFFSET,64,0,'minecraft:iron_ingot',3)
    call('container',OFFSET,64,0,'create:iron_sheet',2)
    give('create:wrench');call('key','shift','down');call('wait',3)
    try:click()
    finally:call('release')
    inv=call('inventory')['counts']
    assert inv.get('create:depot')==1 and inv.get('minecraft:iron_ingot')==3 and inv.get('create:iron_sheet')==2,inv
    assert block(0,64,0)['block']=='minecraft:air'
    print('Foundation: survival casing, encasing without consumption, wrench rotation/removal and depot contents passed',flush=True)

    automation(call, OFFSET, reset, clear, tp)
    if graphics: crafting(call,OFFSET,clear)
    else: print("Headless: crafting and motor screen checks require the Horizon renderer and are skipped",flush=True)
    call('command','gamemode creative');clear();reset();motor();tp(.5,64,2.5)
    if graphics:
        import value_settings_checks
        result=value_settings_checks.run(call,graphics,log_path,scratch,[OFFSET,64,0])
        speed(1,result['speed'])
    # Keep the selected signed speed as a save/reload fixture.
    return {'motor_pos':[OFFSET,64,0],'speed':number(0,64,0,'ScrollValue')}


def crafting(call,offset,clear,recipes=None):
    def resolve(ingredient,seen=()):
        if isinstance(ingredient,list):return resolve(ingredient[0],seen)
        if isinstance(ingredient,dict):return resolve(ingredient.get('item') or '#'+ingredient['tag'],seen)
        if not ingredient.startswith('#'):return ingredient
        tag=ingredient[1:]
        assert tag not in seen,tag
        if tag=='minecraft:planks':return 'minecraft:oak_planks'
        namespace,name=tag.split(':',1)
        values=json.loads((ROOT/'content/data'/namespace/'tags/item'/(name+'.json')).read_text())['values']
        for value in values:
            value=value['id'] if isinstance(value,dict) else value
            if value.startswith('minecraft:') or value.startswith('#'):return resolve(value,(*seen,tag))
            if value.startswith('create:'):
                item=value[7:]
                if (ROOT/'content/data/create/horizon/item'/(item+'.json')).is_file() or (ROOT/'content/data/create/horizon/block'/(item+'.json')).is_file():return value
        raise AssertionError('No implemented ingredient for '+tag)
    call('setblock',offset+1,64,0,'minecraft:crafting_table')
    call('command',f'tp @s {offset+.5} 64 2.5')
    recipes=recipes or ['materials/andesite_alloy','kinetics/shaft','kinetics/cogwheel','kinetics/large_cogwheel','kinetics/hand_crank','kinetics/gearbox','kinetics/clutch','kinetics/gearshift','kinetics/mechanical_press','kinetics/depot','kinetics/wrench']
    for name in recipes:
        recipe=json.loads((ROOT/'content/data/create/recipe/crafting'/(name+'.json')).read_text())
        if 'pattern' in recipe:
            cells={100+row*3+col:resolve(recipe['key'][char]) for row,line in enumerate(recipe['pattern']) for col,char in enumerate(line) if char!=' '}
        else:cells={100+i:resolve(v) for i,v in enumerate(recipe['ingredients'])}
        clear()
        for item,count in collections.Counter(cells.values()).items():call('command',f'give @s {item} {count}')
        call('wait',5);inv=call('inventory')
        sources={slot['item']:slot['slot'] for slot in inv['hotbar']+inv['main'] if slot.get('item')}
        call('interact',offset+1,64,0,'south');call('wait',10)
        assert call('screen')['screen']=='inventory'
        for item in dict.fromkeys(cells.values()):
            call('click-slot',sources[item])
            for slot,entry in cells.items():
                if entry==item:call('click-slot',slot,'right')
        call('wait',5);screen=call('screen');result=next(slot for slot in screen['slots'] if slot['slot']==200)
        expected=recipe['result']
        assert result.get('item')==expected['id'] and result.get('count')==expected.get('count',1),(name,expected,result,screen)
        call('click-slot',200,'shift');call('wait',5);call('close');call('wait',5)
        counts=call('inventory')['counts'];assert counts.get(expected['id'])==expected.get('count',1),(name,counts)
        print('Crafted through vanilla server menu:',name,expected,flush=True)


def reloaded(call,fixture):
    text=' '.join(call('command','data get block '+' '.join(map(str,fixture['motor_pos'])))['chat'])
    match=re.search(r'\bScrollValue:\s*(-?\d+)',text)
    assert match and int(match[1])==fixture['speed'],text


def automation(call, offset, reset, clear, tp):
    def slots(x=0,y=64,z=0):
        return call('container',offset+x,y,z)['slots']
    def count(values,item):
        return sum(s['count'] for s in values if s and s['item']==item)
    reset();clear();tp(3.5,64,-3)
    call('setblock',offset,64,0,'create:depot')
    call('setblock',offset,65,0,'minecraft:hopper[facing=down]')
    call('container',offset,65,0,'minecraft:iron_ingot',5)
    call('wait',30)
    assert count(slots(),'minecraft:iron_ingot')==1,slots()
    assert count(slots(y=65),'minecraft:iron_ingot')==4,slots(y=65)
    call('setblock',offset+1,65,0,'minecraft:redstone_block')
    call('setblock',offset,63,0,'minecraft:hopper[facing=down]')
    call('wait',30)
    assert all(s is None for s in slots()),slots()
    assert count(slots(y=63),'minecraft:iron_ingot')==1,slots(y=63)
    assert count(slots(y=65),'minecraft:iron_ingot')==4,slots(y=65)
    call('container',offset,64,0,'minecraft:copper_ingot',3)
    call('container',offset,64,0,'create:copper_sheet',2)
    call('wait',80)
    assert all(s is None for s in slots()),slots()
    assert count(slots(y=63),'minecraft:copper_ingot')==3 and count(slots(y=63),'create:copper_sheet')==2,slots(y=63)
    print('Automation: hopper insertion refuses merging, extraction drains held input and output buffer without loss',flush=True)
    # A dropped stack must land on the 13/16 collision surface before capture.
    reset();clear();call('setblock',offset,63,0,'minecraft:smooth_stone');call('setblock',offset,64,0,'create:depot')
    call('command',f'summon minecraft:item {offset+.5} 65.3 .5 {{Item:{{id:"minecraft:candle",count:2,components:{{"minecraft:custom_data":{{create_port_drop:456}}}}}},PickupDelay:32767}}')
    call('wait',50)
    assert slots()[0]=={'item':'minecraft:candle','count':2},slots()
    tp(.5,65,2.5);call('interact',offset,64,0,'up');call('wait',10)
    candles=[s for s in call('inventory')['hotbar']+call('inventory')['main'] if s.get('item')=='minecraft:candle']
    assert len(candles)==1 and candles[0]['count']==2 and 'create_port_drop:456' in candles[0].get('components',''),candles
    assert all(s is None for s in slots()),slots()
    print('Automation: falling item captured and retrieved with its original custom data',flush=True)
    reset();clear();tp(3.5,64,-3)
    replace_motor(call, (offset, 66, 0), 128, 'east')
    for x,block in [(1,'create:shaft[axis=x]'),(2,'create:mechanical_press[facing=east]')]:call('setblock',offset+x,66,0,block)
    call('setblock',offset+2,64,0,'minecraft:smooth_stone')
    call('command',f'summon minecraft:item {offset+2.5} 65.3 .5 {{Item:{{id:"minecraft:iron_ingot",count:3}},PickupDelay:32767}}')
    call('wait',150)
    entities=call('entities',24,'minecraft:item')['entities']
    sheets=sum(e['item']['count'] for e in entities if e.get('item',{}).get('item',e.get('item',{}).get('id'))=='create:iron_sheet')
    assert sheets==3,entities
    assert not any(e.get('item',{}).get('item',e.get('item',{}).get('id'))=='minecraft:iron_ingot' for e in entities),entities
    text=' '.join(call('command',f'data get block {offset+2} 66 0')['chat'])
    assert re.search(r'\bMode:\s*0',text),text
    print('World press: three loose ingots processed individually on a solid surface without a depot',flush=True)
    clear()
