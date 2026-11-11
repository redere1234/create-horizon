"""Compare rendered native HUD state with privately captured original Create UI.

The reference contains eight visible goggles cases and one value board. Text,
font advances, inherited styles and layout are checked separately from PNGs;
state equality alone is not a claim of pixel parity. No Java client is mutated.
"""
import argparse
import json
from pathlib import Path
import re
import struct
import sys
import time

from common import ROOT

REFERENCE = ROOT / '.local/java-reference/verified-ui-reference.json'
COLORS = dict(zip(('black', 'dark_blue', 'dark_green', 'dark_aqua', 'dark_red',
                  'dark_purple', 'gold', 'gray', 'dark_gray', 'blue', 'green',
                  'aqua', 'red', 'light_purple', 'yellow', 'white'),
                 (0, 0xaa, 0xaa00, 0xaaaa, 0xaa0000, 0xaa00aa, 0xffaa00,
                  0xaaaaaa, 0x555555, 0x5555ff, 0x55ff55, 0x55ffff, 0xff5555,
                  0xff55ff, 0xffff55, 0xffffff)))


def component_spans(component, language):
    """Resolve translation/inheritance, comparing visible style rather than JSON shape."""
    result = []

    def text(value, style):
        if not value:
            return
        if result and result[-1]['style'] == style:
            result[-1]['text'] += value
        else:
            result.append({'text': value, 'style': dict(style)})

    def visit(node, inherited):
        if isinstance(node, str):
            text(node, inherited)
            return
        if isinstance(node, list):
            for child in node:
                visit(child, inherited)
            return
        style = dict(inherited)
        for key in ('color', 'bold', 'italic', 'underlined', 'strikethrough', 'obfuscated', 'font'):
            if key in node:
                style[key] = node[key]
        if isinstance(style['color'], str):
            color = style['color']
            style['color'] = int(color[1:], 16) if color.startswith('#') else COLORS[color]
        if 'text' in node:
            text(str(node['text']), style)
        elif 'translate' in node:
            key = node['translate']
            translated = language.get(key, node.get('fallback', key))
            arguments = node.get('with', [])
            last, index = 0, 0
            for match in re.finditer(r'%(?:(\d+)\$)?([s%])', translated):
                text(translated[last:match.start()], style)
                if match[2] == '%':
                    text('%', style)
                else:
                    selected = int(match[1]) - 1 if match[1] else index
                    visit(arguments[selected], style)
                    index += not bool(match[1])
                last = match.end()
            text(translated[last:], style)
        for child in node.get('extra', []):
            visit(child, style)

    visit(component, {'color': 0xffffff, 'bold': False, 'italic': False,
                      'underlined': False, 'strikethrough': False,
                      'obfuscated': False, 'font': 'minecraft:default'})
    return result


def languages():
    directory = ROOT / '.local/java-reference/text-resources/assets/create/lang'
    return {key: json.loads((directory / (key + '.json')).read_text()) for key in ('en_us', 'ru_ru')}


def validate_reference(path=REFERENCE):
    evidence = json.loads(Path(path).read_text())
    assert len(evidence['goggles']) == 8 and evidence['board'], 'Expected eight goggles and one board'
    locales = languages()
    for case in evidence['goggles']:
        assert case['visually_inspected'] and case['capture']['client']['ready'], case['capture']
        assert case['state']['gui_size'] == [640, 360]
        assert Path(case['capture']['path']).is_file(), case['capture']
        assert not any(box['alive'] and not box['passive'] for box in case['ui'].get('value_boxes', []))
        for line in case['ui']['goggles']['lines']:
            resolved = component_spans(line['component'], locales[case['language']])
            assert ''.join(span['text'] for span in resolved) == line['text'], line
    assert evidence['board']['visually_inspected'] and evidence['board']['ready_before_open']['ready']
    return evidence, locales


def traces(log, prefix, after=0):
    result = []
    with Path(log).open() as stream:
        stream.seek(after)
        for line in stream:
            if prefix in line:
                try:
                    result.append(json.loads(line.split(prefix, 1)[1]))
                except json.JSONDecodeError:
                    continue  # The writer may still be completing its final line.
    return result


def wait_trace(call, log, prefix, predicate, after=0, timeout=12):
    deadline = time.monotonic() + timeout
    while True:
        rows = traces(log, prefix, after)
        matching = [row for row in rows if predicate(row)]
        if matching:
            return matching[-1]
        if time.monotonic() >= deadline:
            raise AssertionError({'missing_trace': prefix, 'latest': rows[-3:]})
        call('wait', 2)


def compare_hud(expected, actual, locale):
    failures = []

    def same(name, left, right):
        if left != right:
            failures.append({'field': name, 'java': left, 'native': right})

    source = expected['ui']['goggles']
    same('text', [line['text'] for line in source['lines']], [line['text'] for line in actual['lines']])
    same('font_advances', [line['width'] for line in source['lines']], [line['width'] for line in actual['lines']])
    same('styled_spans', [component_spans(line['component'], locale) for line in source['lines']],
         [component_spans(line['component'], locale) for line in actual['lines']])
    same('anchor', source['source_tooltip_anchor'], actual['anchor'])
    x, y = source['source_tooltip_anchor']
    width, height = source['max_text_width'], source['tooltip_height']
    # All eight source fixtures fit without wrapping or clamping. This is the
    # original RemovedGuiUtils placement, not a native-derived expected value.
    assert x + width + 16 <= 640 and y - 12 + height + 4 <= 360
    same('tooltip_rectangle', [x + 12, y - 12, width, height], actual['tooltip'])
    return failures


def png_size(path):
    with Path(path).open('rb') as stream:
        header = stream.read(24)
    assert header[:8] == b'\x89PNG\r\n\x1a\n', path
    return list(struct.unpack('>II', header[16:24]))


def run(call, graphics, log, scratch, reference=REFERENCE):
    assert graphics, 'Goggles comparison needs a rendered client'
    evidence, locales = validate_reference(reference)
    scratch = Path(scratch)
    report = {'reference': str(reference), 'goggles': [], 'board': None,
              'scope': 'Eight actual native HUD/provider comparisons plus one board state; paired PNGs need separate visual assessment'}

    def save():
        (scratch / 'goggles-comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')

    call('release')
    call('command', 'gamemode creative')
    call('command', 'gamerule minecraft:send_command_feedback false')
    call('command', 'gamerule minecraft:advance_time false')
    call('command', 'gamerule minecraft:spawn_mobs false')
    call('command', 'gamerule minecraft:block_drops false')
    call('command', 'time set 6000')
    call('command', 'weather clear')
    call('fill', -4, 63, -4, 16, 63, 12, 'minecraft:smooth_stone')
    call('fill', -4, 64, -4, 16, 73, 12, 'minecraft:air')
    for x, state in enumerate(('create:creative_motor[facing=east]', 'create:shaft[axis=x]',
                              'create:speedometer[facing=south,axis_along_first=true]',
                              'create:stressometer[facing=south,axis_along_first=true]',
                              'create:mechanical_press[facing=east]')):
        call('setblock', x, 66, 0, state)
    call('command', 'data merge block 0 66 0 {ScrollValue:128}')
    call('setblock', 4, 64, 0, 'create:depot')
    call('command', 'kill @e[type=minecraft:item]')
    call('command', 'clear @s')
    call('command', 'item replace entity @s armor.head with create:goggles')
    call('options-set', 'guiScale', 4)
    call('options-set', 'fov', 70)
    call('options-set', 'bobView', 'false')
    call('options-set', 'tutorialStep', 'none')
    call('options-set', 'chatVisibility', 2)
    call('wait', 30)
    assert call('ui')['gui_size'] == [640, 360], 'Use a 2560x1440 framebuffer with GUI scale 4'

    current_language = None
    for case in evidence['goggles']:
        result = {'block': case['block'], 'language': case['language'], 'java_image': case['capture']['path']}
        report['goggles'].append(result)
        try:
            if current_language != case['language']:
                call('options-set', 'lang', case['language'])
                call('wait-ready', 120)
                current_language = case['language']
            call('look', 0, -80)  # No hit resets the source hover/trace cache.
            call('wait', 3)
            pose = case['capture']['client']
            call('command', 'tp @s ' + ' '.join(map(str, pose['position'])))
            after = Path(log).stat().st_size
            call('look', pose['yaw'], pose['pitch'])
            actual = wait_trace(call, log, 'Create visual: ',
                                lambda row: row.get('event') == 'goggles_hud' and row.get('pos') == case['ui']['hit']['pos'], after)
            result['native'] = actual
            result['failures'] = compare_hud(case, actual, locales[case['language']])
            result['native_image'] = str(scratch / ('native-' + Path(case['capture']['path']).name))
            call('screenshot', result['native_image'])
            assert png_size(result['native_image']) == [2560, 1440]
        except (AssertionError, RuntimeError) as error:
            result['error'] = f'{type(error).__name__}: {error}'
        save()

    # Ninth reference: the source board at the active central motor value box.
    source = evidence['board']
    board = {'java_image': source['capture']['path']}
    report['board'] = board
    try:
        call('options-set', 'lang', 'en_us')
        call('wait-ready', 120)
        pose = source['capture']['client']
        call('command', 'tp @s ' + ' '.join(map(str, pose['position'])))
        call('look', pose['yaw'], pose['pitch'])
        call('wait', 4)
        after = Path(log).stat().st_size
        call('mouse', 'right', 'down')
        call('wait', 12)
        assert call('screen')['screen'] == 'mod'
        expected = source['ui']['value_settings']
        call('click-at', *expected['hovered']['gui_coordinate'])
        actual = wait_trace(call, log, 'Create motor board: ',
                            lambda row: row.get('row') == expected['hovered']['row'] and row.get('value') == expected['hovered']['value'], after)
        board['native'] = actual
        board['failures'] = []
        for key, value in {'coordinate': expected['hovered']['gui_coordinate'],
                           'cursor': expected['hovered']['formatted']['text'],
                           'title': expected['title']['text'], 'title_width': expected['title']['width']}.items():
            if actual.get(key) != value:
                board['failures'].append({'field': key, 'java': value, 'native': actual.get(key)})
        board['native_image'] = str(scratch / 'native-verified-motor-value-settings-en_us.png')
        call('screenshot', board['native_image'])
        assert png_size(board['native_image']) == [2560, 1440]
    except (AssertionError, RuntimeError) as error:
        board['error'] = f'{type(error).__name__}: {error}'
    finally:
        call('key', 'escape', 'tap')
        call('release')
    report['passed'] = all(not case.get('failures') and not case.get('error') for case in [*report['goggles'], board])
    save()
    assert report['passed'], str(scratch / 'goggles-comparison.json')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validate', action='store_true')
    parser.add_argument('--reference', type=Path, default=REFERENCE)
    for key in ('game', 'resources', 'ctl', 'create-jar'):
        parser.add_argument('--' + key, type=Path)
    args = parser.parse_args()
    if args.validate:
        validate_reference(args.reference)
        print('Original reference validated: 8 visible goggles cases and 1 board; semantic component normalization matches all provider text')
        return
    assert all((args.game, args.resources, args.ctl, args.create_jar)), 'Specify game, resources, ctl and create-jar'
    from native_check_session import NativeCheckSession
    # NativeCheckSession takes logical window dimensions; Retina doubles both.
    size = (1280, 720) if sys.platform == 'darwin' else (2560, 1440)
    with NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                            name='goggles-source', size=size) as session:
        print('scratch', session.scratch, flush=True)
        run(session.call, True, session.log, session.scratch, args.reference)


if __name__ == '__main__':
    main()
