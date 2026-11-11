#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare ordinary Wrench clicks on a stationary Fluid Valve in both clients."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from burner_heat_java_checks import number
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from funnel_checks import click, put, step
from native_check_session import NativeCheckSession, wait_loaded
import reference_java


POS = (2264, 134, 1557)
AREA = '2260 133 1553 2268 140 1561'
COLUMN = '2256 1552 2271 1567'
BLOCK = 'create:fluid_valve'
CASES = (
    ('east', True, 'east'), ('west', False, 'east'),
    ('east', True, 'up'), ('north', False, 'up'),
    ('up', False, 'east'), ('down', True, 'south'),
    ('north', True, 'east'), ('east', False, 'south'),
    ('down', True, 'up'),
)


def states(host, work):
    x, y, z = POS
    camera = {
        'east': (x + 2.65, y, z + .5),
        'south': (x + .5, y, z + 2.65),
        'up': (x - .3, y + 2, z + .5),
    }
    command = host.command
    command(f'forceload add {COLUMN}')
    step(host, 24, POS)
    command(f'fill {AREA} minecraft:air')
    command('fill 2262 133 1555 2267 133 1560 minecraft:smooth_stone')
    put(command, (x - 1, y + 1, z), 'minecraft:smooth_stone')
    command('gamemode creative')
    result = {}
    for facing, first, face in CASES:
        name = f'{facing}-{str(first).lower()}-{face}'
        props = f'facing={facing},axis_along_first={str(first).lower()},enabled=true'
        put(command, POS, 'minecraft:air')
        put(command, POS, f'{BLOCK}[{props}]{{Pointer:{{Value:1.0f,Target:0.0f,Speed:0.0f}}}}')
        step(host, 3, POS)
        click(host, work, name, POS, face, camera[face], (x + .5, y + .5, z + .5), 'create:wrench')
        [after] = step(host, 3, POS)
        assert after['id'] == BLOCK, after
        props = {key: value.lower() for key, value in after['properties'].items()}
        assert props['enabled'] == 'true' and props['waterlogged'] == 'false', after
        assert number(after, 'Value') == 1.0, after
        assert (props['facing'], props['axis_along_first']) != (facing, str(first).lower()), after
        result[name] = props
    return result


def java(work):
    host = Original()
    manifest = json.loads((reference_java.BASE / 'manifest.json').read_text())
    assert manifest['create_sha256'] == reference_java.CREATE_SHA256
    prior = host.call('state', {})
    assert prior['ready'] and prior['data_version'] == 3955, prior
    host.call('tick', {'frozen': True})
    try:
        host.command(f'tp @s {xyz(POS)}')
        return states(host, work)
    finally:
        host.command(f'fill {AREA} minecraft:air')
        host.command(f'forceload remove {COLUMN}')
        host.command('item replace entity @s weapon.mainhand with minecraft:air')
        host.call('camera', {k: prior[k] for k in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': prior['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session):
    try:
        with session:
            host = Native(session)
            host.command(f'tp @s {xyz(POS)}')
            wait_loaded(session.call, [POS])
            host.command('tick freeze')
            return states(host, session.scratch)
    finally:
        session.control_temp.cleanup()
        for folder in (session.resources, session.scratch / '.horizon-cache', session.scratch / 'horizon-mods'):
            shutil.rmtree(folder, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.game:
        if not all((args.resources, args.ctl, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl and --reference')
        source = json.loads(args.reference.read_text())
        assert source['passed'] and source['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='valve-wrench-native', world='ValveWrench')
        work = session.scratch
        samples = native(session)
    else:
        work = Path(tempfile.mkdtemp(prefix='valve-wrench-java-', dir=ROOT / '.local'))
        samples = java(work)
    if args.game:
        assert samples == source['cases'], (samples, source['cases'])
    path = work / 'result.json'
    path.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], cases=samples), indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
