#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare Drill's retained cobblestone and direct hopper loot in both games."""
import argparse
import errno
import json
from pathlib import Path
import re
import shutil
import tempfile
import time

from bearing_native_checks import Batch
from burner_heat_java_checks import field, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession
import reference_java
from reference_java import BASE, CREATE_SHA256


X, Y = 2032, 168
LANES = dict(merging=886, full=894, no_collector=902, vertical_water=910, empty=918)
COLLECTORS = ('merging', 'full', 'empty')
REGION = '2028 166 882 2037 172 921'
LOAD = '2016 880 2047 927'
COBBLE = 'minecraft:cobblestone'
BEFORE_RESTART = dict(active=36, drops_disabled=24, parked=3)
AFTER_RESTART = dict(restored=1, resumed=24)


def drill(z):
    return X - 1, Y, z


def target(z):
    return X, Y, z


def hopper(z):
    return X, Y - 1, z


def power(put, z, on):
    put((X - 2, Y, z), ('create:creative_motor[facing=east]{ScrollValue:256}'
                        if on else 'minecraft:air'))


def prepare(command, put):
    command('fill ' + REGION + ' minecraft:air')
    command('kill @e[type=minecraft:item,x=2028,y=166,z=882,dx=9,dy=6,dz=39]')
    for lane, z in LANES.items():
        command(f'fill {X - 1} {Y - 2} {z - 2} {X + 1} {Y - 1} {z + 2} minecraft:smooth_stone')
        command(f'fill {X + 1} {Y} {z - 2} {X + 1} {Y} {z + 2} minecraft:smooth_stone')
        for dz in (-2, 2):
            put((X, Y, z + dz), 'minecraft:smooth_stone')
        for dz in (-1, 1):
            put((X - 1, Y, z + dz), 'minecraft:smooth_stone')
        if lane != 'no_collector':
            nbt = ''
            if lane == 'merging':
                nbt = '{Items:[{Slot:3b,id:"minecraft:cobblestone",count:63}]}'
            elif lane == 'full':
                nbt = '{Items:[' + ','.join(f'{{Slot:{i}b,id:"minecraft:dirt",count:64}}' for i in range(5)) + ']}'
            put(hopper(z), 'minecraft:hopper[facing=down]' + nbt)
        put(drill(z), 'create:mechanical_drill[facing=east]')
        put(target(z), COBBLE)
        put((X, Y, z + 1), 'minecraft:lava[level=0]')
        if lane == 'vertical_water':
            for dx, dz in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                put((X + dx, Y + 1, z + dz), 'minecraft:smooth_stone')
            put((X, Y + 1, z), 'minecraft:water[level=0]')
        else:
            put((X, Y, z - 1), 'minecraft:water[level=0]')
        power(put, z, True)


def phase(command, put, name, gamerule):
    if name == 'drops_disabled':
        command(f'gamerule {gamerule} false')
    elif name == 'parked':
        for z in LANES.values():
            power(put, z, False)
    elif name == 'resumed':
        power(put, LANES['merging'], True)


def probes(name):
    lanes = LANES if name == 'active' else {k: LANES[k] for k in COLLECTORS}
    result = []
    for lane, z in lanes.items():
        result.append((lane, 'cobble', target(z)))
        result.append((lane, 'drill', drill(z)))
        if lane != 'no_collector':
            result.append((lane, 'hopper', hopper(z)))
    return result


def slots(raw):
    if 'Items:' not in raw:
        return []
    rows = []
    for entry in re.findall(r'\{([^{}]*)\}', field(raw, 'Items')):
        rows.append([int(number({'nbt': entry}, 'Slot')), re.search(r'\bid:\s*"([^"]+)"', entry)[1],
                     int(number({'nbt': entry}, 'count'))])
    return sorted(rows)


def sample(probe, values):
    result = {}
    for (name, kind, _), value in zip(probe, values, strict=True):
        lane = result.setdefault(name, {})
        if kind == 'drill':
            lane[kind] = [number({'nbt': value}, key) for key in ('Progress', 'NextTick', 'Speed')]
        elif kind == 'hopper':
            assert 'minecraft:hopper' in value, value
            lane[kind] = slots(value)
        else:
            lane[kind] = value
    return result


def nearby_entities(name, kind):
    return f'@e[type=minecraft:{kind},x={X - 1},y={Y - 1},z={LANES[name] - 1},dx=2,dy=3,dz=2]'


def record_entity_checks(batch):
    for lane in COLLECTORS:
        for kind in ('item', 'experience_orb'):
            batch.command(f'execute if entity {nearby_entities(lane, kind)} run say drill_cobble_entity', True)


def restart_reference(host):
    # Minecraft's integrated server saves normally when the client quits.
    host.call('quit', {})
    deadline = time.monotonic() + 60
    while reference_java.process_alive(BASE):
        if time.monotonic() >= deadline:
            raise RuntimeError('The isolated Java client did not stop after saving')
        time.sleep(0.2)
    state = reference_java.launch(BASE)
    assert state['ready'], state
    host.call('tick', {'frozen': True})
    position = list(map(int, state['position']))
    for _ in range(10):
        replies = [host.command(f'data get block {xyz(drill(z))}')
                   for z in LANES.values()]
        if all(any('create:drill' in message for message in reply['messages']) for reply in replies):
            return
        host.call('observe_ticks', {'positions': [position], 'ticks': 5})
    raise RuntimeError('Saved generator columns did not reload')


def java_run(work, restart):
    host = Original()
    assert json.loads((BASE / 'manifest.json').read_text())['create_sha256'] == CREATE_SHA256
    state = host.call('state', {})
    assert state['ready'] and state['data_version'] == 3955, state
    host.call('tick', {'frozen': True})
    rule = ' '.join(host.command('gamerule doTileDrops')['messages']).lower()
    assert 'true' in rule or 'false' in rule, rule
    phases = {}

    def put(pos, block):
        host.command(f'setblock {xyz(pos)} {block}')

    try:
        host.command('forceload add ' + LOAD)
        host.call('observe_ticks', {'positions': [list(map(int, state['position']))], 'ticks': 40})
        host.command('gamerule doTileDrops true')
        prepare(host.command, put)
        for name, ticks in (BEFORE_RESTART | AFTER_RESTART).items():
            if restart and name == 'restored':
                restart_reference(host)
            phase(host.command, put, name, 'doTileDrops')
            probe = probes(name)
            observed = host.call('observe_ticks', {'positions': [p for _, _, p in probe], 'ticks': ticks})
            phases[name] = [sample(probe, [block['id'] == COBBLE if kind == 'cobble' else block['nbt']
                                           for (_, kind, _), block in zip(probe, row['blocks'], strict=True)])
                            for row in observed['samples']]
            for lane in COLLECTORS:
                center = [value + 0.5 for value in target(LANES[lane])]
                entities = host.call('entities', {'center': center, 'radius': 2})['entities']
                assert all(e['type'] not in ('minecraft:item', 'minecraft:experience_orb') for e in entities), (
                    name, lane, entities)
        return phases
    finally:
        host.command('fill ' + REGION + ' minecraft:air')
        host.command('kill @e[type=minecraft:item,x=2028,y=166,z=882,dx=9,dy=6,dz=39]')
        host.command(f'gamerule doTileDrops {str("true" in rule).lower()}')
        host.command('forceload remove ' + LOAD)
        host.call('tick', {'frozen': state['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    phases = {}
    for label, mapping in [('before-restart', BEFORE_RESTART), ('after-restart', AFTER_RESTART)]:
        batch = Batch()
        batch.load((X, Y + 4, 898))
        all_points = [p for _, _, p in probes('active')]
        for pos in all_points:
            batch.command(f'execute if loaded {xyz(pos)} run say drill_cobble_loaded', True)
        if label == 'before-restart':
            batch.command('gamerule minecraft:block_drops true')
            prepare(batch.command, batch.put)
        for name, ticks in mapping.items():
            phase(batch.command, batch.put, name, 'minecraft:block_drops')
            for _ in range(ticks):
                batch.tick()
                for _, kind, pos in probes(name):
                    if kind == 'cobble':
                        batch.expect(pos, COBBLE)
                    else:
                        batch.data(pos)
            record_entity_checks(batch)
        rows = batch.run(session, label)
        assert all('drill_cobble_loaded' in line for line in rows[:len(all_points)]), rows[:len(all_points)]
        data = iter(rows[len(all_points):])
        for name, ticks in mapping.items():
            probe = probes(name)
            phases[name] = [sample(probe, ['bearing_check' in value if kind == 'cobble' else value
                                           for (_, kind, _), value in zip(probe, (next(data) for _ in probe),
                                                                           strict=True)])
                            for _ in range(ticks)]
            for lane in COLLECTORS:
                for kind in ('item', 'experience_orb'):
                    assert 'drill_cobble_entity' not in next(data), (name, lane, kind)
        assert next(data, None) is None
    return phases


def summarize(phases):
    def total(row):
        return sum(count for _, item, count in row['merging']['hopper'] if item == COBBLE)

    active = phases['active']
    first = next(i for i, row in enumerate(active, 1) if total(row) > 63)
    assert active[first - 1]['merging']['hopper'] == [[3, COBBLE, 64]], active[first - 1]
    assert active[first - 1]['empty']['hopper'] == [[0, COBBLE, 1]], active[first - 1]
    assert any(row['merging']['hopper'][0][0] == 0 for row in active[first:]), active
    for rows in phases.values():
        for row in rows:
            assert all(row[name]['cobble'] for name in COLLECTORS), row
            assert row['full']['hopper'] == [[i, 'minecraft:dirt', 64] for i in range(5)], row
    assert total(phases['drops_disabled'][-1]) > total(active[-1]), phases
    assert total(phases['restored'][0]) == total(phases['parked'][-1]), phases
    assert total(phases['resumed'][-1]) > total(phases['restored'][0]), phases
    negative = {name: next(i for i, row in enumerate(active, 1) if not row[name]['cobble'])
                for name in ('no_collector', 'vertical_water')}
    return dict(first=first, ordinary_break=negative, active_count=total(active[-1]),
                disabled_count=total(phases['drops_disabled'][-1]), resumed_count=total(phases['resumed'][-1]))


def resume_deliveries(phases):
    previous = phases['restored'][-1]['merging']['hopper']
    ticks = []
    for tick, row in enumerate(phases['resumed'], 1):
        current = row['merging']['hopper']
        if current != previous:
            ticks.append(tick)
        previous = current
    return ticks


def compare(native, java):
    actual_ticks = resume_deliveries(native)
    expected_ticks = resume_deliveries(java)
    assert actual_ticks and expected_ticks and actual_ticks[0] == expected_ticks[0], (actual_ticks, expected_ticks)
    for name, expected in java.items():
        for tick, (actual, wanted) in enumerate(zip(native[name], expected, strict=True), 1):
            # Idle turns before re-powering advance the unsaved lazy counter.
            # Require exact startup and first output; report the later cadence.
            if name == 'resumed' and tick > expected_ticks[0]:
                break
            for lane in COLLECTORS:
                assert actual[lane] == wanted[lane], (name, tick, lane, actual[lane], wanted[lane])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    parser.add_argument('--java-restart', action='store_true', help='save and restart the isolated Java client')
    for flag in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java_restart and not args.java:
        parser.error('--java-restart is for the isolated Java run')
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='drill-cobble-java-', dir=ROOT / '.local'))
        phases = java_run(work, args.java_restart)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon runs require --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='drill-cobble-native', graphics=False, world='CreateDrillCobble')
        work = session.scratch
        try:
            phases = native_run(session)
        finally:
            session.control_temp.cleanup()
            for path in (session.resources, work / '.horizon-cache'):
                if not path.is_dir():
                    continue
                try:
                    shutil.rmtree(path)
                except OSError as error:
                    if error.errno != errno.ENOTEMPTY:
                        raise
                    shutil.rmtree(path)
    (work / 'observed.json').write_text(json.dumps(phases, indent=2) + '\n')
    result = dict(passed=True, create=PINS['create_revision'], summary=summarize(phases),
                  restarted=args.java_restart or not args.java, resume_deliveries=resume_deliveries(phases),
                  phases=phases)
    if not args.java:
        assert result['summary'] == reference['summary'], (result['summary'], reference['summary'])
        compare(phases, reference['phases'])
        result['java_restarted'] = reference.get('restarted', False)
        result['java_resume_deliveries'] = resume_deliveries(reference['phases'])
    path = work / 'result.json'
    path.write_text(json.dumps(result, indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
