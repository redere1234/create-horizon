#!/usr/bin/env python3
"""Run real item-owner/machine tests in a leased full official-woven stage.

Only cfg(test) modules are appended, then game.rs is restored byte for byte.
No gameplay substitution, trait registration, window or GPU is involved. Source
AST mapping, original-Java observations and rendered/two-process acceptance are
separate evidence levels.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from common import ROOT, PINS, environment

TEST_FILTERS = ['source_item_contacts_actual_owned_game_and_remote',
                'mixer_deferred_scheduling_actual_game', 'mixer_reload_actual_game_and_client_rng']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(stage, resources, target, clippy=False, runtime_patch=None, build_result=None, fixtures_dir=None,
        material_injection=None, only=None):
    stage, resources, target = map(lambda p: Path(p).resolve(), (stage, resources, target))
    assert stage.is_relative_to(ROOT / '.local') and target.is_relative_to(ROOT / '.local')
    assert (stage / '.horizon-mixins-stage.json').is_file()
    revision = PINS['horizon_revision']
    if build_result:
        build = json.loads(Path(build_result).read_text())
        assert build['passed'] and Path(build['stage_cache']).resolve() == stage
        revision = build['horizon']
    assert (stage / '.horizon-revision').read_text().strip() == revision
    source = stage / 'crates/horizon-client/src/game.rs'
    hooks = stage / 'crates/horizon-client/src/game/native_hooks.rs'
    movement = stage / 'crates/horizon-client/src/game/item_contacts.rs'
    assert 'fn create_item_after_vertical_collision(' in hooks.read_text()
    assert 'if mod_api::mods().is_empty()' not in movement.read_text()
    before = source.read_bytes()
    assert 'mod item_contact_adapter_proof' not in before.decode()
    work = Path(tempfile.mkdtemp(prefix='item-contact-adapter-', dir=ROOT / '.local'))
    tests = ['tools/rust/item_contact_test.rs', 'tools/rust/mixer_schedule_test.rs',
             'tools/rust/mixer_reload_test.rs']
    if material_injection:
        tests.append('tools/rust/burner_material_test.rs')
    snapshots = {}
    (work / 'tests').mkdir()
    for name in tests:
        snapshot = work / 'tests' / Path(name).name
        origin = Path(fixtures_dir) / Path(name).name if fixtures_dir else ROOT / name
        shutil.copyfile(origin, snapshot)
        snapshots[name] = snapshot
    report = dict(passed=False, horizon=revision, create=PINS['create_revision'],
                  stage=str(stage), target=str(target),
                  build_result_sha256=sha(Path(build_result)) if build_result else None,
                  runtime_patch_sha256=sha(Path(runtime_patch)) if runtime_patch else None,
                  production_sha256={str(p.relative_to(stage)): sha(p) for p in (source, hooks, movement)},
                  test_sha256={name: sha(snapshots[name]) for name in tests},
                  scope='Full official-woven Game/Remote active item owner plus ordinary machine callbacks; no Java, rendered, acoustic or two-process acceptance claim',
                  checks=[])
    modified = before.decode()
    marker = 'pub(crate) mod create_port_mixer {'
    assert modified.count(marker) == 1
    additions = '\n'.join('#[cfg(test)] mod ' + name + ' { include!('
                           + json.dumps(str(snapshots[path])) + '); }'
                           for name, path in [('contact_schedule_proof', tests[1]), ('contact_reload_proof', tests[2])])
    modified = modified.replace(marker, marker + '\n' + additions, 1)
    if material_injection:
        marker = 'pub(crate) mod create_port_burner_presentation {'
        assert modified.count(marker) == 1
        injection = Path(material_injection).read_text().replace(
            str(ROOT / tests[3]), str(snapshots[tests[3]]))
        helper = work / 'tests/material-test-only-injection.rs'
        helper.write_text(injection)
        report['material_injection_sha256'] = sha(helper)
        modified = modified.replace(marker, marker + '\n' + injection, 1)
    modified += '\n#[cfg(test)] mod item_contact_adapter_proof {\ninclude!(' + json.dumps(str(snapshots[tests[0]])) + ');\n}\n'
    env = environment()
    env.update(CARGO_TARGET_DIR=str(target), CARGO_BUILD_JOBS='2',
               RUST_MIN_STACK='33554432',
               HORIZON_TEST_RESOURCES=str(resources), HORIZON_NO_AUDIO='1',
               HORIZON_LAUNCHER_NO_SELF_UPDATE='1', HORIZON_API_DISCOVERY='http://127.0.0.1:9')
    for key in ['HORIZON_HOME', 'HORIZON_LAUNCHER_HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME']:
        (work / key).mkdir(); env[key] = str(work / key)
    try:
        source.write_text(modified)
        commands = [(name, ['cargo', 'test', '--offline', '--locked', '-p', 'horizon-client',
                            '--lib', name, '--', '--ignored', '--nocapture']) for name in
                    TEST_FILTERS if only is None or name == only]
        if clippy:
            commands.append(('full-stage-strict-clippy', ['cargo', 'clippy', '--offline', '--locked',
                             '-p', 'horizon-client', '--lib', '--tests', '--', '-D', 'warnings']))
        failed = 0
        for name, command in commands:
            start = time.monotonic()
            with (work / (name + '.log')).open('w') as log:
                process = subprocess.run(command, cwd=stage, env=env, stdout=log, stderr=subprocess.STDOUT)
            report['checks'].append(dict(check=name, exit=process.returncode, seconds=time.monotonic() - start))
            (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
            print(name, process.returncode, work, flush=True)
            failed = failed or process.returncode
        report['passed'] = failed == 0
        return failed
    finally:
        source.write_bytes(before)
        report['stage_restored'] = source.read_bytes() == before
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'passed': report['passed'], 'restored': report['stage_restored'],
                          'result': str(work / 'result.json')}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('stage', 'resources', 'target'):
        parser.add_argument('--' + key, required=True, type=Path)
    parser.add_argument('--clippy', action='store_true', help='run strict checks for the complete injected stage')
    parser.add_argument('--runtime-patch', type=Path, help='record a narrowly applied local runtime candidate, distinct from the pinned binary')
    parser.add_argument('--build-result', type=Path, help='completed immutable developer build receipt, independent of later working-tree pins')
    parser.add_argument('--fixtures-dir', type=Path, help='read fixture basenames from an already captured private directory')
    parser.add_argument('--material-injection', type=Path, help='optional cfg(test)-only Burner baseline helpers; compile material test with the same Game executable')
    parser.add_argument('--only', choices=TEST_FILTERS, help='rerun only an unresolved filter after a fixture-only correction')
    args = parser.parse_args()
    raise SystemExit(run(args.stage, args.resources, args.target, args.clippy, args.runtime_patch,
                        args.build_result, args.fixtures_dir, args.material_injection, args.only))
