#!/usr/bin/env python3
"""Twelve bounded Java/native burner frame comparisons in private test worlds.

Captures cover geometry, material selection, orientation and cosmetic parts.
Actual framebuffer PNGs require human review. Different AnimationTickHolder
clocks, per-object hashes, particles, lighting engines and independent rendering
make these captures unsuitable for exact animation-phase or full-frame pixel
parity claims. Canonical creative NBT holds presentation states; this is not a
fuel-admission test. No original image/model/texture is written outside .local.

Default --mode plan is read-only. Java capture requires the existing isolated
reference lease; native capture requires its own fresh NativeCheckSession/GPU
lease. The callback run() can also be used by a coordinated parent session.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from common import ROOT, PINS
from goggles_checks import png_size
from native_check_session import wait_loaded
import reference_java as java

POS = (510, 64, 16)
ABOVE = (510, 65, 16)
CAMERA = (513.2, 64, 19.2)
TARGET = (510.5, 64.55, 16.5)
WINDOW = (1280, 720)
FRAMEBUFFER = [2560, 1440]
FOV = 40
CASES = [
    dict(name='01-none-north', heat='none', facing='north'),
    dict(name='02-smouldering-north', heat='smouldering', facing='north'),
    dict(name='03-fading-active-north', heat='fading', facing='north', active=True),
    dict(name='04-kindled-active-north', heat='kindled', facing='north', active=True),
    dict(name='05-seething-active-north', heat='seething', facing='north', active=True),
    dict(name='06-kindled-active-east', heat='kindled', facing='east', active=True),
    dict(name='07-kindled-active-south', heat='kindled', facing='south', active=True),
    dict(name='08-kindled-active-west', heat='kindled', facing='west', active=True),
    dict(name='09-smouldering-small-goggles', heat='smouldering', facing='north', goggles=True),
    dict(name='10-seething-goggles-trainhat', heat='seething', facing='south', active=True,
         goggles=True, trainhat=True),
    dict(name='11-lit-regular', flame='regular'),
    dict(name='12-lit-soul', flame='soul'),
]


def xyz(pos):
    return ' '.join(map(str, pos))


def block_state(case):
    if 'flame' in case:
        return 'create:lit_blaze_burner[flame_type=' + case['flame'] + ']'
    return 'create:blaze_burner[blaze=' + case['heat'] + ',facing=' + case['facing'] + ']'


def seed(case):
    if 'flame' in case or case['heat'] == 'none':
        return None
    keys = ['isCreative:1b']
    if case.get('goggles'):
        keys.append('Goggles:1b')
    if case.get('trainhat'):
        keys.append('TrainHat:1b')
    return '{' + ','.join(keys) + '}'


def private(path):
    path = Path(path).resolve()
    path.relative_to((ROOT / '.local').resolve())
    return path


def image_record(path):
    path = private(path)
    assert png_size(path) == FRAMEBUFFER, (str(path), png_size(path))
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                framebuffer=FRAMEBUFFER, visually_inspected=False)


def capture_java(base=java.BASE, reference=None, replace_case=None):
    """Capture the fixed matrix through the existing original client bridge."""
    base = Path(base).resolve()
    assert base == java.BASE.resolve(), 'Only the owned disposable reference is authorized'
    manifest = json.loads((base / 'manifest.json').read_text())
    assert manifest['data_version'] == 3955 and manifest['create_sha256'] == java.CREATE_SHA256
    selected = CASES
    if replace_case:
        assert reference, 'A targeted recapture needs the previous private result'
        reference = private(reference)
        work = reference.parent
        report = json.loads(reference.read_text())
        assert report['passed'] and report['reference'] == PINS['create_revision']
        assert [row['spec']['name'] for row in report['cases']] == [case['name'] for case in CASES]
        selected = [case for case in CASES if case['name'] == replace_case]
        assert len(selected) == 1, replace_case
        for row, case in zip(report['cases'], CASES):
            assert image_record(row['capture']['path'])['sha256'] == row['capture']['sha256']
            assert case['name'] == replace_case or row['spec'] == case
        previous = reference.with_name('before-targeted-' + replace_case + '.json')
        assert not previous.exists(), 'Keep prior targeted recapture evidence; no repeat loops'
        shutil.copy2(reference, previous)
        old = next(row for row in report['cases'] if row['spec']['name'] == replace_case)
        shutil.copy2(old['capture']['path'], work / ('before-targeted-' + replace_case + '.png'))
        trace = json.loads((work / 'transcript.json').read_text())
        report['passed'] = False
    else:
        assert reference is None, '--reference for Java is used only with --replace-java-case'
        work = Path(tempfile.mkdtemp(prefix='burner-presentation-java-', dir=ROOT / '.local'))
        report = dict(passed=False, reference=PINS['create_revision'], source_jar_sha256=java.CREATE_SHA256,
                      scope=__doc__, cases=[], human_review='pending', window=WINDOW, fov=FOV)
        trace = []
    def save():
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        (work / 'transcript.json').write_text(json.dumps(trace, indent=2) + '\n')
    def call(method, body):
        reply = java.call(base, method, body)
        trace.append(dict(method=method, body=body, reply=reply))
        save()
        return reply
    def cmd(command):
        return call('command', {'command': command})
    initial = call('state', {})
    assert initial['ready'] and initial['screen'] == 'playing', initial
    print(json.dumps({'scratch': str(work), 'cases': len(selected)}), flush=True)
    try:
        call('tick', {'frozen': True})
        cmd('gamemode creative')
        cmd('forceload add 504 10 518 24')
        cmd('fill 504 64 10 518 70 24 minecraft:air')
        cmd('fill 504 63 10 518 63 24 minecraft:smooth_stone')
        cmd('time set 6000'); cmd('weather clear')
        cmd('clear @s')
        cmd('item replace entity @s weapon.offhand with minecraft:air')
        cmd('item replace entity @s armor.head with minecraft:air')
        call('camera', dict(position=CAMERA, target=TARGET, fov=FOV,
                            window_size=WINDOW, hide_gui=True))
        call('capture', {'name': 'burner-presentation-window-ready.png', 'frames': 20})
        assert call('state', {})['framebuffer_size'] == FRAMEBUFFER
        for case in selected:
            cmd('setblock ' + xyz(ABOVE) + ' minecraft:air')
            cmd('setblock ' + xyz(POS) + ' minecraft:air')
            cmd('setblock ' + xyz(POS) + ' ' + block_state(case))
            nbt = seed(case)
            if nbt:
                cmd('data merge block ' + xyz(POS) + ' ' + nbt)
            if case.get('active'):
                cmd('setblock ' + xyz(ABOVE) + ' create:basin[facing=down]')
            # Real normal ticks allow the source head-angle/head-height chasers
            # to settle. The independently timed bob/UV phase is not paired.
            observation = call('observe_ticks', {'ticks': 60, 'positions': [POS, ABOVE]})
            assert len(observation['samples']) == 60, observation
            cmd('kill @e[type=minecraft:item]'); cmd('clear @s')
            call('camera', dict(position=CAMERA, target=TARGET, fov=FOV, hide_gui=True))
            capture = call('capture', {'name': 'burner-presentation-' + case['name'] + '.png', 'frames': 30})
            state = capture['client']
            assert state['ready'] and state['screen'] == 'playing', state
            assert state['held'] == 'minecraft:air' and state['head'] == 'minecraft:air', state
            assert state['framebuffer_size'] == FRAMEBUFFER and state['fov'] == FOV, state
            assert all(abs(a-b) < .001 for a,b in zip(state['position'], CAMERA)), state
            block = call('block', {'pos': POS})
            if 'flame' in case:
                assert block['id'] == 'create:lit_blaze_burner', block
                assert block['properties']['flame_type'].lower() == case['flame'], block
            else:
                assert block['id'] == 'create:blaze_burner', block
                assert block['properties']['blaze'].lower() == case['heat'], block
                assert block['properties']['facing'].lower() == case['facing'], block
                if case['heat'] == 'none':
                    assert not block.get('nbt'), block
                else:
                    for key in ('Goggles', 'TrainHat'):
                        expected = case.get('goggles' if key == 'Goggles' else 'trainhat', False)
                        assert (key + ':' in block['nbt']) == expected, block
            path = work / (case['name'] + '.png')
            shutil.copy2(capture['path'], path)
            record = dict(spec=case, seed_nbt=nbt, block=block, camera=state,
                capture=image_record(path), normal_settle_ticks=60,
                animation_clock=call('particles', {'limit': 1}))
            if replace_case:
                index = next(i for i,row in enumerate(report['cases']) if row['spec']['name'] == replace_case)
                report['cases'][index] = record
            else:
                report['cases'].append(record)
            save()
        report['passed'] = True
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        call('input', {'key': 'use', 'down': False})
        call('tick', {'frozen': True})
        cmd('gamemode creative')
        cmd('item replace entity @s armor.head with ' + initial.get('head', 'minecraft:air'))
        call('camera', dict(position=initial['position'], yaw=initial['yaw'], pitch=initial['pitch'],
            fov=initial['fov'], gui_scale=initial['gui_scale'], hide_gui=False))
        save()
        print(json.dumps({'passed': report['passed'], 'result': str(work / 'result.json')}), flush=True)
    return report


def validate_reference(path):
    path = private(path)
    report = json.loads(path.read_text())
    assert report['passed'] and report['reference'] == PINS['create_revision']
    assert [row['spec'] for row in report['cases']] == CASES
    for row in report['cases']:
        image = image_record(row['capture']['path'])
        assert image['sha256'] == row['capture']['sha256'], row['capture']
    return report


def run(call, graphics, log, scratch, reference, only=None):
    """Native callback; caller owns a fresh private world and exclusive GPU lease."""
    assert graphics, 'An actual renderer is required'
    assert call('state')['world'] == 'CreateParity06'
    scratch = private(scratch)
    source = validate_reference(reference)
    selected = source['cases']
    if only is not None:
        assert only and len(only) == len(set(only))
        names = {row['spec']['name'] for row in selected}
        assert set(only) <= names, (only, names)
        selected = [row for row in selected if row['spec']['name'] in only]
    report = dict(passed=False, reference=str(Path(reference).resolve()),
                  source=PINS['create_revision'], scope=__doc__, cases=[], human_review='pending',
                  selected=[row['spec']['name'] for row in selected])
    output = scratch / 'burner-presentation-native-result.json'
    transcript = scratch / 'burner-presentation-native-transcript.jsonl'
    def save():
        output.write_text(json.dumps(report, indent=2) + '\n')
    def ctl(*words):
        reply = call(*words)
        with transcript.open('a') as stream:
            stream.write(json.dumps(dict(command=list(map(str, words)), reply=reply)) + '\n')
        return reply
    def cmd(command):
        return ctl('command', command)
    def game_time():
        import re
        values = re.findall(r'\b\d+\b', ' '.join(cmd('time query gametime')['chat']))
        assert len(values) == 1, values
        return int(values[0])
    hidden = False
    try:
        ctl('release'); cmd('tick unfreeze'); cmd('gamemode creative')
        cmd('tp @s ' + xyz(CAMERA)); ctl('wait-ready', 120)
        wait_loaded(ctl, [(504, 64, 10), (518, 64, 24)])
        cmd('forceload add 504 10 518 24')
        cmd('fill 504 64 10 518 70 24 minecraft:air')
        cmd('fill 504 63 10 518 63 24 minecraft:smooth_stone')
        cmd('gamerule minecraft:advance_time false'); cmd('time set 6000'); cmd('weather clear')
        cmd('clear @s'); cmd('item replace entity @s armor.head with minecraft:air')
        for key, value in [('fov', FOV), ('bobView', 'false'), ('chatVisibility', 2)]:
            ctl('options-set', key, value)
        ctl('key', 'f1', 'tap'); hidden = True
        for row in selected:
            case = row['spec']
            cmd('tick freeze')
            cmd('setblock ' + xyz(ABOVE) + ' minecraft:air')
            cmd('setblock ' + xyz(POS) + ' minecraft:air')
            cmd('setblock ' + xyz(POS) + ' ' + block_state(case))
            if row['seed_nbt']:
                cmd('data merge block ' + xyz(POS) + ' ' + row['seed_nbt'])
            if case.get('active'):
                cmd('setblock ' + xyz(ABOVE) + ' create:basin[facing=down]')
            pose = row['camera']
            cmd('tp @s ' + xyz(pose['position'])); ctl('wait', 8)
            state = ctl('state')
            assert state['player']['on_ground'], state
            assert all(abs(a-b) < .001 for a,b in zip(state['player']['position'], pose['position'])), state
            ctl('look', pose['yaw'], pose['pitch'])
            start = game_time(); cmd('tick unfreeze')
            for _ in range(160):
                ctl('wait', 2)
                if game_time() - start >= 60:
                    break
            else:
                raise AssertionError('The normal simulation did not advance60 ticks')
            cmd('tick freeze'); cmd('kill @e[type=minecraft:item]'); cmd('clear @s')
            ctl('wait', 30)
            state = ctl('state')
            assert state['held'] is None, state
            assert all(abs(a-b) < .001 for a,b in zip(state['player']['position'], pose['position'])), state
            assert abs(state['player']['yaw'] - pose['yaw']) < .001, state
            assert abs(state['player']['pitch'] - pose['pitch']) < .001, state
            actual = ctl('block', *POS)
            def properties(state):
                name, _, tail = state.partition('[')
                return name, dict(entry.split('=', 1) for entry in tail.rstrip(']').split(',') if entry)
            assert properties(actual['state']) == properties(block_state(case)), (actual, block_state(case))
            path = scratch / ('burner-presentation-' + case['name'] + '.png')
            ctl('screenshot', path)
            report['cases'].append(dict(spec=case, java_image=row['capture'],
                native_image=image_record(path), native_camera=state, native_block=actual,
                gui_hidden_by='normal F1 key on a fresh session',
                minimum_normal_settle_ticks=60, native_visually_inspected=False))
            save()
        report['passed'] = True
        save()
        return report
    except BaseException as error:
        report['error'] = repr(error); save(); raise
    finally:
        cmd('tick freeze')
        if hidden:
            ctl('key', 'f1', 'tap')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['plan', 'java', 'native'], default='plan')
    parser.add_argument('--reference', type=Path)
    parser.add_argument('--only', nargs='+', choices=[case['name'] for case in CASES],
        help='native-only bounded recapture; omitted retains the full twelve-case check')
    parser.add_argument('--replace-java-case', choices=[case['name'] for case in CASES],
        help='one targeted source recapture; preserves prior JSON/PNG and refuses another repeat')
    for name in ('game', 'resources', 'ctl', 'create-jar'):
        parser.add_argument('--' + name)
    args = parser.parse_args()
    if args.mode == 'plan':
        print(json.dumps(dict(cases=CASES, position=POS, camera=CAMERA, target=TARGET,
                              window=WINDOW, framebuffer=FRAMEBUFFER, fov=FOV), indent=2))
    elif args.mode == 'java':
        assert args.only is None, '--only is a native capture option'
        capture_java(reference=args.reference, replace_case=args.replace_java_case)
    else:
        if not all([args.reference, args.game, args.resources, args.ctl, args.create_jar]):
            parser.error('native requires --reference, --game, --resources, --ctl and --create-jar')
        from native_check_session import NativeCheckSession
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
            name='burner-presentation-native', graphics=True, username='CreateBurnView')
        (session.scratch / 'options.txt').write_text('tutorialStep:none\nchatVisibility:2\n')
        session.env.update(HORIZON_API_DISCOVERY='http://127.0.0.1:9/', HORIZON_NO_DISCORD='1')
        with session:
            run(session.call, True, session.log, session.scratch, args.reference, only=args.only)


if __name__ == '__main__':
    main()
