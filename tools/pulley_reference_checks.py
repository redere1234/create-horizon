#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Capture Rope Pulley pickup, stop and return in the isolated Java reference."""
import json
from pathlib import Path
import tempfile

from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT


CONTROLLER = (1130, 120, 58)
DOWN_MOTOR = (1129, 120, 58)
UP_MOTOR = (1131, 120, 58)
PATH = [CONTROLLER] + [(1130, y, 58) for y in range(119, 111, -1)]


def actuator_state(block):
    return [number(block, key, 0) for key in ('Offset', 'Running', 'InitialOffset')]


def main():
    original = Original()
    assert original.call('state', {})['data_version'] == 3955
    original.call('tick', {'frozen': True})
    original.command('gamemode creative')
    original.command('tp @s 1128.5 121 58.5')
    original.command('forceload add 1120 48 1135 63')

    def step(ticks, commands=()):
        return original.call('observe_ticks', {
            'ticks': ticks, 'positions': PATH, 'commands': commands,
        })['samples']

    def put(position, state):
        original.command(f'setblock {xyz(position)} {state}')

    step(32)
    original.command('fill 1124 112 50 1134 124 62 minecraft:air')
    put(CONTROLLER, 'create:rope_pulley')
    assert step(1)[-1]['blocks'][0]['properties'] == {'axis': 'x'}
    put(PATH[3], 'minecraft:oak_log[axis=y]')
    put(DOWN_MOTOR, 'create:creative_motor[facing=east]{ScrollValue:128}')
    down = step(22)
    assert [actuator_state(row['blocks'][0]) for row in down[8:11]] == [
        [1.75, 1, 0], [2, 0, 0], [2, 1, 2],
    ]
    assert [block['id'] for block in down[9]['blocks'][1:4]] == [
        'create:rope', 'create:pulley_magnet', 'minecraft:oak_log',
    ]
    # Apply the removal while effective RPM is still available. A frozen
    # command hides that RPM and bypasses the original sign-change snap.
    stop = step(1, ['tick unfreeze', f'setblock {xyz(DOWN_MOTOR)} minecraft:air'])
    assert actuator_state(stop[0]['blocks'][0]) == [4, 0, 0]
    assert [block['id'] for block in stop[0]['blocks'][1:6]] == [
        *(['create:rope'] * 3), 'create:pulley_magnet', 'minecraft:oak_log',
    ]
    put(UP_MOTOR, 'create:creative_motor[facing=west]{ScrollValue:128}')
    up = step(25)
    assert actuator_state(up[-1]['blocks'][0]) == [0, 0, 0]
    assert up[-1]['blocks'][1]['id'] == 'minecraft:oak_log'
    assert all(block['id'] == 'minecraft:air' for block in up[-1]['blocks'][2:])
    result = {'passed': True, 'create': PINS['create_revision'], 'down': down, 'stop': stop, 'up': up}
    work = Path(tempfile.mkdtemp(prefix='pulley-reference-', dir=ROOT / '.local'))
    (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    (work / 'transcript.json').write_text(json.dumps(original.trace, indent=2) + '\n')
    print(json.dumps({'result': str(work / 'result.json'), 'samples': len(down) + len(stop) + len(up)}))


if __name__ == '__main__':
    main()
