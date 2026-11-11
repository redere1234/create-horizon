#!/usr/bin/env python3
"""Capture eight bounded original Mixer HUD cases in the private reference.

All cases use a real motor/cog/Mixer network. Overstress precedence is covered
by the separate source-method/CPU Game oracle; it is not a live case here.
PNGs require separate human review.
No Java process is launched or stopped by this tool.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from common import ROOT, PINS
import reference_java as java
from basin_tooltip_reference import languages

MIXER = [486, 66, 18]
MOTOR = [485, 65, 18]
CAMERA = [488.5, 64, 21.5]
TARGET = [486.5, 66.45, 18.5]
WINDOW = [1280, 720]
CASES = [
    dict(name='mixer-32-en', rpm=32, goggles=True, language='en_us', frozen=False),
    dict(name='mixer-16-en', rpm=16, goggles=True, language='en_us', frozen=False),
    dict(name='mixer-16-no-goggles', rpm=16, goggles=False, language='en_us', frozen=False),
    dict(name='mixer-minus16-ru', rpm=-16, goggles=True, language='ru_ru', frozen=False),
    dict(name='mixer-30-en', rpm=30, goggles=True, language='en_us', frozen=False),
    dict(name='mixer-stopped', rpm=0, goggles=False, language='en_us', frozen=False),
    dict(name='mixer-frozen16', rpm=16, goggles=False, language='en_us', frozen=True),
    dict(name='mixer-minus30-no-goggles', rpm=-30, goggles=False, language='en_us', frozen=False),
]


def xyz(pos):
    return ' '.join(map(str, pos))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume', type=Path, help='one diagnosed fixture continuation; retains previous evidence')
    args = parser.parse_args()
    if args.resume:
        work = args.resume.resolve().parent
        work.relative_to((ROOT / '.local').resolve())
        report = json.loads(args.resume.read_text())
        assert not report['passed'] and report['reference'] == PINS['create_revision']
        assert [row['spec'] for row in report['cases']] == CASES[:len(report['cases'])]
        prior = work / ('before-resume-' + str(len(report['cases'])) + '.json')
        assert not prior.exists(), 'Refuse repeating the same continuation without a diagnosis'
        shutil.copy2(args.resume, prior)
        trace = json.loads((work / 'transcript.json').read_text())
        report.setdefault('diagnostics', []).append(dict(previous_result=str(prior), error=report.pop('error', None)))
        report['scope'] = __doc__
    else:
        work = Path(tempfile.mkdtemp(prefix='goggles-mixer-java-', dir=ROOT / '.local'))
        report = dict(passed=False, reference=PINS['create_revision'], cases=[],
                      source_jar_sha256=java.CREATE_SHA256, scope=__doc__, human_review='pending')
        trace = []

    def save():
        (work / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        (work / 'transcript.json').write_text(json.dumps(trace, ensure_ascii=False, indent=2) + '\n')

    def call(method, body):
        reply = java.call(java.BASE, method, body)
        trace.append(dict(method=method, body=body, reply=reply))
        save()
        return reply

    def cmd(command):
        return call('command', dict(command=command))

    def ready(language):
        call('language', dict(language=language))
        for _ in range(20):
            state = call('state', {})
            if state['ready'] and state['language'] == language:
                return
            call('capture', dict(name='goggles-mixer-resource-loading.png', frames=20))
        raise AssertionError('Resource reload did not settle')

    def power(rpm):
        call('tick', dict(frozen=False))
        # Removing the source is the ordinary stopped case; setting ScrollValue
        # on an actual generator exercises network propagation for every RPM.
        cmd('setblock ' + xyz(MOTOR) + ' minecraft:air')
        if rpm != 0:
            # /data load of an existing motor does not invoke the scroll-value
            # callback. A fresh generator's ordinary initialize() does; do not
            # pretend that loading ScrollValue alone turns an existing one.
            cmd('setblock ' + xyz(MOTOR) + ' create:creative_motor[facing=up]{ScrollValue:' + str(-rpm) + '}')
        call('capture', dict(name='goggles-mixer-power-settle.png', frames=80))
        block = call('block', dict(pos=MIXER))
        # Inspect authoritative canonical data independently of provider output.
        import re
        found = re.search(r'(?:^|[,\s{])Speed:([-+0-9.Ee]+)f', block['nbt'])
        assert found and float(found[1]) == rpm, block
        return block

    initial = call('state', {})
    assert initial['ready'] and initial['screen'] == 'playing', initial
    print(json.dumps(dict(scratch=str(work), cases=len(CASES))), flush=True)
    try:
        for language, values in languages(java.BASE).items():
            (work / ('lang-' + language + '.json')).write_text(json.dumps(values, ensure_ascii=False) + '\n')
        call('tick', dict(frozen=False))
        cmd('gamemode creative')
        cmd('gamerule doDaylightCycle false')
        cmd('gamerule doWeatherCycle false')
        cmd('time set 6000')
        cmd('weather clear')
        cmd('forceload add 480 12 492 26')
        cmd('fill 480 64 12 492 72 26 minecraft:air')
        cmd('fill 480 63 12 492 63 26 minecraft:smooth_stone')
        cmd('clear @s')
        cmd('item replace entity @s weapon.offhand with minecraft:air')
        cmd('setblock 485 66 18 create:cogwheel[axis=y]')
        cmd('setblock ' + xyz(MIXER) + ' create:mechanical_mixer')
        call('camera', dict(position=CAMERA, target=TARGET, window_size=WINDOW,
                            gui_scale=4, fov=70, hide_gui=False))
        call('capture', dict(name='goggles-mixer-window-ready.png', frames=30))
        assert call('state', {})['framebuffer_size'] == [2560, 1440]
        for case in CASES[len(report['cases']):]:
            before_freeze = power(case['rpm'])
            ready(case['language'])
            cmd('item replace entity @s armor.head with ' +
                ('create:goggles' if case['goggles'] else 'minecraft:air'))
            if case['frozen']:
                call('tick', dict(frozen=True))
            call('camera', dict(position=CAMERA, target=TARGET, hide_gui=False))
            capture = call('capture', dict(name='goggles-' + case['name'] + '.png', frames=80))
            state = capture['client']
            ui = call('ui', {})
            block = call('block', dict(pos=MIXER))
            assert state['ready'] and state['screen'] == 'playing', state
            assert state['hit'].get('pos') == MIXER, state
            assert state['held'] == 'minecraft:air', state
            assert state['gui_size'] == [640, 360] and state['framebuffer_size'] == [2560, 1440], state
            assert ui['goggles']['wearing'] == case['goggles'], ui
            lines = [line['text'] for line in ui['goggles']['lines']]
            if case['rpm'] == 0 or case['frozen'] or (not case['goggles'] and abs(case['rpm']) >= 30):
                assert not lines, lines
            elif case['language'] == 'en_us':
                assert any('Speed Requirement:' in line for line in lines) == (0 < abs(case['rpm']) < 30), lines
            path = work / (case['name'] + '.png')
            shutil.copy2(capture['path'], path)
            capture.update(original_path=capture['path'], path=str(path),
                           sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            report['cases'].append(dict(spec=case, state=state, ui=ui, block=block,
                                        powered_before_freeze=before_freeze, capture=capture,
                                        visually_inspected=False))
            save()
        # Read-only observation of the actual registered burner rendering path.
        # Public Flywheel exposes aggregate visual counts, not per-BE lookup.
        call('tick', dict(frozen=True))
        cmd('setblock 488 64 22 create:blaze_burner[blaze=kindled,facing=south]')
        cmd('data merge block 488 64 22 {Goggles:1b,FuelLevel:1,RemainingBurnTime:1777}')
        cmd('item replace entity @s armor.head with minecraft:air')
        call('camera', dict(position=[488.5, 64, 25.5], target=[488.5, 64.5, 22.5], hide_gui=True))
        capture = call('capture', dict(name='goggles-burner-backend-observation.png', frames=60))
        state = capture['client']
        assert state['hit'].get('block') == 'create:blaze_burner', state
        assert state['render_backend']['hit_block_entity'] == 'create:blaze_heater', state
        path = work / 'burner-backend.png'
        shutil.copy2(capture['path'], path)
        report['burner_backend'] = dict(state=state, block=call('block', dict(pos=[488, 64, 22])),
            capture=dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest()),
            scope='Actual public backend/registration/skip policy, not individual visual-instance introspection')
        report['passed'] = True
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        call('tick', dict(frozen=True))
        ready('en_us')
        cmd('item replace entity @s armor.head with create:goggles')
        call('camera', dict(position=initial['position'], yaw=initial['yaw'], pitch=initial['pitch'],
                            gui_scale=4, fov=70, hide_gui=False))
        save()
        print(json.dumps(dict(passed=report['passed'], result=str(work / 'result.json'))), flush=True)


if __name__ == '__main__':
    main()
