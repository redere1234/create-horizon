#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare wheel angles against the actual Catnip chaser used by Create 6.0.10."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from common import ROOT

JAVA = """import java.util.Scanner;
import net.createmod.catnip.animation.LerpedFloat;

public class FlywheelProbe {
    public static void main(String[] args) {
        var motion = LerpedFloat.linear().chase(0, 1 / 64f, LerpedFloat.Chaser.EXP);
        float angle = 0;
        var input = new Scanner(System.in);
        while (input.hasNextInt()) {
            int rpm = input.nextInt();
            motion.updateChaseTarget(rpm);
            motion.tickChaser();
            angle += motion.getValue() * 3 / 10f;
            angle %= 360;
            for (float partial : new float[] {0, .125f, .5f, .875f, 1}) {
                float result = angle + motion.getValue(partial) * 3 / 10f * partial;
                System.out.println(Float.floatToRawIntBits(result));
            }
        }
    }
}
"""

RUST = """#![allow(dead_code)]
mod kinetics {
    pub type Pos = [i32; 3];
    #[derive(Clone, Copy)]
    pub enum Axis { X, Y, Z }
    impl Axis {
        pub fn index(self) -> usize { self as usize }
    }
}
#[path=@@BASIN@@] mod basin;
#[path=@@VISUAL@@] mod visual;
use std::io::{self, Read};
fn main() {
    let mut input = String::new();
    io::stdin().read_to_string(&mut input).unwrap();
    let mut motion = visual::FlywheelMotion::default();
    for rpm in input.split_whitespace() {
        motion.tick(rpm.parse().unwrap());
        for partial in [0.0, 0.125, 0.5, 0.875, 1.0] {
            println!("{}", motion.rendered(partial).to_bits() as i32);
        }
    }
}
"""


def main():
    manifest = json.loads((ROOT / '.local/java-reference/manifest.json').read_text())
    java = Path(manifest['java']) / 'bin/java'
    javac = shutil.which('javac')
    if not javac:
        raise SystemExit('A JDK on PATH and the isolated Create reference are required')
    classpath = os.pathsep.join(manifest['classpath'] + manifest['compile_deps'])
    core = ROOT / 'mixins/create/engine/src/core'
    work = Path(tempfile.mkdtemp(prefix='flywheel-motion-', dir=ROOT / '.local'))
    source = work / 'FlywheelProbe.java'
    source.write_text(JAVA)
    subprocess.run([javac, '--release', '21', '-cp', classpath, '-d', work, source], check=True)
    probe = work / 'probe.rs'
    probe.write_text(RUST.replace('@@BASIN@@', json.dumps(str(core / 'basin.rs')))
                     .replace('@@VISUAL@@', json.dumps(str(core / 'visual.rs'))))
    rust = work / 'probe'
    subprocess.run([ROOT / '.tools/rust/bin/rustc', '--edition', '2024', probe, '-o', rust],
                   check=True)
    rpms = [0] * 4 + [32] * 80 + [256] * 96 + [-64] * 128 + [-256] * 96 + [0] * 1100
    stream = ' '.join(map(str, rpms))
    expected = subprocess.check_output(
        [java, '-cp', str(work) + os.pathsep + classpath, 'FlywheelProbe'], input=stream, text=True)
    actual = subprocess.check_output([rust], input=stream, text=True)
    for i, (left, right) in enumerate(zip(expected.splitlines(), actual.splitlines(), strict=True)):
        assert left == right, {'tick': i // 5, 'partial_index': i % 5, 'java': left, 'rust': right}
    result = dict(passed=True, ticks=len(rpms), angles=5 * len(rpms))
    (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result | {'result': str(work / 'result.json')}))


if __name__ == '__main__':
    main()
