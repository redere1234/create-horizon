#!/usr/bin/env python3
"""Compare Create particle controllers to unchanged pinned Java method bodies.

Vanilla base-particle construction/rendering is intentionally outside this
isolated oracle. Catnip color/rotation/offset helpers reproduce the bytecode of
the supported player's ponder1.0.82 dependency; no textures/JARs are published.
"""
import itertools
import json
import random
import shutil
import subprocess

from common import CREATE, PINS, ROOT, environment
from fan_entity_checks import EXPORTER, JAVA as ENTITY_JAVA


JAVA = r'''
import java.util.*;
public class ParticleOracle {
 static int time;
 enum Axis {X,Y,Z;boolean isHorizontal(){return this!=Y;}boolean isVertical(){return this==Y;}}
 static class Vec3 {
  double x,y,z;static final Vec3 ZERO=new Vec3(0,0,0);
  Vec3(double x,double y,double z){this.x=x;this.y=y;this.z=z;}
  static Vec3 atLowerCornerOf(Vec3 v){return v;}
  Vec3 add(Vec3 v){return new Vec3(x+v.x,y+v.y,z+v.z);}Vec3 add(double a,double b,double c){return add(new Vec3(a,b,c));}
  Vec3 subtract(Vec3 v){return new Vec3(x-v.x,y-v.y,z-v.z);}
  Vec3 scale(double v){return new Vec3(x*v,y*v,z*v);}Vec3 multiply(Vec3 v){return new Vec3(x*v.x,y*v.y,z*v.z);}
  Vec3 multiply(double a,double b,double c){return new Vec3(x*a,y*b,z*c);}double length(){return Math.sqrt(x*x+y*y+z*z);}
  Vec3 normalize(){double d=length();return d<1e-4?ZERO:new Vec3(x/d,y/d,z/d);}
 }
 static class RandomSource extends Random {RandomSource(long seed){super(seed);}}
 static class Mth {
  static final float[] SIN=new float[65536];static{for(int i=0;i<65536;i++)SIN[i]=(float)Math.sin((double)i*Math.PI*2/65536);}
  static float sin(float a){return SIN[(int)(a*10430.378f)&65535];}static float cos(float a){return SIN[(int)(a*10430.378f+16384f)&65535];}
  static double clamp(double v,double a,double b){return Math.min(Math.max(v,a),b);}
 }
 static class VecHelper {
  static Vec3 getCenterOf(Vec3 p){return p.add(.5,.5,.5);}
  static Vec3 offsetRandomly(Vec3 p,RandomSource r,float v){return p.add((r.nextFloat()-.5f)*2*v,(r.nextFloat()-.5f)*2*v,(r.nextFloat()-.5f)*2*v);}
  static Vec3 rotate(Vec3 p,double degrees,Axis a){if(degrees==0)return p;float r=(float)(degrees/180*Math.PI);double s=Mth.sin(r),c=Mth.cos(r);
   return switch(a){case X->new Vec3(p.x,p.y*c-p.z*s,p.z*c+p.y*s);case Y->new Vec3(p.x*c+p.z*s,p.y,p.z*c-p.x*s);case Z->new Vec3(p.x*c-p.y*s,p.y*c+p.x*s,p.z);};}
 }
 static class AnimationTickHolder {static int getTicks(Level l){return time;}}
 static class Color {
  static int mixColors(int a,int b,float f){int result=0;for(int s:new int[]{0,8,16,24}){int x=s==24?a>>24:(a>>s)&255,y=s==24?b>>24:(b>>s)&255;result+=(int)(x+(y-x)*f)<<s;}return result;}
  int rgb;Color(int v){rgb=v;}Vector3f asVectorF(){return new Vector3f();}
 }
 static class Vector3f {}
 static class ParticleTypes {
  static final String FLAME="Flame",BLOCK="LavaBlock",SOUL_FIRE_FLAME="SoulFireFlame",SMOKE="Smoke",LARGE_SMOKE="LargeSmoke",BUBBLE="Bubble",BUBBLE_POP="BubblePop",POOF="Poof",SPIT="Spit";
 }
 static class BlockParticleOption {BlockParticleOption(Object t,Object b){}public String toString(){return "LavaBlock";}}
 static class DustParticleOptions {DustParticleOptions(Vector3f c,int s){}public String toString(){return "BlueDust";}}
 static class Blocks {static final Blocks LAVA=new Blocks();Object defaultBlockState(){return null;}}
 static class Bounds {
  double[] min,max;Bounds(double[] a,double[] b){min=a;max=b;}Bounds inflate(float f){double[] a=min.clone(),b=max.clone();for(int i=0;i<3;i++){a[i]-=f;b[i]+=f;}return new Bounds(a,b);}
  boolean contains(double x,double y,double z){double[] p={x,y,z};for(int i=0;i<3;i++)if(p[i]<min[i]||p[i]>=max[i])return false;return true;}
 }
 static class Event {Object kind;Vec3 p,v;Event(Object k,Vec3 p,Vec3 v){kind=k;this.p=p;this.v=v;}}
 static class Level {
  boolean isClientSide=true;RandomSource random=new RandomSource(1);List<Event> events=new ArrayList<>();
  void addParticle(Object k,double x,double y,double z,double a,double b,double c){events.add(new Event(k,new Vec3(x,y,z),new Vec3(a,b,c)));}
 }
 interface Access {void setColor(int c);void setAlpha(float a);void spawnExtraParticle(Object kind,float multiplier);}
 abstract static class FanProcessingType {abstract void morphAirFlow(Access p,RandomSource r);abstract void spawnProcessingParticles(Level l,Vec3 p);}
 static class BlastingType extends FanProcessingType {public void morphAirFlow(Access particleAccess,RandomSource random) @@MB@@ public void spawnProcessingParticles(Level level,Vec3 pos) @@PB@@}
 static class HauntingType extends FanProcessingType {public void morphAirFlow(Access particleAccess,RandomSource random) @@MH@@ public void spawnProcessingParticles(Level level,Vec3 pos) @@PH@@}
 static class SmokingType extends FanProcessingType {public void morphAirFlow(Access particleAccess,RandomSource random) @@MM@@ public void spawnProcessingParticles(Level level,Vec3 pos) @@PM@@}
 static class SplashingType extends FanProcessingType {public void morphAirFlow(Access particleAccess,RandomSource random) @@MS@@ public void spawnProcessingParticles(Level level,Vec3 pos) @@PS@@}
 static FanProcessingType[] TYPES={new BlastingType(),new HauntingType(),new SmokingType(),new SplashingType()};
 static class Base {
  double x,y,z,xo,yo,zo,xd,yd,zd;int age,lifetime=40,sprite,color=0xEEEEEE;float alpha=.25f;boolean onGround,removed;Level level=new Level();RandomSource random;
  void tick(){}void move(double a,double b,double c){x+=a;y+=b;z+=c;}void remove(){removed=true;}void setColor(int c){color=c;}void setAlpha(float a){alpha=a;}void selectSprite(int s){sprite=s;}
 }
 static class Rotation extends Base {
  float radius,radius2,speed;Axis axis;Vec3 origin,offset;
  public void move(double x,double y,double z) @@RM@@
  public void tick() @@RT@@
 }
 static class Direction {Vec3 v;Direction(Vec3 v){this.v=v;}Vec3 getNormal(){return v;}}
 static class AirCurrent {
  Direction direction;boolean pushing;float maxDistance;Bounds bounds;FanProcessingType kind;
  FanProcessingType getTypeAt(float distance){return distance>=0&&distance<=maxDistance?kind:null;}
 }
 static class Source {boolean removed;AirCurrent current;Vec3 origin=new Vec3(7,64,-11);boolean isSourceRemoved(){return removed;}AirCurrent getAirCurrent(){return current;}Vec3 getAirCurrentPos(){return origin;}}
 static class AirFlow extends Base {
  Source source;Access access=new Access(){public void setColor(int c){AirFlow.this.setColor(c);}public void setAlpha(float a){AirFlow.this.setAlpha(a);}public void spawnExtraParticle(Object k,float m){level.addParticle(k,x,y,z,xd*m,yd*m,zd*m);}};
  FanProcessingType getType(double d){return source.getAirCurrent().getTypeAt((float)d);}
  public void tick() @@AT@@
 }
 static class Kte {Level level=new Level();boolean over;Level getLevel(){return level;}boolean isOverStressed(){return over;}}
 static class KineticEffectHandler {
  int overStressedTime,particleSpawnCountdown,rotations;float overStressedEffect;Kte kte=new Kte();int amount;float motion;String particle="-";
  void spawnEffect(Object k,float m,int n){amount=n;motion=m;particle=k.toString();}
  void spawnRotationIndicators(){rotations++;}
  public void tick() @@KT@@
  public void queueRotationIndicators() @@KQ@@
  public void triggerOverStressedEffect() @@KO@@
 }
 static String events(List<Event> events){StringBuilder s=new StringBuilder();s.append(events.size());for(var e:events)s.append(" ").append(e.kind).append(" ").append(e.p.x).append(" ").append(e.p.y).append(" ").append(e.p.z).append(" ").append(e.v.x).append(" ").append(e.v.y).append(" ").append(e.v.z);return s.toString();}
 public static void main(String[] args){var scan=new Scanner(System.in);while(scan.hasNextLine()){var a=scan.nextLine().split(" ");
  if(a[0].equals("R")){var p=new Rotation();p.axis=Axis.values()[Integer.parseInt(a[1])];p.speed=Float.parseFloat(a[2]);p.radius=Float.parseFloat(a[3]);p.radius2=Float.parseFloat(a[4]);time=Integer.parseInt(a[5]);p.age=Integer.parseInt(a[6]);p.lifetime=Integer.parseInt(a[7]);p.origin=new Vec3(7,64,-11);p.offset=p.axis.isHorizontal()?new Vec3(0,1,0):new Vec3(1,0,0);if(a[8].equals("1"))p.tick();p.move(0,0,0);System.out.println(p.radius+" "+p.x+" "+p.y+" "+p.z);
  }else if(a[0].equals("M")){var p=new AirFlow();p.x=7;p.y=64;p.z=-11;p.xd=.2;p.yd=-.1;p.zd=.3;p.random=new RandomSource(Long.parseLong(a[2]));TYPES[Integer.parseInt(a[1])].morphAirFlow(p.access,p.random);System.out.println(p.color+" "+p.alpha+" "+events(p.level.events)+" "+p.random.nextInt(1073741824));
  }else if(a[0].equals("P")){var l=new Level();l.random=new RandomSource(Long.parseLong(a[2]));TYPES[Integer.parseInt(a[1])].spawnProcessingParticles(l,new Vec3(7,64,-11));System.out.println(events(l.events)+" "+l.random.nextInt(1073741824));
  }else if(a[0].equals("A")){var p=new AirFlow();p.random=new RandomSource(Long.parseLong(a[1]));int axis=Integer.parseInt(a[2]),sign=Integer.parseInt(a[3]),kind=Integer.parseInt(a[7]);double[] dir={0,0,0};dir[axis]=sign;p.source=new Source();var c=new AirCurrent();c.direction=new Direction(new Vec3(dir[0],dir[1],dir[2]));c.pushing=a[4].equals("1");c.maxDistance=Float.parseFloat(a[5]);c.kind=kind<0?null:TYPES[kind];p.source.current=c;p.source.removed=a[8].equals("1");p.age=Integer.parseInt(a[9]);p.onGround=a[10].equals("1");double[] lo={7,64,-11},hi={8,65,-10};if(sign>0){lo[axis]+=1;hi[axis]=lo[axis]+c.maxDistance;}else{hi[axis]-=1;lo[axis]=hi[axis]-c.maxDistance;}c.bounds=new Bounds(lo,hi);
   double offset=Double.parseDouble(a[6]);double[] pos={7.5,64.5,-10.5};pos[axis]+=sign*(offset+.5);p.x=pos[0];p.y=pos[1];p.z=pos[2];p.xd=.2;p.yd=-.1;p.zd=.3;p.tick();System.out.println(p.removed+" "+p.age+" "+p.x+" "+p.y+" "+p.z+" "+p.xd+" "+p.yd+" "+p.zd+" "+p.color+" "+p.alpha+" "+p.sprite+" "+events(p.level.events)+" "+p.random.nextInt(1073741824));
  }else{var p=new KineticEffectHandler();for(int i=1;i<a.length;i++){var b=a[i].split(",");p.kte.level.isClientSide=b[0].equals("1");p.kte.over=b[1].equals("1");if(b[2].equals("1"))p.queueRotationIndicators();if(b[3].equals("1"))p.triggerOverStressedEffect();p.particle="-";p.amount=0;p.motion=0;p.tick();System.out.print(p.overStressedTime+" "+p.overStressedEffect+" "+p.particleSpawnCountdown+" "+p.rotations+" "+p.particle+" "+p.amount+" "+p.motion+" ");}System.out.println();}
 }}
}
'''.replace('static final String FLAME=', 'static final String CLOUD="Cloud",FLAME=')

RUST = r'''
use create_horizon_core::{particles as p,fan::{ProcessingType as T,Segment},kinetics::Axis,placement::Direction};
use std::io::{self,BufRead};
struct Random(u64);impl Random{fn new(s:i64)->Self{Self((s as u64^0x5deece66d)&((1<<48)-1))}fn bits(&mut self,b:u32)->u32{self.0=(self.0.wrapping_mul(0x5deece66d).wrapping_add(11))&((1<<48)-1);(self.0>>(48-b)) as u32}}
impl p::ParticleRandom for Random{fn next_float(&mut self)->f32{self.bits(24)as f32/(1<<24)as f32}fn next_int(&mut self,b:i32)->i32{if b&(b-1)==0{return ((i64::from(b)*i64::from(self.bits(31)))>>31)as i32}loop{let n=self.bits(31)as i32;let v=n%b;if n.wrapping_sub(v).wrapping_add(b-1)>=0{return v}}}}
fn events(es:&[p::Extra])->String{let mut s=es.len().to_string();for e in es{s+=&format!(" {:?} {} {} {} {} {} {}",e.kind,e.position[0],e.position[1],e.position[2],e.velocity[0],e.velocity[1],e.velocity[2])}s}
fn kind(i:i32)->T{[T::Blasting,T::Haunting,T::Smoking,T::Splashing][i as usize]}
fn main(){use p::ParticleRandom;for line in io::stdin().lock().lines(){let line=line.unwrap();let a:Vec<_>=line.split_whitespace().collect();let n=|i:usize|a[i].parse::<f64>().unwrap();let b=|i:usize|a[i]=="1";
 match a[0]{"R"=>{let mut r=p::Rotation{origin:[7.,64.,-11.],axis:[Axis::X,Axis::Y,Axis::Z][n(1)as usize],speed:n(2)as f32,radius:n(3)as f32,target_radius:n(4)as f32};if b(8){r.tick_radius();}let q=r.position(n(5)as f32,n(6)as i32,n(7)as i32);println!("{} {} {} {}",r.radius,q[0],q[1],q[2]);},
 "M"=>{let mut r=Random::new(n(2)as i64);let mut es=Vec::new();let m=p::morph(kind(n(1)as i32),&mut r,[7.,64.,-11.],[.2,-.1,.3],&mut es);println!("{} {} {} {}",m.color,m.alpha,events(&es),r.next_int(1073741824));},
 "P"=>{let mut r=Random::new(n(2)as i64);let es=p::processing_particles(kind(n(1)as i32),[7.,64.,-11.],&mut r);println!("{} {}",events(&es),r.next_int(1073741824));},
 "H"=>{let mut r=Random::new(n(1)as i64);let es=p::horse_haunting_particles([7.,64.,-11.],&mut r);println!("{} {}",events(&es),r.next_int(1073741824));},
 "A"=>{let mut r=Random::new(n(1)as i64);let axis=n(2)as usize;let sign=n(3)as i32;let facing=Direction::ALL.into_iter().find(|d|d.vector()[axis]==sign).unwrap();let distance=n(5)as f32;let mut lo=[7.,64.,-11.];let mut hi=[8.,65.,-10.];if sign>0{lo[axis]+=1.;hi[axis]=lo[axis]+f64::from(distance)}else{hi[axis]-=1.;lo[axis]=hi[axis]-f64::from(distance)}let mut pos=[7.5,64.5,-10.5];pos[axis]+=f64::from(sign)*(n(6)+.5);let k=n(7)as i32;let segments=[Segment{end:if b(4){distance.ceil()as i32}else{0},kind:if k<0{None}else{Some(kind(k))}}];let context=p::AirflowContext{origin:[7,64,-11],facing,pushing:b(4),distance,bounds:[lo,hi],source_removed:b(8),segments:&segments};let mut q=p::Airflow{position:pos,previous:pos,velocity:[.2,-.1,.3],age:n(9)as i32,lifetime:40,color:0xeeeeee,alpha:.25,sprite:0,on_ground:b(10),removed:false};let es=q.tick(&context,&mut r);println!("{} {} {} {} {} {} {} {} {} {} {} {} {}",q.removed,q.age,q.position[0],q.position[1],q.position[2],q.velocity[0],q.velocity[1],q.velocity[2],q.color,q.alpha,q.sprite,events(&es),r.next_int(1073741824));},
 _=>{let mut q=p::KineticEffects::default();let mut rotations=0;for phase in &a[1..]{let v:Vec<_>=phase.split(',').collect();if v[2]=="1"{q.queue_rotation()}if v[3]=="1"{q.trigger_overstress()}let out=q.tick(v[0]=="1",v[1]=="1");rotations+=i32::from(out.rotation_due);let (particle,amount,motion)=out.stress.map(|s|(if s.smoke{"Smoke"}else{"Cloud"},s.amount,s.max_motion)).unwrap_or(("-",0,0.));print!("{} {} {} {} {} {} {} ",q.overstressed_time,q.overstressed_effect,q.rotation_countdown,rotations,particle,amount,motion);}println!();}}
}}
'''.replace('[.2,-.1,.3]', '[0.2,-0.1,0.3]').replace('+.5', '+0.5').replace('alpha:.25', 'alpha:0.25')


def check_transport(work, rustc, library):
    """Compile the actual native codec separately; this is no Java parity claim."""
    source = (ROOT/'mixins/create/particles.rs').read_text()
    declaration = source[source.index('const CHANNEL:'):source.index('#[derive(Clone, Copy)]\nstruct Generator')]
    codec = source[source.index('fn encode('):source.index('pub(super) fn flush(')]
    checks = r'''
fn main() {
 let events:Vec<_>=(0..2500).map(|i|RotationEvent{pos:[i32::MIN+i,i-1200,i32::MAX-i],color:(i as u32)*31,speed:if i%2==0{30.0}else{-20.0},initial:0.125,target:0.65,axis:[Axis::X,Axis::Y,Axis::Z][i as usize%3]}).collect();
 let mut total=0;let mut decoded=Vec::new();
 for batch in events.chunks(MAX_RECORDS) {let data=encode(batch);assert!(data.len()<=30_000);let out=decode(&data).unwrap();assert_eq!(encode(&out),data);decoded.extend(out);total+=1;}
 assert_eq!(encode(&decoded),encode(&events));assert_eq!(total,3);
 let valid=encode(&events[..1]);
 for n in 0..valid.len() {assert_eq!(decode(&valid[..n]).is_some(),n==4);total+=1;}
 for i in 0..4 {let mut data=valid.clone();data[i]^=1;assert!(decode(&data).is_none());total+=1;}
 for (offset,word) in [(20,f32::NAN.to_bits()),(20,f32::INFINITY.to_bits()),(24,(-0.1f32).to_bits()),(24,8.001f32.to_bits()),(28,f32::NEG_INFINITY.to_bits()),(32,3),(32,u32::MAX)] {let mut data=valid.clone();data[offset..offset+4].copy_from_slice(&word.to_le_bytes());assert!(decode(&data).is_none());total+=1;}
 assert!(decode(&encode(&events[..MAX_RECORDS+1])).is_none());total+=1;
 println!("{}",total);
}
'''
    probe=work/'packet_probe.rs'
    probe.write_text('#![allow(dead_code)]\nuse create_horizon_core::kinetics::{Axis,Pos};\n'+declaration+codec+checks)
    executable=work/'packet_probe'
    subprocess.run([rustc,'--edition=2024',str(probe),'--extern','create_horizon_core='+str(library),'-o',str(executable)],env=environment(),check=True)
    return int(subprocess.check_output([str(executable)],text=True))


def check_generators(work, java, javac, rustc):
    """Compare native trigger adapter to unchanged source generator methods.

    Network topology is supplied as strict dominance. Equal compatible source
    ownership is outside this adapter comparison, as it is not in our graph.
    """
    def body(path, owner, method):
        file = work/(owner + '-generator-source.java')
        file.write_bytes(subprocess.check_output(['git', 'show',
            PINS['create_revision']+':src/main/java/com/simibubi/create/content/kinetics/base/'+path+'.java'],cwd=CREATE))
        return subprocess.check_output([java,'-cp',str(work),'ExportEntityMethod',str(file),owner,method],text=True)
    source = r'''
import java.util.*;
public class GeneratorOracle {
 static class Value {int n;Value(int n){this.n=n;}Integer get(){return n;}}
 static class Config {Config kinetics=this;Value fastSpeed=new Value(100),mediumSpeed=new Value(30);}
 static class AllConfigs {static Config server(){return new Config();}}
 enum SpeedLevel {NONE,SLOW,MEDIUM,FAST;static SpeedLevel of(float speed) @@OF@@}
 static class KineticNetwork {void updateStressFor(Object entity,float stress){}void updateStress(){}}
 static class Level {boolean isClientSide;void destroyBlock(Object pos,boolean drop){}}
 static class Effects {int queues;void queueRotationIndicators(){queues++;}}
 static class Base {
  float speed;Object source,sequenceContext,worldPosition;Level level=new Level();Effects effects=new Effects();
  void tick(){}boolean hasSource(){return source!=null;}boolean hasNetwork(){return false;}
  float getSpeed(){return speed;}void setSpeed(float s){speed=s;}void setNetwork(Long n){}
  void onSpeedChanged(float s){}KineticNetwork getOrCreateNetwork(){return new KineticNetwork();}
  void removeSource() @@BASE_REMOVE@@
 }
 static class Generator extends Base {
  boolean reActivateSource;float generated;
  float getGeneratedSpeed(){return generated;}boolean isSource(){return generated!=0;}
  void notifyStressCapacityChange(float capacity){}float calculateAddedStressCapacity(){return 0;}
  float calculateStressApplied(){return 0;}void sendData(){}void attachKinetics(){}void detachKinetics(){}
  Long createNetworkId(){return 1L;}
  public void removeSource() @@REMOVE@@
  public void tick() @@TICK@@
  public void applyNewSpeed(float prevSpeed,float speed) @@APPLY@@
  public void updateGeneratedRotation() @@UPDATE@@
 }
 public static void main(String[] args){var in=new Scanner(System.in);while(in.hasNextLine()){
  var a=in.nextLine().split(" ");var g=new Generator();
  if(a[0].equals("F")){g.speed=Float.parseFloat(a[1]);g.generated=Float.parseFloat(a[3]);g.source=Math.abs(Float.parseFloat(a[2]))>Math.abs(g.generated)?new Object():null;g.updateGeneratedRotation();}
  else if(a[0].equals("C")){float old=Float.parseFloat(a[1]);g.speed=Float.parseFloat(a[2]);g.source=Math.abs(g.speed)>Math.abs(old)?new Object():null;g.generated=Float.parseFloat(a[4]);g.updateGeneratedRotation();}
  else{g.generated=Float.parseFloat(a[1]);g.speed=Float.parseFloat(a[2]);g.source=new Object();g.removeSource();g.tick();}
  System.out.println(g.effects.queues);
 }}
}
'''
    for marker,path,owner,method in [
        ('OF','IRotate','SpeedLevel','of'),
        ('BASE_REMOVE','KineticBlockEntity','KineticBlockEntity','removeSource'),
        ('REMOVE','GeneratingKineticBlockEntity','GeneratingKineticBlockEntity','removeSource'),
        ('TICK','GeneratingKineticBlockEntity','GeneratingKineticBlockEntity','tick'),
        ('APPLY','GeneratingKineticBlockEntity','GeneratingKineticBlockEntity','applyNewSpeed'),
        ('UPDATE','GeneratingKineticBlockEntity','GeneratingKineticBlockEntity','updateGeneratedRotation')]:
        source=source.replace('@@'+marker+'@@',body(path,owner,method))
    file=work/'GeneratorOracle.java';file.write_text(source)
    subprocess.run([javac,'-d',str(work),str(file)],check=True)
    native=(ROOT/'mixins/create/particles.rs').read_text()
    state=native[native.index('#[derive(Clone, Copy)]\nstruct Generator'):native.index('#[derive(Default)]\nstruct Server')]
    tier=native[native.index('fn tier('):native.index('pub(super) fn server_tick(')]
    probe=work/'generator_probe.rs'
    probe.write_text(r'''use std::io::{self,BufRead};
'''+state+tier+r'''
fn main(){for line in io::stdin().lock().lines(){let line=line.unwrap();let mut a=line.split_whitespace();let mode=a.next().unwrap();let v:Vec<f32>=a.map(|s|s.parse().unwrap()).collect();
 let (_,before,after)=match mode {
 "F"=>generator_transition(None,v[0],v[1],v[2]),
 "C"=>generator_transition(Some(Generator{speed:v[0],theoretical:v[1],overpowered:v[1].abs()>v[0].abs()}),v[2],v[4],v[3]),
 _=>generator_transition(Some(Generator{speed:v[0],theoretical:v[1],overpowered:true}),v[2],v[0],v[0])};
 // Source reActivateSource executes after super.tick/effects.tick. Settings
 // and initialization are callbacks before the effects countdown.
 assert_eq!(after,mode=="R"&&tier(v[0])!=0);
 assert!(!(before&&after));
 println!("{}",i32::from(before||after));}}
''')
    executable=work/'generator_probe'
    subprocess.run([rustc,'--edition=2024',str(probe),'-o',str(executable)],env=environment(),check=True)
    speeds=[0,.5,1,16,29,30,32,64,99,100,128,256]
    speeds+= [-x for x in speeds if x]
    cases=[]
    for old,new in itertools.product(speeds,speeds):
        cases.append(f'F {old} {new} {new}')
        for stopped in [False,True]:
            actual=0 if stopped else old
            cases.append(f'C {old} {old} {actual} {new} {new}')
        if old and abs(old)<256:
            external=256 if old>0 else -256
            if abs(new)<=256:
                cases.append(f'C {old} {external} {external} {new} {external}')
    for gen,external in itertools.product(speeds,speeds):
        if abs(external)>abs(gen):
            for actual in [0,external]:
                cases.append(f'R {gen} {external} {actual}')
    # Source settings which outdrive a formerly stronger source do not queue:
    # hasSource is tested before applyNewSpeed, including crossing FAST.
    cases += ['C 16 32 32 128 128','C -16 -32 -32 -128 -128']
    payload='\n'.join(cases)+'\n'
    expected=subprocess.run([java,'-cp',str(work),'GeneratorOracle'],input=payload,text=True,capture_output=True,check=True).stdout.splitlines()
    actual=subprocess.run([str(executable)],input=payload,text=True,capture_output=True,check=True).stdout.splitlines()
    assert len(expected)==len(actual)==len(cases)
    for case,want,got in zip(cases,expected,actual):
        assert want==got,(case,want,got)
    return len(cases)


def main():
    java, javac = shutil.which('java'), shutil.which('javac')
    if not java or not javac:
        raise SystemExit('A JDK is required for the source particle oracle')
    work = ROOT / '.local/particle-oracle'
    work.mkdir(parents=True, exist_ok=True)
    exporter = work / 'ExportEntityMethod.java'
    exporter.write_text(EXPORTER)
    subprocess.run([javac, '-d', str(work), str(exporter)], check=True)
    template = JAVA
    methods = [('RM','base/RotationIndicatorParticle','RotationIndicatorParticle','move'),
               ('RT','base/RotationIndicatorParticle','RotationIndicatorParticle','tick'),
               ('AT','fan/AirFlowParticle','AirFlowParticle','tick'),
               ('KT','base/KineticEffectHandler','KineticEffectHandler','tick'),
               ('KQ','base/KineticEffectHandler','KineticEffectHandler','queueRotationIndicators'),
               ('KO','base/KineticEffectHandler','KineticEffectHandler','triggerOverStressedEffect')]
    for code, owner in [('B','BlastingType'),('H','HauntingType'),('M','SmokingType'),('S','SplashingType')]:
        methods += [('M'+code,'fan/processing/AllFanProcessingTypes',owner,'morphAirFlow'),
                    ('P'+code,'fan/processing/AllFanProcessingTypes',owner,'spawnProcessingParticles')]
    for marker, path, owner, method in methods:
        source = work / (path.rsplit('/', 1)[-1] + '.java')
        source.write_bytes(subprocess.check_output(['git','show',PINS['create_revision']+
            ':src/main/java/com/simibubi/create/content/kinetics/'+path+'.java'],cwd=CREATE))
        body = subprocess.check_output([java,'-cp',str(work),'ExportEntityMethod',str(source),owner,method],text=True)
        template = template.replace('@@'+marker+'@@',body)
    source = work / 'ParticleOracle.java'
    source.write_text(template)
    subprocess.run([javac,'-d',str(work),str(source)],check=True)
    # Reuse the entity context solely to execute HauntingType's unchanged
    # client Horse branch; server branches remain compiled but are not taken.
    horse_body = subprocess.check_output([java,'-cp',str(work),'ExportEntityMethod',
        str(work/'AllFanProcessingTypes.java'),'HauntingType','affectEntity'],text=True)
    horse_source = ENTITY_JAVA[:ENTITY_JAVA.index(' static class BlastingType')]
    horse_source = horse_source.replace('public class FanEntityOracle','public class HorseOracle')
    horse_source = horse_source.replace('static Vec3 offsetRandomly(Vec3 p,Random r,double range){return p;}',
        'static Vec3 offsetRandomly(Vec3 p,Random r,double range){float v=(float)range;return p.add((r.nextFloat()-.5f)*2*v,(r.nextFloat()-.5f)*2*v,(r.nextFloat()-.5f)*2*v);}')
    horse_source = horse_source.replace('void addParticle(Object kind,double x,double y,double z,double vx,double vy,double vz){}',
        'List<String> events=new ArrayList<>();void addParticle(Object kind,double x,double y,double z,double vx,double vy,double vz){events.add((kind==ParticleTypes.SOUL_FIRE_FLAME?"SoulFireFlame":"LargeSmoke")+" "+x+" "+y+" "+z+" "+vx+" "+vy+" "+vz);}')
    horse_source += 'static class HauntingType {void affectEntity(Entity entity,Level level)'+horse_body+'}\n'
    horse_source += r'''public static void main(String[] args){var in=new Scanner(System.in);while(in.hasNextLine()){var a=in.nextLine().split(" ");var h=new Horse();h.pos=new Vec3(7,64,-11);var l=new Level();l.isClientSide=true;l.random=new Random(Long.parseLong(a[1]));new HauntingType().affectEntity(h,l);System.out.println(l.events.size()+" "+String.join(" ",l.events)+" "+l.random.nextInt(1073741824));}}}'''
    horse_file=work/'HorseOracle.java'
    horse_file.write_text(horse_source)
    subprocess.run([javac,'-d',str(work),str(horse_file)],check=True)
    library = work / 'libcreate_horizon_core.rlib'
    rustc = str(ROOT / '.tools/rust/bin/rustc')
    subprocess.run([rustc,'--edition=2024','--crate-type=lib','--crate-name=create_horizon_core',
                    str(ROOT/'mixins/create/engine/src/lib.rs'),'-o',str(library)],env=environment(),check=True)
    probe = work/'probe.rs'
    probe.write_text(RUST)
    subprocess.run([rustc,'--edition=2024',str(probe),'--extern','create_horizon_core='+str(library),
                    '-o',str(work/'probe')],env=environment(),check=True)
    transport_cases = check_transport(work, rustc, library)
    generator_cases = check_generators(work, java, javac, rustc)
    cases = ['R '+' '.join(map(str,v)) for v in itertools.product(range(3),[-30,-20,-10,-.125,0,.125,10,20,30],
        [.25,.75,1.125],[.25,.65,1.5],[0,1,100,10000],[0,1,5,10,40],[10,41],[0,1])]
    for prefix in ('M','P'):
        cases += [f'{prefix} {kind} {seed}' for kind,seed in itertools.product(range(4),range(2000))]
    cases += ['A '+' '.join(map(str,v)) for v in itertools.product([0,1,37,999],range(3),[-1,1],[0,1],
        [.125,.25,3,20],[-.251,-.25,0,.5,2.9,20,21.01],[-1,0,1,2,3],[0,1],[0,39,40],[0,1])]
    rng = random.Random(0xCFE06)
    for _ in range(500):
        cases.append('K '+' '.join(','.join(map(str,[rng.randrange(2),rng.randrange(2),int(rng.random()<.1),int(rng.random()<.1)])) for _ in range(30)))
    stdin = '\n'.join(cases)+'\n'
    expected = subprocess.check_output([java,'-cp',str(work),'ParticleOracle'],input=stdin,text=True).splitlines()
    horses=[f'H {seed}' for seed in range(2000)]
    expected += subprocess.check_output([java,'-cp',str(work),'HorseOracle'],input='\n'.join(horses)+'\n',text=True).splitlines()
    cases += horses
    stdin = '\n'.join(cases)+'\n'
    actual = subprocess.check_output([str(work/'probe')],input=stdin,text=True).splitlines()
    assert len(expected)==len(actual)==len(cases)
    for case,want,got in zip(cases,expected,actual):
        a,b=want.split(),got.split()
        assert len(a)==len(b),(case,want,got)
        for x,y in zip(a,b):
            try:
                equal=abs(float(x)-float(y))<=1e-6
            except ValueError:
                equal=x==y
            assert equal,(case,want,got)
    result={'passed':len(cases),'generator_method_checks':generator_cases,'native_transport_checks':transport_cases,'reference':PINS['create_revision'],
            'scope':'unchanged AST Java rotation move/radius, airflow controller, four media morph/item particle emissions, haunting horse particles and kinetic effect traces; minimal base/level contexts, not full rendering parity'}
    (work/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__=='__main__':
    main()
