#!/usr/bin/env python3
"""Pair eight original Mixer HUD scenes with a fresh native rendered client.

This compares actual provider text/styles/font advances and layout. Saved PNGs
need human review, including absence cases. It does not prove full-frame pixel
or animation-phase equality. Overstress precedence has a separate CPU oracle.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from common import ROOT, PINS
from goggles_checks import compare_hud, png_size, traces, wait_trace
from goggles_mixer_reference import CASES, MIXER, MOTOR, CAMERA, xyz
from native_check_session import NativeCheckSession, wait_loaded


def validate_reference(path):
    path = Path(path).resolve()
    path.relative_to((ROOT / '.local').resolve())
    source = json.loads(path.read_text())
    assert source['passed'] and source['reference'] == PINS['create_revision']
    assert [row['spec'] for row in source['cases']] == CASES
    for row in source['cases']:
        assert row['visually_inspected'] and row['state']['hit']['pos'] == MIXER
        assert row['state']['gui_size'] == [640, 360]
        assert hashlib.sha256(Path(row['capture']['path']).read_bytes()).hexdigest() == row['capture']['sha256']
        assert png_size(row['capture']['path']) == [2560, 1440]
    locales = {key: json.loads((path.parent / ('lang-' + key + '.json')).read_text())
               for key in ('en_us', 'ru_ru')}
    return source, locales


def run(call, graphics, log, scratch, reference):
    assert graphics, 'Mixer HUD acceptance requires a rendered client'
    scratch = Path(scratch).resolve()
    scratch.relative_to((ROOT / '.local').resolve())
    source, locales = validate_reference(reference)
    report = dict(passed=False, reference=str(Path(reference).resolve()), cases=[], scope=__doc__)
    output = scratch / 'goggles-mixer-native-result.json'
    transcript = scratch / 'goggles-mixer-native-transcript.jsonl'
    transcript.write_text('')

    def save():
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')

    def ctl(*words):
        reply = call(*words)
        with transcript.open('a') as stream:
            stream.write(json.dumps(dict(command=list(map(str, words)), reply=reply), ensure_ascii=False) + '\n')
        return reply

    def cmd(text):
        reply = ctl('command', text)
        assert not any('not loaded' in line or 'Unknown block' in line for line in reply.get('chat', [])), reply
        return reply

    save()
    try:
        ctl('release')
        cmd('tick unfreeze')
        cmd('gamemode creative')
        # /data get uses command feedback too. Keep authoritative query output
        # available; chatVisibility below hides command text in the screenshots.
        cmd('gamerule minecraft:send_command_feedback true')
        cmd('gamerule minecraft:spawn_mobs false')
        cmd('gamerule minecraft:advance_time false')
        cmd('time set 6000')
        cmd('weather clear')
        cmd('tp @s ' + xyz(CAMERA))
        ctl('wait-ready', 120)
        wait_loaded(ctl, [(x, 63, z) for x in (480, 492) for z in (12, 26)])
        cmd('fill 480 64 12 492 72 26 minecraft:air')
        cmd('fill 480 63 12 492 63 26 minecraft:smooth_stone')
        cmd('clear @s')
        cmd('item replace entity @s weapon.offhand with minecraft:air')
        cmd('setblock 485 66 18 create:cogwheel[axis=y]')
        cmd('setblock ' + xyz(MIXER) + ' create:mechanical_mixer')
        for key, value in [('guiScale', 4), ('fov', 70), ('bobView', 'false'),
                           ('tutorialStep', 'none'), ('chatVisibility', 2)]:
            ctl('options-set', key, value)
        ctl('wait', 20)
        cmd('kill @e[type=minecraft:item]')
        cmd('clear @s')
        assert ctl('ui')['gui_size'] == [640, 360]
        language = None
        for row in source['cases']:
            case = row['spec']
            result = dict(name=case['name'], java_image=row['capture'], failures=[], visually_inspected=False)
            report['cases'].append(result)
            cmd('tick unfreeze')
            ctl('look', 0, -80)
            ctl('wait', 3)
            cmd('setblock ' + xyz(MOTOR) + ' minecraft:air')
            if case['rpm']:
                cmd('setblock ' + xyz(MOTOR) +
                    ' create:creative_motor[facing=up]{ScrollValue:' + str(-case['rpm']) + '}')
            ctl('wait', 30)
            nbt = ' '.join(cmd('data get block ' + xyz(MIXER))['chat'])
            speed = re.search(r'\bSpeed:\s*([-+0-9.Ee]+)', nbt)
            assert speed and float(speed[1]) == case['rpm'], (case, nbt)
            result['canonical_before_freeze'] = nbt
            if case['frozen']:
                cmd('tick freeze')
            if language != case['language']:
                ctl('options-set', 'lang', case['language'])
                ctl('wait-ready', 120)
                language = case['language']
            cmd('item replace entity @s armor.head with ' +
                ('create:goggles' if case['goggles'] else 'minecraft:air'))
            pose = row['state']
            cmd('tp @s ' + xyz(pose['position']))
            ctl('wait', 8)
            player = ctl('state')['player']
            assert player['on_ground'] and all(abs(a-b) < .001 for a,b in zip(player['position'], pose['position'])), player
            after = Path(log).stat().st_size
            ctl('look', pose['yaw'], pose['pitch'])
            if row['ui']['goggles']['lines']:
                actual = wait_trace(ctl, log, 'Create visual: ',
                    lambda item: item.get('event') == 'goggles_hud' and item.get('pos') == MIXER, after)
                result['native'] = actual
                result['failures'] = compare_hud(row, actual, locales[language])
            else:
                ctl('wait', 30)
                rows = [item for item in traces(log, 'Create visual: ', after)
                        if item.get('event') == 'goggles_hud' and item.get('pos') == MIXER]
                assert not rows, rows
                result['absence_scope'] = 'No HUD trace; saved PNG must also be inspected'
            ctl('wait', 30)
            result['native_state'] = ctl('state')
            image = scratch / ('goggles-' + case['name'] + '.png')
            ctl('screenshot', image)
            assert png_size(image) == [2560, 1440]
            result['native_image'] = dict(path=str(image), sha256=hashlib.sha256(image.read_bytes()).hexdigest())
            save()
            assert not result['failures'], result
        report['passed'] = True
        save()
        return report
    except BaseException as error:
        report['error'] = repr(error)
        save()
        raise
    finally:
        cmd('tick freeze')
        ctl('release')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', required=True, type=Path)
    parser.add_argument('--validate', action='store_true')
    for name in ('game', 'resources', 'ctl', 'create-jar'):
        parser.add_argument('--' + name, type=Path)
    args = parser.parse_args()
    if args.validate:
        validate_reference(args.reference)
        print('Eight original Mixer UI reference cases validated; native GPU proof pending')
        return
    assert all((args.game, args.resources, args.ctl, args.create_jar))
    size = (1280, 720) if sys.platform == 'darwin' else (2560, 1440)
    with NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                            name='goggles-mixer-native', size=size) as session:
        print('scratch', session.scratch, flush=True)
        run(session.call, True, session.log, session.scratch, args.reference)


if __name__ == '__main__':
    main()
