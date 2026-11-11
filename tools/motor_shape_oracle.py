#!/usr/bin/env python3
"""Compare six generated motor shapes with original Create/Ponder Java classes.

Uses only the isolated reference's cached dependencies. No game is launched and
no original class or asset bytes are copied into the public repository.
"""
import json
from pathlib import Path
import re
import subprocess

from common import ROOT
from reference_java import CREATE_SHA256, digest


JAVA = r'''
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.world.phys.Vec3;
import net.minecraft.world.phys.shapes.Shapes;
public class MotorShapeOracle {
    public static void main(String[] args) {
        var shaper = new com.simibubi.create.AllShapes.Builder(
            Shapes.box(BOX_ARGUMENTS)).forDirectional();
        for (var direction : Direction.values()) {
            var b = shaper.get(direction).bounds();
            System.out.printf(java.util.Locale.ROOT,
                "%s %.8f %.8f %.8f %.8f %.8f %.8f%n", direction.getName(),
                b.minX, b.minY, b.minZ, b.maxX, b.maxY, b.maxZ);
        }
        var eye = new Vec3(.5, 65.62, 3.5);
        var end = new Vec3(.5, 66.5, .5);
        for (boolean fullCube : new boolean[]{false, true}) {
            var shape = fullCube ? Shapes.block() : shaper.get(Direction.EAST);
            var hit = shape.clip(eye, end, new BlockPos(0, 66, 0));
            var p = hit.getLocation();
            System.out.printf(java.util.Locale.ROOT, "%s %.8f %.8f %.8f%n",
                fullCube ? "old_full_cube_hit" : "source_hit", p.x, p.y, p.z);
        }
    }
}
'''


def main():
    compatibility = json.loads((ROOT / 'compatibility.json').read_text())
    revision = compatibility['create_revision']
    source = subprocess.check_output([
        'git', 'show', revision + ':src/main/java/com/simibubi/create/AllShapes.java',
    ], cwd=ROOT.parent / 'Create', text=True)
    box = re.search(r'MOTOR_BLOCK\s*=\s*shape\(([^)]+)\)\.forDirectional\(\)', source)
    assert box and re.search(r'forDirectional\(\)\s*\{\s*return forDirectional\(UP\);', source)
    dimensions = [int(value.strip()) for value in box[1].split(',')]
    assert dimensions == [3, 0, 3, 13, 14, 13]
    block_source = subprocess.check_output([
        'git', 'show', revision + ':src/main/java/com/simibubi/create/content/kinetics/motor/CreativeMotorBlock.java',
    ], cwd=ROOT.parent / 'Create', text=True)
    assert 'return AllShapes.MOTOR_BLOCK.get(state.getValue(FACING));' in block_source

    base = ROOT / '.local/java-reference'
    manifest = json.loads((base / 'manifest.json').read_text())
    assert manifest['minecraft'] == '1.21.1' and manifest['create'] == '6.0.10'
    create = base / 'game/mods/create-1.21.1-6.0.10.jar'
    assert digest(create) == CREATE_SHA256
    classpath = ':'.join([*manifest['classpath'], *manifest['compile_deps'], str(create)])
    java = Path(manifest['java']) / 'bin'
    output = ROOT / '.local/motor-shape-oracle'
    output.mkdir(parents=True, exist_ok=True)
    code = JAVA.replace('BOX_ARGUMENTS', ', '.join(str(value) + '/16.0' for value in dimensions))
    path = output / 'MotorShapeOracle.java'
    path.write_text(code)
    subprocess.run([str(java / 'javac'), '-cp', classpath, '-d', str(output), str(path)],
                   check=True, capture_output=True, text=True)
    actual = subprocess.check_output([str(java / 'java'), '-cp', str(output) + ':' + classpath,
                                      'MotorShapeOracle'], text=True)
    (output / 'original-java.txt').write_text(actual)
    records = {row.split()[0]: list(map(float, row.split()[1:])) for row in actual.splitlines()}
    expected = {key: [value] for key, value in records.items() if key not in ('source_hit', 'old_full_cube_hit')}
    assert set(expected) == {'down', 'up', 'north', 'south', 'west', 'east'}
    key = 'data/create/horizon/block/creative_motor.json'
    declaration = json.loads((ROOT / 'content' / key).read_text())
    for kind in ('shapes', 'collision_shapes'):
        assert declaration[kind] == {'property': 'facing', 'values': expected}, declaration[kind]
    bundled = json.loads((ROOT / 'mixins/create/data/content.json').read_text())
    assert json.loads(bundled[key]) == declaration
    center = [.4375, 66.5, .78125]
    distances = {key: sum((a - b) ** 2 for a, b in zip(records[key], center))
                 for key in ('source_hit', 'old_full_cube_hit')}
    assert distances['source_hit'] < .25 ** 2 < distances['old_full_cube_hit'], distances
    report = {'passed': True, 'source': revision,
              'scope': 'Original AllShapes.Builder.forDirectional plus cached Ponder VoxelShaper; six face bounds and exact-pose selection regression',
              'bounds': expected, 'hits': {key: records[key] for key in distances},
              'distance_squared_to_value_box': distances}
    (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Motor shape oracle: 6 original Java facing bounds and selection/collision declarations match; original camera hits inside the value box, old full cube misses')


if __name__ == '__main__':
    main()
