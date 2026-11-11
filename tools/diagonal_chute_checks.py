#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Place ordinary diagonal Chutes and compare transfers with pinned Java Create."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile
import time

from burner_heat_java_checks import field, items, number
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from funnel_checks import block, click, put, step
from native_check_session import NativeCheckSession, wait_loaded
import reference_java


CHUTE = 'create:chute'
AREA = '2515 155 1330 2530 163 1369'
FORCE = '2512 1328 2531 1375'
LANES = {'east': (1, 0), 'west': (-1, 0), 'north': (0, -1), 'south': (0, 1)}
CARGO = 'minecraft:iron_ingot'


def points(base, direction):
    x, y, z = base
    dx, dz = direction
    return [(x, y-1, z), base, (x+dx, y+1, z+dz), (x+2*dx, y+2, z+2*dz)]


def place_side(host, work, name, face, direction, below):
    x, y, z = below
    dx, dz = direction
    support = (x, y+1, z)
    feet = (x+.5+2.7*dx, y, z+.5+2.7*dz)
    put(host.command, support, 'minecraft:smooth_stone')
    put(host.command, (int(feet[0]), y-1, int(feet[2])), 'minecraft:smooth_stone')
    click(host, work, name, support, face, feet,
          (x+.5+.4*dx, y+1.5, z+.5+.4*dz), CHUTE)


def probe(host, positions):
    result = []
    for index, pos in enumerate(positions):
        row = block(host, pos)
        data_key = 'Item' if index else 'Items'
        nbt = row.get('nbt', '')
        content = items(nbt, data_key) if data_key + ':' in nbt else {}
        payload = {CARGO: content[CARGO]} if CARGO in content else {}
        marker = int(number({'nbt': field(nbt, data_key)}, 'diagonal_chute')) if payload else None
        properties = {key: value.lower() for key, value in row['properties'].items()}
        result.append(dict(id=row['id'], properties=properties, stack=payload, marker=marker,
                           position=number(row, 'ItemPosition') if index and payload else None))
    return result


def seed(host, pos, stack, height=1):
    live = f',Items:[{{Slot:0b,{stack}}}]' if isinstance(host, Native) else ''
    host.command(f'data merge block {xyz(pos)} {{Item:{{{stack}}},ItemPosition:{height}f{live}}}')


def restart(host, positions):
    if isinstance(host, Native):
        host.session.restart()
        wait_loaded(host.session.call, positions)
        host.command('tick freeze')
        return
    host.call('quit', {})
    deadline = time.monotonic() + 60
    while reference_java.process_alive(reference_java.BASE):
        if time.monotonic() >= deadline:
            raise RuntimeError('Java Create did not quit')
        time.sleep(.2)
    assert reference_java.launch(reference_java.BASE)['ready']
    host.call('tick', {'frozen': True})
    for _ in range(10):
        if all(block(host, pos)['id'] != 'minecraft:air' for pos in positions):
            return
        step(host, 5, *positions)
    raise RuntimeError('Saved diagonal Chutes did not reload')


def scenario(host, work, *, cold=False):
    host.command('gamemode creative')
    host.command(f'fill {AREA} minecraft:air')
    results = {}
    for index, (face, direction) in enumerate(LANES.items(), 1):
        base = (2522, 157, 1333 + 10*(index-1))
        positions = points(base, direction)
        chest, lower, middle, upper = positions
        put(host.command, chest, 'minecraft:barrel')
        put(host.command, lower, CHUTE)
        place_side(host, work, face+'-middle', face, direction, lower)
        step(host, 5, middle)
        place_side(host, work, face+'-upper', face, direction, middle)
        step(host, 5, lower, middle, upper)
        initial = probe(host, positions)
        assert [(row['properties']['facing'], row['properties']['shape']) for row in initial[1:]] == [
            ('down', 'intersection'), (face, 'normal'), (face, 'intersection')], initial

        stack = f'id:"{CARGO}",count:7,components:{{"minecraft:custom_data":{{diagonal_chute:{index}}}}}'
        seed(host, upper, stack)
        rows = []
        for _ in range(23):
            step(host, 1, *positions)
            rows.append(probe(host, positions))
        assert any(row[2]['position'] == .51 for row in rows), rows
        assert any(row[1]['position'] == .51 for row in rows), rows
        for row in rows:
            assert sum(sum(block['stack'].values()) for block in row) == 7, row
            assert [block['marker'] for block in row if block['stack']] == [index], row
        assert rows[-1][0]['stack'] == {CARGO: 7}, rows[-1]

        saved = None
        if cold and face == 'east':
            full = ','.join(f'{{Slot:{slot}b,id:"minecraft:diamond",count:64}}' for slot in range(27))
            host.command(f'data merge block {xyz(chest)} {{Items:[{full}]}}')
            seed(host, lower, 'id:"minecraft:diamond",count:1', 0.5)
            seed(host, upper, stack)
            step(host, 18, *positions)
            parked = probe(host, positions)
            assert parked[2]['stack'] == {CARGO: 7} and parked[2]['position'] == 0.5, parked
            restart(host, positions)
            reloaded = probe(host, positions)
            assert reloaded == parked, (reloaded, parked)
            host.command(f'data merge block {xyz(chest)} {{Items:[]}}')
            step(host, 18, *positions)
            released = probe(host, positions)
            assert released[0]['stack'] == {CARGO: 7}, released
            assert all(not row['stack'] for row in released[1:]), released
            saved = dict(parked=parked, reloaded=reloaded, released=released)

        put(host.command, lower, 'minecraft:air')
        step(host, 5, middle, upper)
        disconnected = probe(host, positions)[2:]
        assert [(row['properties']['facing'], row['properties']['shape']) for row in disconnected] == [
            ('down', 'normal'), (face, 'intersection')], disconnected
        results[face] = dict(initial=initial, ticks=rows, disconnected=disconnected)
        if saved is not None:
            results[face]['cold'] = saved
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('game', 'resources', 'ctl', 'reference', 'create-jar'):
        parser.add_argument('--' + arg, type=Path)
    parser.add_argument('--cold', action='store_true', help='Restart during the first transfer')
    args = parser.parse_args()
    if args.game:
        if not all((args.resources, args.ctl, args.reference)):
            parser.error('Horizon needs --game, --resources, --ctl and --reference')
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='diagonal-chute-native', world='DiagonalChutes')
        work = session.scratch
        host = Native(session)
    else:
        work = Path(tempfile.mkdtemp(prefix='diagonal-chute-java-', dir=ROOT / '.local'))
        host = Original()
        original = host.call('state', {})
        if original.get('screen') == 'PauseScreen':
            host.call('input', {'kind': 'escape'})
        assert original['ready'] and original['data_version'] == 3955
    try:
        if args.game:
            session.start()
        host.command(f'forceload add {FORCE}')
        host.command('tp @s 2522.5 159 1351.5')
        if args.game:
            wait_loaded(session.call, [(2522, 157, z) for z in (1333, 1343, 1353, 1363)])
            host.command('tick freeze')
        else:
            host.call('tick', {'frozen': True})
            step(host, 30, (2522, 157, 1351))
        lanes = scenario(host, work, cold=args.cold)
    finally:
        if args.game:
            session.stop()
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
        else:
            host.command(f'fill {AREA} minecraft:air')
            host.command(f'forceload remove {FORCE}')
            host.call('camera', {key: original[key] for key in ('position', 'yaw', 'pitch')})
            host.call('tick', {'frozen': original['server']['frozen']})
            (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
    result = dict(passed=False, create=PINS['create_revision'], lanes=lanes)
    path = work / 'result.json'
    path.write_text(json.dumps(result, indent=2) + '\n')
    if args.game:
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == result['create']
        for direction, lane in lanes.items():
            assert lane == reference['lanes'][direction], (direction, lane)
    result['passed'] = True
    path.write_text(json.dumps(result, indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
