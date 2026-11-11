#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare the Deployer and Saw hover hints in the original and native clients."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile
import time
from typing import NamedTuple

from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from deployer_filter_checks import POS, VIEWS, block, point
from native_check_session import NativeCheckSession, wait_loaded
from saw_filter_checks import FEET, OUTSIDE, SAW, center, saw

SET = 'Click with item to set'
REPLACE = 'Click with item to replace'
SAMPLE = '{Filter:{id:"minecraft:oak_planks",count:1}}'
TRACE = 'Create filter hover: '


class Case(NamedTuple):
    name: str
    pos: tuple
    feet: tuple
    aim: tuple
    state: str
    lines: tuple
    sneak: bool = False


CASES = (
    Case('deployer-empty', POS, VIEWS['south'], point('down', 'south'), block(),
         ('Filter', SET)),
    Case('deployer-filled', POS, VIEWS['north'], point('down', 'north'), block() + SAMPLE,
         ('Filter', REPLACE)),
    Case('deployer-top', POS, VIEWS['up'], point('east', 'up'), block('east', False),
         ('Filter', SET)),
    Case('deployer-shaft', POS, VIEWS['east'], point('down', 'east'), block(), ()),
    Case('deployer-sneak', POS, VIEWS['south'], point('down', 'south'), block(), (), True),
    Case('saw-empty', SAW, FEET, center(False, False), saw(False, False),
         ('Recipe Filter', SET)),
    Case('saw-filled', SAW, FEET, center(True, True), saw(True, True) + SAMPLE,
         ('Recipe Filter', REPLACE)),
    Case('saw-outside', SAW, FEET, OUTSIDE, saw(True, True), ()),
    Case('saw-horizontal', SAW, FEET, center(True, True), saw(True, True, 'north'), ()),
)


def stage(teleport, command):
    teleport(VIEWS['south'], POS)
    command('fill 1227 105 97 1235 115 106 minecraft:air')
    for x, y, z in VIEWS.values():
        command(f'setblock {int(x)} {y - 1} {int(z)} minecraft:smooth_stone')
    teleport(FEET, SAW)
    command('fill 1158 102 99 1163 106 106 minecraft:air')
    command('setblock 1160 104 104 minecraft:smooth_stone')


def java_rows(work):
    host = Original()
    initial = host.call('state', {})
    assert initial['ready'] and initial['data_version'] == 3955, initial
    host.call('tick', {'frozen': True})
    host.command('gamemode creative')
    regions = ('1216 96 1231 111', '1152 96 1167 111')

    def teleport(feet, pos):
        host.command('tp @s ' + xyz(feet))
        host.snapshot([pos], 16)

    try:
        for region in regions:
            host.command('forceload add ' + region)
        if initial['language'] != 'en_us':
            host.call('language', {'language': 'en_us'})
            for _ in range(80):
                if host.call('state', {})['ready']:
                    break
                time.sleep(.1)
        stage(teleport, host.command)
        host.command('gamemode survival')
        rows = {}
        for case in CASES:
            host.command(f'setblock {xyz(case.pos)} minecraft:air')
            host.command(f'setblock {xyz(case.pos)} {case.state}')
            host.snapshot([case.pos], 2)
            host.call('camera', {'position': case.feet, 'target': case.aim,
                                 'fov': 40, 'hide_gui': False})
            host.call('input', {'key': 'shift', 'down': case.sneak})
            # Let the preceding case's hover fade and the current one warm up.
            time.sleep(.7)
            ui = host.call('ui', {})
            assert ui['screen'] == 'playing' and tuple(ui['hit']['pos']) == case.pos, (case, ui)
            if case.name == 'deployer-sneak':
                # Java's stored tip can remain during the fade but is never
                # rendered while crouching. The Outliner no longer has an active box.
                assert not any(box['alive'] and not box['passive'] and tuple(box['pos']) == case.pos
                               for box in ui['value_boxes']), ui
            assert tuple(ui['value_hover_tip']) == case.lines, (case, ui)
            rows[case.name] = dict(lines=ui['value_hover_tip'], hit=ui['hit'])
            host.call('input', {'key': 'shift', 'down': False})
            if case.name in ('deployer-empty', 'saw-filled'):
                shot = host.call('capture', {'name': f'{work.name}/{case.name}.png'})
                shutil.copy2(shot['path'], work / f'{case.name}.png')
        return rows
    finally:
        host.call('input', {'key': 'shift', 'down': False})
        for region in regions:
            host.command('forceload remove ' + region)
        host.command('gamemode creative')
        if initial['language'] != 'en_us':
            host.call('language', {'language': initial['language']})
        host.call('camera', {'position': initial['position'], 'yaw': initial['yaw'],
                             'pitch': initial['pitch'], 'fov': initial['fov']})
        host.call('tick', {'frozen': initial['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_rows(session, reference):
    call = session.call

    def command(text):
        call('command', text)

    def teleport(feet, pos):
        command('tp @s ' + xyz(feet))
        wait_loaded(call, [pos])

    rows = {}
    with session:
        command('gamemode creative')
        call('options-set', 'fov', 40)
        call('options-set', 'bobView', 'false')
        stage(teleport, command)
        command('gamemode survival')
        for case in CASES:
            teleport(case.feet, case.pos)
            command(f'setblock {xyz(case.pos)} minecraft:air')
            command(f'setblock {xyz(case.pos)} {case.state}')
            call('look-at', *case.aim)
            if case.sneak:
                call('key', 'shift', 'down')
            call('wait', 16)
            hit = call('looking-at')['block']
            assert hit and tuple(hit['pos']) == case.pos, (case, hit)
            if reference is not None:
                assert hit['face'] == reference[case.name]['hit']['face'], (case, hit)
            log_start = session.log.stat().st_size
            call('wait', 8)
            with session.log.open('rb') as log:
                log.seek(log_start)
                seen = [json.loads(line.split(TRACE, 1)[1])
                        for line in log.read().decode().splitlines() if TRACE in line]
            if case.sneak:
                call('key', 'shift', 'up')
            expected = list(case.lines) if reference is None else reference[case.name]['lines']
            if expected:
                assert seen and all(lines == expected for lines in seen), (case, seen, expected)
            else:
                assert not seen, (case, seen)
            rows[case.name] = dict(lines=seen[-1] if seen else [], hit=hit)
            if case.name in ('deployer-empty', 'saw-filled'):
                call('screenshot', session.scratch / f'{case.name}.png')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for name in ('game', 'resources', 'ctl', 'create-jar', 'reference'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='contraption-filter-hover-java-', dir=ROOT / '.local'))
        print(work, flush=True)
        rows = java_rows(work)
    else:
        if not all((args.game, args.resources, args.ctl)):
            parser.error('native checks require --game, --resources and --ctl')
        reference = None
        if args.reference:
            report = json.loads(args.reference.read_text())
            assert report['passed'] and report['create'] == PINS['create_revision']
            reference = report['cases']
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='contraption-filter-hover', world='CreateFilterHover')
        work = session.scratch
        print(work, flush=True)
        (work / 'options.txt').write_text('lang:en_us\ntutorialStep:none\nchatVisibility:2\n')
        try:
            rows = native_rows(session, reference)
        finally:
            for folder in ('resources', '.horizon-cache', 'horizon-mods'):
                shutil.rmtree(work / folder, ignore_errors=True)
    path = work / 'result.json'
    path.write_text(json.dumps(dict(passed=True, create=PINS['create_revision'], cases=rows),
                               indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
