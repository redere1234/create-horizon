#!/usr/bin/env python3
"""Compare actual native landing with recorded original Create observations.

Runs an isolated headless client through normal server /tick step movement and
real control/command paths, then performs a real exit/start for persistence.
No AABB intake helper, direct adapter invocation or existing player world.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
from common import PINS
from native_check_session import NativeCheckSession, wait_loaded
from burner_heat_java_checks import items as source_items

AT = [12, 64, 0]
MARKER = 'components:{"minecraft:custom_data":{retained:907}}'


def run(game, resources, ctl, create_jar, reference, build_result=None):
    golden = json.loads(Path(reference).read_text())
    assert golden['passed'] and golden['source'] == PINS['create_revision']
    expected = {case['name']: case for case in golden['cases']}
    revision = PINS['horizon_revision']
    if build_result:
        build = json.loads(Path(build_result).read_text())
        assert build['passed'] and Path(build['game']).resolve() == Path(game).resolve()
        revision = build['horizon']
    session = NativeCheckSession(game, resources, ctl, create_jar, name='item-contact-native', graphics=False)
    report = dict(passed=False, game=str(session.game), game_sha256=hashlib.sha256(session.game.read_bytes()).hexdigest(),
                  horizon=revision, source=PINS['create_revision'],
                  build_result_sha256=hashlib.sha256(Path(build_result).read_bytes()).hexdigest() if build_result else None,
                  original_observations_sha256=hashlib.sha256(Path(reference).read_bytes()).hexdigest(),
                  scope=__doc__, cases=[])
    if build_result: assert report['game_sha256'] == build['game_sha256']
    def save():
        (session.scratch / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        (session.scratch / 'transcript.json').write_text(json.dumps(session.transcript, indent=2) + '\n')
    def command(text): return session.call('command', text)
    def text(value): return ' '.join(command(value).get('chat', []))
    def time():
        found = re.findall(r'\b\d+\b', text('time query gametime'))
        assert len(found) == 1, found
        return int(found[0])
    def step(n):
        before = time(); command('tick step ' + str(n))
        for _ in range(100):
            after = time()
            if after >= before + n:
                assert after == before + n, (before, n, after)
                return
            session.call('wait', 2)
        raise AssertionError(('step did not complete', before, n, time()))
    def slots(pos=AT): return session.call('container', *pos)['slots']
    def inputs(machine, pos=AT):
        counts = {}
        for row in slots(pos)[:9 if machine == 'basin' else 1]:
            if row: counts[row['item']] = counts.get(row['item'], 0) + row['count']
        return counts
    def clear(): command('kill @e[type=minecraft:item,x=9,y=62,z=-3,dx=10,dy=10,dz=7]')
    def setup(machine):
        command('fill 10 64 -2 18 70 2 minecraft:air')
        command('setblock 12 64 0 create:' + machine); clear()
    def inventory(machine, slot, count, marker=True, pos=AT):
        ik, size = ('InputItems', 9) if machine == 'basin' else ('InputInventory', 1)
        ok = 'OutputItems' if machine == 'basin' else 'OutputInventory'
        value = '{Slot:' + str(slot) + ',id:"minecraft:wheat",count:' + str(count) + (',' + MARKER if marker else '') + '}'
        command('data merge block ' + ' '.join(map(str, pos)) + ' {' + ik + ':{Size:' + str(size)
                + ',Items:[' + value + ']},' + ok + ':{Size:9,Items:[]}}')
    def remainder(tag):
        selector = '@e[type=minecraft:item,tag=' + tag + ',limit=1]'
        exists = 'contact_remainder_found' in text('execute if entity ' + selector + ' run say contact_remainder_found')
        return text('data get entity ' + selector + ' Item') if exists else None
    def summon(at, item, count, marker=True, tag='contact_native'):
        command('summon minecraft:item ' + ' '.join(map(str, at))
                + ' {Tags:["' + tag + '"],PickupDelay:32767,Motion:[0d,-0.3d,0d],Item:{id:"'
                + item + '",count:' + str(count) + (',' + MARKER if marker else '') + '}}')
    def land(name, machine, at, item='minecraft:wheat', count=13, marker=True):
        summon(at, item, count, marker)
        samples = []
        case = dict(name=name, samples=samples)
        report['cases'].append(case); save()
        source = expected[name]['after']; source_rest = source['entities']
        for tick, original in enumerate(expected[name]['observation']['samples'], 1):
            step(1)
            found = inputs(machine)
            original_input = source_items(original['blocks'][0]['nbt'],
                                          'InputItems' if machine == 'basin' else 'InputInventory')
            samples.append(dict(tick=tick, inputs=found))
            save()
            assert found == original_input, (name, tick, found, original_input)
        found, rest = inputs(machine), remainder('contact_native')
        block = text('data get block 12 64 0')
        case.update(inputs=found, remainder=rest, block=block); save()
        assert found == source['input'], (name, found, source['input'])
        assert bool(rest) == bool(source_rest), (name, rest, source_rest)
        wanted = '0'
        if source_rest:
            wanted = re.search(r'\bcount:\s*(\d+)', source_rest[0]['nbt'])[1]
            assert re.search(r'\bcount:\s*' + wanted + r'\b', rest), (name, rest, wanted)
            if marker: assert re.search(r'\bretained:\s*907\b', rest), rest
        if marker and count > int(wanted):
            assert re.search(r'\bretained:\s*907\b', block), (name, block)
        if name == 'basin-distinct-components':
            assert [row['count'] if row else 0 for row in slots()[:2]] == [1,13]
    try:
        session.start(); command('tp @s 14.5 67 3.5')
        wait_loaded(session.call, [[10,64,-2],[18,64,2]])
        command('tick freeze'); command('fill 10 63 -2 18 63 2 minecraft:smooth_stone')
        for machine, at in [('basin',[12.5,64.5,.5]),('millstone',[12.5,65.1,.5])]:
            setup(machine); land(machine+'-fresh',machine,at)
            setup(machine); inventory(machine,0,63); land(machine+'-partial',machine,at)
            setup(machine); inventory(machine,0,64); land(machine+'-full',machine,at)
            setup(machine); inventory(machine,0,1,False); land(machine+'-distinct-components',machine,at)
            setup(machine); command('setblock 12 65 0 minecraft:stone_slab[type=bottom]')
            land(machine+'-separate-support',machine,[12.5,65.7,.5])
        setup('basin'); inventory('basin',5,63); land('basin-existing-after-hole','basin',[12.5,64.5,.5])
        setup('basin'); land('basin-inside-rim','basin',[12.05,64.95,.5])
        setup('basin'); land('basin-outside-center-rim','basin',[13.05,64.95,.5])
        setup('millstone'); land('millstone-base-here','millstone',[12.0,64.5,.5])
        setup('millstone'); command('setblock 12 65 0 create:millstone')
        inventory('millstone',0,64,pos=[12,65,0]); land('millstone-first-here-full-no-below-fallback','millstone',[12.0,65.5,.5])
        setup('millstone'); land('millstone-forbidden','millstone',[12.5,65.1,.5],item='minecraft:diamond_sword',count=1,marker=False)
        # Keep two independent partial transfers full +12 remainder across real process exit/start.
        setup('basin'); command('setblock 16 64 0 create:millstone'); clear()
        for machine, pos, at, tag in [('basin',AT,[12.5,64.5,.5],'contact_basin_saved'),
                                      ('millstone',[16,64,0],[16.5,65.1,.5],'contact_mill_saved')]:
            inventory(machine,0,63,pos=pos); summon(at,'minecraft:wheat',13,tag=tag)
        step(8)
        before = [(inputs(machine,pos),remainder(tag)) for machine,pos,tag in
                  [('basin',AT,'contact_basin_saved'),('millstone',[16,64,0],'contact_mill_saved')]]
        assert all(counts == {'minecraft:wheat':64} and re.search(r'\bcount:\s*12\b', rest or '') for counts,rest in before), before
        session.stop(); session.start(); command('tick freeze')
        wait_loaded(session.call, [AT,[16,64,0]])
        after = [(inputs(machine,pos),remainder(tag)) for machine,pos,tag in
                 [('basin',AT,'contact_basin_saved'),('millstone',[16,64,0],'contact_mill_saved')]]
        assert after == before, (before, after)
        report['restart'] = dict(process_starts=session.starts,before=before,after=after)
        assert session.starts == 2
        report['passed'] = True; save(); return report
    except Exception as error:
        report['error'] = repr(error); save(); raise
    finally:
        session.stop(); save(); print(json.dumps({'passed':report['passed'],'result':str(session.scratch/'result.json')}),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('game','resources','ctl','create-jar','reference'): parser.add_argument('--'+key,required=True,type=Path)
    parser.add_argument('--build-result',type=Path,help='completed immutable build receipt and binary hash')
    args=parser.parse_args();run(args.game,args.resources,args.ctl,args.create_jar,args.reference,args.build_result)
