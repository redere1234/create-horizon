"""Compare five original Basin tooltip scenarios with a rendered native client.

The reference is captured by basin_tooltip_reference.py in a disposable Java
instance. Text/style/layout comparisons use its actual provider output and
private language snapshots. PNG inspection remains a separate acceptance step;
an absent trace alone does not establish the absence of a rendered tooltip.
"""
import hashlib
import json
from pathlib import Path

from common import ROOT, PINS
from goggles_checks import compare_hud, component_spans, png_size, traces, wait_trace
from native_check_session import wait_loaded


REFERENCE = ROOT / '.local/basin-tooltip-java-smzb23pw/result.json'
POS = (454, 64, 18)


def validate_reference(path):
    path = Path(path).resolve()
    evidence = json.loads(path.read_text())
    assert evidence['passed'] and evidence['reference'] == PINS['create_revision']
    assert [c['name'] for c in evidence['cases']] == [
        'empty', 'items', 'mixed-en', 'mixed-ru', 'no-goggles']
    locales = {key: json.loads((path.parent / ('lang-' + key + '.json')).read_text())
               for key in ('en_us', 'ru_ru')}
    for case in evidence['cases']:
        image = Path(case['capture']['path'])
        assert hashlib.sha256(image.read_bytes()).hexdigest() == case['capture']['sha256']
        assert png_size(image) == [2560, 1440]
        assert case['state']['ready'] and case['state']['screen'] == 'playing'
        assert case['state']['gui_size'] == [640, 360]
        assert case['state']['hit']['block'] == 'create:basin'
        assert case['state']['hit']['pos'] == list(POS)
        for line in case['ui']['goggles']['lines']:
            resolved = component_spans(line['component'], locales[case['language']])
            assert ''.join(span['text'] for span in resolved) == line['text']
    return evidence, locales


def run(call, graphics, log, scratch, reference=REFERENCE):
    assert graphics, 'Basin HUD acceptance requires an actual rendered client'
    assert call('state')['world'] == 'CreateParity06'
    scratch = Path(scratch).resolve()
    scratch.relative_to((ROOT / '.local').resolve())
    evidence, locales = validate_reference(reference)
    report = {'passed': False, 'source': PINS['create_revision'],
              'reference': str(Path(reference).resolve()), 'cases': [],
              'scope': 'Actual rendered HUD text, font advances, styles and layout; '
                       'PNG inspection and pixel parity are separate checks'}
    output = scratch / 'basin-tooltip-native-result.json'
    transcript = scratch / 'basin-tooltip-native-transcript.jsonl'
    transcript.write_text('')

    def save():
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')

    def ctl(*words):
        reply = call(*words)
        with transcript.open('a') as stream:
            stream.write(json.dumps({'command': list(map(str, words)), 'reply': reply},
                                    ensure_ascii=False) + '\n')
        return reply

    def cmd(command):
        return ctl('command', command)

    save()
    try:
        x, y, z = POS
        xyz = ' '.join(map(str, POS))
        ctl('release')
        cmd('tick unfreeze')
        cmd('gamemode creative')
        cmd('gamerule minecraft:send_command_feedback false')
        cmd('gamerule minecraft:spawn_mobs false')
        cmd('gamerule minecraft:advance_time false')
        cmd('time set 6000')
        cmd('weather clear')
        cmd('tp @s 456.5 64 20.5')
        ctl('wait-ready', 120)
        wait_loaded(ctl, [(px, y, pz) for px in (450, 460) for pz in (14, 24)])
        cmd('fill 450 63 14 460 70 24 minecraft:air')
        cmd('fill 450 63 14 460 63 24 minecraft:smooth_stone')
        cmd('clear @s')
        for key, value in [('guiScale', 4), ('fov', 70), ('bobView', 'false'),
                           ('tutorialStep', 'none'), ('chatVisibility', 2)]:
            ctl('options-set', key, value)
        ctl('wait', 10)
        assert ctl('ui')['gui_size'] == [640, 360]
        # Neighbor updates from clearing the fixture can drop vegetation after
        # the first /clear. Retire those unrelated stacks before camera captures.
        ctl('wait', 20)
        cmd('kill @e[type=minecraft:item]')
        cmd('clear @s')
        ctl('wait', 5)
        language = None
        for source in evidence['cases']:
            case = {'name': source['name'], 'language': source['language'],
                    'java_image': source['capture']['path'],
                    'java_visually_inspected': source['visually_inspected'],
                    'native_visually_inspected': False, 'failures': []}
            report['cases'].append(case)
            try:
                ctl('look', 0, -80)
                ctl('wait', 3)
                if language != source['language']:
                    ctl('options-set', 'lang', source['language'])
                    ctl('wait-ready', 120)
                    language = source['language']
                cmd('setblock ' + xyz + ' minecraft:air')
                cmd('setblock ' + xyz + ' create:basin[facing=down]')
                if source['seed_nbt']:
                    cmd('data merge block ' + xyz + ' ' + source['seed_nbt'])
                cmd('item replace entity @s armor.head with ' +
                    ('create:goggles' if source['goggles'] else 'minecraft:air'))
                pose = source['state']
                cmd('tp @s ' + ' '.join(map(str, pose['position'])))
                ctl('wait', 8)
                after = Path(log).stat().st_size
                ctl('look', pose['yaw'], pose['pitch'])
                if source['ui']['goggles']['lines']:
                    actual = wait_trace(ctl, log, 'Create visual: ',
                                        lambda row: row.get('event') == 'goggles_hud'
                                        and row.get('pos') == list(POS), after)
                    case['native'] = actual
                    case['failures'] = compare_hud(source, actual, locales[language])
                else:
                    ctl('wait', 30)
                    rows = [row for row in traces(log, 'Create visual: ', after)
                            if row.get('event') == 'goggles_hud'
                            and row.get('pos') == list(POS)]
                    case['fresh_hud_traces'] = rows
                    assert not rows, rows
                    case['absence_scope'] = 'No emitted HUD trace; inspect the saved PNG too'
                ctl('wait', 30)  # Allow the source 24-frame hover transition to finish.
                case['native_image'] = str(scratch / ('basin-tooltip-' + source['name'] + '.png'))
                ctl('screenshot', case['native_image'])
                assert png_size(case['native_image']) == [2560, 1440]
                case['native_image_sha256'] = hashlib.sha256(
                    Path(case['native_image']).read_bytes()).hexdigest()
            except (AssertionError, RuntimeError) as error:
                case['error'] = repr(error)
            save()
        report['passed'] = all(not c.get('error') and not c['failures'] for c in report['cases'])
        save()
        assert report['passed'], str(output)
        return report
    except Exception as error:
        report['error'] = repr(error)
        save()
        raise
