#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare all single-axis rotary contact with ContinuousOBBCollider in the pinned JAR."""
import itertools
import json
import os
from pathlib import Path
import subprocess
import tempfile

from common import PINS, ROOT
from contraption_contact_oracle import responses
from reference_java import CREATE_SHA256, digest


RUST = r'''
use create_engine::{
    contraption::{contact::ContactBox, rotary_contact::rotary_contact},
    kinetics::Axis,
};
use std::io::{self, BufRead};

fn main() {
    let shapes = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, -1.0]].map(|min| ContactBox {
        min,
        max: min.map(|value| value + 1.0),
    });
    for row in io::stdin().lock().lines() {
        let row = row.expect("fixture input");
        let inputs = row.split_whitespace()
            .map(|value| value.parse::<f64>().expect("fixture coordinate"))
            .collect::<Vec<_>>();
        let [axis, angle, x, y, z, vx, vy, vz] = inputs[..] else { panic!("expected eight inputs") };
        let body = ContactBox {
            min: [x - 0.3, y, z - 0.3],
            max: [x + 0.3, y + 1.8, z + 0.3],
        };
        let axis = [Axis::X, Axis::Y, Axis::Z][axis as usize];
        let result = rotary_contact(axis, [0; 3], angle as f32, body, [vx, vy, vz], shapes, 0.6);
        let [x, y, z] = result.separation;
        println!("contact {x} {y} {z} {} {}", result.impact_fraction, u8::from(result.surface));
    }
}
'''


def main():
    reference = ROOT / '.local/java-reference'
    manifest = json.loads((reference / 'manifest.json').read_text())
    assert manifest['create'] == PINS['create_version']
    assert manifest['minecraft'] == PINS['minecraft_source_version']
    jar = reference / 'game/mods/create-1.21.1-6.0.10.jar'
    assert digest(jar) == CREATE_SHA256
    classpath = os.pathsep.join([*manifest['classpath'], *manifest['compile_deps'], str(jar)])
    jdk = Path(manifest['java']) / 'bin'
    rustc = ROOT / '.tools/rust/bin/rustc'
    work = Path(tempfile.mkdtemp(prefix='rotary-contact-oracle-', dir=ROOT / '.local'))
    java_source = Path(__file__).with_name('java') / 'RotaryContactOracle.java'
    subprocess.run([jdk / 'javac', '-proc:none', '-cp', classpath, '-d', work, java_source], check=True)
    library = work / 'libcreate_engine.rlib'
    subprocess.run([rustc, '--edition=2024', '--crate-name', 'create_engine', '--crate-type',
                    'rlib', ROOT / 'mixins/create/engine/src/lib.rs', '-o', library], check=True)
    probe = work / 'probe.rs'
    probe.write_text(RUST)
    binary = work / 'probe'
    subprocess.run([rustc, '--edition=2024', probe, '--extern', f'create_engine={library}',
                    '-o', binary], check=True)
    cases = [(*sample[:5], *sample[5]) for sample in itertools.product(
        (0, 1, 2),
        (-137.5, -90, -43.2, -9.6, 0, 4.8, 19.2, 43.2, 90, 195.5),
        (-0.36, 0.04, 0.27, 0.5, 0.78, 1.09, 1.42, 1.85, 2.21),
        (-0.77, -0.35, 0, 0.4, 0.62, 1.0, 1.24, 1.8),
        (-1.12, -0.85, -0.29, 0.28, 0.69, 1.17),
        ((0, 0, 0), (0.05, 0, -0.09), (-0.29, -0.08, 0.02), (0, -0.61, 0)),
    )]
    stream = ''.join(' '.join(map(str, case)) + '\n' for case in cases)
    java_output = subprocess.check_output([jdk / 'java', '-cp', f'{work}{os.pathsep}{classpath}',
                                           'RotaryContactOracle'], cwd=work, input=stream, text=True)
    rust_output = subprocess.check_output([binary], input=stream, text=True)
    java, rust = responses(java_output), responses(rust_output)
    assert len(java) == len(rust) == len(cases), (work, len(java), len(rust))
    tolerance = 1e-10
    errors = [dict(input=case, java=expected, rust=actual)
              for case, expected, actual in zip(cases, java, rust)
              if any(abs(a - b) > tolerance for a, b in zip(expected, actual))]
    path = work / 'result.json'
    path.write_text(json.dumps(dict(passed=not errors, create=PINS['create_revision'],
                                    cases=len(cases), tolerance=tolerance, errors=errors),
                               indent=2) + '\n')
    assert not errors, (path, errors[:4])
    print(json.dumps(dict(passed=True, result=str(path), cases=len(cases))))


if __name__ == '__main__':
    main()
