#!/usr/bin/env python3
"""Real Game datapack reload, retained recipe, comparator and client emit RNG.

Uses a caller-leased official native-mod stage, restores exact files in finally,
and opens only private resources/homes. No native performance build or GPU.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time
from common import ROOT, environment
from burner_sync_checks import module
from depot_decode_checks import function


def run(stage,resources,target,prove_before=False):
    stage=Path(stage).resolve();stage.relative_to(ROOT/'.local');target=Path(target).resolve();target.relative_to(ROOT/'.local')
    source=stage/'crates/horizon-client/src/game.rs';before=source.read_bytes();work=Path(tempfile.mkdtemp(prefix='mixer-reload-check-',dir=ROOT/'.local'))
    game=before.decode();native=ROOT/'mixins/create'
    game=game.replace(function(game,'inventory_supported'),function((native/'runtime.rs').read_text(),'inventory_supported'),1)
    game=module(game,'create_port_basin',(native/'basin.rs').read_text())
    mixer=(native/'mixer.rs').read_text()
    proof='\n#[cfg(test)] mod proof { include!('+json.dumps(str(ROOT/'tools/rust/mixer_reload_test.rs'))+'); }\n'
    def injected(body):return '#![allow(clippy::all)]\n'+module(game,'create_port_mixer','#![deny(clippy::all)]\n'+body+proof)
    env=environment();env.update(CARGO_TARGET_DIR=str(target),CARGO_BUILD_JOBS='2',CARGO_INCREMENTAL='0',RUST_MIN_STACK='33554432',HORIZON_TEST_RESOURCES=str(Path(resources).resolve()),HORIZON_NO_AUDIO='1',HORIZON_LAUNCHER_NO_SELF_UPDATE='1',HORIZON_API_DISCOVERY='http://127.0.0.1:9')
    for key in ['HORIZON_HOME','HORIZON_LAUNCHER_HOME','XDG_CONFIG_HOME','XDG_DATA_HOME']:
        path=work/key;path.mkdir();env[key]=str(path)
    args=['cargo','test','--offline','-p','horizon-client','--lib','mixer_reload_actual_game_and_client_rng','--','--include-ignored','--nocapture']
    report={'passed':False,'stage':str(stage),'target':str(target),'before_sha256':hashlib.sha256(before).hexdigest(),'checks':[],'scope':__doc__,'retired_decoder_scope':'No decoder implementation is copied or altered; the proof seeds real native entities directly and does not exercise the leased stage save decoder.'}
    def invoke(name,command):
        started=time.monotonic()
        with (work/(name+'.log')).open('w')as log:result=subprocess.run(command,cwd=stage,env=env,stdout=log,stderr=subprocess.STDOUT)
        report['checks'].append({'name':name,'exit':result.returncode,'seconds':time.monotonic()-started,'log':str(work/(name+'.log'))})
        print(name,result.returncode,work,flush=True);return result.returncode
    print(json.dumps({'work':str(work),'target':str(target)}),flush=True)
    try:
        source.write_text(injected(mixer))
        assert invoke('actual-game',args)==0
        if prove_before:
            stale=mixer.replace('generation.set(generation.get().wrapping_add(1))','generation.set(generation.get())')
            assert stale!=mixer
            source.write_text(injected(stale));code=invoke('before-reload-invalidation',args)
            assert code!=0 and 'new lookup retained the pre-reload tag/recipe' in (work/'before-reload-invalidation.log').read_text()
            start=mixer.index('pub(super) fn client_tick(');wrong=mixer[:start]+mixer[start:].replace('game.particles.level_random().next_float()','game.world.random.next_float()')
            assert wrong!=mixer
            source.write_text(injected(wrong));code=invoke('before-client-rng',args)
            assert code!=0 and 'emission must advance ClientLevel.random' in (work/'before-client-rng.log').read_text()
        source.write_text(injected(mixer))
        assert invoke('actual-game-restored',args)==0
        assert invoke('clippy',['cargo','clippy','--offline','-p','horizon-client','--lib','--tests','--','-D','warnings','-A','dead_code'])==0
        report['passed']=True
    finally:
        source.write_bytes(before);report['stage_restored']=source.read_bytes()==before
        (work/'result.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({'passed':report['passed'],'restored':report['stage_restored'],'result':str(work/'result.json')}),flush=True)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['stage','resources','target']:p.add_argument('--'+key,required=True,type=Path)
    p.add_argument('--prove-before',action='store_true');a=p.parse_args();run(a.stage,a.resources,a.target,a.prove_before)
