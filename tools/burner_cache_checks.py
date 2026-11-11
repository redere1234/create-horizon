#!/usr/bin/env python3
"""CPU checks of the actual burner cache methods and actual ModRevision rule.

Compiles unchanged cache declarations/implementations and reset(), extracted
from the native adapter, against the portable engine. Only the Game dimension
query is an authored context. Identity inputs are controlled values using the
actual pinned ModRevision declaration and same_entity body. This is an adapter
method test, not an actual Game, packet, chunk-loader or rendered-image test.
No source tree is modified; generated probes and results stay private.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from common import ROOT, environment


def function(source, signature):
    start = source.index(signature)
    body = source.index('{', start)
    depth = 1
    end = body + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def run(args):
    output = args.output.resolve()
    assert output.is_relative_to(ROOT / '.local'), output
    output.mkdir(parents=True, exist_ok=True)
    native = ROOT / 'mixins/create/burner_presentation.rs'
    revision = args.horizon / 'crates/horizon-client-render/src/chunk/block_entity.rs'
    text = native.read_text()
    tokens = revision.read_text()
    token_start = tokens.index('#[derive(Clone, Copy, Debug, PartialEq, Eq)]\npub struct ModRevision')
    token_end = tokens.index('static MOD_BLOCK_ENTITIES_MADE:', token_start)
    cache = text[text.index('#[derive(Clone, PartialEq, Eq)]'):text.index("struct Random<'a>")]
    fixture = (ROOT / 'tools/rust/burner_cache_test.rs.in').read_text()
    generated = '''#![allow(dead_code)]
mod adapter {
use std::{cell::RefCell,collections::BTreeMap};
use create_horizon_core::{burner::Heat, burner_visual::{Animation,Visual}, placement::Direction};
// Only this dimension-query context is authored; no Game behavior is simulated.
struct Game<'a> { dimension: &'a str }
impl Game<'_> {fn native_dimension(&self)->&str {self.dimension}}
''' + tokens[token_start:token_end] + cache + function(text, 'pub(super) fn reset()') + fixture + '\n}\n'
    cargo = output / 'cargo'
    (cargo / 'src').mkdir(parents=True, exist_ok=True)
    (cargo / 'Cargo.toml').write_text('[package]\nname="burner-cache-checks"\nversion="0.0.0"\nedition="2024"\n[workspace]\n[dependencies]\ncreate-horizon-core={path=' + json.dumps(str(ROOT)) + '}\n')
    (cargo / 'src/lib.rs').write_text(generated)
    # These static assertions establish the actual callback's disposal route;
    # executing an engine world-unload callback remains separate native proof.
    config = (ROOT / 'mixins/create/horizon-mixin.toml').read_text()
    unload = next(row for row in re.split(r'^\[\[', config, flags=re.M)
                  if re.search(r'^id\s*=\s*"motor-world-reset"\s*$', row, re.M))
    assert re.search(r'^hook\s*=\s*"client_level_unload"\s*$', unload, re.M)
    helper = re.search(r'^helper\s*=\s*"([^"]+)"\s*$', unload, re.M).group(1)
    assert 'create_port_burner_presentation::reset();' in (ROOT / 'mixins/create' / helper).read_text()
    assert 'create_port_burner_presentation::reset();' in (ROOT / 'mixins/create/server_data.rs').read_text()
    assert 'create_port_burner_presentation::resources_reloaded(game);' in (ROOT / 'mixins/create/burner_resources.rs').read_text()
    env = environment()
    env.update({'CARGO_TARGET_DIR': str(cargo / 'target'), 'RUST_MIN_STACK': str(8 * 1024 * 1024)})
    report = {'passed': False, 'scope': __doc__, 'source_sha256': {
        str(native.relative_to(ROOT)): hashlib.sha256(native.read_bytes()).hexdigest(),
        'ModRevision': hashlib.sha256(tokens[token_start:token_end].encode()).hexdigest(),
        'fixture': hashlib.sha256(fixture.encode()).hexdigest()}, 'checks': []}
    for name, command in [
        ('cache-methods', ['cargo', 'test', '--offline', '--manifest-path', str(cargo / 'Cargo.toml'), '--', '--nocapture']),
        ('strict-clippy', ['cargo', 'clippy', '--offline', '--manifest-path', str(cargo / 'Cargo.toml'), '--all-targets', '--', '-D', 'warnings']),
    ]:
        with (output / (name + '.log')).open('w') as log:
            process = subprocess.run(command, env=env, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        report['checks'].append({'name': name, 'exit': process.returncode})
        report['passed'] = len(report['checks']) == 2 and all(row['exit'] == 0 for row in report['checks'])
        (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        if process.returncode:
            raise RuntimeError(f'{name} failed: {output / (name + ".log")}')
    print(json.dumps(report))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--horizon', type=Path, default=ROOT.parent / 'horizon-port-runtime')
    parser.add_argument('--output', type=Path, default=ROOT / '.local/burner-cache-checks')
    run(parser.parse_args())
