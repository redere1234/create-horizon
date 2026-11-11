#!/usr/bin/env python3
"""Compare default/bulk held-item routing, press RPM and head motion to Create.

Method bodies come from the pinned Java source through the JDK AST exporter.
The context models one deterministic recipe; item components/world IO are tested
by the actual Horizon smoke scenarios, not by these simplified Java classes.
"""
import json
import shutil
import subprocess
from common import ROOT, CREATE, PINS, cargo


def main():
    java,javac=shutil.which('java'),shutil.which('javac')
    work=ROOT/'.local/processing-oracle';work.mkdir(parents=True,exist_ok=True)
    subprocess.run([javac,'-d',str(work),str(ROOT/'tools/java/ExportMethod.java')],check=True)
    template=(ROOT/'tools/java/ProcessingOracle.java.in').read_text()
    base='src/main/java/com/simibubi/create/content/kinetics/press/'
    for marker,filename,method in [('HELD','BeltPressingCallbacks.java','whenItemHeld'),('SPEED','PressingBehaviour.java','getRunningTickSpeed'),('HEAD','PressingBehaviour.java','getRenderedHeadOffset')]:
        source=work/filename
        source.write_bytes(subprocess.check_output(['git','show',PINS['create_revision']+':'+base+filename],cwd=CREATE))
        body=subprocess.check_output([java,'-cp',str(work),'ExportMethod',str(source),method],text=True)
        template=template.replace('@@'+marker+'@@',body)
    source=work/'ProcessingOracle.java';source.write_text(template)
    subprocess.run([javac,'-d',str(work),str(source)],check=True)
    cases=[f'D {count} {bulk}' for count in range(1,65) for bulk in range(2)]
    cases += [f'S {rpm/4}' for rpm in range(-4096,4097)]
    cases += [f'H {tick/4}' for tick in range(961)]
    inputs='\n'.join(cases)+'\n'
    expected=subprocess.check_output([java,'-cp',str(work),'ProcessingOracle'],input=inputs,text=True).splitlines()
    cargo('build','--locked','--example','processing_probe','--target-dir',ROOT/'target/core')
    actual=subprocess.check_output([str(ROOT/'target/core/debug/examples/processing_probe')],input=inputs,text=True).splitlines()
    assert len(expected)==len(actual)==len(cases)
    for case,a,b in zip(cases,expected,actual):
        equal=abs(float(a)-float(b))<1e-6 if case.startswith('H') else a==b
        assert equal,{'case':case,'java':a,'rust':b}
    result={'passed':len(cases),'reference':PINS['create_revision'],'scope':'AST-exported belt item routing (counts 1..64, bulk off/on), press speed and head curve; deterministic recipe/context stubs'}
    (work/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__=='__main__':main()
