#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare native Chute outline and collision with the pinned Java geometry."""

import itertools
import json
from pathlib import Path
import subprocess
import tempfile

from basin_shape_oracle import JAVA, expression, source
from common import PINS, ROOT
from reference_java import BASE, CREATE_SHA256, digest


def occupied(boxes):
    cells = set()
    for box in boxes:
        bounds = [round(value * 16) for value in box]
        assert all(abs(bound - value * 16) < 1e-8
                   for bound, value in zip(bounds, box, strict=True)), box
        cells.update(itertools.product(*(range(bounds[i], bounds[i+3]) for i in range(3))))
    return cells


def main():
    revision = PINS['create_revision']
    source_dir = 'com/simibubi/create/'
    shapes = source(revision, source_dir + 'AllShapes.java')
    assert 'CHUTE_SLOPE = shape(ChuteShapes.createSlope()).forHorizontal(SOUTH)' in shapes
    state_key = 'data/create/horizon/block/chute.json'
    declaration = json.loads((ROOT / 'content' / state_key).read_text())
    bundle = json.loads((ROOT / 'mixins/create/data/content.json').read_text())
    assert json.loads(bundle[state_key]) == declaration
    outline = declaration['shapes']['values']
    collision = declaration['collision_shapes']['values']
    assert outline.keys() == collision.keys()

    commands = ['var vertical = ' + expression(shapes, 'CHUTE')['java'] + ';',
                'var slope = new AllShapes.Builder(ChuteShapes.createSlope()).forHorizontal(Direction.SOUTH);']
    for index, key in enumerate(outline):
        face, shape = key.split(',')
        boxed = shape in ('intersection', 'encased')
        if face == 'down':
            value = 'Shapes.block()' if boxed else 'vertical'
        else:
            value = f'slope.get(Direction.{face.upper()})'
            if boxed:
                value = ('Shapes.joinUnoptimized(ChuteShapes.INTERSECTION_MASK, '
                         f'Shapes.or(Shapes.block(), {value}), BooleanOp.AND)')
        if index:
            commands.append('System.out.print(",");')
        commands += [f'var outline{index} = {value};',
                     f'emit("outline:{key}", outline{index});',
                     'System.out.print(",");',
                     f'emit("collision:{key}", Shapes.joinUnoptimized(ChuteShapes.COLLISION_MASK, '
                     f'outline{index}, BooleanOp.AND));']

    manifest = json.loads((BASE / 'manifest.json').read_text())
    jar = BASE / 'game/mods/create-1.21.1-6.0.10.jar'
    assert manifest['minecraft'] == '1.21.1' and digest(jar) == CREATE_SHA256
    work = Path(tempfile.mkdtemp(prefix='chute-shape-', dir=ROOT / '.local'))
    java = Path(manifest['java']) / 'bin'
    classpath = ':'.join([str(work), *manifest['classpath'], *manifest['compile_deps'], str(jar)])
    path = work / 'ChuteShapeOracle.java'
    code = JAVA.replace('import com.simibubi.create.AllShapes;',
                        'import com.simibubi.create.AllShapes;\n'
                        'import com.simibubi.create.content.logistics.chute.ChuteShapes;')
    path.write_text(code.replace('BasinShapeOracle', 'ChuteShapeOracle')
                    .replace('EXPRESSIONS', '\n'.join(commands)))
    subprocess.run([java / 'javac', '-proc:none', '-cp', classpath, '-d', work, path], check=True)
    actual = subprocess.check_output([java / 'java', '-cp', classpath, 'ChuteShapeOracle'], text=True)
    (work / 'java.json').write_text(actual)
    measured = json.loads(actual)
    for kind, variants in (('outline', outline), ('collision', collision)):
        for key, boxes in variants.items():
            assert occupied(boxes) == occupied(measured[f'{kind}:{key}']), (kind, key)
    result = {'passed': True, 'create': revision, 'outline_and_collision_shapes': len(measured)}
    path = work / 'result.json'
    path.write_text(json.dumps(result, indent=2) + '\n')
    print(path)


if __name__ == '__main__':
    main()
