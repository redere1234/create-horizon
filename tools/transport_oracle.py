#!/usr/bin/env python3
"""Belt geometry/transport parity against unchanged AST-exported Create methods.

Default CLI: world queries, component equality and machine callbacks are explicit
small development contexts. Separate run/run_reload/run_boundaries helpers use
a caller-owned isolated native session; only those establish native evidence.
Original Java code is read at the pinned MIT commit and remains only in .local.
"""
import itertools
import json
from pathlib import Path
import random
import re
import shutil
import subprocess

from common import CREATE, PINS, ROOT, cargo
from native_check_session import wait_loaded


SHAPES_JAVA = r'''import java.util.*;
import java.util.function.Function;
public class BeltShapeOracle {
 enum Axis {X,Y,Z}
 enum Direction {
  DOWN(Axis.Y,AxisDirection.NEGATIVE,-1),UP(Axis.Y,AxisDirection.POSITIVE,-1),
  NORTH(Axis.Z,AxisDirection.NEGATIVE,2),SOUTH(Axis.Z,AxisDirection.POSITIVE,0),
  WEST(Axis.X,AxisDirection.NEGATIVE,1),EAST(Axis.X,AxisDirection.POSITIVE,3);
  enum AxisDirection {NEGATIVE,POSITIVE}
  Axis axis;AxisDirection sign;int turn;Direction(Axis a,AxisDirection s,int t){axis=a;sign=s;turn=t;}
  Axis getAxis(){return axis;}AxisDirection getAxisDirection(){return sign;}
  Direction getOpposite(){return values()[ordinal()^1];}float toYRot(){return turn*90;}
  static class Plane {static final List<Direction> HORIZONTAL=List.of(NORTH,SOUTH,WEST,EAST);}
 }
 enum BeltSlope{HORIZONTAL,UPWARD,DOWNWARD,VERTICAL,SIDEWAYS}
 enum BeltPart{START,MIDDLE,END,PULLEY}
 static class Property<T>{}
 static class BeltBlock {
  static final Property<Direction> HORIZONTAL_FACING=new Property<>();
  static final Property<BeltSlope> SLOPE=new Property<>();
  static final Property<BeltPart> PART=new Property<>();
  static final Property<Boolean> CASING=new Property<>();
 }
 record BlockState(Direction direction,BeltSlope slope,BeltPart part,boolean casing) {
  @SuppressWarnings("unchecked") <T>T getValue(Property<T> p){return (T)(p==BeltBlock.HORIZONTAL_FACING?direction:p==BeltBlock.SLOPE?slope:p==BeltBlock.PART?part:casing);}
 }
 record Vec3(double x,double y,double z){}
 record Bounds(double x,double y,double z,double X,double Y,double Z) {
  boolean contains(double a,double b,double c){return a>x&&a<X&&b>y&&b<Y&&c>z&&c<Z;}
 }
 static class VoxelShape {
  List<Bounds> boxes=new ArrayList<>();
  VoxelShape move(double x,double y,double z){var s=new VoxelShape();for(var b:boxes)s.boxes.add(new Bounds(b.x+x,b.y+y,b.z+z,b.X+x,b.Y+y,b.Z+z));return s;}
 }
 static VoxelShape box(double x,double y,double z,double X,double Y,double Z){var s=new VoxelShape();s.boxes.add(new Bounds(x/16,y/16,z/16,X/16,Y/16,Z/16));return s;}
 enum BooleanOp{AND}
 static class Shapes {
  static VoxelShape empty(){return new VoxelShape();}static VoxelShape block(){return box(0,0,0,16,16,16);}
  static VoxelShape or(VoxelShape... ss){var s=new VoxelShape();for(var t:ss)s.boxes.addAll(t.boxes);return s;}
  static VoxelShape joinUnoptimized(VoxelShape a,VoxelShape b,BooleanOp op){var s=new VoxelShape();for(var l:a.boxes)for(var r:b.boxes){var v=new Bounds(Math.max(l.x,r.x),Math.max(l.y,r.y),Math.max(l.z,r.z),Math.min(l.X,r.X),Math.min(l.Y,r.Y),Math.min(l.Z,r.Z));if(v.x<v.X&&v.y<v.Y&&v.z<v.Z)s.boxes.add(v);}return s;}
 }
 // Catnip's actual VoxelShaper uses independent centred X, then Y, then Z
 // VecHelper rotations; horizontal values are (0,-toYRot,0). The context
 // below does those quarter turns directly, without copying the Python path.
 static class VoxelShaper {
  Map<Direction,VoxelShape> shapes=new HashMap<>();
  VoxelShape get(Direction d){return shapes.get(d);}VoxelShape get(Axis a){return get(a==Axis.X?Direction.EAST:a==Axis.Y?Direction.UP:Direction.SOUTH);}
  static VoxelShaper forHorizontal(VoxelShape s,Direction d){return forDirectionsWithRotation(s,d,Direction.Plane.HORIZONTAL,x->new Vec3(0,-x.toYRot(),0));}
  static VoxelShaper forHorizontalAxis(VoxelShape s,Axis a){return forHorizontal(s,a==Axis.X?Direction.EAST:Direction.SOUTH);}
  static VoxelShaper forDirectionsWithRotation(VoxelShape s,Direction from,Iterable<Direction> dirs,Function<Direction,Vec3> f){var v=new VoxelShaper();for(var d:dirs){var a=f.apply(from);var b=f.apply(d);v.shapes.put(d,rotatedCopy(s,new Vec3(b.x-a.x,b.y-a.y,b.z-a.z)));}return v;}
  static double[] rotate(double[] p,int axis,double degrees){int turns=Math.floorMod((int)Math.round(degrees/90),4);for(int j=0;j<turns;j++){double x=p[0],y=p[1],z=p[2];p=switch(axis){case 0->new double[]{x,-z,y};case 1->new double[]{z,y,-x};default->new double[]{-y,x,z};};}return p;}
  static VoxelShape rotatedCopy(VoxelShape s,Vec3 rot){var t=new VoxelShape();for(var b:s.boxes){double[] lo={Double.POSITIVE_INFINITY,Double.POSITIVE_INFINITY,Double.POSITIVE_INFINITY},hi={Double.NEGATIVE_INFINITY,Double.NEGATIVE_INFINITY,Double.NEGATIVE_INFINITY};for(int bits=0;bits<8;bits++){double[] p={(bits&1)==0?b.x:b.X,(bits&2)==0?b.y:b.Y,(bits&4)==0?b.z:b.Z};for(int i=0;i<3;i++)p[i]-=.5;for(int i=0;i<3;i++)p=rotate(p,i,new double[]{rot.x,rot.y,rot.z}[i]);for(int i=0;i<3;i++){lo[i]=Math.min(lo[i],p[i]+.5);hi[i]=Math.max(hi[i],p[i]+.5);}}t.boxes.add(new Bounds(lo[0],lo[1],lo[2],hi[0],hi[1],hi[2]));}return t;}
 }
 static class AllShapes {
  static final VoxelShape BELT_COLLISION_MASK=box(0,0,0,16,19,16);
  static final VoxelShaper CASING_11PX=VoxelShaper.forHorizontal(box(0,0,0,16,11,16),Direction.SOUTH);
  static {CASING_11PX.shapes.put(Direction.UP,box(0,0,0,16,11,16));}
 }
 @@SOURCE@@
 static String occupancy(VoxelShape s){byte[] bits=new byte[16*26*16/8];int k=0;for(int y=-5;y<21;y++)for(int z=0;z<16;z++)for(int x=0;x<16;x++,k++){double a=(x+.5)/16,b=(y+.5)/16,c=(z+.5)/16;for(var box:s.boxes)if(box.contains(a,b,c)){bits[k/8]|=(byte)(1<<(k%8));break;}}return HexFormat.of().formatHex(bits);}
 public static void main(String[] args){for(var d:Direction.Plane.HORIZONTAL)for(var s:BeltSlope.values())for(var p:BeltPart.values())for(boolean c:new boolean[]{false,true}){var state=new BlockState(d,s,p,c);System.out.println(d.name().toLowerCase()+","+s.name().toLowerCase()+","+p.name().toLowerCase()+","+c+" "+occupancy(BeltShapes.getShape(state))+" "+occupancy(BeltShapes.getCollisionShape(state)));}}
}'''


def shape_checks():
    """All bare and cased source state volumes, independent of the Python generator."""
    import belt_shapes
    work = ROOT / '.local/belt-shape-oracle'
    work.mkdir(parents=True, exist_ok=True)
    source = subprocess.check_output(['git', 'show', PINS['create_revision'] + ':src/main/java/com/simibubi/create/content/kinetics/belt/BeltShapes.java'], cwd=CREATE, text=True)
    source = '\n'.join(line for line in source.splitlines() if not line.startswith(('package ', 'import ')))
    assert source.count('public class BeltShapes {') == 1
    source = source.replace('public class BeltShapes {', 'static class BeltShapes {', 1)
    program = work / 'BeltShapeOracle.java'
    program.write_text(SHAPES_JAVA.replace('@@SOURCE@@', source))
    subprocess.run([shutil.which('javac') or 'javac', '-d', str(work), str(program)], check=True)
    expected = subprocess.check_output([shutil.which('java') or 'java', '-cp', str(work), 'BeltShapeOracle'], text=True).splitlines()
    geometry, collision = belt_shapes.geometry()

    def occupancy(boxes):
        bits = bytearray(16 * 26 * 16 // 8)
        index = 0
        for y in range(-5, 21):
            for z in range(16):
                for x in range(16):
                    point = ((x + .5) / 16, (y + .5) / 16, (z + .5) / 16)
                    if any(all(box[i] < point[i] < box[i + 3] for i in range(3)) for box in boxes):
                        bits[index // 8] |= 1 << (index % 8)
                    index += 1
        return bits.hex()

    for line in expected:
        key, outline, passive = line.split()
        assert max(len(geometry['values'][key]), len(collision['values'][key])) <= 16, key
        assert occupancy(geometry['values'][key]) == outline, ('outline', key)
        assert occupancy(collision['values'][key]) == passive, ('collision', key)
    assert len(expected) == len(geometry['values']) == 160
    result = {'passed': True, 'states': 160, 'shape_volumes': 320,
              'occupancy_cells': 160 * 2 * 16 * 26 * 16, 'reference': PINS['create_revision'],
              'scope': 'unchanged BeltShapes Java, bare and cased blocks; explicit independent shape algebra context'}
    (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def run(call, graphics=False, log=None, scratch=None):
    """Actual native belt fixture, exclusively in a caller-owned local world.

    This intentionally does not claim the not-yet-wired virtual segment hopper
    capability, living passengers, casings or belt processor callbacks. A real
    connector builds the chain; output uses original depot/direct-input and
    dropped-entity to ordinary hopper paths. No game is started here.
    """
    scratch = Path(scratch).resolve()
    scratch.relative_to((ROOT / '.local').resolve())
    world = call('state')['world']
    assert world != 'CreateProcessing05', 'Use a separate synthetic belt world'
    assert (scratch / 'saves' / world / 'level.dat').is_file(), (scratch, world)
    x, y, z = 224, 66, 0
    events = []
    (scratch / 'belt-native-result.json').write_text(json.dumps({'passed': False, 'status': 'running', 'world': world}) + '\n')

    def command(line):
        reply = call('command', line)
        events.append({'command': line, 'reply': reply})
        (scratch / 'belt-native-transcript.json').write_text(json.dumps(events, indent=2) + '\n')
        return reply

    def text(pos, key=None):
        line = 'data get block ' + ' '.join(map(str, pos))
        if key:
            line += ' ' + key
        return ' '.join(command(line).get('chat', []))

    def number(pos, key):
        value = text(pos)
        found = re.search(r'\b' + re.escape(key) + r':\s*(-?[\d.]+)', value)
        assert found, (pos, key, value)
        return float(found[1])

    def motor(rpm):
        command(f'data merge block {x - 1} {y} {z} {{ScrollValue:{rpm}}}')
        call('wait', 8)

    def stack(item, count, location=0, component=False):
        components = ',components:{"minecraft:custom_data":{belt_sentinel:17}}' if component else ''
        command(f'summon minecraft:item {x + .5} {y + 1.05} {z + location + .5} {{PickupDelay:32767,Item:{{id:"{item}",count:{count}{components}}}}}')

    def count(pos, item):
        return sum(v['count'] for v in call('container', *pos)['slots'] if v and v['item'] == item)

    def stand(px, pz):
        support = (int(px), y - 1, int(pz))
        present = command('execute if block ' + ' '.join(map(str, support)) +
                          ' minecraft:smooth_stone run say belt_support_present')
        assert any('belt_support_present' in line for line in present['chat']), (support, present)
        assert call('block', *support)['block'] == 'minecraft:smooth_stone'
        command(f'tp @s {px} {y} {pz}')
        call('wait', 3)
        player = call('state')['player']
        assert player['on_ground'] and abs(player['position'][1] - y) < .001, player

    command('gamemode creative')
    command('kill @e[type=minecraft:item]')
    command(f'tp @s {x + 2.5} {y + 2} {z - 2.5}')
    call('wait-ready', 120)
    command(f'fill {x - 2} {y - 3} {z - 3} {x + 7} {y + 4} {z + 8} minecraft:air')
    command(f'fill {x - 2} {y - 1} {z - 3} {x + 7} {y - 1} {z + 8} minecraft:smooth_stone')
    command(f'setblock {x - 1} {y} {z} create:creative_motor[facing=east]')
    command(f'setblock {x} {y} {z} create:shaft[axis=x]')
    command(f'setblock {x} {y} {z + 5} create:shaft[axis=x]')
    command(f'setblock {x} {y} {z + 6} create:depot')
    command('clear @s')
    command('give @s create:belt_connector 1')
    call('wait', 5)
    call('select', 'create:belt_connector')
    for offset in [0, 5]:
        stand(x + 2.5, z + offset - 1.5)
        call('look-at', 'block', x, y, z + offset, 'east')
        call('wait', 2)
        call('interact', x, y, z + offset, 'east')
        call('wait', 8)
    for index in range(6):
        block = call('block', x, y, z + index)
        expected = 'start' if index == 0 else 'end' if index == 5 else 'middle'
        assert block['block'] == 'create:belt' and f'part={expected}' in block['state'], (index, block)
        assert 'facing=south' in block['state'] and 'slope=horizontal' in block['state'], block
        assert number((x, y, z + index), 'Length') == 6
        assert number((x, y, z + index), 'Index') == index
    motor(32)
    for index in range(6):
        assert number((x, y, z + index), 'Speed') == 32

    # A stopped belt accepts a dropped full component-bearing stack, then moves
    # it into the real depot when powered. No ItemStack gets flattened to an id.
    motor(0)
    stand(x + 3.5, z + 2.5)
    stack('minecraft:copper_ingot', 7, component=True)
    call('wait', 12)
    held = text((x, y, z), 'Inventory')
    assert 'minecraft:copper_ingot' in held and 'belt_sentinel: 17' in held, held
    motor(32)
    call('wait', 160)
    assert count((x, y, z + 6), 'minecraft:copper_ingot') == 7
    held = text((x, y, z + 6), 'HeldItem')
    assert 'belt_sentinel: 17' in held, held

    # Occupied source depots reject another stack. The belt queues at the
    # original direct-input margin; reversing sends it back to a real hopper.
    stack('minecraft:iron_ingot', 3)
    call('wait', 150)
    held = text((x, y, z), 'Inventory')
    assert 'minecraft:iron_ingot' in held and re.search(r'Pos:\s*5\.75[f,}]', held), held
    images = []
    if graphics:
        stand(x + 5.5, z + 3.5)
        call('look-at', x + .5, y + .6, z + 2.5)
        image = scratch / 'belt-native.png'
        call('key', 'f1', 'tap')
        try:
            call('wait', 2)
            call('screenshot', image)
        finally:
            call('key', 'f1', 'tap')
        images.append(str(image))
    command(f'setblock {x} {y - 2} {z - 1} minecraft:chest')
    command(f'setblock {x} {y - 1} {z - 1} minecraft:hopper[facing=down]')
    motor(-32)
    call('wait', 180)
    assert count((x, y - 2, z - 1), 'minecraft:iron_ingot') == 3
    assert 'minecraft:iron_ingot' not in text((x, y, z), 'Inventory')

    # Middle removal restores both pulley shafts and clears every middle.
    command('clear @s')
    stand(x + 2.5, z + 2.5)
    call('look-at', 'block', x, y, z + 2, 'east')
    call('wait', 2)
    call('break', x, y, z + 2)
    call('wait', 10)
    for index in range(6):
        block = call('block', x, y, z + index)
        assert block['block'] == ('create:shaft' if index in [0, 5] else 'minecraft:air'), (index, block)
    # Leave a canonical, stopped, component-bearing inventory for an actual
    # process/world restart. run_reload deliberately verifies this later.
    motor(0)
    command('give @s create:belt_connector 1')
    call('wait', 5)
    call('select', 'create:belt_connector')
    for offset in [0, 5]:
        stand(x + 2.5, z + offset - 1.5)
        call('look-at', 'block', x, y, z + offset, 'east')
        call('wait', 2)
        call('interact', x, y, z + offset, 'east')
        call('wait', 8)
    stack('minecraft:gold_ingot', 2, location=2, component=True)
    call('wait', 12)
    saved = text((x, y, z), 'Inventory')
    assert 'minecraft:gold_ingot' in saved and 'belt_sentinel: 17' in saved, saved
    report = {'passed': True, 'world': world, 'anchor': [x, y, z],
              'checks': ['connector placement and canonical chain metadata', 'all six segments powered',
                         'stopped input and component-preserving depot output', 'occupied depot backpressure',
                         'reversed ejection through ordinary hopper into chest', 'chain removal restores shafts'],
              'images': images, 'reload_fixture': {'controller': [x, y, z], 'inventory': saved},
              'unwired': ['virtual segment hopper capability', 'living passengers', 'casings/dyes', 'belt machine processing']}
    (scratch / 'belt-native-transcript.json').write_text(json.dumps(events, indent=2) + '\n')
    (scratch / 'belt-native-result.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def run_reload(call, scratch):
    """After a real close/reopen, compare the previously saved full inventory."""
    scratch = Path(scratch).resolve()
    scratch.relative_to((ROOT / '.local').resolve())
    report = json.loads((scratch / 'belt-native-result.json').read_text())
    assert report['passed'] and call('state')['world'] == report['world']
    fixture = report['reload_fixture']
    x, y, z = fixture['controller']
    call('command', f'tp @s {x + 2.5} {y + 1} {z + 2.5}')
    call('wait-ready', 120)
    actual = ' '.join(call('command', f'data get block {x} {y} {z} Inventory').get('chat', []))
    assert actual == fixture['inventory'], (fixture['inventory'], actual)
    for index in range(6):
        assert call('block', x, y, z + index)['block'] == 'create:belt'
    report['checks'].append('actual restart preserves exact transported positions, components, angles and order')
    report['reload_passed'] = True
    (scratch / 'belt-native-result.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def run_boundaries(call, graphics=False, log=None, scratch=None, numeric_overrides=False, numeric_only=False,
                   expect_component_sync=False):
    """Real native dimension/cache/component boundaries in a disposable world.

    Keep overworld and Nether belts at identical coordinates and force-load both
    while switching dimensions. Later unload every belt chunk, freeze before
    reloading, and destroy before BE ticks can repopulate the runtime cache.
    """
    scratch = Path(scratch).resolve()
    scratch.relative_to((ROOT / '.local').resolve())
    assert call('state')['world'] != 'CreateProcessing05'
    x, y, z = 320, 80, 12
    events, checks, images = [], [], []
    assert not numeric_only or numeric_overrides
    path = scratch / ('belt-numeric-result.json' if numeric_only else 'belt-boundaries-result.json')
    report = {'passed': False, 'checks': checks, 'images': images}
    path.write_text(json.dumps(report, indent=2) + '\n')

    def ctl(*args):
        value = call(*args)
        events.append({'command': list(map(str, args)), 'reply': value})
        (scratch / ('belt-numeric-transcript.json' if numeric_only else 'belt-boundaries-transcript.json')).write_text(json.dumps(events, indent=2) + '\n')
        return value

    def command(line):
        return ctl('command', line)

    def data(pos=(x, y, z), key='Inventory'):
        return ' '.join(command('data get block ' + ' '.join(map(str, pos)) + (' ' + key if key else ''))['chat'])

    def dimension(name):
        command(f'execute in {name} run tp @s {x + 2.5} {y} {z - 1.5}')
        ctl('wait-ready', 120)
        ctl('wait', 5)
        assert ctl('state')['dimension'] == name

    def clear_items():
        command('kill @e[type=minecraft:item]')
        command('clear @s')
        ctl('wait', 5)

    def stand(px, pz, frozen=False):
        # Control `fill` changes the client scene; the fixture needs a real
        # server floor so it survives chunk synchronization and restarts.
        support = (int(px), y - 1, int(pz))
        present = command('execute if block ' + ' '.join(map(str, support)) +
                          ' minecraft:smooth_stone run say boundary_support_present')
        assert any('boundary_support_present' in line for line in present['chat']), (support, present)
        assert ctl('block', *support)['block'] == 'minecraft:smooth_stone'
        command(f'tp @s {px} {y} {pz}')
        ctl('wait', 3)
        player = ctl('state')['player']
        assert abs(player['position'][1] - y) < .001, player
        if not frozen:
            assert player['on_ground'], player

    def connector():
        command('give @s create:belt_connector 1')
        ctl('wait', 5)
        ctl('select', 'create:belt_connector')
        for offset in [0, 5]:
            stand(x + 2.5, z + offset - 1.5)
            ctl('look-at', 'block', x, y, z + offset, 'east')
            ctl('wait', 2)
            ctl('interact', x, y, z + offset, 'east')
            ctl('wait', 8)
        for index in range(6):
            assert ctl('block', x, y, z + index)['block'] == 'create:belt'
        command(f'data merge block {x - 1} {y} {z} {{ScrollValue:0}}')
        ctl('wait', 8)
        stand(x + 3.5, z + 2.5)

    def setup(name):
        command('gamemode creative')
        dimension(name)
        wait_loaded(ctl, [(px, y, pz) for px in [x - 2, x + 5] for pz in [z - 3, z + 8]])
        command(f'fill {x - 2} {y - 3} {z - 3} {x + 5} {y + 4} {z + 8} minecraft:air')
        command(f'fill {x - 2} {y - 1} {z - 3} {x + 5} {y - 1} {z + 8} minecraft:smooth_stone')
        ctl('wait', 5)
        clear_items()
        command(f'setblock {x - 1} {y} {z} create:creative_motor[facing=east]')
        command(f'setblock {x} {y} {z} create:shaft[axis=x]')
        command(f'setblock {x} {y} {z + 5} create:shaft[axis=x]')
        ctl('wait', 5)
        connector()

    def feed(item, count, mark, maximum=None):
        extra = (',"!minecraft:max_stack_size":{}' if maximum == 'removed' else
                 f',"minecraft:max_stack_size":{maximum}' if maximum else '')
        components = '{"minecraft:custom_data":{boundary_sentinel:' + str(mark) + '}' + extra + '}'
        nbt = '{PickupDelay:32767,Item:{id:"' + item + '",count:' + str(count) + ',components:' + components + '}}'
        command(f'summon minecraft:item {x + .5} {y + 1.05} {z + .5} ' + nbt)
        ctl('wait', 12)
        held = data()
        assert item in held and f'boundary_sentinel: {mark}' in held, held
        return held

    def loose(item):
        return [e for e in ctl('entities', 32, 'minecraft:item')['entities'] if e['item']['item'] == item]

    def total(item):
        return sum(e['item']['count'] for e in loose(item)) + ctl('inventory')['counts'].get(item, 0)

    def destroy(index=0, frozen=False):
        stand(x + 2.5, z + index + .5, frozen=frozen)
        ctl('look-at', 'block', x, y, z + index, 'east')
        ctl('wait', 2)
        ctl('break', x, y, z + index)
        ctl('wait', 5)
        for offset in range(6):
            expected = 'minecraft:air' if offset not in [0, 5] or offset == index else 'create:shaft'
            assert ctl('block', x, y, z + offset)['block'] == expected

    # Component override must split a 32-stack into16 transported +16 entity.
    setup('minecraft:overworld')
    held = feed('minecraft:cobblestone', 32, 16, maximum=16)
    assert sum(map(int, re.findall(r'\bcount:\s*(\d+)', held))) == 16, held
    assert '"minecraft:max_stack_size": 16' in held, held
    remaining = loose('minecraft:cobblestone')
    assert sum(e['item']['count'] for e in remaining) == 16, remaining
    selector = '@e[type=minecraft:item,nbt={Item:{id:"minecraft:cobblestone"}},limit=1]'
    entity_nbt = ' '.join(command('data get entity ' + selector)['chat'])
    assert '"minecraft:max_stack_size": 16' in entity_nbt and 'boundary_sentinel: 16' in entity_nbt, entity_nbt
    report['client_projection'] = remaining
    if expect_component_sync:
        assert all('"minecraft:max_stack_size":16' in e['item'].get('components', '').replace(' ', '')
                   for e in remaining), remaining
    else:
        report['known_native_gap'] = 'component sync was not required by this older-binary fixture; authoritative conservation is checked separately'
    command('clear @s')
    command('data merge entity ' + selector + ' {PickupDelay:0}')
    command(f'tp @s {x + .5} {y + .8125} {z + .5}')
    ctl('wait', 20)
    assert ctl('inventory')['counts'].get('minecraft:cobblestone', 0) == 16
    player_nbt = ' '.join(command('data get entity @s Inventory')['chat'])
    assert '"minecraft:max_stack_size": 16' in player_nbt and 'boundary_sentinel: 16' in player_nbt, player_nbt
    checks.append('component maximum16 limits intake; transported16 + entity16 conserves original32; normal pickup retains authoritative component')
    if numeric_overrides:
        numeric_cases = []
        for literal in ['16b', '16s', '16L', '16.75f', '16.75d', '4294967312L']:
            setup('minecraft:overworld')
            held = feed('minecraft:cobblestone', 32, 16, maximum=literal)
            assert sum(map(int, re.findall(r'\bcount:\s*(\d+)', held))) == 16, (literal, held)
            remaining = loose('minecraft:cobblestone')
            assert sum(e['item']['count'] for e in remaining) == 16, (literal, remaining)
            if expect_component_sync:
                assert all('"minecraft:max_stack_size":16' in e['item'].get('components', '').replace(' ', '')
                           for e in remaining), (literal, remaining)
            numeric_cases.append({'literal': literal, 'transported': held, 'remaining': remaining})
        report['numeric_cases'] = numeric_cases
        checks.append('all legal numeric max_stack_size tag forms follow original Number.intValue codec capacity')
        if expect_component_sync:
            setup('minecraft:overworld')
            held = feed('minecraft:cobblestone', 2, 18, maximum='removed')
            assert sum(map(int, re.findall(r'\bcount:\s*(\d+)', held))) == 1, held
            assert '"!minecraft:max_stack_size"' in held, held
            remaining = loose('minecraft:cobblestone')
            assert sum(e['item']['count'] for e in remaining) == 1, remaining
            assert all('"!minecraft:max_stack_size"' in e['item'].get('components', '')
                       for e in remaining), remaining
            report['removed_capacity'] = {'transported': held, 'remaining': remaining}
            checks.append('removed max-stack component defaults to1 and survives actual client entity sync')
    else:
        report['pending'] = ['Byte/Short/Long/Float/Double max_stack_size tags require subsequent numeric-codec patch binary']
    if numeric_only:
        report.update({'passed': True, 'source': PINS['create_revision'],
                       'scope': 'numeric max-stack capacity and authoritative conservation; client component sync required=' + str(expect_component_sync)})
        path.write_text(json.dumps(report, indent=2) + '\n')
        return report

    # Both dimensions tick while force-loaded, at the same controller position.
    setup('minecraft:overworld')
    before_overworld = feed('minecraft:diamond', 7, 101)
    command(f'forceload add {x} {z} {x} {z + 5}')
    setup('minecraft:the_nether')
    before_nether = feed('minecraft:diamond', 11, 202)
    command(f'forceload add {x} {z} {x} {z + 5}')
    dimension('minecraft:overworld')
    assert data() == before_overworld
    destroy(0)
    assert total('minecraft:diamond') == 7
    assert all('boundary_sentinel:101' in e['item'].get('components', '').replace(' ', '') for e in loose('minecraft:diamond'))
    dimension('minecraft:the_nether')
    assert data() == before_nether
    destroy(2)
    assert total('minecraft:diamond') == 11
    assert all('boundary_sentinel:202' in e['item'].get('components', '').replace(' ', '') for e in loose('minecraft:diamond'))
    checks.append('two simultaneously ticking dimensions preserve separate component-bearing inventories; controller/middle destruction conserves7/11 diamonds')
    command(f'forceload remove {x} {z} {x} {z + 5}')

    # A true whole-chunk unload: observe both client and authoritative server
    # unloaded before returning. Freeze makes cache-miss destruction independent
    # of a normal BE tick repopulating the cache after load.
    setup('minecraft:overworld')
    before_unload = feed('minecraft:gold_ingot', 5, 303)
    command(f'forceload remove {x} {z} {x} {z + 5}')
    command(f'tp @s {x + 4096.5} {y} {z + .5}')
    ctl('wait-ready', 120)
    unloaded = False
    for attempt in range(20):
        ctl('wait', 40)
        local = ctl('block', x, y, z)
        server = command(f'execute if loaded {x} {y} {z} run say belt_boundary_still_loaded')
        if not local['loaded'] and not any('belt_boundary_still_loaded' in v for v in server.get('chat', [])):
            unloaded = True
            break
    assert unloaded, ('belt chunk did not unload', local, server)
    command('tick freeze')
    try:
        command(f'tp @s {x + 2.5} {y} {z + .5}')
        ctl('wait-ready', 120)
        ctl('wait', 5)
        assert data() == before_unload, (before_unload, data())
        destroy(0, frozen=True)
        assert total('minecraft:gold_ingot') == 5
        motion_text = ' '.join(command('data get entity @e[type=minecraft:item,nbt={Item:{id:"minecraft:gold_ingot"}},limit=1] Motion')['chat'])
        vector = re.search(r'\[([^]]+)\]', motion_text)
        assert vector, motion_text
        motion = [float(v.strip().rstrip('dDfF')) for v in vector[1].split(',')]
        assert motion == [0.0, 0.125, 0.0], motion
    finally:
        command('tick unfreeze')
    checks.append('whole-chunk unload/reload preserves full inventory; frozen pre-tick destruction conserves5 gold and stopped source vertical ejection')

    # Survival source pulley removal with an inventory containing no free slot
    # and no shaft merge room must return the shaft as a normal player drop.
    setup('minecraft:overworld')
    command('gamemode survival')
    command('clear @s')
    command('give @s create:shaft 1')
    ctl('wait', 5)
    ctl('select', 'create:shaft')
    stand(x + 2.5, z + 2.5)
    ctl('look-at', 'block', x, y, z + 2, 'east')
    ctl('wait', 2)
    ctl('interact', x, y, z + 2, 'east')
    ctl('wait', 5)
    assert 'part=pulley' in ctl('block', x, y, z + 2)['state']
    for slot in range(36):
        target = f'hotbar.{slot}' if slot < 9 else f'inventory.{slot - 9}'
        command(f'item replace entity @s {target} with minecraft:stone 64')
    command('item replace entity @s hotbar.0 with create:wrench 1')
    ctl('wait', 5)
    ctl('select', 'create:wrench')
    assert ctl('inventory')['counts'] == {'create:wrench': 1, 'minecraft:stone': 2240}
    ctl('look-at', 'block', x, y, z + 2, 'east')
    ctl('wait', 2)
    ctl('interact', x, y, z + 2, 'east')
    ctl('wait', 5)
    assert 'part=middle' in ctl('block', x, y, z + 2)['state']
    assert ctl('inventory')['counts'].get('create:shaft', 0) == 0
    assert sum(e['item']['count'] for e in loose('create:shaft')) == 1
    checks.append('survival middle pulley wrench refund survives a completely full player inventory')
    command('gamemode creative')
    if graphics:
        command(f'tp @s {x + 4.5} {y} {z + 3.5}')
        ctl('wait', 3)
        ctl('look-at', x + .5, y + .6, z + 2.5)
        ctl('key', 'f1', 'tap')
        try:
            ctl('wait', 2)
            image = scratch / 'belt-boundaries.png'
            ctl('screenshot', image)
            images.append(str(image))
        finally:
            ctl('key', 'f1', 'tap')
    report.update({'passed': True, 'dimensions': ['minecraft:overworld', 'minecraft:the_nether'],
                   'anchor': [x, y, z], 'source': PINS['create_revision']})
    path.write_text(json.dumps(report, indent=2) + '\n')
    return report



JAVA = r'''import java.util.*;
public class TransportOracle {
 enum Axis { X,Y,Z; int choose(int x,int y,int z){return new int[]{x,y,z}[ordinal()];} boolean isVertical(){return this==Y;} }
 enum AxisDirection {NEGATIVE(-1),POSITIVE(1);int step;AxisDirection(int s){step=s;}int getStep(){return step;} }
 enum Direction {
  DOWN(Axis.Y,-1),UP(Axis.Y,1),NORTH(Axis.Z,-1),SOUTH(Axis.Z,1),WEST(Axis.X,-1),EAST(Axis.X,1);
  Axis axis;int step;Direction(Axis a,int s){axis=a;step=s;}Axis getAxis(){return axis;}
  AxisDirection getAxisDirection(){return step<0?AxisDirection.NEGATIVE:AxisDirection.POSITIVE;}
  Direction getOpposite(){return values()[ordinal()^1];} Vec3i getNormal(){return new Vec3i(axis==Axis.X?step:0,axis==Axis.Y?step:0,axis==Axis.Z?step:0);}
  static Direction get(AxisDirection s,Axis a){for(var d:values())if(d.axis==a&&d.step==s.step)return d;throw new AssertionError();}
  static Direction fromAxisAndDirection(Axis a,AxisDirection s){return get(s,a);}
 }
 static final AxisDirection NEGATIVE=AxisDirection.NEGATIVE,POSITIVE=AxisDirection.POSITIVE;
 enum BeltSlope {HORIZONTAL,UPWARD,DOWNWARD,VERTICAL,SIDEWAYS}
 enum BeltPart{START,MIDDLE,END,PULLEY}
 static final BeltSlope HORIZONTAL=BeltSlope.HORIZONTAL;static final BeltPart MIDDLE=BeltPart.MIDDLE;
 record Vec3i(int x,int y,int z){int getX(){return x;}int getY(){return y;}int getZ(){return z;}}
 static class Property<T>{}
 static class BlockStateProperties {static final Property<Axis> AXIS=new Property<>();static final Property<Direction> HORIZONTAL_FACING=new Property<>();}
 static class BeltBlock {static final Property<BeltSlope> SLOPE=new Property<>();static final Property<BeltPart> PART=new Property<>();}
 static class BlockState {
  Axis axis;BeltSlope slope;Direction facing;boolean shaft,replaceable;
  @SuppressWarnings("unchecked") <T>T getValue(Property<T> key){return (T)(key==BlockStateProperties.AXIS?axis:key==BlockStateProperties.HORIZONTAL_FACING?facing:key==BeltBlock.PART?BeltPart.START:slope);}
  boolean canBeReplaced(){return replaceable;}
 }
 record BlockPos(int x,int y,int z) {static final Vec3i ZERO=new Vec3i(0,0,0);
  int getX(){return x;}int getY(){return y;}int getZ(){return z;}
  BlockPos subtract(BlockPos o){return new BlockPos(x-o.x,y-o.y,z-o.z);}
  BlockPos offset(BlockPos o){return new BlockPos(x+o.x,y+o.y,z+o.z);}
  BlockPos above(int y){return new BlockPos(x,this.y+y,z);}
  BlockPos relative(Direction d){return new BlockPos(x+(d.axis==Axis.X?d.step:0),y+(d.axis==Axis.Y?d.step:0),z+(d.axis==Axis.Z?d.step:0));}
  boolean closerThan(BlockPos p,double distance){double a=x-p.x,b=y-p.y,c=z-p.z;return a*a+b*b+c*c<distance*distance;}
  static BlockPos containing(double x,double y,double z){return new BlockPos((int)Math.floor(x),(int)Math.floor(y),(int)Math.floor(z));}
 }
 static class BlockEntity {}
 static class KineticBlockEntity extends BlockEntity {float speed;KineticBlockEntity(float s){speed=s;}float getTheoreticalSpeed(){return speed;}}
 static class ShaftBlock {static boolean isShaft(BlockState state){return state.shaft;}}
 static class AbstractSimpleShaftBlock {static final Property<Axis> AXIS=BlockStateProperties.AXIS;}
 static class Level {
  boolean isClientSide;BlockPos first,second;Axis firstAxis,secondAxis;float firstRpm,secondRpm;int flags,space;int room;
  boolean isLoaded(BlockPos p){return !(p.equals(first)&&(flags&1)!=0||p.equals(second)&&(flags&2)!=0);}
  BlockState getBlockState(BlockPos p){var s=new BlockState();s.replaceable=space==0;s.shaft=space==1||space==2;s.axis=space==2?Axis.values()[(firstAxis.ordinal()+1)%3]:firstAxis;
   if(p.equals(first)){s.shaft=(flags&4)==0;s.axis=firstAxis;}if(p.equals(second)){s.shaft=(flags&8)==0;s.axis=secondAxis;}return s;}
  BlockEntity getBlockEntity(BlockPos p){return new KineticBlockEntity(p.equals(first)?firstRpm:secondRpm);}
 }
 static int maximum=20;static Integer maxLength(){return maximum;}
 static boolean validateAxis(Level world,BlockPos pos) @@VALIDATE@@
 static boolean canConnect(Level world,BlockPos first,BlockPos second) @@CONNECT@@
 static BeltSlope getSlopeBetween(BlockPos start,BlockPos end) @@SLOPE@@
 static Direction getFacingFromTo(BlockPos start,BlockPos end) @@FACING@@
 static List<BlockPos> getBeltChainBetween(BlockPos start,BlockPos end,BeltSlope slope,Direction direction) @@CHAIN@@
 static class ItemStack {
  int count,key;ItemStack(int k,int c){key=k;count=c;}boolean isEmpty(){return count==0;}
  static boolean matches(ItemStack a,ItemStack b){return a.key==b.key&&a.count==b.count;}
 }
 static class TransportedItemStack implements Comparable<TransportedItemStack> {
  ItemStack stack;float beltPosition,prevBeltPosition,sideOffset,prevSideOffset;int angle,insertedAt;Direction insertedFrom=Direction.UP;boolean locked,lockedExternally;
  float getTargetSideOffset() @@OFFSET@@
  public int compareTo(TransportedItemStack o) @@COMPARE@@
 }
 static class BeltBlockEntity {
  float speed;Direction facing;BeltSlope slope;int beltLength;Level level=new Level();BeltBlockEntity(float s,Direction f,BeltSlope l,int len){speed=s;facing=f;slope=l;beltLength=len;}
  float getSpeed(){return speed;}Direction getBeltFacing(){return facing;}Level getLevel(){return level;}
  boolean isVirtual(){return false;}void notifyUpdate(){}
  BlockState getBlockState(){var s=new BlockState();s.slope=slope;s.facing=facing;return s;}
  float getBeltMovementSpeed() @@SPEED@@
  float getDirectionAwareBeltMovementSpeed() @@AWARE@@
  Direction getMovementFacing() @@MOVEMENT_FACING@@
 Vec3i getMovementDirection(boolean firstHalf,boolean ignoreHalves) @@MOVEMENT_DIRECTION@@
 Vec3i getBeltChainDirection() @@CHAIN_DIRECTION@@
 }
 static class ServerSpeedProvider {static float get(){return 1;}}
 static class BeltHelper {static BlockPos getPositionForOffset(BeltBlockEntity b,int i){return new BlockPos(i,0,0);}}
 enum ProcessingResult {PASS,HOLD,REMOVE}
 static class TransportedItemStackHandlerBehaviour {}
 static class BeltProcessingBehaviour {
  int mode;BeltProcessingBehaviour(int m){mode=m;}
  ProcessingResult handleHeldItem(TransportedItemStack s,TransportedItemStackHandlerBehaviour h){return mode==1?ProcessingResult.HOLD:mode==3?ProcessingResult.REMOVE:ProcessingResult.PASS;}
  ProcessingResult handleReceivedItem(TransportedItemStack s,TransportedItemStackHandlerBehaviour h){return handleHeldItem(s,h);}
  static boolean isBlocked(Level l,BlockPos p){return false;}
 }
 static class DirectBeltInputBehaviour {
  static final Class<DirectBeltInputBehaviour> TYPE=DirectBeltInputBehaviour.class;Level level;DirectBeltInputBehaviour(Level l){level=l;}
  boolean canInsertFromSide(Direction d){return true;}
  ItemStack handleInsertion(TransportedItemStack s,Direction d,boolean sim){int n=Math.min(level.room,s.stack.count);level.room-=n;return new ItemStack(s.stack.key,s.stack.count-n);}
 }
 static class BlockEntityBehaviour {@SuppressWarnings("unchecked") static<T>T get(Level l,BlockPos p,Class<T> type){return (T)new DirectBeltInputBehaviour(l);}}
 static class BeltFunnelInteractionHandler {static boolean checkForFunnels(Inventory i,TransportedItemStack t,float n){return false;}}
 static class BeltTunnelInteractionHandler {static boolean flapTunnelsAndCheckIfStuck(Inventory i,TransportedItemStack t,float n){return false;}}
 static class BeltCrusherInteractionHandler {static boolean checkForCrushers(Inventory i,TransportedItemStack t,float n){return false;}}
 static void flapTunnel(Inventory i,int segment,Direction d,boolean in){}
 static class Mth {static float clamp(float x,float a,float b){return x<a?a:Math.min(x,b);}}
 static class Inventory {
  BeltBlockEntity belt;List<TransportedItemStack> items=new LinkedList<>(),toInsert=new LinkedList<>(),toRemove=new LinkedList<>(),ejected=new LinkedList<>();
  TransportedItemStack lazyClientItem;boolean beltMovementPositive;int end,processorSegment,processorMode;
  Inventory(BeltBlockEntity b){belt=b;}
  enum Ending {UNRESOLVED(0),EJECT(0),INSERT(.25f),FUNNEL(.5f),BLOCKED(.45f);float margin;Ending(float m){margin=m;}}
  Ending resolveEnding(){return Ending.values()[end+1];}
  void eject(TransportedItemStack s){ejected.add(s);}
  BeltProcessingBehaviour getBeltProcessingAtSegment(int segment){return processorMode!=0&&segment==processorSegment?new BeltProcessingBehaviour(processorMode):null;}
  TransportedItemStackHandlerBehaviour getTransportedItemStackHandlerAtSegment(int segment){return new TransportedItemStackHandlerBehaviour();}
  void insert(TransportedItemStack newStack) @@INSERT@@
  boolean isBlocking(int segment,Direction side,float segmentPos,TransportedItemStack stack) @@BLOCKING@@
  boolean canInsertAtFromSide(int segment,Direction side) @@CAN_INSERT@@
  TransportedItemStack getStackAtOffset(int offset) @@GET_STACK@@
  boolean handleBeltProcessingAndCheckIfRemoved(TransportedItemStack currentItem,float nextOffset,boolean noMovement) @@PROCESS@@
  void tick() @@TICK@@
 }
 public static void main(String[] args){
  var in=new Scanner(System.in);var out=new StringBuilder();
  while(in.hasNext()){
   String op=in.next();switch(op){
    case "C"->{var l=new Level();l.first=new BlockPos(0,0,0);l.firstAxis=Axis.values()[in.nextInt()];l.secondAxis=Axis.values()[in.nextInt()];l.second=new BlockPos(in.nextInt(),in.nextInt(),in.nextInt());l.firstRpm=in.nextFloat();l.secondRpm=in.nextFloat();l.flags=in.nextInt();l.space=in.nextInt();maximum=in.nextInt();
     boolean valid=validateAxis(l,l.first)&&validateAxis(l,l.second)&&canConnect(l,l.first,l.second);out.append(valid?1:0);
     if(valid){var slope=getSlopeBetween(l.first,l.second);var facing=getFacingFromTo(l.first,l.second);if(l.second.x==l.second.z)facing=Direction.get(facing.getAxisDirection(),l.firstAxis==Axis.X?Axis.Z:Axis.X);var chain=getBeltChainBetween(l.first,l.second,slope,facing);if(l.firstAxis==Axis.Y)slope=BeltSlope.SIDEWAYS;out.append(' ').append(slope.ordinal()).append(' ').append(facing.ordinal()).append(' ').append(chain.size());}
    }
    case "E"->{var b=new BeltBlockEntity(in.nextFloat(),Direction.values()[in.nextInt()],BeltSlope.values()[in.nextInt()],6);var v=b.getBeltChainDirection();double speed=Math.max(Math.abs(b.getBeltMovementSpeed()),1/8f);out.append(Double.doubleToRawLongBits(v.x()*speed)).append(' ').append(Double.doubleToRawLongBits(v.y()*speed+1/8f)).append(' ').append(Double.doubleToRawLongBits(v.z()*speed));}
    case "M"->{var b=new BeltBlockEntity(in.nextFloat(),Direction.values()[in.nextInt()],BeltSlope.HORIZONTAL,5);out.append(Float.floatToRawIntBits(b.getBeltMovementSpeed())).append(' ').append(Float.floatToRawIntBits(b.getDirectionAwareBeltMovementSpeed())).append(' ').append(b.getMovementFacing().ordinal());}
    case "I"->{var b=new BeltBlockEntity(in.nextFloat(),Direction.values()[in.nextInt()],BeltSlope.HORIZONTAL,5);var inv=new Inventory(b);inv.beltMovementPositive=in.nextInt()!=0;int segment=in.nextInt();var side=Direction.values()[in.nextInt()];var item=new TransportedItemStack();item.beltPosition=in.nextFloat();item.insertedAt=in.nextInt();item.insertedFrom=Direction.values()[in.nextInt()];inv.items.add(item);out.append(inv.canInsertAtFromSide(segment,side)?1:0);}
    case "G"->{var inv=new Inventory(new BeltBlockEntity(16,Direction.SOUTH,BeltSlope.HORIZONTAL,5));int segment=in.nextInt(),n=in.nextInt();for(int i=0;i<n;i++){var item=new TransportedItemStack();item.beltPosition=in.nextFloat();item.stack=new ItemStack(i,1);inv.items.add(item);}var stack=inv.getStackAtOffset(segment);out.append(stack==null?-1:stack.stack.key);}
    case "T"->{var b=new BeltBlockEntity(in.nextFloat(),Direction.values()[in.nextInt()],BeltSlope.values()[in.nextInt()],in.nextInt());var inv=new Inventory(b);inv.beltMovementPositive=in.nextInt()!=0;inv.end=in.nextInt();int ticks=in.nextInt();b.level.room=in.nextInt();inv.processorSegment=in.nextInt();inv.processorMode=in.nextInt();int n=in.nextInt();
     for(int i=0;i<n;i++){var item=new TransportedItemStack();item.stack=new ItemStack(i,in.nextInt());item.beltPosition=in.nextFloat();item.angle=in.nextInt();item.sideOffset=in.nextFloat();item.locked=in.nextInt()!=0;item.lockedExternally=in.nextInt()!=0;inv.items.add(item);}
     for(int i=0;i<ticks;i++)inv.tick();out.append(b.level.room).append(' ').append(inv.items.size()).append(' ').append(inv.ejected.size());
     for(var item:inv.items)out.append(' ').append(item.stack.key).append(':').append(item.stack.count).append(':').append(Float.floatToRawIntBits(item.beltPosition)).append(':').append(Float.floatToRawIntBits(item.sideOffset)).append(':').append(item.locked?1:0).append(':').append(item.lockedExternally?1:0);
     for(var item:inv.ejected)out.append(" E").append(item.stack.key).append(':').append(item.stack.count);
    }
    default->throw new IllegalArgumentException(op);
   }out.append('\n');
  }System.out.print(out);
 }
}'''


RUST = r'''pub use create_horizon_core::{fan,kinetics,placement};
#[path="@@TRANSPORT@@"] mod transport;
use transport::*;
use std::io::{self,BufRead};
fn dir(n:usize)->placement::Direction {placement::Direction::ALL[n]}
fn axis(n:usize)->kinetics::Axis {[kinetics::Axis::X,kinetics::Axis::Y,kinetics::Axis::Z][n]}
fn slope(n:usize)->Slope {[Slope::Horizontal,Slope::Upward,Slope::Downward,Slope::Vertical,Slope::Sideways][n]}
fn end(n:usize)->Ending {[Ending::Eject,Ending::Insert,Ending::Funnel,Ending::Blocked][n]}
struct Effects {end:Ending,room:u32,segment:i32,mode:u32}
impl Hooks<u32> for Effects {
 fn ending(&mut self,_:bool)->Ending {self.end}
 fn insert_end(&mut self,s:&Stack<u32>,_:placement::Direction)->Stack<u32>{let n=s.count.min(self.room);self.room-=n;Stack {count:s.count-n,..s.clone()}}
 fn processor(&mut self,segment:i32)->Option<bool>{Some(self.mode!=0&&segment==self.segment)}
 fn received(&mut self,_:&mut Transported<u32>,_:i32)->ProcessingResult {match self.mode {1=>ProcessingResult::Hold,3=>ProcessingResult::Remove,_=>ProcessingResult::Pass}}
 fn held(&mut self,t:&mut Transported<u32>,s:i32)->ProcessingResult {self.received(t,s)}
}
fn main(){for line in io::stdin().lock().lines(){let line=line.unwrap();let v=line.split_whitespace().collect::<Vec<_>>();let mut i=1;macro_rules! n {($t:ty)=>{{let x=v[i].parse::<$t>().unwrap();i+=1;x}}}
 match v[0] {
 "C"=>{let a=axis(n!(usize));let b=axis(n!(usize));let pos=[n!(i32),n!(i32),n!(i32)];let ar=n!(f32);let br=n!(f32);let flags=n!(u8);let space=n!(u8);let max=n!(f64);let first=Pulley {pos:[0;3],axis:a,rpm:ar,loaded:flags&1==0,shaft:flags&4==0};let second=Pulley {pos,axis:b,rpm:br,loaded:flags&2==0,shaft:flags&8==0};
 let chain=connect(first,second,max,|_|match space {0=>Space::Replaceable,1=>Space::Shaft(a),2=>Space::Shaft(axis((a.index()+1)%3)),_=>Space::Blocked});match chain {Ok(c)=>println!("1 {} {} {}",c.slope as u8,c.facing as u8,c.segments.len()),Err(_)=>println!("0")}}
 "E"=>{let rpm=n!(f32);let facing=dir(n!(usize));let slope=slope(n!(usize));let v=Belt {rpm,facing,slope,length:6}.ejection_velocity();println!("{} {} {}",v[0].to_bits() as i64,v[1].to_bits() as i64,v[2].to_bits() as i64);}
 "M"=>{let rpm=n!(f32);let facing=dir(n!(usize));println!("{} {} {}",movement_speed(rpm).to_bits() as i32,direction_aware_speed(rpm,facing).to_bits() as i32,movement_facing(rpm,facing) as u8);}
 "I"=>{let rpm=n!(f32);let facing=dir(n!(usize));let positive=n!(u8)!=0;let segment=n!(i32);let side=dir(n!(usize));let position=n!(f32);let inserted_at=n!(i32);let inserted_from=dir(n!(usize));let mut item=Transported::new(Stack {payload:0u32,count:1,maximum:64},180);item.position=position;item.inserted_at=inserted_at;item.inserted_from=inserted_from;let inv=Inventory {items:vec![item],positive,..Default::default()};println!("{}",u8::from(inv.can_insert(Belt {rpm,facing,slope:Slope::Horizontal,length:5},segment,side)));}
 "G"=>{let segment=n!(i32);let count=n!(usize);let mut inv=Inventory::default();for key in 0..count {let mut item=Transported::new(Stack {payload:key as u32,count:1,maximum:64},180);item.position=n!(f32);inv.items.push(item);}println!("{}",inv.stack_at(segment).map_or(-1,|i|inv.items[i].stack.payload as i32));}
 "T"=>{let rpm=n!(f32);let facing=dir(n!(usize));let slope=slope(n!(usize));let length=n!(i32);let positive=n!(u8)!=0;let end=end(n!(usize));let ticks=n!(usize);let room=n!(u32);let segment=n!(i32);let mode=n!(u32);let count=n!(usize);let mut inv=Inventory {positive,..Default::default()};
 for key in 0..count {let count=n!(u32);let position=n!(f32);let angle=n!(i32);let offset=n!(f32);let locked=n!(u8)!=0;let externally_locked=n!(u8)!=0;let mut item=Transported::new(Stack {payload:key as u32,count,maximum:64},angle);item.position=position;item.side_offset=offset;item.locked=locked;item.externally_locked=externally_locked;inv.items.push(item);}
 let mut hooks=Effects {end,room,segment,mode};let mut ejected=Vec::new();for _ in 0..ticks {ejected.extend(inv.tick(Belt {rpm,facing,slope,length},&mut hooks).ejected);}
 print!("{} {} {}",hooks.room,inv.items.len(),ejected.len());for t in &inv.items {print!(" {}:{}:{}:{}:{}:{}",t.stack.payload,t.stack.count,t.position.to_bits() as i32,t.side_offset.to_bits() as i32,u8::from(t.locked),u8::from(t.externally_locked));}for t in &ejected {print!(" E{}:{}",t.stack.payload,t.stack.count);}println!();}
 _=>panic!("bad probe")};let _=i;
}}
'''


def main():
    java, javac = shutil.which('java'), shutil.which('javac')
    if not java or not javac:
        raise SystemExit('A JDK is required for the source-method transport oracle')
    work = ROOT / '.local/transport-oracle'
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run([javac, '-d', str(work), str(ROOT / 'tools/java/ExportMethod.java')], check=True)
    template = JAVA
    base = 'src/main/java/com/simibubi/create/content/kinetics/belt/'
    specs = [
        ('item/BeltConnectorItem.java', [('VALIDATE', 'validateAxis'), ('CONNECT', 'canConnect'), ('SLOPE', 'getSlopeBetween'), ('FACING', 'getFacingFromTo'), ('CHAIN', 'getBeltChainBetween')]),
        ('BeltBlockEntity.java', [('SPEED', 'getBeltMovementSpeed'), ('AWARE', 'getDirectionAwareBeltMovementSpeed'), ('MOVEMENT_FACING', 'getMovementFacing'), ('CHAIN_DIRECTION', 'getBeltChainDirection'), ('MOVEMENT_DIRECTION', 'getMovementDirection')]),
        ('transport/TransportedItemStack.java', [('OFFSET', 'getTargetSideOffset'), ('COMPARE', 'compareTo')]),
        ('transport/BeltInventory.java', [('INSERT', 'insert'), ('BLOCKING', 'isBlocking'), ('CAN_INSERT', 'canInsertAtFromSide'), ('GET_STACK', 'getStackAtOffset'), ('PROCESS', 'handleBeltProcessingAndCheckIfRemoved'), ('TICK', 'tick')]),
    ]
    for filename, methods in specs:
        source = work / Path(filename).name
        source.write_bytes(subprocess.check_output(['git', 'show', PINS['create_revision'] + ':' + base + filename], cwd=CREATE))
        for marker, method in methods:
            if method == 'getMovementDirection':
                original = source.read_text()
                renamed = original.replace('public Vec3i getMovementDirection(boolean firstHalf)', 'public Vec3i unusedMovementDirectionOverload(boolean firstHalf)')
                assert renamed != original
                source.write_text(renamed)
            body = subprocess.check_output([java, '-cp', str(work), 'ExportMethod', str(source), method], text=True)
            template = template.replace('@@' + marker + '@@', body)
    source = work / 'TransportOracle.java'
    source.write_text(template)
    subprocess.run([javac, '-d', str(work), str(source)], check=True)
    probe = work / 'probe'
    (probe / 'src').mkdir(parents=True, exist_ok=True)
    (probe / 'Cargo.toml').write_text('[package]\nname="transport-oracle-probe"\nversion="0.0.0"\nedition="2024"\n[workspace]\n[dependencies]\ncreate-horizon-core={path=' + json.dumps(str(ROOT)) + '}\n')
    (probe / 'src/main.rs').write_text(RUST.replace('@@TRANSPORT@@', str(ROOT / 'mixins/create/engine/src/core/transport.rs')))
    cargo('build', '--offline', '--manifest-path', probe / 'Cargo.toml', '--target-dir', work / 'target')
    cargo('test', '--offline', '--manifest-path', probe / 'Cargo.toml', '--target-dir', work / 'target')
    cases = []
    for axis, other, x, y, z in itertools.product(range(3), range(3), range(-5, 6), range(-5, 6), range(-5, 6)):
        cases.append(f'C {axis} {other} {x} {y} {z} 16 16 0 0 20')
    for axis, x, y, z, r1, r2, flags, space in itertools.product(range(3), [0, 3, 14, 19, 20], [0, 3, 14, 19, 20], [0], [0, 16, -32], [0, 64, -16], [0, 1, 2, 4, 8], range(4)):
        cases.append(f'C {axis} {axis} {x} {y} {z} {r1} {r2} {flags} {space} 20')
    for rpm, facing in itertools.product([x / 8 for x in range(-4096, 4097)], range(2, 6)):
        cases.append(f'M {rpm} {facing}')
    for rpm, facing, slope in itertools.product([0.0, -0.0, -256, -0.5, 16, 128, 256, 8192], range(2, 6), range(5)):
        cases.append(f'E {rpm} {facing} {slope}')
    rng = random.Random(3955)
    for _ in range(5000):
        rpm, facing, positive, segment, side = rng.choice([0, -256, 16, 256]), rng.randrange(2, 6), rng.randrange(2), rng.randrange(5), rng.randrange(6)
        position, inserted, origin = rng.randrange(-8, 88) / 16, rng.randrange(5), rng.randrange(6)
        cases.append(f'I {rpm} {facing} {positive} {segment} {side} {position} {inserted} {origin}')
    for segment, p in itertools.product(range(5), [-.001, 0, .001, .5, 1, 1.001, 2, 4.999, 5]):
        cases.append(f'G {segment} 3 {p} 1.0 2.0')
    for _ in range(1800):
        rpm, facing, slope, length, positive, ending = rng.choice([0, -256, -.5, 16, 128, 256, 8192]), rng.randrange(2, 6), rng.randrange(3), rng.choice([2, 3, 5]), rng.randrange(2), rng.randrange(4)
        ticks, room, pseg, pmode = rng.choice([1, 2, 7, 35]), rng.choice([0, 1, 16, 64]), rng.randrange(length), rng.randrange(4)
        positions = sorted([rng.randrange(length * 16 + 1) / 16 for _ in range(rng.randrange(1, 5))], reverse=bool(positive))
        items = ' '.join(f'{rng.choice([0, 1, 16, 64])} {pos} {rng.randrange(360)} {rng.randrange(-8, 9) / 8} {rng.randrange(2)} {rng.randrange(2)}' for pos in positions)
        cases.append(f'T {rpm} {facing} {slope} {length} {positive} {ending} {ticks} {room} {pseg} {pmode} {len(positions)} {items}')
    data = '\n'.join(cases) + '\n'
    expected = subprocess.check_output([java, '-cp', str(work), 'TransportOracle'], input=data, text=True).splitlines()
    actual = subprocess.check_output([str(work / 'target/debug/transport-oracle-probe')], input=data, text=True).splitlines()
    assert len(cases) == len(expected) == len(actual)
    for case, original, port in zip(cases, expected, actual):
        assert original == port, {'case': case, 'java': original, 'rust': port}
    result = {'passed': len(cases), 'reference': PINS['create_revision'],
              'scope': '18 unchanged AST-exported belt geometry/motion/inventory methods; server-only, explicit world/processing/endpoint contexts; no funnels/tunnels/crushers/native/render check'}
    result['source_shapes'] = shape_checks()
    (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
