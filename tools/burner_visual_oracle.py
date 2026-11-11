#!/usr/bin/env python3
"""Unchanged Create methods with actual player-supplied Catnip/Mth/RNG dependencies.

Checks numerical animation, specifically the retained Flywheel BlazeBurnerVisual
backend, source particle events and RNG continuation. Actual runtime backend
selection is separate; this is not a full client or an image comparison.
"""
import argparse
import itertools
import json
import math
import os
from pathlib import Path
import random
import subprocess
from common import CREATE, PINS, ROOT, environment
from fan_entity_checks import EXPORTER


def cases():
    result=[]
    rng=random.Random(0xB1A2E6)
    for direction,phase,initial in itertools.product(range(6),[-12,-1,0,1,12,25],[0,1]):
        phases=[]
        # Covers no render on some ticks, multiple renders without a tick, retained
        # rods/flames on kind changes, head model threshold, goggles and hat lifetime.
        for heat,valid,stock in [(1,0,0),(3,1,0),(4,1,0),(2,1,0),(0,0,0),(0,1,1),(4,0,0),(1,0,0)]:
            for step in range(18):
                phases.append(','.join(map(str,[2 if step==17 else step%5!=0 and 1 or 0,heat,valid,step%4<2 and 1 or 0,step%6<4 and 1 or 0,stock,
                    step*.75-7,rng.choice([0,.125,.5,.999999,1]),rng.uniform(-100,100),rng.uniform(-100,100),step%7==0 and 1 or 0])))
        result.append(f'S {direction} {phase} {initial} '+ ' '.join(phases))
    for heat,empty,seed in itertools.product(range(5),[0,1],range(160)):
        result.append(f'P {heat} {seed} {empty}')
    for soul,seed in itertools.product([0,1],range(160)):
        result.append(f'B {soul} {seed}')
    for kind,heat,seed,pos in itertools.product(['A','L'],range(5),range(64),[(7,64,-11),(16777217,-16777217,0)]):
        if kind=='L' and heat>1:continue
        result.append(f'{kind} {heat} {seed} '+' '.join(map(str,pos)))
    return result


def run(args):
    manifest=json.loads(args.reference_manifest.read_text())
    if manifest['minecraft']!='1.21.1':raise ValueError('pinned 1.21.1 dependency manifest required')
    work=args.output.resolve();work.mkdir(parents=True,exist_ok=True)
    args.horizon=args.horizon.resolve()
    java_binary=str(Path(manifest['java'])/'bin/java')
    classes=work/'classes';classes.mkdir(exist_ok=True)
    cp=os.pathsep.join(manifest['compile_deps']+manifest['classpath'])
    exporter=work/'ExportEntityMethod.java';exporter.write_text(EXPORTER)
    subprocess.run([args.javac,'--release','21','-d',str(classes),str(exporter)],check=True)
    source=(ROOT/'tools/java/BurnerVisualOracle.java.in').read_text()
    for marker,owner,method in [('ANIMATION','BlazeBurnerBlockEntity','tickAnimation'),('PARTICLES','BlazeBurnerBlockEntity','spawnParticles'),
                              ('BURST','BlazeBurnerBlockEntity','spawnParticleBurst'),('MODEL','BlazeBurnerRenderer','getBlazeModel'),
                              ('VISUAL','BlazeBurnerVisual','animate'),('FLAME','BlazeBurnerVisual','setupFlameInstance'),('DELETE','BlazeBurnerVisual','_delete'),
                              ('AMBIENT','BlazeBurnerBlock','animateTick'),('LIT','LitBlazeBurnerBlock','animateTick')]:
        path=f'src/main/java/com/simibubi/create/content/processing/burner/{owner}.java'
        original=work/f'{owner}.java'
        original.write_bytes(subprocess.check_output(['git','show',PINS['create_revision']+':'+path],cwd=CREATE))
        body=subprocess.check_output([java_binary,'-cp',str(classes),'ExportEntityMethod',str(original),owner,method],text=True)
        source=source.replace('@@'+marker+'@@',body)
    java=work/'BurnerVisualOracle.java';java.write_text(source)
    subprocess.run([args.javac,'--release','21','-cp',cp,'-d',str(classes),str(java)],check=True)
    core=ROOT/'mixins/create/engine/src/core'
    modules=''.join(f'#[path={json.dumps(str(core/(name+".rs")))}] mod {name};\n' for name in ['kinetics','placement','transport','fan','burner','burner_visual'])
    modules+=f'#[path={json.dumps(str(core/"particles.rs"))}] mod particle_rules;\n'
    modules+=f'#[path={json.dumps(str(args.horizon/"crates/horizon-core/src/geometry/trig.rs"))}] mod trig;\n'
    rust=work/'probe.rs';rust.write_text(modules+(ROOT/'tools/rust/burner_ambient_probe.rs.in').read_text()+(ROOT/'mixins/create/burner_animate.rs').read_text()+(ROOT/'tools/rust/burner_visual_probe.rs.in').read_text())
    binary=work/'probe'
    subprocess.run([str(ROOT/'.tools/rust/bin/rustc'),'--edition=2024','-Awarnings',str(rust),'-o',str(binary)],env=environment(),check=True)
    records=cases();payload='\n'.join(records)+'\n'
    want=subprocess.check_output([java_binary,'-cp',str(classes)+os.pathsep+cp,'audit.BurnerVisualOracle'],input=payload,text=True).splitlines()
    got=subprocess.check_output([str(binary)],input=payload,text=True).splitlines()
    (work/'cases.txt').write_text(payload)
    (work/'java.txt').write_text('\n'.join(want)+'\n')
    (work/'rust.txt').write_text('\n'.join(got)+'\n')
    assert len(want)==len(got)==len(records)
    maximum=0.0;floats=0
    for case,a,b in zip(records,want,got):
        a=a.split();b=b.split();assert len(a)==len(b),(case[:200],len(a),len(b))
        for i,(x,y) in enumerate(zip(a,b)):
            x=float(x);y=float(y);difference=abs(x-y);maximum=max(maximum,difference);floats+=1
            if case.startswith('S '):
                exact=i%16 in [4,7,8,10,11]
                equal=x==y if exact else math.isclose(x,y,abs_tol=2e-6,rel_tol=2e-7)
            elif case.startswith(('A ','L ')):
                count=int(a[0]);sound_at=1+count*8
                exact=i==0 or i==len(a)-1 or (i<sound_at and (i-1)%8 in [0,7]) or i==sound_at
                equal=x==y if exact else math.isclose(x,y,abs_tol=1e-7,rel_tol=2e-14)
            else:
                exact=i==0 or i==len(a)-1 or (i-1)%7==0
                equal=x==y if exact else math.isclose(x,y,abs_tol=2e-12,rel_tol=2e-14)
            assert equal,(case[:200],i,x,y,difference)
    # Separate source-only instance-disposal proof: unchanged _delete and animate
    # must dispose every recorded instance exactly once, including a visual
    # recreation that leaves the client BE/chaser values alive. Rust's portable
    # Visual owns values, not renderer handles; no GPU allocation claim follows.
    disposal=['D '+' '.join(map(str,c)) for c in itertools.product(range(5),[0,1],[0,1],[0,1])]
    disposed=subprocess.check_output([java_binary,'-cp',str(classes)+os.pathsep+cp,'audit.BurnerVisualOracle'],input='\n'.join(disposal)+'\n',text=True).splitlines()
    assert len(disposed)==len(disposal)
    for case,line in zip(disposal,disposed):
        allocated,deleted=map(int,line.split());assert allocated>0 and allocated==deleted,(case,line)
    (work/'disposal-cases.txt').write_text('\n'.join(disposal)+'\n')
    (work/'disposal-java.txt').write_text('\n'.join(disposed)+'\n')
    result={'passed':True,'cases':len(records),'source_only_disposal_cases':len(disposal),'sequence_frames':72*144,'numeric_values':floats,'maximum_absolute_difference':maximum,
            'create_revision':PINS['create_revision'],'renderer_backend':'Flywheel BlazeBurnerVisual; live backend selection is not proved','scope':'eight unchanged Java animation/particle methods plus source-only Visual._delete disposal cases; actual Catnip animation/angle helpers plus Mth/Vec3/RandomSource; native ambient effect requests before providers; inherited cross-call sampler/provider RNG coupling, rendered images and whole-client parity are not claimed'}
    (work/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-manifest',type=Path,default=ROOT/'.local/java-reference/manifest.json')
    parser.add_argument('--javac',default='/Applications/Android Studio.app/Contents/jbr/Contents/Home/bin/javac')
    parser.add_argument('--horizon',type=Path,default=ROOT.parent/'horizon-native-terrain-model')
    parser.add_argument('--output',type=Path,default=ROOT/'.local/burner-visual-oracle')
    run(parser.parse_args())
