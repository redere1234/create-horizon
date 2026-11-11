#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare Deployer wax application and removal with the pinned Java client."""

import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import field, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from deployer_transport_checks import tag_items
from native_check_session import NativeCheckSession


ROOM = '1998 124 1200 2006 130 1216'
TICKET = '1998 1200 2006 1216'
TOOL = 'minecraft:diamond_axe'
WAX = 'minecraft:honeycomb_block'
LANES = (
    (1202, 'copper_block', ('waxed_copper_block', 'waxed_copper_block'), WAX),
    (1206, 'waxed_exposed_copper', ('exposed_copper', 'copper_block'), TOOL),
    (1210, 'weathered_cut_copper_slab', ('exposed_cut_copper_slab', 'cut_copper_slab'), TOOL),
    (1214, 'copper_block', (), 'minecraft:oak_planks'),
)
PROBES = [(2002, y, z) for z, *_ in LANES for y in (126, 128)]


def install(command, advance):
    command(f'fill {ROOM} minecraft:air')
    command('fill 1999 124 1201 2005 124 1215 minecraft:stone')
    for z, _, _, tool in LANES:
        damage = '"minecraft:damage":17,' if tool == TOOL else ''
        hand = (f'{{Slot:0b,id:"{tool}",count:1,components:{{{damage}'
                '"minecraft:custom_data":{copper_tool:31}}}')
        command(f'setblock 2002 126 {z} create:depot')
        command(f'setblock 2002 128 {z} create:deployer[facing=down,axis_along_first=true]'
                f'{{Mode:"USE",State:"WAITING",Timer:0,Inventory:[{hand}]}}')
    advance(2)
    for z, *_ in LANES:
        command(f'setblock 2001 128 {z} create:creative_motor[facing=east]{{ScrollValue:64}}')
    advance(23)
    for z, source, _, _ in LANES:
        command(f'data merge block 2002 126 {z} {{HeldItem:{{'
                f'Item:{{id:"minecraft:{source}",count:2}},Pos:.5f,PrevPos:.5f,Angle:180,InDirection:1}}}}')


def snapshot(rows):
    values = iter(rows)
    observed = []
    for _, _, _, tool in LANES:
        depot, deployer = next(values), next(values)
        hand = field(deployer, 'HeldItem')
        assert tag_items(deployer, 'HeldItem') == {tool: 1}, hand
        assert number({'nbt': hand}, 'copper_tool') == 31, hand
        damage = re.search(r'"minecraft:damage"\s*:\s*(\d+)', hand)
        assert (int(damage[1]) if damage else 0) == (17 if tool == TOOL else 0), hand
        observed.append([tag_items(depot, 'HeldItem'), tag_items(depot, 'OutputBuffer')])
    return observed


def verify(trace):
    for index, (_, source, results, _) in enumerate(LANES):
        original = [{f'minecraft:{source}': 2}, {}]
        assert trace[0][index] == original, trace[0]
        if not results:
            assert all(row[index] == original for row in trace)
            continue
        first, settled = ({f'minecraft:{result}': 1} for result in results)
        assert [{f'minecraft:{source}': 1}, first] in [row[index] for row in trace]
        assert trace[-1][index] == [settled, first], trace[-1]


def java(work):
    host = Original()
    initial = host.call('state', {})
    if initial.get('screen') == 'PauseScreen':
        host.call('input', {'kind': 'escape'})
        initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955

    def sample(ticks):
        return host.call('observe_ticks', {'ticks': ticks, 'positions': PROBES})['samples']

    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {TICKET}')
        host.command('tp @s 2002.5 130 1208.5')
        sample(24)
        install(host.command, sample)
        return [snapshot(block['nbt'] for block in row['blocks']) for row in sample(70)]
    finally:
        host.command(f'fill {ROOM} minecraft:air')
        host.command(f'forceload remove {TICKET}')
        host.call('camera', {key: initial[key] for key in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native(session):
    batch = Batch()
    batch.load((2002, 128, 1208))
    install(batch.command, batch.tick)
    for _ in range(70):
        batch.tick()
        for probe in PROBES:
            batch.data(probe)
    values = batch.run(session, 'wax-and-scrape')
    size = len(PROBES)
    return [snapshot(values[offset:offset + size]) for offset in range(0, len(values), size)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + argument, type=Path)
    args = parser.parse_args()
    if args.game:
        if not all((args.resources, args.ctl, args.reference)):
            parser.error('Horizon needs --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['create'] == PINS['create_revision'] and reference['passed']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None, name='deployer-copper-native',
                                     graphics=False, world='DeployerCopper')
        work = session.scratch
        try:
            rows = native(session)
        finally:
            session.control_temp.cleanup()
            for path in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(path, ignore_errors=True)
        for tick, (row, expected) in enumerate(zip(rows, reference['rows'], strict=True), 1):
            assert row == expected, (tick, row, expected)
    else:
        work = Path(tempfile.mkdtemp(prefix='deployer-copper-java-', dir=ROOT / '.local'))
        rows = java(work)
    verify(rows)
    output = work / 'result.json'
    output.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], rows=rows), indent=2) + '\n')
    print(output)


if __name__ == '__main__':
    main()
