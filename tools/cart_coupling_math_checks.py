#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare the rail correction with the pinned Java Create JAR."""
import itertools
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile

from common import PINS, ROOT
from reference_java import CREATE_SHA256, digest


JAVA = '''
import com.simibubi.create.content.contraptions.minecart.CouplingPhysics;
import java.util.Locale;
import java.util.Scanner;
import net.minecraft.world.phys.Vec3;

public class CartCouplingOracle {
    private static Vec3 vector(Scanner in) {
        return new Vec3(in.nextDouble(), in.nextDouble(), in.nextDouble());
    }

    public static void main(String[] args) {
        try (var in = new Scanner(System.in).useLocale(Locale.ROOT)) {
            while (in.hasNextDouble()) {
                Vec3 result = CouplingPhysics.followLinkOnRail(vector(in), vector(in), in.nextFloat(), vector(in));
                System.out.printf("%016x %016x %016x%n", Double.doubleToRawLongBits(result.x),
                    Double.doubleToRawLongBits(result.y), Double.doubleToRawLongBits(result.z));
            }
        }
    }
}
'''

RUST = r'''
use create_horizon_core::contraption::cart_coupling::follow_link_on_rail;
use std::io::{self, BufRead};

fn main() {
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        let mut tokens = line.split_ascii_whitespace();
        let mut scalar = || tokens.next().unwrap().parse::<f64>().unwrap();
        let link = std::array::from_fn(|_| scalar());
        let cart = std::array::from_fn(|_| scalar());
        let magnitude = scalar() as f32;
        let rail = std::array::from_fn(|_| scalar());
        let [x, y, z] = follow_link_on_rail(link, cart, magnitude, rail).map(f64::to_bits);
        println!("{x:016x} {y:016x} {z:016x}");
    }
}
'''


def samples():
    diagonal = 2**-.5
    rails = [(0, 0, 1), (1, 0, 0), (diagonal, 0, diagonal), (diagonal, 0, -diagonal), (0, 1, 0)]
    links = [(0, 0, 0), (5, 0, 0), (-5, 0, 0), (0, 5, 0), (3, 0, 4), (0, .02, 4), (1, 2, 3)]
    magnitudes = [0, .125, .5, -.5, 2, -2]
    for link, magnitude, rail in itertools.product(links, magnitudes, rails):
        yield (*link, 13, 4, 1, magnitude, *rail)
    rng = random.Random(610)
    for _ in range(512):
        link = [rng.uniform(-32, 32) for _ in range(3)]
        cart = [rng.uniform(-2**23, 2**23) for _ in range(3)]
        yield (*link, *cart, rng.uniform(-3, 3), *rng.choice(rails))


def main():
    reference = ROOT / '.local/java-reference'
    manifest = json.loads((reference / 'manifest.json').read_text())
    assert manifest['create'] == PINS['create_version'] and manifest['minecraft'] == PINS['minecraft_source_version']
    jar = reference / 'game/mods/create-1.21.1-6.0.10.jar'
    assert digest(jar) == CREATE_SHA256
    classpath = os.pathsep.join([*manifest['classpath'], *manifest['compile_deps'], str(jar)])
    jdk = Path(manifest['java']) / 'bin'
    work = Path(tempfile.mkdtemp(prefix='cart-coupling-math-', dir=ROOT / '.local'))
    java_source = work / 'CartCouplingOracle.java'
    java_source.write_text(JAVA)
    subprocess.run([str(jdk / 'javac'), '-proc:none', '-cp', classpath, '-d', str(work), str(java_source)], check=True)

    rustc = str(ROOT / '.tools/rust/bin/rustc')
    library = work / 'libcreate_horizon_core.rlib'
    engine = ROOT / 'mixins/create/engine/src/lib.rs'
    subprocess.run([rustc, '--edition=2024', '--crate-name', 'create_horizon_core', '--crate-type',
                    'rlib', str(engine), '-o', str(library)], check=True)
    probe = work / 'probe.rs'
    probe.write_text(RUST)
    subprocess.run([rustc, '--edition=2024', str(probe), '--extern', f'create_horizon_core={library}',
                    '-o', str(work / 'probe')], check=True)

    cases = [' '.join(map(str, row)) for row in samples()]
    stream = '\n'.join(cases) + '\n'
    java = subprocess.check_output([str(jdk / 'java'), '-cp', f'{work}{os.pathsep}{classpath}',
                                    'CartCouplingOracle'], cwd=work, input=stream, text=True)
    rust = subprocess.check_output([str(work / 'probe')], input=stream, text=True)
    (work / 'cases.txt').write_text(stream)
    (work / 'java.txt').write_text(java)
    (work / 'rust.txt').write_text(rust)
    expected, actual = java.splitlines(), rust.splitlines()
    assert len(expected) == len(actual) == len(cases), work
    for case, want, got in zip(cases, expected, actual):
        assert got == want, {'work': str(work), 'case': case, 'java': want, 'rust': got}
    result = dict(create_revision=PINS['create_revision'], samples=len(cases), work=str(work))
    (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
