#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare actual native offhand placement with the pinned Create replay."""

import argparse
import json
import re
from pathlib import Path

from common import PINS
from native_check_session import NativeCheckSession, wait_loaded
from saved_block_checks import read_saved_chunk_tag
from super_glue_offhand_checks import (
    AIR, GLUE, GRASS, STONE, SUPPORT, TARGET, VIEW, WIDE, WIDE_TARGET, place, xyz,
)

KEYS = ('horizon:attachments', 'create', 'super_glue', 'value')


def scenarios(session, reference, report):
    call = session.call

    def command(text):
        return call('command', text)['chat']

    def saved(pos=TARGET):
        call('save')
        stored = read_saved_chunk_tag(session.scratch, pos, KEYS, session.world)['nbt']
        if stored is None:
            return []
        assert stored['value']['Version']['value'] == 1, stored
        return [tag['value'] for tag in stored['value']['Volumes']['value']]

    def equip(*, creative=False, wear=0):
        command('clear @s')
        command('gamemode ' + ('creative' if creative else 'survival'))
        command('item replace entity @s weapon.mainhand with minecraft:stone 16')
        if wear is not None:
            data = f'[minecraft:damage={wear}]' if wear else ''
            command('item replace entity @s weapon.offhand with ' + GLUE + data)
        call('wait', 5)

    def tap(*, pos_view=VIEW, aimed=SUPPORT, button='right'):
        command('tp @s ' + xyz(pos_view))
        call('wait', 5)
        call('look-at', aimed[0] + 0.5, 105.62, aimed[2] + 0.5)
        call('wait', 4)
        hit = call('looking-at')['block']
        assert hit['pos'] == list(aimed), hit
        call('mouse', button, 'click')
        call('wait', 8)

    def clear_volume():
        command('gamemode survival')
        command('item replace entity @s weapon.mainhand with ' + GLUE)
        call('wait', 5)
        tap(aimed=TARGET, button='left')
        assert not saved(), 'Native attack did not clear the fixture glue'

    def server_stock():
        stock = ' '.join(command('data get entity @s SelectedItem.count'))
        return int(re.search(r'\b(\d+)\s*$', stock)[1])

    def check(name, *, pos=TARGET, placement=True, **aim):
        before = call('state')['held']['count']
        before_server = server_stock()
        tap(**aim)
        snapshot = call('state')
        server_count = server_stock()
        stack = call('inventory')['offhand']
        damage = stack.get('damage', 0) if stack and stack.get('item') == GLUE else None
        actual = dict(block=call('block', *pos)['block'], damage=damage, volumes=saved(pos),
                      consumed=before - snapshot['held']['count'],
                      server_consumed=before_server - server_count)
        report['cases'][name] = actual
        expected = reference[name]
        assert actual['block'] == expected['block'], (name, actual, expected)
        expected_spent = int(placement and snapshot['gamemode'] != 'creative')
        assert actual['consumed'] == actual['server_consumed'] == expected_spent, (name, actual)
        if name == 'crosses_column_boundary':
            assert not actual['volumes'] and actual['damage'] == 0 and not saved(WIDE), actual
            actual['known_java_difference'] = 'Cross-column glue volumes are not supported'
        else:
            assert actual['damage'] == expected['damage'], (name, actual, expected)
            wanted = [[*SUPPORT, *TARGET]] if expected['entities'] else []
            assert actual['volumes'] == wanted, (name, actual, expected)

    command('tp @s ' + xyz(VIEW))
    wait_loaded(call, [TARGET, WIDE_TARGET])
    command('fill 1252 104 102 1269 110 111 minecraft:air')
    command('fill 1252 103 102 1269 103 111 minecraft:smooth_stone')
    command(place(SUPPORT, STONE))
    call('select', 1)
    equip()
    check('survival')
    session.restart()
    wait_loaded(call, [TARGET, WIDE_TARGET])
    assert saved() == [[*SUPPORT, *TARGET]]
    assert call('inventory')['offhand']['damage'] == 1
    report['restart'] = dict(volume=saved(), damage=call('inventory')['offhand']['damage'])

    command(place(TARGET, AIR))
    check('already_glued')
    clear_volume()
    command(place(TARGET, AIR))
    equip(creative=True)
    check('creative')
    clear_volume()
    command(place(TARGET, AIR))
    equip(wear=98)
    check('breaks_offhand')
    clear_volume()
    command(place(TARGET, AIR))
    command(place(SUPPORT, 'create:mechanical_drill[facing=east]'))
    equip()
    check('invalid_drill_front')
    command(place(SUPPORT, AIR))
    command(place((1258, 104, 105), 'minecraft:dirt'))
    command(place(TARGET, GRASS))
    command(place((1256, 105, 105), STONE))
    equip(wear=None)
    check('replace_plant_control', aimed=TARGET)
    command(place(TARGET, GRASS))
    equip()
    check('nonadjacent_cancels_placement', aimed=TARGET, placement=False)
    command(place((1256, 105, 105), AIR))
    check('miss_allows_placement', aimed=TARGET)
    command(place(WIDE, STONE))
    equip()
    check('crosses_column_boundary', pos=WIDE_TARGET, aimed=WIDE,
          pos_view=(1267.4, 104, 109.5))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + key, required=True, type=Path)
    args = parser.parse_args()
    java = json.loads(args.reference.read_text())
    assert java['passed'] and java['source'] == PINS['create_revision']
    session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                 name='glue-offhand', world='SuperGlueOffhand')
    print(session.scratch, flush=True)
    report = dict(passed=False, source=java['source'], cases={})
    try:
        with session:
            scenarios(session, java['cases'], report)
        report['passed'] = True
    finally:
        output = session.scratch / 'result.json'
        output.write_text(json.dumps(report, indent=2) + '\n')
        print(output, flush=True)


if __name__ == '__main__':
    main()
