#!/usr/bin/env python3
"""Pinned source tooltip methods versus real native Game/providers/CPU widgets.

Original KineticBlockEntity and TooltipHelper method bodies remain unchanged.
Registry/config/translation contexts and LangBuilder recording are explicit test
scaffolding. JDK line boundaries use measured native font widths, so this proves
provider logic/styles/wrapping under those metrics, not original font pixels,
mouse/equipment interaction, a Java client, GPU frames or whole-screen parity.
All original language data and generated source stay in the private scratch.
"""
import argparse
import base64
import hashlib
import itertools
import json
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile

from common import CREATE, PINS, ROOT, environment
from goggles_checks import compare_hud, component_spans


def body(source, signature):
    start = source.index(signature)
    start = source.index('{', start)
    end, depth = start + 1, 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def main(args):
    stage, target = args.stage.resolve(), args.target.resolve()
    assert stage.is_relative_to(ROOT / '.local') and target.is_relative_to(ROOT / '.local')
    assert stage.parent.name.startswith(('ownmod-lint-', 'goggles-provider-'))
    assert (stage / '.horizon-mixins-stage.json').is_file()
    resources = args.resources.resolve()
    assert resources.is_relative_to(ROOT / '.local')
    work = Path(tempfile.mkdtemp(prefix='goggles-provider-', dir=ROOT / '.local'))
    report = {'passed': False, 'scope': __doc__, 'source': PINS['create_revision'],
              'source_sha256': {}, 'work': str(work), 'stage_restored': False}
    result_path = work / 'result.json'
    result_path.write_text(json.dumps(report, indent=2) + '\n')
    original_game = stage / 'crates/horizon-client/src/game.rs'
    before = original_game.read_bytes()
    source = ROOT / 'mixins/create/goggles.rs'
    report['native_sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = json.loads((ROOT / '.local/java-reference/manifest.json').read_text())
    java = str(Path(manifest['java']) / 'bin/java')
    javac = str(Path(manifest['java']) / 'bin/javac')
    classes = work / 'classes'
    classes.mkdir()
    subprocess.run([javac, '--release', '21', '-d', str(classes),
                    str(ROOT / 'tools/java/ExportMethod.java')], check=True)
    prefix = 'src/main/java/com/simibubi/create/'
    paths = {'kinetic': prefix + 'content/kinetics/base/KineticBlockEntity.java',
             'cut': prefix + 'foundation/item/TooltipHelper.java',
             'blocks': prefix + 'AllBlocks.java',
             'mixer': prefix + 'content/kinetics/mixer/MechanicalMixerBlock.java',
             'config': prefix + 'infrastructure/config/CKinetics.java'}
    originals = {}
    for name, path in paths.items():
        data = subprocess.check_output(['git', 'show', PINS['create_revision'] + ':' + path], cwd=CREATE)
        originals[name] = data.decode()
        report['source_sha256'][path] = hashlib.sha256(data).hexdigest()
        (work / (name + '.java')).write_bytes(data)
    mixer_registration = originals['blocks'].split('MECHANICAL_MIXER =', 1)[1].split('.register();', 1)[0]
    assert 'CStress.setImpact(4.0)' in mixer_registration
    assert 'return SpeedLevel.MEDIUM;' in originals['mixer']
    assert re.search(r'mediumSpeed\s*=\s*f\(30,', originals['config'])
    template = (ROOT / 'tools/java/KineticTooltipOracle.java.in').read_text()
    for marker, method in [('SPEED', 'getSpeed'), ('THEORETICAL', 'getTheoreticalSpeed'),
                           ('REQUIREMENT', 'isSpeedRequirementFulfilled'),
                           ('HOVER', 'addToTooltip'), ('GOGGLES', 'addToGoggleTooltip'),
                           ('STRESS', 'addStressImpactStats')]:
        extracted = subprocess.check_output([java, '-cp', str(classes), 'ExportMethod',
                                            str(work / 'kinetic.java'), method, 'KineticBlockEntity'], text=True)
        template = template.replace('@@' + marker + '@@', extracted)
    signature = 'public static List<Component> cutTextComponent(Component c, Style primaryStyle,\n\t\tStyle highlightStyle, int indent)'
    template = template.replace('@@CUT@@', body(originals['cut'], signature))
    generated = work / 'KineticTooltipOracle.java'
    generated.write_text(template)
    subprocess.run([javac, '--release', '21', '-d', str(classes), str(generated)], check=True)
    languages = {}
    language_lines = []
    with zipfile.ZipFile(args.create_jar) as jar:
        for locale in ['en_us', 'ru_ru']:
            data = jar.read('assets/create/lang/' + locale + '.json')
            languages[locale] = json.loads(data)
            path = work / 'languages/assets/create/lang' / (locale + '.json')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            for key, value in languages[locale].items():
                language_lines.append(locale + '\t' + key + '\t' + base64.b64encode(value.encode()).decode())
    language_file = work / 'languages.tsv'
    language_file.write_text('\n'.join(language_lines) + '\n')
    java_command = [java, '-cp', str(classes), 'KineticTooltipOracle']
    words = subprocess.check_output(java_command + ['words', str(language_file)], text=True).splitlines()
    requested = []
    for row in words:
        locale, encoded = row.split('\t')
        requested.append({'locale': locale, 'encoded': encoded,
                          'text': base64.b64decode(encoded).decode()})
    (work / 'words.json').write_text(json.dumps(requested))
    speeds = [0, .5, -.5, 1, -1, 16, -16, 29, -29, 29.999, 30, -30, 32, -32, 128,
              'NaN', 'Infinity', '-Infinity']
    cases = []
    protocol = []
    for locale, block, rpm, overload, frozen, goggles in itertools.product(
            languages, ['mechanical_mixer', 'mechanical_press'], speeds, [False, True],
            [False, True], [False, True]):
        case = dict(id=str(len(cases)), locale=locale, block=block, rpm=rpm,
                    overload=overload, frozen=frozen, goggles=goggles)
        cases.append(case)
        protocol.append('\t'.join(map(str, [case['id'], locale, block, rpm,
                                           int(overload), int(frozen), int(goggles)])))
    (work / 'cases.json').write_text(json.dumps(cases))
    (work / 'cases.tsv').write_text('\n'.join(protocol) + '\n')
    reference = ROOT / '.local/java-reference/verified-ui-reference.json'
    legacy = json.loads(reference.read_text())['goggles']
    assert len(legacy) == 8 and all(row['visually_inspected'] for row in legacy)
    (work / 'legacy.json').write_text(json.dumps(legacy))
    report['legacy_reference_sha256'] = hashlib.sha256(reference.read_bytes()).hexdigest()
    # Source-method branch check first, under an explicitly authored width6
    # context. Exact native comparisons below use actual loaded GUI metrics.
    synthetic = work / 'synthetic-widths.tsv'
    synthetic.write_text('\n'.join(row + '\t' + str(len(item['text']) * 6)
                                   for row, item in zip(words, requested)) + '\n')
    fixed = subprocess.check_output(java_command + ['cases', str(language_file), str(synthetic),
                                                   str(work / 'cases.tsv')], text=True)
    (work / 'source-fixed-context.jsonl').write_text(fixed)
    expected_fixed = [json.loads(row) for row in fixed.splitlines()]
    assert len(expected_fixed) == len(cases)
    for case, expected in zip(cases, expected_fixed):
        rpm = float(case['rpm'])
        minimum = 30 if case['block'] == 'mechanical_mixer' else 0
        warning = case['overload'] or (not case['frozen'] and rpm != 0 and not abs(rpm) >= minimum)
        assert bool(expected['rows']) == (case['goggles'] or warning)
        if case['goggles'] and not warning:
            assert len(expected['rows']) == 3
    report['source_context_cases'] = len(expected_fixed)
    fixture = ROOT / 'tools/rust/goggles_provider_test.rs'
    injection = '\n#[cfg(test)] mod source_provider_tests {\ninclude!(' + json.dumps(str(fixture)) + ');\n}\n'
    game_text = before.decode()
    start = game_text.index('pub(crate) mod create_port_goggles {')
    original_body = body(game_text, 'pub(crate) mod create_port_goggles {')
    end = game_text.index('{', start) + len(original_body)
    replacement = 'pub(crate) mod create_port_goggles {\n' + source.read_text() + injection + '\n}'
    env = environment()
    env.update({'CARGO_TARGET_DIR': str(target), 'CARGO_BUILD_JOBS': '2',
                'HORIZON_TEST_RESOURCES': str(resources), 'CREATE_GOGGLES_PROBE': str(work),
                'HORIZON_NO_AUDIO': '1', 'HORIZON_API_DISCOVERY': 'http://127.0.0.1:9',
                'RUST_MIN_STACK': str(16 * 1024 * 1024)})
    for key in ['HORIZON_HOME', 'HORIZON_LAUNCHER_HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME']:
        path = work / key
        path.mkdir()
        env[key] = str(path)
    print(json.dumps({'work': str(work), 'source_context_cases': len(cases)}), flush=True)
    try:
        original_game.write_text(game_text[:start] + replacement + game_text[end:])
        with (work / 'cargo.log').open('w') as log:
            process = subprocess.run(['cargo', 'test', '--locked', '--offline', '-p', 'horizon-client',
                '--lib', 'kinetic_goggles_actual_game_source_inputs', '--', '--ignored', '--nocapture'],
                cwd=stage, env=env, stdout=log, stderr=subprocess.STDOUT)
        report['native_exit'] = process.returncode
        assert process.returncode == 0, str(work / 'cargo.log')
    finally:
        original_game.write_bytes(before)
        report['stage_restored'] = original_game.read_bytes() == before
        result_path.write_text(json.dumps(report, indent=2) + '\n')
    widths = json.loads((work / 'widths.json').read_text())
    metrics = work / 'native-widths.tsv'
    metrics.write_text('\n'.join(row['locale'] + '\t' + row['encoded'] + '\t' + str(row['width'])
                                 for row in widths) + '\n')
    expected = subprocess.check_output(java_command + ['cases', str(language_file), str(metrics),
                                                       str(work / 'cases.tsv')], text=True)
    (work / 'source-native-metrics.jsonl').write_text(expected)
    source_rows = {row['id']: row['rows'] for row in map(json.loads, expected.splitlines())}
    native = json.loads((work / 'native.json').read_text())
    assert len(native) == len(cases)
    for case, actual in zip(cases, native):
        assert actual['id'] == case['id']
        visible = []
        for row in actual['lines']:
            spans = component_spans(row['component'], languages[case['locale']])
            assert ''.join(span['text'] for span in spans) == row['text']
            for span in spans:
                assert span['style'] == dict(color=span['style']['color'], bold=False, italic=False,
                    underlined=False, strikethrough=False, obfuscated=False, font='minecraft:default')
            visible.append([dict(text=s['text'], color=s['style']['color']) for s in spans])
        assert visible == source_rows[case['id']], {'case': case, 'source': source_rows[case['id']], 'native': visible}
    actual_legacy = json.loads((work / 'native-legacy.json').read_text())
    assert len(actual_legacy) == 8
    for previous, actual in zip(legacy, actual_legacy):
        assert not compare_hud(previous, actual, languages[previous['language']]), (previous['block'], actual)
    report.update({'passed': True, 'actual_game_cases': len(native),
                   'accepted_legacy_provider_cases': len(actual_legacy),
                   'fixture_sha256': hashlib.sha256(fixture.read_bytes()).hexdigest(),
                   'paired_client_pending': True})
    result_path.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': True, 'cases': len(native), 'result': str(result_path)}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['stage', 'target', 'resources', 'create-jar']:
        parser.add_argument('--' + name, type=Path, required=True)
    main(parser.parse_args())
