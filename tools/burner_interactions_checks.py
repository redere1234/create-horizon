"""Real normal-click burner lifecycle checks, matching burner_interactions_reference.

A caller owns an isolated NativeCheckSession. This runner verifies authoritative
state, inventory and normal durability; adapter_checks separately inspects local
prediction sounds/particles. It does not establish acoustic or pixel parity.
"""
import json
from pathlib import Path
import re
from common import ROOT, PINS
from native_check_session import wait_loaded

POS = (482, 63, 10)


def run(call, graphics=False, log=None, scratch=None):
    scratch = Path(scratch).resolve(); scratch.relative_to((ROOT / '.local').resolve())
    report = {'passed': False, 'source': PINS['create_revision'], 'checks': [],
              'java_reference': 'tools/burner_interactions_reference.py',
              'scope': __doc__, 'client_definitions': 'Authoritative merged fuel/capturable snapshot; cold or invalid data fails closed. Snapshot codec and reload admission are checked separately by tools/burner_sync_checks.py.'}
    trace = scratch / 'burner-interactions-transcript.jsonl'; trace.write_text('')
    result = scratch / 'burner-interactions-result.json'
    def save(): result.write_text(json.dumps(report, indent=2)+'\n')
    def ctl(*words):
        reply = call(*words)
        with trace.open('a') as stream: stream.write(json.dumps({'command': list(map(str, words)), 'reply': reply})+'\n')
        return reply
    def cmd(text): return ctl('command', text)
    def raw(text): return ' '.join(cmd(text).get('chat', []))
    def passed(name, **data): report['checks'].append({'name': name, **data}); save()
    def selected(): return raw('data get entity @s SelectedItem')
    def setup(state, item, count=1, creative=False, offhand=False):
        cmd('tick unfreeze'); ctl('wait', 7); cmd('tick freeze')
        cmd('gamemode ' + ('creative' if creative else 'survival'))
        cmd('clear @s'); cmd('setblock 482 63 11 air'); cmd('setblock 482 63 10 air')
        cmd('setblock 482 63 10 '+state)
        cmd('item replace entity @s weapon.'+('offhand' if offhand else 'mainhand')+' with '+item+' '+str(count))
        cmd('tp @s 482.5 63 13'); ctl('wait', 5)
        ctl('look-at', 'block', *POS, 'south'); ctl('wait', 3)
    def click(): ctl('mouse', 'right', 'click'); ctl('wait', 8)
    def state(): return ctl('block', *POS)['state']
    def counts(): return ctl('inventory')['counts']
    try:
        cmd('gamemode creative'); cmd('tp @s 482.5 63 13'); ctl('wait-ready', 120)
        wait_loaded(ctl, [(478, 63, 8), (490, 63, 16)])
        cmd('fill 478 62 8 490 62 16 minecraft:smooth_stone')
        cmd('fill 478 63 8 490 67 16 minecraft:air')
        setup('create:blaze_burner', 'minecraft:flint_and_steel')
        click(); assert 'create:lit_blaze_burner' in state() and 'flame_type=regular' in state(), state()
        assert re.search(r'(?:damage["\']?\s*:\s*)1\b', selected()), selected()
        passed('empty-flint-regular-wears-once', state=state(), held=selected())
        if graphics:
            image=scratch/'lit-regular-native.png';ctl('screenshot',image)
            report.setdefault('captures',[]).append(dict(path=str(image),visually_inspected=False))
        setup('create:lit_blaze_burner', 'minecraft:iron_shovel')
        click(); assert 'blaze=none' in state() and 'facing=north' in state(), state()
        assert re.search(r'(?:damage["\']?\s*:\s*)1\b', selected()), selected()
        passed('shovel-extinguish-empty-default-wears-once', state=state(), held=selected())
        setup('create:lit_blaze_burner', 'minecraft:soul_sand', 2)
        click(); assert 'flame_type=soul' in state() and counts()=={'minecraft:soul_sand':2}, (state(),counts())
        passed('soul-conversion-keeps-item', state=state(), inventory=counts())
        if graphics:
            image=scratch/'lit-soul-native.png';ctl('screenshot',image)
            report.setdefault('captures',[]).append(dict(path=str(image),visually_inspected=False))
        setup('create:lit_blaze_burner', 'minecraft:water_bucket')
        click(); cmd('tick step 2'); ctl('wait', 5)
        assert 'create:lit_blaze_burner' in state() and counts()=={'minecraft:bucket':1}, (state(),counts())
        passed('water-bucket-leaves-lit-burner', state=state(), inventory=counts())
        next_blaze='SpawnData:{entity:{id:"minecraft:blaze"}}'
        next_zombie='SpawnData:{entity:{id:"minecraft:zombie"}}'
        zombie='{weight:1,data:{entity:{id:"minecraft:zombie"}}}'
        blaze='{weight:1,data:{entity:{id:"minecraft:blaze"}}}'
        for name, nbt, count, creative, expected in [
            ('empty-potentials-use-next',next_blaze+',SpawnPotentials:[]',1,False,{'create:blaze_burner':1}),
            ('any-potential-captures',next_zombie+',SpawnPotentials:['+zombie+','+blaze+']',2,False,{'create:empty_blaze_burner':1,'create:blaze_burner':1}),
            ('creative-capture-keeps-empty',next_blaze+',SpawnPotentials:[]',1,True,{'create:empty_blaze_burner':1,'create:blaze_burner':1}),
        ]:
            setup('minecraft:spawner{'+nbt+'}', 'create:empty_blaze_burner', count, creative)
            before=raw('data get block 482 63 10')
            click(); after=raw('data get block 482 63 10')
            assert counts()==expected and before==after, (name,counts(),before,after)
            passed(name, spawner=after, inventory=counts())
        setup('minecraft:spawner{'+next_blaze+',SpawnPotentials:['+zombie+']}', 'create:empty_blaze_burner')
        click(); adjacent=ctl('block',482,63,11)
        assert adjacent['block']=='create:blaze_burner' and 'blaze=none' in adjacent['state'], adjacent
        assert counts().get('create:blaze_burner',0)==0, counts()
        passed('nonempty-potentials-never-fallback-to-next', adjacent=adjacent, inventory=counts())
        setup('minecraft:stone','create:empty_blaze_burner')
        cmd('setblock 482 63 10 air')
        cmd('kill @e[type=minecraft:item,x=478,y=62,z=8,dx=12,dy=6,dz=8]')
        cmd('summon minecraft:blaze 482.5 63 10.5 {NoAI:1b,Silent:1b,PersistenceRequired:1b,Tags:["burner_interaction_probe"]}')
        ctl('look',180,18.2); ctl('wait',5)
        assert 'burner_probe_alive' in raw('execute if entity @e[type=minecraft:blaze,tag=burner_interaction_probe] run say burner_probe_alive')
        click()
        assert counts()=={'create:blaze_burner':1}, counts()
        assert 'burner_probe_gone' in raw('execute unless entity @e[type=minecraft:blaze,tag=burner_interaction_probe] run say burner_probe_gone')
        assert 'unexpected_burner_loot' not in raw('execute if entity @e[type=minecraft:item,x=478,y=62,z=8,dx=12,dy=6,dz=8] run say unexpected_burner_loot')
        passed('living-blaze-capture-discards-without-loot',inventory=counts())
        # Source shovel deliberately uses MAINHAND break animation for either
        # stack hand. Slot-aware engine tests verify the actual event separately.
        for block,item,maximum in [('create:blaze_burner','minecraft:flint_and_steel',64),('create:lit_blaze_burner','minecraft:iron_shovel',250)]:
            setup(block,item+'[minecraft:damage='+str(maximum-1)+']',offhand=True)
            click(); assert not counts().get(item,0), counts()
            offhand=ctl('inventory')['offhand']
            assert offhand.get('item') is None, offhand
            expected='create:lit_blaze_burner' if 'flint' in item else 'blaze=none'
            assert expected in state(), state()
            passed('offhand-normal-break-'+item,state=state(),inventory=counts())
        for block,expected in [('create:blaze_burner','create:empty_blaze_burner'),('create:blaze_burner[blaze=smouldering]','create:blaze_burner'),('create:lit_blaze_burner','create:empty_blaze_burner')]:
            setup(block,'create:wrench')
            ctl('key','shift','down'); ctl('wait',4); ctl('look-at','block',*POS,'south'); ctl('wait',3)
            try: click()
            finally: ctl('release')
            assert ctl('block',*POS)['block']=='minecraft:air', state()
            assert counts()=={'create:wrench':1,expected:1}, counts()
            passed('source-sneak-wrench-'+block,inventory=counts())
        # Keep an ordinary source state for a genuine process-restart callback.
        setup('create:lit_blaze_burner[flame_type=soul]','minecraft:soul_sand',2)
        report['passed']=True; save()
        return {'pos':POS,'state':'create:lit_blaze_burner[flame_type=soul]','inventory':counts()}
    finally:
        ctl('release'); save()


def reloaded(call, fixture):
    call('command','tp @s 482.5 63 13'); call('wait-ready',120)
    wait_loaded(call,[fixture['pos']])
    block=call('block',*fixture['pos'])
    assert 'create:lit_blaze_burner' in block['state'] and 'flame_type=soul' in block['state'],block
    assert call('inventory')['counts']==fixture['inventory']
    return {'passed':True,'block':block,'inventory':fixture['inventory']}


def main():
    import argparse
    import hashlib
    from native_check_session import NativeCheckSession
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['game', 'resources', 'ctl', 'create-jar']:
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--graphics', action='store_true')
    parser.add_argument('--expected-sha')
    args = parser.parse_args()
    digest = hashlib.sha256(Path(args.game).read_bytes()).hexdigest()
    if args.expected_sha and digest != args.expected_sha:
        raise SystemExit('Game SHA256 does not match the selected build')
    session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                 name='burner-interactions-native', graphics=args.graphics)
    (session.scratch/'options.txt').write_text('tutorialStep:none\nchatVisibility:2\n')
    session.env.update(HORIZON_API_DISCOVERY='http://127.0.0.1:9/', HORIZON_NO_DISCORD='1')
    report = dict(passed=False, game_sha256=digest, scratch=str(session.scratch),
                  graphics=args.graphics)
    print(json.dumps(dict(status='starting', **report)), flush=True)
    try:
        with session:
            fixture = run(session.call, args.graphics, session.log, session.scratch)
            report['lifecycle'] = json.loads((session.scratch/'burner-interactions-result.json').read_text())
            first = session.process
            session.stop()
            assert first.returncode == 0, ('First game process failed to close', first.returncode)
            session.start()
            assert first.pid != session.process.pid
            report['restart'] = reloaded(session.call, fixture)
            report['process_pids'] = [first.pid, session.process.pid]
            second = session.process
        assert second.returncode == 0, ('Second game process failed to close', second.returncode)
        report['passed'] = True
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        output = session.scratch/'aggregate-result.json'
        output.write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps(dict(passed=report['passed'], result=str(output))), flush=True)


if __name__ == '__main__':
    main()
