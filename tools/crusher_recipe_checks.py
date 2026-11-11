#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare original crushing recipes through a powered wheel and a Chute."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import items, number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from crushing_wheel_checks import AIR, CHUTE, CONTROLLER, X, Y, put, seed_chute, wheels
from native_check_session import NativeCheckSession
from reference_java import BASE, CREATE_SHA256


DATA = ROOT / 'content/data'
RECIPES = DATA / 'create/recipe/crushing'
CENTRE = (X, Y + 4, 1200)
AREA = '2132 166 1169 2136 172 1231'
LOAD = '2128 1168 2143 1231'
DROPS = '@e[type=minecraft:item,x=2132,y=166,z=1169,dx=4,dy=6,dz=62]'
TICKS = 30
TAG_SAMPLES = {'minecraft:wool': 'minecraft:cyan_wool',
               'create:stone_types/diorite': 'create:cut_diorite'}


def fixtures():
    cases = []
    for path in sorted(RECIPES.glob('*.json')):
        # No supported decorative Tuff item exercises this recipe separately
        # from the plain Tuff recipe, which wins for minecraft:tuff in Java.
        if path.stem == 'tuff_recycling':
            continue
        recipe = json.loads(path.read_text())
        [ingredient] = recipe['ingredients']
        if ingredient.startswith('#'):
            tag = ingredient[1:]
            if tag in TAG_SAMPLES:
                ingredient = TAG_SAMPLES[tag]
            else:
                namespace, name = tag.split(':', 1)
                tag_file = DATA / f'{namespace}/tags/item/{name}.json'
                [ingredient] = json.loads(tag_file.read_text())['values']
        cases.append((path.stem, ingredient, recipe))
    for start in range(0, len(cases), 16):
        yield [(1170 + 4 * i, *case) for i, case in enumerate(cases[start:start + 16])]


def cleanup(command):
    command(f'kill {DROPS}')
    command(f'fill {AREA} {AIR}')


def setup(command, tick, lanes):
    cleanup(command)
    command('fill 2132 166 1169 2136 166 1231 minecraft:smooth_stone')
    for z, *_ in lanes:
        wheels(command, z)
    tick(28)
    for z, *_ in lanes:
        put(command, (X, Y + 1, z), CHUTE)
    tick(28)
    for z, _, item, _ in lanes:
        seed_chute(command, z, item, 1, z)


def sample(raw, lanes):
    result = []
    for z, _, item, _ in lanes:
        controller, chute = next(raw), next(raw)
        assert CONTROLLER in controller and 'create:chute' in chute, (controller, chute)
        held = items(controller, 'Inventory')
        applied = number({'nbt': controller}, 'AppliedRecipe') != 0
        if not applied and item in held:
            assert number({'nbt': controller}, 'crusher_marker') == z
        result.append(dict(rpm=number({'nbt': controller}, 'Speed'),
                           remaining=number({'nbt': controller}, 'ProcessingTime'),
                           applied=applied,
                           held=held, inlet=items(chute, 'Item')))
    return result


def summarize(trace, lanes):
    phases = {}
    for index, (_, name, item, recipe) in enumerate(lanes):
        rows = [tick[index] for tick in trace]
        assert all(row['rpm'] == 1.28 for row in rows), (name, rows)
        assert rows[0]['held'] == {item: 1} and not rows[0]['inlet'], (name, rows[0])
        assert rows[0]['remaining'] == recipe['processing_time'], (name, rows[0])
        application = next(i for i, row in enumerate(rows, 1) if row['applied'])
        assert application == recipe['processing_time'] // 20 + 1, (name, application)
        actual = rows[application - 1]['held']
        minimum, maximum = {}, {}
        for output in recipe['results']:
            ident, count = output['id'], output.get('count', 1)
            if output.get('chance', 1) == 1:
                minimum[ident] = minimum.get(ident, 0) + count
            maximum[ident] = maximum.get(ident, 0) + count
        assert actual.keys() <= maximum.keys(), (name, actual, maximum)
        assert all(minimum.get(i, 0) <= actual.get(i, 0) <= count
                   for i, count in maximum.items()), (name, actual, minimum, maximum)
        assert not any(row['held'] or row['inlet'] for row in rows[application:]), name
        assert all(row['applied'] == (not actual) for row in rows[application:]), name
        # RNG streams differ, so compare every timing field and the bounds
        # separately from the optional output quantities.
        phases[name] = [dict(rpm=row['rpm'], remaining=row['remaining'],
                             applied=row['applied'] if i < application else None,
                             inlet=row['inlet'], processing=not row['applied'] and item in row['held'])
                        for i, row in enumerate(rows)]
    return phases


def java_run(work):
    host = Original()
    manifest = json.loads((BASE / 'manifest.json').read_text())
    assert manifest['create_sha256'] == CREATE_SHA256
    prior = host.call('state', {})
    assert prior['ready'] and prior['data_version'] == 3955, prior
    host.call('tick', {'frozen': True})

    try:
        host.command(f'forceload add {LOAD}')
        x, y, z = CENTRE
        host.command(f'tp @s {x}.5 {y} {z}.5')
        host.call('observe_ticks', {'positions': [CENTRE], 'ticks': 30})
        for lanes in fixtures():
            points = [(X, y, z) for z, *_ in lanes for y in (Y, Y + 1)]

            def observe(ticks):
                return host.call('observe_ticks', {'positions': points, 'ticks': ticks})['samples']

            setup(host.command, observe, lanes)
            trace = [sample(iter(block['nbt'] for block in row['blocks']), lanes)
                     for row in observe(TICKS)]
            yield lanes, trace
    finally:
        cleanup(host.command)
        host.command(f'forceload remove {LOAD}')
        host.call('camera', {k: prior[k] for k in ('position', 'yaw', 'pitch')})
        host.call('tick', {'frozen': prior['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    for group, lanes in enumerate(fixtures(), 1):
        batch = Batch()
        batch.load(CENTRE)
        setup(batch.command, batch.tick, lanes)
        for _ in range(TICKS):
            batch.tick()
            for z, *_ in lanes:
                batch.data((X, Y, z))
                batch.data((X, Y + 1, z))
        raw = iter(batch.run(session, f'recipes-{group}'))
        result = [sample(raw, lanes) for _ in range(TICKS)]
        assert next(raw, None) is None
        yield lanes, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='crusher-recipes-java-', dir=ROOT / '.local'))
        runs = java_run(work)
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon needs --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == PINS['create_revision']
        session = NativeCheckSession(args.game, args.resources, args.ctl, None, graphics=False,
                                     name='crusher-recipes-native', world='CrusherRecipes')
        work = session.scratch
        runs = native_run(session)
    phases = {}
    try:
        for group, (lanes, trace) in enumerate(runs, 1):
            (work / f'observed-{group}.json').write_text(json.dumps(trace, indent=2) + '\n')
            phases.update(summarize(trace, lanes))
    finally:
        runs.close()
        if not args.java:
            session.control_temp.cleanup()
            for path in (session.resources, work / '.horizon-cache'):
                shutil.rmtree(path, ignore_errors=True)
    if not args.java:
        assert phases.keys() == reference['phases'].keys()
        for name, rows in phases.items():
            assert rows == reference['phases'][name], (name, rows, reference['phases'][name])
    result = work / 'result.json'
    result.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], phases=phases),
                                 indent=2) + '\n')
    print(result)


if __name__ == '__main__':
    main()
