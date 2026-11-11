#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Observe the pinned Java piston separating its local player from a wall."""
import json
from pathlib import Path
import tempfile

from common import PINS, ROOT
from chain_drive_checks import Original
from burner_heat_java_checks import number


PIVOT = (903, 100, 102)


def run_side(host, z, expected_z):
    def step(count, commands=()):
        trace = host.call('observe_ticks', {
            'ticks': count, 'positions': [PIVOT], 'commands': commands,
        })['samples']
        block = trace[-1]['blocks'][0]
        return dict(position=host.call('state', {})['position'],
                    offset=number(block, 'Offset', 0),
                    running=number(block, 'Running', 0))

    host.call('tick', {'frozen': True})
    host.command('gamemode creative')
    host.command(f'tp @s 905.45 100 {z}')
    host.command('forceload add 896 96 911 111')
    step(8)
    for command in (
        'fill 898 100 98 910 107 107 minecraft:air',
        'fill 898 99 98 910 99 107 minecraft:stone',
        'setblock 903 100 102 create:mechanical_piston[facing=east,axis_along_first=false]',
        *(f'setblock {x} 100 102 create:piston_extension_pole[facing=east]' for x in (900, 901, 902)),
        'setblock 904 100 102 minecraft:stone',
    ):
        host.command(command)
    host.call('camera', {'position': [905.45, 100, z], 'target': [904.5, 100.5, z]})
    before = step(8)
    free = step(20, ['setblock 903 100 101 create:creative_motor[facing=south]{ScrollValue:-32}'])
    wall = step(1, ['fill 907 101 101 907 104 103 minecraft:stone'])
    samples = [wall, *(step(1) for _ in range(32))]
    after = samples[-1]
    assert free['position'][0] > before['position'][0] + 0.45, (before, free)
    assert abs(free['position'][1] - before['position'][1]) < 1e-6, free
    assert abs(free['position'][2] - z) < 1e-6, free
    assert abs(after['position'][2] - expected_z) < 1e-9, after
    assert abs(after['position'][0] - 906.7) < 1e-5 and after['offset'] == 3.0, after
    assert abs(after['position'][1] - 100.0) < 1e-6, after
    return dict(before=before, free=free, obstructed=after, wall_ticks=samples)


def main():
    host = Original()
    assert host.call('state', {})['data_version'] == 3955
    cases = dict(south=run_side(host, 102.65, 103.30010011192093),
                 north=run_side(host, 102.35, 101.69989988807907))
    work = Path(tempfile.mkdtemp(prefix='side-contact-reference-', dir=ROOT / '.local'))
    path = work / 'result.json'
    path.write_text(json.dumps(dict(create=PINS['create_revision'], **cases), indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
