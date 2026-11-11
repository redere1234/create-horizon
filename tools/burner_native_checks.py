"""Registered burner and heated Mixer checks in an owned NativeCheckSession.

Fuel admission uses normal player interactions. Canonical inventory/fuel seeds
isolate the recipe and expiry boundaries. Exact clock comparisons belong to the
normal command-harness timing runner, never /tick sprint or multi-RPC polling.
"""
import json
import hashlib
from pathlib import Path
import re
import subprocess
import sys

from common import ROOT, PINS
from native_check_session import wait_loaded

BASE = (444, 63, 16)
BASIN = (448, 64, 16)
BURNER = (448, 63, 16)
MOTOR = (447, 65, 16)
MIXER = (448, 66, 16)


def _number(text, key, default=None):
    match = re.search(r'\b' + key + r'\s*:\s*(-?[\d.]+)', text)
    if default is not None and not match: return default
    assert match, (key, text)
    return float(match[1])


def _time(call):
    text = ' '.join(call('command', 'time query gametime')['chat'])
    numbers = re.findall(r'\b\d+\b', text)
    assert len(numbers) == 1, text
    return int(numbers[0])


def run(call, graphics=False, log=None, scratch=None, *, burner_visuals=False, client_trace=False):
    scratch = Path(scratch).resolve(); scratch.relative_to((ROOT / '.local').resolve())
    assert call('state')['world'] == 'CreateParity06'
    report = {'passed': False, 'source': PINS['create_revision'], 'checks': [], 'images': [],
        'source_tools': ['tools/burner_java_checks.py', 'tools/burner_heat_java_checks.py',
                         'tools/burner_placement_java_checks.py'],
        'timing_scope': 'bounded real-game output/power checks; no exact clock claim from these RPCs',
        'burner_dynamic_models_implemented': burner_visuals,
        'client_absent_fields_verified': False,
        'client_absent_field_scope': 'canonical server removal and no goggles HUD; optional changed-only actual renderer-input trace tests client fields separately'}
    if not burner_visuals:
        report['presentation_gap'] = 'Burner dynamic head/rods/flames are not required by this initial adapter acceptance.'
    result = scratch / 'burner-native-result.json'
    transcript = scratch / 'burner-native-transcript.jsonl'; transcript.write_text('')
    def save(): result.write_text(json.dumps(report, indent=2) + '\n')
    def ctl(*words):
        reply = call(*words)
        with transcript.open('a') as f: f.write(json.dumps({'command': list(map(str, words)), 'reply': reply}) + '\n')
        return reply
    def cmd(command): return ctl('command', command)
    def xyz(pos): return ' '.join(map(str, pos))
    def data(pos, path=''): return ' '.join(cmd('data get block ' + xyz(pos) + ' ' + path)['chat'])
    def setblock(pos, state): return cmd('setblock ' + xyz(pos) + ' ' + state)
    def merge(pos, nbt): return cmd('data merge block ' + xyz(pos) + ' ' + nbt)
    def passed(name, **extra): report['checks'].append(dict(name=name, **extra)); save()
    def held(item=None, count=1, marker=None):
        cmd('clear @s')
        if item:
            patch = '[minecraft:custom_data={fuel_marker:' + str(marker) + '}]' if marker else ''
            cmd(f'item replace entity @s weapon.mainhand with {item}{patch} {count}')
        ctl('wait', 5)
    def stand(pos):
        x, y, z = pos
        support = cmd(f'execute if block {x+2} 62 {z+2} minecraft:smooth_stone run say burner_support_ok')
        assert any('burner_support_ok' in s for s in support['chat']), support
        cmd(f'tp @s {x+2.5} 63 {z+2.5}'); ctl('wait', 4)
        state = ctl('state')['player']
        assert state['on_ground'] and abs(state['position'][1]-63) < .001, state
        ctl('look-at', 'block', *pos, 'south'); ctl('wait', 2)
    def click(pos=BASE):
        stand(pos); ctl('interact', *pos, 'south'); ctl('wait', 5)
    def offset():return Path(log).stat().st_size if client_trace else 0
    def client_state(after,expected,present=(),absent=()):
        assert graphics and client_trace and log,'Actual client render-read tracing must be explicitly enabled'
        for _ in range(40):
            with Path(log).open('rb') as stream:
                stream.seek(after);tail=stream.read().decode('utf-8',errors='replace')
            # The logger can still be writing its final JSON line.
            lines=tail.splitlines(keepends=True)
            if lines and not lines[-1].endswith('\n'):lines.pop()
            for line in reversed(lines):
                prefix='Create burner client state: '
                if prefix not in line:continue
                row=json.loads(line.split(prefix,1)[1])
                if row.get('event')!='burner_client_state' or row.get('pos')!=list(BASE):continue
                keys=row['keys'];assert keys==sorted(keys),row
                if all(row.get(k)==v for k,v in expected.items()) and all(k in keys for k in present) and all(k not in keys for k in absent):
                    passed('Actual client renderer-input state',expected=expected,present=list(present),absent=list(absent),observed=row)
                    return row
            ctl('wait',2)
        raise AssertionError(('No matching actual client burner state',expected,present,absent,lines[-10:]))
    def step(n):
        before=_time(ctl);cmd('tick step '+str(n))
        for _ in range(40):
            now=_time(ctl)
            assert now<=before+n,(before,n,now)
            if now==before+n:return
            ctl('wait',2)
        raise AssertionError(('Frozen tick steps did not complete',before,n,now))
    def prepare(*, heat='smouldering', fuel=0, time=0, item='minecraft:coal', count=3, creative=False, marker=None):
        cmd('tick freeze'); step(7)
        cmd('gamemode ' + ('creative' if creative else 'survival'))
        setblock(BASE, 'minecraft:air')
        setblock(BASE, 'create:blaze_burner[blaze=' + heat + ',facing=north]')
        merge(BASE, '{fuelLevel:' + str(fuel) + ',burnTimeRemaining:' + str(time) + '}')
        held(item, count, marker)
    def check_fuel(name, fuel, time, heat, item, count):
        server = data(BASE)
        assert _number(server, 'fuelLevel', 0) == fuel, (name, server)
        assert _number(server, 'burnTimeRemaining', 0) == time, (name, server)
        assert 'create:blaze_heater' in server, server
        state = ctl('block', *BASE)['state']
        assert 'blaze=' + heat in state, (name, state)
        expected = {item: count} if count else {}
        assert ctl('inventory')['counts'] == expected, (name, ctl('inventory'), expected)
        passed(name, server=server, observed_state=state, inventory=expected)
    def counts():
        totals = {}
        for stack in ctl('container', *BASIN)['slots']:
            if stack: totals[stack['item']] = totals.get(stack['item'], 0) + stack['count']
        return totals
    def power(rpm): merge(MOTOR, '{ScrollValue:' + str(rpm) + '}')
    def inventory(n):
        merge(BASIN, '{InputItems:{Size:9,Items:['
            '{Slot:0,id:"minecraft:copper_ingot",count:' + str(n) + ',components:{"minecraft:custom_data":{heat_marker:71}}},'
            '{Slot:1,id:"create:zinc_ingot",count:' + str(n) + ',components:{"minecraft:custom_data":{heat_marker:72}}}]},'
            'OutputItems:{Size:9,Items:[]}}')
    def recipe_setup(n=1, fuel=True):
        cmd('tick unfreeze'); cmd('gamemode creative')
        for pos in [MIXER, BASIN, BURNER, MOTOR, (447,66,16)]: setblock(pos, 'minecraft:air')
        setblock(BURNER, 'create:blaze_burner[blaze=smouldering,facing=north]')
        setblock(BASIN, 'create:basin[facing=down]')
        setblock(MOTOR, 'create:creative_motor[facing=up]')
        setblock((447,66,16), 'create:cogwheel[axis=y]')
        setblock(MIXER, 'create:mechanical_mixer')
        power(0); ctl('wait',20); inventory(n)
        if fuel:
            held('minecraft:coal', 3, 501); click(BURNER)
            assert ctl('inventory')['counts'] == {'minecraft:coal': 3}, 'Creative keeps fuel'
            assert 'fuel_marker: 501' in ' '.join(cmd('data get entity @s SelectedItem')['chat'])
        power(32)
    def until(predicate, limit=400):
        for _ in range(limit // 2):
            current = data(MIXER)
            if predicate(current): return current
            ctl('wait',2)
        raise AssertionError(('Mixer predicate timed out', current, data(BASIN), data(BURNER)))
    def completion(expected, limit=400):
        for _ in range(limit // 5):
            got = counts()
            if got == expected: return got
            ctl('wait',5)
        raise AssertionError(('Heated output timed out', got, expected, data(BASIN), data(MIXER), data(BURNER)))
    save()
    try:
        if log is not None:
            errors=[line for line in Path(log).read_text().splitlines() if 'mod create content not loaded:' in line]
            assert not errors,('Create content registration failed before the gameplay fixture',errors)
        if graphics:
            ctl('options-set','chatVisibility','2')
            ctl('options-set','tutorialStep','none')
        cmd('tick unfreeze'); cmd('gamemode creative'); cmd('tp @s 446.5 63 18.5')
        ctl('wait-ready',120); ctl('wait',8)
        wait_loaded(ctl,[(x,63,z) for x in [440,453] for z in [12,21]])
        cmd('fill 440 62 12 453 70 21 minecraft:air')
        cmd('fill 440 62 12 453 62 21 minecraft:smooth_stone')
        cmd('execute positioned 448 64 16 run kill @e[type=minecraft:item,distance=..12]')
        cmd('tick freeze')

        for alias,heat in [('create:blaze_burner','smouldering'),('create:empty_blaze_burner','none')]:
            for yaw,facing,player in [(0,'north',(444.5,63,13.5)),(90,'east',(447.5,63,16.5)),
                (180,'south',(444.5,63,19.5)),(270,'west',(441.5,63,16.5))]:
                cmd('gamemode survival');setblock(BASE,'minecraft:air');held(alias,2)
                cmd('tp @s '+' '.join(map(str,player)));ctl('wait',4)
                assert ctl('state')['player']['on_ground']
                ctl('look-at','block',444,62,16,'up');ctl('wait',3)
                ctl('interact',444,62,16,'up');ctl('wait',6)
                state=ctl('block',*BASE)['state']
                assert 'create:blaze_burner' in state and 'blaze='+heat in state and 'facing='+facing in state,(alias,yaw,state)
                assert ctl('inventory')['counts']=={alias:1},(alias,yaw,ctl('inventory'))
                raw=data(BASE)
                if heat=='none':
                    assert 'create:blaze_heater' not in raw and re.search('not.*block entity|no.*block entity',raw,re.I),raw
                else:
                    assert 'create:blaze_heater' in raw and _number(raw,'fuelLevel')==0 and _number(raw,'burnTimeRemaining')==0,raw
                passed('Actual alias placement '+alias+' yaw'+str(yaw),observed_state=state,server=raw)
            for mode,player in [('survival',(444.5,63,16.5)),('adventure',(444.5,63,19.5))]:
                setblock(BASE,'minecraft:air');cmd('gamemode '+mode);held(alias,2)
                cmd('tp @s '+' '.join(map(str,player)));ctl('wait',4)
                assert ctl('state')['player']['on_ground']
                ctl('look-at','block',444,62,16,'up');ctl('wait',3)
                ctl('interact',444,62,16,'up');ctl('wait',6)
                assert ctl('block',*BASE)['state']=='minecraft:air'
                assert ctl('inventory')['counts']=={alias:2}
                passed('Placement refuses '+('player collision' if mode=='survival' else 'adventure without CanPlaceOn')+' '+alias)
        cmd('gamemode creative');held()

        setblock(BASE,'minecraft:air')
        setblock(BASE,'create:blaze_burner[blaze=none,facing=north]'); ctl('wait',5)
        empty = data(BASE)
        assert 'create:blaze_heater' not in empty and re.search('not.*block entity|no.*block entity',empty,re.I),empty
        setblock(BASE,'create:blaze_burner[blaze=smouldering,facing=north]')
        assert 'create:blaze_heater' in data(BASE), data(BASE)
        merge(BASE,'{fuelLevel:1,burnTimeRemaining:1777,fixture_unknown:{marker:42}}')
        setblock(BASE,'create:blaze_burner[blaze=none,facing=north]')
        retained=data(BASE)
        assert _number(retained,'burnTimeRemaining')==1777 and 'marker: 42' in retained,retained
        passed('Fresh NONE has no BE; NONE→smouldering creates BE; existing BE survives same-block→NONE',canonical=retained)

        for name,args,expected in [
            ('survival-coal',{},(1,1600,'kindled','minecraft:coal',2)),
            ('overflow-cap',{'fuel':1,'time':9999,'heat':'kindled'},(1,10000,'kindled','minecraft:coal',2)),
            ('cap-still-consumes',{'fuel':1,'time':10000,'heat':'kindled'},(1,10000,'kindled','minecraft:coal',2)),
            ('threshold-extends',{'fuel':1,'time':500,'heat':'kindled'},(1,2100,'kindled','minecraft:coal',2)),
            ('special-upgrade',{'item':'create:blaze_cake'},(2,3200,'seething','create:blaze_cake',2)),
            ('special-over-threshold-refused',{'fuel':2,'time':501,'heat':'seething','item':'create:blaze_cake'},(2,501,'seething','create:blaze_cake',3)),
            ('special-at-threshold',{'fuel':2,'time':500,'heat':'seething','item':'create:blaze_cake'},(2,3700,'seething','create:blaze_cake',2)),
            ('fuel-downgrade-refused',{'fuel':2,'time':300,'heat':'seething'},(2,300,'seething','minecraft:coal',3)),
            ('creative-keeps-coal',{'creative':True},(1,1600,'kindled','minecraft:coal',3)),
            ('fuel-container-remainder',{'item':'minecraft:lava_bucket','count':1},(1,20000,'kindled','minecraft:bucket',1)),
        ]:
            prepare(**args); click(); check_fuel(name,*expected)
        prepare(item='create:creative_blaze_cake'); click()
        raw=data(BASE)
        assert _number(raw,'isCreative')==1 and not re.search(r'\b(?:fuelLevel|burnTimeRemaining):',raw),raw
        assert ctl('inventory')['counts']=={'create:creative_blaze_cake':3}
        passed('Creative cake is not consumed and omits canonical fuel fields',server=raw)
        for fuel,time,heat,expected in [(2,1,'seething',(1,5000,'kindled')),(1,1,'kindled',(0,0,'smouldering'))]:
            prepare(fuel=fuel,time=time,heat=heat);step(1);ctl('wait',4)
            raw=data(BASE)
            assert (_number(raw,'fuelLevel'),_number(raw,'burnTimeRemaining'))==expected[:2],raw
            assert 'blaze='+expected[2] in ctl('block',*BASE)['state']
            passed('Source fuel expiry ' + heat,server=raw)
        prepare(marker=501);click()
        selected=' '.join(cmd('data get entity @s SelectedItem')['chat'])
        assert 'fuel_marker: 501' in selected and re.search(r'\bcount:\s*2\b',selected),selected
        passed('Partially consumed component-bearing fuel retains its full stack patch',selected=selected)
        prepare(item='create:goggles',count=1)
        merge(BASE,'{fixture_unknown:{marker:42}}')
        after=offset();click()
        assert _number(data(BASE),'Goggles')==1
        assert ctl('inventory')['counts']=={'create:goggles':1}
        if client_trace:
            client_state(after,{'goggles':True},present=['Goggles','fixture_unknown'])
            after=offset();merge(BASE,'{Goggles:0b,presence_zero_goggles_probe:{}}')
            client_state(after,{'goggles':True},present=['Goggles','fixture_unknown','presence_zero_goggles_probe'])
        held();after=offset();click();raw=data(BASE)
        assert not re.search(r'\bGoggles:',raw),raw
        if client_trace:
            client_state(after,{'goggles':False},present=['fixture_unknown'],absent=['Goggles'])
            after=offset();merge(BASE,'{TrainHat:1b}')
            client_state(after,{'trainhat':True},present=['TrainHat','fixture_unknown'])
            after=offset();merge(BASE,'{TrainHat:0b,presence_zero_trainhat_probe:{}}')
            client_state(after,{'trainhat':True},present=['TrainHat','fixture_unknown','presence_zero_trainhat_probe'])
            after=offset();cmd('data remove block '+xyz(BASE)+' TrainHat')
            client_state(after,{'trainhat':False},present=['fixture_unknown'],absent=['TrainHat'])
            held('create:creative_blaze_cake',3);after=offset();click()
            client_state(after,{'creative':True,'fuel':0,'remaining':0},present=['isCreative','fixture_unknown'],absent=['fuelLevel','burnTimeRemaining'])
            after=offset();cmd('data remove block '+xyz(BASE)+' isCreative')
            merge(BASE,'{fuelLevel:1,burnTimeRemaining:1800}')
            client_state(after,{'creative':False,'fuel':1,'remaining':1800},present=['fuelLevel','burnTimeRemaining','fixture_unknown'],absent=['isCreative','Goggles','TrainHat'])
            assert 'marker: 42' in data(BASE)
            report['client_absent_fields_verified']=True
        passed('Burner cosmetic goggles attach without consumption; empty-hand remove omits server field',server=raw)

        recipe_setup(2); completion({'create:brass_ingot':4})
        assert 'heat_marker' not in data(BASIN,'OutputItems')
        passed('Actual fueled burner +32RPM mixer converts2copper+2zinc→4brass; results do not inherit input components')
        recipe_setup(1)
        until(lambda raw:_number(raw,'Running')==1 and 1<=_number(raw,'Ticks')<20)
        merge(BURNER,'{burnTimeRemaining:1}')
        ctl('wait',130)
        assert counts()=={'minecraft:copper_ingot':1,'create:zinc_ingot':1},counts()
        raw=data(BASIN)
        assert 'heat_marker: 71' in raw and 'heat_marker: 72' in raw,raw
        assert 'blaze=smouldering' in ctl('block',*BURNER)['state']
        passed('Fuel loss during an active heated cycle preserves all inputs/components and produces no brass',server=raw)
        recipe_setup(1)
        until(lambda raw:_number(raw,'Running')==1 and 1<=_number(raw,'Ticks')<20)
        power(0);ctl('wait',45)
        assert counts()=={'minecraft:copper_ingot':1,'create:zinc_ingot':1},counts()
        power(32);completion({'create:brass_ingot':2})
        passed('Power interruption preserves inputs; restored mechanical power completes real brass recipe')

        if graphics:
            cmd('item replace entity @s armor.head with create:goggles')
            stand(BURNER)
            hud_after=Path(log).stat().st_size
            ctl('wait',35)
            with Path(log).open('rb') as stream:
                stream.seek(hud_after);observed=stream.read().decode('utf-8',errors='replace')
            assert not any('"event":"goggles_hud"' in line for line in observed.splitlines()),observed[-4000:]
            image=scratch/'burner-no-goggles-hud-native.png';ctl('screenshot',image)
            report['images'].append(str(image))
            passed('Worn goggles show no invented burner tooltip; source provider also returns zero lines')
        report['passed']=True;save();return report
    except BaseException as error:
        report['error']=repr(error);save();raise
    finally:
        cmd('tick unfreeze')


def prepare_restart(call,scratch):
    assert call('state')['world']=='CreateParity06'
    call('command','tick freeze')
    call('command','tp @s 450.5 63 18.5')
    call('wait-ready',120)
    wait_loaded(call,[BURNER,BASIN,MIXER])
    call('command','data merge block 447 65 16 {ScrollValue:0}')
    call('command','data merge block 448 63 16 {fuelLevel:1,burnTimeRemaining:1777,Goggles:1b,TrainHat:1b,fixture_unknown:{marker:42}}')
    call('command','data merge block 448 64 16 {InputItems:{Size:9,Items:[{Slot:0,id:"minecraft:copper_ingot",count:2,components:{"minecraft:custom_data":{restart_heat:91}}},{Slot:1,id:"create:zinc_ingot",count:2,components:{"!minecraft:custom_name":{},"minecraft:custom_data":{restart_heat:92}}}]},OutputItems:{Size:9,Items:[]}}')
    before={'passed':False,'time':_time(call),
        'items':call('command','data get block 448 64 16 InputItems')['chat'],
        'burner':call('command','data get block 448 63 16')['chat'],
        'requires_actual_process_restart':True}
    # Use the documented control operation, which waits for the host's save.
    # A chat command acknowledgement alone does not prove command acceptance.
    call('save-all')
    before['saved'] = _saved_restart(scratch)
    (Path(scratch)/'burner-restart-result.json').write_text(json.dumps(before,indent=2)+'\n')
    return before


def _saved_restart(scratch):
    from saved_block_checks import read_saved_block
    saved = {'burner': read_saved_block(scratch, BURNER),
             'basin': read_saved_block(scratch, BASIN)}
    values = saved['burner']['nbt']['value']
    assert values['id']['value'] == 'create:blaze_heater', saved
    for key, expected in [('fuelLevel', 1), ('burnTimeRemaining', 1777),
                          ('Goggles', 1), ('TrainHat', 1)]:
        assert values[key]['value'] == expected, (key, saved)
    assert values['fixture_unknown']['value']['marker']['value'] == 42, saved
    inventory = saved['basin']['nbt']['value']['InputItems']['value']['Items']['value']
    assert len(inventory) == 2, saved
    for tag, item, marker in zip(inventory, ['minecraft:copper_ingot', 'create:zinc_ingot'], [91, 92]):
        stack = tag['value']
        assert stack['id']['value'] == item and stack['count']['value'] == 2, stack
        patch = stack['components']['value']
        assert patch['minecraft:custom_data']['value']['restart_heat']['value'] == marker, stack
    assert inventory[1]['value']['components']['value']['!minecraft:custom_name']['value'] == {}, saved
    return saved


def closed_restart_snapshot(scratch, before):
    """Read exact saved canonical NBT after process exit and before reopening."""
    saved = _saved_restart(scratch)
    assert all(saved[key]['nbt'] == before['saved'][key]['nbt'] for key in saved), (saved, before)
    before['saved_while_closed'] = saved
    (Path(scratch)/'burner-restart-result.json').write_text(json.dumps(before,indent=2)+'\n')


def verify_restart(call,scratch,before):
    assert call('state')['world']=='CreateParity06'
    assert 'saved_while_closed' in before, 'Read the exact saved NBT after closing and before reopening the fixture'
    call('command','tick freeze')
    call('command','tp @s 450.5 63 18.5');call('wait-ready',120);call('wait',8)
    wait_loaded(call, [BURNER, BASIN, MIXER])
    call('command','forceload add 440 8 456 24')
    now=_time(call);elapsed=now-before['time'];assert 0<=elapsed<1777,elapsed
    burner=call('command','data get block 448 63 16')['chat'];raw=' '.join(burner)
    remaining=_number(raw,'burnTimeRemaining')
    consumed=1777-remaining
    # World time includes early ticks before this chunk/BE starts ticking. The
    # exact disk value is checked above; no guessed startup tolerance is used.
    assert _number(raw,'fuelLevel')==1 and 0<=consumed<=elapsed,(elapsed,raw)
    assert _number(raw,'Goggles')==1 and _number(raw,'TrainHat')==1 and 'marker: 42' in raw,raw
    items=call('command','data get block 448 64 16 InputItems')['chat']
    assert items==before['items'],(items,before['items'])
    held=False
    try:
        call('server-hold','on');held=True
        call('command','tick unfreeze')
        start=_time(call)
        initial=' '.join(call('command','data get block 448 63 16')['chat'])
        call('server-hold','off');held=False
        for _ in range(80):
            call('wait',5)
            if _time(call)>=start+20:
                break
        else:
            raise AssertionError('Loaded normal simulation did not advance20 ticks')
        call('server-hold','on');held=True
        end=_time(call)
        final=' '.join(call('command','data get block 448 63 16')['chat'])
        assert 20<=end-start<1777,(start,end)
        assert _number(initial,'burnTimeRemaining')-_number(final,'burnTimeRemaining')==end-start,(start,end,initial,final)
        assert 'marker: 42' in final and _number(final,'Goggles')==1 and _number(final,'TrainHat')==1,final
        final_items=call('command','data get block 448 64 16 InputItems')['chat']
        assert final_items==before['items'],(final_items,before['items'])
    finally:
        call('command','tick freeze')
        if held:call('server-hold','off')
    result=dict(before,passed=True,after_time=now,startup_world_ticks=elapsed,
        startup_burner_ticks=consumed,startup_ticks_before_burner_loaded=elapsed-consumed,
        startup_bound='0<=consumed<=elapsed from exact saved1777; no arbitrary tolerance',
        loaded_start_time=start,loaded_end_time=end,loaded_burner_ticks=end-start,
        loaded_initial=initial,loaded_final=final,after_burner=burner,after_items=items,
        loaded_final_items=final_items)
    (Path(scratch)/'burner-restart-result.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def run_restart_only(game, resources, ctl, create_jar, restart_from):
    """Clone one closed private successful live fixture; repeat only persistence."""
    import shutil
    from native_check_session import NativeCheckSession
    source=Path(restart_from).resolve()
    source.relative_to((ROOT/'.local').resolve())
    evidence=json.loads((source/'burner-native-result.json').read_text())
    assert evidence['passed'], 'A successful private live fixture is required'
    world=source/'saves/CreateParity06'
    assert (world/'level.dat').is_file() and not any(p.is_symlink() for p in world.rglob('*')),world
    fingerprint=hashlib.sha256((world/'level.dat').read_bytes()).hexdigest()
    session=NativeCheckSession(game,resources,ctl,create_jar,name='burner-restart-only',
                               graphics=False,username='CreateBurner')
    shutil.copytree(world,session.scratch/'saves/CreateParity06')
    (session.scratch/'options.txt').write_text('tutorialStep:none\nchatVisibility:2\n')
    session.env.update(HORIZON_API_DISCOVERY='http://127.0.0.1:9/',HORIZON_NO_DISCORD='1')
    report=dict(passed=False,game=str(session.game),
        game_sha256=hashlib.sha256(session.game.read_bytes()).hexdigest(),
        scope=run_restart_only.__doc__,original_private_fixture=str(source),source_untouched=False)
    output=session.scratch/'aggregate-result.json'
    print(json.dumps({'scratch':str(session.scratch),'game_sha256':report['game_sha256']}),flush=True)
    try:
        with session:
            before=prepare_restart(session.call,session.scratch)
            session.stop()
            closed_restart_snapshot(session.scratch,before)
            session.start()
            report['restart']=verify_restart(session.call,session.scratch,before)
            assert session.starts==2,session.starts
            report['process_starts']=session.starts
        assert hashlib.sha256((world/'level.dat').read_bytes()).hexdigest()==fingerprint
        report.update(passed=True,source_untouched=True)
    except BaseException as error:
        report['error']=repr(error);raise
    finally:
        output.write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({'passed':report['passed'],'result':str(output)}),flush=True)
    return report


def run_live(game, resources, ctl, create_jar, *, graphics=False, burner_visuals=False,
             client_trace=False, hold_on_failure=False):
    """Run real admission/placement/heat checks and a two-process save reload.

    Every invocation creates a new private home and world. Renderer-input tracing
    checks received client NBT; neither a trace nor a screenshot asserts pixel or
    fuel-particle parity. A failed fixture is recorded before optional inspection.
    """
    from native_check_session import NativeCheckSession
    if client_trace and not graphics:
        raise ValueError('Actual client renderer-input tracing requires --graphics')
    if hold_on_failure and not sys.stdin.isatty():
        raise ValueError('--hold-on-failure requires an interactive terminal')
    session = NativeCheckSession(game, resources, ctl, create_jar, name='burner-native',
                                 graphics=graphics, username='CreateBurner')
    # options-set changes the saved setting but cannot erase a live tutorial
    # toast. Seed the private options before the first world open instead.
    (session.scratch / 'options.txt').write_text('tutorialStep:none\nchatVisibility:2\n')
    session.env.update(HORIZON_API_DISCOVERY='http://127.0.0.1:9/', HORIZON_NO_DISCORD='1')
    result = session.scratch / 'aggregate-result.json'
    report = {'passed': False, 'game': str(session.game),
        'game_sha256': hashlib.sha256(session.game.read_bytes()).hexdigest(),
        'source': PINS['create_revision'], 'scratch': str(session.scratch),
        'world': session.world, 'username': session.username,
        'scope': run_live.__doc__, 'requires_actual_process_restart': True}
    print(json.dumps({'scratch': str(session.scratch), 'game_sha256': report['game_sha256']}), flush=True)
    try:
        with session:
            try:
                report['checks'] = run(session.call, graphics, session.log, session.scratch,
                    burner_visuals=burner_visuals, client_trace=client_trace)
                before = prepare_restart(session.call, session.scratch)
                session.stop()
                closed_restart_snapshot(session.scratch, before)
                session.start()
                report['restart'] = verify_restart(session.call, session.scratch, before)
                assert session.starts == 2, session.starts
                report['process_starts'] = session.starts
            except BaseException as error:
                report['error'] = repr(error)
                report['diagnostics'] = {}
                probes = [('freeze', ('command', 'tick freeze')), ('state', ('state',)),
                    ('screen', ('screen',)), ('inventory', ('inventory',)),
                    ('base', ('block', *BASE)),
                    ('burner', ('command', 'data get block 448 63 16')),
                    ('basin', ('command', 'data get block 448 64 16')),
                    ('mixer', ('command', 'data get block 448 66 16'))]
                for label, words in probes:
                    try:
                        report['diagnostics'][label] = session.call(*words)
                    except BaseException as failure:
                        report['diagnostics'][label] = repr(failure)
                if graphics:
                    try:
                        image = session.scratch / 'failure.png'
                        session.call('screenshot', image)
                        report['failure_image'] = str(image)
                    except BaseException as failure:
                        report['screenshot_error'] = repr(failure)
                result.write_text(json.dumps(report, indent=2) + '\n')
                session.save_transcript()
                print(json.dumps({'failed': str(result), 'socket': str(session.socket)}), flush=True)
                if hold_on_failure:
                    input('Private failure saved; press Enter to close only this client.\n')
                raise
        # A successful report includes the real second process exiting cleanly.
        report['passed'] = True
    except BaseException as error:
        report.setdefault('error', repr(error))
        raise
    finally:
        result.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'passed': report['passed'], 'result': str(result)}), flush=True)
    return report


def run_timing(game, resources, ctl, create_jar):
    """Compare83/62 and expiry boundaries using existing tick_server(false).

    The stock command-script development harness advances real ordinary server
    ticks between read-only snapshots. It adds no clock API or direct Mixer call.
    Fuel/stock are explicit canonical fixture seeds; real admission is run().
    """
    from native_check_session import NativeCheckSession
    from burner_heat_java_checks import field, items
    session = NativeCheckSession(game, resources, ctl, create_jar,
                                 name='burner-timing', graphics=False)
    script=session.scratch/'commands.jsonl';output=session.scratch/'observations.jsonl'
    report={'passed':False,'game':str(session.game),
        'game_sha256':hashlib.sha256(session.game.read_bytes()).hexdigest(),
        'source':PINS['create_revision'],'scope':run_timing.__doc__}
    operations=[];labels=[]
    def command(text,label=None):
        operations.append({'op':'cmd','cmd':text,'record':label is not None})
        if label is not None:labels.append(label)
    def tick(n):operations.append({'op':'tick','n':n})
    def setup(n):
        for pos in ['2 66 2','2 64 2','2 63 2','1 66 2','1 65 2']:
            command('setblock '+pos+' minecraft:air')
        for pos,state in [('2 63 2','create:blaze_burner[blaze=kindled,facing=north]'),
            ('2 64 2','create:basin[facing=down]'),('1 65 2','create:creative_motor[facing=up]'),
            ('1 66 2','create:cogwheel[axis=y]'),('2 66 2','create:mechanical_mixer')]:
            command('setblock '+pos+' '+state)
        command('data merge block 1 65 2 {ScrollValue:0}');tick(20)
        command('data merge block 2 64 2 {InputItems:{Size:9,Items:['
            '{Slot:0,id:"minecraft:copper_ingot",count:'+str(n)+',components:{"minecraft:custom_data":{heat_marker:71}}},'
            '{Slot:1,id:"create:zinc_ingot",count:'+str(n)+',components:{"minecraft:custom_data":{heat_marker:72}}}]},'
            'OutputItems:{Size:9,Items:[]}}')
        command('data merge block 2 63 2 {fuelLevel:1,burnTimeRemaining:1600}')
        command('setblock 2 63 2 create:blaze_burner[blaze=kindled,facing=north]')
        command('data merge block 1 65 2 {ScrollValue:32}')
    def observe(group,n):
        for i in range(n):
            tick(1)
            for key,text in [('time','time query gametime'),('mixer','data get block 2 66 2'),
                ('basin','data get block 2 64 2'),('burner','data get block 2 63 2'),
                ('smouldering','execute if block 2 63 2 create:blaze_burner[blaze=smouldering] run say source_smouldering')]:
                command(text,(group,i,key))
    command('tick unfreeze');command('gamemode creative');command('tp @s 4.5 63 4.5')
    operations.append({'op':'settle'})
    command('fill -2 62 -2 8 70 8 minecraft:air')
    command('fill -2 62 -2 8 62 8 minecraft:smooth_stone')
    setup(2);observe('brass',200)
    setup(1);observe('midcycle-before',20)
    command('data merge block 2 63 2 {burnTimeRemaining:1}')
    observe('midcycle-after',100)
    setup(2);observe('repeat-before',83)
    command('data merge block 2 63 2 {burnTimeRemaining:1}')
    observe('repeat-after',62)
    script.write_text(''.join(json.dumps(op)+'\n' for op in operations))
    session.env.update(HORIZON_COMMAND_SCRIPT=str(script),HORIZON_COMMAND_OUTPUT=str(output),
                       HORIZON_API_DISCOVERY='http://127.0.0.1:9/')
    print(json.dumps({'scratch':str(session.scratch)}),flush=True)
    try:
        with session.log.open('w') as stream:
            process=subprocess.run([str(session.game),'--headless','--resources',str(session.resources),
                '--world','CreateParity06','--seed','5','--creative','--render-distance','2'],
                cwd=session.scratch,env=session.env,stdout=stream,stderr=subprocess.STDOUT,timeout=360)
        assert process.returncode==0,(process.returncode,str(session.log))
        errors=[line for line in session.log.read_text().splitlines() if 'mod create content not loaded:' in line]
        assert not errors,('Create content registration failed before the timing fixture',errors)
        rows=[json.loads(line) for line in output.read_text().splitlines()]
        assert len(rows)==len(labels),(len(rows),len(labels))
        def text(row):return ' '.join(''.join(span[0] for span in message) for message in row['messages'])
        groups={}
        for (group,index,key),row in zip(labels,rows):
            groups.setdefault(group,{}).setdefault(index,{})[key]=text(row)
        parsed={}
        for name,indexed in groups.items():
            samples=[]
            for index in range(len(indexed)):
                row=indexed[index];times=re.findall(r'\b\d+\b',row['time']);assert len(times)==1,row
                samples.append({'time':int(times[0]),'running':_number(row['mixer'],'Running'),
                    'ticks':_number(row['mixer'],'Ticks'),'speed':_number(row['mixer'],'Speed'),
                    'inputs':items(row['basin'],'InputItems'),'outputs':items(row['basin'],'OutputItems'),
                    'smouldering':'source_smouldering' in row['smouldering'],
                    'remaining':_number(row['burner'],'burnTimeRemaining'),'raw':row})
            assert all(b['time']==a['time']+1 for a,b in zip(samples,samples[1:])),name
            parsed[name]=samples
        report['samples']=parsed
        brass=parsed['brass'];start=next(i for i,s in enumerate(brass) if s['running'] and s['ticks']==1)
        first=next(i for i,s in enumerate(brass) if s['outputs']=={'create:brass_ingot':2})
        second=next(i for i,s in enumerate(brass) if s['outputs']=={'create:brass_ingot':4})
        assert (first-start+1,second-first)==(83,62),(start,first,second)
        report.update(first_cycle_inclusive_ticks=first-start+1,repeat_ticks=second-first)
        assert all(s['outputs']==({} if i<first else {'create:brass_ingot':2 if i<second else 4}) for i,s in enumerate(brass))
        assert not brass[-1]['inputs'] and 'heat_marker' not in field(brass[-1]['raw']['basin'],'OutputItems')
        before=parsed['midcycle-before'];after=parsed['midcycle-after']
        assert before[0]['ticks']==1 and before[-1]['ticks']==20,before
        assert after[0]['running']==1 and after[0]['ticks']==20 and after[0]['smouldering'],after[0]
        assert all(s['outputs']=={} and s['inputs']=={'minecraft:copper_ingot':1,'create:zinc_ingot':1} for s in after)
        attempt=next(i for i,s in enumerate(after) if s['ticks']==22)
        assert attempt+1==63,attempt
        before=parsed['repeat-before'];after=parsed['repeat-after']
        assert before[0]['ticks']==1 and before[-1]['outputs']=={'create:brass_ingot':2},before[-1]
        assert after[0]['smouldering'] and all(s['ticks']==20 for s in after[:-1]),after
        assert after[-1]['ticks']==22 and all(s['outputs']=={'create:brass_ingot':2} and s['inputs']=={'minecraft:copper_ingot':1,'create:zinc_ingot':1} for s in after)
        report.update(passed=True,first_cycle_inclusive_ticks=83,repeat_ticks=62,
            first_expired_heat_rejection_at_cycle_tick=83,repeat_expired_heat_rejection_after=62,
            replaced_be_first_cycle_inclusive_ticks=83,
            same_be_counter84_scope='method oracle only; original command-placed kinetic BE NBT reload clears kinetic information through wasMoved',samples=parsed)
    except BaseException as error:
        report['error']=repr(error);raise
    finally:
        (session.scratch/'result.json').write_text(json.dumps(report,indent=2)+'\n')
        session.control_temp.cleanup()
        print(json.dumps({'passed':report['passed'],'result':str(session.scratch/'result.json')}),flush=True)
    return report


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['game','resources','ctl','create-jar']:parser.add_argument('--'+name,required=True)
    parser.add_argument('--mode', choices=['timing','live','all','restart'], default='timing',
        help='all runs the normal-clock regression before a fresh live world and real restart')
    parser.add_argument('--restart-from', type=Path,
        help='restart mode clones this closed .local successful live fixture; never reruns admission')
    parser.add_argument('--graphics', action='store_true')
    parser.add_argument('--client-trace', action='store_true',
        help='require the actual client burner renderer-input trace (needs graphics)')
    parser.add_argument('--burner-visuals', action='store_true',
        help='record that the selected build includes dynamic burner models; not a pixel-parity check')
    parser.add_argument('--hold-on-failure', action='store_true',
        help='keep only the failed private live client open until Enter (needs a terminal)')
    parser.add_argument('--expected-game-sha256',
        help='refuse a different binary before creating any private fixture')
    args=parser.parse_args()
    if args.client_trace and not args.graphics:
        parser.error('--client-trace requires --graphics')
    if args.hold_on_failure and not sys.stdin.isatty():
        parser.error('--hold-on-failure requires an interactive terminal')
    if args.mode=='restart' and not args.restart_from:
        parser.error('--mode restart requires --restart-from')
    if args.expected_game_sha256:
        expected=args.expected_game_sha256.lower()
        if not re.fullmatch('[0-9a-f]{64}', expected):
            parser.error('--expected-game-sha256 must contain 64 hexadecimal characters')
        actual=hashlib.sha256(Path(args.game).read_bytes()).hexdigest()
        if actual!=expected:
            parser.error('Binary SHA256 differs: '+actual)
    if args.mode in ('timing','all'):
        run_timing(args.game,args.resources,args.ctl,args.create_jar)
    if args.mode in ('live','all'):
        run_live(args.game,args.resources,args.ctl,args.create_jar,graphics=args.graphics,
            burner_visuals=args.burner_visuals,client_trace=args.client_trace,
            hold_on_failure=args.hold_on_failure)
    if args.mode=='restart':
        run_restart_only(args.game,args.resources,args.ctl,args.create_jar,args.restart_from)
