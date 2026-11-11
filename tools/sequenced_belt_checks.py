#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Run Precision Assembly through fifteen ordinary Deployers on one Belt."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from deployer_transport_checks import tag_items
from native_check_session import NativeCheckSession
from sequenced_checks import INCOMPLETE, RECIPE, RESULTS, SHEET, TOOLS, TOTAL, stack


X, Y, Z = 2027, 126, 1223
START, OUTPUT = (X, Y, Z), (X + TOTAL + 2, Y, Z)
DEPLOYERS = [(X + i, Y + 2, Z) for i in range(1, TOTAL + 1)]
ROOM = '2026 124 1220 2046 131 1226'
TICKET = '2016 1216 2047 1231'
TICKS = 460


def setup(command, advance):
    command(f'fill {ROOM} minecraft:air')
    command(f'setblock {xyz(OUTPUT)} create:depot')
    for i in range(TOTAL + 2):
        part = 'start' if i == 0 else 'end' if i == TOTAL + 1 else 'middle'
        command(f'setblock {X+i} {Y} {Z} create:belt[facing=east,slope=horizontal,part={part}]')
    for i, pos in enumerate(DEPLOYERS):
        tool = TOOLS[i % len(TOOLS)]
        command(f'setblock {xyz(pos)} create:deployer[facing=down,axis_along_first=true]'
                f'{{Mode:"USE",State:"WAITING",Timer:0,Inventory:[{{Slot:0b,id:"{tool}",count:1}}]}}')
    advance(3)
    command(f'setblock {X} {Y+2} {Z} create:creative_motor[facing=east]{{ScrollValue:64}}')
    command(f'setblock {X} {Y} {Z-1} create:creative_motor[facing=south]{{ScrollValue:-32}}')
    advance(28)
    command(f'data merge block {xyz(START)} {{Inventory:{{PositiveOrder:1b,Items:[{{'
            f'Item:{{id:"{SHEET}",count:1,components:{{"minecraft:custom_data":{{sequenced_probe:19}}}}}},'
            'Pos:.5f,PrevPos:.5f,InDirection:5,Angle:180}]}}')


def observe(belt, depot):
    inv = field(belt, 'Inventory')
    cargo = stack(field(inv, 'Item')) if 'Item:' in inv else None
    result = stack(field(depot, 'HeldItem')) if 'HeldItem:' in depot else None
    assert not (cargo and result), (cargo, result)
    position = number({'nbt': inv}, 'Pos') if cargo else None
    return dict(cargo=cargo, position=position, result=result)


def verify(trace, hands):
    first = trace[0]['cargo']
    assert first['id'] == SHEET and first['count'] == 1 and first['marked'], first
    used = []
    for row in trace:
        cargo = row['cargo']
        if not cargo or not cargo['assembly']:
            continue
        assembly = cargo['assembly']
        step = assembly['step']
        assert cargo['id'] == INCOMPLETE and cargo['count'] == 1 and not cargo['marked'], row
        assert assembly['id'] == RECIPE and abs(assembly['progress'] - step / TOTAL) < 6e-8, row
        if not used or used[-1] != step:
            used.append(step)
            assert abs(row['position'] - (step + .5)) < .3, row
    assert used == list(range(1, TOTAL)), used
    final = trace[-1]['result']
    assert not trace[-1]['cargo'] and final and final['id'] in RESULTS, trace[-1]
    assert final['count'] == 1 and final['assembly'] is None and not final['marked'], final
    assert hands == [{}] * TOTAL, hands


def comparable(row):
    def mask_roll(item):
        if item and not item['assembly'] and not item['marked']:
            assert item['id'] in RESULTS, item
            return dict(item, id='weighted_result')
        return item

    return dict(row, cargo=mask_roll(row['cargo']), result=mask_roll(row['result']))


def java(work):
    host = Original()
    state = host.call('state', {})
    if state.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        state = host.call('state', {})
    assert state['ready'] and state['data_version'] == 3955

    def advance(ticks):
        return host.call('observe_ticks', {'positions': [START, OUTPUT], 'ticks': ticks})['samples']

    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {TICKET}')
        host.command(f'tp @s {X+8}.5 {Y+4} {Z+2}.5')
        advance(24)
        setup(host.command, advance)
        trace = []
        for i in range(0, TICKS, 60):
            trace.extend(observe(*(block['nbt'] for block in row['blocks']))
                         for row in advance(min(60, TICKS - i)))
        hands = [tag_items(host.call('block', {'pos': pos})['nbt'], 'HeldItem') for pos in DEPLOYERS]
        return trace, hands
    finally:
        host.command(f'fill {ROOM} minecraft:air')
        host.command(f'forceload remove {TICKET}')
        host.call('camera', {key: state[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': state['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session, reference):
    def sample(batch, ticks):
        for _ in range(ticks):
            batch.tick()
            batch.data(START)
            batch.data(OUTPUT)

    def observe_pairs(rows):
        return [observe(belt, depot) for belt, depot in zip(rows[::2], rows[1::2], strict=True)]

    cut = next(index for index, row in enumerate(reference, 1)
               if row['cargo'] and (row['cargo']['assembly'] or {}).get('step') == 7)
    first = Batch()
    first.load((X + 8, Y + 3, Z + 2))
    setup(first.command, first.tick)
    sample(first, cut)
    warm = observe_pairs(first.run(session, 'before-restart'))

    second = Batch()
    second.load((X + 8, Y + 3, Z + 2))
    second.data(START)
    second.data(OUTPUT)
    sample(second, TICKS - cut)
    for pos in DEPLOYERS:
        second.data(pos)
    rows = second.run(session, 'after-restart')
    cold, *resumed = observe_pairs(rows[:-TOTAL])
    assert cold == warm[-1], (cold, warm[-1])
    assert cold['cargo'] and (cold['cargo']['assembly'] or {}).get('step') == 7, cold
    return warm + resumed, [tag_items(row, 'HeldItem') for row in rows[-TOTAL:]], cut


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + key, type=Path)
    args = parser.parse_args()
    if args.game:
        if not all((args.resources, args.ctl, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None, name='sequenced-belt-native',
                                     graphics=False, world='CreatePrecisionLine')
        work = session.scratch
        try:
            trace, hands, checkpoint = native(session, reference['trace'])
        finally:
            session.control_temp.cleanup()
            for folder in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(folder, ignore_errors=True)
    else:
        work = Path(tempfile.mkdtemp(prefix='sequenced-belt-java-', dir=ROOT / '.local'))
        trace, hands = java(work)
        checkpoint = None
    path = work / 'result.json'
    result = dict(passed=False, create=PINS['create_revision'], trace=trace, hands=hands, checkpoint=checkpoint)
    path.write_text(json.dumps(result, indent=2) + '\n')
    verify(trace, hands)
    if args.game:
        for tick, (actual, original) in enumerate(zip(trace, reference['trace'], strict=True), 1):
            assert comparable(actual) == comparable(original), (tick, actual, original)
    result['passed'] = True
    path.write_text(json.dumps(result, indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
