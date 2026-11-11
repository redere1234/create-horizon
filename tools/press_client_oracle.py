#!/usr/bin/env python3
"""Compare PressingBehaviour client state, interpolation and effect requests.

Requires the private reference_java prepared dependency manifest and pinned
Create checkout. Java bodies are AST-extracted without substitutions; authored
world/NBT/item/admission contexts are explicit. This does not establish packet
lifecycle, actual particle admission, sound, GPU, or cross-client pixel parity.
"""
import hashlib,itertools,json,os,random,subprocess,sys
from pathlib import Path
from common import CREATE, PINS, ROOT, environment
from basin_oracle import EXPORT

# These contexts isolate read/start/client tick/math and particle request
# semantics. Native receipt, limiter behavior and GPU rendering need separate
# integration evidence. Original source bodies stay private under .local.
JAVA = (ROOT / 'tools/java/PressClientOracle.java.in').read_text()

def main():
    import argparse, tempfile
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=ROOT / '.local/java-reference/manifest.json')
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    JDK = Path(manifest['java']) / 'bin'
    CP = os.pathsep.join([*manifest['classpath'], *manifest['compile_deps']])
    WORK = Path(tempfile.mkdtemp(prefix='press-client-oracle-', dir=ROOT / '.local'))
    print(json.dumps({'work': str(WORK)}), flush=True)
    (WORK/'BasinExport.java').write_text(EXPORT)
    subprocess.run([str(JDK/'javac'),'-d',str(WORK),str(WORK/'BasinExport.java')],check=True)
    source=subprocess.check_output(['git','show',PINS['create_revision']+':src/main/java/com/simibubi/create/content/kinetics/press/PressingBehaviour.java'],cwd=CREATE)
    path=WORK/'PressingBehaviour.java';path.write_bytes(source)
    program=JAVA
    methods=[('READ','read',3),('START','start',1),('TICK','tick',0),('SPEED','getRunningTickSpeed',0),('HEAD','getRenderedHeadOffset',1),('SPAWN','spawnParticles',0),('NORMAL2','makePressingParticleEffect',2),('NORMAL3','makePressingParticleEffect',3),('COMPACT','makeCompactingParticleEffect',2),('WORLD','applyInWorld',0),('BASIN','applyOnBasin',0),('INWORLD','inWorld',0),('ONBASIN','onBasin',0)]
    for marker,name,argc in methods:
        body=subprocess.check_output([str(JDK/'java'),'-cp',str(WORK),'BasinExport',str(path),name,str(argc)],text=True)
        program=program.replace('@@'+marker+'@@',body)
    (WORK/'PressClientOracle.java').write_text(program)
    subprocess.run([str(JDK/'javac'),'-proc:none','-cp',CP,'-d',str(WORK),str(WORK/'PressClientOracle.java')],check=True)
    rustc = str(ROOT / '.tools/rust/bin/rustc')
    library = WORK / 'libcreate_horizon_core.rlib'
    subprocess.run([rustc, '--edition=2024', '--crate-name', 'create_horizon_core',
                    '--crate-type', 'rlib', '-O', str(ROOT / 'mixins/create/engine/src/lib.rs'),
                    '-o', str(library)], env=environment(), check=True)
    subprocess.run([rustc, '--edition=2024', '-O', str(ROOT / 'tools/rust/press_client_probe.rs'),
                    '--extern', 'create_horizon_core=' + str(library), '-o', str(WORK/'probe')],
                   env=environment(), check=True)
    import struct
    bits=lambda f:struct.unpack('<I',struct.pack('<f',f))[0]
    cases=[]
    def row(op='T',rpm=32.0,running=1,prev=0,ticks=0,mode=0,finished=0,virtual=0,attached=1,n=1,partial=0.5,initial=0,packet=(1,1,120,2,2),seed=923,particle_level=0):
        return ' '.join(map(str,[op,seed,bits(rpm),running,prev,ticks,mode,finished,virtual,attached,n,bits(partial),initial,*packet,particle_level]))
    # Every ordinary interval endpoint, both sides of pause/retraction, and
    # the original client counter continuing past240 pending a server packet.
    for ticks,partial in itertools.product(range(-241,501),[0.0,0.5,1.0]):cases.append(row(ticks=ticks,prev=ticks-4,n=0,partial=partial))
    for ticks,rpm,virtual,attached,n in itertools.product([-2147483648,-121,-120,-119,0,116,119,120,121,159,160,239,240,241,2147483647],[0.0,-0.0,1.0,-32.0,32.0,512.0,float('nan'),float('inf'),-float('inf')],[0,1],[0,1],[1,2]):
        cases.append(row(ticks=ticks,prev=7,rpm=rpm,virtual=virtual,attached=attached,n=n,initial=2))
    rng=random.Random(0xB617)
    for _ in range(1600):
        partial=struct.unpack('<f',struct.pack('<I',rng.getrandbits(32)))[0]
        cases.append(row(ticks=rng.randrange(-2**31,2**31),prev=rng.randrange(-2**31,2**31),partial=partial,n=0,mode=rng.randrange(3),running=rng.randrange(2),finished=rng.randrange(2)))
    for op,mode,finished,initial,n,packetmode,count,packetfinished in itertools.product(['R','L'],range(3),[0,1],[0,2],[1,2],range(3),[0,1,2],[0,1]):
        cases.append(row(op=op,mode=mode,finished=finished,initial=initial,n=n,packet=(1,packetfinished,120,packetmode,count),seed=0x3955+len(cases)))
    for mode,finished,initial in itertools.product(range(3),[0,1],[0,2]):cases.append(row(op='S',ticks=-120,prev=120,finished=finished,initial=initial,n=mode))
    # Admission can consume the same level RNG between source requests.
    # Explicit platform context: Decreased's nextInt(3), checked separately
    # against the real native ParticleEngine before claiming adapter parity.
    for mode,count,repeats,level,seed in itertools.product(range(3),[1,2,4],[1,2],[0,1],range(7)):
        cases.append(row(op='R',n=repeats,packet=(1,0,120,mode,count),seed=seed,particle_level=level))
    payload='\n'.join(cases)+'\n'
    expected=subprocess.check_output([str(JDK/'java'),'-cp',str(WORK)+os.pathsep+CP,'PressClientOracle'],input=payload,text=True).splitlines()
    actual=subprocess.check_output([str(WORK/'probe')],input=payload,text=True).splitlines()
    assert len(expected)==len(actual)==len(cases),(len(expected),len(actual),len(cases))
    for index,(case,want,got) in enumerate(zip(cases,expected,actual)):
        if want!=got:
            (WORK/'mismatch.json').write_text(json.dumps({'index':index,'case':case,'java':want,'rust':got},indent=2)+'\n')
            raise AssertionError({'index':index,'case':case,'java':want[:1000],'rust':got[:1000]})
    report={'passed':True,'cases':len(cases),'methods':len(methods),'source':PINS['create_revision'],'core_sha256':hashlib.sha256((ROOT/'mixins/create/engine/src/core/press_client.rs').read_bytes()).hexdigest(),'oracle_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'scope':'Unchanged13 Create method bodies; actual cached public Minecraft Mth/RandomSource and MIT Catnip VecHelper runtime calls. Actual complete Rust engine library. Explicit world/NBT/item and Decreased admission contexts; no Java particle constructor implementation. NaN payloads compared by NaN class. No native packet lifecycle/render/GPU or pixel parity claim.'}
    (WORK/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
if __name__=='__main__':main()
