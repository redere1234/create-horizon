#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare Hand Crank placement and support loss in the actual clients."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from burner_heat_java_checks import number
from chain_drive_checks import Native, Original, xyz
from common import PINS, ROOT
from fluid_tank_checks import click
from funnel_checks import block, step, text
from native_check_session import NativeCheckSession, wait_loaded
from reference_java import BASE, CREATE_SHA256


CRANK = 'create:hand_crank'
AIR, WATER, STONE = ('minecraft:' + block for block in ('air', 'water', 'smooth_stone'))
X, Y, Z = 3431, 103, 1783
ORIGIN = (X, Y, Z)
AREA = '3426 101 1778 3436 107 1788'
LOAD = '3424 1776 3439 1791'
DROPS = '@e[type=minecraft:item,x=3426,y=101,z=1778,dx=10,dy=6,dz=10]'
DIRECTIONS = dict(down=(0, -1, 0), up=(0, 1, 0), north=(0, 0, -1),
                  south=(0, 0, 1), west=(-1, 0, 0), east=(1, 0, 0))


def put(host, pos, state):
    host.command(f'setblock {xyz(pos)} {state}')


def clean(host):
    host.command(f'kill {DROPS}')
    host.command(f'fill {AREA} {AIR}')


def state(host, pos):
    if isinstance(host, Native):
        host.session.call('wait', 4)
    row = block(host, pos)
    return dict(id=row['id'], properties={k: v.lower() for k, v in row['properties'].items()})


def crank(facing, wet):
    return f'{CRANK}[facing={facing},waterlogged={str(wet).lower()}]'


def audit(host, work):
    report = {}
    host.command('gamemode creative')
    drop_rule = 'minecraft:block_drops' if isinstance(host, Native) else 'doTileDrops'
    host.command(f'gamerule {drop_rule} true')
    for facing, (dx, dy, dz) in DIRECTIONS.items():
        clean(host)
        support = (X - dx, Y - dy, Z - dz)
        unrelated = (X + dx, Y + dy, Z + dz)
        put(host, support, STONE)
        wet = facing == 'down'
        put(host, ORIGIN, crank(facing, wet))
        put(host, unrelated, STONE)
        put(host, unrelated, AIR)
        kept = state(host, ORIGIN)
        assert kept == dict(id=CRANK, properties=dict(facing=facing, waterlogged=str(wet).lower())), kept
        put(host, support, AIR)
        step(host, 1, ORIGIN)
        removed = state(host, ORIGIN)
        drop = CRANK in text(host, f'data get entity {DROPS[:-1]},limit=1] Item.id')
        assert removed['id'] == (WATER if wet else AIR) and drop, (facing, removed, drop)
        report[facing] = dict(kept=kept, removed=removed, dropped=drop)
    for wet in (False, True):
        clean(host)
        host.command(f'fill {X-3} {Y-2} {Z-2} {X+3} {Y-2} {Z+4} {STONE}')
        support = (X, Y, Z - 1)
        put(host, support, 'minecraft:oak_slab[type=bottom]')
        if wet:
            put(host, ORIGIN, WATER)
        name = 'wet_slab' if wet else 'dry_slab'
        click(host, work, name, CRANK, feet=(X + .5, Y - 1, Z + 3.25),
              aim=(X + .5, Y + .25, Z), pos=support, face='south')
        mounted = state(host, ORIGIN)
        assert mounted == dict(id=CRANK, properties=dict(facing='south', waterlogged=str(wet).lower())), mounted
        report[name] = mounted
        if not wet:
            put(host, (X, Y, Z + 2), STONE)
            put(host, (X + 1, Y, Z), STONE)
            [rest] = step(host, 12, ORIGIN)
            assert number(rest, 'InUse', 0) == 0, rest
            sight = dict(feet=(X + .5, Y + 1, Z + 2.5),
                         aim=(X + .5, Y + .92, Z + .3), pos=ORIGIN, face='up')
            if isinstance(host, Original):
                host.call('camera', {'position': sight['feet']})
                host.call('capture', {'name': f'{work.name}/wrench-stand.png', 'frames': 8})
            click(host, work, 'wrench', 'create:wrench', **sight)
            after = block(host, ORIGIN)
            assert after['properties']['facing'] == 'south' and number(after, 'InUse', 0) > 0, after
            report['wrench'] = dict(facing=after['properties']['facing'], running=True)
    return report


def java_run(work):
    host = Original()
    assert json.loads((BASE / 'manifest.json').read_text())['create_sha256'] == CREATE_SHA256
    prior = host.call('state', {})
    assert prior['ready'] and prior['data_version'] == 3955
    drops = 'true' in text(host, 'gamerule doTileDrops').lower()
    host.call('tick', {'frozen': True})
    try:
        host.command(f'forceload add {LOAD}')
        host.command(f'tp @s {X + .5} {Y + 4} {Z + .5}')
        host.call('observe_ticks', {'ticks': 24, 'positions': [ORIGIN]})
        return audit(host, work)
    finally:
        clean(host)
        host.command(f'gamerule doTileDrops {str(drops).lower()}')
        host.command(f'forceload remove {LOAD}')
        host.call('camera', {k: prior[k] for k in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': prior['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='crank-support-java-', dir=ROOT / '.local'))
        report = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon requires --game, --resources, --ctl and --reference')
        source = json.loads(args.reference.read_text())
        assert source['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='crank-support-native', world='CrankSupport')
        work = session.scratch
        try:
            with session:
                host = Native(session)
                host.command(f'tp @s {X + .5} {Y + 4} {Z + .5}')
                wait_loaded(session.call, [ORIGIN])
                host.command('tick freeze')
                report = audit(host, work)
        finally:
            for path in (session.resources, work / '.horizon-cache', work / 'horizon-mods'):
                shutil.rmtree(path, ignore_errors=True)
        assert report == source['cases'], (report, source)
    result = work / 'result.json'
    result.write_text(json.dumps(dict(create=PINS['create_revision'], cases=report), indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
