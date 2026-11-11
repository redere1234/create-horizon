#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Observe the original Super Glue selection, removal and offhand placement."""
import json
from pathlib import Path
import tempfile

from chain_drive_checks import Original, xyz
from common import PINS, ROOT
import reference_java as java


def run():
    manifest = json.loads((java.BASE / 'manifest.json').read_text())
    assert manifest['create_sha256'] == java.CREATE_SHA256 and manifest['data_version'] == 3955
    host = Original()
    assert host.call('state', {})['ready']
    work = Path(tempfile.mkdtemp(prefix='super-glue-java-', dir=ROOT / '.local'))
    result = dict(passed=False, create=PINS['create_revision'])
    first_corner = (1002, 100, 55)
    last_corner = (1003, 100, 55)
    support = (1002, 100, 58)
    placement = (1003, 100, 58)

    def call(method, **body):
        return host.call(method, body)

    def cmd(text):
        return host.command(text)

    def aim(pos, target):
        call('camera', position=pos, target=target, hide_gui=False)
        call('capture', name=f'{work.name}/aim.png', frames=15)
        return call('state')['hit']

    def click(key, name):
        call('input', key=key)
        call('capture', name=f'{work.name}/{name}.png', frames=16)
        call('input', key=key, down=False)

    def glue():
        entities = call('entities', center=first_corner, radius=10)['entities']
        return [entity for entity in entities if entity['type'] == 'create:super_glue']

    def held():
        return cmd('data get entity @s SelectedItem')['messages']

    try:
        call('tick', frozen=True)
        cmd('gamemode creative')
        cmd('tp @s 1002.5 99 52.5')
        cmd('forceload add 992 48 1023 63')
        call('observe_ticks', ticks=20, positions=[first_corner])
        cmd('kill @e[type=create:super_glue,distance=..10]')
        cmd('fill 1000 98 51 1007 98 62 minecraft:smooth_stone')
        cmd('fill 1000 99 51 1007 106 62 minecraft:air')
        cmd(f'setblock {xyz(first_corner)} minecraft:stone')
        cmd(f'setblock {xyz(last_corner)} minecraft:stone')
        cmd('clear @s')
        cmd('gamemode survival')
        cmd('item replace entity @s weapon.mainhand with create:super_glue 1')
        result['before'] = held()
        hit = aim([1002.5, 99, 52.5], [1002.5, 100.5, 55.5])
        assert tuple(hit['pos']) == first_corner, hit
        click('use', 'first')
        assert not glue()
        hit = aim([1003.5, 99, 52.5], [1003.5, 100.5, 55.5])
        assert tuple(hit['pos']) == last_corner, hit
        click('use', 'second')
        result['after'] = held()
        result['added'] = glue()
        assert len(result['added']) == 1, result
        volume = result['added'][0]
        assert volume['position'] == [1003.0, 100.0, 55.5], volume
        assert 'From:[-1.0d,0.0d,-0.5d]' in volume['nbt'], volume
        assert 'To:[1.0d,1.0d,0.5d]' in volume['nbt'], volume
        assert '"minecraft:damage": 2' in result['after'][0], result
        click('attack', 'remove')
        result['removed'] = not glue()
        result['after_remove'] = held()
        assert result['removed'] and result['after_remove'] == result['after'], result

        cmd('gamemode creative')
        cmd(f'setblock {xyz(support)} minecraft:stone')
        cmd('clear @s')
        cmd('gamemode survival')
        cmd('item replace entity @s weapon.mainhand with minecraft:stone 2')
        cmd('item replace entity @s weapon.offhand with create:super_glue 1')
        hit = aim([1006.5, 99, 58.5], [1002.5, 100.5, 58.5])
        assert tuple(hit['pos']) == support and hit['face'] == 'east', hit
        click('use', 'offhand')
        assert call('block', pos=placement)['id'] == 'minecraft:stone'
        result['offhand_added'] = glue()
        result['offhand_inventory'] = cmd('data get entity @s Inventory')['messages']
        assert len(result['offhand_added']) == 1, result
        assert '"minecraft:damage": 1' in result['offhand_inventory'][0], result
        result['passed'] = True
    finally:
        (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
        print(json.dumps(dict(passed=result['passed'], result=str(work / 'result.json'))), flush=True)


if __name__ == '__main__':
    run()
