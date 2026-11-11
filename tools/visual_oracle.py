#!/usr/bin/env python3
"""Compare actual Java bodies for phase, crank interpolation, gauge target and wheel RPM.

Rendering matrices, fluid world sampling and interactions are tested in the game;
this fixture supplies only default config and the isolated method contexts.
"""
import itertools
import json
import shutil
import subprocess
from common import ROOT,CREATE,PINS,cargo

def main():
    java,javac=shutil.which('java'),shutil.which('javac')
    work=ROOT/'.local/visual-oracle';work.mkdir(parents=True,exist_ok=True)
    subprocess.run([javac,'-d',str(work),str(ROOT/'tools/java/ExportMethod.java')],check=True)
    text=(ROOT/'tools/java/VisualOracle.java.in').read_text()
    methods=[('ANGLE','base/KineticBlockEntityRenderer','getAngleForBe'),('OFFSET_TEST','base/KineticBlockEntityVisual','shouldOffset'),('OFFSET','base/KineticBlockEntityVisual','rotationOffset'),('SPEED','gauge/SpeedGaugeBlockEntity','getDialTarget'),('ANGULAR','base/KineticBlockEntity','convertToAngular'),('CRANK','crank/HandCrankBlockEntity','tick'),('CRANK_ANGLE','crank/HandCrankBlockEntity','getIndependentAngle'),('WHEEL','waterwheel/WaterWheelBlockEntity','getGeneratedSpeed')]
    for marker,path,method in methods:
        source=work/(path.rsplit('/',1)[-1]+'.java')
        source.write_bytes(subprocess.check_output(['git','show',PINS['create_revision']+':src/main/java/com/simibubi/create/content/kinetics/'+path+'.java'],cwd=CREATE))
        body=subprocess.check_output([java,'-cp',str(work),'ExportMethod',str(source),method],text=True)
        text=text.replace('@@'+marker+'@@',body)
    source=work/'VisualOracle.java';source.write_text(text);subprocess.run([javac,'-d',str(work),str(source)],check=True)
    cases=['O '+' '.join(map(str,p)) for p in itertools.product(range(3),range(-3,4),range(-3,4),range(-3,4),range(2))]
    cases += [f'A {t} {r} {o}' for t,r,o in itertools.product([0,.25,1,20,1200,24000,1000000,16777216],[-256,-32,0,16,256],[0,11.25,22.5])]
    cases += [f'S {r/8}' for r in range(-2048,2049)]
    cases += [f'C {r} {p/8}' for r,p in itertools.product([-256,-64,-32,0,32,64,256],range(9))]
    cases += [f'W {score} {size}' for score,size in itertools.product(range(-12,13),[1,2])]
    inputs='\n'.join(cases)+'\n'
    expected=subprocess.check_output([java,'-cp',str(work),'VisualOracle'],input=inputs,text=True).splitlines()
    cargo('build','--locked','--example','visual_probe','--target-dir',ROOT/'target/core')
    actual=subprocess.check_output([str(ROOT/'target/core/debug/examples/visual_probe')],input=inputs,text=True).splitlines()
    assert len(expected)==len(actual)==len(cases)
    for case,a,b in zip(cases,expected,actual):assert abs(float(a)-float(b))<0.0001,{'case':case,'java':a,'rust':b}
    result={'passed':len(cases),'reference':PINS['create_revision'],'scope':'AST-exported phase, crank smoothing/reversal/coasting, gauge targets with default config and flow-score RPM saturation'}
    (work/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))

if __name__=='__main__':main()
