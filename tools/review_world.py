#!/usr/bin/env python3
"""Prepare a NEW 0.5 processing gallery through the official launcher/control API.

Requires an installed native Create instance and its locally supplied asset JAR.
Never opens or replaces an existing world. Runtime gameplay remains Rust.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from common import ROOT
from catalog import BLOCKS, ITEMS

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--instance',required=True)
    parser.add_argument('--world',default='CreateProcessing05')
    parser.add_argument('--launcher',type=Path,default=Path('/Applications/Horizon.app/Contents/MacOS/horizon-launcher'))
    parser.add_argument('--ctl',type=Path,required=True)
    args=parser.parse_args()
    if not args.world or args.world in ['.', '..'] or any(c in args.world for c in '/\\'):
        parser.error('--world must be a single new world name, not a path.')
    instances=json.loads(subprocess.check_output([str(args.launcher),'--json','instance','list'],text=True))
    instance=next(i for i in instances if args.instance in [i['id'],i['name']])
    home=Path(instance['home'])
    world_path=home/'saves'/args.world
    if world_path.exists() or world_path.is_symlink():parser.error('World already exists; choose a new --world. It will not be replaced.')
    version=instance.get('version')
    if not version or not version.startswith('native-'):parser.error('Build and pin the native Create version for this instance first.')
    if not list((home/'horizon-mods/create-resources').glob('*.jar')):parser.error('Place the supported Create JAR in the instance first.')
    ROOT.joinpath('.local').mkdir(exist_ok=True)
    work=Path(tempfile.mkdtemp(prefix='review05-',dir=ROOT/'.local'))
    socket=work/'ctl.sock';transcript=[]
    env=os.environ.copy();env.update(HORIZON_NO_AUDIO='1',HORIZON_LAUNCHER_NO_SELF_UPDATE='1')
    def call(*words):
        p=subprocess.run([str(args.ctl),'--socket',str(socket),*map(str,words)],text=True,capture_output=True,timeout=180)
        if p.returncode:raise RuntimeError(str(words)+p.stdout+p.stderr)
        value=json.loads(p.stdout);transcript.append({'command':list(map(str,words)),'reply':value});return value
    def put(x,y,z,name):return call('setblock',x,y,z,name if ':' in name else 'create:'+name)
    def data(x,y,z,nbt):return call('command',f'data merge block {x} {y} {z} '+nbt)
    def stock(pos,slot,item,count=32):
        return call('command',f'item replace block {pos[0]} {pos[1]} {pos[2]} container.{slot} with {item} {count}')
    def sign(x,z,lines):
        put(x,64,z,'minecraft:oak_sign[rotation=0]')
        data(x,64,z,'{front_text:{messages:'+json.dumps(lines,ensure_ascii=False)+',color:"black"},is_waxed:1b}')
    def speed(x,y,z):
        import re
        text=' '.join(call('command',f'data get block {x} {y} {z}')['chat'])
        match=re.search(r'Speed:\s*(-?[\d.]+)',text);assert match,text;return float(match[1])
    def channel(x,y,z,r):
        # A contained, reversible vanilla bubble current. Replace magma with soul sand.
        for yy in range(y-1,y+4):
            for xx,zz in [(x-1,z+r),(x+1,z+r),(x,z+r+1),(x,z+r-1)]:
                if call('block',xx,yy,zz)['block']=='minecraft:air':put(xx,yy,zz,'minecraft:glass')
        put(x,y-2,z+r,'minecraft:magma_block')
        for yy in range(y-1,y+3):put(x,yy,z+r,'minecraft:water')
    with (work/'game.log').open('w') as log:
        command=[str(args.launcher),'play','--instance',instance['id'],'--version',version,'--world',args.world,'--creative','--arg=--seed','--arg=5','--arg=--render-distance','--arg=4','--arg=--control-socket','--arg='+str(socket),'--arg=--headless']
        process=subprocess.Popen(command,env=env,stdout=log,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+180
            while True:
                if process.poll() is not None:raise RuntimeError('Launcher stopped; inspect '+str(work/'game.log'))
                try:
                    if call('state').get('world')==args.world:break
                except RuntimeError:pass
                if time.monotonic()>deadline:raise TimeoutError('Review world startup')
                time.sleep(.25)
            call('wait-ready',120);call('command','tp @s 12 80 12');call('wait-ready',120)
            call('fill',-4,64,-4,31,81,22,'minecraft:air');call('fill',-4,63,-4,31,63,22,'minecraft:smooth_stone')
            for x,z in [(0,2),(0,8),(13,2),(24,2)]:
                put(x,64,z,'andesite_casing');put(x,65,z,'andesite_casing')
            for x,name in [(0,'creative_motor[facing=east]'),(1,'shaft[axis=x]'),(2,'mechanical_press[facing=east]')]:put(x,66,2,name)
            put(2,64,2,'depot');data(0,66,2,'{ScrollValue:256}');call('container',2,64,2,'create:brass_ingot',8);call('wait',150);data(0,66,2,'{ScrollValue:16}')
            assert sum(s['count'] for s in call('container',2,64,2)['slots'] if s and s['item']=='create:brass_sheet')==8
            for x,name in [(0,'creative_motor[facing=east]'),(1,'shaft[axis=x]'),(2,'speedometer[facing=south,axis_along_first=true]'),(3,'stressometer[facing=south,axis_along_first=true]'),(4,'gearbox[axis=y]'),(5,'shaft[axis=x]'),(6,'mechanical_press[facing=east]')]:put(x,66,8,name)
            put(6,64,8,'depot');put(2,65,9,'andesite_casing');put(2,66,9,'minecraft:comparator[facing=north]');put(2,65,10,'andesite_casing');put(2,66,10,'minecraft:redstone_wire')
            for z,kind in [(14,'clutch'),(18,'gearshift')]:
                for x,name in [(0,'creative_motor[facing=east]'),(1,'shaft[axis=x]'),(2,kind+'[axis=x]'),(3,'shaft[axis=x]'),(4,'cogwheel[axis=x]')]:put(x,64,z,name)
                put(2,65,z,'minecraft:lever[face=floor,facing=north]')
            # A live water-driven factory: 8 RPM -> large/small gears -> 16 RPM press.
            for x,y,z,name in [(13,67,2,'water_wheel[facing=east]'),(14,67,2,'shaft[axis=x]'),(15,67,2,'large_cogwheel[axis=x]'),(15,66,3,'cogwheel[axis=x]'),(16,66,3,'speedometer[facing=south,axis_along_first=true]'),(17,66,3,'mechanical_press[facing=east]'),(17,64,3,'depot')]:put(x,y,z,name)
            channel(13,67,2,1);call('wait',40)
            assert abs(speed(14,67,2))==8 and abs(speed(16,66,3))==16
            # Large wheel's structural 3x3 ring is built by the Rust block itself.
            put(24,67,2,'large_water_wheel[axis=x]');call('wait',8)
            for x,name in [(25,'shaft[axis=x]'),(26,'speedometer[facing=south,axis_along_first=true]'),(27,'stressometer[facing=south,axis_along_first=true]')]:put(x,67,2,name)
            channel(24,67,2,2);data(24,67,2,'{Material:{Name:"minecraft:cherry_planks"}}');call('wait',40)
            assert abs(speed(25,67,2))==4
            for x,name in [(18,'hand_crank[facing=west]'),(19,'shaft[axis=x]'),(20,'mechanical_press[facing=east]')]:put(x,66,12,name)
            put(20,64,12,'depot');call('container',20,64,12,'minecraft:copper_ingot',2)
            for x,z,name in [(9,12,'gearbox[axis=x]'),(9,13,'shaft[axis=z]'),(9,11,'shaft[axis=z]'),(18,17,'andesite_encased_shaft[axis=x]'),(20,17,'brass_encased_shaft[axis=z]'),(22,17,'andesite_casing'),(24,17,'brass_casing'),(26,17,'minecraft:stripped_oak_log'),(28,17,'minecraft:crafting_table')]:put(x,64,z,name)
            put(9,65,12,'shaft[axis=y]');put(9,66,12,'cogwheel[axis=y]')
            # Vanilla barrel deliberately supplies materials; Create depots never open this menu.
            put(27,64,10,'minecraft:barrel');put(29,64,10,'minecraft:barrel')
            for x,z,lines in [(2,5,['ПРЕСС / 8 ЛИСТОВ','Пустая рука: взять','Положите 8 слитков','Латунь тоже есть']), (3,12,['ПРИБОРЫ И ОЧКИ','Наведите на сеть','ПКМ мотор: RPM','Компаратор сзади']), (2,16,['СЦЕПЛЕНИЕ','Рычаг: разрыв','Вход вращается','Ключ: поворот']), (3,20,['РЕВЕРС','Рычаг меняет знак','Сравните валы','']), (9,15,['ВЕРТ. РЕДУКТОР','Тот же gearbox','Ключ: повернуть','Shift+ключ: снять']), (15,6,['ВОДЯНОЙ ПРИВОД','8 RPM / 256 SU','Передача 2:1','Далее пресс 16 RPM']), (25,7,['БОЛЬШОЕ КОЛЕСО','4 RPM / 512 SU','Доски меняют вид','Магма: течение вниз']), (20,14,['РУЧНОЙ ПРЕСС','ПКМ: вращение','Shift: реверс','В депо 2 меди']), (26,12,['МАТЕРИАЛЫ','Два обычных бочонка','Доски, вода, слитки','Верстак справа'])]:sign(x,z,lines)
            materials=['minecraft:oak_planks','minecraft:cherry_planks','minecraft:spruce_planks','minecraft:water_bucket','minecraft:soul_sand','minecraft:magma_block','minecraft:iron_ingot','minecraft:copper_ingot','minecraft:gold_ingot','create:brass_ingot','minecraft:andesite','minecraft:iron_nugget','minecraft:redstone','minecraft:glass','minecraft:string']
            for slot,item in enumerate(materials):
                barrel=27 if slot<9 else 29
                call('command',f'item replace block {barrel} 64 10 container.{slot%9} with {item} '+('1' if item.endswith('bucket') else '32'))
            # Extend only this newly-created world; keep every 0.4 stall above.
            call('command','tp @s 39 80 11');call('wait-ready',120)
            call('fill',32,64,-4,48,81,22,'minecraft:air')
            call('fill',32,63,-4,48,63,22,'minecraft:smooth_stone')
            # Fixed Y side-cog input leaves the bottom free for real hopper IO.
            put(35,64,0,'creative_motor[facing=up]');data(35,64,0,'{ScrollValue:128}')
            put(35,65,0,'cogwheel[axis=y]');put(36,65,0,'millstone')
            put(36,64,0,'minecraft:hopper[facing=east]');put(37,64,0,'minecraft:chest[facing=south]')
            put(36,66,0,'minecraft:hopper[facing=down]')
            sign(36,3,['ЖЁРНОВ / 128 RPM','Пшеница сверху','Выход в сундук','ПКМ: забрать'])
            # Separate, manually supplied depots: no fictional belt/auto recipes.
            fan_rows=[(7,'minecraft:oak_fence[waterlogged=true]','create:wheat_flour','ПРОМЫВКА','Мука → тесто'),
                      (11,'minecraft:campfire[lit=true]','create:dough','КОПЧЕНИЕ','Тесто → хлеб'),
                      (15,'minecraft:soul_campfire[lit=true]','minecraft:sand','ОГОНЬ ДУШ','Песок → песок душ'),
                      (19,'minecraft:lava','minecraft:raw_iron','ОБЖИГ','Сырая руда → слиток')]
            for z,catalyst,item,title,result in fan_rows:
                put(33,65,z,'creative_motor[facing=east]');data(33,65,z,'{ScrollValue:32}')
                put(34,65,z,'shaft[axis=x]');put(35,65,z,'encased_fan[facing=east]')
                put(38,64,z,'depot');put(40,65,z,'minecraft:glass')
                if catalyst=='minecraft:lava':
                    # Glass encloses source above/below/sides; iron bars retain
                    # lava at the front while the source fan tag passes airflow.
                    for x,y,zz in [(36,64,z),(36,66,z),(36,65,z-1),(36,65,z+1)]:
                        put(x,y,zz,'minecraft:glass')
                    put(37,65,z,'minecraft:iron_bars')
                else:
                    put(36,64,z,'minecraft:smooth_stone')
                put(36,65,z,catalyst)
                sign(38,z+2,[title,result,'Подача: верх депо','Реверс: RPM мотора'])
            # Stationary drill remains stopped until the reviewer flips its
            # powered clutch lever; replacing the front target is manual.
            put(44,65,13,'clutch[axis=x,powered=true]')
            put(44,66,13,'minecraft:lever[face=floor,facing=north,powered=true]')
            put(43,65,13,'creative_motor[facing=east]');data(43,65,13,'{ScrollValue:128}')
            put(45,65,13,'mechanical_drill[facing=east,waterlogged=false]')
            put(46,64,13,'minecraft:hopper[facing=east]');put(47,64,13,'minecraft:chest[facing=south]')
            stock((47,64,13),0,'minecraft:cobblestone');stock((47,64,13),1,'minecraft:stone')
            put(46,65,13,'minecraft:stone')
            sign(45,16,['МЕХАНИЧЕСКИЙ БУР','Рычаг: вкл./выкл.','Камень перед буром','Запас / выход: сундук'])
            # Supplies are ordinary vanilla storage; only hoppers move items.
            put(43,64,3,'minecraft:barrel');put(45,64,7,'minecraft:barrel')
            for slot,item in enumerate(['minecraft:wheat','create:wheat_flour','create:dough','minecraft:sand','minecraft:gravel','minecraft:raw_iron']):
                stock((43,64,3),slot,item)
            sign(43,5,['МАТЕРИАЛЫ 0.5','Пшеница, мука, тесто','Песок, гравий, руда','Для ручной подачи'])
            call('command','kill @e[type=minecraft:item]');call('command','clear @s')
            # Nine useful hotbar entries, then the three new processing items.
            # Give at most 36 distinct stacks; the rest go to a real barrel.
            order=['wrench','creative_motor','shaft','cogwheel','millstone','encased_fan','mechanical_drill','depot','hand_crank',
                   'propeller','wheat_flour','dough']
            order += [name for name in BLOCKS+ITEMS if name not in order]
            carried,overflow=order[:36],order[36:]
            assert len(order)==len(set(order))==len(BLOCKS+ITEMS)
            for name in carried:call('command','give @s create:'+name+(' 1' if name in ['wrench','goggles'] else ' 16'))
            for slot,name in enumerate(overflow):stock((45,64,7),slot,'create:'+name,1 if name in ['wrench','goggles'] else 16)
            sign(45,9,['ОСТАЛЬНОЙ КАТАЛОГ',f'В инвентаре: {len(carried)} ID',f'В бочке: {len(overflow)} ID','Без выпадения вещей'])
            call('command','item replace entity @s armor.head with create:goggles')
            call('wait',5)
            inventory=call('inventory')['counts']
            assert all(inventory.get('create:'+name,0)>=1 for name in carried),inventory
            # Supply live fixtures last, after world setup and item-drop cleanup.
            stock((36,66,0),0,'minecraft:wheat')
            for z,_,item,_,_ in fan_rows:
                # Terrain debris can land on a depot during construction and
                # survive entity cleanup. A fresh depot guarantees slot zero
                # receives the demo input instead of silently using its buffer.
                put(38,64,z,'minecraft:air');put(38,64,z,'depot')
                slots=call('container',38,64,z,item,8)['slots']
                assert slots[0]=={'item':item,'count':8} and all(s is None for s in slots[1:]),(z,slots)
            call('command','time set day');call('command','weather clear');call('options-set','lang','ru_ru');call('options-set','chatVisibility','2')
            call('command','tp @s 41.5 64 10.5');call('look-at',35.5,65.5,11.5);call('select','create:wrench');call('wait',10);state=call('state');call('save');call('quit');process.wait(timeout=30)
        finally:
            (work/'transcript.json').write_text(json.dumps(transcript,indent=2,ensure_ascii=False)+'\n')
            if process.poll() is None:
                try:call('quit');process.wait(timeout=30)
                except Exception:process.terminate();process.wait(timeout=10)
    (work/'result.json').write_text(json.dumps({'passed':True,'instance':instance['id'],'world':args.world,'version':version,'state':state,
        'catalog_entries':len(order),'carried_entries':len(carried),'overflow_barrel':[45,64,7],
        'overflow_entries':overflow,'millstone':[36,65,0],'fan_depots':[[38,64,row[0]] for row in fan_rows],
        'drill':[45,65,13],'drill_clutch_starts_powered':True},indent=2)+'\n')
    print(work/'result.json',flush=True)

if __name__=='__main__':main()
