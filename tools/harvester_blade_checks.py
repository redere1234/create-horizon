#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare moving tool phases with Flywheel actors in the pinned JAR."""
import argparse
import itertools
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile

from common import PINS, ROOT
from reference_java import CREATE_SHA256, digest

PROBE = r'''
use create_horizon_core::{
    contraption::actors::{Spin, animation_speed, harvester::Blade, points_backwards},
    placement::Direction,
};
use std::io::{self, BufRead};

fn main() {
    let drill = std::env::args().nth(1).as_deref() == Some("drill");
    let mut blade = Blade::default();
    let mut head = Spin::default();
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        let mut words = line.split_whitespace();
        let facing = words.next().unwrap();
        let facing = Direction::ALL.into_iter().find(|d| d.name() == facing).unwrap();
        let [x, y, z, a, b, c]: [f64; 6] =
            std::array::from_fn(|_| words.next().unwrap().parse().unwrap());
        let stalled = words.next() == Some("1");
        let disabled = words.next() == Some("1");
        let distance = (x * x + y * y + z * z).sqrt();
        let active = !disabled && !points_backwards([a, b, c], facing);
        if drill {
            head.advance(if active { animation_speed(distance, stalled) / 20.0 } else { 0.0 });
            println!("{}", head.angle(0.5));
        } else {
            blade.tick(distance, active && !stalled);
            println!("{}", blade.angle(0.5));
        }
    }
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--drill', action='store_true')
    args = parser.parse_args()
    tool = 'drill' if args.drill else 'harvester'
    reference = ROOT / '.local/java-reference'
    manifest = json.loads((reference / 'manifest.json').read_text())
    assert manifest['create'] == PINS['create_version']
    jar = reference / 'game/mods/create-1.21.1-6.0.10.jar'
    assert digest(jar) == CREATE_SHA256
    out = Path(tempfile.mkdtemp(prefix='harvester-blade-', dir=ROOT / '.local'))
    cp = os.pathsep.join([str(out), *manifest['classpath'], *manifest['compile_deps'], str(jar)])
    jdk = Path(manifest['java']) / 'bin'
    subprocess.run([jdk / 'javac', '-proc:none', '-cp', cp, '-d', out,
                    ROOT / 'tools/java/HarvesterBladeOracle.java'], check=True)

    rustc = ROOT / '.tools/rust/bin/rustc'
    library = out / 'libcreate_horizon_core.rlib'
    subprocess.run([rustc, '--edition=2024', '--crate-name', 'create_horizon_core', '--crate-type', 'rlib',
                    ROOT / 'mixins/create/engine/src/lib.rs', '-o', library], check=True)
    (out / 'probe.rs').write_text(PROBE)
    subprocess.run([rustc, '--edition=2024', out / 'probe.rs', '--extern',
                    f'create_horizon_core={library}', '-o', out / 'probe'], check=True)

    rng = random.Random(610)
    cases = []
    for facing, (stall, disabled) in itertools.product(
            ('north', 'south', 'east', 'west', 'up', 'down') if args.drill else
            ('north', 'south', 'east', 'west'), itertools.product((0, 1), repeat=2)):
        for i in range(100):
            motion = [rng.uniform(-2, 2) for _ in range(3)] if i else [0.0, 0.0, 0.0]
            relative = [rng.uniform(-1, 1) for _ in range(3)]
            cases.append(' '.join(map(str, (facing, *motion, *relative, stall, disabled))))
    stream = '\n'.join(cases) + '\n'
    java = subprocess.check_output([jdk / 'java', '-cp', cp, 'HarvesterBladeOracle', tool],
                                   text=True, input=stream, cwd=out)
    rust = subprocess.check_output([out / 'probe', tool], text=True, input=stream)
    (out / 'inputs.txt').write_text(stream)
    (out / 'java.txt').write_text(java)
    (out / 'rust.txt').write_text(rust)
    expected = [float(line.split()[-1]) for line in java.splitlines() if len(line.split()) == 3]
    actual = list(map(float, rust.splitlines()))
    assert len(expected) == len(actual) == len(cases), out
    for case, want, got in zip(cases, expected, actual):
        assert abs(want-got) < 1e-5, (case, want, got, out)
    result = dict(passed=True, tool=tool, observations=len(cases), directory=str(out))
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
