#!/usr/bin/env python3
"""Test actual burner callbacks in an owned full official-apply source stage.

The supplied stage is a disposable COPY, never the stable Stage6/runtime or an
installed Launcher cache. Production code and callback wiring are not replaced.
Only a cfg(test) module is appended; source files are restored in finally.
No game window, network listener, server entry or EULA write is involved.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time
from common import ROOT, PINS, environment


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', required=True, type=Path)
    parser.add_argument('--resources', required=True, type=Path)
    parser.add_argument('--target', required=True, type=Path)
    parser.add_argument('--revision', default=PINS['horizon_revision'])
    parser.add_argument('--runtime-patch', type=Path,
                        help='record the source diff of an applied local runtime candidate')
    args = parser.parse_args()
    tree = args.stage.resolve()
    assert tree.is_relative_to(ROOT / '.local') and not args.stage.is_symlink(), tree
    # The explicit leaf is an isolated adapter copy. Reject the production
    # developer cache even though it also lives under .local.
    assert tree.parent.name.startswith('burner-adapter-'), tree
    assert (tree / 'native-crates/create/engine/Cargo.toml').is_file(), tree
    assert (tree / '.horizon-revision').read_text().strip() == args.revision
    source = tree / 'crates/horizon-client/src/game.rs'
    hooks = tree / 'crates/horizon-client/src/game/native_hooks.rs'
    remote = tree / 'crates/horizon-client/src/game/remote.rs'
    runtime_files = [tree / 'crates/horizon-client/src/game/entity.rs',
                     tree / 'crates/horizon-client/src/game/commands.rs',
                     tree / 'crates/horizon-client/src/game/persist.rs']
    hooks_text = hooks.read_text()
    pre = hooks_text.index('pub(super) fn native_interact_entity(')
    post = hooks_text.index('pub(super) fn native_item_interact_mob(')
    assert 'create_burner_interact_entity' not in hooks_text[pre:post]
    assert hooks_text.count('fn create_burner_interact_entity(') == 1
    assert 'create_burner_interact_entity' in hooks_text[post:post + 1600]
    assert 'game.spectator()' in remote.read_text()
    assert 'game.remote_mob_takes(index, hand)' in remote.read_text()
    assert 'mod burner_adapter_tests' not in source.read_text()
    before = source.read_bytes()
    scratch = Path(tempfile.mkdtemp(prefix='burner-adapter-check-', dir=ROOT / '.local'))
    report = {'passed': False, 'horizon': args.revision, 'source': PINS['create_revision'],
              'stage': str(tree), 'production_sha256': {str(p.relative_to(tree)): digest(p)
              for p in [source, hooks, remote, *runtime_files]},
              'runtime_patch_sha256': digest(args.runtime_patch) if args.runtime_patch else None,
              'test_sha256': digest(ROOT / 'tools/rust/burner_interactions_test.rs'),
              'scope': 'Actual normal server callback and actual client prediction adapter in full official-apply stage; direct helper checks are identified in the Rust fixture; no live handshake, rendered, acoustic or process-restart claim.',
              'checks': []}
    env = environment()
    target = args.target.resolve()
    assert target.is_relative_to(ROOT / '.local'), target
    env.update({'CARGO_TARGET_DIR': str(target), 'CARGO_BUILD_JOBS': '2',
                'HORIZON_TEST_RESOURCES': str(args.resources.resolve()),
                'HORIZON_NO_AUDIO': '1', 'HORIZON_LAUNCHER_NO_SELF_UPDATE': '1',
                'HORIZON_API_DISCOVERY': 'http://127.0.0.1:9'})
    for key in ['HORIZON_HOME', 'HORIZON_LAUNCHER_HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME']:
        path = scratch / key
        path.mkdir()
        env[key] = str(path)
    proof = '\n#[cfg(test)] mod burner_adapter_tests {\n#![deny(clippy::all)]\nuse super::create_port_burner_interactions::*;\ninclude!(' + json.dumps(str(ROOT / 'tools/rust/burner_interactions_test.rs')) + ');\n}\n'
    # Existing complete-mod Clippy findings stay outside this test-only result;
    # the actual probe module denies the group again. No crate is blanket allowed.
    try:
        source.write_text('#![allow(clippy::all)]\n' + before.decode() + proof)
        for name, command in [
            ('actual-game', ['cargo', 'test', '--offline', '-p', 'horizon-client', '--lib',
                             'burner_source_prediction_sound_particles_and_state', '--', '--ignored', '--nocapture']),
            ('scoped-strict-clippy', ['cargo', 'clippy', '--offline', '-p', 'horizon-client',
                                      '--lib', '--tests', '--', '-D', 'warnings', '-A', 'dead_code']),
        ]:
            start = time.monotonic()
            with (scratch / (name + '.log')).open('w') as log:
                process = subprocess.run(command, cwd=tree, env=env, stdout=log, stderr=subprocess.STDOUT)
            report['checks'].append({'check': name, 'exit': process.returncode,
                                     'seconds': time.monotonic() - start})
            report['passed'] = all(row['exit'] == 0 for row in report['checks']) and len(report['checks']) == 2
            (scratch / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
            print(name, process.returncode, scratch, flush=True)
            if process.returncode:
                raise SystemExit(process.returncode)
    finally:
        source.write_bytes(before)


if __name__ == '__main__':
    main()
