#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare Deployer wrench clicks and empty-hand Use versus Punch in real clients."""

import argparse
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile

from actor_native_checks import matched
from bearing_native_checks import Batch
from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from deployer_filter_checks import block, item_in
from goggles_checks import compare_hud, languages, wait_trace
from native_check_session import NativeCheckSession, wait_loaded
import reference_java


BODY = (1220, 109, 101)
LOAD = '1216 96 1231 111'
REGION = '1216 105 100 1226 113 111'
VIEWS = {
    'east': ([1223.5, 108, 101.5], [1220.99, 109.5, 101.5]),
    'west': ([1217.5, 108, 101.5], [1220.01, 109.5, 101.5]),
}
TAPS = (
    ('hand_load', 'east', 'minecraft:oak_sapling 3', 'USE', 'false'),
    ('hand_punch', 'east', 'create:wrench', 'PUNCH', 'false'),
    ('rear_shaft', 'west', 'create:wrench', 'PUNCH', 'true'),
    ('hand_use', 'east', 'create:wrench', 'USE', 'true'),
    ('hand_punch_again', 'east', 'create:wrench', 'PUNCH', 'true'),
)
LANES = (('USE', (1220, 109, 106)), ('PUNCH', (1220, 109, 109)))
LEVER = 'minecraft:lever[face=floor,facing=north'
TICKS = 84


def put(command, pos, state):
    command(f'setblock {xyz(pos)} {state}')


def prepare(command):
    command('gamemode creative')
    command(f'fill {REGION} minecraft:air')
    command('fill 1216 107 100 1225 107 102 minecraft:smooth_stone')
    command('item replace entity @s armor.head with create:goggles')
    put(command, BODY, block('east', False))


def tick_lanes(command):
    for mode, (x, y, z) in LANES:
        put(command, (x, y - 3, z), 'minecraft:stone')
        put(command, (x, y - 2, z), LEVER + ',powered=false]')
        put(command, (x, y, z), block() + f'{{Mode:"{mode}"}}')


def power_lanes(command):
    for _, (x, y, z) in LANES:
        put(command, (x - 1, y, z), 'create:creative_motor[facing=east]{ScrollValue:32}')


def state(nbt):
    return dict(mode=re.search(r'\bMode:\s*"([A-Z]+)"', nbt)[1],
                state=re.search(r'\bState:\s*"([A-Z]+)"', nbt)[1],
                timer=number({'nbt': nbt}, 'Timer'),
                speed=number({'nbt': nbt}, 'Speed', 0))


def tooltip(lines):
    return [line['text'].strip() for line in lines]


def normalize_components(value):
    # Java serializes the translated item count as a numeric component argument.
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list):
        return [normalize_components(part) for part in value]
    if isinstance(value, dict):
        return {key: normalize_components(part) for key, part in value.items()}
    return value


def goggles(ui):
    for line in ui['lines']:
        line['component'] = normalize_components(line['component'])
    return ui


def java_run(work):
    manifest = json.loads((reference_java.BASE / 'manifest.json').read_text())
    assert manifest['data_version'] == 3955 and manifest['create_sha256'] == reference_java.CREATE_SHA256
    host = Original()
    call = host.call
    command = host.command
    initial = call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial

    def frame(name, frames=12):
        return call('capture', {'name': f'{work.name}/{name}.png', 'frames': frames})

    report = dict(passed=False, source=PINS['create_revision'], clicks={})
    try:
        call('tick', {'frozen': True})
        command('tp @s ' + xyz(VIEWS['east'][0]))
        command(f'forceload add {LOAD}')
        call('observe_ticks', {'ticks': 24, 'positions': [BODY]})
        prepare(command)
        call('observe_ticks', {'ticks': 3, 'positions': [BODY]})
        for name, side, held, mode, first in TAPS:
            command('item replace entity @s weapon.mainhand with ' + held)
            position, point = VIEWS[side]
            call('camera', dict(position=position, target=point, fov=40, gui_scale=4, hide_gui=False))
            frame('aim')
            hit = call('state', {})['hit']
            assert hit['pos'] == list(BODY) and hit['face'] == side, hit
            call('input', {'key': 'use'})
            capture = frame(name, 40)
            call('input', {'key': 'use', 'down': False})
            current = call('block', {'pos': BODY})
            assert current['properties'] == {'facing': 'east', 'axis_along_first': first}, current
            assert state(current['nbt'])['mode'] == mode, current
            assert item_in(current['nbt'], 'HeldItem') == ['minecraft:oak_sapling', 3], current
            ui = goggles(call('ui', {})['goggles'])
            lines = tooltip(ui['lines'])
            assert lines[1] == ('Mode: Use' if mode == 'USE' else 'Mode: Attack'), lines
            shutil.copy2(capture['path'], work / (name + '.png'))
            report['clicks'][name] = dict(camera=capture['client'], lines=lines, ui=dict(goggles=ui))

        tick_lanes(command)
        points = [p for _, (x, y, z) in LANES for p in ((x, y, z), (x, y - 2, z))]
        call('observe_ticks', {'ticks': 3, 'positions': points})
        power_lanes(command)
        rows = []
        for ticks in (60, TICKS - 60):
            for sample in call('observe_ticks', {'ticks': ticks, 'positions': points})['samples']:
                frames = sample['blocks']
                rows.append([state(frames[i]['nbt']) | dict(lever=frames[i + 1]['properties']['powered'])
                             for i in range(0, len(frames), 2)])
        assert {row[0]['lever'] for row in rows} == {'true', 'false'}, rows
        assert all(row[1]['lever'] == 'false' for row in rows), rows
        assert all(any(row[i]['state'] == 'RETRACTING' for row in rows) for i in range(len(LANES))), rows
        report.update(passed=True, trace=rows)
    finally:
        call('input', {'key': 'use', 'down': False})
        command(f'fill {REGION} minecraft:air')
        command(f'forceload remove {LOAD}')
        call('camera', {k: initial[k] for k in ('position', 'yaw', 'pitch', 'fov', 'gui_scale')})
        call('tick', {'frozen': initial['server']['frozen']})
        save(work, report)
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_ticks(session, reference):
    batch = Batch()
    batch.load(BODY)
    tick_lanes(batch.command)
    batch.tick(3)
    power_lanes(batch.command)
    for row in reference:
        batch.tick()
        for (_, (x, y, z)), sample in zip(LANES, row, strict=True):
            batch.data((x, y, z))
            batch.expect((x, y - 2, z), LEVER + ',powered=' + sample['lever'] + ']')
    rows = batch.run(session, 'deployer-mode-ticks')
    observed = []
    for tick, lane_samples in enumerate(reference, 1):
        for lane, expected in enumerate(lane_samples):
            index = 2 * ((tick - 1) * len(LANES) + lane)
            actual = state(rows[index])
            lever = matched(rows[index + 1])
            assert lever and actual == {k: v for k, v in expected.items() if k != 'lever'}, (
                tick, lane, actual, expected, rows[index + 1])
            observed.append(dict(tick=tick, lane=lane, state=actual, lever_match=lever))
    return observed


def native_run(session, reference):
    report = dict(passed=False, source=PINS['create_revision'], clicks={})
    locale = languages()['en_us']
    try:
        with session:
            call = session.call

            def command(value):
                return ' '.join(call('command', value)['chat'])

            command('tp @s ' + xyz(VIEWS['east'][0]))
            wait_loaded(call, [BODY])
            prepare(command)
            call('options-set', 'fov', 40)
            call('options-set', 'guiScale', 4)
            for name, side, held, mode, first in TAPS:
                call('look', 0, -80)
                call('wait', 3)
                after = session.log.stat().st_size
                command('item replace entity @s weapon.mainhand with ' + held)
                pose = reference['clicks'][name]['camera']
                command('tp @s ' + xyz(pose['position']))
                call('look', pose['yaw'], pose['pitch'])
                call('wait', 7)
                hit = call('looking-at')['block']
                assert hit['pos'] == list(BODY) and hit['face'] == side, hit
                call('mouse', 'right', 'click')
                call('wait', 8)
                row = command('data get block ' + xyz(BODY))
                assert state(row)['mode'] == mode and item_in(row, 'HeldItem') == ['minecraft:oak_sapling', 3], row
                match = command(f'execute if block {xyz(BODY)} {block("east", first == "true")} '
                                'run say bearing_check')
                assert matched(match), (name, match)
                expected = reference['clicks'][name]
                ui = wait_trace(call, session.log, 'Create visual: ',
                                lambda row: row.get('event') == 'goggles_hud' and row.get('pos') == list(BODY)
                                and tooltip(row['lines']) == expected['lines'], after)
                failures = compare_hud(expected, goggles(ui), locale)
                report['clicks'][name] = dict(nbt=row, ui=ui, failures=failures)
                call('screenshot', session.scratch / (name + '.png'))
                assert not failures, (name, failures)
            session.restart()
            wait_loaded(call, [BODY])
            saved = command('data get block ' + xyz(BODY))
            assert state(saved)['mode'] == 'PUNCH' and item_in(saved, 'HeldItem') == ['minecraft:oak_sapling', 3], saved
            report['cold'] = state(saved)

        report['trace'] = native_ticks(session, reference['trace'])
        report['passed'] = True
    finally:
        for path in (session.resources, session.scratch / '.horizon-cache', session.scratch / 'horizon-mods'):
            shutil.rmtree(path, ignore_errors=True)
        save(session.scratch, report)


def save(work, report):
    path = work / 'result.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(path, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'jar', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='deployer-mode-java-', dir=ROOT / '.local'))
        java_run(work)
        return
    if not all((args.game, args.resources, args.ctl, args.reference)):
        parser.error('Specify --java or --game, --resources, --ctl and --reference')
    reference = json.loads(args.reference.read_text())
    assert reference['passed'] and reference['source'] == PINS['create_revision']
    width, height = reference['clicks']['hand_load']['camera']['gui_size']
    # The offscreen window uses 2x backing pixels on macOS.
    window_scale = 2 if sys.platform == 'darwin' else 4
    session = NativeCheckSession(args.game, args.resources, args.ctl, args.jar,
                                 name='deployer-mode-native', graphics=True, world='DeployerModes',
                                 size=(int(width) * window_scale, int(height) * window_scale),
                                 username='BearingReview')
    native_run(session, reference)


if __name__ == '__main__':
    main()
