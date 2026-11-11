#!/usr/bin/env python3
"""Check Basin/Mixer declarations against original source-expression geometry.

Create and Catnip/Ponder shape code is MIT licensed (The Create Team / The
Creators of Create). This developer oracle uses the supplied private JAR and
cached Minecraft1.21.1 classes; it launches no game and distributes no JAR bytes.
It executes original Builder.add/build and Ponder directional transforms. The
source erase expression uses real vanilla Shapes.join(ONLY_FIRST), avoiding
initialization of unrelated AllShapes static fields that require NeoForge.
"""
import json
from pathlib import Path
import re
import subprocess

from common import ROOT
from reference_java import CREATE_SHA256, digest


JAVA = r'''
import com.simibubi.create.AllShapes;
import net.minecraft.core.Direction;
import net.minecraft.world.phys.shapes.*;
public class BasinShapeOracle {
    static VoxelShape box(double a,double b,double c,double d,double e,double f) {
        return Shapes.box(a/16,b/16,c/16,d/16,e/16,f/16);
    }
    static void emit(String key,VoxelShape shape) {
        System.out.print("\""+key+"\":[");
        boolean first=true;
        for(var b:shape.toAabbs()) {
            if(!first)System.out.print(","); first=false;
            System.out.printf(java.util.Locale.ROOT,"[%s,%s,%s,%s,%s,%s]",
                b.minX,b.minY,b.minZ,b.maxX,b.maxY,b.maxZ);
        }
        System.out.print("]");
    }
    public static void main(String[] args) {
        System.out.print("{");
        EXPRESSIONS
        System.out.println("}");
    }
}
'''


def source(revision, path):
    return subprocess.check_output(['git', 'show', revision + ':src/main/java/' + path],
                                   cwd=ROOT.parent / 'Create', text=True)


def expression(text, name, directional=False):
    end = '.forDirectional()' if directional else '.build()'
    found = re.search(r'\b' + name + r'\s*=\s*(.*?' + re.escape(end) + ')', text, re.S)
    assert found, name
    value = re.sub(r'\s+', '', found[1])
    first = re.match(r'shape\((.*?)\)(?=\.|$)', value)
    assert first, value
    initial = first[1]
    if initial == 'Shapes.block()':
        result = initial
    else:
        assert re.fullmatch(r'\d+(?:,\d+){5}', initial), initial
        result = 'box(' + initial + ')'
    chain = value[first.end():]
    while chain.startswith(('.erase(', '.add(')):
        operation = re.match(r'\.(erase|add)\((\d+(?:,\d+){5})\)', chain)
        assert operation, chain
        kind, coordinates = operation.groups()
        if kind == 'erase':
            result = 'Shapes.join(' + result + ',box(' + coordinates + '),BooleanOp.ONLY_FIRST)'
        else:
            result = 'new AllShapes.Builder(' + result + ').add(box(' + coordinates + ')).build()'
        chain = chain[operation.end():]
    assert chain == end, (name, chain)
    if directional:
        result = 'new AllShapes.Builder(' + result + ').forDirectional().get(Direction.DOWN)'
    return {'source': found[1], 'java': result}


def occupied(boxes):
    # All dimensions are exact integer voxels. Include an exterior cell around
    # the full cube, so accidental expansion is detected as well as missing rims.
    return {(x, y, z) for x in range(-1, 17) for y in range(-1, 17) for z in range(-1, 17)
            if any(all(b[i] <= p[i] < b[i + 3] for i in range(3)) for b in boxes
                   for p in [[(v + .5) / 16 for v in [x, y, z]]])}


def main():
    revision = json.loads((ROOT / 'compatibility.json').read_text())['create_revision']
    shapes = source(revision, 'com/simibubi/create/AllShapes.java')
    assert 'Shapes.join(shape, cuboid(x1, y1, z1, x2, y2, z2), BooleanOp.ONLY_FIRST)' in shapes
    assert 'return forDirectional(UP);' in shapes
    basin_source = source(revision, 'com/simibubi/create/content/processing/basin/BasinBlock.java')
    mixer_source = source(revision, 'com/simibubi/create/content/kinetics/mixer/MechanicalMixerBlock.java')
    assert re.search(r'instanceof ItemEntity\).*?return AllShapes.BASIN_COLLISION_SHAPE;', basin_source, re.S)
    assert 'return AllShapes.BASIN_RAYTRACE_SHAPE;' in basin_source
    assert re.search(r'instanceof Player\).*?return AllShapes.CASING_14PX.get\(Direction.DOWN\);', mixer_source, re.S)
    records = {name: expression(shapes, constant, name == 'mixer_player_outline') for name, constant in [
        ('basin', 'BASIN_BLOCK_SHAPE'), ('basin_item', 'BASIN_COLLISION_SHAPE'),
        ('basin_interaction', 'BASIN_RAYTRACE_SHAPE'), ('mixer', 'MECHANICAL_PROCESSOR_SHAPE'),
        ('mixer_player_outline', 'CASING_14PX')]}
    statements = []
    for index, (name, value) in enumerate(records.items()):
        if index:
            statements.append('System.out.print(",");')
        statements.append('emit(' + json.dumps(name) + ',' + value['java'] + ');')

    base = ROOT / '.local/java-reference'
    manifest = json.loads((base / 'manifest.json').read_text())
    assert manifest['minecraft'] == '1.21.1' and manifest['create'] == '6.0.10'
    create = base / 'game/mods/create-1.21.1-6.0.10.jar'
    assert digest(create) == CREATE_SHA256
    classpath = ':'.join([*manifest['classpath'], *manifest['compile_deps'], str(create)])
    java = Path(manifest['java']) / 'bin'
    output = ROOT / '.local/basin-shape-oracle'
    output.mkdir(parents=True, exist_ok=True)
    path = output / 'BasinShapeOracle.java'
    path.write_text(JAVA.replace('EXPRESSIONS', '\n'.join(statements)))
    subprocess.run([str(java / 'javac'), '-cp', classpath, '-d', str(output), str(path)],
                   check=True, capture_output=True, text=True)
    actual = subprocess.check_output([str(java / 'java'), '-cp', str(output) + ':' + classpath,
                                      'BasinShapeOracle'], text=True)
    (output / 'original-geometry.json').write_text(actual)
    original = json.loads(actual)
    bundle = json.loads((ROOT / 'mixins/create/data/content.json').read_text())
    declarations = {}
    for block in ['basin', 'mechanical_mixer']:
        key = 'data/create/horizon/block/' + block + '.json'
        declarations[block] = json.loads((ROOT / 'content' / key).read_text())
        assert json.loads(bundle[key]) == declarations[block]
    basin, mixer = declarations['basin'], declarations['mechanical_mixer']
    expected = {'basin': basin['collision_shapes']['default'],
                'basin_item': basin['collision_context_shapes']['item']['default'],
                'basin_interaction': basin['interaction_shapes']['default'],
                'mixer': mixer['collision_shapes']['default'],
                'mixer_player_outline': mixer['outline_context_shapes']['player']['default']}
    assert set(basin['collision_context_shapes']) == {'item'}
    assert set(mixer['outline_context_shapes']) == {'player'}
    for name, rows in expected.items():
        assert occupied(rows) == occupied(original[name]), name
    report = {'passed': True, 'source': revision, 'minecraft': manifest['minecraft'],
              'scope': 'Pinned source-expression geometry with actual vanilla boolean shapes, original Builder.add/build and Ponder directional transform; not whole-game AllShapes static initialization or native dispatch proof',
              'expressions': records, 'voxel_cells_checked': len(expected) * 18 ** 3,
              'occupied_cells': {name: len(occupied(rows)) for name, rows in expected.items()}}
    (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Basin/Mixer source shape oracle: 5 original expression geometries and generated/bundled context declarations match')


if __name__ == '__main__':
    main()
