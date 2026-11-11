#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare actor direction tests and ordered tree plans with the original JAR."""
import itertools
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile

from common import PINS, ROOT
from reference_java import CREATE_SHA256, digest


RUST = r'''
use create_horizon_core::{
    contraption::actors::{MotionTracker, Sample, saw::{TreeBlock, TreeStem, find_tree}},
    placement::Direction,
};
use std::{collections::HashMap, io::{self, BufRead}};

fn block(kind: &str) -> TreeBlock {
    let mut block = TreeBlock::default();
    match kind {
        "O" => block.stem = TreeStem::Log,
        "R" => block.stem = TreeStem::Root,
        "A" => block.attachment = true,
        "C" | "K" => block.stem = TreeStem::VerticalPlant,
        "P" | "H" => block.stem = TreeStem::Chorus,
        "M" => block.nondecaying_leaf_radius = Some(2),
        "N" => block.nondecaying_leaf_radius = Some(3),
        distance => block.leaf_distance = Some(distance.parse().unwrap()),
    }
    block
}

fn main() {
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        let mut tokens = line.split_whitespace();
        let kind = tokens.next().unwrap();
        if kind == "F" {
            let name = tokens.next().unwrap();
            let facing = Direction::ALL.into_iter().find(|direction| direction.name() == name).unwrap();
            let mut tracker = MotionTracker::default();
            let sample = Sample {
                position: [0.0; 3], facing, stalled: false, disabled: false,
                allow_stationary_first_visit: false,
            };
            tracker.sample(sample, |motion| motion, |motion| motion);
            let position = std::array::from_fn(|_| tokens.next().unwrap().parse().unwrap());
            let sample = tracker.sample(Sample { position, ..sample }, |motion| motion, |motion| motion);
            println!("{}", sample.active);
            continue;
        }
        let count = tokens.next().unwrap().parse::<usize>().unwrap();
        let mut states = HashMap::new();
        for _ in 0..count {
            let position = std::array::from_fn(|_| tokens.next().unwrap().parse().unwrap());
            states.insert(position, block(tokens.next().unwrap()));
        }
        let plan = find_tree([0; 3], block(kind), 384, 65_536,
            |position| Some(states.get(&position).copied().unwrap_or_default())).unwrap();
        for (part, positions) in [("logs", plan.logs), ("leaves", plan.leaves), ("attachments", plan.attachments)] {
            print!("{part}=");
            for [x, y, z] in positions {
                print!("{x},{y},{z};");
            }
            print!(" ");
        }
        println!();
    }
}
'''


def tree_cases():
    scenes = [
        ('O', [(0, 1, 0, 'O'), (1, 1, 0, 'O'), (1, 0, 0, 'O')]),
        ('O', [(0, 1, 0, 'O'), (1, 1, 0, 'O')]),
        ('O', [(0, 1, 0, 'O'), (1, 1, 0, '1'), (2, 1, 0, '2'), (3, 1, 0, '1'), (0, 2, 0, 'A')]),
        ('O', [(0, 1, 0, 'O'), (1, 0, 0, 'R'), (2, -1, 0, 'R'), (3, -2, 0, 'R'), (1, -1, 0, 'O')]),
        ('C', [(0, 1, 0, 'C'), (0, 2, 0, 'C'), (0, 3, 0, 'K'), (1, 2, 0, 'C')]),
        ('P', [(0, 1, 0, 'P'), (0, 2, 0, 'P'), (1, 2, 0, 'H')]),
        ('P', [(0, 1, 0, 'P'), (0, 2, 0, 'P'), (1, 1, 0, 'P'), (1, 2, 0, 'H')]),
    ]
    rng = random.Random(610)
    trunk = [(0, 1, 0), (0, 2, 0)]
    for _ in range(100):
        cells = [(*position, 'O') for position in trunk]
        for position in itertools.product(range(-3, 4), range(-1, 5), range(-3, 4)):
            if position != (0, 0, 0) and position not in trunk and rng.random() <= .15:
                cells.append((*position, rng.choice('OORAMN1234567')))
        scenes.append(('O', cells))
    return [' '.join((kind, str(len(cells)), *(' '.join(map(str, cell)) for cell in cells)))
            for kind, cells in scenes]


def main():
    reference = ROOT / '.local/java-reference'
    manifest = json.loads((reference / 'manifest.json').read_text())
    assert manifest['create'] == PINS['create_version'] and manifest['minecraft'] == PINS['minecraft_source_version']
    jar = reference / 'game/mods/create-1.21.1-6.0.10.jar'
    assert digest(jar) == CREATE_SHA256
    classpath = os.pathsep.join([*manifest['classpath'], *manifest['compile_deps'], str(jar)])
    jdk = Path(manifest['java']) / 'bin'
    work = Path(tempfile.mkdtemp(prefix='actor-reference-', dir=ROOT / '.local'))
    source = ROOT / 'tools/java/ActorOracle.java'
    subprocess.run([str(jdk / 'javac'), '-proc:none', '-cp', classpath, '-d', str(work), str(source)], check=True)

    rustc = str(ROOT / '.tools/rust/bin/rustc')
    library = work / 'libcreate_horizon_core.rlib'
    engine = ROOT / 'mixins/create/engine/src/lib.rs'
    subprocess.run([rustc, '--edition=2024', '--crate-name', 'create_horizon_core', '--crate-type',
                    'rlib', str(engine), '-o', str(library)], check=True)
    probe = work / 'probe.rs'
    probe.write_text(RUST)
    subprocess.run([rustc, '--edition=2024', str(probe), '--extern', f'create_horizon_core={library}',
                    '-o', str(work / 'probe')], check=True)

    trees = tree_cases()
    directions = [' '.join(map(str, ('F', facing, *motion)))
                  for facing in ('down', 'up', 'north', 'south', 'west', 'east')
                  for motion in itertools.product((0, .000001, .01, -.01, .125, -.125, 1, -1), repeat=3)]
    cases = trees + directions
    stream = '\n'.join(cases) + '\n'
    java = subprocess.check_output([str(jdk / 'java'), '-cp', f'{work}{os.pathsep}{classpath}',
                                    'ActorOracle'], cwd=work, input=stream, text=True)
    rust = subprocess.check_output([str(work / 'probe')], input=stream, text=True)
    (work / 'cases.txt').write_text(stream)
    (work / 'java.txt').write_text(java)
    (work / 'rust.txt').write_text(rust)
    expected = [line for line in java.splitlines() if line.startswith('logs=') or line in ('true', 'false')]
    actual = rust.splitlines()
    assert len(expected) == len(actual) == len(cases), work
    for case, want, got in zip(cases, expected, actual):
        assert want == got, {'work': str(work), 'case': case, 'java': want, 'rust': got}
    result = {'passed': True, 'create_revision': PINS['create_revision'], 'tree_plans': len(trees),
              'direction_samples': len(directions), 'work': str(work)}
    (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
