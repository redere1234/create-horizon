#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Record three Mechanical Bearing scenes in the isolated Java Create client."""
import json
from pathlib import Path
import tempfile

from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT


def offset(pos, direction, scale=1):
    return tuple(p + v * scale for p, v in zip(pos, direction, strict=True))


PAYLOAD_PIVOT = (904, 100, 72)
PAYLOAD_MOTOR = offset(PAYLOAD_PIVOT, (0, -1, 0))
PAYLOAD_ANCHOR = offset(PAYLOAD_PIVOT, (0, 1, 0))
PAYLOAD_RIM = tuple(offset(PAYLOAD_ANCHOR, side) for side in (
    (1, 0, 0), (0, 0, -1), (-1, 0, 0), (0, 0, 1),
))
PAYLOAD_IDS = (
    'minecraft:red_concrete', 'minecraft:cyan_stained_glass',
    'minecraft:light_gray_terracotta', 'minecraft:blue_wool',
)


def put_payload(put):
    put(PAYLOAD_PIVOT, 'create:mechanical_bearing[facing=up]')
    put(PAYLOAD_ANCHOR, 'minecraft:slime_block')
    for position, block in zip(PAYLOAD_RIM, PAYLOAD_IDS, strict=True):
        put(position, block)
    put(PAYLOAD_MOTOR, 'create:creative_motor[facing=up]{ScrollValue:32}')


def payload_reference(step, put):
    positions = [PAYLOAD_PIVOT, PAYLOAD_ANCHOR, *PAYLOAD_RIM]
    put_payload(put)
    moving = step(10, positions)[-1]['blocks']
    assert number(moving[0], 'Running') == 1 and number(moving[0], 'Angle') > 45, moving
    assert [block['id'] for block in moving[1:]] == ['minecraft:air'] * 5, moving
    put(PAYLOAD_MOTOR, 'minecraft:air')
    final = step(1, positions)[-1]['blocks']
    assert number(final[0], 'Running') == 0, final
    landed = [block['id'] for block in final[1:]]
    assert landed == ['minecraft:slime_block', PAYLOAD_IDS[-1], *PAYLOAD_IDS[:-1]], final
    return dict(angle=number(moving[0], 'Angle'), landed=landed)


def main():
    host = Original()
    assert host.call('state', {})['data_version'] == 3955
    host.call('tick', {'frozen': True})
    host.command('gamemode creative')
    host.command('tp @s 901.5 101 50.5')
    host.command('forceload add 896 32 927 79')

    def step(ticks, points):
        return host.call('observe_ticks', {'ticks': ticks, 'positions': points})['samples']

    def put(pos, state):
        host.command(f'setblock {xyz(pos)} {state}')

    step(40, [(900, 100, 50)])
    host.command('fill 897 95 35 925 109 72 minecraft:air')
    cases = [
        ('east', (1, 0, 0), 'z', (0, 0, 1), 'y', (0, -1, 0)),
        ('up', (0, 1, 0), 'z', (0, 0, 1), 'x', (1, 0, 0)),
        ('south', (0, 0, 1), 'x', (1, 0, 0), 'y', (0, 1, 0)),
    ]
    expected = [0.0, 9.6, 19.2, 28.800001, 38.4, 48.0, 57.6, 67.2, 76.799995, 86.399994]
    rows = []
    for index, (facing, axis, log_axis, radial, final_axis, target) in enumerate(cases):
        pivot = (903 + 7 * index, 100, 50)
        anchor = offset(pivot, axis)
        motor = offset(pivot, axis, -1)
        log = offset(anchor, radial)
        landing = offset(anchor, target)
        put(pivot, f'create:mechanical_bearing[facing={facing}]')
        put(anchor, 'minecraft:slime_block')
        put(log, f'minecraft:oak_log[axis={log_axis}]')
        put(motor, f'create:creative_motor[facing={facing}]{{ScrollValue:32}}')

        trace = step(10, [pivot, anchor, log])
        controllers = [sample['blocks'][0] for sample in trace]
        assert [number(block, 'Angle') for block in controllers] == expected, trace
        assert [number(block, 'Running') for block in controllers] == [0] + [1] * 9, trace
        assert [block['id'] for block in trace[0]['blocks'][1:]] == [
            'minecraft:slime_block', 'minecraft:oak_log'
        ], trace
        assert all(block['id'] == 'minecraft:air' for sample in trace[1:]
                   for block in sample['blocks'][1:]), trace

        put(motor, 'minecraft:air')
        final = step(1, [pivot, anchor, log, landing])[-1]['blocks']
        assert number(final[0], 'Running') == number(final[0], 'Angle') == 0, final
        assert [block['id'] for block in final[1:]] == [
            'minecraft:slime_block', 'minecraft:air', 'minecraft:oak_log'
        ], final
        assert final[-1]['properties']['axis'] == final_axis, final
        rows.append(dict(facing=facing, trace=trace, final=final))

    host.command('fill 900 96 69 909 106 75 minecraft:air')
    payload = payload_reference(step, put)
    work = Path(tempfile.mkdtemp(prefix='bearing-reference-', dir=ROOT / '.local'))
    report = dict(passed=True, create=PINS['create_revision'], cases=rows, payload=payload)
    (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
    print(json.dumps(dict(result=str(work / 'result.json'), samples=len(expected) * len(cases))))


if __name__ == '__main__':
    main()
