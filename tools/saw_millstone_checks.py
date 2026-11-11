#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare direct Saw-to-Millstone transfer, backpressure and native restart."""
import argparse
import errno
import json
from pathlib import Path
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field, items, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession
from reference_java import BASE, CREATE_SHA256


ACCEPT = ((1775, 168, 703), (1776, 168, 703))
REJECT = ((1808, 168, 703), (1807, 168, 703))
PARTIAL = ((1791, 168, 703), (1792, 168, 703))
WRONG_SIDE = (1774, 168, 703)
POINTS = [*ACCEPT, *REJECT, *PARTIAL, WRONG_SIDE]
CENTER = (1792, 175, 700)
LOAD = '1774 700 1808 703'
REGION = '1773 167 700 1809 175 703'
DROPS = '@e[type=minecraft:item,x=1773,y=164,z=700,dx=36,dy=12,dz=5]'
WHEAT = 'minecraft:wheat'
DIAMOND = 'minecraft:diamond'
TICKS = {'full': 1, 'drops_and_partial': 18, 'retained': 2, 'cleared': 3}


def stack(item, count, marker):
    return f'id:"{item}",count:{count},components:{{"minecraft:custom_data":{{saw_mill_marker:{marker}}}}}'


def stock(count):
    contents = f'{{Slot:0,{stack(WHEAT, count, 303)}}}' if count else ''
    return f'data merge block {xyz(PARTIAL[1])} {{InputInventory:{{Size:1,Items:[{contents}]}}}}'


def setup(command, *, native=False):
    command(f'fill {REGION} minecraft:air')
    command(f'kill {DROPS}')
    for saw, millstone in (ACCEPT, REJECT, PARTIAL):
        command(f'setblock {xyz(saw)} create:mechanical_saw[facing=up,axis_along_first=false]')
        command(f'setblock {xyz(millstone)} create:millstone')
    command(f'setblock {xyz(WRONG_SIDE)} create:millstone')
    command(stock(64))
    seed = stack(WHEAT, 3, 303)
    completed = f'[{{Slot:0,{seed}}}]'
    # Horizon's generic Items save format only accepts its exact byte slot tag.
    live = f',Items:[{{Slot:0b,{seed}}}]' if native else ''
    command(f'data merge block {xyz(PARTIAL[0])} {{Inventory:{{Size:32,Items:{completed},'
            f'ProcessingTime:0f,RecipeTime:20f,AppliedRecipe:1b}}{live}}}')
    for ((x, y, z), _), rpm in ((ACCEPT, 128), (REJECT, -128), (PARTIAL, 128)):
        command(f'setblock {x} {y} {z - 1} create:creative_motor[facing=south]{{ScrollValue:{rpm}}}')


def phase(command, name):
    if name == 'drops_and_partial':
        command(stock(63))
        for ((x, y, z), _), item, marker in ((ACCEPT, WHEAT, 101), (REJECT, DIAMOND, 202)):
            command(f'summon minecraft:item {x + .5} {y + 1.3} {z + .5} '
                    f'{{PickupDelay:32767s,Item:{{{stack(item, 1, marker)}}}}}')
    elif name == 'cleared':
        command(stock(0))


def slot(raw, key):
    if key + ':' not in raw:
        return None
    contents = field(raw, key)
    stacks = items(raw, key)
    if not stacks:
        return None
    [(item, count)] = stacks.items()
    index = int(number({'nbt': contents}, 'Slot'))
    marker = int(number({'nbt': contents}, 'saw_mill_marker'))
    return [index, item, count, marker]


def sample(raw):
    result = []
    for i, nbt in enumerate(raw):
        assert ('create:saw' if i in (0, 2, 4) else 'create:millstone') in nbt, nbt
        if i in (0, 2, 4):
            tag = {'nbt': nbt}
            result.append(dict(stack=slot(nbt, 'Inventory'), rpm=number(tag, 'Speed'),
                               cycle=[number(tag, 'ProcessingTime', -1), number(tag, 'RecipeTime', 0),
                                      number(tag, 'AppliedRecipe', 0), number(tag, 'RecipeIndex', 0)]))
        else:
            result.append(dict(stack=slot(nbt, 'InputInventory'),
                               output=items(nbt, 'OutputInventory') if 'OutputInventory:' in nbt else {}))
    return result


def verify(phases):
    full = phases['full'][0]
    assert full[4] == dict(stack=[0, WHEAT, 3, 303], rpm=128, cycle=[0, 20, 1, 0]), full
    assert full[5]['stack'] == [0, WHEAT, 64, 303], full
    timeline = phases['drops_and_partial']
    for state in timeline:
        assert state[4] == dict(full[4], stack=[0, WHEAT, 2, 303]), state
        assert state[5] == full[5], state
        assert state[3]['stack'] is None and state[6]['stack'] is None, state
    delivered = next(i for i, state in enumerate(timeline) if state[1]['stack'] is not None)
    assert delivered > 0 and timeline[delivered - 1][0]['stack'] == [0, WHEAT, 1, 101], timeline
    settled = timeline[-1]
    assert timeline[delivered] == settled, timeline
    assert settled[0] == dict(stack=None, rpm=128, cycle=[0, 20, 1, 0]), settled
    assert settled[1]['stack'] == [0, WHEAT, 1, 101], settled
    assert settled[2] == dict(stack=[0, DIAMOND, 1, 202], rpm=-128, cycle=[0, 20, 1, 0]), settled
    assert all(state == settled for state in phases['retained']), phases['retained']
    cleared = [*settled[:4], dict(settled[4], stack=None),
               dict(settled[5], stack=[0, WHEAT, 2, 303]), settled[6]]
    assert all(state == cleared for state in phases['cleared']), phases['cleared']
    return delivered + 1


def java_run(work):
    host = Original()
    manifest = json.loads((BASE / 'manifest.json').read_text())
    assert manifest['create_sha256'] == CREATE_SHA256
    state = host.call('state', {})
    assert state['ready'] and state['data_version'] == 3955, state
    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {LOAD}')
        host.call('observe_ticks', {'positions': [list(map(int, state['position']))], 'ticks': 40})
        setup(host.command)
        host.call('observe_ticks', {'positions': POINTS, 'ticks': 12})
        phases = {}
        for name, ticks in TICKS.items():
            phase(host.command, name)
            reply = host.call('observe_ticks', {'positions': POINTS, 'ticks': ticks})
            phases[name] = [sample([block['nbt'] for block in row['blocks']]) for row in reply['samples']]
            drops = host.command(f'execute if entity {DROPS} run say loose_saw_millstone')
            assert not any('loose_saw_millstone' in row for row in drops['messages']), drops
        return phases
    finally:
        host.command(f'fill {REGION} minecraft:air')
        host.command(f'kill {DROPS}')
        host.command(f'forceload remove {LOAD}')
        host.call('tick', {'frozen': state['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    phases = {}
    for label, names in [('before-restart', ('full', 'drops_and_partial')),
                         ('after-restart', ('retained', 'cleared'))]:
        batch = Batch()
        batch.load(CENTER)
        for pos in POINTS:
            batch.command(f'execute if loaded {xyz(pos)} run say loaded_saw_millstone', True)
        if label == 'before-restart':
            setup(batch.command, native=True)
            batch.tick(12)
        for name in names:
            phase(batch.command, name)
            for _ in range(TICKS[name]):
                batch.tick()
                for pos in POINTS:
                    batch.data(pos)
            batch.command(f'execute if entity {DROPS} run say loose_saw_millstone', True)
        values = batch.run(session, label)
        assert all('loaded_saw_millstone' in row for row in values[:len(POINTS)]), values[:len(POINTS)]
        offset = len(POINTS)
        for name in names:
            end = offset + len(POINTS) * TICKS[name]
            phases[name] = [sample(values[i:i + len(POINTS)]) for i in range(offset, end, len(POINTS))]
            assert 'loose_saw_millstone' not in values[end], values[end]
            offset = end + 1
        assert offset == len(values), (offset, len(values))
    return phases


def compare(native, java):
    for phase_name, expected in java.items():
        for tick, (actual, wanted) in enumerate(zip(native[phase_name], expected, strict=True), 1):
            for pos, got, reference in zip(POINTS, actual, wanted, strict=True):
                got_cycle, ref_cycle = got.get('cycle'), reference.get('cycle')
                if got_cycle is not None:
                    assert abs(got_cycle[0] - ref_cycle[0]) < 1e-5, (phase_name, tick, pos, got, reference)
                    got = dict(got, cycle=[ref_cycle[0], *got_cycle[1:]])
                assert got == reference, (phase_name, tick, pos, got, reference)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for arg in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + arg, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='saw-millstone-java-', dir=ROOT / '.local'))
        phases = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon runs require --game, --resources, --ctl and --reference')
        expected = json.loads(args.reference.read_text())
        assert expected['passed'] and expected['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='saw-millstone-native', graphics=False, world='CreateSawMillstone')
        work = session.scratch
        try:
            phases = native_run(session)
        finally:
            session.control_temp.cleanup()
            for disposable in (session.resources, work / '.horizon-cache'):
                if not disposable.is_dir():
                    continue
                try:
                    shutil.rmtree(disposable)
                except OSError as error:
                    if error.errno != errno.ENOTEMPTY:
                        raise
                    shutil.rmtree(disposable)
        (work / 'observed.json').write_text(json.dumps(phases, indent=2) + '\n')
        compare(phases, expected['phases'])
    delivery_tick = verify(phases)
    result = dict(passed=True, create=PINS['create_revision'], delivery_tick=delivery_tick, phases=phases)
    path = work / 'result.json'
    path.write_text(json.dumps(result, indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
