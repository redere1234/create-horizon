#!/usr/bin/env python3
"""Observe original burner cases09/10 in the already-running private bridge.

MIT Create method counters and public baked model/material metadata separate
actual executed paths from registration policy. No backend is changed, no
Flywheel implementation is read, and this tool never launches a client.
Original PNGs/model-derived output stay under .local and need human review.
"""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import time

from common import ROOT, PINS
from burner_presentation_checks import CASES, POS, ABOVE, CAMERA, TARGET, WINDOW, FRAMEBUFFER, FOV, xyz, block_state, seed
import reference_java as java


def main():
    work = Path(tempfile.mkdtemp(prefix='burner-backend-java-', dir=ROOT / '.local'))
    report = dict(passed=False, source=PINS['create_revision'], cases=[], scope=__doc__)
    transcript = []

    def save():
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        (work / 'transcript.json').write_text(json.dumps(transcript, indent=2) + '\n')

    def call(method, body):
        reply = java.call(java.BASE, method, body)
        transcript.append(dict(method=method, body=body, reply=reply))
        save()
        return reply

    def cmd(text):
        return call('command', dict(command=text))

    print(json.dumps(dict(work=str(work))), flush=True)
    # Wait only for this one authorized startup. A failed process/display is a
    # setup failure, never a reason for this tool to launch another instance.
    deadline = time.monotonic() + 120
    while True:
        initial = call('state', {})
        if initial['ready'] and initial['screen'] == 'playing':
            break
        assert java.process_alive(java.BASE), 'Reference process stopped during startup'
        assert time.monotonic() < deadline, initial
        time.sleep(.5)
    try:
        call('tick', dict(frozen=True))
        cmd('gamemode creative')
        cmd('forceload add 504 10 518 24')
        cmd('fill 504 64 10 518 70 24 minecraft:air')
        cmd('fill 504 63 10 518 63 24 minecraft:smooth_stone')
        cmd('time set 6000')
        cmd('weather clear')
        cmd('clear @s')
        cmd('item replace entity @s weapon.offhand with minecraft:air')
        cmd('item replace entity @s armor.head with minecraft:air')
        call('camera', dict(position=CAMERA, target=TARGET, fov=FOV,
                            window_size=WINDOW, gui_scale=4, hide_gui=True))
        call('capture', dict(name='burner-backend-window-ready.png', frames=20))
        assert call('state', {})['framebuffer_size'] == FRAMEBUFFER
        for case in CASES[8:10]:
            cmd('setblock ' + xyz(ABOVE) + ' minecraft:air')
            cmd('setblock ' + xyz(POS) + ' minecraft:air')
            cmd('setblock ' + xyz(POS) + ' ' + block_state(case))
            cmd('data merge block ' + xyz(POS) + ' ' + seed(case))
            if case.get('active'):
                cmd('setblock ' + xyz(ABOVE) + ' create:basin[facing=down]')
            observation = call('observe_ticks', dict(ticks=60, positions=[POS, ABOVE]))
            assert len(observation['samples']) == 60
            call('camera', dict(position=CAMERA, target=TARGET, fov=FOV, hide_gui=True))
            before = call('state', {})
            capture = call('capture', dict(name='burner-backend-' + case['name'] + '.png', frames=80))
            state = capture['client']
            assert state['ready'] and state['screen'] == 'playing', state
            assert state['framebuffer_size'] == FRAMEBUFFER
            observed = state['burner_render_observation']
            assert observed.get('observed') and (observed['renderer_calls'] or observed['visual_frames']), observed
            image = work / (case['name'] + '.png')
            shutil.copy2(capture['path'], image)
            report['cases'].append(dict(spec=case, block=call('block', dict(pos=POS)),
                before=before, state=state, capture=dict(path=str(image),
                sha256=hashlib.sha256(image.read_bytes()).hexdigest()), visually_inspected=False))
            save()
        report['models'] = call('burner_models', {})
        assert len(report['models']['parts']) == 14
        report['passed'] = True
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        call('tick', dict(frozen=True))
        cmd('item replace entity @s armor.head with create:goggles')
        call('camera', dict(position=initial['position'], yaw=initial['yaw'], pitch=initial['pitch'],
                            fov=70, gui_scale=4, hide_gui=False))
        save()
        print(json.dumps(dict(passed=report['passed'], result=str(work / 'result.json'))), flush=True)


if __name__ == '__main__':
    main()
