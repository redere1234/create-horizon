#!/usr/bin/env python3
"""Deferred Mixer scheduling in a complete official source-woven Game stage.

The caller must lease the stage/target exclusively and supply private prepared
resources. Production source is not substituted: this only appends cfg(test)
fixtures to the captured Mixer module and restores exact bytes in finally.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import time

from common import ROOT, environment


def run(stage, resources, target, *, clippy=True):
    stage = Path(stage).resolve()
    target = Path(target).resolve()
    stage.relative_to(ROOT / '.local')
    target.relative_to(ROOT / '.local')
    source = stage / 'crates/horizon-client/src/game.rs'
    before = source.read_bytes()
    game = before.decode()
    prefix = 'pub(crate) mod create_port_mixer {'
    assert game.count(prefix) == 1
    assert 'fn on_speed_changed' in game
    assert 'create_port_basin::notify_contents' in game
    work = Path(tempfile.mkdtemp(prefix='mixer-schedule-check-', dir=ROOT / '.local'))
    proofs = [('schedule_proof', 'mixer_schedule_test.rs'),
              ('reload_proof', 'mixer_reload_test.rs')]
    append = ''.join('\n#[cfg(test)] mod ' + name + ' { include!(' +
                     json.dumps(str(ROOT / 'tools/rust' / file)) + '); }\n'
                     for name, file in proofs)
    modified = game.replace(prefix, prefix + append, 1)
    env = environment()
    env.update(CARGO_TARGET_DIR=str(target), CARGO_BUILD_JOBS='2',
               CARGO_INCREMENTAL='0', RUST_MIN_STACK='33554432',
               HORIZON_TEST_RESOURCES=str(Path(resources).resolve()),
               HORIZON_NO_AUDIO='1', HORIZON_LAUNCHER_NO_SELF_UPDATE='1',
               HORIZON_API_DISCOVERY='http://127.0.0.1:9')
    for name in ['HORIZON_HOME', 'HORIZON_LAUNCHER_HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME']:
        path = work / name
        path.mkdir()
        env[name] = str(path)
    report = {'passed': False, 'stage': str(stage), 'target': str(target),
              'stage_before_sha256': hashlib.sha256(before).hexdigest(),
              'fixture_sha256': {file: hashlib.sha256((ROOT / 'tools/rust' / file).read_bytes()).hexdigest()
                                 for _, file in proofs},
              'scope': __doc__, 'checks': []}
    commands = [('scheduling', ['cargo', 'test', '--offline', '-p', 'horizon-client', '--lib',
                                'mixer_deferred_scheduling_actual_game', '--', '--include-ignored',
                                '--nocapture', '--test-threads=1']),
                ('reload-rng', ['cargo', 'test', '--offline', '-p', 'horizon-client', '--lib',
                                'mixer_reload_actual_game_and_client_rng', '--', '--include-ignored',
                                '--nocapture', '--test-threads=1'])]
    if clippy:
        commands.append(('clippy', ['cargo', 'clippy', '--offline', '-p', 'horizon-client', '--lib',
                                   '--tests', '--', '-D', 'warnings', '-A', 'dead_code']))
    print(json.dumps({'work': str(work), 'scope': 'captured official source-woven Game'}), flush=True)
    try:
        source.write_text(modified)
        for name, command in commands:
            start = time.monotonic()
            path = work / (name + '.log')
            with path.open('w') as output:
                result = subprocess.run(command, cwd=stage, env=env, stdout=output,
                                        stderr=subprocess.STDOUT)
            report['checks'].append({'name': name, 'exit': result.returncode,
                                     'seconds': time.monotonic() - start, 'log': str(path)})
            print(name, result.returncode, path, flush=True)
            if result.returncode:
                raise RuntimeError(name + ' failed; inspect ' + str(path))
        report['passed'] = True
    finally:
        source.write_bytes(before)
        report['stage_restored'] = source.read_bytes() == before
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'passed': report['passed'], 'restored': report['stage_restored'],
                          'result': str(work / 'result.json')}), flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['stage', 'resources', 'target']:
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--no-clippy', action='store_true', help='For an outer combined driver that runs Clippy once.')
    args = parser.parse_args()
    run(args.stage, args.resources, args.target, clippy=not args.no_clippy)
