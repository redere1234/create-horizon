#!/usr/bin/env python3
"""Real Horizon BlockState/registry and declared-content placement-port regression.

The current and historical production wrappers execute unchanged with a small
authored world accessor. Original source shaft contracts are represented by the
existing engine Node::shaft_port. No full Game, Java server, GPU or rendering claim.
"""
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from burner_material_checks import function
from common import PINS, ROOT, environment


def run(args):
    horizon = args.horizon.resolve()
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=horizon, text=True).strip()
    if revision != PINS['horizon_revision']:
        raise ValueError('Use the pinned Horizon checkout for actual registry types')
    target = args.target.resolve()
    target.relative_to((ROOT / '.local').resolve())
    work = Path(tempfile.mkdtemp(prefix='placement-ports-', dir=ROOT / '.local'))
    print(json.dumps({'work': str(work)}), flush=True)
    path = 'mixins/create/placement_runtime.rs'
    current = (ROOT / path).read_text()
    old = subprocess.check_output(['git', 'show', args.baseline + ':' + path], cwd=ROOT, text=True)
    owns = subprocess.check_output(['git', 'show', args.baseline + ':mixins/create/runtime.rs'], cwd=ROOT, text=True)
    source = (ROOT / 'tools/rust/placement_ports_probe.rs.in').read_text()
    for marker, body in {
        'STATE_AXIS': function(current, 'fn state_axis('),
        'STATE_PORT': function(current, 'fn state_shaft_port('),
        'LEVEL_AXIS': function(current, 'fn level_axis('),
        'LEVEL_PORTS': function(current, 'pub(super) fn level_ports('),
        'OLD_AXIS': function(old, 'fn level_axis('),
        'OLD_PORTS': function(old, 'pub(super) fn level_ports('),
        'OWNS': function(owns, 'pub(super) fn owns('),
    }.items():
        source = source.replace('@@' + marker + '@@', body)
    assert '@@' not in source
    # level_axis is called by wheel placement as well as this port wrapper.
    source = source.replace('fn level_axis(', '#[allow(dead_code)] fn level_axis(', 1)
    probe = work / 'probe'
    (probe / 'src').mkdir(parents=True)
    (probe / 'src/main.rs').write_text(source)
    manifest = '[package]\nname="create-placement-ports-checks"\nversion="0.0.0"\nedition="2024"\n[workspace]\n[dependencies]\n'
    manifest += f'horizon-world={{path={json.dumps(str(horizon / "crates/horizon-world"))}}}\n'
    manifest += f'create-engine={{path={json.dumps(str(ROOT / "mixins/create/engine"))}}}\nserde_json="1"\n'
    manifest += '[profile.dev]\ndebug="line-tables-only"\n'
    (probe / 'Cargo.toml').write_text(manifest)
    shutil.copyfile(horizon / 'Cargo.lock', probe / 'Cargo.lock')
    rows = []
    content_hashes = {}
    for path in sorted((ROOT / 'content/data/create/horizon/block').glob('*.json')):
        data = path.read_bytes()
        content_hashes[path.name] = hashlib.sha256(data).hexdigest()
        declaration = json.loads(data)
        assert declaration['template'] == 'minecraft:glass', (path, 'Explicitly add template states before extending this test')
        props = declaration.get('state_properties', {})
        values = [['false', 'true'] if value['type'] == 'boolean' else value['values'] for value in props.values()]
        for combo in itertools.product(*values):
            rows.append({'name': 'create:' + path.stem, 'properties': dict(zip(props, combo))})
    rows.append({'name': 'example:unknown', 'properties': {'axis': 'y'}})
    rows.append({'name': 'minecraft:stone', 'properties': {}})
    (work / 'cases.json').write_text(json.dumps(rows))
    env = environment()
    env.update(CARGO_TARGET_DIR=str(target), CARGO_BUILD_JOBS='2')
    report = {'passed': False, 'scope': __doc__, 'horizon': revision, 'baseline': args.baseline,
              'placement_runtime_sha256': hashlib.sha256(current.encode()).hexdigest(),
              'content_sha256': content_hashes, 'commands': []}

    def command(words, name, **kwargs):
        report['commands'].append({'command': list(map(str, words)), 'log': str(work / name)})
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        done = subprocess.run(list(map(str, words)), env=env, text=True, capture_output=True, **kwargs)
        (work / name).write_text(done.stdout + done.stderr)
        if done.returncode:
            raise RuntimeError(f'Inspect {work / name}')
        return done.stdout

    cargo = ROOT / '.tools/rust/bin/cargo'
    common = ['--offline', '--manifest-path', probe / 'Cargo.toml']
    output = command([cargo, 'run', '--quiet', *common], 'run.log', input=json.dumps(rows))
    report.update(json.loads(output))
    command([cargo, 'clippy', *common, '--all-targets', '--', '-D', 'warnings'], 'clippy.log')
    report['passed'] = True
    (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': True, 'work': str(work), 'states': report['states'],
                      'face_cases': report['face_cases'], 'old_wrong_cases': report['old_wrong_cases']}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--horizon', type=Path, required=True)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--baseline', default='d34abf3')
    run(parser.parse_args())


if __name__ == '__main__':
    main()
