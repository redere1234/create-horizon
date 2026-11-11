#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare Belt and Chute feed into a stopped upward Saw, then through a Chute."""

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import tempfile
import time

from bearing_native_checks import Batch
from burner_heat_java_checks import field, items, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession
import reference_java


FORCE = '2224 1344 2255 1359'
LOG, STRIPPED = 'minecraft:oak_log', 'minecraft:stripped_oak_log'
WARM, RUN = 16, 86


@dataclass(frozen=True)
class Fixture:
    name: str
    inlet: tuple[int, int, int]
    saw: tuple[int, int, int]
    region: str

    @property
    def probes(self):
        x, y, z = self.saw
        return self.inlet, self.saw, (x+1, y, z), (x+1, y-1, z)

    @property
    def marker(self):
        return f'{self.name}_saw_input'


BELT = Fixture('belt', (2237, 126, 1348), (2240, 126, 1348), '2234 124 1345 2244 130 1351')
CHUTE = Fixture('chute', (2237, 127, 1356), (2237, 126, 1356), '2235 124 1354 2241 130 1358')


def setup(command, advance, fixture, *, native=False):
    inlet, saw, chute, chest = fixture.probes
    command(f'fill {fixture.region} minecraft:air')
    command(f'setblock {xyz(chest)} minecraft:chest')
    command(f'setblock {xyz(chute)} create:chute[facing=down,shape=window]')
    command(f'setblock {xyz(saw)} create:mechanical_saw[facing=up,axis_along_first=false]')
    if fixture is BELT:
        x, y, z = inlet
        for index, part in enumerate(('start', 'middle', 'end')):
            command(f'setblock {x+index} {y} {z} create:belt[facing=east,slope=horizontal,part={part}]')
        command(f'setblock {x} {y} {z-1} create:creative_motor[facing=south]{{ScrollValue:-32}}')
    else:
        command(f'setblock {xyz(inlet)} create:chute[facing=down,shape=window]')
    advance(24)
    stack = f'id:"{LOG}",count:3,components:{{"minecraft:custom_data":{{{fixture.marker}:37}}}}'
    if fixture is BELT:
        command(f'data merge block {xyz(inlet)} {{Inventory:{{PositiveOrder:1b,Items:[{{'
                f'Item:{{{stack}}},'
                'Pos:2.65f,PrevPos:2.65f,InDirection:5,InSegment:2,Angle:180}]}}')
    else:
        live = f',Items:[{{Slot:0b,{stack}}}]' if native else ''
        command(f'data merge block {xyz(inlet)} {{Item:{{{stack}}},ItemPosition:1f{live}}}')


def start_saw(command, fixture):
    x, y, z = fixture.saw
    command(f'setblock {x} {y} {z-1} create:creative_motor[facing=south]{{ScrollValue:128}}')


def snapshot(raw, fixture):
    inlet, saw, _, _ = raw
    inlet_key = 'Inventory' if fixture is BELT else 'Item'
    keys = (inlet_key, 'Inventory', 'Item', 'Items')
    inventories = [items(data, key) if f'{key}:' in data else {} for data, key in zip(raw, keys, strict=True)]
    for data, key, content in zip(raw[:2], keys[:2], inventories[:2], strict=True):
        if LOG in content:
            assert number({'nbt': field(data, key)}, fixture.marker) == 37, data
    timer = [number({'nbt': saw}, key, 0) for key in ('ProcessingTime', 'RecipeTime', 'AppliedRecipe')]
    position = None
    if inventories[0]:
        position = (number({'nbt': field(inlet, 'Inventory')}, 'Pos') if fixture is BELT
                    else number({'nbt': inlet}, 'ItemPosition'))
    return {'belt' if fixture is BELT else 'feed': inventories[0],
            'saw': inventories[1], 'chute': inventories[2], 'chest': inventories[3],
            'timer': timer, 'position': position}


def verify(warm, cold, running, fixture):
    inlet = 'belt' if fixture is BELT else 'feed'
    assert warm[-1] == cold, (warm[-1], cold)
    assert cold == {inlet: {LOG: 2}, 'saw': {LOG: 1}, 'chute': {}, 'chest': {},
                    'timer': [50, 50, 0], 'position': 2.75 if fixture is BELT else 0.5}, cold
    for row in warm + running:
        assert sum(sum(row[key].values()) for key in (inlet, 'saw', 'chute', 'chest')) == 3, row
        assert sum(row['saw'].values()) <= 1, row
    assert running[-1]['chest'] == {STRIPPED: 3} and not running[-1][inlet], running[-1]


def compare(report, reference):
    assert report['warm'] == reference['warm']
    assert report['cold'] == reference['cold']
    running = report['running']
    original = reference['running']
    handoffs = []
    for index, (actual, expected) in enumerate(zip(running, original, strict=True)):
        if actual == expected:
            continue
        previous = original[index-1] if index else reference['cold']
        following = original[index+1] if index+1 < len(original) else expected
        allowed = expected.copy()
        # On cold load the engines can visit the Belt, Saw and Chute in
        # different orders. Cutting and export must still happen at the
        # same time, even if the Belt refills the Saw on the export tick.
        if STRIPPED in previous['saw'] and not expected['saw'] and LOG in following['saw']:
            for key in ('belt', 'saw', 'position'):
                allowed[key] = following[key]
            duration = following['timer'][1]
            allowed['timer'] = [duration, duration, 0]
        # The Chute may reach the Chest one tick later.
        if previous['chest'] != expected['chest']:
            for key in ('chute', 'chest'):
                allowed[key] = previous[key]
        assert actual == allowed, (index+1, actual, expected)
        handoffs.append(index+1)
    return handoffs


def java(work, fixture):
    host = Original()
    state = host.call('state', {})
    if state.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        state = host.call('state', {})
    assert state['ready'] and state['data_version'] == 3955

    def advance(ticks):
        return host.call('observe_ticks', {'positions': fixture.probes, 'ticks': ticks})['samples']

    def sample(ticks):
        return [snapshot([block['nbt'] for block in row['blocks']], fixture) for row in advance(ticks)]

    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {FORCE}')
        x, _, z = fixture.saw
        host.command(f'tp @s {x}.5 130 {z+1}.5')
        advance(23)
        setup(host.command, advance, fixture)
        warm = sample(WARM)
        host.call('quit', {})
        deadline = time.monotonic() + 60
        while reference_java.process_alive(reference_java.BASE):
            if time.monotonic() >= deadline:
                raise RuntimeError('The reference Java world did not quit')
            time.sleep(.2)
        assert reference_java.launch(reference_java.BASE)['ready']
        host.call('tick', {'frozen': True})
        for _ in range(10):
            blocks = [host.call('block', {'pos': pos}) for pos in fixture.probes]
            if all(block['id'] != 'minecraft:air' for block in blocks):
                break
            advance(5)
        else:
            raise RuntimeError('Saved Saw fixture did not reload')
        cold = snapshot([block['nbt'] for block in blocks], fixture)
        start_saw(host.command, fixture)
        running = sample(60) + sample(RUN - 60)
        return warm, cold, running
    finally:
        host.command(f'fill {fixture.region} minecraft:air')
        host.command(f'forceload remove {FORCE}')
        host.call('camera', {key: state[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': state['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session, fixture):
    x, _, z = fixture.saw
    player = (x, 129, z+1)
    columns = len(fixture.probes)

    def probe(batch):
        for pos in fixture.probes:
            batch.data(pos)

    def rows(batch, label):
        raw = batch.run(session, label)
        return [snapshot(raw[i:i+columns], fixture) for i in range(0, len(raw), columns)]

    first = Batch()
    first.load(player)
    setup(first.command, first.tick, fixture, native=True)
    for _ in range(WARM):
        first.tick()
        probe(first)
    warm = rows(first, 'before-restart')

    resumed = Batch()
    resumed.load(player)
    probe(resumed)
    start_saw(resumed.command, fixture)
    for _ in range(RUN):
        resumed.tick()
        probe(resumed)
    cold, *running = rows(resumed, 'after-restart')
    return warm, cold, running


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + key, type=Path)
    parser.add_argument('--chute-inlet', action='store_true', help='Feed the Saw from a vertical Chute')
    args = parser.parse_args()
    fixture = CHUTE if args.chute_inlet else BELT
    label = f'{fixture.name}-saw'
    if args.game:
        if not all((args.resources, args.ctl, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None, graphics=False,
                                     name=f'{label}-native', world=f'{fixture.name.title()}Saw')
        work = session.scratch
        try:
            warm, cold, running = native(session, fixture)
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    else:
        work = Path(tempfile.mkdtemp(prefix=f'{label}-java-', dir=ROOT / '.local'))
        warm, cold, running = java(work, fixture)
    path = work / 'result.json'
    report = dict(passed=False, create=PINS['create_revision'], warm=warm, cold=cold, running=running)
    path.write_text(json.dumps(report, indent=2) + '\n')
    verify(warm, cold, running, fixture)
    if args.game:
        if fixture is BELT:
            report['one_tick_handoffs'] = compare(report, reference)
        else:
            for phase in ('warm', 'running'):
                for tick, (row, expected) in enumerate(zip(report[phase], reference[phase], strict=True), 1):
                    assert row == expected, (phase, tick, row, expected)
    report['passed'] = True
    path.write_text(json.dumps(report, indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
