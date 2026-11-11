#!/usr/bin/env python3
"""Pinned MIT ChainDriveBlock/Generator method bodies versus portable Rust.

Minecraft Direction and Catnip direction iteration/axis rotation run from the
private reference classpath. Authored world/property/IRotate contexts isolate
state transitions; this does not prove native callbacks, meshes, networks or pixels.
"""
import argparse
from collections import Counter
import hashlib
import itertools
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile

from common import CREATE, PINS, ROOT, environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=ROOT / '.local/java-reference/manifest.json')
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    jdk = Path(manifest['java']) / 'bin'
    classpath = os.pathsep.join(manifest['classpath'] + manifest['compile_deps'])
    work = Path(tempfile.mkdtemp(prefix='chain-drive-oracle-', dir=ROOT / '.local'))
    print(json.dumps({'work': str(work)}), flush=True)
    (work / 'result.json').write_text(json.dumps({'passed': False, 'status': 'running'}) + '\n')
    subprocess.run([str(jdk / 'javac'), '-d', str(work), str(ROOT / 'tools/java/ExportMethod.java')], check=True)
    template = (ROOT / 'tools/java/ChainDriveOracle.java.in').read_text()
    methods = [
        ('content/kinetics/chainDrive/ChainDriveBlock.java', [
            ('PLACE', 'getStateForPlacement'), ('UPDATE', 'updateShape'),
            ('WRENCH', 'getRotatedBlockState'), ('REBUILD', 'updateAfterWrenched'),
            ('CONNECTED', 'areBlocksConnected'), ('CONNECTION_AXIS', 'getConnectionAxis'),
            ('SHAFT', 'hasShaftTowards'),
        ]),
        ('content/kinetics/chainDrive/ChainDriveGenerator.java', [
            ('MODEL_X', 'getXRotation'), ('MODEL_Y', 'getYRotation'), ('MODEL_NAME', 'getModelSuffix'),
        ]),
        ('content/kinetics/base/RotatedPillarKineticBlock.java', [('PREFERRED', 'getPreferredAxis')]),
        ('content/equipment/wrench/IWrenchable.java', [('BASE_WRENCH', 'getRotatedBlockState')]),
    ]
    sources = {}
    for relative, names in methods:
        data = subprocess.check_output(['git', 'show', PINS['create_revision'] + ':src/main/java/com/simibubi/create/' + relative], cwd=CREATE)
        source = work / relative.rsplit('/', 1)[-1]
        source.write_bytes(data)
        sources[relative] = hashlib.sha256(data).hexdigest()
        for marker, name in names:
            body = subprocess.check_output([str(jdk / 'java'), '-cp', str(work), 'ExportMethod', str(source), name], text=True)
            template = template.replace('@@' + marker + '@@', body)
    assert '@@' not in template
    program = work / 'ChainDriveOracle.java'
    program.write_text(template)
    subprocess.run([str(jdk / 'javac'), '-proc:none', '-cp', classpath, '-d', str(work), str(program)], check=True)
    # Compile the actual complete engine, not a reimplementation or extracted Rust fragment.
    rustc = str(ROOT / '.tools/rust/bin/rustc')
    library = work / 'libcreate_horizon_core.rlib'
    subprocess.run([rustc, '--edition=2024', '--crate-name', 'create_horizon_core', '--crate-type', 'rlib', '-O', str(ROOT / 'mixins/create/engine/src/lib.rs'), '-o', str(library)], env=environment(), check=True)
    subprocess.run([rustc, '--edition=2024', '-O', str(ROOT / 'examples/chain_drive_probe.rs'), '--extern', 'create_horizon_core=' + str(library), '-o', str(work / 'probe')], env=environment(), check=True)
    cases = [f'U {s} {d} {other}' for s, d, other in itertools.product(range(24), range(6), range(-1, 24))]
    cases += [f'C {s} {other} {d}' for s, other, d in itertools.product(range(24), range(24), range(6))]
    cases += [f'M {s}' for s in range(24)]
    cases += [f'R {s} {d}' for s, d in itertools.product(range(24), range(6))]
    layouts = [[-1] * 6]
    for d, s in itertools.product(range(6), range(24)):
        layout = [-1] * 6
        layout[d] = s
        layouts.append(layout)
    for s, d, layout in itertools.product(range(24), range(6), layouts):
        cases.append(' '.join(map(str, ['W', s, d, *layout])))
    for look, shift, ports in itertools.product(range(6), range(2), range(64)):
        cases.append(' '.join(map(str, ['P', look, shift, ports, *([-1] * 6)])))
    for look, shift, layout in itertools.product(range(6), range(2), layouts):
        cases.append(' '.join(map(str, ['P', look, shift, 0, *layout])))
    rng = random.Random(0xC4A17)
    for _ in range(2400):
        layout = [rng.randrange(-1, 24) for _ in range(6)]
        cases.append(' '.join(map(str, ['P', rng.randrange(6), rng.randrange(2), rng.randrange(64), *layout])))
        cases.append(' '.join(map(str, ['W', rng.randrange(24), rng.randrange(6), *layout])))
    payload = '\n'.join(cases) + '\n'
    (work / 'cases.txt').write_text(payload)
    expected = subprocess.check_output([str(jdk / 'java'), '-cp', str(work) + os.pathsep + classpath, 'ChainDriveOracle'], input=payload, text=True).splitlines()
    actual = subprocess.check_output([str(work / 'probe')], input=payload, text=True).splitlines()
    assert len(expected) == len(actual) == len(cases), (len(expected), len(actual), len(cases))
    for index, (case, want, got) in enumerate(zip(cases, expected, actual)):
        if want != got:
            (work / 'mismatch.json').write_text(json.dumps({'index': index, 'case': case, 'java': want, 'rust': got}, indent=2) + '\n')
            raise AssertionError({'case': case, 'java': want, 'rust': got})
    models = []
    for case, value in zip(cases, actual):
        if not case.startswith('M '):
            continue
        code = int(case.split()[1])
        axis, first, part = ['x', 'y', 'z'][code // 8], code % 8 >= 4, ['start', 'middle', 'end', 'none'][code % 4]
        suffix, x_rotation, y_rotation = value.split()
        models.append({'state': code, 'key': f'axis={axis},axis_along_first={str(first).lower()},part={part}',
                       'model': value, 'suffix': suffix, 'x_rotation': int(x_rotation), 'y_rotation': int(y_rotation)})
    assert len(models) == 24 and len({m['state'] for m in models}) == 24
    result = {
        'passed': True, 'cases': len(cases), 'methods': sum(len(n) for _, n in methods),
        'reference': PINS['create_revision'], 'sources': sources,
        'groups': dict(Counter(case.split()[0] for case in cases)),
        'core_sha256': hashlib.sha256((ROOT / 'mixins/create/engine/src/core/chain_drive.rs').read_bytes()).hexdigest(),
        'probe_sha256': hashlib.sha256((ROOT / 'examples/chain_drive_probe.rs').read_bytes()).hexdigest(),
        'template_sha256': hashlib.sha256((ROOT / 'tools/java/ChainDriveOracle.java.in').read_bytes()).hexdigest(),
        'models': models,
        'scope': 'Unchanged AST-exported Create method bodies with actual cached Minecraft Direction and MIT Catnip Iterate/VoxelShaper. Explicit property/world/shaft contexts. Actual complete Rust engine. No native placement/update callbacks, kinetic network, imported mesh, audio, GPU or pixel-parity claim.',
    }
    (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
