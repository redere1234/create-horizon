#!/usr/bin/env python3
"""Source-method fan entity oracle and disposable native integration checks.

The oracle extracts unchanged Java affectEntity/tickAffectedEntities bodies.
Its contexts model vanilla entity facts; it does not run the entire Java mod.
Native checks require a control callback from the isolated smoke driver.
"""
import itertools
import json
from pathlib import Path
import random
import re
import shutil
import subprocess

from common import CREATE, PINS, ROOT, environment


EXPORTER = r'''
import com.sun.source.tree.*;
import com.sun.source.util.*;
import javax.tools.*;
import java.nio.file.*;
import java.util.*;
public class ExportEntityMethod {
 public static void main(String[] args)throws Exception {
  var compiler=ToolProvider.getSystemJavaCompiler();
  try(var files=compiler.getStandardFileManager(null,null,null)) {
   var task=(JavacTask)compiler.getTask(null,files,null,List.of("-proc:none"),null,files.getJavaFileObjects(args[0]));
   var tree=task.parse().iterator().next();var positions=Trees.instance(task).getSourcePositions();
   var source=Files.readString(Path.of(args[0]));var bodies=new ArrayList<String>();
   new TreeScanner<Void,String>() {
    public Void visitClass(ClassTree type,String parent) {return super.visitClass(type,type.getSimpleName().toString());}
    public Void visitMethod(MethodTree method,String owner) {
     if(args[1].equals(owner) && method.getName().contentEquals(args[2]) && method.getBody()!=null) {
      var body=method.getBody();bodies.add(source.substring((int)positions.getStartPosition(tree,body),(int)positions.getEndPosition(tree,body)));
     }return super.visitMethod(method,owner);
    }
   }.scan(tree,"");
   if(bodies.size()!=1)throw new IllegalStateException("Expected one method: "+Arrays.toString(args));
   System.out.print(bodies.getFirst());
  }
 }
}
'''

JAVA = r'''
import java.util.*;
public class FanEntityOracle {
 static final class Vec3 {
  double x,y,z;Vec3(double a,double b,double c){x=a;y=b;z=c;}
  static final Vec3 ZERO=new Vec3(0,0,0);
  Vec3 add(Vec3 v){return new Vec3(x+v.x,y+v.y,z+v.z);}
  Vec3 add(double a,double b,double c){return new Vec3(x+a,y+b,z+c);}
  Vec3 scale(double s){return new Vec3(x*s,y*s,z*s);}
  Vec3 multiply(double a,double b,double c){return new Vec3(x*a,y*b,z*c);}
  Vec3 normalize(){return scale(1/Math.sqrt(x*x+y*y+z*z));}
  double distanceTo(Vec3 b){return Math.sqrt(Math.pow(x-b.x,2)+Math.pow(y-b.y,2)+Math.pow(z-b.z,2));}
 }
 static final class Vec3i {
  int x,y,z;Vec3i(int a,int b,int c){x=a;y=b;z=c;}
  int getX(){return x;}int getY(){return y;}int getZ(){return z;}
 }
 static final class Direction {
  Vec3i normal;Direction(int a,int b,int c){normal=new Vec3i(a,b,c);}
  Vec3i getNormal(){return normal;}
  Direction getOpposite(){return new Direction(-normal.x,-normal.y,-normal.z);}
 }
 static final class VecHelper {
  static Vec3 offsetRandomly(Vec3 p,Random r,double range){return p;}
  static Vec3 getCenterOf(Vec3 p){return p;}
  static double alignedDistanceToFace(Vec3 p,Vec3 origin,Direction d){return 0;}
 }
 static final class Mth {
  static double clamp(double v,double min,double max){return Math.max(min,Math.min(max,v));}
  static float clamp(float v,float min,float max){return Math.max(min,Math.min(max,v));}
 }
 static final class Bounds {boolean intersects(Bounds b){return true;}}
 static class CompoundTag {
  Map<String,Integer> ints=new HashMap<>();
  int getInt(String k){return ints.getOrDefault(k,0);}void putInt(String k,int v){ints.put(k,v);}
  void remove(String k){}
 }
 static class Entity {
  boolean immune,onFire,cleared,alive=true,sneak,creative,flying,discarded;
  int ignite,above=9;float damage;String damageId="-";
  Vec3 pos=new Vec3(1,0,0),velocity=Vec3.ZERO;float fallDistance=7;
  Object type=new Object();CompoundTag nbt=new CompoundTag();
  Map<String,MobEffectInstance> effects=new HashMap<>();
  boolean fireImmune(){return immune;}void igniteForSeconds(int seconds){ignite=seconds*20;}
  void hurt(String id,float amount){damageId=id;damage=amount;}
  boolean isOnFire(){return onFire&&!immune;}void clearFire(){cleared=true;onFire=false;}
  Object getType(){return type;}Vec3 blockPosition(){return pos;}
  Vec3 getPosition(int a){return pos;}Vec3 position(){return pos;}
  boolean isAlive(){return alive;}Bounds getBoundingBox(){return new Bounds();}
  boolean isShiftKeyDown(){return sneak;}Vec3 getDeltaMovement(){return velocity;}
  void setDeltaMovement(Vec3 v){velocity=v;}
  void discard(){discarded=true;}Object registryAccess(){return null;}
 }
 static class LivingEntity extends Entity {void addEffect(MobEffectInstance effect){effects.put(effect.id,effect);}}
 static class Horse extends LivingEntity {
  CompoundTag getPersistentData(){return nbt;}
  ItemStack getBodyArmorItem(){return new ItemStack();}void spawnAtLocation(ItemStack item){}
  CompoundTag saveWithoutId(CompoundTag tag){return tag;}
 }
 static class EnderMan extends LivingEntity {}
 static class SkeletonHorse extends LivingEntity {void deserializeNBT(Object r,CompoundTag t){}void setPos(Vec3 p){pos=p;}}
 static class ItemStack {boolean isEmpty(){return true;}}
 static class ItemEntity extends Entity {}
 static class ServerPlayer extends Entity {Connection connection=new Connection();}
 static class Connection {int aboveGroundTickCount=9;}
 static class MobEffectInstance {
  String id;int ticks,amp;boolean ambient,particles;
  MobEffectInstance(String i,int t,int a,boolean b,boolean p){id=i;ticks=t;amp=a;ambient=b;particles=p;}
 }
 static class MobEffects {static final String BLINDNESS="blindness",MOVEMENT_SLOWDOWN="slowness";}
 static class EntityType {
  static final Object SNOW_GOLEM=new Object(),BLAZE=new Object();
  static final EntityType SKELETON_HORSE=new EntityType();
  SkeletonHorse create(Level level){return new SkeletonHorse();}
 }
 static class CreateDamageSources {static String fanFire(Level l){return "create:fan_fire";}static String fanLava(Level l){return "create:fan_lava";}}
 static class DamageSources {String drown(){return "minecraft:drown";}}
 static class Level {
  boolean isClientSide,converted;Random random=new Random(1);float soulPitch=-1;
  DamageSources damageSources(){return new DamageSources();}
  void addFreshEntity(Entity entity){converted=true;}
  void playSound(Object who,Vec3 at,String sound,Object source,float volume,float pitch){if(sound.equals("soul"))soulPitch=pitch;}
  void addParticle(Object kind,double x,double y,double z,double vx,double vy,double vz){}
 }
 static class SoundHolder {String value(){return "soul";}}
 static class SoundEvents {static final SoundHolder SOUL_ESCAPE=new SoundHolder();static final String GENERIC_EXTINGUISH_FIRE="extinguish";}
 static class SoundSource {static final Object NEUTRAL=new Object();}
 static class ParticleTypes {static final Object SOUL_FIRE_FLAME=new Object(),LARGE_SMOKE=new Object();}
 static class BlastingType {void affectEntity(Entity entity,Level level) @@BLAST@@}
 static class HauntingType {void affectEntity(Entity entity,Level level) @@HAUNT@@}
 static class SmokingType {void affectEntity(Entity entity,Level level) @@SMOKE@@}
 static class SplashingType {void affectEntity(Entity entity,Level level) @@SPLASH@@}
 static class FanProcessingType {void spawnProcessingParticles(Level l,Vec3 p){}void affectEntity(Entity e,Level l){}}
 static class FanProcessing {static boolean canProcess(ItemEntity e,FanProcessingType t){return false;}static boolean applyProcessing(ItemEntity e,FanProcessingType t){return false;}}
 static class AllAdvancements {static final int FAN_PROCESSING=1;}
 static class Source {float rpm;Vec3 getAirCurrentPos(){return Vec3.ZERO;}float getSpeed(){return rpm;}}
 static class EncasedFanBlockEntity extends Source {void award(int a){}}
 static class CatnipServices {static final Platform PLATFORM=new Platform();}
 static class Platform {Env getEnv(){return new Env();}}
 static class Env {boolean isClient(){return false;}}
 static class AirCurrent {
  List<Entity> caughtEntities=new ArrayList<>();Bounds bounds=new Bounds();
  Direction direction;boolean pushing=true;float maxDistance;Source source=new Source();
  FanProcessingType getTypeAt(float offset){return null;}
  static boolean isPlayerCreativeFlying(Entity e){return e.creative&&e.flying;}
  static class Client {static void enableClientPlayerSound(Entity e,float volume){}}
  void tickAffectedEntities(Level world) @@MOTION@@
 }
 static String status(Entity e,String id){var s=e.effects.get(id);return s==null?"0 0 false false":s.ticks+" "+s.amp+" "+s.ambient+" "+s.particles;}
 public static void main(String[] args) {
  var scanner=new Scanner(System.in);
  while(scanner.hasNextLine()){
   var a=scanner.nextLine().split(" ");
   if(a[0].equals("E")){
    int kind=Integer.parseInt(a[1]),category=Integer.parseInt(a[2]),progress=Integer.parseInt(a[5]);
    Entity e=switch(category){case 1->new LivingEntity();case 2->new Horse();case 3->new EnderMan();default->new Entity();};
    if(category==4){e=new LivingEntity();e.type=EntityType.SNOW_GOLEM;}
    if(category==5){e=new LivingEntity();e.type=EntityType.BLAZE;}
    e.immune=a[3].equals("1");e.onFire=a[4].equals("1");e.nbt.putInt("CreateHaunting",progress);var l=new Level();
    switch(kind){case 0->new BlastingType().affectEntity(e,l);case 1->new HauntingType().affectEntity(e,l);case 2->new SmokingType().affectEntity(e,l);case 3->new SplashingType().affectEntity(e,l);}
    System.out.println(e.ignite+" "+e.damageId+" "+e.damage+" "+status(e,"blindness")+" "+status(e,"slowness")+" "+e.cleared+" "+e.nbt.getInt("CreateHaunting")+" "+l.soulPitch+" "+l.converted);
   }else{
    var c=new AirCurrent();var e=new ServerPlayer();c.source.rpm=Float.parseFloat(a[1]);c.maxDistance=Float.parseFloat(a[2]);
    int axis=Integer.parseInt(a[3]),sign=Integer.parseInt(a[4]);int[] d=new int[3];d[axis]=sign;c.direction=new Direction(d[0],d[1],d[2]);
    e.sneak=a[5].equals("1");e.creative=a[6].equals("1");e.flying=a[7].equals("1");e.alive=a[9].equals("1");
    e.pos=new Vec3(Double.parseDouble(a[10]),Double.parseDouble(a[11]),Double.parseDouble(a[12]));e.velocity=new Vec3(Double.parseDouble(a[13]),Double.parseDouble(a[14]),Double.parseDouble(a[15]));
    if(!a[8].equals("1"))c.caughtEntities.add(e);c.tickAffectedEntities(new Level());
    System.out.println(!c.caughtEntities.isEmpty()+" "+e.velocity.x+" "+e.velocity.y+" "+e.velocity.z+" "+e.fallDistance+" "+e.connection.aboveGroundTickCount);
   }
  }
 }
}
'''.replace('Object registryAccess(){return null;}', 'Object registryAccess(){return null;} DamageSources damageSources(){return new DamageSources();}')

RUST = r'''
use create_horizon_core::{fan::ProcessingType as T,fan_entities::{self as f,Facts,Horse}};
use std::io::{self,BufRead};
fn status(s:Option<f::Status>)->String {match s{Some(s)=>format!("{} {} {} {}",s.ticks,s.amplifier,s.ambient,s.particles),None=>"0 0 false false".into()}}
fn main(){for line in io::stdin().lock().lines(){let line=line.unwrap();let a:Vec<_>=line.split_whitespace().collect();
 if a[0]=="E"{let category:i32=a[2].parse().unwrap();let immune=a[3]=="1";let progress:i32=a[5].parse().unwrap();let facts=Facts{living:category!=0,horse:category==2,fire_immune:immune,on_fire:a[4]=="1"&&!immune,water_sensitive:category>=3};
 let e=f::effects([T::Blasting,T::Haunting,T::Smoking,T::Splashing][a[1].parse::<usize>().unwrap()],facts,progress);
 let (id,amount)=e.damage.map(|(id,amount)|(id.id(),amount)).unwrap_or(("-",0.0));
 let (p,pitch,convert)=match e.horse{Horse::None=>(progress,-1.0,false),Horse::Progress{value,sound_pitch}=>(value,sound_pitch.unwrap_or(-1.0),false),Horse::Convert=>(progress,-1.0,true)};
 println!("{} {} {} {} {} {} {} {} {}",e.ignite_ticks,id,amount,status(e.statuses[0]),status(e.statuses[1]),e.extinguish,p,pitch,convert);
 }else{let n=|i:usize|a[i].parse::<f64>().unwrap();let yes=f::eligible(a[9]=="1",a[8]=="1",a[6]=="1",a[7]=="1");let mut d=[0;3];d[a[3].parse::<usize>().unwrap()]=a[4].parse().unwrap();let before=[n(13),n(14),n(15)];let v=if yes{f::movement(before,[n(10),n(11),n(12)],[0.0;3],d,n(1)as f32,n(2)as f32,a[5]=="1")}else{before};println!("{} {} {} {} {} {}",yes,v[0],v[1],v[2],if yes{0}else{7},if yes{0}else{9});}
}}
'''


def oracle():
    java, javac = shutil.which('java'), shutil.which('javac')
    if not java or not javac:
        raise SystemExit('A JDK is required for the Java source oracle')
    work = ROOT / '.local/fan-entity-oracle'
    work.mkdir(parents=True, exist_ok=True)
    exporter = work / 'ExportEntityMethod.java'
    exporter.write_text(EXPORTER)
    subprocess.run([javac, '-d', str(work), str(exporter)], check=True)
    template = JAVA
    for marker, path, owner, method in [
        ('BLAST', 'fan/processing/AllFanProcessingTypes', 'BlastingType', 'affectEntity'),
        ('HAUNT', 'fan/processing/AllFanProcessingTypes', 'HauntingType', 'affectEntity'),
        ('SMOKE', 'fan/processing/AllFanProcessingTypes', 'SmokingType', 'affectEntity'),
        ('SPLASH', 'fan/processing/AllFanProcessingTypes', 'SplashingType', 'affectEntity'),
        ('MOTION', 'fan/AirCurrent', 'AirCurrent', 'tickAffectedEntities'),
    ]:
        source = work / (path.rsplit('/', 1)[-1] + '.java')
        source.write_bytes(subprocess.check_output(['git', 'show', PINS['create_revision'] +
            ':src/main/java/com/simibubi/create/content/kinetics/' + path + '.java'], cwd=CREATE))
        body = subprocess.check_output([java, '-cp', str(work), 'ExportEntityMethod',
                                        str(source), owner, method], text=True)
        template = template.replace('@@' + marker + '@@', body)
    source = work / 'FanEntityOracle.java'
    source.write_text(template)
    subprocess.run([javac, '-d', str(work), str(source)], check=True)
    probe = work / 'probe.rs'
    probe.write_text(RUST)
    # This portable crate has no dependencies. Compile its actual current
    # sources directly so concurrent package/version work cannot modify a lock.
    library = work / 'libcreate_horizon_core.rlib'
    subprocess.run([str(ROOT / '.tools/rust/bin/rustc'), '--edition=2024',
                    '--crate-type=lib', '--crate-name=create_horizon_core',
                    str(ROOT / 'mixins/create/engine/src/lib.rs'), '-o', str(library)],
                   env=environment(), check=True)
    subprocess.run([str(ROOT / '.tools/rust/bin/rustc'), '--edition=2024', str(probe),
                    '--extern', 'create_horizon_core=' + str(library), '-o', str(work / 'probe')],
                   env=environment(), check=True)
    cases = ['E ' + ' '.join(map(str, values)) for values in itertools.product(
        range(4), range(6), range(2), range(2), [-20, -10, -1, *range(0, 111), 150])]
    rng = random.Random(0xCFE06)
    for rpm, axis, sign, sneak, creative, flying, spectator, alive in itertools.product(
            [1, 16, 32, 128, 256, 512], range(3), [-1, 1], range(2), range(2), range(2), range(2), range(2)):
        point = [rng.uniform(-30, 30) for _ in range(3)]
        velocity = [rng.uniform(-8, 8) for _ in range(3)]
        cases.append('M ' + ' '.join(map(str, [rpm, rng.uniform(.25, 20), axis, sign,
                     sneak, creative, flying, spectator, alive, *point, *velocity])))
    stdin = '\n'.join(cases) + '\n'
    expected = subprocess.check_output([java, '-cp', str(work), 'FanEntityOracle'], input=stdin, text=True).splitlines()
    actual = subprocess.check_output([str(work / 'probe')], input=stdin, text=True).splitlines()
    assert len(expected) == len(actual) == len(cases)
    for case, want, got in zip(cases, expected, actual):
        left, right = want.split(), got.split()
        assert len(left) == len(right), (case, want, got)
        for a, b in zip(left, right):
            try:
                equal = abs(float(a) - float(b)) <= 1e-6
            except ValueError:
                equal = a == b
            assert equal, (case, want, got)
    result = {'passed': len(cases), 'reference': PINS['create_revision'],
              'scope': 'unchanged AST Java four medium server entity effects and AirCurrent motion; entity/level stubs, not a full-client comparison'}
    (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
    return result


def run(call, graphics=False, log=None, scratch=None):
    """Run only on a disposable paired native client/server smoke world."""
    origin = 200
    selector = '@e[tag=audit06_fan,limit=1]'

    def command(text):
        return call('command', text)

    def step(ticks):
        command(f'tick step {ticks}')
        call('wait', ticks + 4)

    def text(target=selector, path=''):
        return ' '.join(command('data get entity ' + target + (' ' + path if path else ''))['chat'])

    def number(key, target=selector):
        value = text(target)
        found = re.search(r'\b' + re.escape(key) + r':\s*(-?[\d.]+(?:[eE][+-]?\d+)?)', value)
        assert found, (key, value)
        return float(found[1])

    def motion():
        value = text(path='Motion')
        found = re.search(r'\[([^]]+)\]', value)
        assert found, value
        return [float(v.strip().rstrip('dDfF')) for v in found[1].split(',')]

    def block(x, y, z, name):
        value=call('setblock', origin + x, y, z, name)
        assert value['block'].split('[',1)[0]==name.split('[',1)[0],('block write failed',name,value)
        return value

    def setup(kind=None, rpm=256):
        command('kill @e[tag=audit06_fan]')
        call('fill', origin - 3, 67, -3, origin + 8, 73, 4, 'minecraft:air')
        call('fill', origin - 3, 68, -3, origin + 8, 68, 4, 'minecraft:smooth_stone')
        command(f'tp @s {origin + 5.5} 69 3.5')
        # Trap mobs before the source flow limit, without exposing them to the
        # actual catalyst's contact damage or flowing lava/water.
        call('fill', origin + 6, 69, -2, origin + 6, 72, 2, 'minecraft:stone')
        if kind in ('blasting', 'splashing'):
            for x, y, z in [(1, 68, 0), (1, 70, 0), (1, 69, -1), (1, 69, 1)]:
                block(x, y, z, 'minecraft:glass')
            block(2, 69, 0, 'minecraft:iron_bars')
            block(1, 69, 0, 'minecraft:lava' if kind == 'blasting' else 'minecraft:water')
        elif kind:
            block(1, 69, 0, 'minecraft:soul_campfire[lit=true]' if kind == 'haunting'
                  else 'minecraft:campfire[lit=true]')
        block(-1, 69, 0, 'create:creative_motor[facing=east]')
        command(f'data merge block {origin - 1} 69 0 {{ScrollValue:{rpm}}}')

    def summon(kind='sheep', extra=''):
        command(f'summon minecraft:{kind} {origin + 3.5} 69 0.5 '
                '{Tags:["audit06_fan"],NoAI:1b,NoGravity:1b,Silent:1b' + extra + '}')
        # Place the fan last so its first source search sees this entity.
        block(0, 69, 0, 'create:encased_fan[facing=east]')

    command(f'tp @s {origin + 5.5} 70 3.5')
    command(f'forceload add {origin-16} -16 {origin+16} 16')
    call('wait-ready', 120)
    call('wait',40)
    command('gamemode creative')
    # Keep the later status sample deterministic: a well-fed player can
    # regenerate between the hurt record and this paired-client observation.
    command('gamerule minecraft:natural_health_regeneration false')
    command('tick freeze')
    try:
        setup(rpm=0)
        summon()
        step(8)
        assert abs(motion()[0]) < 1e-8, text()
        command(f'data merge block {origin - 1} 69 0 {{ScrollValue:256}}')
        step(1)
        assert motion()[0] > .01, text()
        command(f'data merge block {origin - 1} 69 0 {{ScrollValue:-256}}')
        step(2)
        assert motion()[0] < -.01, text()
        print('Fan entity native: stopped/current/reversed mob velocity uses real physics', flush=True)

        for medium, mob, expected, resist in [
            ('blasting', 'sheep', 4, False),
            ('smoking', 'sheep', 6, False),
            ('blasting', 'blaze', 20, False),
            ('blasting', 'sheep', 8, True),
            ('splashing', 'blaze', 18, False),
        ]:
            setup(medium)
            summon(mob)
            command(f'attribute {selector} minecraft:armor base set 20')
            if resist:
                command(f'effect give {selector} minecraft:fire_resistance 60 0 true')
            step(1)
            assert number('Health') == expected, (medium, mob, resist, text())
            if medium in ('smoking', 'blasting') and mob != 'blaze':
                assert number('Fire') > 0, text()
        print('Fan entity native: source fire/armor bypass, immune blaze, resistance and water-sensitive damage', flush=True)

        setup('haunting')
        summon()
        step(1)
        held = text()
        assert 'minecraft:blindness' in held and 'minecraft:slowness' in held, held
        assert number('Health') == 8, held

        setup('splashing')
        summon(extra=',Fire:100s')
        step(1)
        assert number('Fire') <= 0, text()
        print('Fan entity native: haunting applies both real status effects; splashing extinguishes', flush=True)

        setup('haunting')
        summon('horse', ',NeoForgeData:{CreateHaunting:99,audit06_sibling:601},'
               'CustomName:{text:"Fan horse"},equipment:{body:{id:"minecraft:iron_horse_armor",count:1}}')
        before = text(path='UUID')
        step(1)
        assert number('CreateHaunting') == 100, text()
        step(1)
        horse = text('@e[type=minecraft:skeleton_horse,tag=audit06_fan,limit=1]')
        assert 'audit06_sibling: 601' in horse, horse
        assert 'Fan horse' in horse and text('@e[type=minecraft:skeleton_horse,tag=audit06_fan,limit=1]',path='UUID') != before, horse
        command('kill @e[tag=audit06_fan]')
        print('Fan entity native: horse converts at101st exposure with fresh UUID and preserved persistent data/name', flush=True)

        # Both paired client/server run, even with the offscreen renderer. The
        # player force must be produced once on the local client, not twice.
        setup()
        block(0, 69, 0, 'create:encased_fan[facing=east]')
        speeds = []
        def first_player_motion():
            # Source acquisition can take six ticks. Sample the first moving
            # tick, before the standing player reaches the trap wall. Measure
            # displacement: frozen stepping leaves extra real client ticks to
            # apply normal drag before a control status reply is observed.
            for _ in range(9):
                before=call('status')['player']['position'][0]
                step(1)
                speed=call('status')['player']['position'][0]-before
                if speed>1e-7:return speed
            raise AssertionError(('player never acquired by current',call('status')['player']))
        for crouch in (False, True):
            command('gamemode survival')
            command('gamemode creative')
            command(f'tp @s {origin + 3.5} 69 0.5')
            if crouch:
                call('key', 'shift', 'down')
            speeds.append(first_player_motion())
            call('key', 'shift', 'up')
        assert speeds[0] > .01 and 0 < speeds[1] < speeds[0] * .5, speeds
        command('gamemode spectator')
        command(f'tp @s {origin + 3.5} 69 0.5')
        step(8)
        assert abs(call('status')['player']['velocity'][0]) < 1e-6
        # GameType keeps spectator flight when entering creative in the air.
        # A gap avoids ServerPlayer.setGameMode's intentional near-ground
        # landing; no timing-sensitive synthetic double-tap is required.
        block(3,68,0,'minecraft:air')
        command('gamemode creative')
        assert re.search(r'\b1b\b', text('@s', 'abilities.flying')), text('@s', 'abilities')
        command(f'tp @s {origin + 3.5} 69 0.5')
        step(8)
        assert abs(call('status')['player']['velocity'][0]) < 1e-6
        print('Fan entity native: creative ground player moves, crouch weakens force, spectator/creative flight excluded', flush=True)

        # Normal server damage records must retain the actual custom damage ID.
        command('gamemode survival')
        setup('blasting')
        command('effect clear @s')
        step(21)
        command('effect give @s minecraft:instant_health 1 10 true')
        command('item replace entity @s armor.chest with minecraft:diamond_chestplate')
        block(0, 69, 0, 'create:encased_fan[facing=east]')
        command(f'tp @s {origin + 3.5} 69 0.5')
        step(8)
        damage = call('hurtlog')
        hits = [hurt for player in damage['players'] for hurt in player['hurts']
                if hurt['source'] == 'create:fan_lava' and hurt['hurt']]
        assert hits and hits[-1]['amount'] == 4 and hits[-1]['taken'] == 4, damage
        assert hits[-1]['health'] == 16 and hits[-1]['armor'] == 0, damage
        assert call('status')['player']['health'] == 16, call('status')['player']
        print('Fan entity native: paired player takes armor-bypassing source-ID damage through normal hurt path', flush=True)
    finally:
        call('key', 'shift', 'up')
        call('key', 'space', 'up')
        command('gamemode creative')
        command(f'tp @s {origin + 5.5} 69 3.5')
        command('tick unfreeze')
    return {'passed': True, 'scope': 'paired client/server player and mob flow, crouch/flight gates, native hazard damage/effects, horse conversion and persistent data'}


if __name__ == '__main__':
    oracle()
