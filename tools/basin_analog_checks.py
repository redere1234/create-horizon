#!/usr/bin/env python3
"""Comparator regression using extracted adapter bodies and real ModBlockEntity.

This proves the defensive native-created short-slot boundary, not a failure of
normal canonical decode (whose unsupported results still have18 slots). It does
not read or copy any canonical inventory decoder implementation.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
from common import ROOT, environment
from depot_decode_checks import function


def run(horizon, target, prove_before=False):
    horizon=Path(horizon).resolve();work=ROOT/'.local/basin-analog-checks';src=work/'probe/src';src.mkdir(parents=True,exist_ok=True)
    manifest='[package]\nname="create-basin-analog-checks"\nversion="0.0.0"\nedition="2024"\n[workspace]\n[dependencies]\n'
    manifest+=''.join(f'{name}={{path={json.dumps(str(horizon/"crates"/name))},default-features=false}}\n' for name in ['horizon-client-lib','horizon-core','horizon-world','horizon-items'])
    manifest+='[patch.crates-io]\n'+''.join(f'{name}={{path={json.dumps(str(horizon/"third_party"/name))}}}\n' for name in ['wgpu-hal','naga','libmimalloc-sys'])+'[profile.dev]\ndebug="line-tables-only"\n'
    (work/'probe/Cargo.toml').write_text(manifest);shutil.copyfile(horizon/'Cargo.lock',work/'probe/Cargo.lock')
    runtime=(ROOT/'mixins/create/runtime.rs').read_text();basin=(ROOT/'mixins/create/basin.rs').read_text();template=(ROOT/'tools/rust/basin_analog_probe.rs.in').read_text()
    for key,source,name in [('SUPPORTED',runtime,'inventory_supported'),('MAXIMUM',runtime,'stack_maximum_override'),('RESTORE',basin,'restore'),('ANALOG',basin,'analog')]:template=template.replace('@@'+key+'@@',function(source,name).replace('pub(super) ',''))
    template=template.replace('fn inventory_supported(', 'pub(crate) fn inventory_supported(')
    env=environment();env['CARGO_TARGET_DIR']=str(Path(target).resolve());env['CARGO_BUILD_JOBS']='2'
    args=[str(ROOT/'.tools/rust/bin/cargo'),'test','--offline','--manifest-path',str(work/'probe/Cargo.toml')]
    (src/'main.rs').write_text(template)
    tests=subprocess.run(args,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT);(work/'rust-tests.log').write_text(tests.stdout)
    if tests.returncode:print(tests.stdout);return tests.returncode
    before=False
    if prove_before:
        guard='    if !crate::game::create_port::inventory_supported(e) {\n        return;\n    }\n'
        assert template.count(guard)==1
        (src/'main.rs').write_text(template.replace(guard,''))
        old=subprocess.run(args,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT);(work/'before-guard.log').write_text(old.stdout)
        before=old.returncode!=0 and 'range end index 9 out of range for slice of length 0' in old.stdout
        assert before,old.stdout
        (src/'main.rs').write_text(template)
    report={'passed':True,'rust_test_groups':3,'native_created_unsupported_cases':16,'normal_cases':4,'unrelated_case':1,'before_guard_panic_reproduced':before,'scope':__doc__,'horizon_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=horizon,text=True).strip()}
    (work/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));return 0


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--horizon',type=Path,required=True);parser.add_argument('--target',type=Path,required=True);parser.add_argument('--prove-before',action='store_true');args=parser.parse_args()
    raise SystemExit(run(args.horizon,args.target,args.prove_before))
