#!/usr/bin/env python3
"""Check a closed CreateFactory06 source on a fresh disposable native clone.

The executable hash must be supplied explicitly. A successful run records
mechanism, crafting and process-restart checks; screenshot acceptance and an
independent code review remain separate evidence. No installed instance opens.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path

import review_map_06_checks as audit
from native_check_session import NativeCheckSession
from saved_block_checks import read_saved_block


def _slots(tag):
    result=collections.Counter()
    for entry in (tag or {}).get('value',[]):
        fields=entry['value']
        if 'id' in fields:
            result[fields['id']['value']]+=fields.get('count',{'value':1})['value']
    return result


def cold_preflight(source):
    """Inspect delivered NBT before any client opens even the copy."""
    world=source/'saves'/audit.WORLD
    manifest=audit._save_manifest(world)
    records={}
    def fields(pos):
        record=read_saved_block(source,pos,audit.WORLD)
        records[' '.join(map(str,pos))]=record
        return record['nbt']['value']
    catalog=collections.Counter()
    for pos in [(2,64,0),(4,64,0)]:catalog.update(_slots(fields(pos).get('Items')))
    assert dict(catalog)=={'create:'+name:1 for name in audit.CATALOG},catalog
    for pos,expected in [((43,64,2),{'minecraft:andesite':4,'minecraft:iron_nugget':4}),
        ((55,64,2),{'create:wheat_flour':4}),
        ((59,64,6),{'minecraft:dirt':2,'minecraft:coarse_dirt':1,'minecraft:rooted_dirt':1}),
        ((69,65,2),{'minecraft:copper_ingot':4,'create:zinc_ingot':4}),
        ((60,64,20),{'minecraft:snowball':8}),
        ((66,64,20),{'minecraft:snow_block':9}),
        ((72,64,20),{'minecraft:flint':2,'minecraft:gravel':1})]:
        data=fields(pos)
        assert dict(_slots(data['InputItems']['value'].get('Items')))==expected,(pos,data)
        assert not _slots(data['OutputItems']['value'].get('Items')),(pos,data)
    for z,item,_ in audit.FANS:
        data=fields((6,64,z));stack=data['HeldItem']['value']['Item']['value']
        assert stack['id']['value']==item and stack['count']['value']==8,(z,data)
        assert not _slots(data['OutputBuffer']['value'].get('Items')),(z,data)
    for pos,expected in [((12,64,8),{'minecraft:copper_ingot':8}),
                         ((14,64,0),{}),((25,65,6),{})]:
        data=fields(pos)
        held=data.get('HeldItem',{}).get('value',{}).get('Item',{}).get('value',{})
        counts={} if not held else {held['id']['value']:held.get('count',{'value':1})['value']}
        assert counts==expected,(pos,data)
        assert not _slots(data.get('OutputBuffer',{}).get('value',{}).get('Items')),(pos,data)
    display=fields((55,64,9))
    segments=display['InputTanks']['value']
    assert len(segments)==2,segments
    fluids=[]
    for segment in segments:
        fluid=segment['value']['TankContent']['value']['Fluid']['value']
        assert fluid['amount']=={'type':'int','value':1000},fluid
        fluids.append(fluid['id']['value'])
    assert fluids==['minecraft:water','minecraft:lava'],fluids
    compacting=fields((72,64,20))['InputTanks']['value']
    compacting_fluids=[]
    for segment in compacting:
        content=segment['value']['TankContent']['value']
        assert not content or set(content)=={'Fluid'},content
        compacting_fluids.append(content.get('Fluid',{}).get('value',{}))
    assert any(fluid.get('id',{}).get('value')=='minecraft:lava'
               and fluid.get('amount',{}).get('value')==1000 for fluid in compacting_fluids),compacting_fluids
    assert not _slots(display['InputItems']['value'].get('Items')),display
    assert not _slots(display['OutputItems']['value'].get('Items')),display
    belt=fields((25,65,0))['Inventory']['value']['Items']['value']
    assert len(belt)==1,belt
    stack=belt[0]['value']['Item']['value']
    assert stack['id']['value']=='minecraft:copper_ingot' and stack['count']['value']==8,stack
    assert stack['components']['value']['minecraft:custom_data']['value']['review06_belt']['value']==71,stack
    mill=collections.Counter()
    for pos in [(43,66,14),(43,65,14),(43,64,14),(44,64,14)]:
        data=fields(pos)
        if data['id']['value']=='create:millstone':
            for key in ['InputInventory','OutputInventory']:
                mill.update(_slots(data.get(key,{}).get('value',{}).get('Items')))
        else:mill.update(_slots(data.get('Items')))
    assert dict(mill)=={'minecraft:wheat':32},mill
    stock=collections.Counter()
    for pos in audit.CRAFT_BARRELS:stock.update(_slots(fields(pos).get('Items')))
    required=audit._craft_requirement(audit.CRAFT_RECIPES)
    assert all(stock[item]>=count for item,count in required.items()),('Delivered stock missing',required,dict(stock))
    assert audit._save_manifest(world)==manifest,'Cold reader changed the source save'
    return {'passed':True,'source_manifest':manifest,'craft_stock':dict(stock),
            'craft_required':required,'saved_records':records}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ['game','resources','ctl','create-jar','source','expected-sha']:
        parser.add_argument('--'+key,required=True)
    args=parser.parse_args()
    game=Path(args.game).resolve();source=Path(args.source).resolve()
    actual=hashlib.sha256(game.read_bytes()).hexdigest()
    if actual!=args.expected_sha:parser.error('Executable SHA256 differs from --expected-sha')
    completed=json.loads((source/'result.json').read_text())
    assert completed['passed'] and completed['home']==str(source),completed
    # This entry point accepts the current complete review package only.
    # Historical clones remain usable by their recorded runners, but must not
    # silently turn a missing new station into a successful current audit.
    authored=json.loads((source/'review06-build-result.json').read_text())
    assert authored['passed'] and {'schematic','compacting'} <= {station['id'] for station in authored['plan']['stations']}, \
        'The current review audit requires schematic station12 and Press/Basin station13'
    fixtures=json.loads((source/'schematic-fixtures.json').read_text())
    assert {'own-press.nbt','unsupported-belt.nbt'}<=fixtures.keys(), \
        'The current review package is missing required schematic fixtures'
    assert audit._save_manifest(source/'schematics')==fixtures,'Delivered schematic fixture hashes differ'
    preflight=cold_preflight(source)
    session=NativeCheckSession(game,args.resources,args.ctl,args.create_jar,
        name='review06-audit',graphics=True,world=audit.WORLD,username='Delete228')
    session.env.update(HORIZON_API_DISCOVERY='http://127.0.0.1:9/',HORIZON_NO_DISCORD='1')
    marker=audit.prepare_clone(session,source)
    report={'passed':False,'scope':__doc__,'game':str(game),'game_sha256':actual,
        'source_home':str(source),'source_game_sha256':completed['game_sha256'],
        'scratch':str(session.scratch),'source_unchanged':False,'images_reviewed':False,
        'release_acceptance':False,
        'test_sources_sha256':{name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
            for name in ['review_world_audit.py','review_map_06_checks.py','review_world_06.py']}}
    out=session.scratch/'aggregate-result.json'
    (session.scratch/'cold-preflight.json').write_text(json.dumps(preflight,indent=2)+'\n')
    def save():out.write_text(json.dumps(report,indent=2)+'\n')
    def restart_check(phase):
        before=audit.prepare_restart(session.call,session.scratch)
        old=session.process;starts=session.starts
        session.restart()
        assert old.poll()==0 and session.starts==starts+1 and session.process.pid!=old.pid,(old.poll(),session.starts)
        result=audit.verify_restart(session.call,session.scratch,before)
        result.update(previous_pid=old.pid,next_pid=session.process.pid)
        (session.scratch/('review06-'+phase+'-restart.json')).write_text(json.dumps(result,indent=2)+'\n')
        return result
    save();print(session.scratch,flush=True)
    try:
        with session:
            report['first_pid']=session.process.pid
            report['initial_restart']=restart_check('initial')
            report['stations']=audit.run(session.call,True,session.log,session.scratch)
            report['final_restart']=restart_check('final')
            assert session.starts==3
            report['process_restart_verified']=True
        audit._source_unchanged(marker)
        report.update(passed=True,source_unchanged=True,
            source_files_verified=len(marker['source_files_sha256']))
    except BaseException as error:
        report['error']=repr(error)
        try:audit._source_unchanged(marker);report['source_unchanged']=True
        except BaseException as changed:report['source_change_error']=repr(changed)
        raise
    finally:
        save();print(json.dumps({'result':str(out),'passed':report['passed']}),flush=True)


if __name__=='__main__':main()
