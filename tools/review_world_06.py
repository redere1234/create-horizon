#!/usr/bin/env python3
"""Author a fresh private factory review world; never open an existing instance.

Default mode prints the plan. --build needs an explicit tested native binary.
The official-instance installation and independent clone audit are separate.
Original models/textures remain in the locally supplied JAR/private cache.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

from catalog import BLOCKS, ITEMS
from common import ROOT, PINS
from native_check_session import NativeCheckSession, wait_loaded

WORLD = 'CreateFactory06'
CATALOG_BARRELS = [(2,64,0),(4,64,0)]
SCHEMATIC_ANCHOR = (64,64,32)
FANS = [
    (20,'minecraft:oak_fence[waterlogged=true]','create:wheat_flour','create:dough','ПРОМЫВКА'),
    (24,'minecraft:campfire[lit=true]','create:dough','minecraft:bread','КОПЧЕНИЕ'),
    (28,'minecraft:soul_campfire[lit=true]','minecraft:sand','minecraft:soul_sand','ОГОНЬ ДУШ'),
    (32,'minecraft:lava','minecraft:raw_iron','minecraft:iron_ingot','ОБЖИГ'),
    (36,'create:blaze_burner[blaze=smouldering,facing=north]','minecraft:beef','minecraft:cooked_beef','ТЛЕНИЕ / ДЫМ'),
]
STATIONS = [
    {'id':'catalog','title':'01. Каталог и снаряжение','visit':[3.5,64,4.5],'target':[3,65,0],
     'check':'Очки надеты; в двух обычных бочках все 47 ID; в рюкзаке 36 полезных стеков.'},
    {'id':'ui','title':'02. Очки и приборы','visit':[12.5,64,4.5],'target':[12.5,66.5,.5],
     'check':'Навести на приборы 32 RPM; открыть исходную шкалу мотора; сравнить компаратор.'},
    {'id':'press','title':'03. Пресс и восемь слитков','visit':[12.5,64,11.5],'target':[12.5,65,8.5],
     'check':'Мотор 0→128 RPM; восемь медных слитков обрабатываются по одному; пустой рукой забрать 8 листов.'},
    {'id':'belt','title':'04. Настоящая лента и пресс','visit':[29.5,64,5.5],'target':[25.5,66,2.5],
     'check':'Мотор ленты 0→32 RPM; пресс 128 RPM; восемь слитков едут через пресс, депо и в сундук.'},
    {'id':'dry','title':'05. Сухое смешивание','visit':[46.5,64,5.5],'target':[43.5,65,2.5],
     'check':'Мотор 0→32 RPM; четыре андезита + четыре железных самородка дают 4 сплава; обычные воронки в запасе.'},
    {'id':'fluids','title':'06. Вода, тесто и грязь','visit':[57.5,64,11.5],'target':[55.5,64.7,9.5],
     'check':'Влить 1000 mB воды: одна мука→одно тесто; другая чаша расходует 250 mB на каждую грязь. Вода/лава в демонстрационной чаше.'},
    {'id':'brass','title':'07. Настоящий нагрев и латунь','visit':[72.5,64,5.5],'target':[69.5,65.5,2.5],
     'check':'Уголь в заполненную горелку; мотор 0→32 RPM; медь + цинк→2 латуни. Пустая клетка отдельна.'},
    {'id':'fans','title':'08. Пять сред вентилятора','visit':[9.5,64,28.5],'target':[5,65,28.5],
     'check':'Моторы 0→32 RPM: закрытая вода, костёр, костёр душ, закрытая лава, тлеющая горелка. Промывка через открытые ворота — не закрывать. Во всех депо 8 исходных предметов.'},
    {'id':'air','title':'09. Безопасный воздушный коридор','visit':[18.5,64,27.5],'target':[17.5,65,24.5],
     'check':'Без огня; не лететь. Мотор 0→128 RPM толкает, отрицательные RPM тянут. Стекло ограничивает коридор.'},
    {'id':'power','title':'10. Вода, приводы и бур','visit':[32.5,64,34.5],'target':[30,67,28.5],
     'check':'Малое колесо 8 RPM, передача 16 RPM; большое 4 RPM. Бур включается отдельным рычагом, запас камня в сундуке.'},
    {'id':'craft','title':'11. Обычный survival-крафт','visit':[16.5,64,39.5],'target':[17,64.5,36],
     'check':'Обычные верстаки и бочки с материалами; переключить survival для ручной проверки рецептов.'},
    {'id':'schematic','title':'12. Проверка и вставка схематики','visit':[68.5,64,37.5],'target':[66,65,32],
     'check':'/create schematic inspect own-press.nbt, затем /create schematic paste own-press.nbt 64 64 32. Пять блоков образуют работающий пресс; неподдержанные схемы отклоняются целиком.'},
    {'id':'compacting','title':'13. Пресс над чашей','visit':[68.5,64,27.5],'target':[66,65,20],
     'check':'Три мотора 0→32 RPM: 8 снежков→2 снежных блока; 9 снежных блоков→1 лёд; 2 кремня+гравий+100 mB лавы→1 андезит. Горелка не нужна. Пустая рука забирает выход.'},
]


def fan_enclosure(z, medium):
    """Physical walls only; preserve the original medium and eastward air path."""
    if medium=='minecraft:lava':
        return [*((p,'minecraft:glass') for p in [(4,64,z),(4,66,z),(4,65,z-1),(4,65,z+1)]),
                ((5,65,z),'minecraft:iron_bars')]
    if medium=='minecraft:oak_fence[waterlogged=true]':
        # A dry open gate rejects liquid replacement while its empty collision
        # shape passes Create AirCurrent.getFlowLimit. Glass closes the sides.
        return [((4,64,z),'minecraft:smooth_stone'),
                *((p,'minecraft:glass') for p in [(4,66,z),(4,65,z-1),(4,65,z+1)]),
                ((5,65,z),'minecraft:oak_fence_gate[facing=east,open=true,powered=false,in_wall=false]')]
    return [((4,64,z),'minecraft:smooth_stone')]


def plan(include_lit=False):
    return {'world':WORLD,'source':PINS['create_revision'],'catalog_blocks':len(BLOCKS),
        'catalog_items':len(ITEMS),'catalog_ids':['create:'+i for i in BLOCKS+ITEMS],
        'catalog_barrels':CATALOG_BARRELS,'stations':STATIONS,'include_lit_burner':include_lit,
        'schematic_demo':{'filename':'own-press.nbt','anchor':SCHEMATIC_ANCHOR,
                          'fixture_source':'tools/schematic_checks.py; independently authored geometry'},
        'defaults':'Processing drives stopped; UI32RPM, belt press128RPM, wheel generation live.',
        'scope':'No mid-belt hopper fiction, fluid pipes, heated fluid recipes or falling Basin intake claim.'}


def write_walkthrough(scratch,include_lit=False):
    scratch=Path(scratch)
    (scratch/'review06-plan.json').write_text(json.dumps(plan(include_lit),ensure_ascii=False,indent=2)+'\n')
    lines=['# CreateFactory06: маршрут проверки','',
        'Новая частная карта. Построение и независимый аудит копии записываются отдельно.',
        'Очки надеты. Каталог целиком в двух бочках; обработка запускается явно моторами.',
        '','| Станция | Подойти к X Y Z | Проверка |','| --- | --- | --- |']
    for station in STATIONS:
        lines.append('| '+station['title']+' | '+' '.join(map(str,station['visit']))+' | '+station['check']+' |')
    lines.extend(['','Жёрнов с настоящими входной и выходной воронками: X43 Y65 Z14.',
        'Схематика: в creative выполните `/create schematic inspect own-press.nbt`, затем',
        '`/create schematic paste own-press.nbt 64 64 32`. Положите один медный слиток на депо X66 Y64 Z32.',
        'Файлы рядом с миром, в папке `schematics/`. `unsupported-belt.nbt` демонстрирует отказ до записи блоков.',
        'Станция 13: чаши X60/66/72 Y64 Z20, моторы X58/64/70 Y66 Z20. Поставьте 32 RPM.',
        'Лава внутри третьей чаши: 1000 mB до обработки и 900 mB после одного андезита.',
        'Это ограниченный командный импорт; исходные предметы, preview и экран схематики ещё не перенесены.',
        'Внутренняя лавовая чаша не выпускает жидкость в мир; наружная лава вентилятора закрыта стеклом.',
        'Автовставка в середину ленты, трубы, нагреваемые жидкостные рецепты и падающий ввод Basin здесь не обещаны.',
        'Жидкостные частицы и прочие оставшиеся визуальные отличия сверяются с актуальным отчётом разработки.',
        'Старые миры 0.5 не открываются и не заменяются.'])
    (scratch/'REVIEW_06_RU.md').write_text('\n'.join(lines)+'\n')


def build(call,scratch,*,include_lit=False):
    scratch=Path(scratch).resolve();scratch.relative_to((ROOT/'.local').resolve())
    marker=json.loads((scratch/'.review06-fresh.json').read_text())
    assert marker=={'world':WORLD,'fresh_private_home':str(scratch),'username':'Delete228'},marker
    assert call('state')['world']==WORLD
    result={'passed':False,'plan':plan(include_lit),'checks':[],'images':[],
        'independent_clone_audit':'pending; this is authoring verification only'}
    write_walkthrough(scratch,include_lit)
    def save():(scratch/'review06-build-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    def cmd(text):
        reply=call('command',text)
        assert not any('not loaded' in s or 'Unknown block' in s for s in reply.get('chat',[])),(text,reply)
        return reply
    def put(pos,state):return cmd('setblock '+' '.join(map(str,pos))+' '+(state if ':' in state else 'create:'+state))
    def data(pos,nbt):return cmd('data merge block '+' '.join(map(str,pos))+' '+nbt)
    def power(pos,rpm):return data(pos,'{ScrollValue:'+str(rpm)+'}')
    def stock(pos,slot,item,count=32):return cmd('item replace block '+' '.join(map(str,pos))+f' container.{slot} with {item} {count}')
    def sign(x,z,lines):
        assert len(lines)<=4
        put((x,64,z),'minecraft:oak_sign[rotation=0]')
        data((x,64,z),'{front_text:{messages:'+json.dumps(lines,ensure_ascii=False)+',color:"black"},is_waxed:1b}')
    def check(name,**values):result['checks'].append(dict(name=name,**values));save()
    def read(pos,path=''):return ' '.join(cmd('data get block '+' '.join(map(str,pos))+' '+path)['chat'])
    def rpm(pos):
        raw=read(pos);m=re.search(r'\bSpeed:\s*(-?[\d.]+)',raw);assert m,raw;return float(m[1])
    def basin_stock(pos,inputs):
        entries=','.join('{Slot:'+str(i)+',id:"'+item+'",count:'+str(n)+'}' for i,(item,n) in enumerate(inputs))
        data(pos,'{InputItems:{Size:9,Items:['+entries+']},OutputItems:{Size:9,Items:[]}}')
    def mixer(x,z,y=64):
        for pos,block in [((x,y,z),'basin[facing=down]'),((x,y+2,z),'mechanical_mixer'),
            ((x-1,y+1,z),'creative_motor[facing=up]'),((x-1,y+2,z),'cogwheel[axis=y]')]:put(pos,block)
        power((x-1,y+1,z),0)
    def bucket(pos,item):
        x,y,z=pos;cmd('clear @s');cmd('item replace entity @s weapon.mainhand with minecraft:'+item+' 1')
        cmd(f'tp @s {x+2.5} 64 {z+2.5}');call('wait',4)
        state=call('state')['player'];assert state['on_ground'] and abs(state['position'][1]-64)<.001,state
        call('look-at','block',x,y,z,'south');call('wait',3);call('interact',x,y,z,'south');call('wait',6)
    save()
    try:
        cmd('tick unfreeze');cmd('gamemode creative');cmd('gamerule minecraft:spawn_mobs false')
        # A fresh private world only. Tile the mutations below the normal fill
        # limit; load authoritative columns before touching each tile.
        for x in range(-4,80,16):
            for z in range(-4,44,16):
                xx=min(x+15,79);zz=min(z+15,43)
                cmd(f'tp @s {x+7.5} 84 {z+7.5}');call('wait-ready',120);call('wait',6)
                wait_loaded(call,[(x,64,z),(xx,64,zz)])
                cmd(f'fill {x} 64 {z} {xx} 94 {zz} minecraft:air')
                cmd(f'fill {x} 63 {z} {xx} 63 {zz} minecraft:smooth_stone')
        cmd('forceload add -16 -16 80 48')
        for x in range(-4,80):
            for z in [-4,43]:put((x,64,z),'minecraft:glass')
        for z in range(-3,43):
            for x in [-4,79]:put((x,64,z),'minecraft:glass')
        check('Fresh tiled floor and boundary authored; existing worlds untouched')

        for pos in CATALOG_BARRELS:put(pos,'minecraft:barrel')
        for pos,ids in zip(CATALOG_BARRELS,[BLOCKS,ITEMS]):
            for slot,item in enumerate(ids):stock(pos,slot,'create:'+item,1)
        sign(2,2,['01 КАТАЛОГ','27 блоков / 20 вещей','Обычные бочки','Очки уже надеты'])
        sign(5,2,['CREATE / 0.6 DEV','Маршрут: слева','направо, затем назад','Все приводы доступны'])

        for x,block in [(10,'creative_motor[facing=east]'),(11,'shaft[axis=x]'),
            (12,'speedometer[facing=south,axis_along_first=true]'),(13,'stressometer[facing=south,axis_along_first=true]'),
            (14,'mechanical_press[facing=east]')]:put((x,66,0),block)
        for y in [64,65]:put((10,y,0),'andesite_casing')
        put((14,64,0),'depot');power((10,66,0),32)
        put((12,65,1),'andesite_casing');put((12,66,1),'minecraft:comparator[facing=north]')
        put((12,65,2),'andesite_casing');put((12,66,2),'minecraft:redstone_wire')
        sign(12,4,['02 ОЧКИ / ПРИБОРЫ','Сеть: 32 RPM','Удержите ПКМ мотора','Шкала и компаратор'])
        for x,block in [(10,'creative_motor[facing=east]'),(11,'shaft[axis=x]'),(12,'mechanical_press[facing=east]')]:put((x,66,8),block)
        power((10,66,8),0);put((12,64,8),'depot')
        sign(12,11,['03 ПРЕСС / 8 МЕДИ','Мотор: 0 → 128 RPM','Листы по одному','Пустой рукой: взять'])

        for pos,block in [((24,65,0),'creative_motor[facing=east]'),((25,65,0),'shaft[axis=x]'),
            ((25,65,5),'shaft[axis=x]'),((25,65,6),'depot'),((25,64,6),'minecraft:hopper[facing=east]'),
            ((26,64,6),'minecraft:chest[facing=south]'),((24,67,2),'creative_motor[facing=east]'),
            ((25,67,2),'mechanical_press[facing=east]')]:put(pos,block)
        power((24,65,0),0);power((24,67,2),128)
        cmd('clear @s');cmd('give @s create:belt_connector 1');call('wait',5);call('select','create:belt_connector')
        for offset in [0,5]:
            cmd(f'tp @s 27.5 64 {offset-1.5}');call('wait',4)
            assert call('state')['player']['on_ground']
            call('look-at','block',25,65,offset,'east');call('wait',3);call('interact',25,65,offset,'east');call('wait',8)
        assert all(call('block',25,65,z)['block']=='create:belt' for z in range(6))
        sign(28,8,['04 ЛЕНТА + ПРЕСС','Лента: 0 → 32 RPM','Пресс: 128 RPM','Выход: сундук ниже'])
        put((28,64,0),'minecraft:barrel');stock((28,64,0),0,'minecraft:copper_ingot',32)
        check('Six-part belt created with real connector clicks; normal depot/hopper/chest exit')

        mixer(43,2);sign(43,5,['05 СУХАЯ ЧАША','Мотор: 0 → 32 RPM','Андезит + самородок','4 сплава, без нагрева'])
        for pos,block in [((42,64,14),'creative_motor[facing=up]'),((42,65,14),'cogwheel[axis=y]'),
            ((43,65,14),'millstone'),((43,66,14),'minecraft:hopper[facing=down]'),
            ((43,64,14),'minecraft:hopper[facing=east]'),((44,64,14),'minecraft:chest[facing=south]')]:put(pos,block)
        power((42,64,14),0)
        sign(43,17,['ЖЁРНОВ / ВОРОНКИ','Мотор: 0 → 128 RPM','Пшеница сверху','Выход: мука и семена'])
        mixer(55,2);mixer(59,6)
        sign(55,5,['06 ТЕСТО / ВОДА','Влейте 1000 mB','Мотор: 0 → 32 RPM','1 мука → 1 тесто'])
        sign(60,9,['ГРЯЗЬ / BLOCK TAG','Влейте 1000 mB','Мотор: 0 → 32 RPM','4 блока → 4 грязи'])
        put((55,64,9),'basin[facing=down]')
        put((58,64,11),'minecraft:barrel')
        for slot,item,n in [(0,'minecraft:water_bucket',1),(1,'minecraft:water_bucket',1),
            (2,'minecraft:lava_bucket',1),(3,'minecraft:bucket',4),(4,'create:wheat_flour',32),
            (5,'minecraft:dirt',32),(6,'minecraft:coarse_dirt',16),(7,'minecraft:rooted_dirt',16)]:stock((58,64,11),slot,item,n)
        sign(55,12,['ВОДА / ЛАВА','Внутри чаши безопасно','ПКМ ведром: 1000 mB','Повтор воды: отказ'])

        put((69,64,2),'blaze_burner[blaze=smouldering,facing=north]');mixer(69,2,65)
        put((73,64,2),'blaze_burner[blaze=none,facing=north]')
        put((73,64,5),'blaze_burner[blaze=smouldering,facing=north]')
        if include_lit:put((76,64,5),'lit_blaze_burner[flame_type=regular]')
        put((72,64,8),'minecraft:barrel')
        for slot,item,n in [(0,'minecraft:coal',32),(1,'minecraft:copper_ingot',32),(2,'create:zinc_ingot',32),
            (3,'create:empty_blaze_burner',4),(4,'create:blaze_burner',4),(5,'create:blaze_cake',4),
            (6,'minecraft:flint_and_steel',1),(7,'minecraft:iron_shovel',1),(8,'minecraft:soul_sand',8)]:stock((72,64,8),slot,item,n)
        sign(69,6,['07 ЛАТУНЬ / НАГРЕВ','Уголь в горелку','Мотор: 0 → 32 RPM','Медь + цинк → 2'])
        sign(74,9,['ПУСТАЯ ≠ С БЛЕЙЗОМ','Слева: пустая клетка','Тление не плавит латунь','Для нагрева нужен уголь'])
        if include_lit:sign(77,8,['ОГОНЬ БЕЗ БЛЕЙЗА','Огниво: зажечь','Лопата: погасить','Песок душ: синий'])

        for z,medium,item,output,title in FANS:
            for x,block in [(1,'creative_motor[facing=east]'),(2,'shaft[axis=x]'),(3,'encased_fan[facing=east]')]:put((x,65,z),block)
            power((1,65,z),0);put((6,64,z),'depot');put((8,65,z),'minecraft:glass')
            for pos,block in fan_enclosure(z,medium):put(pos,block)
            put((4,65,z),medium)
            sign(6,z+2,[title,'Мотор: 0 → 32 RPM','8 предметов в депо',
                'Ворота: открыты' if medium=='minecraft:oak_fence[waterlogged=true]' else 'Пустая рука: забрать'])
        for x,block in [(12,'creative_motor[facing=east]'),(13,'shaft[axis=x]'),(14,'encased_fan[facing=east]')]:put((x,65,24),block)
        power((12,65,24),0)
        for x in range(15,24):
            for z in [23,25]:
                for y in range(64,67):put((x,y,z),'minecraft:glass')
        for y in range(64,67):put((23,y,24),'minecraft:glass')
        sign(17,27,['09 ВЕТЕР БЕЗ ОГНЯ','Не летайте в коридоре','Мотор: 0 → 128 RPM','Минус RPM: назад'])

        def channel(x,z,r):
            for y in range(66,71):
                for xx,zz in [(x-1,z+r),(x+1,z+r),(x,z+r-1),(x,z+r+1)]:
                    if call('block',xx,y,zz)['block']=='minecraft:air':put((xx,y,zz),'minecraft:glass')
            put((x,65,z+r),'minecraft:magma_block')
            for y in range(66,70):put((x,y,z+r),'minecraft:water')
        for pos,block in [((25,67,28),'water_wheel[facing=east]'),((26,67,28),'shaft[axis=x]'),
            ((27,67,28),'large_cogwheel[axis=x]'),((27,66,29),'cogwheel[axis=x]'),
            ((28,66,29),'speedometer[facing=south,axis_along_first=true]'),((34,67,28),'large_water_wheel[axis=x]'),
            ((35,67,28),'shaft[axis=x]'),((36,67,28),'speedometer[facing=south,axis_along_first=true]')]:put(pos,block)
        channel(25,28,1);channel(34,28,2)
        sign(28,33,['10 ВОДЯНЫЕ ПРИВОДЫ','Малое: 8 → 16 RPM','Большое: 4 RPM','Поток ванильный'])
        for pos,block in [((43,65,25),'creative_motor[facing=east]'),((44,65,25),'clutch[axis=x,powered=true]'),
            ((44,66,25),'minecraft:lever[face=floor,facing=north,powered=true]'),((45,65,25),'mechanical_drill[facing=east,waterlogged=false]'),
            ((46,65,25),'minecraft:stone'),((46,64,25),'minecraft:hopper[facing=east]'),((47,64,25),'minecraft:chest[facing=south]')]:put(pos,block)
        power((43,65,25),128);stock((47,64,25),0,'minecraft:stone',32)
        sign(45,28,['БУР / РЫЧАГ','Сцепление отключено','Камень ставить вручную','Добыча: сундук'])
        for x,block in [(42,'hand_crank[facing=west]'),(43,'shaft[axis=x]'),(44,'gearbox[axis=y]'),
            (45,'gearshift[axis=x]'),(46,'cogwheel[axis=x]')]:put((x,65,34),block)
        put((45,66,34),'minecraft:lever[face=floor,facing=north]')
        sign(44,37,['РУЧНОЙ ПРИВОД','ПКМ: вращение','Shift: назад','Рычаг: реверс'])

        for pos in [(14,64,36),(20,64,36)]:put(pos,'minecraft:crafting_table')
        for pos in [(16,64,36),(18,64,36),(22,64,36)]:put(pos,'minecraft:barrel')
        materials=['minecraft:oak_planks','minecraft:stick','minecraft:iron_ingot','minecraft:iron_nugget',
            'minecraft:copper_ingot','minecraft:gold_ingot','minecraft:redstone','minecraft:andesite','minecraft:string',
            'minecraft:glass','minecraft:white_wool','minecraft:netherrack','minecraft:iron_bars','create:andesite_alloy',
            'create:iron_sheet','create:brass_ingot','create:zinc_ingot','create:wheat_flour','minecraft:coal',
            'create:andesite_casing','create:cogwheel','minecraft:dried_kelp']
        for i,item in enumerate(materials):
            barrel=16 if i<9 else 18 if i<18 else 22
            stock((barrel,64,36),i%9 if i<18 else 4+i-18,item,32)
        stock((22,64,36),0,'minecraft:water_bucket',1);stock((22,64,36),1,'minecraft:bucket',4)
        stock((22,64,36),2,'minecraft:hopper',8);stock((22,64,36),3,'minecraft:chest',4)
        sign(17,39,['11 ОБЫЧНЫЙ КРАФТ','Материалы в бочках','Верстак ванильный','/gamemode survival'])

        # Keep the demonstration destination empty for the owner's first paste.
        # Fixtures are our own small structures, never copied Create assets.
        from schematic_checks import write_fixtures
        fixtures=write_fixtures(scratch/'schematics')
        (scratch/'schematic-fixtures.json').write_text(json.dumps(fixtures,indent=2)+'\n')
        sign(66,38,['12 СХЕМАТИКИ','Команды: REVIEW_06_RU','own-press.nbt','Вставка: 64 64 32'])
        check('Authored schematic fixtures prepared; destination left empty',
              fixture_hashes=fixtures,anchor=SCHEMATIC_ANCHOR)

        for x in [60,66,72]:
            for pos,block in [((x,64,20),'basin[facing=down]'),
                ((x,66,20),'mechanical_press[facing=east]'),
                ((x-1,66,20),'shaft[axis=x]'),
                ((x-2,66,20),'creative_motor[facing=east]')]:put(pos,block)
            power((x-2,66,20),0)
        put((72,64,24),'minecraft:barrel')
        for slot,item,n in [(0,'minecraft:snowball',16),(1,'minecraft:snow_block',64),
            (2,'minecraft:flint',64),(3,'minecraft:gravel',64),
            (4,'minecraft:lava_bucket',1),(5,'minecraft:bucket',4)]:stock((72,64,24),slot,item,n)
        sign(60,24,['13 ПРЕСС + ЧАША','8 снежков → 2 блока','Мотор: 0 → 32 RPM','Пустая рука: взять'])
        sign(66,24,['УПЛОТНЕНИЕ','9 снежных блоков','→ 1 лёд','Мотор: 0 → 32 RPM'])
        sign(72,27,['АНДЕЗИТ / ЛАВА','2 кремня + гравий','100 mB → 1 андезит','Нагрев не нужен'])

        # Final stock after terrain debris is gone. Recreate depots so debris
        # cannot silently occupy HeldItem or an output buffer during authoring.
        cmd('kill @e[type=minecraft:item]')
        for pos,item,n in [((12,64,8),'minecraft:copper_ingot',8),
            *[((6,64,z),item,8) for z,_,item,_,_ in FANS]]:
            put(pos,'minecraft:air');put(pos,'depot')
            slots=call('container',*pos,item,n)['slots']
            assert slots[0]=={'item':item,'count':n} and all(s is None for s in slots[1:]),(pos,slots)
        basin_stock((43,64,2),[('minecraft:andesite',4),('minecraft:iron_nugget',4)])
        basin_stock((55,64,2),[('create:wheat_flour',4)])
        basin_stock((59,64,6),[('minecraft:dirt',2),('minecraft:coarse_dirt',1),('minecraft:rooted_dirt',1)])
        basin_stock((69,65,2),[('minecraft:copper_ingot',4),('create:zinc_ingot',4)])
        basin_stock((60,64,20),[('minecraft:snowball',8)])
        basin_stock((66,64,20),[('minecraft:snow_block',9)])
        basin_stock((72,64,20),[('minecraft:flint',2),('minecraft:gravel',1)])
        bucket((72,64,20),'lava_bucket')
        compacting_lava=read((72,64,20),'InputTanks')
        assert 'minecraft:lava' in compacting_lava and 'amount: 1000' in compacting_lava,compacting_lava
        assert all(rpm((x,66,20))==0 for x in [58,64,70])
        check('Three stopped Press/Basin stations: snowball compression, explicit ice recipe and real lava-bucket andesite',
              inputs={'60 64 20':{'minecraft:snowball':8},'66 64 20':{'minecraft:snow_block':9},
                      '72 64 20':{'minecraft:flint':2,'minecraft:gravel':1}},lava_millibuckets=1000)
        stock((43,66,14),0,'minecraft:wheat',32)
        bucket((55,64,9),'water_bucket');bucket((55,64,9),'lava_bucket')
        fluids=read((55,64,9),'InputTanks')
        assert 'minecraft:water' in fluids and 'minecraft:lava' in fluids and fluids.count('amount: 1000')==2,fluids
        cmd('summon minecraft:item 25.5 66.05 .5 {PickupDelay:32767,Item:{id:"minecraft:copper_ingot",count:8,components:{"minecraft:custom_data":{review06_belt:71}}}}')
        call('wait',35)
        assert 'review06_belt: 71' in read((25,65,0),'Inventory')

        order=['wrench','creative_motor','shaft','cogwheel','belt_connector','mechanical_press','basin','mechanical_mixer','blaze_burner']
        order += [name for name in BLOCKS+ITEMS if name not in order]
        cmd('clear @s')
        for item in order[:36]:cmd('give @s create:'+item+(' 1' if item in ['wrench','goggles'] else ' 16'))
        cmd('item replace entity @s armor.head with create:goggles')
        call('wait',5);inventory=call('inventory')['counts']
        assert all(inventory.get('create:'+item,0)>0 for item in order[:36]),inventory
        catalog={s['item'] for pos in CATALOG_BARRELS for s in call('container',*pos)['slots'] if s}
        assert catalog=={'create:'+i for i in BLOCKS+ITEMS},catalog
        call('wait',40)
        assert abs(rpm((26,67,28)))==8 and abs(rpm((28,66,29)))==16
        assert abs(rpm((35,67,28)))==4
        assert abs(rpm((12,66,0)))==32 and rpm((45,65,25))==0
        check('Catalog47/no overflow, genuine waiting inputs, fluid stripes, mechanical defaults and8/16/4RPM verified',catalog_ids=sorted(catalog),carried=order[:36])
        cmd('time set day');cmd('weather clear');call('options-set','lang','ru_ru');call('options-set','chatVisibility','2');call('options-set','tutorialStep','none')
        cmd('tp @s 8.5 64 7.5');call('look-at',12.5,66,1);call('select','create:wrench');call('wait',8)
        call('save-all');result['passed']=True;save();return result
    except BaseException as error:
        result['error']=repr(error);save();raise


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build',action='store_true')
    parser.add_argument('--lit-burner-accepted',action='store_true',help='Only after actual lifecycle native acceptance')
    for name in ['game','resources','ctl','create-jar']:parser.add_argument('--'+name,type=Path)
    args=parser.parse_args()
    if not args.build:
        print(json.dumps(plan(args.lit_burner_accepted),ensure_ascii=False,indent=2));return
    if not all([args.game,args.resources,args.ctl,args.create_jar]):parser.error('--build requires explicit game/resources/ctl/create-jar')
    session=NativeCheckSession(args.game,args.resources,args.ctl,args.create_jar,name='review06-source',
        graphics=False,world=WORLD,username='Delete228')
    world=session.scratch/'saves'/WORLD
    assert not world.exists() and not world.is_symlink()
    (session.scratch/'.review06-fresh.json').write_text(json.dumps({'world':WORLD,'fresh_private_home':str(session.scratch),'username':'Delete228'})+'\n')
    session.env.update(HORIZON_API_DISCOVERY='http://127.0.0.1:9/',HORIZON_NO_DISCORD='1')
    metadata={'world':WORLD,'home':str(session.scratch),'game':str(session.game),
        'game_sha256':hashlib.sha256(session.game.read_bytes()).hexdigest(),'passed':False}
    print(json.dumps(metadata),flush=True)
    try:
        with session:metadata['result']=build(session.call,session.scratch,include_lit=args.lit_burner_accepted)
        metadata['passed']=True
    finally:
        (session.scratch/'result.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
    print(session.scratch/'result.json',flush=True)


if __name__=='__main__':main()
