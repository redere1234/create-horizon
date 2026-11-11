#!/usr/bin/env python3
"""Canonical Depot read/save tests and actual pinned NeoForge cold-codec oracle.

Requires private reference libraries for the Java comparison and a local Horizon
source checkout for the production Rust codec. Does not launch either game.
This validates standard eight-slot buffers, not arbitrary edited handler sizes.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
from common import ROOT, environment


def function(source, name):
    start = re.search(r'(?:pub\(super\) )?fn ' + re.escape(name) + r'\(', source).start()
    brace = source.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def cases():
    result = ['{}', '{HeldItem:{Item:{id:"minecraft:iron_ingot",count:3}}}',
              '{Items:[{Slot:0b,id:"minecraft:diamond",count:99}]}']
    sizes = ['', 'Size:8,', 'Size:8b,', 'Size:9b,', 'Size:7s,', 'Size:9L,',
             'Size:1.5f,', 'Size:9.0d,', 'Size:"9",']
    slots = ['', 'Slot:0,', 'Slot:7,', 'Slot:8,', 'Slot:-1,', 'Slot:1b,',
             'Slot:2s,', 'Slot:4294967299L,', 'Slot:4.9f,', 'Slot:5.9d,',
             'Slot:-.5f,', 'Slot:-.5d,', 'Slot:"7",', 'Slot:2147483648.0d,',
             'Slot:-2147483649.0d,']
    for size in sizes:
        for slot in slots:
            result.append('{OutputBuffer:{' + size + 'Items:[{' + slot + 'id:"minecraft:gold_ingot",count:4}]}}')
    for second in ['{Slot:2,id:"minecraft:gold_ingot",count:4}', '{Slot:2}',
                   '{Slot:2,id:"minecraft:air",count:4}', '{Slot:2,id:"INVALID",count:4}']:
        result.append('{OutputBuffer:{Size:8,Items:[{Slot:2,id:"minecraft:iron_ingot",count:3},' + second + ']}}')
    for count in [1,2,16,64,99]:
        result.append('{HeldItem:{Item:{id:"minecraft:iron_ingot",count:' + str(count) + ',components:{"minecraft:custom_data":{marker:923}}}},OutputBuffer:{Size:8,Items:[{Slot:1,id:"minecraft:stone",count:' + str(count) + '}]}}')
    return result


def run(horizon, manifest):
    work = ROOT / '.local/depot-decode'
    src = work / 'probe/src'
    src.mkdir(parents=True, exist_ok=True)
    horizon = Path(horizon).resolve()
    manifest = json.loads(Path(manifest).read_text())
    (work / 'probe/Cargo.toml').write_text('[package]\nname="depot-decode-checks"\nversion="0.0.0"\nedition="2024"\n[workspace]\n[dependencies]\n' + ''.join(
        f'{name}={{path={json.dumps(str(horizon / "crates" / folder))},default-features=false}}\n'
        for name, folder in [('horizon-client-lib','horizon-client-lib'),('horizon-world','horizon-world'),('horizon-items','horizon-items')]) + 'log="0.4"\nserde_json="1"\n[patch.crates-io]\n' + ''.join(f'{name}={{path={json.dumps(str(horizon / "third_party" / name))}}}\n' for name in ['wgpu-hal','naga','libmimalloc-sys']) + '[profile.dev]\ndebug="line-tables-only"\n')
    import shutil
    shutil.copyfile(horizon / 'Cargo.lock', work / 'probe/Cargo.lock')
    runtime = (ROOT / 'mixins/create/runtime.rs').read_text()
    writer = '\n'.join(function(runtime, name) for name in ['inventory_supported','depot_field','depot_data']).replace('pub(super) ', '')
    probe = (ROOT / 'tools/rust/depot_decode_probe.rs.in').read_text().replace('@@CODEC@@',json.dumps(str(ROOT/'mixins/create/inventory_codec.rs'))).replace('@@DECODE@@',json.dumps(str(ROOT / 'mixins/create/inventory_decode.rs'))).replace('@@WRITER@@',writer).replace('@@DESTROY@@',json.dumps(str(ROOT / 'mixins/create/destroy.rs')))
    (src / 'main.rs').write_text(probe)
    env = environment()
    env['CARGO_TARGET_DIR'] = str(ROOT / '.local/fluid-render-target')
    env['CARGO_BUILD_JOBS'] = '2'
    cargo = [str(ROOT / '.tools/rust/bin/cargo')]
    tests = subprocess.run(cargo + ['test','--offline','--manifest-path',str(work / 'probe/Cargo.toml')],env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    (work / 'rust-tests.log').write_text(tests.stdout)
    if tests.returncode:
        print(tests.stdout)
        return tests.returncode
    data = cases()
    (work / 'cases.snbt').write_text('\n'.join(data) + '\n')
    rust = subprocess.run(cargo + ['run','--quiet','--offline','--manifest-path',str(work / 'probe/Cargo.toml')],input='\n'.join(data)+'\n',env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    (work / 'rust-run.log').write_text(rust.stderr)
    rust.check_returncode()
    (work / 'DepotDecodeOracle.java').write_text((ROOT / 'tools/java/DepotDecodeOracle.java.in').read_text())
    cp = ':'.join(dict.fromkeys(manifest['compile_deps'] + manifest['classpath']))
    javac = '/Applications/Android Studio.app/Contents/jbr/Contents/Home/bin/javac'
    subprocess.run([javac,'--release','21','-cp',cp,'-d',str(work),str(work / 'DepotDecodeOracle.java')],check=True)
    java = subprocess.run([str(Path(manifest['java']) / 'bin/java'),'-cp',str(work)+':'+cp,'DepotDecodeOracle'],input='\n'.join(data)+'\n',text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    (work / 'java.log').write_text(java.stdout)
    java.check_returncode()
    actual = [json.loads(s[6:]) for s in java.stdout.splitlines() if s.startswith('DEPOT ')]
    port = [json.loads(s) for s in rust.stdout.splitlines()]
    assert len(actual) == len(port) == len(data), (len(actual),len(port),len(data))
    for i,(a,b) in enumerate(zip(actual,port)):
        assert a == b, (i,data[i],a,b)
    # Guard tests use the actual destroy helper, executed against a tiny host
    # that makes every downstream mutation observable.
    guards = [('runtime.rs','depot_reacts','inventory_blocked'),('runtime.rs','right_click','inventory_blocked'),
              ('runtime.rs','tick','inventory_supported'),('runtime.rs','depot_input','inventory_supported'),
              ('interactions.rs','right_click','inventory_blocked'),('fan.rs','process_depot','inventory_blocked')]
    for file,name,guard in guards:
        assert guard in function((ROOT / 'mixins/create' / file).read_text(),name), (file,name)
    assert 'inventory_supported(entity)' in (ROOT / 'mixins/create/depot_automation.rs').read_text()
    destroy = (ROOT / 'mixins/create/destroy.rs').read_text()
    assert destroy.index('inventory_blocked') < destroy.index('create_port_belt::destroy')
    test_count = int(re.search(r'test result: ok\. (\d+) passed',tests.stdout)[1])
    report = {'passed':True,'rust_tests':test_count,'actual_neoforge_cases':len(data),'guard_source_checks':len(guards)+2,
              'scope':'cold canonical read + real save/NBT roundtrip + writer; no live game/network/restart acceptance',
              'horizon_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=horizon,text=True).strip()}
    (work / 'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    return 0

# Real-game callbacks for the next immutable native build; cold tests above
# deliberately do not claim this integration evidence before they are invoked.
DEPOT = (544, 64, 0)
RELOAD_DEPOT = (548, 64, 0)


def native_run(call, scratch):
    from native_check_session import wait_loaded
    report = {'passed': False, 'checks': [], 'scope': 'canonical command-read, unsupported refusal, and reload fixture setup'}
    scratch = Path(scratch)
    def cmd(text): return call('command', text)
    def xyz(p): return ' '.join(map(str, p))
    def data(p, path=''): return ' '.join(cmd('data get block ' + xyz(p) + ' ' + path)['chat'])
    def check(p, path):
        reply = cmd('execute if data block ' + xyz(p) + ' ' + path + ' run say depot_codec_ok')
        assert any('depot_codec_ok' in t for t in reply['chat']), (p,path,reply)
    cmd('gamemode creative'); cmd('tp @s 544.5 64 3.5'); call('wait', 8)
    wait_loaded(call, [DEPOT, RELOAD_DEPOT])
    cmd('fill 541 63 -3 551 68 5 minecraft:air')
    cmd('fill 541 63 -3 551 63 5 minecraft:smooth_stone')
    cmd('kill @e[type=minecraft:item,x=541,y=63,z=-3,dx=10,dy=6,dz=8]')
    cmd('tp @s 544.5 64 3.5'); call('wait', 8)
    player = call('state')['player']
    assert player['on_ground'] and abs(player['position'][1] - 64) < .001, player
    for p in [DEPOT, RELOAD_DEPOT]: cmd('setblock ' + xyz(p) + ' create:depot')
    canonical = ('{HeldItem:{Item:{id:"minecraft:iron_ingot",count:3,components:{"minecraft:custom_data":{marker:923}}},'
                 'Pos:.7f,Offset:.2f,Angle:87,FanProcessingType:"create:splashing",FanProcessingTime:145,TransportUnknown:42},'
                 'OutputBuffer:{Size:8,UnknownBuffer:1b,Items:[{Slot:7,id:"minecraft:gold_ingot",count:4}]},fixture_unknown:{keep:1b},'
                 'Items:[{Slot:0b,id:"minecraft:diamond",count:99}]}')
    cmd('data merge block ' + xyz(DEPOT) + ' ' + canonical)
    # A player extraction in the very next command sees the canonical slots.
    cmd('clear @s'); call('interact', *DEPOT, 'up'); call('wait', 3)
    inventory = ' '.join(cmd('data get entity @s Inventory')['chat'])
    assert 'minecraft:iron_ingot' in inventory and 'minecraft:gold_ingot' in inventory and 'marker: 923' in inventory, inventory
    assert call('inventory')['counts'] == {'minecraft:iron_ingot':3,'minecraft:gold_ingot':4}, inventory
    assert 'minecraft:diamond' not in inventory, inventory
    assert 'minecraft:iron_ingot' not in data(DEPOT), data(DEPOT)
    report['checks'].append('canonical read before next player interaction; generic Items ignored; components kept')
    # Removal is authoritative even while the generic duplicate still appears
    # in the command accessor's serialized snapshot.
    cmd('data merge block ' + xyz(DEPOT) + ' ' + canonical)
    cmd('data remove block ' + xyz(DEPOT) + ' HeldItem'); call('wait', 3)
    assert 'minecraft:iron_ingot' not in data(DEPOT), data(DEPOT)
    check(DEPOT, 'OutputBuffer.Items[{id:"minecraft:gold_ingot",count:4}]')
    cmd('data remove block ' + xyz(DEPOT) + ' OutputBuffer.Items'); call('wait', 3)
    assert 'minecraft:gold_ingot' not in data(DEPOT), data(DEPOT)
    report['checks'].append('canonical HeldItem/output removal clears live slots without resurrection')
    # An explicit edited size is preserved and ordinary break cannot destroy it.
    cmd('data merge block ' + xyz(DEPOT) + ' ' + canonical)
    cmd('data merge block ' + xyz(DEPOT) + ' {OutputBuffer:{Size:9}}')
    before = data(DEPOT); call('wait', 20); assert data(DEPOT) == before
    call('look-at', 'block', *DEPOT); call('break', *DEPOT); call('wait', 3)
    assert data(DEPOT) == before, (before,data(DEPOT))
    cmd('item replace entity @s weapon.mainhand with create:wrench')
    call('interact', *DEPOT, 'up'); call('wait', 3); assert data(DEPOT) == before
    cmd('data merge block ' + xyz(DEPOT) + ' {OutputBuffer:{Size:8}}')
    cmd('clear @s'); call('interact', *DEPOT, 'up'); call('wait', 3)
    inventory = ' '.join(cmd('data get entity @s Inventory')['chat'])
    assert 'minecraft:iron_ingot' in inventory and 'minecraft:gold_ingot' in inventory, inventory
    assert call('inventory')['counts'] == {'minecraft:iron_ingot':3,'minecraft:gold_ingot':4}, inventory
    assert 'minecraft:diamond' not in inventory, inventory
    report['checks'].append('unsupported size is opaque through ticks/break/use; restoring Size8 recovers both canonical stacks')
    cmd('data merge block ' + xyz(RELOAD_DEPOT) + ' ' + canonical)
    call('wait', 3)
    check(RELOAD_DEPOT, 'HeldItem.Item{id:"minecraft:iron_ingot",count:3}')
    check(RELOAD_DEPOT, 'OutputBuffer.Items[{id:"minecraft:gold_ingot",count:4}]')
    report.update(passed=True,fixture={'pos':list(RELOAD_DEPOT)})
    (scratch/'depot-native-result.json').write_text(json.dumps(report,indent=2)+'\n')
    return report


def native_reloaded(call, fixture):
    from native_check_session import wait_loaded
    p=fixture['pos']; xyz=' '.join(map(str,p))
    call('command', 'tp @s 548.5 64 3.5'); call('wait', 8); wait_loaded(call,[p])
    text=' '.join(call('command','data get block '+xyz)['chat'])
    for token in ['minecraft:iron_ingot','minecraft:gold_ingot','marker: 923','TransportUnknown: 42','UnknownBuffer: 1b','fixture_unknown']:
        assert token in text, (token,text)
    assert 'minecraft:diamond' not in text, text
    call('command','clear @s');call('interact',*p,'up');call('wait',3)
    inventory=' '.join(call('command','data get entity @s Inventory')['chat'])
    assert 'minecraft:iron_ingot' in inventory and 'minecraft:gold_ingot' in inventory and 'marker: 923' in inventory,inventory
    assert call('inventory')['counts'] == {'minecraft:iron_ingot':3,'minecraft:gold_ingot':4},inventory
    assert 'minecraft:diamond' not in inventory,inventory
    assert 'minecraft:iron_ingot' not in ' '.join(call('command','data get block '+xyz)['chat'])
    call('command','clear @s');call('interact',*p,'up');call('wait',3)
    assert call('inventory')['counts'] == {}, call('inventory')
    return {'passed':True,'scope':'true process restart canonical slots/components and single extraction'}


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--horizon',type=Path,default=ROOT.parent/'horizon-native-terrain-model')
    p.add_argument('--manifest',type=Path,default=ROOT/'.local/java-reference/manifest.json')
    args=p.parse_args()
    raise SystemExit(run(args.horizon,args.manifest))
