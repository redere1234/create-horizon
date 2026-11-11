#!/usr/bin/env python3
"""Check imported belt meshes through actual Game draw helpers, without a GPU.

Use an owned developer stage and private reference resources. Only a cfg(test)
include is added; the production source is restored byte for byte on exit.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from burner_material_checks import JAR_SHA256
from common import ROOT, PINS, environment


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('stage', 'target', 'resources', 'build-result', 'create-jar', 'oracle'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    stage, target = args.stage.resolve(), args.target.resolve()
    for path in (stage, target, args.build_result.resolve(), args.oracle.resolve()):
        assert path.is_relative_to(ROOT / '.local'), path
    build = json.loads(args.build_result.read_text())
    oracle = json.loads((args.oracle / 'result.json').read_text())
    assert build['passed'] and Path(build['stage_cache']).resolve() == stage
    assert (stage / '.horizon-revision').read_text().strip() == build['horizon']
    assert oracle['passed'] and oracle['create_revision'] == PINS['create_revision']
    assert build['native_files']['belt.rs'] == sha(ROOT / 'mixins/create/belt.rs')
    assert oracle['adapter_sha256'] == build['native_files']['belt.rs']
    assert sha(args.create_jar) == JAR_SHA256
    work = Path(tempfile.mkdtemp(prefix='belt-render-game-', dir=ROOT / '.local'))
    home = work / 'game'
    inputs = home / 'horizon-mods/create-resources'
    inputs.mkdir(parents=True)
    shutil.copy2(args.create_jar, inputs / 'create.jar')
    resources = work / 'resources'
    if os.uname().sysname == 'Darwin':
        subprocess.run(['cp', '-cR', str(args.resources.resolve()), str(resources)], check=True)
    else:
        shutil.copytree(args.resources, resources)
    shutil.copy2(args.oracle / 'source-frames.json', work / 'source-frames.json')
    fixture = work / 'belt_render_game_test.rs'
    shutil.copy2(ROOT / 'tools/rust/belt_render_game_test.rs', fixture)
    env = environment()
    env.pop('HORIZON_STILL', None)
    env.update(CARGO_TARGET_DIR=str(target), CARGO_BUILD_JOBS='2',
               HORIZON_TEST_RESOURCES=str(resources), CREATE_BELT_RENDER_PROBE=str(work),
               HORIZON_NO_AUDIO='1', HORIZON_LAUNCHER_NO_SELF_UPDATE='1',
               HORIZON_API_DISCOVERY='http://127.0.0.1:9', RUST_MIN_STACK='33554432')
    for name in ('HORIZON_HOME', 'HORIZON_LAUNCHER_HOME', 'XDG_DATA_HOME', 'XDG_CONFIG_HOME'):
        folder = work / name
        folder.mkdir()
        env[name] = str(folder)
    source = stage / 'crates/horizon-client/src/game.rs'
    report = dict(passed=False, stage_restored=False, build_result=str(args.build_result.resolve()),
                  build_result_sha256=sha(args.build_result), fixture_sha256=sha(fixture),
                  source_frames_sha256=sha(work / 'source-frames.json'),
                  jar_sha256=JAR_SHA256, scope=__doc__)

    def save():
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')

    print(str(work), flush=True)
    with stage.with_suffix('.build.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        before = source.read_bytes()
        report['production_sha256'] = sha(source)
        # Stage is reusable and may have changed while this process waited.
        # The recorded module source is the original native input, before
        # prettyplease formats its woven Game module.
        assert (stage / '.horizon-revision').read_text().strip() == build['horizon']
        stamp = json.loads((stage / '.horizon-mixins-stage.json').read_text())
        modules = [module for module in stamp['modules']
                   if module['mod_id'] == 'create' and module['name'] == 'create_port_belt']
        assert len(modules) == 1, modules
        stage_belt_sha = hashlib.sha256(modules[0]['source'].encode()).hexdigest()
        assert stage_belt_sha == build['native_files']['belt.rs']
        report['stage_belt_input_sha256'] = stage_belt_sha
        # New build receipts can bind the precise official-weaver output too.
        # Legacy receipts cannot retroactively establish that output hash.
        expected_output_sha = build.get('stage_game_sha256')
        report['build_stage_output_hash_verified'] = False
        if expected_output_sha is not None:
            assert report['production_sha256'] == expected_output_sha
            report['build_stage_output_hash_verified'] = True
        marker = 'pub(crate) mod create_port_belt {'
        text = before.decode()
        assert text.count(marker) == 1
        include = '\n#[cfg(test)] mod render_mesh_tests { include!(' + json.dumps(str(fixture)) + '); }\n'
        try:
            source.write_text(text.replace(marker, marker + include, 1))
            command = ['cargo', 'test', '--locked', '--offline', '-p', 'horizon-client', '--lib',
                       '--profile', 'fast', '--config', 'profile.fast.package.horizon-client.opt-level=0',
                       '--no-run', '--message-format=json']
            with (work / 'cargo.jsonl').open('w') as log:
                result = subprocess.run(command, cwd=stage, env=env, stdout=log, stderr=subprocess.STDOUT)
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
            report.update(test_executable=str(executable), test_executable_sha256=sha(executable))
            with (work / 'test.log').open('w') as log:
                result = subprocess.run([str(executable), 'belt_render_actual_game_mesh',
                                         '--ignored', '--nocapture'], cwd=home, env=env,
                                        stdout=log, stderr=subprocess.STDOUT)
            report['test_exit'] = result.returncode
            assert result.returncode == 0, str(work / 'test.log')
            report['native'] = json.loads((work / 'native-mesh.json').read_text())
            assert report['native']['passed'] and report['native']['frames'] == 60
            # Independent Cartesian coverage: 60 duplicated rows must not
            # masquerade as every orientation at all three supported speeds.
            expected = {(facing, slope, rpm)
                        for facing in ('north', 'south', 'west', 'east')
                        for slope in ('horizontal', 'upward', 'downward', 'vertical', 'sideways')
                        for rpm in (-32.0, 0.0, 32.0)}
            observed = [(row['facing'], row['slope'], row['rpm'])
                        for row in report['native']['observed']]
            assert len(observed) == len(expected) == 60, observed
            assert len(set(observed)) == 60, 'duplicate native draw cases'
            assert set(observed) == expected, (expected - set(observed), set(observed) - expected)
            report['passed'] = True
        finally:
            source.write_bytes(before)
            report['stage_restored'] = source.read_bytes() == before
            report['passed'] = report['passed'] and report['stage_restored']
            save()
            assert report['stage_restored'], 'stage source was not restored'
    print(json.dumps(dict(passed=report['passed'], result=str(work / 'result.json'))), flush=True)


if __name__ == '__main__':
    main()
