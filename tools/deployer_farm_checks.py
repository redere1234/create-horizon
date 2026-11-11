#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare a rotating sapling Deployer in the pinned Java and native clients."""
import argparse
import json
from pathlib import Path
import re
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded
import reference_java as java


PIVOT = (1159, 99, 55)
MOTOR = (1159, 98, 55)
DEPLOYER = (1161, 100, 55)
ROTOR = ((1159, 100, 55), (1160, 100, 55))
SOIL = [(x, 97, z) for x in range(1156, 1163) for z in range(52, 59)]
RING = [(x, 98, z) for x, _, z in SOIL if 0 < max(abs(x - 1159), abs(z - 55)) <= 2]
ROCK = (1160, 97, 54)
PRE_PLANTED = (1160, 98, 57)
STOCK = 24
TICKS = 40
SAPLING = 'minecraft:oak_sapling'


def setup(command, loaded=True, stock=STOCK):
    command('fill 1154 95 51 1165 106 62 minecraft:air')
    command('fill 1154 96 51 1165 96 62 minecraft:smooth_stone')
    command('fill 1156 97 52 1162 97 58 minecraft:dirt')
    command(f'setblock {xyz(ROCK)} minecraft:stone')
    command(f'setblock {xyz(PRE_PLANTED)} {SAPLING}')
    command(f'setblock {xyz(PIVOT)} create:mechanical_bearing[facing=up]')
    for pos in ROTOR:
        command(f'setblock {xyz(pos)} minecraft:slime_block')
    nbt = f'{{Mode:"USE",Inventory:[{{Slot:0b,id:"{SAPLING}",count:{stock}}}]}}' if loaded else ''
    command(f'setblock {xyz(DEPLOYER)} create:deployer[facing=down,axis_along_first=false]{nbt}')


def start(command):
    command(f'setblock {xyz(MOTOR)} create:creative_motor[facing=up]{{ScrollValue:32}}')


def stop(command):
    command(f'setblock {xyz(MOTOR)} minecraft:air')


def planted(blocks):
    return [list(p) for p, block in zip(RING, blocks, strict=True) if block['id'] == SAPLING]


def held_count(nbt):
    held = re.search(r'HeldItem\s*:\s*\{([^}]*)\}', nbt)
    if held and SAPLING in held[1]:
        count = re.search(r'count\s*:\s*(\d+)', held[1])
        assert count, nbt
        return int(count[1])
    return 0


def java_review(base):
    java.BASE = base
    manifest = json.loads((base / 'manifest.json').read_text())
    assert manifest['create_sha256'] == java.CREATE_SHA256 and manifest['data_version'] == 3955
    host = Original()
    work = Path(tempfile.mkdtemp(prefix='deployer-rotary-java-', dir=ROOT / '.local'))
    report = dict(passed=False, create=PINS['create_revision'])
    try:
        host.call('tick', {'frozen': True})
        host.command('gamemode creative')
        host.command('tp @s 1156.5 98 60.5')
        host.command('forceload add 1152 48 1167 63')
        host.call('observe_ticks', {'ticks': 24, 'positions': [PIVOT]})
        setup(host.command)
        start(host.command)
        samples = host.call('observe_ticks', {'ticks': TICKS, 'positions': [PIVOT, *RING]})['samples']
        report['trace'] = [dict(tick=s['tick'], angle=number(s['blocks'][0], 'Angle'),
                                planted=planted(s['blocks'][1:])) for s in samples]
        stop(host.command)
        final = host.call('observe_ticks', {'ticks': 2, 'positions': [PIVOT, *RING, DEPLOYER]})['samples'][-1]['blocks']
        assert number(final[0], 'Running') == 0 and final[-1]['id'] == 'create:deployer', final[-1]
        report['planted'] = planted(final[1:-1])
        report['remaining'] = held_count(final[-1]['nbt'])
        assert len(report['planted']) > 6, report
        assert report['remaining'] == STOCK - (len(report['planted']) - 1), report
        report['landed_properties'] = final[-1]['properties']
        report['passed'] = True
    finally:
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')
        print(json.dumps(dict(result=str(work / 'result.json'), passed=report['passed'])))


def native_timing(session, reference):
    batch = Batch()
    batch.load((1157, 98, 60))
    setup(batch.command)
    start(batch.command)
    for _ in range(TICKS):
        batch.tick()
        batch.data(PIVOT)
        for pos in RING:
            batch.expect(pos, SAPLING)
    stop(batch.command)
    batch.tick(2)
    batch.data(PIVOT)
    batch.data(DEPLOYER)
    properties = ','.join(f'{key}={value}' for key, value in reference['landed_properties'].items())
    batch.expect(DEPLOYER, f'create:deployer[{properties}]')
    rows = batch.run(session, 'deployer-rotary-timing')
    stride = 1 + len(RING)
    assert len(rows) == TICKS * stride + 3, len(rows)
    trace = []
    for i in range(TICKS):
        row = rows[i * stride:(i + 1) * stride]
        trace.append(dict(tick=i + 1, angle=number({'nbt': row[0]}, 'Angle', 0),
                          planted=[list(pos) for pos, cell in zip(RING, row[1:], strict=True)
                                   if 'bearing_check' in cell]))
    assert [row['angle'] for row in trace] == [row['angle'] for row in reference['trace']]
    assert [row['planted'] for row in trace] == [row['planted'] for row in reference['trace']], [
        dict(tick=native['tick'], native=native, java=original)
        for native, original in zip(trace, reference['trace'], strict=True)
        if native['planted'] != original['planted']
    ][:4]
    assert number({'nbt': rows[-3]}, 'Running') == 0, rows[-3]
    assert held_count(rows[-2]) == reference['remaining'], rows[-2]
    assert 'bearing_check' in rows[-1], rows[-1]
    return trace


def native_interactions(session, reference):
    batch = Batch()
    batch.load((1157, 98, 60))
    setup(batch.command, loaded=False)
    batch.command(f'data merge block {xyz(DEPLOYER)} {{Owner:[I;11,22,33,44]}}')
    batch.run(session, 'deployer-rotary-hand')
    call = session.call

    def command(line):
        return call('command', line)

    def hand_click(pos):
        x, y, z = pos
        command(f'tp @s {x + 1.5} {y - 2} {z + 0.5}')
        call('wait', 5)
        call('look-at', x + 0.5, y + 0.00001, z + 0.5)
        call('wait', 4)
        hit = call('looking-at')['block']
        assert hit['pos'] == list(pos) and hit['face'] == 'down', hit
        call('mouse', 'right', 'click')
        call('wait', 8)

    def data(pos):
        return ' '.join(command(f'data get block {xyz(pos)}')['chat'])

    def hand_count():
        slot = call('inventory')['hotbar'][0]
        return slot.get('count', 0) if slot.get('item') == SAPLING else 0

    with session:
        wait_loaded(call, [PIVOT, DEPLOYER, *RING[::8]])
        command('gamemode survival')
        command('clear @s')
        call('select', 1)
        command(f'item replace entity @s weapon.mainhand with {SAPLING} {STOCK}')
        call('wait', 5)
        assert hand_count() == STOCK
        hand_click(DEPLOYER)
        assert hand_count() == 0 and held_count(data(DEPLOYER)) == STOCK
        command('tp @s 1155.5 97 59.5')
        start(command)
        call('wait', TICKS + 5)
        assert number({'nbt': data(PIVOT)}, 'Running') == 1
        assert call('block', *DEPLOYER)['block'] == 'minecraft:air'
        call('save')
        session.restart()
        wait_loaded(call, [PIVOT, DEPLOYER])
        assert number({'nbt': data(PIVOT)}, 'Running') == 1
        stop(command)
        call('wait', 8)
        assert number({'nbt': data(PIVOT)}, 'Running') == 0
        landed = [p for p in [(x, 100, z) for x in range(1157, 1162) for z in range(53, 58)]
                  if call('block', *p)['block'] == 'create:deployer']
        assert len(landed) == 1, landed
        final = data(landed[0])
        assert re.search(r'Owner\s*:\s*\[I;\s*11,\s*22,\s*33,\s*44\]', final), final
        field = [p for p in RING if call('block', *p)['block'] == SAPLING]
        assert len(field) == len(reference['planted']), field
        remaining = STOCK - (len(field) - 1)
        assert held_count(final) == remaining, final
        hand_click(landed[0])
        assert hand_count() == remaining and held_count(data(landed[0])) == 0
        hand_click(landed[0])
        assert hand_count() == 0 and held_count(data(landed[0])) == remaining
    return dict(planted=field, landed=landed[0], remaining=held_count(final), owner_preserved=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', type=Path)
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--create-jar', type=Path)
    args = parser.parse_args()
    if args.java:
        java_review(args.java.resolve())
        return
    if not all([args.game, args.resources, args.ctl, args.reference]):
        parser.error('Pass --java or --game, --resources, --ctl and --reference')
    reference = json.loads(args.reference.read_text())
    assert reference['passed'], args.reference
    session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                 name='deployer-rotary-native', world='CreateDeployerTiming', username='BearingReview')
    print(session.scratch, flush=True)
    try:
        timing = native_timing(session, reference)
        # A timed field is harvested only by the test reset. Use a separate
        # live world so its dropped saplings cannot enter the test player's hand.
        session.world = 'CreateDeployerFarm'
        live = native_interactions(session, reference)
        result = session.scratch / 'result.json'
        result.write_text(json.dumps(dict(passed=True, timing=timing, live=live), indent=2) + '\n')
        print(json.dumps(dict(passed=True, result=str(result))))
    finally:
        session.control_temp.cleanup()


if __name__ == '__main__':
    main()
