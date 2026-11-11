#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Exercise the Windmill Bearing with real right clicks in the isolated Java reference."""
import hashlib
import json
from pathlib import Path
import tempfile

from burner_heat_java_checks import number
from chain_drive_checks import xyz
from common import PINS, ROOT
import reference_java as java

PIVOT = (938, 100, 55)
SHAFT = (937, 100, 55)
COLORS = (
    'white', 'orange', 'magenta', 'light_blue', 'yellow', 'lime', 'pink', 'gray',
    'light_gray', 'cyan', 'purple', 'blue', 'brown', 'green', 'red', 'black',
)


def structure(sails):
    blocks = {(939, 100, 55 + index): 'minecraft:slime_block' for index in range(min(8, sails))}
    for index, color in enumerate(COLORS[:sails]):
        x, y = (940, 100) if index < 8 else (939, 101)
        blocks[x, y, 55 + index % 8] = f'minecraft:{color}_wool'
    return blocks


def run():
    manifest = json.loads((java.BASE / 'manifest.json').read_text())
    assert manifest['data_version'] == 3955 and manifest['create_sha256'] == java.CREATE_SHA256
    work = Path(tempfile.mkdtemp(prefix='windmill-reference-', dir=ROOT / '.local'))
    result = dict(
        passed=False,
        create=PINS['create_revision'],
        fixture_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        cases={},
    )
    trace = []

    def call(method, **body):
        reply = java.call(java.BASE, method, body)
        trace.append(dict(method=method, body=body, reply=reply))
        return reply

    def command(value):
        return call('command', command=value)

    def put(pos, block):
        command(f'setblock {xyz(pos)} {block}')

    def observe(ticks, points):
        return call('observe_ticks', ticks=ticks, positions=points)['samples']

    def click(name):
        filename = f'{work.name}/{name}.png'
        call('capture', name=filename, frames=16)
        state = call('state')
        hit = state['hit']
        assert state['held'] == 'minecraft:air' and hit['block'] == 'create:windmill_bearing', state
        assert tuple(hit['pos']) == PIVOT and hit['face'] == 'west', hit
        call('input', key='use')
        call('capture', name=filename, frames=12)
        call('input', key='use', down=False)

    try:
        state = call('state')
        assert state['ready'] and state['data_version'] == manifest['data_version'], state
        call('tick', frozen=True)
        command('gamemode creative')
        command('tp @s 935.2 99 55.84')
        command('forceload add 928 48 959 79')
        observe(24, [PIVOT])
        command('fill 934 96 50 943 115 73 minecraft:air')
        command('fill 934 98 50 938 98 55 minecraft:smooth_stone')
        command('clear @s')
        # The side faces contain the scroll-value hit box. Aim around the
        # shaft at the rear bearing face to exercise assembly instead.
        call('camera', position=[935.2, 99, 55.84], target=[938.5, 100.75, 55.84], hide_gui=False)
        put(PIVOT, 'create:windmill_bearing[facing=east]')
        put(SHAFT, 'create:creative_motor[facing=east]{ScrollValue:32}')
        initial = structure(7)
        for pos, block in initial.items():
            put(pos, block)

        result['cases']['powered_without_click'] = observe(12, [PIVOT, SHAFT, *initial])
        powered = result['cases']['powered_without_click'][-1]['blocks']
        assert number(powered[1], 'Speed') == 32, powered
        assert number(powered[0], 'Running') == number(powered[0], 'LastGenerated') == 0, powered
        assert [block['id'] for block in powered[2:]] == list(initial.values()), powered

        put(SHAFT, 'create:shaft[axis=x]')
        click('seven-sails')
        result['cases']['seven_sails'] = observe(8, [PIVOT, SHAFT, *initial])
        refused = result['cases']['seven_sails'][-1]['blocks']
        assert number(refused[0], 'Running') == number(refused[0], 'LastGenerated') == 0, refused
        assert 'not_enough_sails' in refused[0]['nbt'], refused
        assert [block['id'] for block in refused[2:]] == list(initial.values()), refused

        previous = initial
        for sails, rpm, direction in [(8, 1, 0), (16, -2, 1)]:
            name = f'{sails}_sails'
            blocks = structure(sails)
            for pos in blocks.keys() - previous.keys():
                put(pos, blocks[pos])
            if direction:
                command(f'data merge block {xyz(PIVOT)} {{ScrollValue:{direction}}}')
            points = [PIVOT, SHAFT, *blocks]
            result['cases'][name] = phase = {}
            phase['idle'] = observe(8, points)
            idle = phase['idle'][-1]['blocks']
            assert number(idle[0], 'Running') == number(idle[0], 'LastGenerated') == 0, idle
            assert [block['id'] for block in idle[2:]] == list(blocks.values()), idle

            click(name + '-assemble')
            phase['running'] = observe(16, points)
            turning = phase['running'][-1]['blocks']
            assert number(turning[0], 'Running') == 1, turning
            assert number(turning[0], 'LastGenerated') == number(turning[0], 'Speed') == rpm, turning
            assert number(turning[1], 'Speed') == rpm, turning
            assert number(turning[0], 'Angle') * rpm > 0, turning
            assert all(block['id'] == 'minecraft:air' for block in turning[2:]), turning
            call('capture', name=f'{work.name}/{name}-running.png', frames=8)

            click(name + '-disassemble')
            phase['restored'] = observe(8, points)
            restored = phase['restored'][-1]['blocks']
            assert number(restored[0], 'Running') == number(restored[0], 'LastGenerated') == 0, restored
            assert number(restored[0], 'Angle') == number(restored[1], 'Speed') == 0, restored
            assert [block['id'] for block in restored[2:]] == list(blocks.values()), restored
            previous = blocks
        result['passed'] = True
    finally:
        (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        (work / 'transcript.json').write_text(json.dumps(trace, indent=2) + '\n')
    print(json.dumps(dict(result=str(work / 'result.json'), cases=len(result['cases']))))


if __name__ == '__main__':
    run()
