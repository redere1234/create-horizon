#!/usr/bin/env python3
"""Exercise burner sync in an owned official horizon-mixins apply stage.

No launcher build, game window, server entry or EULA write is performed. The
stage must already contain the full Create mod and its normal callback wiring.
Only the two owned sync modules and the current remote adapter are refreshed
temporarily. cfg(test) hooks control Remote's private lifecycle field without
replacing any production fuel, packet, prediction or cleanup implementation.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time

from common import ROOT, environment


def module(text, name, body):
    prefix = 'pub(crate) mod ' + name + ' {'
    assert text.count(prefix) == 1, name
    start = text.index(prefix)
    following = re.search(r'^pub\(crate\) mod ', text[start + len(prefix):], re.M)
    end = start + len(prefix) + following.start() if following else len(text)
    return text[:start] + prefix + '\n' + body + '\n}\n' + text[end:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', required=True, type=Path)
    parser.add_argument('--resources', required=True, type=Path)
    parser.add_argument('--target', required=True, type=Path)
    args = parser.parse_args()
    stage = args.stage.resolve()
    assert stage.is_relative_to(ROOT / '.local') and not args.stage.is_symlink(), stage
    assert (stage / 'native-crates/create/engine/Cargo.toml').is_file(), stage
    sources = [stage / 'crates/horizon-client/src/game.rs',
               stage / 'crates/horizon-client/src/game/remote.rs']
    before = {path: path.read_bytes() for path in sources}
    scratch = Path(tempfile.mkdtemp(prefix='burner-sync-check-', dir=ROOT / '.local'))
    native = ROOT / 'mixins/create'
    # The complete mod currently has unrelated Clippy findings. Suppress that
    # inherited lint group, then deny it again inside the two owned modules.
    game = '#![allow(clippy::all)]\n' + sources[0].read_text()
    proof = '\n#[cfg(test)] mod proof { include!(' + json.dumps(
        str(ROOT / 'tools/rust/burner_sync_test.rs')) + '); }\n'
    for name in ['burner_sync', 'burner_sync_protocol']:
        body = '#![deny(clippy::all)]\n' + (native / (name + '.rs')).read_text()
        game = module(game, 'create_port_' + name, body + (proof if name == 'burner_sync' else ''))
    remote = module(sources[1].read_text(), 'create_port_burner_prediction',
                    (native / 'burner_prediction.rs').read_text())
    remote += '\ninclude!(' + json.dumps(str(ROOT / 'tools/rust/burner_sync_remote_test.rs')) + ');\n'
    env = environment()
    env['CARGO_TARGET_DIR'] = str(args.target.resolve())
    env['CARGO_BUILD_JOBS'] = '2'
    env['HORIZON_TEST_RESOURCES'] = str(args.resources.resolve())
    env['HORIZON_NO_AUDIO'] = '1'
    env['HORIZON_LAUNCHER_NO_SELF_UPDATE'] = '1'
    # Remote's ordinary profile-service constructor must not contact a real
    # account service in this memory-Pipe controlled Game test.
    env['HORIZON_API_DISCOVERY'] = 'http://127.0.0.1:9'
    for key in ['HORIZON_HOME', 'HORIZON_LAUNCHER_HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME']:
        path = scratch / key
        path.mkdir()
        env[key] = str(path)
    records = []
    try:
        sources[0].write_text(game)
        sources[1].write_text(remote)
        for name, command in [
            ('actual-game', ['cargo', 'test', '--offline', '-p', 'horizon-client', '--lib',
                             'burner_sync', '--', '--include-ignored', '--nocapture']),
            # Existing full-mod entry points unused by the current wiring are
            # outside the sync review boundary; the two owned modules deny all
            # Clippy lints locally, including their cfg(test) proof module.
            ('clippy', ['cargo', 'clippy', '--offline', '-p', 'horizon-client', '--lib',
                        '--tests', '--', '-D', 'warnings', '-A', 'dead_code']),
        ]:
            started = time.monotonic()
            with (scratch / (name + '.log')).open('w') as log:
                process = subprocess.run(command, cwd=stage, env=env, stdout=log,
                                         stderr=subprocess.STDOUT)
            records.append({'check': name, 'exit': process.returncode,
                            'seconds': time.monotonic() - started})
            (scratch / 'result.json').write_text(json.dumps(records, indent=2) + '\n')
            print(name, process.returncode, scratch, flush=True)
            if process.returncode:
                raise SystemExit(process.returncode)
    finally:
        for path, content in before.items():
            path.write_bytes(content)


if __name__ == '__main__':
    main()
