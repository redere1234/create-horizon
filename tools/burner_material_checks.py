#!/usr/bin/env python3
"""Actual Game CPU draw regression for the observed burner OBJ shade contract.

Uses the owned private stage/target and player's imported models. The previous
and candidate draw functions execute through real native terrain-model helpers.
No GPU/window, source instance mutation, original assets in public output, or
pixel-parity claim. game.rs is restored exactly even after a failed check.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from common import ROOT, PINS, environment

JAR_SHA256 = 'ef87fe5709f1ba1f5b8bb20a2925b5afb4669e178fd6d8bf10c167759eefe37a'


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            value.update(block)
    return value.hexdigest()


def function(source, signature):
    start = source.index(signature)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def reference(path):
    source = json.loads(path.read_text())
    assert source['passed'] and source['source'] == PINS['create_revision']
    assert len(source['models']['parts']) == 14
    off = {'create:block/blaze_burner/' + name for name in
           ('rods_small', 'rods_large', 'superheated_rods_small', 'superheated_rods_large', 'flame')}
    for row in source['models']['parts']:
        is_off = row['id'] in off
        assert row['shade_true'] == (0 if is_off else row['quad_count']), row
        assert row['colors'] == ['ffffffff'], row
        assert all(material['cardinal_lighting'] == ('OFF' if is_off else 'ENTITY')
                   for material in row['public_flywheel_materials']), row
    for case in source['cases']:
        observed = case['state']['burner_render_observation']
        assert observed['renderer_calls'] == 0 and observed['visual_frames'] > 0
    return source


def run_prebuilt(args):
    """Run a captured cfg(test) executable; never weave, compile or edit a stage."""
    binary, snapshot = args.test_binary.resolve(), args.snapshot.resolve()
    for path in (binary, snapshot, args.reference.resolve(), args.resources.resolve()):
        path.relative_to((ROOT / '.local').resolve())
    build = json.loads(snapshot.read_text())
    assert build['passed'] and build['native_files']['burner_presentation.rs']
    reference(args.reference)
    assert digest(args.create_jar) == JAR_SHA256
    work = Path(tempfile.mkdtemp(prefix='burner-material-prebuilt-', dir=ROOT / '.local'))
    home = work / 'game'
    input_dir = home / 'horizon-mods/create-resources'
    input_dir.mkdir(parents=True)
    shutil.copy2(args.create_jar, input_dir / args.create_jar.name)
    shutil.copy2(args.reference, work / 'source.json')
    env = environment()
    env.update(HORIZON_TEST_RESOURCES=str(args.resources.resolve()),
               CREATE_BURNER_MATERIAL_PROBE=str(work), HORIZON_NO_AUDIO='1',
               HORIZON_API_DISCOVERY='http://127.0.0.1:9', RUST_MIN_STACK=str(16 * 1024 * 1024))
    for key in ('HORIZON_HOME', 'HORIZON_LAUNCHER_HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME'):
        path = work / key
        path.mkdir()
        env[key] = str(path)
    report = dict(passed=False, scope='Captured cfg(test) Game/CPU vertices; build/test receipts recorded; no GPU pixel claim',
                  test_executable=str(binary), test_executable_sha256=digest(binary),
                  snapshot=str(snapshot), snapshot_sha256=digest(snapshot),
                  native_files=build['native_files'], source_observation_sha256=digest(args.reference),
                  jar_sha256=JAR_SHA256, stage_untouched=True, cargo_not_invoked=True)
    if args.test_receipt:
        receipt = args.test_receipt.resolve()
        receipt.relative_to((ROOT / '.local').resolve())
        captured = work / 'captured-test-receipt.json'
        shutil.copy2(receipt, captured)
        report.update(test_receipt=str(receipt), captured_test_receipt=str(captured),
                      test_receipt_sha256=digest(captured))
    print(json.dumps(dict(work=str(work))), flush=True)
    try:
        with (work / 'test.log').open('w') as log:
            result = subprocess.run([str(binary), 'burner_material_actual_game_vertices',
                '--ignored', '--nocapture'], cwd=home, env=env, stdout=log, stderr=subprocess.STDOUT)
        report['test_exit'] = result.returncode
        assert result.returncode == 0, str(work / 'test.log')
        native = json.loads((work / 'native.json').read_text())
        assert native['frames'] == 128 and len(native['models']) == 14
        imports = list((home / '.horizon-cache/create-assets/imports').glob('*/import.json'))
        assert len(imports) == 1, imports
        imported = json.loads(imports[0].read_text())
        assert imported['jar_sha256'] == JAR_SHA256
        report.update(native=native, import_receipt=imported, passed=True)
    finally:
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(dict(passed=report['passed'], result=str(work / 'result.json'))), flush=True)
    return report


def run(args):
    stage, target = args.stage.resolve(), args.target.resolve()
    assert stage.parent.name.startswith('ownmod-lint-')
    for path in (stage, target, args.resources.resolve(), args.reference.resolve()):
        path.relative_to((ROOT / '.local').resolve())
    work = Path(tempfile.mkdtemp(prefix='burner-material-game-', dir=ROOT / '.local'))
    home = work / 'game'
    input_dir = home / 'horizon-mods/create-resources'
    input_dir.mkdir(parents=True)
    assert digest(args.create_jar) == JAR_SHA256
    shutil.copy2(args.create_jar, input_dir / args.create_jar.name)
    source = reference(args.reference)
    (work / 'source.json').write_text(json.dumps(source))
    adapter = ROOT / 'mixins/create/burner_presentation.rs'
    runtime = ROOT / 'mixins/create/runtime.rs'
    baseline = subprocess.check_output(['git', 'show', args.baseline_commit + ':mixins/create/burner_presentation.rs'],
                                       cwd=ROOT, text=True)
    candidate = adapter.read_text()
    fixture = ROOT / 'tools/rust/burner_material_test.rs'
    baseline_functions = function(baseline, 'fn part(').replace('fn part(', 'fn baseline_part(', 1)
    baseline_functions += '\n#[cfg(test)]\n' + function(baseline, 'pub(super) fn draw(').replace(
        'fn draw(', 'fn baseline_draw(', 1).replace('part(', 'baseline_part(')
    injection = '\n#[cfg(test)]\n' + baseline_functions + '\n#[cfg(test)] mod material_tests {include!(' + json.dumps(str(fixture)) + ');}\n'
    game = stage / 'crates/horizon-client/src/game.rs'
    before = game.read_bytes()
    text = before.decode()
    # This owned stage predates the entity-hat registration fix. Weave only
    # the current registration function alongside the candidate draw; retain
    # the exact stage bytes for finally, just as for the draw module.
    runtime_start = text.index('pub(crate) mod create_port {')
    previous_models = function(text[runtime_start:], 'pub(super) fn models(')
    current_models = function(runtime.read_text(), 'pub(super) fn models(')
    models_start = text.index(previous_models, runtime_start)
    text = text[:models_start] + current_models + text[models_start + len(previous_models):]
    signature = 'pub(crate) mod create_port_burner_presentation {'
    start = text.index(signature)
    old = function(text, signature)
    replacement = signature + '\n' + candidate + injection + '\n}'
    generated = text[:start] + replacement + text[start+len(old):]
    module_first = text[:start].count('\n') + 1
    module_last = module_first + replacement.count('\n')
    env = environment()
    env.update(CARGO_TARGET_DIR=str(target), CARGO_BUILD_JOBS='2', CARGO_INCREMENTAL='0',
               HORIZON_TEST_RESOURCES=str(args.resources.resolve()), CREATE_BURNER_MATERIAL_PROBE=str(work),
               HORIZON_NO_AUDIO='1', HORIZON_API_DISCOVERY='http://127.0.0.1:9', RUST_MIN_STACK=str(16*1024*1024))
    for key in ('HORIZON_HOME', 'HORIZON_LAUNCHER_HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME'):
        path = work / key
        path.mkdir()
        env[key] = str(path)
    report = dict(passed=False, scope=__doc__, adapter_sha256=hashlib.sha256(candidate.encode()).hexdigest(),
                  source_observation_sha256=hashlib.sha256(args.reference.read_bytes()).hexdigest(),
                  fixture_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest(), stage_restored=False,
                  jar_sha256=JAR_SHA256, game_dir=str(home),
                  runtime_sha256=digest(runtime),
                  registration_function_sha256=hashlib.sha256(current_models.encode()).hexdigest(),
                  scope_limit='Candidate functions on the recorded owned helper stage; not Stage10 binary acceptance')
    report['stage_helper_sha256'] = {name: hashlib.sha256((stage / name).read_bytes()).hexdigest()
        for name in ('crates/horizon-client/src/game/native_terrain_model.rs',
                     'crates/horizon-client-render/src/terrain_model.rs')}
    print(json.dumps(dict(work=str(work))), flush=True)
    try:
        game.write_text(generated)
        # Cargo runs tests from the package directory. Compile first, then run
        # this single test from its private game directory so normal asset_root
        # sees the player's verified JAR instead of the provisional fallback.
        with (work / 'cargo.jsonl').open('w') as log:
            result = subprocess.run(['cargo', 'test', '--locked', '--offline', '-p', 'horizon-client', '--lib',
                '--no-run', '--message-format=json'], cwd=stage, env=env,
                stdout=log, stderr=subprocess.STDOUT)
        report['compile_exit'] = result.returncode
        assert result.returncode == 0, str(work / 'cargo.jsonl')
        executables = set()
        for line in (work / 'cargo.jsonl').read_text().splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (row.get('reason') == 'compiler-artifact' and row.get('executable')
                    and row.get('profile', {}).get('test')
                    and row.get('target', {}).get('name') == 'horizon_client'):
                executables.add(Path(row['executable']))
        assert len(executables) == 1, executables
        executable = executables.pop()
        report['test_executable_sha256'] = digest(executable)
        with (work / 'test.log').open('w') as log:
            result = subprocess.run([str(executable), 'burner_material_actual_game_vertices',
                '--ignored', '--nocapture'], cwd=home, env=env, stdout=log, stderr=subprocess.STDOUT)
        report['test_exit'] = result.returncode
        assert result.returncode == 0, str(work / 'test.log')
        native = json.loads((work / 'native.json').read_text())
        assert native['frames'] == 128 and len(native['models']) == 14
        report['native'] = native
        imports = list((home / '.horizon-cache/create-assets/imports').glob('*/import.json'))
        assert len(imports) == 1, imports
        report['import_receipt'] = json.loads(imports[0].read_text())
        with (work / 'strict-clippy.jsonl').open('w') as log:
            quality = subprocess.run(['cargo', 'clippy', '--locked', '--offline', '-p', 'horizon-client', '--lib',
                '--message-format=json', '--', '-D', 'warnings'], cwd=stage, env=env,
                stdout=log, stderr=subprocess.STDOUT)
        report['clippy_exit'] = quality.returncode
        own, upstream = [], []
        for line in (work / 'strict-clippy.jsonl').read_text().splitlines():
            try:
                message = json.loads(line).get('message', {})
            except json.JSONDecodeError:
                continue
            if message.get('level') != 'error':
                continue
            spans = [span for span in message.get('spans', []) if span.get('is_primary')]
            row = dict(message=message['message'], code=message.get('code'), spans=spans)
            destination = own if any(span['file_name'].endswith('/game.rs')
                and module_first <= span['line_start'] <= module_last for span in spans) else upstream
            destination.append(row)
        report['own_clippy_errors'] = own
        report['upstream_clippy_errors'] = upstream
        assert not own, own
        assert quality.returncode == 0 or len(upstream) == 6, upstream
        report['passed'] = True
    finally:
        game.write_bytes(before)
        report['stage_restored'] = game.read_bytes() == before
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(dict(passed=report['passed'], result=str(work / 'result.json'))), flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('resources', 'reference'):
        parser.add_argument('--' + name, required=True, type=Path)
    for name in ('stage', 'target', 'test-binary', 'snapshot', 'test-receipt'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--create-jar', type=Path,
                        default=ROOT / '.local/input-instance/mods/create-1.21.1-6.0.10.jar')
    parser.add_argument('--baseline-commit', default='a7d0088')
    args = parser.parse_args()
    if args.test_binary:
        if not args.snapshot or not args.test_receipt or args.stage or args.target:
            parser.error('--test-binary requires --snapshot/--test-receipt and refuses --stage/--target')
        run_prebuilt(args)
    else:
        if not args.stage or not args.target or args.snapshot or args.test_receipt:
            parser.error('The weaving mode requires --stage/--target and refuses snapshot/receipt')
        run(args)
