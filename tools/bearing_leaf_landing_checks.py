#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Check vertical bearing landing through ordinary dry foliage."""
import argparse
import json
from pathlib import Path
import re

from bearing_native_checks import Batch
from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from deployer_farm_checks import PIVOT, start, stop
from native_check_session import NativeCheckSession
from saved_block_checks import read_saved_chunk_tag

ANCHOR = (1159, 100, 55)
LOG = (1160, 100, 55)
AIR = 'minecraft:air'
LEAF = 'minecraft:oak_leaves[persistent=true,waterlogged=false]'
WET = 'minecraft:oak_leaves[persistent=true,waterlogged=true]'
LOG_STATE = 'minecraft:oak_log[axis=x]'
SCENE = ('horizon:attachments', 'create', 'moving_structures', 'value')
ITEMS = '@e[type=minecraft:item,x=1154,y=96,z=50,dx=11,dy=9,dz=11]'


def put(command, position, state):
    command(f'setblock {xyz(position)} {state}')


def setup(command):
    command('fill 1154 97 51 1164 105 61 minecraft:air')
    put(command, PIVOT, 'create:mechanical_bearing[facing=up]')
    put(command, ANCHOR, 'minecraft:slime_block')
    put(command, LOG, LOG_STATE)
    start(command)


def java_review():
    host = Original()
    assert host.call('state', {})['data_version'] == 3955
    host.call('tick', {'frozen': True})
    try:
        host.command('gamemode creative')
        host.command('tp @s 1155.5 106 60.5')
        host.command('forceload add 1152 48 1167 63')
        host.call('observe_ticks', {'ticks': 20, 'positions': [PIVOT]})
        setup(host.command)
        positions = [PIVOT, ANCHOR, LOG]
        before = host.call('observe_ticks', {'ticks': 2, 'positions': positions})['samples'][-1]['blocks']
        assert [block['id'] for block in before[1:]] == [AIR, AIR], before
        put(host.command, ANCHOR, LEAF)
        put(host.command, LOG, LEAF)
        stop(host.command)
        after = host.call('observe_ticks', {'ticks': 2, 'positions': positions})['samples'][-1]['blocks']
        assert number(after[0], 'Running') == 0, after
        assert [block['id'] for block in after[1:]] == ['minecraft:slime_block', 'minecraft:oak_log'], after
        assert after[-1]['properties']['axis'] == 'x', after
        print(json.dumps(dict(passed=True, before=before, landed=after)))
    finally:
        stop(host.command)
        host.command('forceload remove 1152 48 1167 63')
        host.call('tick', {'frozen': False})


def loaded_batch():
    batch = Batch()
    batch.load((1155, 106, 60))
    return batch


def no_item(batch):
    batch.command(f'execute if entity {ITEMS} run say unexpected_leaf_loot', True)


def record(session):
    return read_saved_chunk_tag(session.scratch, PIVOT, SCENE, session.world)['nbt']


def native_case(session, obstacle):
    batch = loaded_batch()
    setup(batch.command)
    batch.tick(2)
    for p in (ANCHOR, LOG):
        batch.expect(p, AIR)
    batch.put(ANCHOR, LEAF)
    batch.put(LOG, obstacle or LEAF)
    if obstacle is None:
        batch.command('gamerule minecraft:block_drops false')
    stop(batch.command)
    batch.tick(2)
    batch.data(PIVOT)
    batch.expect(ANCHOR, LEAF if obstacle else 'minecraft:slime_block')
    batch.expect(LOG, obstacle or LOG_STATE)
    no_item(batch)
    rows = batch.run(session, 'attempt')
    assert all('bearing_check' in raw for raw in rows[:2] + rows[3:5]), rows
    assert number({'nbt': rows[2]}, 'Running') == int(obstacle is not None), rows
    assert 'unexpected_leaf_loot' not in rows[-1], rows
    if obstacle:
        assert record(session) is not None
        batch = loaded_batch()
        batch.expect(ANCHOR, LEAF)
        batch.expect(LOG, obstacle)
        batch.put(LOG, AIR)
        batch.tick(4)
        batch.data(PIVOT)
        batch.expect(ANCHOR, 'minecraft:slime_block')
        batch.expect(LOG, LOG_STATE)
        rows = batch.run(session, 'retry-after-restart')
        assert number({'nbt': rows[2]}, 'Running') == 0, rows
        assert all('bearing_check' in raw for raw in rows[:2] + rows[3:]), rows
    assert record(session) is None
    return True


def item_count(raw):
    found = re.search(r'count:\s*(\d+)', raw, re.IGNORECASE)
    assert found, raw
    return int(found[1])


def native_loot_replay(session):
    # Enough original bare-hand rolls to exercise real item persistence in
    # the fixed seed fixture without changing a vanilla loot table.
    batch = loaded_batch()
    setup(batch.command)
    batch.command('fill 1156 100 52 1162 100 58 minecraft:slime_block')
    batch.tick(2)
    batch.expect(ANCHOR, AIR)
    batch.command(f'fill 1156 100 52 1162 100 58 {LEAF}')
    stop(batch.command)
    batch.tick()
    batch.expect(ANCHOR, 'minecraft:slime_block')
    batch.command(f'execute if entity {ITEMS}', True)
    rows = batch.run(session, 'successful-leaf-loot')
    assert all('bearing_check' in row for row in rows[:2]), rows
    count = item_count(rows[-1])
    assert count > 0 and record(session) is None, rows

    batch = loaded_batch()
    batch.command(f'execute if entity {ITEMS}', True)
    batch.expect(ANCHOR, 'minecraft:slime_block')
    rows = batch.run(session, 'successful-leaf-loot-restart')
    assert item_count(rows[0]) == count and 'bearing_check' in rows[1], rows
    assert record(session) is None
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java:
        java_review()
        return
    if not all((args.game, args.resources, args.ctl)):
        parser.error('Pass --java or --game, --resources and --ctl')
    session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                 name='bearing-leaf-landing', graphics=False)
    print(session.scratch, flush=True)
    result = {}
    for name, obstacle in [('dry', None), ('solid', 'minecraft:stone'), ('wet', WET)]:
        session.world = name
        result[name] = native_case(session, obstacle)
    session.world = 'loot'
    result['persisted_item_entities'] = native_loot_replay(session)
    (session.scratch / 'result.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
