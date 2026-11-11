#!/usr/bin/env python3
"""Compare tank chase/interpolation bits with actual cached Catnip + MC classes.

No game is launched. The player-supplied original JARs remain private; the
runner compiles only our probe and calls the unchanged original class methods.
"""
import hashlib
import json
from pathlib import Path
import random
import shutil
import struct
import subprocess

from common import ROOT

JAVA = r'''import java.util.*;import net.createmod.catnip.animation.LerpedFloat;
public class FluidLevelProbe {
 public static void main(String[]args){var in=new Scanner(System.in);var out=new StringBuilder();while(in.hasNext()){
 float value=Float.intBitsToFloat(Integer.parseUnsignedInt(in.next())),target=Float.intBitsToFloat(Integer.parseUnsignedInt(in.next())),speed=Float.intBitsToFloat(Integer.parseUnsignedInt(in.next())),partial=Float.intBitsToFloat(Integer.parseUnsignedInt(in.next()));int ticks=in.nextInt();
 var f=LerpedFloat.linear().startWithValue(value).chase(target,speed,LerpedFloat.Chaser.EXP);
 for(int i=0;i<ticks;i++){f.tickChaser();out.append(Integer.toUnsignedString(Float.floatToRawIntBits(f.getValue(1)))).append(':').append(Integer.toUnsignedString(Float.floatToRawIntBits(f.getValue(partial)))).append(',');}out.append('\n');
 }System.out.print(out);}
}'''
RUST = r'''#![allow(dead_code)]
#[path=@@SOURCE@@]mod basin;use std::io::{self,BufRead};
fn main(){for line in io::stdin().lock().lines(){let line=line.unwrap();let n=line.split_whitespace().map(|n|n.parse::<u32>().unwrap()).collect::<Vec<_>>();let mut f=basin::FluidLevel{value:f32::from_bits(n[0]),target:f32::from_bits(n[1]),speed:f32::from_bits(n[2]),..Default::default()};for _ in 0..n[4]{f.tick();print!("{}:{},",f.at(1.0).to_bits(),f.at(f32::from_bits(n[3])).to_bits());}println!();}}
'''


def main():
    work = ROOT / '.local/basin-fluid-level-oracle'
    work.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ROOT / '.local/java-reference/manifest.json').read_text())
    paths = manifest['classpath'] + manifest['compile_deps']
    classpath = ':'.join(paths)
    java = str(Path(manifest['java']) / 'bin/java')
    javac = shutil.which('javac')
    if not javac:
        raise SystemExit('JDK and the isolated reference manifest are required')
    (work / 'FluidLevelProbe.java').write_text(JAVA)
    subprocess.run([javac, '--release', '21', '-cp', classpath, '-d', str(work), str(work / 'FluidLevelProbe.java')], check=True)
    (work / 'probe.rs').write_text(RUST.replace('@@SOURCE@@', json.dumps(str(ROOT / 'mixins/create/engine/src/core/basin.rs'))))
    subprocess.run([str(ROOT / '.tools/rust/bin/rustc'), '--edition', '2024', str(work / 'probe.rs'), '-o', str(work / 'probe')], check=True)
    def bits(f): return struct.unpack('I', struct.pack('f', f))[0]
    cases = [(0, 1, .25, .5, 80), (1, 0, .25, .125, 80),
             (0, .00001, .25, 1, 2), (0, .000009999, .25, .25, 2)]
    rng = random.Random(0xF10A7)
    cases += [(rng.uniform(-1, 2), rng.uniform(-1, 2), rng.choice([0, .1, .25, .5, 1]),
               rng.choice([0, .125, .5, .875, 1]), rng.randrange(1, 100)) for _ in range(2048)]
    stream = '\n'.join(' '.join(map(str, [*(bits(v) for v in row[:4]), row[4]])) for row in cases) + '\n'
    expected = subprocess.check_output([java, '-cp', str(work) + ':' + classpath, 'FluidLevelProbe'], input=stream, text=True).splitlines()
    actual = subprocess.check_output([str(work / 'probe')], input=stream, text=True).splitlines()
    (work / 'cases.txt').write_text(stream)
    (work / 'java.txt').write_text('\n'.join(expected) + '\n')
    (work / 'rust.txt').write_text('\n'.join(actual) + '\n')
    assert len(expected) == len(actual) == len(cases)
    for case, wanted, got in zip(cases, expected, actual):
        assert wanted == got, {'case': case, 'java': wanted, 'rust': got}
    relevant = [Path(p) for p in paths if 'ponder-' in Path(p).name or Path(p).name.endswith('-srg.jar')]
    result = {'passed': True, 'cases': len(cases), 'ticks': sum(c[4] for c in cases),
              'reference_jars': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in relevant},
              'scope': 'unchanged actual LerpedFloat and MC Mth, float-bit chase/interpolation; no game/render/serialization Force acceptance'}
    (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
