#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare the Chute into a downward Crushing Wheel controller in Java and Horizon."""
import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile
import time

from bearing_native_checks import Batch
from burner_heat_java_checks import field, items, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession
import reference_java
from reference_java import BASE, CREATE_SHA256


X, Y = 2134, 168
LOAD = '2128 880 2143 911'
REGION = '2132 166 880 2136 171 902'
DROPS = '@e[type=minecraft:item,x=2132,y=166,z=880,dx=4,dy=5,dz=22]'
AIR = 'minecraft:air'
WHEEL = 'create:crushing_wheel[axis=z]'
CONTROLLER = 'create:crushing_wheel_controller'
CHUTE = 'create:chute[facing=down,shape=normal,waterlogged=false]'
COBBLE = 'minecraft:cobblestone'
GRAVEL = 'minecraft:gravel'
LANES = {
    'single': (882, COBBLE, 1),
    'priority': (887, GRAVEL, 4),
    'unknown': (892, 'minecraft:diamond', 1),
    'pause': (898, COBBLE, 4),
}


def positions(z):
    return [(X, Y, z), (X, Y + 1, z)]


POINTS = [p for z, *_ in LANES.values() for p in positions(z)]


def put(command, pos, block):
    command(f'setblock {xyz(pos)} {block}')


def wheel_power(command, z, side, enabled):
    rpm = -64 if side < 0 else 96
    motor = f'create:creative_motor[facing=south]{{ScrollValue:{rpm}}}' if enabled else AIR
    put(command, (X + side, Y, z - 1), motor)


def wheels(command, z):
    for side in (-1, 1):
        put(command, (X + side, Y, z), WHEEL)
        wheel_power(command, z, side, True)


def seed_chute(command, z, item, count, marker):
    command(f'data merge block {X} {Y + 1} {z} '
            f'{{ItemPosition:0.1f,Item:{{id:"{item}",count:{count},'
            f'components:{{"minecraft:custom_data":{{crusher_marker:{marker}}}}}}}}}')


def seed(command):
    for marker, (z, item, count) in enumerate(LANES.values(), 1):
        seed_chute(command, z, item, count, marker)


def setup(command, advance):
    command(f'fill {REGION} {AIR}')
    command(f'fill 2132 166 880 2136 166 902 minecraft:smooth_stone')
    command(f'kill {DROPS}')
    for lane, (z, *_) in LANES.items():
        if lane == 'priority':
            put(command, (X, Y + 1, z), CHUTE)
        else:
            wheels(command, z)
    advance(28)
    for lane, (z, *_) in LANES.items():
        if lane == 'priority':
            wheels(command, z)
        else:
            put(command, (X, Y + 1, z), CHUTE)
    advance(28)


def snapshot(blocks):
    result = {}
    for name, controller, chute in zip(LANES, blocks[::2], blocks[1::2], strict=True):
        assert controller['id'] == CONTROLLER and chute['id'] == 'create:chute', (controller, chute)
        raw = controller['nbt']
        inventory = field(raw, 'Inventory')
        assert number({'nbt': inventory}, 'Size') == 32, inventory
        result[name] = dict(state=controller['properties'], speed=number(controller, 'Speed'),
                            inventory=items(raw, 'Inventory'), chute=items(chute['nbt'], 'Item'),
                            remaining=number({'nbt': inventory}, 'ProcessingTime'),
                            recipe_time=number({'nbt': inventory}, 'RecipeTime'),
                            applied=number({'nbt': inventory}, 'AppliedRecipe') != 0,
                            marker=int(number({'nbt': inventory}, 'crusher_marker', 0)))
    return result


def dropped(host):
    result = {}
    for name, (z, *_) in LANES.items():
        rows = host.call('entities', {'center': [X + .5, Y - .5, z + .5], 'radius': 1.5})['entities']
        result[name] = [dict(items=items(e['nbt'], 'Item'), position=e['position'], motion=e['motion'],
                             pickup_delay=number(e, 'PickupDelay'),
                             bypass='BypassCrushingWheel' in e['nbt'])
                        for e in rows if e['type'] == 'minecraft:item']
    return result


def verify(trace, first_output, final_output, *, original):
    first = trace['active'][0]
    assert first['single']['remaining'] == 250 and first['single']['inventory'] == {COBBLE: 1}, first
    assert first['priority']['remaining'] < 250 and first['priority']['inventory'] == {GRAVEL: 4}, first
    diamond = {'minecraft:diamond': 1}
    if original:
        assert first['unknown']['remaining'] == 100 and first['unknown']['inventory'] == diamond, first
    for marker, lane in enumerate(LANES, 1):
        row = first[lane]
        assert row['state'] == {'valid': 'true', 'facing': 'down'}, row
        assert row['speed'] == 1.28 and row['recipe_time'] == 0 and not row['applied'], row
        if original or lane != 'unknown':
            assert row['marker'] == marker and not row['chute'], row
    saved = trace['active'][-1]['pause']
    assert all(row['pause']['speed'] == 0 and row['pause']['remaining'] == saved['remaining']
               and row['pause']['state']['valid'] == 'false' for row in trace['paused']), trace['paused']
    assert trace['resumed'][0]['pause']['speed'] == 1.28, trace['resumed'][0]
    timeline = [*trace['active'], *trace['paused'], *trace['resumed'], *trace['settled']]
    for name, expected_tick in {'single': 13, 'priority': 90, 'pause': 96}.items():
        applied = next(i for i, row in enumerate(timeline) if row[name]['applied'])
        assert applied + 1 == expected_tick, (name, applied + 1)
        before, after = timeline[applied][name], timeline[applied + 1][name]
        assert before['inventory'] and before['remaining'] == 0 and before['recipe_time'] == 0, before
        assert not after['inventory'] and not after['applied'], after
    if not original:
        # The bounded port leaves unsupported input in the Chute. Java consumes it.
        assert all(row['unknown']['chute'] == diamond and not row['unknown']['inventory']
                   and row['unknown']['remaining'] == 0 and not row['unknown']['applied']
                   for row in timeline), timeline
    [single] = first_output['single']
    assert single['items'] == {GRAVEL: 1} and single['motion'] == [0, 0, 0], single
    assert single['position'][::2] == [X + .5, LANES['single'][0] + .5], single
    assert abs(single['position'][1] - (Y - .05)) < 1e-6 and single['pickup_delay'] == 0, single
    assert single['bypass'], single
    assert not final_output['unknown'], final_output
    assert [row['items'] for row in final_output['pause']] == [{GRAVEL: 4}], final_output
    priority = {item: count for row in final_output['priority'] for item, count in row['items'].items()}
    assert priority.get('minecraft:sand') == 4, priority
    assert set(priority) <= {'minecraft:sand', 'minecraft:flint', 'minecraft:clay_ball'}, priority
    assert all(1 <= count <= 4 for count in priority.values()), priority


def java_cold(host, observe):
    lanes = ('single', 'priority')
    host.command(f'kill {DROPS}')
    for marker, name in enumerate(lanes, 51):
        seed_chute(host.command, LANES[name][0], COBBLE, 1, marker)
    staged = observe(12)[-1]
    assert staged['single']['remaining'] == 30 and staged['single']['marker'] == 51, staged
    assert staged['priority']['applied'] and staged['priority']['inventory'] == {GRAVEL: 1}, staged
    for name in lanes:
        wheel_power(host.command, LANES[name][0], 1, False)
    parked = observe(1)[0]
    assert all(parked[name]['speed'] == 0 for name in lanes), parked

    host.call('quit', {})
    deadline = time.monotonic() + 60
    while reference_java.process_alive(BASE):
        if time.monotonic() >= deadline:
            raise RuntimeError('The isolated Java client did not stop after saving')
        time.sleep(0.2)
    state = reference_java.launch(BASE)
    assert state['ready'], state
    host.call('tick', {'frozen': True})
    for _ in range(10):
        blocks = [host.call('block', {'pos': pos}) for pos in POINTS]
        if all(b['id'] == CONTROLLER for b in blocks[::2]):
            break
        host.call('observe_ticks', {'positions': [list(map(int, state['position']))], 'ticks': 5})
    else:
        raise RuntimeError('Saved crusher columns did not reload')
    loaded = snapshot(blocks)
    assert {name: loaded[name] for name in lanes} == {name: parked[name] for name in lanes}, loaded
    loaded_drops = dropped(host)
    assert all(not loaded_drops[name] for name in lanes), loaded_drops
    for name in lanes:
        wheel_power(host.command, LANES[name][0], 1, True)
    resumed = observe(8)
    output = dropped(host)
    for name in lanes:
        assert not resumed[-1][name]['inventory'], resumed[-1]
        assert [row['items'] for row in output[name]] == [{GRAVEL: 1}], output
    return dict(parked=parked, loaded=loaded, resumed=resumed, output=output)


def run(work, restart=False):
    host = Original()
    assert json.loads((BASE / 'manifest.json').read_text())['create_sha256'] == CREATE_SHA256
    state = host.call('state', {})
    assert state['ready'] and state['data_version'] == 3955, state
    host.call('tick', {'frozen': True})

    def observe(ticks):
        reply = host.call('observe_ticks', {'positions': POINTS, 'ticks': ticks})
        return [snapshot(row['blocks']) for row in reply['samples']]

    try:
        host.command(f'forceload add {LOAD}')
        host.call('observe_ticks', {'positions': [list(map(int, state['position']))], 'ticks': 40})
        setup(host.command, lambda n: host.call('observe_ticks', {'positions': POINTS, 'ticks': n}))
        order = host.call('ticker_order', {'positions': POINTS})['blockEntityTickers']
        index = {tuple(row['pos']): row['index'] for row in order if not row['removed']}
        for lane, (z, *_) in LANES.items():
            controller, chute = positions(z)
            assert (index[controller] > index[chute]) == (lane == 'priority'), (lane, index)
        seed(host.command)
        trace = {'active': observe(8)}
        z = LANES['pause'][0]
        wheel_power(host.command, z, 1, False)
        trace['paused'] = observe(4)
        wheel_power(host.command, z, 1, True)
        trace['resumed'] = observe(2)
        first_output = dropped(host)
        trace['settled'] = observe(105)
        final_output = dropped(host)
        result = dict(ticker_order=order, trace=trace, first_output=first_output, final_output=final_output)
        if restart:
            result['restart'] = java_cold(host, observe)
        return result
    finally:
        host.command(f'fill {REGION} {AIR}')
        host.command(f'kill {DROPS}')
        host.command(f'forceload remove {LOAD}')
        host.call('tick', {'frozen': state['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_sample(values):
    blocks = []
    for controller, chute, validity, down in zip(values[::4], values[1::4], values[2::4], values[3::4], strict=True):
        assert 'crusher_down' in down, down
        blocks.extend([dict(id=CONTROLLER if CONTROLLER in controller else '', nbt=controller,
                            properties=dict(facing='down', valid='true' if 'crusher_valid' in validity else 'false')),
                       dict(id='create:chute' if 'create:chute' in chute else '', nbt=chute)])
    return snapshot(blocks)


def native_probe(batch):
    for z, *_ in LANES.values():
        controller, chute = positions(z)
        batch.data(controller)
        batch.data(chute)
        batch.command(f'execute if block {xyz(controller)} {CONTROLLER}[valid=true] run say crusher_valid', True)
        batch.command(f'execute if block {xyz(controller)} {CONTROLLER}[facing=down] run say crusher_down', True)


def native_drops(batch):
    for z, *_ in LANES.values():
        area = f'type=minecraft:item,x={X - 1},y={Y - 2},z={z - 1},dx=2,dy=3,dz=2'
        # One output entity per item ID is enough for the small fixture stacks.
        for item in (GRAVEL, 'minecraft:sand', 'minecraft:flint', 'minecraft:clay_ball', 'minecraft:diamond'):
            batch.command(f'data get entity @e[{area},nbt={{Item:{{id:"{item}"}}}},limit=1]', True)


def vector(raw, key):
    return [float(v.strip().rstrip('dD')) for v in field(raw, key)[1:-1].split(',')]


def native_drop_values(values):
    return {lane: [dict(items=items(raw, 'Item'), position=vector(raw, 'Pos'), motion=vector(raw, 'Motion'),
                        pickup_delay=number({'nbt': raw}, 'PickupDelay'), bypass='BypassCrushingWheel' in raw)
                   for raw in values[i * 5:(i + 1) * 5] if re.search(r'\bItem\s*:', raw)]
            for i, lane in enumerate(LANES)}


def native_run(session):
    trace = {}
    controller_rows = len(LANES) * 4
    entity_rows = len(LANES) * 5

    def tick(batch, count):
        for _ in range(count):
            batch.tick()
            native_probe(batch)

    def parse(values, count):
        return [native_sample(values[i * controller_rows:(i + 1) * controller_rows]) for i in range(count)]

    z = LANES['pause'][0]
    before = Batch()
    before.load((X, Y + 4, 890))
    setup(before.command, before.tick)
    seed(before.command)
    tick(before, 8)
    wheel_power(before.command, z, 1, False)
    tick(before, 4)
    wheel_power(before.command, z, 1, True)
    tick(before, 1)
    values = before.run(session, 'before-restart')
    assert len(values) == 13 * controller_rows, values
    trace['active'] = parse(values[:8 * controller_rows], 8)
    trace['paused'] = parse(values[8 * controller_rows:12 * controller_rows], 4)
    trace['resumed'] = parse(values[12 * controller_rows:], 1)

    after = Batch()
    after.load((X, Y + 4, 890))
    native_probe(after)
    tick(after, 1)
    native_drops(after)
    tick(after, 105)
    native_drops(after)
    values = after.run(session, 'after-restart')
    assert len(values) == 107 * controller_rows + 2 * entity_rows, len(values)
    cold = parse(values[:controller_rows], 1)[0]
    trace['resumed'] += parse(values[controller_rows:2 * controller_rows], 1)
    first_output = native_drop_values(values[2 * controller_rows:2 * controller_rows + entity_rows])
    trace['settled'] = parse(values[2 * controller_rows + entity_rows:-entity_rows], 105)
    final_output = native_drop_values(values[-entity_rows:])
    return dict(trace=trace, cold=cold, first_output=first_output, final_output=final_output)


def compare(actual, reference):
    assert actual['cold'] == actual['trace']['resumed'][0], actual['cold']
    for phase, expected in reference['trace'].items():
        for tick, (wanted, got) in enumerate(zip(expected, actual['trace'][phase], strict=True), 1):
            for lane, row in wanted.items():
                observed = got[lane]
                if lane == 'unknown':
                    assert observed['state'] == row['state'] and observed['speed'] == row['speed'], observed
                    continue
                assert abs(row['remaining'] - observed['remaining']) < 1e-5, (phase, tick, lane, row, observed)
                observed = dict(observed, remaining=row['remaining'])
                if lane == 'priority' and row['applied']:
                    # Chance outputs use different loaded world random streams.
                    assert observed['inventory'].get('minecraft:sand') == 4, observed
                    observed = dict(observed, inventory=row['inventory'])
                assert row == observed, (phase, tick, lane, row, observed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--java-restart', action='store_true')
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java_restart and not args.java:
        parser.error('--java-restart requires --java')
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='crushing-wheel-java-', dir=ROOT / '.local'))
        result = run(work, args.java_restart)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon runs require --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None, name='crushing-wheel-native',
                                     graphics=False, world='CreateCrushingWheel')
        work = session.scratch
        try:
            result = native_run(session)
        finally:
            session.control_temp.cleanup()
            for path in (session.resources, work / '.horizon-cache'):
                shutil.rmtree(path, ignore_errors=True)
    (work / 'observed.json').write_text(json.dumps(result, indent=2) + '\n')
    if not args.java:
        compare(result, reference)
    verify(result['trace'], result['first_output'], result['final_output'], original=args.java)
    path = work / 'result.json'
    path.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], **result), indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
