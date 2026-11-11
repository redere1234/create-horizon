#!/usr/bin/env python3
"""Exercise the authored CreateFactory06 stations only on a marked private clone.

The builder's author also wrote this tool. Its evidence is a clone verification,
not an independent review; another agent should inspect and execute it. The
source save stays closed and its level.dat fingerprint must remain unchanged.
"""
import collections
import hashlib
import json
from pathlib import Path
import re
import shutil

from common import ROOT
from reference_java import CREATE_SHA256
from native_check_session import wait_loaded
from review_washing_checks import inspect as inspect_washing
from review_compacting_checks import BASINS as COMPACTING_BASINS, inspect as inspect_compacting, run as run_compacting

WORLD = 'CreateFactory06'
CATALOG = set('''creative_motor shaft cogwheel large_cogwheel mechanical_press depot
gearbox clutch gearshift hand_crank andesite_encased_shaft brass_encased_shaft
andesite_casing brass_casing andesite_alloy_block brass_block zinc_block speedometer
stressometer water_wheel large_water_wheel millstone encased_fan mechanical_drill
basin mechanical_mixer blaze_burner iron_sheet golden_sheet copper_sheet andesite_alloy
brass_ingot brass_nugget zinc_ingot zinc_nugget wrench brass_sheet vertical_gearbox
goggles propeller wheat_flour dough belt_connector whisk empty_blaze_burner blaze_cake
creative_blaze_cake'''.split())
FANS = [(20,'create:wheat_flour','create:dough'), (24,'create:dough','minecraft:bread'),
        (28,'minecraft:sand','minecraft:soul_sand'), (32,'minecraft:raw_iron','minecraft:iron_ingot'),
        (36,'minecraft:beef','minecraft:cooked_beef')]
OUTPUTS = [(26,64,6),(44,64,14),(47,64,25),(43,64,2),(55,64,2),(59,64,6),(69,65,2),*COMPACTING_BASINS]
MILL_PIPELINE = [(43,66,14),(43,65,14),(43,64,14)]
CRAFT_BARRELS = [(16,64,36),(18,64,36),(22,64,36)]
CRAFT_RECIPES = ['kinetics/whisk','kinetics/basin','kinetics/mechanical_mixer',
                 'kinetics/belt_connector','kinetics/empty_blaze_burner','appliances/dough']


def _digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _save_manifest(source):
    source=Path(source)
    return {str(p.relative_to(source)):_digest(p) for p in sorted(source.rglob('*')) if p.is_file()}


def _source_unchanged(marker):
    source=Path(marker['source'])
    assert _digest(source/'level.dat')==marker['source_level_sha256'],marker
    assert _save_manifest(source)==marker['source_files_sha256'],'Authored source save files changed'
    if 'source_schematic_files_sha256' in marker:
        assert _save_manifest(source.parents[1]/'schematics')==marker['source_schematic_files_sha256'], \
            'Authored schematic input files changed'



def prepare_clone(session, authored_home):
    """Copy only a completed, closed private authored save into a fresh session."""
    authored_home=Path(authored_home).resolve();authored_home.relative_to((ROOT/'.local').resolve())
    scratch=Path(session.scratch).resolve();scratch.relative_to((ROOT/'.local').resolve())
    assert session.world==WORLD and session.username=='Delete228'
    fresh=json.loads((authored_home/'.review06-fresh.json').read_text())
    assert fresh=={'world':WORLD,'fresh_private_home':str(authored_home),'username':'Delete228'},fresh
    # The builder writes this aggregate PASS only after its context manager
    # has stopped the source client, not merely after authoring commands finish.
    completed=json.loads((authored_home/'result.json').read_text())
    assert completed['passed'] and completed['home']==str(authored_home) and completed['world']==WORLD,completed
    source=authored_home/'saves'/WORLD;clone=scratch/'saves'/WORLD
    assert source.is_dir() and source!=clone and not clone.exists()
    assert all(not p.is_symlink() for p in source.rglob('*'))
    source_manifest=_save_manifest(source)
    clone.parent.mkdir(exist_ok=True);shutil.copytree(source,clone,copy_function=shutil.copy2)
    assert _save_manifest(clone)==source_manifest,'Clone differs from the closed source save'
    marker={'world':WORLD,'source':str(source),'clone':str(clone),
        'source_level_sha256':_digest(source/'level.dat'),
        'source_game_sha256':completed['game_sha256'],
        'source_files_sha256':source_manifest}
    if (authored_home/'schematic-fixtures.json').is_file():
        fixtures=json.loads((authored_home/'schematic-fixtures.json').read_text())
        inputs=authored_home/'schematics'
        assert inputs.is_dir() and not inputs.is_symlink()
        assert all(p.is_file() and not p.is_symlink() for p in inputs.iterdir())
        assert _save_manifest(inputs)==fixtures,'Authored schematic fixture hashes differ'
        shutil.copytree(inputs,scratch/'schematics',copy_function=shutil.copy2)
        assert _save_manifest(scratch/'schematics')==fixtures
        marker['source_schematic_files_sha256']=fixtures
    (scratch/'.review06-clone.json').write_text(json.dumps(marker,indent=2)+'\n')
    # Tutorial state is constructed at world open; changing its saved option
    # through the live control socket does not dismiss an existing toast.
    (scratch/'options.txt').write_text('tutorialStep:none\nchatVisibility:2\nlang:ru_ru\n')
    _clone(scratch)
    return marker


def _clone(scratch):
    scratch = Path(scratch).resolve(); scratch.relative_to((ROOT / '.local').resolve())
    marker = json.loads((scratch / '.review06-clone.json').read_text())
    source = Path(marker['source']).resolve(); source.relative_to((ROOT / '.local').resolve())
    clone = scratch / 'saves' / WORLD
    assert marker['world'] == WORLD and Path(marker['clone']).resolve() == clone, marker
    assert source != clone and clone.is_dir() and not clone.is_symlink(), marker
    for path in clone.rglob('*'):
        assert not path.is_symlink(), ('A clone must not redirect into its source',path)
        if path.is_file(): assert path.stat().st_nlink==1, ('Hard-linked save files are not disposable copies',path)
    assert (clone / 'level.dat').is_file(),marker
    _source_unchanged(marker)
    authored = json.loads((source.parents[1] / 'review06-build-result.json').read_text())
    assert authored['passed'] and authored['plan']['world'] == WORLD, authored
    completed=json.loads((source.parents[1]/'result.json').read_text())
    assert completed['passed'] and completed['home']==str(source.parents[1]) and completed['world']==WORLD,completed
    marker=dict(marker,include_lit_burner=authored['plan'].get('include_lit_burner',False),
        include_compacting=any(station['id']=='compacting' for station in authored['plan']['stations']))
    return scratch, marker


def _output_positions(marker):
    return [p for p in OUTPUTS if marker.get('include_compacting') or p not in COMPACTING_BASINS]


def _counts(slots):
    result = collections.Counter()
    for stack in slots:
        if stack and stack.get('item'): result[stack['item']] += stack['count']
    return dict(result)


def _schematic_station(call, scratch, record):
    """Use the delivered bytes and empty site; no reconstruction of the source save."""
    from schematic_checks import _json_reply
    from review_world_06 import SCHEMATIC_ANCHOR
    x,y,z=SCHEMATIC_ANCHOR
    inputs=scratch/'schematics'
    before_files=_save_manifest(inputs)
    call('command','gamemode creative')
    _grounded(call,(x+4.5,y,z+5.5))
    wait_loaded(call,[(x,y,z),(x+3,y+2,z+1)])
    def snapshot():
        return [call('command',f'execute if block {xx} {yy} {zz} minecraft:air run say schematic_site_air')['chat']
                for xx in range(x,x+4) for yy in range(y,y+3) for zz in range(z,z+2)]
    before=snapshot()
    assert all(any('schematic_site_air' in s for s in lines) for lines in before),before
    inspected=_json_reply(call('command','create schematic inspect own-press.nbt'))
    assert inspected['ok'] and inspected['blocks']==5 and inspected['skipped_air']==1,inspected
    assert snapshot()==before,'Schematic inspection changed the delivered empty site'
    rejected=_json_reply(call('command',f'create schematic paste unsupported-belt.nbt {x} {y} {z}'))
    assert not rejected['ok'] and rejected['issues'],rejected
    assert snapshot()==before,'Rejected schematic changed the delivered empty site'
    pasted=_json_reply(call('command',f'create schematic paste own-press.nbt {x} {y} {z}'))
    assert pasted['ok'] and pasted['blocks']==5,pasted
    call('wait',20)
    shaft=call('block',x+1,y+2,z)['state']
    assert 'axis=x' in shaft and 'waterlogged=false' in shaft,shaft
    assert call('block',x+2,y,z)['block']=='create:depot'
    assert _counts(call('container',x+2,y,z)['slots'])=={}
    # Give one test input through the ordinary top-face player interaction.
    # This is a mechanism check; unlike the separate crafting checks, it does
    # not claim that this ingot was withdrawn from the delivered stock.
    call('command','clear @s');call('command','gamemode survival')
    call('command','give @s minecraft:copper_ingot 1');call('wait',4)
    _grounded(call,(x+4.5,y,z+2.5))
    call('look-at','block',x+2,y,z,'up');call('wait',3)
    call('interact',x+2,y,z,'up');call('wait',4)
    assert call('inventory')['counts']=={},call('inventory')
    for _ in range(30):
        if _counts(call('container',x+2,y,z)['slots'])=={'create:copper_sheet':1}:break
        call('wait',10)
    else:raise AssertionError(('Pasted schematic did not press one ingot',call('container',x+2,y,z)))
    call('look-at','block',x+2,y,z,'up');call('wait',3)
    call('interact',x+2,y,z,'up');call('wait',5)
    assert call('inventory')['counts']=={'create:copper_sheet':1},call('inventory')
    assert _counts(call('container',x+2,y,z)['slots'])=={}
    assert _save_manifest(inputs)==before_files,'Schematic import changed input files'
    call('command','gamemode creative')
    record('Delivered schematic inspect/rejection/paste; normal player input1→sheet1 and pickup',
           schematic_files_sha256=before_files,inspected=inspected,rejected=rejected,pasted=pasted)


def _ingredient(value, seen=()):
    if isinstance(value,list): return _ingredient(value[0],seen)
    if isinstance(value,dict): return _ingredient(value.get('item') or '#'+value['tag'],seen)
    if not value.startswith('#'): return value
    tag=value[1:]; assert tag not in seen,tag
    if tag=='minecraft:planks': return 'minecraft:oak_planks'
    namespace,path=tag.split(':',1)
    values=json.loads((ROOT/'content/data'/namespace/'tags/item'/(path+'.json')).read_text())['values']
    for value in values:
        value=value['id'] if isinstance(value,dict) else value
        if value.startswith(('minecraft:','#')): return _ingredient(value,(*seen,tag))
        if value.startswith('create:') and value[7:] in CATALOG: return value
    raise AssertionError(('No implemented ingredient',tag))


def _recipes(recipes):
    result=[]
    for name in recipes:
        recipe=json.loads((ROOT/'content/data/create/recipe/crafting'/(name+'.json')).read_text())
        if 'pattern' in recipe:
            cells={100+r*3+c:_ingredient(recipe['key'][ch]) for r,row in enumerate(recipe['pattern']) for c,ch in enumerate(row) if ch!=' '}
        else: cells={100+i:_ingredient(value) for i,value in enumerate(recipe['ingredients'])}
        result.append((name,recipe,cells))
    return result


def _craft_requirement(recipes):
    # Earlier crafted intermediates remain available to later recipes.
    available=collections.Counter();required=collections.Counter()
    for _,recipe,cells in _recipes(recipes):
        for item,count in collections.Counter(cells.values()).items():
            used=min(available[item],count);available[item]-=used;required[item]+=count-used
        available[recipe['result']['id']]+=recipe['result'].get('count',1)
    return dict(+required)


def _grounded(call, player=None):
    if player is not None:
        call('command','tp @s '+' '.join(map(str,player)))
        call('wait-ready',120);call('wait',5)
    state=call('state')['player']
    assert state['on_ground'] and not state['flying'] and not state['fall_flying'],state
    ability=' '.join(call('command','data get entity @s abilities.flying')['chat'])
    assert re.search(r'\b0b(?:\W|$)',ability),('Server flying ability still enabled',ability)
    if player is not None: assert abs(state['position'][1]-player[1])<.01,state
    return state


def _craft(call, table, recipes, clear, scratch=None):
    """Survival UI using only delivered barrel stock; no supplied ingredients."""
    assert call('block', *table)['block'] == 'minecraft:crafting_table'
    call('command','gamemode survival');clear()
    required=_craft_requirement(recipes)
    collected=collections.Counter()
    for pos in CRAFT_BARRELS:
        initial=call('container',*pos)['slots']
        chosen=[(i,s) for i,s in enumerate(initial) if s and s['item'] in required and collected[s['item']]<required[s['item']]]
        if not chosen: continue
        _grounded(call,(pos[0]+.5,64,pos[2]+2.5))
        call('look-at','block',*pos,'south');call('wait',3);call('interact',*pos,'south');call('wait',8)
        screen=call('screen')
        assert screen['screen']=='container' and screen['container']==list(pos),screen
        for i,stack in chosen:
            call('click-slot',300+i,'shift');call('wait',3)
            collected[stack['item']]+=stack['count']
        call('close');call('wait',4)
        after=call('container',*pos)['slots']
        for i,stack in chosen: assert after[i] is None,(pos,i,stack,after)
    expected=collections.Counter(call('inventory')['counts'])
    assert dict(expected)==dict(collected),(expected,collected)
    assert all(expected[item]>=count for item,count in required.items()),('Delivered crafting stock is insufficient',required,expected)
    results=[]
    for name,recipe,cells in _recipes(recipes):
        before=expected.copy()
        _grounded(call,(table[0]+.5,64,table[2]+2.5))
        call('look-at','block',*table,'south');call('wait',3);call('interact',*table,'south');call('wait',8)
        assert call('screen')['screen']=='inventory'
        inventory=call('inventory')
        sources={s['item']:s['slot'] for s in inventory['hotbar']+inventory['main'] if s.get('item')}
        for item in dict.fromkeys(cells.values()):
            source=sources[item];call('click-slot',source)
            for slot,entry in cells.items():
                if entry==item: call('click-slot',slot,'right')
            if call('inventory')['carried'] is not None: call('click-slot',source)
            assert call('inventory')['carried'] is None
        call('wait',5);screen=call('screen');output=next(s for s in screen['slots'] if s['slot']==200)
        result=recipe['result'];assert output.get('item')==result['id'] and output.get('count')==result.get('count',1),(name,output,result)
        image=None
        if scratch is not None:
            image=str(Path(scratch)/('review06-craft-'+name.rsplit('/',1)[-1]+'.png'))
            call('screenshot',image)
        call('click-slot',200,'shift');call('wait',5);call('close');call('wait',5)
        expected.subtract(collections.Counter(cells.values()));expected[result['id']]+=result.get('count',1)
        if name=='appliances/dough': expected['minecraft:bucket']+=1
        expected=+expected
        actual=call('inventory')['counts'];assert actual==dict(expected),(name,dict(expected),actual)
        assert call('inventory')['carried'] is None
        results.append({'recipe':name,'result':result,'before':dict(before),'inventory':actual,'image':image})
    return results


def run(call, graphics=False, log=None, scratch=None, *, resume_initial=False, resume_press_ready=False):
    scratch,marker=_clone(scratch)
    assert not (resume_initial and resume_press_ready)
    resume_proof=json.loads((scratch/'review06-clone-result.json').read_text()) if resume_initial or resume_press_ready else None
    assert call('state')['world']==WORLD
    report={'passed':False,'world':WORLD,'source':marker['source'],'clone':marker['clone'],
        'source_world_modified':False,'review_scope':__doc__,'checks':[],'images':[]}
    def save(): (scratch/'review06-clone-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    def cmd(text): return call('command',text)
    def raw(pos,path=''): return ' '.join(cmd('data get block '+' '.join(map(str,pos))+' '+path)['chat'])
    def number(pos,key):
        text=raw(pos);match=re.search(r'\b'+re.escape(key)+r'\s*:\s*(-?[\d.]+(?:[eE][+-]?\d+)?)',text);assert match,(pos,key,text)
        return float(match[1])
    def expect(pos,name,*properties):
        block=call('block',*pos);assert block['block']==name and all(p in block['state'] for p in properties),(pos,block,properties)
        return block
    def counts(pos): return _counts(call('container',*pos)['slots'])
    def power(pos,value): cmd('data merge block '+' '.join(map(str,pos))+' {ScrollValue:'+str(value)+'}')
    def record(name,**details): report['checks'].append(dict(name=name,**details));save();print('Review06 clone:',name,flush=True)
    def wait_for(test,description,ticks=1600):
        for _ in range(ticks//10):
            if test(): return
            call('wait',10)
        raise AssertionError(('Prepared station did not complete',description))
    def stand(player):
        return _grounded(call,player)
    def click(pos,face='south',player=None):
        if player: stand(player)
        else: _grounded(call)
        side=() if face is None else (face,)
        call('look-at','block',*pos,*side);call('wait',3);call('interact',*pos,*side);call('wait',8)
        assert call('screen')['screen']=='playing',pos
    def clear(): cmd('clear @s');call('wait',4)
    def bucket(pos,item):
        clear();cmd('item replace entity @s weapon.mainhand with minecraft:'+item);call('wait',4)
        x,y,z=pos;attempts=[]
        # A requested block interaction still obeys the real hit ray: a cow in
        # front of the Basin legitimately milks into an empty bucket. Select a
        # clear side before using the item, without removing the animal.
        for player,face in [((x-2.5,64,z+.5),'west'),((x+.5,64,z+2.5),'south'),
                            ((x+2.5,64,z+.5),'east'),((x+.5,64,z-2.5),'north')]:
            stand(player);call('look-at','block',*pos,face);call('wait',3)
            hit=call('state').get('looking_at')
            attempts.append({'player':player,'face':face,'looking_at':hit})
            if not hit or hit.get('kind')!='block' or hit.get('block',{}).get('pos')!=list(pos):continue
            call('interact',*pos,face);call('wait',8)
            assert call('screen')['screen']=='playing',pos
            report.setdefault('bucket_targeting',[]).append({'pos':pos,'item':item,'attempts':attempts})
            return
        raise AssertionError(('No clear side for a real Basin bucket interaction',pos,attempts))
    def capture(name,player,target):
        if not graphics: return
        cmd('gamemode spectator');cmd('tp @s '+' '.join(map(str,player)));call('wait-ready',120)
        call('look-at',*target);call('wait',25)
        path=scratch/(name+'.png');call('screenshot',path);assert path.is_file() and path.stat().st_size>1024,path
        report['images'].append(str(path))
        # Spectator->creative retains flight. Land through ordinary survival
        # mode before returning to creative; every later click checks this.
        cmd('gamemode survival');stand((40.5,64,20.5));cmd('gamemode creative')
        _grounded(call)
        wait_for(lambda:all(call('block',*p)['loaded'] for p in [(2,64,0),(73,64,0),(2,64,40),(73,64,40)]),
            'client map columns after overview observer',ticks=400)
    save()
    try:
        if resume_press_ready:
            # Resume only the documented side-face fixture refusal. The initial
            # stock/UI proofs remain attached; do not replenish or reprocess it.
            assert resume_proof['source']==marker['source'] and not resume_proof['passed']
            assert len(resume_proof['checks'])==2 and 'motor_ui' in resume_proof,resume_proof
            assert json.loads((scratch/'review06-initial-restart.json').read_text())['passed']
            assert counts((12,64,8))=={'create:copper_sheet':8}
            assert number((10,66,8),'ScrollValue')==0 and call('inventory')['counts']=={}
            report.update(resume_proof);report.pop('error',None)
            report['resumed_checkpoint']='All8 press outputs ready; previous side-face request correctly passed without pickup'
            save()
        else:
            # Forceload proves server availability; block()/screens read the client.
            # Center the observer so all delivered stations fit the small view range.
            stand((40.5,64,20.5))
            initial_positions=[(2,64,0),(25,65,0),(43,64,2),(43,65,14),(55,64,9),
                (69,65,2),(73,64,5),(6,64,36),(47,64,25),(2,64,40),(73,64,40)]
            wait_loaded(call,initial_positions)
            wait_for(lambda:all(call('block',*p)['loaded'] for p in initial_positions),
                'client columns for delivered station inspection',ticks=400)
            # Initial checks precede clear(), item insertion or any repair. A dirty
            # delivered station fails here; the test never silently sanitizes it.
            if resume_initial:
                initial=json.loads((scratch/'review06-initial-restart.json').read_text())
                previous=resume_proof
                assert initial['passed'] and len(previous['checks'])==1 and not previous['passed'],previous
                assert call('inventory')['counts']=={},'Observer-only resume requires the deliberately cleared inventory'
                inventory=initial['inventory']
                report['resumed_initial_inventory_scope']='Previously verified initial true-restart snapshot; stations rechecked live before resuming'
                report['images'].extend(previous['images'])
            else: inventory=call('inventory')
            carried=[s['item'] for s in inventory['hotbar']+inventory['main'] if s.get('item')]
            assert len(carried)==len(set(carried))==36,inventory
            assert [s.get('item') for s in inventory['hotbar']]==['create:'+n for n in ['wrench','creative_motor','shaft','cogwheel','belt_connector','mechanical_press','basin','mechanical_mixer','blaze_burner']],inventory
            assert any(s.get('part')=='head' and s.get('item')=='create:goggles' for s in inventory['armor']),inventory
            catalog=collections.Counter()
            for pos in [(2,64,0),(4,64,0)]:catalog.update(counts(pos))
            assert len(CATALOG)==47 and dict(catalog)=={'create:'+n:1 for n in CATALOG},catalog
            assert set(carried)<={'create:'+n for n in CATALOG},carried
            receipts=list((scratch/'.horizon-cache/create-assets/imports').glob('*/import.json'))
            receipts=[p for p in receipts if json.loads(p.read_text())['jar_sha256']==CREATE_SHA256]
            assert len(receipts)==1,receipts
            receipt_path=receipts[0];receipt=json.loads(receipt_path.read_text())
            required=['belt/start','belt/middle','belt/end','mechanical_press/head','millstone/inner',
                'mechanical_drill/head','mechanical_mixer/head','mechanical_mixer/pole','basin/block',
                'blaze_burner/block','blaze_burner/blaze/idle','blaze_burner/blaze/active',
                'blaze_burner/blaze/super','blaze_burner/flame']
            assert all('assets/create/models/block/'+name+'.json' in receipt['files'] for name in required),receipt
            for name,digest in receipt['files'].items():
                assert _digest(receipt_path.parent/'pack'/name)==digest,('Imported cache file changed',name)
            if log is not None:
                assert 'Create: '+str(len(receipt['files']))+' local resources' in Path(log).read_text(),log
            report['resource_evidence']={'receipt':str(receipt_path),'schema':receipt['schema'],
                'private_files_verified':len(receipt['files']),'required_models':required,
                'scope':'Private-cache hashes and pack application; screenshots still require human visual review.'}
            for pos,label in [((2,64,2),'КАТАЛОГ'),((12,64,4),'ОЧКИ'),((12,64,11),'ПРЕСС'),((28,64,8),'ЛЕНТА'),
                ((43,64,5),'СУХАЯ'),((55,64,5),'ТЕСТО'),((69,64,6),'ЛАТУНЬ'),((17,64,27),'ВЕТЕР'),((17,64,39),'КРАФТ')]:
                expect(pos,'minecraft:oak_sign');assert label in raw(pos,'front_text.messages'),(pos,label,raw(pos))
            if marker.get('source_schematic_files_sha256'):
                expect((66,64,38),'minecraft:oak_sign')
                assert 'СХЕМАТИКИ' in raw((66,64,38),'front_text.messages')
                assert _save_manifest(scratch/'schematics')==marker['source_schematic_files_sha256']
            for pos in [(43,64,2),(55,64,2),(59,64,6),(69,65,2)]:
                expect(pos,'create:basin','facing=down');assert number((pos[0]-1,pos[1]+1,pos[2]),'ScrollValue')==0
            for pos,rpm in [((10,66,0),32),((10,66,8),0),((24,65,0),0),((24,67,2),128),
                ((42,64,14),0),((12,65,24),0),((43,65,25),128)]:
                assert number(pos,'ScrollValue')==rpm,(pos,rpm,raw(pos))
            expect((44,66,25),'minecraft:lever','powered=true')
            expect((46,65,25),'minecraft:stone');assert number((45,65,25),'Speed')==0
            for pos,expected in [((43,64,2),{'minecraft:andesite':4,'minecraft:iron_nugget':4}),
                ((55,64,2),{'create:wheat_flour':4}),((59,64,6),{'minecraft:dirt':2,'minecraft:coarse_dirt':1,'minecraft:rooted_dirt':1}),
                ((69,65,2),{'minecraft:copper_ingot':4,'create:zinc_ingot':4}),((12,64,8),{'minecraft:copper_ingot':8}),
                ((26,64,6),{}),((47,64,25),{'minecraft:stone':32})]: assert counts(pos)==expected,(pos,counts(pos),expected)
            for pos in [(14,64,0),(25,65,6)]:assert counts(pos)=={},(pos,counts(pos))
            for z,item,_ in FANS:
                expect((3,65,z),'create:encased_fan','facing=east');assert number((1,65,z),'ScrollValue')==0
                slots=call('container',6,64,z)['slots'];assert slots[0]=={'item':item,'count':8} and all(s is None for s in slots[1:]),(z,slots)
            belt=raw((25,65,0),'Inventory')
            assert 'review06_belt: 71' in belt and re.findall(r'\bcount:\s*(\d+)\b',belt)==['8'],belt
            assert len(re.findall(r'\bid:\s*"minecraft:copper_ingot"',belt))==1,belt
            report['delivered_belt_component']='minecraft:custom_data.review06_belt=71; one copper_ingot stack of8'
            for z in range(6):expect((25,65,z),'create:belt')
            mill_total=collections.Counter()
            for pos in [(43,66,14),(43,65,14),(43,64,14),(44,64,14)]:mill_total.update(counts(pos))
            assert dict(mill_total)=={'minecraft:wheat':32},mill_total
            display=raw((55,64,9),'InputTanks');assert 'minecraft:water' in display and 'minecraft:lava' in display and display.count('amount: 1000')==2,display
            expect((73,64,2),'create:blaze_burner','blaze=none');expect((73,64,5),'create:blaze_burner','blaze=smouldering')
            assert counts((58,64,11)).get('minecraft:water_bucket')==2
            assert counts((72,64,8)).get('minecraft:coal')==32
            assert all(call('block',*p)['block']=='minecraft:crafting_table' for p in [(14,64,36),(20,64,36)])
            craft_stock=collections.Counter()
            for pos in CRAFT_BARRELS: craft_stock.update(counts(pos))
            required=_craft_requirement(CRAFT_RECIPES)
            missing={item:count-craft_stock[item] for item,count in required.items() if craft_stock[item]<count}
            assert not missing,('Delivered crafting materials missing before any mutation',missing,dict(craft_stock))
            report['delivered_crafting_stock']={'required':required,'available':dict(craft_stock)}
            assert not any(call('entities',96,'minecraft:item')['entities']), 'Unexpected loose item entities in delivered map'
            report['washing_initial']=inspect_washing(call)
            if marker.get('include_compacting'):
                report['compacting_initial']=inspect_compacting(call,scratch)
            record('Delivered catalog47, carried36/goggles, signs/materials, stopped inputs and empty output buffers')
            if not resume_initial: capture('review06-overview-before',(42,86,51),(39,65,15))
            cmd('gamemode creative');cmd('tick unfreeze');clear()

            # Gauge mutations use the delivered motor and actual comparator.
            stand((12.5,64,4.5))
            for value,power_value in [(16,4),(256,15),(32,7)]:
                power((10,66,0),value);call('wait',25)
                assert number((12,66,0),'Speed')==value
                expect((12,66,2),'minecraft:redstone_wire','power='+str(power_value))
            assert number((13,66,0),'Stress')>0
            if graphics:
                import value_settings_checks
                cmd('item replace entity @s armor.head with create:goggles')
                report['motor_ui']=value_settings_checks.run(call,graphics,Path(log),scratch,[10,66,0])
                power((10,66,0),32)
            record('Existing gauges/comparator16→256→32 RPM; actual source motor UI when graphics enabled')

            clear()
            power((10,66,8),128)
            wait_for(lambda:counts((12,64,8))=={'create:copper_sheet':8},'press8')
        power((10,66,8),0);click((12,64,8),'up',player=(14.5,64,10.5))
        assert counts((12,64,8))=={} and call('inventory')['counts'].get('create:copper_sheet')==8
        record('Delivered press processes eight copper ingots; ordinary empty-hand pickup clears depot')
        clear();power((24,65,0),32)
        wait_for(lambda:counts((26,64,6))=={'create:copper_sheet':8},'belt press/end hopper')
        power((24,65,0),0)
        assert counts((25,65,6))=={} and counts((25,64,6))=={} and 'review06_belt' not in raw((26,64,6)),raw((26,64,6))
        record('Real connector belt carries eight copper ingots through existing press/depot/hopper to8sheets')
        capture('review06-belt',(30,69,8),(25.5,66,2.5))

        power((42,64,14),128)
        mill_upstream=[(43,66,14),(43,65,14),(43,64,14)]
        wait_for(lambda:counts((44,64,14)).get('create:wheat_flour',0)>=32
            and all(counts(p)=={} for p in mill_upstream),'millstone wheat32/pipeline drained',ticks=2400)
        power((42,64,14),0);mill=counts((44,64,14))
        assert set(mill)<={'create:wheat_flour','minecraft:wheat_seeds'} and all(counts(p)=={} for p in mill_upstream),mill
        assert 32<=mill.get('create:wheat_flour',0)<=96 and 0<=mill.get('minecraft:wheat_seeds',0)<=32,mill
        record('Existing hopper-fed millstone consumes wheat32; source flour32..96/seeds0..32, pipeline empty',outputs=mill)
        power((42,65,2),32)
        wait_for(lambda:counts((43,64,2))=={'create:andesite_alloy':4},'dry alloy4');power((42,65,2),0)
        record('Dry Basin/Mixer consumes actual prepared4andesite+4nuggets into4alloy')

        for pos,motor,expected in [((55,64,2),(54,65,2),{'create:wheat_flour':3,'create:dough':1}),
            ((59,64,6),(58,65,6),{'minecraft:mud':4})]:
            bucket(pos,'water_bucket');power(motor,32);wait_for(lambda:counts(pos)==expected,('water recipe',pos));power(motor,0)
            assert 'minecraft:water' not in raw(pos,'InputTanks'),raw(pos,'InputTanks')
        bucket((55,64,9),'bucket');half=raw((55,64,9),'InputTanks')
        assert 'minecraft:water' not in half and 'minecraft:lava' in half,half
        bucket((55,64,9),'bucket');assert 'minecraft:lava' not in raw((55,64,9),'InputTanks')
        bucket((55,64,9),'water_bucket');bucket((55,64,9),'lava_bucket')
        record('Normal buckets: source water recipes dough1000mB/mud4×250mB and output-first display drain/refill')
        capture('review06-basins',(62,69,13),(56.5,65,6))

        clear();cmd('gamemode survival');cmd('give @s minecraft:coal 2');call('wait',4)
        click((69,64,2),player=(71.5,64,4.5));assert call('inventory')['counts']=={'minecraft:coal':1}
        assert number((69,64,2),'burnTimeRemaining')>0
        cmd('gamemode creative');power((68,66,2),32)
        wait_for(lambda:counts((69,65,2))=={'create:brass_ingot':8},'brass8');power((68,66,2),0)
        record('Survival coal2→1 feeds real burner; actual heated Basin/Mixer converts4copper+4zinc→8brass')
        capture('review06-brass',(74,68,7),(69.5,65.5,2.5))
        if marker['include_lit_burner']:
            expect((76,64,5),'create:lit_blaze_burner','flame_type=regular')
            for item,amount in [('minecraft:flint_and_steel',1),('minecraft:soul_sand',2),('minecraft:iron_shovel',1)]:
                clear();cmd('gamemode survival');cmd(f'give @s {item} {amount}');call('wait',4)
                click((73,64,2),player=(75.5,64,4.5))
                if item.endswith('flint_and_steel'):
                    expect((73,64,2),'create:lit_blaze_burner','flame_type=regular')
                elif item.endswith('soul_sand'):
                    expect((73,64,2),'create:lit_blaze_burner','flame_type=soul')
                    assert call('inventory')['counts']=={item:2}
                else:expect((73,64,2),'create:blaze_burner','blaze=none','facing=north')
                if item.endswith(('flint_and_steel','iron_shovel')):
                    selected=' '.join(cmd('data get entity @s SelectedItem')['chat'])
                    assert re.search(r'damage["\']?\s*:\s*1\b',selected),selected
            cmd('gamemode creative')
            record('Delivered empty cage: normal flint ignition, unconsumed soul conversion, shovel extinguish and real tool damage')

        clear()
        fan_positions=[*[(6,64,z) for z,_,_ in FANS],
            (4,64,32),(4,66,32),(4,65,31),(4,65,33),(5,65,32),(5,64,32),
            (4,64,20),(4,66,20),(4,65,19),(4,65,21),(4,65,20),(5,65,20)]
        stand((9.5,64,28.5));wait_loaded(call,fan_positions)
        wait_for(lambda:all(call('block',*p)['loaded'] for p in fan_positions),
            'client columns for fan enclosures and depots',ticks=400)
        for z,_,_ in FANS:power((1,65,z),32)
        wait_for(lambda:all(counts((6,64,z))=={out:8} for z,_,out in FANS),'five fan lines')
        for z,_,out in FANS:power((1,65,z),0)
        for pos in [(4,64,32),(4,66,32),(4,65,31),(4,65,33)]:expect(pos,'minecraft:glass')
        expect((5,65,32),'minecraft:iron_bars');expect((5,64,32),'minecraft:air')
        report['washing_processed']=inspect_washing(call)
        record('Five delivered fan media produce exactly8outputs each; physical water/lava enclosures remain intact')
        capture('review06-fans',(12,75,41),(4,65,28))
        cmd('gamemode survival');stand((16.5,64,24.5));power((12,65,24),128);call('wait',35)
        pushed=call('state')['player'];assert pushed['position'][0]>17.5,pushed
        power((12,65,24),0);stand((20.5,64,24.5));power((12,65,24),-128);call('wait',35)
        pulled=call('state')['player'];assert pulled['position'][0]<19.5,pulled
        power((12,65,24),0);cmd('gamemode creative')
        record('Existing safe corridor moves actual grounded survival player with positive and negative RPM',pushed=pushed,pulled=pulled)

        for shaft,magnitude in [((26,67,28),8),((28,66,29),16),((35,67,28),4)]: assert abs(number(shaft,'Speed'))==magnitude
        expect((44,66,25),'minecraft:lever','powered=true');expect((46,65,25),'minecraft:stone');assert number((45,65,25),'Speed')==0
        before=counts((47,64,25));clear();click((44,66,25),None,player=(45.5,64,27.5))
        expect((44,66,25),'minecraft:lever','powered=false')
        expected=dict(before);expected['minecraft:cobblestone']=expected.get('minecraft:cobblestone',0)+1
        wait_for(lambda:counts((47,64,25))==expected,'drill stone/cobble')
        expect((46,65,25),'minecraft:air');click((44,66,25),None)
        expect((44,66,25),'minecraft:lever','powered=true');call('wait',8)
        cmd('setblock 46 65 25 minecraft:stone');call('wait',30)
        expect((46,65,25),'minecraft:stone');assert counts((47,64,25))==expected and number((45,65,25),'Speed')==0
        record('Actual8/16/4RPM channels and existing drill lever yield exactly one new cobblestone before stopping',chest=expected)

        if graphics:
            stand((14.5,64,38.5))
            report['crafted']=_craft(call,(14,64,36),CRAFT_RECIPES,clear,scratch)
            cmd('gamemode creative')
            record('Six survival recipes use delivered barrel stock through the vanilla table; exact consumption and dough bucket return')
        else:report['crafting_gap']='Actual menu checks require graphics'
        if marker.get('source_schematic_files_sha256'):
            _schematic_station(call,scratch,record)
        if marker.get('include_compacting'):
            report['compacting']=run_compacting(call,graphics,log,scratch)
            report['images'].extend(report['compacting']['images'])
            record('Three delivered Press/Basin rigs: snowballs8→snowblocks2, snowblocks9→ice1, flint2+gravel1+lava100mB→andesite1; stopped and picked up normally')
        cmd('item replace entity @s armor.head with create:goggles')
        capture('review06-overview-after',(42,86,51),(39,65,15))
        call('save-all');_source_unchanged(marker)
        report['passed']=True;save();return report
    except BaseException as error:
        report['error']=repr(error);save();raise


def _inventory_snapshot(call, positions):
    result={}
    for p in positions:
        block=call('block',*p)['block']
        if block=='create:basin': paths=['InputItems','OutputItems','InputTanks','OutputTanks']
        elif block=='create:depot': paths=['HeldItem','OutputBuffer']
        elif block=='create:millstone': paths=['InputInventory','OutputInventory']
        else: paths=['Items']
        result[' '.join(map(str,p))]={path:call('command','data get block '+' '.join(map(str,p))+' '+path)['chat'] for path in paths}
    return result


def prepare_restart(call,scratch):
    scratch,marker=_clone(scratch);assert call('state')['world']==WORLD
    wait_loaded(call,[*MILL_PIPELINE,(44,64,14)])
    call('command','tick freeze');call('wait',5)
    # Restart startup permits ordinary ticks before the client is ready for
    # another freeze command. Drain the stopped Millstone's feeding hopper
    # normally first, so per-container restart equality compares a stable state.
    motor=' '.join(call('command','data get block 42 64 14')['chat'])
    speed=re.search(r'\bScrollValue\s*:\s*(-?[\d.]+)',motor)
    assert speed and float(speed[1])==0,('Millstone must remain stopped while settling',motor)
    pipeline=[*MILL_PIPELINE,(44,64,14)]
    def pipe_slots():
        return {' '.join(map(str,p)):call('container',*p)['slots'] for p in pipeline}
    def totals(inventories):
        result=collections.Counter()
        for slots in inventories.values():
            for stack in slots:
                if stack and stack.get('item'):
                    signature=json.dumps({k:v for k,v in stack.items() if k!='count'},sort_keys=True)
                    result[signature]+=stack['count']
        return dict(result)
    def game_time():
        text=' '.join(call('command','time query gametime')['chat'])
        numbers=re.findall(r'\b\d+\b',text);assert len(numbers)==1,text
        return int(numbers[0])
    pipe_before=pipe_slots();total_before=totals(pipe_before)
    started=game_time();waited=0
    hoppers=[MILL_PIPELINE[0],MILL_PIPELINE[2]]
    if any(_counts(pipe_before[' '.join(map(str,p))]) for p in hoppers):
        call('command','tick unfreeze')
        try:
            while waited<600:
                call('wait',10);waited+=10
                if all(not _counts(call('container',*p)['slots']) for p in hoppers):break
                if game_time()-started>=580:break
        finally:
            call('command','tick freeze');call('wait',5)
    pipe_after=pipe_slots();elapsed=game_time()-started
    assert 0<=elapsed<=600,('Millstone settling exceeded normal tick bound',elapsed,waited)
    assert all(not _counts(pipe_after[' '.join(map(str,p))]) for p in hoppers),('Stopped mill pipeline did not settle',pipe_after)
    assert totals(pipe_after)==total_before,('Mill pipeline lost/changed stacks while settling',pipe_before,pipe_after)
    settling={'before':pipe_before,'after':pipe_after,'totals_before':total_before,
        'totals_after':totals(pipe_after),'normal_ticks_waited':waited,'normal_game_ticks_elapsed':elapsed,
        'motor_scroll_value':0,'scope':'Ordinary hopper transfer with stopped Millstone; no replenishment, redstone or NBT/timer edits.'}
    positions=[(2,64,0),(4,64,0),*CRAFT_BARRELS,*_output_positions(marker),*MILL_PIPELINE,*[(6,64,z) for z,_,_ in FANS]]
    wait_loaded(call,positions)
    before={'source':marker['source'],'source_level_sha256':marker['source_level_sha256'],
        'mill_pipeline_settling':settling,
        'containers':{' '.join(map(str,p)):call('container',*p)['slots'] for p in positions},
        'canonical_inventory_nbt':_inventory_snapshot(call,positions),
        'display':call('command','data get block 55 64 9 InputTanks')['chat'],
        'belt_inventory':call('command','data get block 25 65 0 Inventory')['chat'],
        'inventory':call('inventory'),'player_inventory_nbt':call('command','data get entity @s Inventory')['chat'],
        'requires_actual_process_restart':True,'passed':False}
    call('save-all');_source_unchanged(marker)
    (scratch/'review06-restart.json').write_text(json.dumps(before,indent=2)+'\n')
    return before


def verify_restart(call,scratch,before):
    scratch,marker=_clone(scratch);assert call('state')['world']==WORLD
    call('command','tick freeze');wait_loaded(call,[tuple(map(int,p.split())) for p in before['containers']])
    for key,slots in before['containers'].items():
        pos=tuple(map(int,key.split()));assert call('container',*pos)['slots']==slots,(pos,slots,call('container',*pos))
    positions=[tuple(map(int,p.split())) for p in before['containers']]
    after=_inventory_snapshot(call,positions)
    assert after==before['canonical_inventory_nbt'],('Canonical inventory/components changed on restart',before['canonical_inventory_nbt'],after)
    assert call('command','data get block 55 64 9 InputTanks')['chat']==before['display']
    assert call('command','data get block 25 65 0 Inventory')['chat']==before['belt_inventory']
    assert call('inventory')==before['inventory'],('Player slots/armor/offhand/cursor changed',before['inventory'],call('inventory'))
    assert call('command','data get entity @s Inventory')['chat']==before['player_inventory_nbt']
    _source_unchanged(marker)
    result=dict(before,passed=True);(scratch/'review06-restart.json').write_text(json.dumps(result,indent=2)+'\n');return result
