#!/usr/bin/env python3
"""Compare implemented shaft/gear/gearbox/gearshift port equations to Create.

Original method bodies are exported with JDK AST. The fixture supplies block
kinds, facing and source-face reference bases; it is not a full world oracle.
An open clutch is covered by separate split-component state tests: it has no
single local shaft basis, and its external input port is not deleted.
"""
import itertools
import json
import shutil
import subprocess
from common import ROOT, CREATE, PINS, cargo


def main():
    java,javac=shutil.which('java'),shutil.which('javac')
    work=ROOT/'.local/rotation-oracle';work.mkdir(parents=True,exist_ok=True)
    subprocess.run([javac,'-d',str(work),str(ROOT/'tools/java/ExportMethod.java')],check=True)
    template=(ROOT/'tools/java/RotationOracle.java.in').read_text()
    methods=[('MODIFIER','RotationPropagator','getRotationSpeedModifier'),('AXIS_MODIFIER','RotationPropagator','getAxisModifier'),('LARGE_LARGE','RotationPropagator','isLargeToLargeGear'),('LARGE_SMALL','RotationPropagator','isLargeToSmallCog'),('CLUTCH','transmission/ClutchBlockEntity','getRotationSpeedModifier'),('GEARSHIFT','transmission/GearshiftBlockEntity','getRotationSpeedModifier')]
    for marker,path,method in methods:
        source=work/(path.rsplit('/',1)[-1]+'.java')
        source.write_bytes(subprocess.check_output(['git','show',PINS['create_revision']+':src/main/java/com/simibubi/create/content/kinetics/'+path+'.java'],cwd=CREATE))
        body=subprocess.check_output([java,'-cp',str(work),'ExportMethod',str(source),method],text=True)
        template=template.replace('@@'+marker+'@@',body)
    source=work/'RotationOracle.java';source.write_text(template)
    subprocess.run([javac,'-d',str(work),str(source)],check=True)
    nodes=[]
    for kind,axis in itertools.product(range(8),range(3)):
        faces=range(6) if kind==3 else [0]
        for face in faces:
            for power in [0,1] if kind==6 else [0]: nodes.append((kind,axis,face,power))
    offsets=[p for p in itertools.product(range(-1,2),repeat=3) if 1<=sum(map(abs,p))<=2]
    cases=[' '.join(map(str,(*a,*b,*p))) for a,b,p in itertools.product(nodes,nodes,offsets)]
    inputs='\n'.join(cases)+'\n'
    expected=subprocess.check_output([java,'-cp',str(work),'RotationOracle'],input=inputs,text=True).splitlines()
    cargo('build','--locked','--example','rotation_probe','--target-dir',ROOT/'target/core')
    actual=subprocess.check_output([str(ROOT/'target/core/debug/examples/rotation_probe')],input=inputs,text=True).splitlines()
    assert len(actual)==len(expected)==len(cases)
    for case,a,b in zip(cases,expected,actual):
        if float(a)!=float(b):raise SystemExit(str({'case':case,'java':a,'rust':b}))
    result={'passed':len(cases),'reference':PINS['create_revision'],'scope':'source-derived rotation modifiers with fixture contexts and explicit port reference bases; open clutch graph isolation tested separately'}
    (work/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__=='__main__':main()
