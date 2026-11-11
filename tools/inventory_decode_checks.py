#!/usr/bin/env python3
"""Rust-only canonical Create inventory checks; consumes recorded API outputs.

Does not read/generate Java code or require NeoForge implementation sources.
Actual native injection, automation and restart acceptance are separate checks.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
from common import ROOT, HORIZON, environment
from depot_decode_checks import function


def run(horizon):
    horizon = Path(horizon).resolve()
    work = ROOT / '.local/create-inventory-codec'
    src = work / 'probe/src'
    src.mkdir(parents=True, exist_ok=True)
    manifest = '[package]\nname="create-inventory-codec-checks"\nversion="0.0.0"\nedition="2024"\n[workspace]\n[dependencies]\n'
    manifest += ''.join(f'{name}={{path={json.dumps(str(horizon / "crates" / name))},default-features=false}}\n' for name in ['horizon-client-lib','horizon-world','horizon-items'])
    manifest += 'log="0.4"\nserde_json="1"\n[patch.crates-io]\n'
    manifest += ''.join(f'{name}={{path={json.dumps(str(horizon / "third_party" / name))}}}\n' for name in ['wgpu-hal','naga','libmimalloc-sys'])
    manifest += '[profile.dev]\ndebug="line-tables-only"\n'
    (work/'probe/Cargo.toml').write_text(manifest)
    shutil.copyfile(horizon/'Cargo.lock',work/'probe/Cargo.lock')
    runtime=(ROOT/'mixins/create/runtime.rs').read_text()
    writer='\n'.join(function(runtime,name) for name in ['inventory_supported','depot_field','depot_data']).replace('pub(super) ','')
    probe=(ROOT/'tools/rust/depot_decode_probe.rs.in').read_text().replace('@@CODEC@@',json.dumps(str(ROOT/'mixins/create/inventory_codec.rs'))).replace('@@DECODE@@',json.dumps(str(ROOT/'mixins/create/inventory_decode.rs'))).replace('@@WRITER@@',writer).replace('@@DESTROY@@',json.dumps(str(ROOT/'mixins/create/destroy.rs')))
    # The existing public probe uses a tiny game for destruction isolation.
    probe=probe.replace('pub mod create_port {','pub mod create_port {pub fn inventory_supported(e:&crate::ModBlockEntity)->bool{crate::inventory_supported(e)}',1)
    extension=(ROOT/'tools/rust/create_inventory_decode_probe.rs.in').read_text()
    for name in ['basin','millstone']:
        source=(ROOT/f'mixins/create/{name}.rs').read_text()
        adapter='\n'.join(function(source,func) for func in ['inventory','restore','data']).replace('pub(super) ','')
        extension=extension.replace('@@'+name.upper()+'@@',adapter)
    machines=(horizon/'crates/horizon-client/src/game/machines.rs').read_text()
    extension=extension.replace('@@MOVE_IN_ITEM@@',function(machines,'move_in_item'))
    packet=(ROOT/'tools/rust/inventory_packet_probe.rs.in').read_text()
    (src/'main.rs').write_text(probe+'\n'+extension+'\n'+packet)
    env=environment();env['CARGO_TARGET_DIR']=str(ROOT/'.local/fluid-render-target');env['CARGO_BUILD_JOBS']='2'
    args=[str(ROOT/'.tools/rust/bin/cargo')]
    common=['--offline','--manifest-path',str(work/'probe/Cargo.toml')]
    tests=subprocess.run(args+['test']+common,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    (work/'rust-tests.log').write_text(tests.stdout)
    if tests.returncode: print(tests.stdout);return tests.returncode
    corpus=json.loads((ROOT/'tools/data/inventory_decode_observations.json').read_text())
    assert corpus['schema_version']==1
    cases='\n'.join(case['snbt'] for case in corpus['cases'])+'\n'
    expected=[case['slots'] for case in corpus['cases']]
    actual=subprocess.run(args+['run','--quiet']+common,input=cases,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    (work/'rust-run.log').write_text(actual.stderr);actual.check_returncode()
    found=[json.loads(line) for line in actual.stdout.splitlines()]
    assert len(found)==len(expected)==len(cases.splitlines())
    for index,(wanted,got) in enumerate(zip(expected,found)): assert wanted==got,(index,cases.splitlines()[index],wanted,got)
    # Machine-consumed guarded routes: the real player break/use guards invoke
    # the generalized predicate, and generic automation refuses before dispatch.
    assert 'if !inventory_supported(entity)' in function(runtime,'tick')
    assert 'if !crate::game::create_port::inventory_supported(entity)' in function((ROOT/'mixins/create/depot_automation.rs').read_text(),'create_depot_can_place')
    for name in ['basin','millstone']:
        source=(ROOT/f'mixins/create/{name}.rs').read_text()
        for func in ['data','tick']: assert 'inventory_supported(entity)' in function(source,func),(name,func)
        assert 'inventory_blocked(game, pos)' in function(source,'right_click'),name
    report={'passed':True,'rust_tests':int(re.search(r'test result: ok\. (\d+) passed',tests.stdout)[1]),'recorded_depot_observations':len(found),'observations_fixture':'tools/data/inventory_decode_observations.json','scope':'shared cold/client codec + real ModBlockEntity merge/identity + extracted native hopper merge + ordinary writers + real save/NBT codec; injected API/live game acceptance is separate','horizon_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=horizon,text=True).strip()}
    (work/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));return 0


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--horizon',type=Path,default=HORIZON)
    raise SystemExit(run(parser.parse_args().horizon))
