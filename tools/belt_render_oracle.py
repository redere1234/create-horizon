#!/usr/bin/env python3
"""Compare the pinned Create BeltVisual and scrolling shader with native draw().

Execute the original BeltVisual setup, the fallback BeltRenderer, and the
original motor isSideActive predicate. Record surface selection, poses and UV
phase with a separate render clock. The game mesh check consumes this output.
Original assets stay private.
"""
import argparse
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import subprocess
import zipfile

from burner_material_checks import function
from common import CREATE, PINS, ROOT
from fan_entity_checks import EXPORTER

BELT_SOURCE = 'src/main/java/com/simibubi/create/content/kinetics/belt/BeltRenderer.java'
VISUAL_SOURCE = 'src/main/java/com/simibubi/create/content/kinetics/belt/BeltVisual.java'
SCROLL_SHADER = 'src/main/resources/assets/create/flywheel/instance/scrolling.vert'
MOTOR_SOURCE = 'src/main/java/com/simibubi/create/content/kinetics/motor/CreativeMotorBlockEntity.java'
DIRECTIONS = ['north', 'south', 'west', 'east']
SLOPES = ['horizontal', 'upward', 'downward', 'vertical', 'sideways']
PARTS = ['start', 'middle', 'end', 'pulley']


def original(path):
    return subprocess.check_output(
        ['git', 'show', PINS['create_revision'] + ':' + path], cwd=CREATE,
    )


def export_body(java, classes, source, owner, method):
    return subprocess.check_output(
        [str(java / 'java'), '-cp', str(classes), 'ExportEntityMethod',
         str(source), owner, method],
        text=True,
    )


def parse_frames(text):
    cases = []
    current = []
    for line in text.splitlines():
        if line == ';':
            cases.append(current)
            current = []
            continue
        values = line.split()
        assert len(values) == 19, values
        current.append({
            'model': values[0],
            'shifted': values[1] == '1',
            'scroll': float(values[2]),
            'matrix': list(map(float, values[3:])),
        })
    assert not current, 'The recorder omitted its final case delimiter'
    return cases


def compare_case(case, want, got):
    assert len(want) == len(got), (case, want, got)
    maximum = 0.0
    for left, right in zip(want, got):
        for key in ['model', 'shifted']:
            assert left[key] == right[key], (case, key, left, right)
        pairs = [(left['scroll'], right['scroll'], 2e-6)]
        pairs.extend((a, b, 1e-5) for a, b in zip(left['matrix'], right['matrix']))
        for a, b, bound in pairs:
            maximum = max(maximum, abs(a - b))
            assert math.isclose(a, b, abs_tol=bound, rel_tol=3e-7), (case, a, b)
    return maximum


def compile_rust(source, path):
    path.with_suffix('.rs').write_text(source)
    subprocess.run(
        [str(ROOT / '.tools/rust/bin/rustc'), '--edition=2024', '-Dwarnings',
         str(path.with_suffix('.rs')), '-o', str(path)],
        check=True,
    )


def private_face_counts():
    """Record source metadata counts, never copy original asset geometry."""
    jar = ROOT / '.local/input-instance/mods/create-1.21.1-6.0.10.jar'
    names = ['middle', 'middle_bottom', 'diagonal_middle']
    with zipfile.ZipFile(jar) as archive:
        return {
            name: sum(len(element.get('faces', {}))
                      for element in json.loads(archive.read(
                          'assets/create/models/block/belt/' + name + '.json',
                      )).get('elements', []))
            for name in names
        }


def run(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'result.json').write_text(json.dumps({'passed': False, 'status': 'running'}) + '\n')
    manifest = json.loads((ROOT / '.local/java-reference/manifest.json').read_text())
    java = Path(manifest['java']) / 'bin'
    classpath = os.pathsep.join(manifest['classpath'] + manifest['compile_deps'])
    classes = output / 'classes'
    classes.mkdir(exist_ok=True)
    exporter = output / 'ExportEntityMethod.java'
    exporter.write_text(EXPORTER)
    subprocess.run(
        [str(java / 'javac'), '--release', '21', '-d', str(classes), str(exporter)],
        check=True,
    )
    belt_source = original(BELT_SOURCE)
    visual_source = original(VISUAL_SOURCE)
    scroll_shader = original(SCROLL_SHADER)
    assert b'fract(instance.speed * flw_renderTicks + instance.offset) * instance.scale' in scroll_shader
    motor_source = original(MOTOR_SOURCE)
    belt_path = output / 'BeltRenderer.java'
    visual_path = output / 'BeltVisual.java'
    motor_path = output / 'CreativeMotorBlockEntity.java'
    belt_path.write_bytes(belt_source)
    visual_path.write_bytes(visual_source)
    motor_path.write_bytes(motor_source)
    template = (ROOT / 'tools/java/BeltRenderOracle.java.in').read_text()
    constants = [line.strip() for line in visual_source.decode().splitlines()
                 if line.strip().startswith('public static final float ')]
    assert len(constants) == 5
    template = template.replace('@@VISUAL_CONSTANTS@@', '\n  '.join(constants))
    for marker, path, owner, method in [
        ('RENDER', belt_path, 'BeltRenderer', 'renderSafe'),
        ('PARTIAL', belt_path, 'BeltRenderer', 'getBeltPartial'),
        ('VISUAL_SETUP', visual_path, 'BeltVisual', 'setup'),
        ('MOTOR_SIDE', motor_path, 'MotorValueBox', 'isSideActive'),
    ]:
        template = template.replace(
            '@@' + marker + '@@', export_body(java, classes, path, owner, method),
        )
    generated = output / 'BeltRenderOracle.java'
    generated.write_text(template)
    subprocess.run(
        [str(java / 'javac'), '--release', '21', '-proc:none', '-cp', classpath,
         '-d', str(classes), str(generated)],
        check=True,
    )
    adapter = (ROOT / 'mixins/create/belt.rs').read_text()
    motor = (ROOT / 'mixins/create/motor_value_world.rs').read_text()
    motor_context = '\n'.join([
        '#[derive(Clone, Copy)] struct Side([i32; 3]);',
        'impl Side {' + function(motor, 'fn axis(') + '}',
        'struct MotorPlan {motor_facing: Option<Side>, side: Side}',
        'impl MotorPlan {' + function(motor, 'fn side_active(') + '}',
    ])
    rust = (ROOT / 'tools/rust/belt_render_probe.rs.in').read_text()
    rust = rust.replace('@@YAW@@', function(adapter, 'fn render_yaw('))
    rust = rust.replace('@@DRAW@@', function(adapter, 'pub(super) fn draw('))
    rust = rust.replace('@@MOTOR@@', motor_context)
    probe = output / 'probe'
    compile_rust(rust, probe)
    cases = [
        [*row, clock, partial]
        for row in itertools.product(range(4), range(5), range(4), [-256, -32, 0, 32, 256])
        for clock, partial in [(0, 0), (10, .125), (10000, .875), (120000, .25)]
    ]
    payload = ''.join(' '.join(map(str, row)) + '\n' for row in cases)
    (output / 'cases.txt').write_text(payload)
    java_command = [str(java / 'java'), '-cp', str(classes) + os.pathsep + classpath,
                    'BeltRenderOracle']
    want_text = subprocess.check_output(java_command, input=payload, text=True)
    got_text = subprocess.check_output([str(probe)], input=payload, text=True)
    (output / 'java.txt').write_text(want_text)
    (output / 'rust.txt').write_text(got_text)
    want = parse_frames(want_text)
    got = parse_frames(got_text)
    assert len(want) == len(got) == len(cases)
    maximum = max(compare_case(case, a, b) for case, a, b in zip(cases, want, got))

    fallback = parse_frames(subprocess.check_output(
        java_command + ['fallback'], input=payload, text=True,
    ))
    assert len(fallback) == len(want)
    stopped_cases = 0
    for case, visual, old in zip(cases, want, fallback):
        if case[3] != 0:
            continue
        assert all(frame['shifted'] for frame in visual), (case, visual)
        assert all(not frame['shifted'] for frame in old), (case, old)
        expected = [0.1875] if case[1] in (1, 2) else [0.25, 0.0]
        assert [frame['scroll'] for frame in visual] == expected, (case, visual)
        stopped_cases += 1

    # Using the old fallback yaw with the new instance rotations must fail.
    wrong_yaw = rust.replace('Direction::West => 90.0', 'Direction::West => -90.0')
    wrong_yaw = wrong_yaw.replace('Direction::East => 270.0', 'Direction::East => -270.0')
    assert wrong_yaw != rust
    negative_probe = output / 'old-yaw-probe'
    compile_rust(wrong_yaw, negative_probe)
    rejected = 0
    negative = parse_frames(subprocess.check_output(
        [str(negative_probe)], input=payload, text=True,
    ))
    for case, a, b in zip(cases, want, negative):
        try:
            compare_case(case, a, b)
        except AssertionError:
            rejected += 1
    assert rejected == 800, rejected

    motor_want = subprocess.check_output(java_command + ['motor'], text=True).splitlines()
    motor_got = subprocess.check_output([str(probe), 'motor'], text=True).splitlines()
    assert len(motor_want) == len(motor_got) == 36
    assert motor_want == motor_got, (motor_want, motor_got)
    (output / 'motor-sides.txt').write_text('\n'.join(motor_want) + '\n')
    rows = [{
        'facing': DIRECTIONS[case[0]], 'slope': SLOPES[case[1]], 'part': PARTS[case[2]],
        'rpm': case[3], 'clock': case[4], 'partial': case[5], 'frames': frames,
    } for case, frames in zip(cases, want)]
    (output / 'source-frames.json').write_text(json.dumps({
        'rows': rows, 'face_counts': private_face_counts(),
    }, indent=2) + '\n')
    result = {
        'passed': True, 'cases': len(cases),
        'surface_frames': sum(map(len, got)), 'maximum_absolute_difference': maximum,
        'old_yaw_rejected_cases': rejected, 'motor_side_cases': len(motor_got),
        'stopped_cases_with_flywheel_scroll': stopped_cases,
        'create_revision': PINS['create_revision'],
        'visual_sha256': hashlib.sha256(visual_source).hexdigest(),
        'fallback_sha256': hashlib.sha256(belt_source).hexdigest(),
        'shader_sha256': hashlib.sha256(scroll_shader).hexdigest(),
        'adapter_sha256': hashlib.sha256(adapter.encode()).hexdigest(), 'scope': __doc__,
    }
    (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / '.local/belt-render-oracle')
    run(parser.parse_args().output)
