#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Prove a real Java chunk reload resumes the paused Deployer stroke."""
import argparse
import json
from pathlib import Path
import subprocess
from tempfile import NamedTemporaryFile

from chain_drive_checks import Original, xyz
from saved_block_checks import _probe, _raw_chunk
import reference_java as java
from deployer_stationary_reference_checks import (
    AIR, DEPLOYER, LOCK, MOTOR, POSITIONS, REDSTONE, SAPLING, motor, prepare, put, state_edges, trace,
)


def saved_block(base, probe):
    cx, cz = DEPLOYER[0] // 16, DEPLOYER[2] // 16
    region = base / 'game/saves/CreateJavaReference/region' / f'r.{cx // 32}.{cz // 32}.mca'
    raw, fingerprint = _raw_chunk(region, cx, cz)
    with NamedTemporaryFile(suffix='.nbt') as stream:
        stream.write(raw)
        stream.flush()
        result = subprocess.run([str(probe), stream.name, *map(str, DEPLOYER)], check=True,
                                capture_output=True, text=True)
    return dict(fields=json.loads(result.stdout), fingerprint=fingerprint)


def run(base, probe, output):
    java.BASE = base
    manifest = json.loads((base / 'manifest.json').read_text())
    assert manifest['create_sha256'] == java.CREATE_SHA256 and manifest['data_version'] == 3955
    host = Original()
    report = dict(passed=False)
    loaded = False
    try:
        assert host.call('state', {})['data_version'] == 3955
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        host.command('tp @s 1128.5 107 85.5')
        host.command('forceload add 1131 85')
        loaded = True
        host.call('observe_ticks', {'ticks': 22, 'positions': POSITIONS})
        prepare(host, stock=2)
        trace(host, 8, [motor(-32)])
        rows = trace(host, 5, [put(MOTOR, AIR), put(LOCK, REDSTONE)])
        held = rows[-1]
        assert (held['state'], held['timer'], held['held'], held['powered']) == ('EXPANDING', 616, 2, True), held
        report['paused'] = held
        host.command('forceload remove 1131 85')
        loaded = False
        host.command('tp @s 640.5 107 40.5')
        for _ in range(4):
            host.call('tick', {'step': 100})
            unseen = host.command(f'execute unless loaded {xyz(DEPLOYER)} run time query gametime')
            if any('The time is' in line for line in unseen['messages']):
                report['unloaded'] = unseen
                break
        else:
            raise AssertionError('Vanilla did not evict the unforced chunk')

        for _ in range(8):
            host.call('tick', {'step': 30})
            on_disk = saved_block(base, probe)
            fields = on_disk['fields']['value']
            if fields['State']['value'] == 'EXPANDING' and fields['Timer']['value'] == 616:
                report['saved_on_disk'] = on_disk
                break
        else:
            raise AssertionError(('Java did not write the evicted Deployer', fields))
        assert fields['Powered']['value'] == 1, fields
        assert fields['HeldItem']['value']['count']['value'] == 2, fields

        host.command('forceload add 1131 85')
        loaded = True
        host.command('tp @s 1128.5 107 85.5')
        host.call('tick', {'step': 20})
        [cold] = trace(host, 1)
        fields = ('state', 'timer', 'rpm', 'powered', 'held', 'gap', 'target', 'soil')
        assert [cold[key] for key in fields] == [held[key] for key in fields], (held, cold)
        report['cold_loaded'] = cold
        resumed = trace(host, 37, [motor(-32)])
        placed = next(row for row in resumed if row['target'] == SAPLING)
        assert placed['held'] == 1 and placed['powered'] and placed['state'] == 'RETRACTING', placed
        report['resumed_edges'] = state_edges(resumed)
        report['resumed'] = resumed
        report['passed'] = True
    finally:
        if loaded:
            host.command('forceload remove 1131 85')
        host.call('tick', {'frozen': False})
        output.mkdir(parents=True, exist_ok=True)
        (output/'cold.json').write_text(json.dumps(report, indent=2) + '\n')
        (output/'cold-transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
        print(output/'cold.json')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('java', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.java, _probe()[0], args.output)
