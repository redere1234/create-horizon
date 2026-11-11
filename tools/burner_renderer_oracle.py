#!/usr/bin/env python3
"""Unchanged MIT Create renderShared/getBlazeModel/draw, not Flywheel Visual.

Own recording contexts capture actual Java/JOML poses, model/material choice,
fullbright and scrolling UVs. This proves the independent RendererFrame model;
it does not select the live backend or claim pixel/whole-client parity.
"""
import argparse,hashlib,itertools,json,math,os,random,subprocess
from pathlib import Path
from common import ROOT,CREATE,PINS,environment
from fan_entity_checks import EXPORTER

def run(output):
 output=Path(output);output.mkdir(parents=True,exist_ok=True)
 manifest=json.loads((ROOT/'.local/java-reference/manifest.json').read_text());java=str(Path(manifest['java'])/'bin/java');javac=str(Path(manifest['java'])/'bin/javac')
 cp=os.pathsep.join(manifest['classpath']+manifest['compile_deps']);classes=output/'classes';classes.mkdir(exist_ok=True)
 exporter=output/'ExportEntityMethod.java';exporter.write_text(EXPORTER)
 subprocess.run([javac,'--release','21','-d',str(classes),str(exporter)],check=True)
 original=subprocess.check_output(['git','show',PINS['create_revision']+':src/main/java/com/simibubi/create/content/processing/burner/BlazeBurnerRenderer.java'],cwd=CREATE)
 source=output/'BlazeBurnerRenderer.java';source.write_bytes(original)
 template=(ROOT/'tools/java/BurnerRendererOracle.java.in').read_text()
 for marker,method in [('RENDER','renderShared'),('MODEL','getBlazeModel'),('DRAW','draw')]:
  body=subprocess.check_output([java,'-cp',str(classes),'ExportEntityMethod',str(source),'BlazeBurnerRenderer',method],text=True)
  template=template.replace('@@'+marker+'@@',body)
 generated=output/'BurnerRendererOracle.java';generated.write_text(template)
 subprocess.run([javac,'--release','21','-proc:none','-cp',cp,'-d',str(classes),str(generated)],check=True)
 cargo=output/'cargo';(cargo/'src').mkdir(parents=True,exist_ok=True)
 (cargo/'Cargo.toml').write_text('[package]\nname="burner-renderer-oracle"\nversion="0.0.0"\nedition="2024"\n[workspace]\n[dependencies]\ncreate-horizon-core={path='+json.dumps(str(ROOT))+'}\n')
 (cargo/'src/main.rs').write_text((ROOT/'tools/rust/burner_renderer_probe.rs.in').read_text())
 env=environment();env['CARGO_TARGET_DIR']=str(cargo/'target')
 subprocess.run([str(ROOT/'.tools/rust/bin/cargo'),'build','--offline','--manifest-path',str(cargo/'Cargo.toml')],env=env,check=True)
 cases=[]
 for heat,animation,goggles,hat,phase in itertools.product(range(5),[0,.125,.12500002,.175],[0,1],[-1,0,1],[-12,0,12]):
  cases.append(f'{heat} {animation} 1.234 123.75 {phase} {int(heat>=2)} {goggles} {hat}')
 rng=random.Random(0xBEF411)
 for _ in range(1500):
  cases.append(f'{rng.randrange(5)} {rng.uniform(-.1,.3)} {rng.uniform(-8,8)} {rng.uniform(-10000,10000)} {rng.randrange(-500,500)} {rng.randrange(2)} {rng.randrange(2)} {rng.randrange(-1,2)}')
 payload='\n'.join(cases)+'\n';(output/'cases.txt').write_text(payload)
 want=subprocess.check_output([java,'-cp',str(classes)+os.pathsep+cp,'audit.BurnerRendererOracle'],input=payload,text=True).splitlines()
 got=subprocess.check_output([str(cargo/'target/debug/burner-renderer-oracle')],input=payload,text=True).splitlines()
 (output/'java.txt').write_text('\n'.join(want)+'\n');(output/'rust.txt').write_text('\n'.join(got)+'\n')
 assert len(want)==len(got)==len(cases)
 maximum=0.;values=0
 for case,left,right in zip(cases,want,got):
  a=left.split();b=right.split();assert len(a)==len(b),(case,len(a),len(b))
  for i,(x,y) in enumerate(zip(a,b)):
   x=float(x);y=float(y);values+=1;maximum=max(maximum,abs(x-y))
   exact=i==0 or (i-1)%22<4
   # JOML Matrix4f.rotateY reconstructs cosine from its rounded sine;
   # independent Rust sin_cos has a few-ulp difference near cardinal angles.
   # Only pose entries receive this documented bound; selectors remain exact.
   tolerance=1e-5 if (i-1)%22>=6 else 2e-7
   assert x==y if exact else math.isclose(x,y,abs_tol=tolerance,rel_tol=3e-7),(case,i,x,y)
 result={'passed':True,'source':PINS['create_revision'],'renderer_sha256':hashlib.sha256(original).hexdigest(),'cases':len(cases),'numeric_values':values,'maximum_absolute_difference':maximum,'pose_absolute_bound':1e-5,'uv_absolute_bound':2e-7,'scope':__doc__}
 (output/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=ROOT/'.local/burner-renderer-oracle');run(p.parse_args().output)
