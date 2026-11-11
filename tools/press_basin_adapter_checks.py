#!/usr/bin/env python3
"""Run Press/Basin and existing machine regressions in an official woven stage.

Only cfg(test) includes are added to the leased developer stage. Production is
restored byte for byte. This checks actual Game adapters, not a window, audio,
network connection or pixel parity with Java.
"""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

from common import ROOT, environment


FIXTURES = [
    ('create_port_basin_recipes', 'basin_recipe_test.rs',
     'basin_recipe_operators_reload_and_compacting_actual_game'),
    ('create_port_press_client', 'press_client_test.rs',
     'press_actual_client_receipt_tick_identity_and_particle_rng'),
    ('create_port_press_basin', 'press_basin_test.rs',
     'press_basin_actual_game_lifecycle'),
    ('create_port_mixer', 'mixer_schedule_test.rs',
     'mixer_deferred_scheduling_actual_game'),
    ('create_port_mixer', 'mixer_reload_test.rs',
     'mixer_reload_actual_game_and_client_rng'),
    (None, 'item_contact_test.rs',
     'source_item_contacts_actual_owned_game_and_remote'),
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('stage', 'resources', 'target', 'build-result'):
        parser.add_argument('--' + key, type=Path, required=True)
    parser.add_argument('--only', choices=[row[2] for row in FIXTURES])
    args = parser.parse_args()
    stage, resources, target = map(Path.resolve, (args.stage, args.resources, args.target))
    assert stage.is_relative_to(ROOT / '.local') and target.is_relative_to(ROOT / '.local')
    assert (stage / '.horizon-mixins-stage.json').is_file()
    build = json.loads(args.build_result.read_text())
    assert build['passed'] and Path(build['stage_cache']).resolve() == stage
    assert (stage / '.horizon-revision').read_text().strip() == build['horizon']
    work = Path(tempfile.mkdtemp(prefix='press-basin-adapter-', dir=ROOT / '.local'))
    (work / 'fixtures').mkdir()
    source = stage / 'crates/horizon-client/src/game.rs'
    report = dict(passed=False, build_result=str(args.build_result.resolve()),
                  build_result_sha256=sha(args.build_result), stage=str(stage),
                  target=str(target), horizon=build['horizon'],
                  scope='Actual Game adapters with cfg(test) includes; no Java, GPU, audio or connected LAN claim',
                  fixtures={}, checks=[])
    def save():
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    env = environment()
    env.update(CARGO_TARGET_DIR=str(target), CARGO_BUILD_JOBS='2',
               RUST_MIN_STACK='33554432', HORIZON_TEST_RESOURCES=str(resources),
               HORIZON_NO_AUDIO='1', HORIZON_LAUNCHER_NO_SELF_UPDATE='1',
               HORIZON_API_DISCOVERY='http://127.0.0.1:9')
    for key in ('HORIZON_HOME', 'HORIZON_LAUNCHER_HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME'):
        home = work / key
        home.mkdir()
        env[key] = str(home)
    print(str(work), flush=True)
    with stage.with_suffix('.build.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        original = source.read_bytes()
        report['production_sha256'] = sha(source)
        modified = original.decode()
        for index, (module, basename, _) in enumerate(FIXTURES):
            fixture = work / 'fixtures' / basename
            shutil.copyfile(ROOT / 'tools/rust' / basename, fixture)
            report['fixtures'][basename] = sha(fixture)
            include = '\n#[cfg(test)] mod press_basin_proof_' + str(index) + ' { include!(' + json.dumps(str(fixture)) + '); }\n'
            if module:
                marker = 'pub(crate) mod ' + module + ' {'
                assert modified.count(marker) == 1, module
                modified = modified.replace(marker, marker + include, 1)
            else:
                modified += include
        save()
        try:
            source.write_text(modified)
            for _, _, name in FIXTURES:
                if args.only and args.only != name:
                    continue
                command = ['cargo', 'test', '--offline', '--locked', '-p', 'horizon-client',
                           '--lib', name, '--', '--ignored', '--nocapture']
                start = time.monotonic()
                path = work / (name + '.log')
                with path.open('w') as log:
                    run = subprocess.run(command, cwd=stage, env=env,
                                         stdout=log, stderr=subprocess.STDOUT)
                log = path.read_text()
                real_pass = bool(re.search(r'test result: ok\. 1 passed;', log))
                report['checks'].append(dict(name=name, exit=run.returncode,
                                             actual_one_test_passed=real_pass,
                                             seconds=time.monotonic() - start))
                save()
                print(name, run.returncode, real_pass, flush=True)
                if run.returncode or not real_pass:
                    raise RuntimeError('Actual Game regression failed: ' + str(path))
            report['passed'] = True
        finally:
            source.write_bytes(original)
            report['stage_restored'] = source.read_bytes() == original
            save()
    print(json.dumps({'passed': report['passed'], 'result': str(work / 'result.json')}), flush=True)


if __name__ == '__main__':
    main()
