#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Check chassis grouping and payload capture in the pinned Java client."""
import json
from pathlib import Path
import tempfile

from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT


STONE = 'minecraft:stone'
LINEAR = 'create:linear_chassis'
SECONDARY = 'create:secondary_linear_chassis'
RADIAL = 'create:radial_chassis'


def chassis(block, axis, distance, sticky):
    return f'{block}[axis={axis},{sticky}=true]{{ScrollValue:{distance}}}'


def rig(host, pivot, payload, control):
    x, y, z = pivot
    motor = (x, y - 1, z)
    positions = [pivot, *payload, *control]
    host.command(f'tp @s {x}.5 {y + 2} {z}.5')
    host.command(f'forceload add {x - 4} {z - 4} {x + 4} {z + 4}')

    def observe(ticks, commands=()):
        return host.call('observe_ticks', {
            'ticks': ticks, 'positions': positions, 'commands': commands,
        })['samples'][-1]['blocks']

    observe(8)
    host.command(f'fill {x - 4} {y - 2} {z - 4} {x + 4} {y + 4} {z + 4} minecraft:air')
    host.command(f'setblock {xyz(pivot)} create:mechanical_bearing[facing=up]')
    for pos, state in {**payload, **control}.items():
        host.command(f'setblock {xyz(pos)} {state}')
    before = observe(3)
    assert [block['id'] for block in before[1:]] == [
        state.split('[')[0] for state in [*payload.values(), *control.values()]
    ], before
    moving = observe(4, [f'setblock {xyz(motor)} create:creative_motor[facing=up]{{ScrollValue:32}}'])
    assert number(moving[0], 'Running', 0) == 1, moving[0]
    assert [b['id'] for b in moving[1:]] == ['minecraft:air'] * len(payload) + [
        state.split('[')[0] for state in control.values()
    ], moving
    landed = observe(2, [f'setblock {xyz(motor)} minecraft:air'])
    assert number(landed[0], 'Running', 0) == 0, landed[0]
    assert [b['id'] for b in landed[1:]] == [b['id'] for b in before[1:]], landed
    for source, restored in zip(before[1:], landed[1:]):
        assert source['properties'] == restored['properties'], (source, restored)
        if source['id'] in (LINEAR, SECONDARY, RADIAL):
            assert number(source, 'ScrollValue') == number(restored, 'ScrollValue'), (source, restored)
    return dict(before=before, moving=moving, landed=landed)


def scenes():
    linear = ((1048, 100, 87), {
        (1048, 101, 87): chassis(LINEAR, 'x', 2, 'sticky_top'),
        (1049, 101, 87): STONE,
        (1050, 101, 87): STONE,
        (1048, 101, 88): chassis(LINEAR, 'x', 1, 'sticky_bottom'),
        (1047, 101, 88): STONE,
    }, {
        (1051, 101, 87): STONE,
        (1047, 101, 87): STONE,
        (1048, 101, 86): f'{SECONDARY}[axis=x]',
        (1048, 102, 87): f'{LINEAR}[axis=z]',
    })
    radial = ((1048, 100, 104), {
        (1048, 101, 104): chassis(RADIAL, 'y', 2, 'sticky_east'),
        (1049, 101, 104): STONE,
        (1050, 101, 104): STONE,
        (1050, 101, 105): STONE,
        (1048, 102, 104): chassis(RADIAL, 'y', 1, 'sticky_north'),
        (1048, 102, 103): STONE,
    }, {
        (1050, 101, 106): STONE,
        (1047, 101, 104): STONE,
        (1049, 102, 104): STONE,
        (1048, 101, 103): f'{RADIAL}[axis=y]',
    })
    return dict(linear=linear, radial=radial)


def main():
    host = Original()
    assert host.call('state', {})['data_version'] == 3955
    host.call('tick', {'frozen': True})
    host.command('gamemode creative')
    observed = {name: rig(host, *scene) for name, scene in scenes().items()}
    work = Path(tempfile.mkdtemp(prefix='chassis-reference-', dir=ROOT / '.local'))
    path = work / 'result.json'
    path.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], **observed),
                               indent=2) + '\n')
    (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
    print(json.dumps(dict(passed=True, result=str(path))))


if __name__ == '__main__':
    main()
