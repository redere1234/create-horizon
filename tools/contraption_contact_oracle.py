#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare axis-aligned separation with ContinuousOBBCollider in the pinned JAR."""
import itertools
import json
import os
from pathlib import Path
import subprocess
import tempfile

from common import PINS, ROOT
from reference_java import CREATE_SHA256, digest


RUST = r'''
use create_engine::contraption::contact::{ContactBox, linear_overlap_response};
use std::io::{self, BufRead};

fn main() {
    let shapes = [
        ContactBox { min: [0.0, 0.375, 0.375], max: [0.75, 0.625, 0.625] },
        ContactBox { min: [0.75, 0.0, 0.0], max: [1.0, 1.0, 1.0] },
        ContactBox { min: [1.0, 0.0, 0.0], max: [2.0, 1.0, 1.0] },
    ];
    for row in io::stdin().lock().lines() {
        let row = row.expect("fixture input");
        let center = row.split_whitespace()
            .map(|value| value.parse::<f64>().expect("coordinate"))
            .collect::<Vec<_>>();
        let [x, y, z] = center[..] else { panic!("expected three coordinates") };
        let body = ContactBox {
            min: [x - 0.3, y, z - 0.3],
            max: [x + 0.3, y + 1.675, z + 0.3],
        };
        let [x, y, z] = linear_overlap_response(body, &shapes, 0.6).unwrap_or([0.0; 3]);
        println!("contact {x} {y} {z}");
    }
}
'''


def responses(output):
    return [tuple(map(float, row.split()[1:])) for row in output.splitlines()
            if row.startswith('contact ')]


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
    work = Path(tempfile.mkdtemp(prefix='contact-oracle-', dir=ROOT / '.local'))

    source = Path(__file__).resolve().with_name('java') / 'ContactOracle.java'
    subprocess.run([jdk / 'javac', '-proc:none', '-cp', classpath, '-d', work, source], check=True)
    library = work / 'libcreate_engine.rlib'
    engine = ROOT / 'mixins/create/engine/src/lib.rs'
    subprocess.run([rustc, '--edition=2024', '--crate-name', 'create_engine', '--crate-type',
                    'rlib', engine, '-o', library], check=True)
    probe = work / 'probe.rs'
    probe.write_text(RUST)
    binary = work / 'probe'
    subprocess.run([rustc, '--edition=2024', probe, '--extern', f'create_engine={library}',
                    '-o', binary], check=True)

    cases = list(itertools.product(
        (-0.35, -0.25, 0, 0.2, 0.35, 0.45, 0.6, 0.7, 0.8, 1.0, 1.2, 1.5, 1.8, 2.05, 2.3),
        (-0.05, 0, 0.1, 0.4, 0.55, 0.62, 0.99, 1.0, 1.01),
        (0.05, 0.35, 0.45, 0.5, 0.55, 0.65, 0.95),
    ))
    stream = ''.join(' '.join(map(str, case)) + '\n' for case in cases)
    java_output = subprocess.check_output([jdk / 'java', '-cp', f'{work}{os.pathsep}{classpath}',
                                           'ContactOracle'], cwd=work, input=stream, text=True)
    rust_output = subprocess.check_output([binary], input=stream, text=True)
    java, rust = responses(java_output), responses(rust_output)
    assert len(java) == len(rust) == len(cases) == 945, (work, len(java), len(rust))
    tolerance = 1e-10
    errors = [dict(body=case, java=expected, rust=actual)
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
