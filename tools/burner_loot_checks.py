#!/usr/bin/env python3
"""Actual Game/registry burner loot and wrench callbacks in an owned native stage.

Uses the real bundled content loader, Game::block_loot_at, ordinary item loot
evaluator and native wrench callback. No window, GPU, server listener or existing
world is opened. Source Java interaction captures remain a separate proof; this
test does not claim original explosion-event or normal mouse-input acceptance.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from common import ROOT, environment


def digest(data):
    return hashlib.sha256(data).hexdigest()


def validate(table, lit):
    """Refuse unreviewed export features, rather than discard unknown JSON.

    This is the bounded authored burner export, not a restriction on ordinary
    player data packs. Its source declares no functions, nested tables or other
    predicate types. Horizon's actual evaluator remains responsible for rolls.
    """
    def require(condition):
        if not condition:
            raise ValueError('Unsupported burner loot export structure')
    require(set(table) == {'type', 'pools'} and table['type'] == 'minecraft:block')
    require(isinstance(table['pools'], list) and len(table['pools']) == 1)
    pool = table['pools'][0]
    require(set(pool) == ({'rolls', 'conditions', 'entries'} if lit else {'rolls', 'entries'}))
    require(pool['rolls'] == 1)
    if lit:
        require(pool['conditions'] == [{'type': 'minecraft:survives_explosion'}])
    entries = pool['entries']
    require(isinstance(entries, list) and len(entries) == (1 if lit else 5))
    for index, entry in enumerate(entries):
        require(set(entry) == ({'type', 'name'} if lit else {'type', 'name', 'conditions'}))
        require(entry['type'] == 'minecraft:item')
        require(entry['name'] == ('create:empty_blaze_burner' if lit or index == 0 else 'create:blaze_burner'))
        if not lit:
            require(entry['conditions'] == [
                {'type': 'minecraft:survives_explosion'},
                {'type': 'minecraft:block_state_property', 'block': 'create:blaze_burner',
                 'properties': {'blaze': ['none', 'smouldering', 'fading', 'kindled', 'seething'][index]}},
            ])


def parse_proof(log):
    rows = [json.loads(line.removeprefix('BURNER_LOOT_PROOF '))
            for line in log.splitlines() if line.startswith('BURNER_LOOT_PROOF ')]
    assert len(rows) == 1 and 'test result: ok. 1 passed;' in log
    expected = {'actual_game_state_cases': 22, 'pre_regression_empty_cases': 22,
                'target_explosion_cases': 44, 'actual_server_wrench_callbacks': 3}
    assert rows[0] == expected, rows
    return rows[0]


def run(args):
    stage = args.stage.resolve()
    target = args.target.resolve()
    assert stage.is_relative_to(ROOT / '.local') and not args.stage.is_symlink(), stage
    assert stage.parent.name.startswith(('ownmod-lint-', 'burner-loot-')), stage
    assert (stage / '.horizon-mixins-stage.json').is_file(), stage
    assert target.is_relative_to(ROOT / '.local'), target
    work = Path(tempfile.mkdtemp(prefix='burner-loot-game-', dir=ROOT / '.local'))
    resources = work / 'resources'
    subprocess.run(['cp', '-cR', str(args.resources.resolve()), str(resources)], check=True)
    game = stage / 'crates/horizon-client/src/game.rs'
    data = stage / 'native-data/create/content.json'
    current = ROOT / 'mixins/create/data/content.json'
    bundle = json.loads(current.read_text())
    tables = []
    for lit, name in [(False, 'blaze_burner'), (True, 'lit_blaze_burner')]:
        path = 'data/create/loot_table/blocks/' + name + '.json'
        table = json.loads(bundle[path])
        assert table == json.loads((ROOT / 'content' / path).read_text())
        validate(table, lit)
        tables.append(table)
    # Negative schema examples establish that unknown source features cannot
    # disappear silently in a future export change.
    for key, value in [('functions', []), ('modifier', []), ('value', 'test:nested')]:
        bad = copy.deepcopy(tables[0])
        bad['pools'][0]['entries'][0][key] = value
        try:
            validate(bad, False)
        except ValueError:
            pass
        else:
            raise AssertionError(('Unsupported export was accepted', key))
    before = {path: path.read_bytes() for path in [game, data]}
    fixture = ROOT / 'tools/rust/burner_loot_test.rs'
    assert 'mod burner_loot_tests' not in before[game].decode()
    injection_text = '\n#[cfg(test)] mod burner_loot_tests {\ninclude!(' + json.dumps(str(fixture)) + ');\n}\n'
    env = environment()
    env.update({'CARGO_TARGET_DIR': str(target), 'CARGO_BUILD_JOBS': '2',
                'HORIZON_TEST_RESOURCES': str(resources), 'HORIZON_NO_AUDIO': '1',
                'HORIZON_LAUNCHER_NO_SELF_UPDATE': '1',
                'HORIZON_API_DISCOVERY': 'http://127.0.0.1:9',
                'RUST_MIN_STACK': str(16 * 1024 * 1024)})
    for key in ['HORIZON_HOME', 'HORIZON_LAUNCHER_HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME']:
        path = work / key
        path.mkdir()
        env[key] = str(path)
    report = {'passed': False, 'scope': __doc__, 'stage': str(stage),
              'horizon': (stage / '.horizon-revision').read_text().strip(),
              'fixture_sha256': digest(fixture.read_bytes()),
              'export_schema_negative_guards': 3,
              'native_data_sha256': digest(current.read_bytes()),
              'stage_game_sha256': digest(before[game]), 'resources_copy': str(resources)}
    try:
        game.write_bytes(before[game] + injection_text.encode())
        data.write_bytes(current.read_bytes())
        command = ['cargo', 'test', '--locked', '--offline', '-p', 'horizon-client', '--lib',
                   'burner_loot_actual_game_registry_and_wrench', '--', '--ignored', '--nocapture']
        report['command'] = command
        print(json.dumps({'work': str(work), 'target': str(target)}), flush=True)
        with (work / 'cargo.log').open('w') as log:
            result = subprocess.run(command, env=env, cwd=stage, stdout=log, stderr=subprocess.STDOUT)
        report['exit'] = result.returncode
        assert result.returncode == 0, (result.returncode, str(work / 'cargo.log'))
        report['actual_game'] = parse_proof((work / 'cargo.log').read_text())
        report['passed'] = True
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        for path, original in before.items():
            path.write_bytes(original)
        report['stage_restored'] = all(path.read_bytes() == original for path, original in before.items())
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'passed': report['passed'], 'result': str(work / 'result.json')}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', type=Path, required=True)
    parser.add_argument('--resources', type=Path, required=True)
    parser.add_argument('--target', type=Path, required=True)
    run(parser.parse_args())
