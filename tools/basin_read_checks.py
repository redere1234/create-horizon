#!/usr/bin/env python3
"""Compare real Basin Game methods with an explicit historical baseline.

Headless process with CPU model resources: no window, device, existing world or
GPU. This is a native method/geometry regression, not a Java, live tick, packet
or screenshot comparison. Uses only an explicitly owned private stage/target;
restores game.rs, Cargo.toml and Cargo.lock byte for byte even after failure.
The allocation counter is a private generated dev dependency, preserving the
engine's forbid(unsafe_code). No production module or inventory codec is edited.
"""
import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from common import ROOT, environment



def run(args):
    HERE=args.scratch.resolve()
    STAGE=args.stage.resolve()
    TARGET=args.target.resolve()
    assert HERE.is_relative_to(ROOT/'.local') and STAGE.is_relative_to(ROOT/'.local')
    assert STAGE.parent.name.startswith(('ownmod-lint-','basin-read-'))
    assert TARGET.is_relative_to(ROOT/'.local')
    assert args.resources.resolve().is_relative_to(ROOT/'.local')
    assert (STAGE/'.horizon-mixins-stage.json').is_file()
    HERE.mkdir(parents=True,exist_ok=True)
    GAME=STAGE/'crates/horizon-client/src/game.rs'
    baseline=subprocess.check_output(['git','show',args.baseline_commit+':mixins/create/basin.rs'],cwd=ROOT,text=True)
    candidate_source=(ROOT/'mixins/create/basin.rs').read_text()
    runtime=(ROOT/'mixins/create/runtime.rs').read_text()
    def function(source,signature):
     start=source.index(signature);body=source.index('{',start);end=body+1;depth=1
     while depth:
      depth+=(source[end]=='{')-(source[end]=='}');end+=1
     return source[start:end]
    def compact(v):
     v=re.sub(r'//[^\n]*','',v)
     v=re.sub(r'\s+','',v)
     return re.sub(r',([\]\)}>])',r'\1',v)
    def sha(v):return hashlib.sha256(v).hexdigest()
    before=GAME.read_bytes();text=before.decode()
    module_start=text.index('pub(crate) mod create_port_basin {')
    module=function(text[module_start:],'pub(crate) mod create_port_basin {')
    for signature in ['fn restore(','fn empty_tanks(','pub(super) fn unsupported(','fn component_maximum(','pub(super) fn core_stack(','fn read_tanks(','fn draw_fluids(']:
     assert compact(function(baseline,signature))==compact(function(module,signature))==compact(function(candidate_source,signature)),signature
    stage_supported=function(text[text.index('pub(crate) mod create_port {'):],'pub(super) fn inventory_supported')
    assert compact(stage_supported)==compact(function(runtime,'pub(super) fn inventory_supported'))
    methods=[]
    for name in ['read','analog','draw']:
     old=function(baseline,'pub(super) fn '+name+'(')
     candidate=function(candidate_source,'pub(super) fn '+name+'(').replace('fn '+name+'(','fn perf_candidate_'+name+'(',1)
     assert 'entity.clone()' not in candidate and 'e.clone()' not in candidate and 'copy.items' not in candidate
     methods+=[old.replace('fn '+name+'(','fn perf_baseline_'+name+'(',1),candidate]

    allocator='''
    struct PerfAllocator;
    thread_local! {pub static PERF_RECORD:std::cell::Cell<bool>=const{std::cell::Cell::new(false)};}
    pub static PERF_ALLOCS:std::sync::atomic::AtomicU64=std::sync::atomic::AtomicU64::new(0);
    pub static PERF_BYTES:std::sync::atomic::AtomicU64=std::sync::atomic::AtomicU64::new(0);
    #[global_allocator] static PERF_ALLOCATOR:PerfAllocator=PerfAllocator;
    unsafe impl std::alloc::GlobalAlloc for PerfAllocator {
     unsafe fn alloc(&self,l:std::alloc::Layout)->*mut u8 {
      if PERF_RECORD.try_with(|v|v.get()).unwrap_or(false) {PERF_ALLOCS.fetch_add(1,std::sync::atomic::Ordering::Relaxed);PERF_BYTES.fetch_add(l.size() as u64,std::sync::atomic::Ordering::Relaxed);}
      unsafe{std::alloc::GlobalAlloc::alloc(&std::alloc::System,l)}
     }
     unsafe fn dealloc(&self,p:*mut u8,l:std::alloc::Layout){unsafe{std::alloc::GlobalAlloc::dealloc(&std::alloc::System,p,l)}}
     unsafe fn realloc(&self,p:*mut u8,l:std::alloc::Layout,n:usize)->*mut u8 {
      if PERF_RECORD.try_with(|v|v.get()).unwrap_or(false) {PERF_ALLOCS.fetch_add(1,std::sync::atomic::Ordering::Relaxed);PERF_BYTES.fetch_add(n as u64,std::sync::atomic::Ordering::Relaxed);}
      unsafe{std::alloc::GlobalAlloc::realloc(&std::alloc::System,p,l,n)}
     }
    }
    '''
    alloc_dir=HERE/'allocator'
    (alloc_dir/'src').mkdir(parents=True,exist_ok=True)
    (alloc_dir/'Cargo.toml').write_text('[package]\nname="basin-perf-alloc"\nversion="0.0.0"\nedition="2024"\nlicense="MIT"\n[workspace]\n')
    (alloc_dir/'src/lib.rs').write_text('// Private benchmark allocator, never included in production.\n'+allocator)
    manifest=STAGE/'crates/horizon-client/Cargo.toml'
    lock=STAGE/'Cargo.lock'
    originals={GAME:before,manifest:manifest.read_bytes(),lock:lock.read_bytes()}
    fixture=(ROOT/'tools/rust/basin_read_test.rs').read_text()
    injected='\n#[cfg(test)] mod basin_read_perf_tests {\nuse basin_perf_alloc::{PERF_RECORD,PERF_ALLOCS,PERF_BYTES};\n'+'\n'.join(methods)+'\n'+fixture+'\n}\n'
    assert 'mod basin_read_perf_tests' not in text
    work=Path(tempfile.mkdtemp(prefix='basin-read-game-',dir=ROOT/'.local'))
    (work/'candidate-methods.rs').write_text('\n'.join(methods))
    (work/'fixture.rs').write_text(fixture)
    report={'passed':False,'stage':str(STAGE),'target':str(TARGET),'scope':'Actual Game, current baseline read/analog/draw methods versus private borrowed candidate with unchanged stage helpers; real registered Basin/item/fluid decoding and CPU submitted vertices. No production edit, renderer backend change, GPU/image or gameplay-tick acceptance.', 'baseline_commit':args.baseline_commit,'baseline_sha256':sha(baseline.encode()),'candidate_sha256':sha(candidate_source.encode()),'stage_game_sha256':sha(before),'candidate_methods_sha256':sha('\n'.join(methods).encode()),'fixture_sha256':sha(fixture.encode()),'helper_semantic_comparison':'Bodies equal after removing whitespace, line comments and optional trailing commas; recorded helper dependencies match current production.','horizon':(STAGE/'.horizon-revision').read_text().strip()}
    env=environment();env.update({'CARGO_TARGET_DIR':str(TARGET),'CARGO_BUILD_JOBS':'2','HORIZON_TEST_RESOURCES':str(args.resources.resolve()),'HORIZON_NO_AUDIO':'1','HORIZON_LAUNCHER_NO_SELF_UPDATE':'1','HORIZON_API_DISCOVERY':'http://127.0.0.1:9','RUST_MIN_STACK':str(16*1024*1024)})
    for key in ['HORIZON_HOME','HORIZON_LAUNCHER_HOME','XDG_CONFIG_HOME','XDG_DATA_HOME']:
     p=work/key;p.mkdir();env[key]=str(p)
    try:
     # Only append the test inside the existing Basin module; unrelated source and
     # native data stay untouched. finally restores the exact original source.
     pos=module_start+len(module)-1
     GAME.write_text(text[:pos]+injected+text[pos:])
     manifest.write_bytes(originals[manifest]+('\n[dev-dependencies.basin-perf-alloc]\npath='+json.dumps(str(alloc_dir))+'\n').encode())
     command=['cargo','test','--offline','-p','horizon-client','--lib','basin_read_perf_actual_game','--','--ignored','--nocapture']
     print(json.dumps({'work':str(work)}),flush=True)
     with (work/'cargo.log').open('w') as log:
      result=subprocess.run(command,cwd=STAGE,env=env,stdout=log,stderr=subprocess.STDOUT)
     report['exit']=result.returncode
     assert result.returncode==0,str(work/'cargo.log')
     log=(work/'cargo.log').read_text()
     proof=[json.loads(line.removeprefix('BASIN_PERF_PROOF ')) for line in log.splitlines() if line.startswith('BASIN_PERF_PROOF ')]
     assert len(proof)==1 and proof[0]['actual_game_cases']==108 and proof[0]['geometry_cases']==108 and proof[0]['geometry_vertices']>0,proof
     samples=[json.loads(line.removeprefix('BASIN_PERF_SAMPLE ')) for line in log.splitlines() if line.startswith('BASIN_PERF_SAMPLE ')]
     assert len(samples)==18,len(samples)
     report.update({'actual_game':proof[0],'measurements':samples,'passed':True})
    except BaseException as error:
     report['error']=repr(error);raise
    finally:
     for path,data in originals.items():path.write_bytes(data)
     report['stage_restored']=all(path.read_bytes()==data for path,data in originals.items())
     (work/'result.json').write_text(json.dumps(report,indent=2)+'\n')
     print(json.dumps({'passed':report['passed'],'result':str(work/'result.json'),'stage_restored':report['stage_restored']}),flush=True)


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',type=Path,required=True)
    parser.add_argument('--target',type=Path,required=True)
    parser.add_argument('--resources',type=Path,required=True)
    parser.add_argument('--scratch',type=Path,default=ROOT/'.local/basin-read-perf')
    parser.add_argument('--baseline-commit',default='a7d0088')
    run(parser.parse_args())
