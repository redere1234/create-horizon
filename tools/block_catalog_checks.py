#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Audit IDs, default block states and block entity types for the public catalog."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from catalog import BLOCKS
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from funnel_checks import block
from native_check_session import NativeCheckSession, wait_loaded
from reference_java import BASE, CREATE_SHA256


ORIGIN = (3296, 111, 1744)
FLOOR = '3296 110 1744 3343 110 1775'
AREA = '3296 111 1744 3343 114 1775'
COLUMNS = '3296 1744 3343 1775'
CELLS = {f'create:{name}': (ORIGIN[0] + 4 * (i % 12), ORIGIN[1], ORIGIN[2] + 4 * (i // 12))
         for i, name in enumerate(BLOCKS)}
BE_ID = re.compile(r'\bid\s*:\s*"([^"]+)"')
PIPE = 'create:fluid_pipe'
SIDES = ('down', 'up', 'north', 'south', 'west', 'east')


def snapshot(observation):
    entity = BE_ID.search(observation.get('nbt', ''))
    return dict(id=observation['id'],
                properties={k: v.lower() for k, v in observation['properties'].items()},
                entity=entity[1] if entity else None)


def place(host, *, strict=False):
    host.command(f'fill {AREA} minecraft:air')
    host.command(f'fill {FLOOR} minecraft:smooth_stone')
    for expected, pos in CELLS.items():
        host.command(f'setblock {xyz(pos)} {expected}' + (' strict' if strict else ''))


def native_blocks(host):
    # The control socket reads the client block state. Let the server's
    # block updates arrive even though world simulation is frozen.
    host.session.call('wait', 10)
    return {expected: snapshot(block(host, pos)) for expected, pos in CELLS.items()}


def original(work):
    host = Original()
    assert json.loads((BASE / 'manifest.json').read_text())['create_sha256'] == CREATE_SHA256
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {COLUMNS}')
        host.command('tp @s 3318.5 116 1758.5')
        host.call('observe_ticks', {'ticks': 40, 'positions': [ORIGIN]})
        place(host)
        return {expected: host.call('block', {'pos': pos, 'default_state': True})
                for expected, pos in CELLS.items()}
    finally:
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'fill {FLOOR} minecraft:air')
        host.command(f'forceload remove {COLUMNS}')
        host.call('camera', {k: initial[k] for k in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session):
    with session:
        host = Native(session)
        host.command('tp @s 3318.5 116 1758.5')
        host.command(f'forceload add {COLUMNS}')
        wait_loaded(session.call, CELLS.values())
        host.command('tick freeze')
        place(host)
        placed = native_blocks(host)
        place(host, strict=True)
        return placed, native_blocks(host)


def differences(reference, observed):
    return {name: dict(java=reference[name], native=row) for name, row in observed.items()
            if row != reference[name]}


def expected_pipe_difference(*connected):
    # The native fluid adapter only simulates dry straight lines. The source
    # registry opens all six sides and Java's neighbor prepass closes four.
    return {PIPE: dict(java={side: str(side in connected).lower()
                                 for side in (*SIDES, 'waterlogged')},
                       native=dict.fromkeys((*SIDES, 'waterlogged'), 'false'))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    report = dict(create=PINS['create_revision'])
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='catalog-java-', dir=ROOT / '.local'))
        observations = original(work)
        report['blocks'] = {name: snapshot(row) for name, row in observations.items()}
        report['registry_defaults'] = {name: {k: v.lower() for k, v in row['default_properties'].items()}
                                       for name, row in observations.items()}
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon needs --game, --resources, --ctl and --reference')
        source = json.loads(args.reference.read_text())
        assert source['create'] == report['create'] and source['blocks'].keys() == CELLS.keys()
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='catalog-native', graphics=False, world='CatalogAudit')
        work = session.scratch
        try:
            report['blocks'], strict = native(session)
        finally:
            for path in (session.resources, work / '.horizon-cache'):
                shutil.rmtree(path, ignore_errors=True)
        report['registry_defaults'] = {name: row['properties'] for name, row in strict.items()}
        report['differences'] = differences(source['blocks'], report['blocks'])
        report['registry_differences'] = differences(source['registry_defaults'], report['registry_defaults'])
    report['resolved'] = sum(name == row['id'] for name, row in report['blocks'].items())
    result = work / 'result.json'
    result.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(result=str(result), blocks=len(CELLS), resolved=report['resolved'],
                          differences=len(report.get('differences', {})))), flush=True)
    assert report['resolved'] == len(CELLS), result
    if not args.java:
        assert all(name == row['id'] for name, row in strict.items()), result
        assert report['registry_differences'] in ({}, expected_pipe_difference(*SIDES)), result
        pipe = expected_pipe_difference('east', 'west')
        java_pipe = {**source['blocks'][PIPE], 'properties': pipe[PIPE]['java']}
        native_pipe = {**source['blocks'][PIPE], 'properties': pipe[PIPE]['native']}
        assert report['differences'] in ({}, {PIPE: dict(java=java_pipe, native=native_pipe)}), result


if __name__ == '__main__':
    main()
