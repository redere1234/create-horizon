#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Check sail interactions and windmill capture in the pinned Java client."""
import json
from pathlib import Path
import tempfile

from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
import reference_java as java

SAIL = (1091, 100, 55)
NEIGHBOR = (1092, 100, 55)
PIVOT = (1100, 100, 55)
SHAFT = (1099, 100, 55)
ROTOR = {
    (1101, 100 + dy, 55 + dz): f'create:{name}[facing=east]'
    for (dy, dz), name in zip(
        [(0, 0), (-1, 0), (1, 0), (0, -1), (0, 1), (1, 1), (-1, -1), (1, -1)],
        ['sail_frame', 'sail_frame', 'white_sail', 'yellow_sail', 'white_sail',
         'cyan_sail', 'blue_sail', 'black_sail'],
        strict=True,
    )
}
AXIAL = (1102, 100, 55)


def run():
    manifest = json.loads((java.BASE / 'manifest.json').read_text())
    assert manifest['create_sha256'] == java.CREATE_SHA256 and manifest['data_version'] == 3955
    host = Original()
    assert host.call('state', {})['ready']
    work = Path(tempfile.mkdtemp(prefix='sail-reference-', dir=ROOT / '.local'))
    report = dict(passed=False, create=PINS['create_revision'])

    def put(pos, block):
        return host.command(f'setblock {xyz(pos)} {block}')

    def click(label, pos, eye, target):
        host.call('camera', {'position': eye, 'target': target})
        host.call('capture', {'name': f'{work.name}/{label}-before.png', 'frames': 12})
        hit = host.call('state', {})['hit']
        assert tuple(hit['pos']) == pos, hit
        host.call('input', {'key': 'use'})
        host.call('capture', {'name': f'{work.name}/{label}-after.png', 'frames': 8})
        host.call('input', {'key': 'use', 'down': False})

    def tick(points, count=3):
        return host.call('observe_ticks', {'positions': points, 'ticks': count})['samples'][-1]['blocks']

    def mainhand(item):
        host.command(f'item replace entity @s weapon.mainhand with {item}')

    def hand():
        return host.command('data get entity @s SelectedItem')['messages'][0].split(': ', 1)[1]

    try:
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        host.command('tp @s 1092.5 99 58.5')
        host.command('forceload add 1088 48 1119 63')
        tick([SAIL], 20)
        host.command('fill 1089 95 51 1106 106 61 minecraft:air')
        host.command('fill 1089 98 57 1096 98 61 minecraft:smooth_stone')
        host.command('fill 1096 98 54 1100 98 56 minecraft:smooth_stone')
        host.command('clear @s')
        put(SAIL, 'create:white_sail[facing=south]')
        put(NEIGHBOR, 'create:blue_sail[facing=south]')
        host.command('gamemode survival')
        eye = [1091.85, 99, 58.5]
        edge = [1091.85, 100.52, 55.5]
        mainhand('minecraft:red_dye 5')
        click('dye', SAIL, eye, edge)
        report['dye'] = tick([SAIL, NEIGHBOR])
        assert [s['id'] for s in report['dye']] == ['create:red_sail', 'create:blue_sail'], report['dye']
        assert report['dye'][0]['properties']['facing'].lower() == 'south', report['dye']
        report['dye_inventory'] = hand()
        assert report['dye_inventory'] == '{count: 5, id: "minecraft:red_dye"}', report
        click('dye-adjacent', SAIL, eye, edge)
        report['dye_adjacent'] = tick([SAIL, NEIGHBOR])
        assert [s['id'] for s in report['dye_adjacent']] == ['create:red_sail'] * 2, report['dye_adjacent']

        mainhand('minecraft:shears')
        click('shear', SAIL, eye, edge)
        report['shear'] = tick([SAIL, NEIGHBOR])
        assert [s['id'] for s in report['shear']] == ['create:sail_frame', 'create:red_sail'], report['shear']
        report['shears_inventory'] = hand()
        assert report['shears_inventory'] == '{count: 1, id: "minecraft:shears"}', report

        put(NEIGHBOR, 'minecraft:air')
        mainhand('create:white_sail 3')
        click('place-adjacent', SAIL, eye, edge)
        report['placement'] = tick([SAIL, NEIGHBOR])
        assert report['placement'][1]['id'] == 'create:white_sail', report['placement']
        assert report['placement'][1]['properties']['facing'].lower() == 'south', report['placement']
        report['placement_inventory'] = hand()
        assert report['placement_inventory'] == '{count: 2, id: "create:white_sail"}', report

        host.command('gamemode creative')
        host.command('clear @s')
        put(PIVOT, 'create:windmill_bearing[facing=east]')
        put(SHAFT, 'create:shaft[axis=x]')
        for pos, block in ROTOR.items():
            put(pos, block)
        put(AXIAL, 'create:orange_sail[facing=east]')
        pts = [PIVOT, SHAFT, *ROTOR, AXIAL]
        tick(pts, 12)
        eye = [1097.2, 99, 55.84]
        target = [1100.5, 100.75, 55.84]
        click('run', PIVOT, eye, target)
        report['rotating'] = running = tick(pts, 20)
        assert number(running[0], 'Running') == number(running[0], 'LastGenerated') == 1, running[:2]
        assert number(running[1], 'Speed') == 1, running[:2]
        assert all(s['id'] == 'minecraft:air' for s in running[2:-1]), running[2:]
        assert running[-1]['id'] == 'create:orange_sail', running[-1]
        click('stop', PIVOT, eye, target)
        report['landed'] = landed = tick(pts, 16)
        assert number(landed[0], 'Running') == 0, landed[0]
        assert all(s['id'] == block.split('[')[0] and s['properties']['facing'].lower() == 'east'
                   for s, block in zip(landed[2:-1], ROTOR.values(), strict=True)), landed[2:]
        report['passed'] = True
    finally:
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
        print(json.dumps(dict(result=str(work / 'result.json'), passed=report['passed'])))


if __name__ == '__main__':
    run()
