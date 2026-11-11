#!/usr/bin/env python3
"""Source-method checks for ambient sound math and fan sound lifecycle.

Uses unchanged AST-exported Java methods. Sound device mixing, resource weights
and client event ordering require the separate native/reference observations.
"""
import itertools
import json
import random
import shutil
import subprocess

from common import CREATE, PINS, ROOT, environment
from fan_entity_checks import EXPORTER


JAVA = r'''
import java.util.*;
public class SoundOracle {
 static class Vec3 {
  static final Vec3 ZERO=new Vec3(0,0,0);double x,y,z;
  Vec3(double x,double y,double z){this.x=x;this.y=y;this.z=z;}
  Vec3 add(Vec3 v){return new Vec3(x+v.x,y+v.y,z+v.z);}Vec3 scale(double f){return new Vec3(x*f,y*f,z*f);}
  double length(){return Math.sqrt(x*x+y*y+z*z);}double distanceTo(Vec3 v){return new Vec3(x-v.x,y-v.y,z-v.z).length();}
 }
 record BlockPos(int x,int y,int z){static BlockPos ZERO=new BlockPos(0,0,0);
  boolean closerThan(BlockPos p,double d){return new Vec3(x-p.x,y-p.y,z-p.z).length()<d;}}
 static class VecHelper {static Vec3 getCenterOf(BlockPos p){return new Vec3(p.x+.5,p.y+.5,p.z+.5);}}
 static class Mth {
  static float clamp(float v,float a,float b){return v<a?a:Math.min(v,b);}
  static double clamp(double v,double a,double b){return v<a?a:Math.min(v,b);}
  static double lerp(double t,double a,double b){return a+t*(b-a);}
 }
 enum PitchGroup{VERY_LOW,LOW,NORMAL,HIGH,VERY_HIGH}
 enum AmbienceGroup{KINETIC,COG,CRUSHING,MILLING}
 static class Value{float n=.1f;float getF(){return n;}}
 static class Config{Value ambientVolumeCap=new Value();}
 static class AllConfigs{static Config config=new Config();static Config client(){return config;}}
 static class Entity{Vec3 pos,velocity;Entity(Vec3 p){pos=p;}Vec3 position(){return pos;}Vec3 getDeltaMovement(){return velocity;}
  BlockPos blockPosition(){return new BlockPos((int)Math.floor(pos.x),(int)Math.floor(pos.y),(int)Math.floor(pos.z));}}
 static class Manager{void play(AirCurrentSound sound){}}
 static class Minecraft{static Minecraft mc=new Minecraft();Entity cameraEntity;Manager manager=new Manager();ClientLevel level=new ClientLevel();
  static Minecraft getInstance(){return mc;}Entity getCameraEntity(){return cameraEntity;}Manager getSoundManager(){return manager;}}
 static class SoundEvents{static String ELYTRA_FLYING="elytra",MINECART_INSIDE="minecart";}
 static class AllSoundEvents{static Event COGS=new Event("cogs"),CRUSHING_1=new Event("crushing_1"),CRUSHING_2=new Event("crushing_2"),CRUSHING_3=new Event("crushing_3"),CRANKING=new Event("cranking");}
 record Event(String name){String getMainEvent(){return name;}void playAt(ClientLevel level,BlockPos pos,float volume,float pitch,boolean delay){level.events.add(volume+" "+pitch);}}
 static class Block{boolean has(Object state){return true;}}static class AllBlocks{static Block HAND_CRANK=new Block();}
 static class CrankBase{void tickAudio(){}}
 static class HandCrank extends CrankBase{int inUse,updates;boolean backwards;ClientLevel level;BlockPos worldPosition=BlockPos.ZERO;Object getBlockState(){return null;}
  float getGeneratedSpeed(){return inUse==0?0:backwards?-32:32;}void updateGeneratedRotation(){updates++;}
  void turn(boolean back) @@TURN@@
  public void tickAudio() @@CRANK@@
 }
 enum SoundSource{AMBIENT}
 static class AnimationTickHolder{static int ticks;static int getTicks(){return ticks;}}
 static class ClientLevel{boolean isClientSide;List<String> events=new ArrayList<>();void playLocalSound(double x,double y,double z,String event,SoundSource source,float volume,float pitch,boolean delay){events.add(event+" "+x+" "+y+" "+z+" "+volume+" "+pitch+" "+delay);}}
 static class SoundScapes{
  static final int MAX_AMBIENT_SOURCE_DISTANCE=16,SOUND_VOLUME_ARG_MAX=15;
  static Set<BlockPos> locations=new HashSet<>();static int count;
  static PitchGroup getGroupFromPitch(float pitch) @@GROUP@@
  static boolean outOfRange(BlockPos pos) @@RANGE@@
  static BlockPos getCameraPos() @@CAMERA@@
  static Set<BlockPos> getAllLocations(AmbienceGroup g,PitchGroup p){return locations;}
  static int getSoundCount(AmbienceGroup g,PitchGroup p){return count;}
  static SoundScape kinetic(float pitch,AmbienceGroup group) @@KINETIC@@
  static SoundScape cogwheel(float pitch,AmbienceGroup group) @@COG@@
  static SoundScape crushing(float pitch,AmbienceGroup group) @@CRUSHING@@
  static SoundScape milling(float pitch,AmbienceGroup group) @@MILLING@@
 }
 static class SoundScape{
  AmbienceGroup group=AmbienceGroup.KINETIC;PitchGroup pitchGroup=PitchGroup.NORMAL;Vec3 meanPos;float pitch;
  List<RepeatingSound> repeating=new ArrayList<>();
  SoundScape(){}SoundScape(float p,AmbienceGroup g){pitch=p;group=g;pitchGroup=SoundScapes.getGroupFromPitch(p);}
  SoundScape continuous(String event,float relativeVolume,float relativePitch){return this;}
  SoundScape add(RepeatingSound sound){repeating.add(sound);return this;}
  SoundScape repeating(String sound,float relativeVolume,float relativePitch,int delay) @@REPEATING_ADD@@
  Vec3 getMeanPos() @@MEAN_GET@@
  Vec3 determineMeanPos() @@MEAN@@
  float getVolume() @@VOLUME@@
 }
 static class RepeatingSound{
  String event;float sharedPitch,relativeVolume;int repeatDelay;SoundScape scape;
  RepeatingSound(String event,SoundScape scape,float pitch,float volume,int delay){this.event=event;this.scape=scape;sharedPitch=pitch;relativeVolume=volume;repeatDelay=Math.max(1,delay);}
  void tick() @@REPEATING_TICK@@
 }
 static class AirCurrentSound {
  float pitch,volume=.01f;boolean stopped;
  AirCurrentSound(String event,float pitch){this.pitch=pitch;}
  void stop(){stopped=true;}boolean isStopped(){return stopped;}
  void setPitch(float pitch) @@SET_PITCH@@
  void fadeIn(float maxVolume) @@FADE_IN@@
  void fadeOut() @@FADE_OUT@@
  boolean isFaded() @@FADED@@
  void stopSound() @@STOP@@
 }
 static class Client{
  static boolean isClientPlayerInAirCurrent;static AirCurrentSound flyingSound;
  static void enableClientPlayerSound(Entity e,float maxVolume) @@ENABLE@@
  static void tickClientPlayerSounds() @@TICK@@
 }
 public static void main(String[] args){var in=new Scanner(System.in);while(in.hasNextLine()){
  String[] a=in.nextLine().split(" ");
  if(a[0].equals("P"))System.out.println(SoundScapes.getGroupFromPitch(Float.parseFloat(a[1])).ordinal());
  else if(a[0].equals("V")){SoundScapes.count=Integer.parseInt(a[1]);var s=new SoundScape();s.meanPos=new Vec3(Double.parseDouble(a[5]),Double.parseDouble(a[6]),Double.parseDouble(a[7]));
   Minecraft.mc.cameraEntity=a[9].equals("1")?new Entity(new Vec3(Double.parseDouble(a[2]),Double.parseDouble(a[3]),Double.parseDouble(a[4]))):null;
   AllConfigs.config.ambientVolumeCap.n=Float.parseFloat(a[8]);System.out.println(s.getVolume());}
  else if(a[0].equals("U")){var crank=new HandCrank();crank.inUse=Integer.parseInt(a[1]);crank.backwards=a[2].equals("1");crank.level=new ClientLevel();crank.turn(a[3].equals("1"));System.out.println(crank.inUse+" "+crank.backwards+" "+crank.updates);}
  else if(a[0].equals("C")){AnimationTickHolder.ticks=Integer.parseInt(a[2]);var crank=new HandCrank();crank.inUse=Integer.parseInt(a[1]);crank.level=new ClientLevel();crank.tickAudio();System.out.println(crank.level.events.size()+" "+String.join(" ",crank.level.events));}
  else if(a[0].equals("D")){int group=Integer.parseInt(a[1]);AnimationTickHolder.ticks=Integer.parseInt(a[2]);float pitch=Float.parseFloat(a[3]);
   Minecraft.mc.cameraEntity=new Entity(Vec3.ZERO);Minecraft.mc.level.events.clear();SoundScapes.count=1;SoundScapes.locations.clear();SoundScapes.locations.add(new BlockPos(1,0,0));AllConfigs.config.ambientVolumeCap.n=.1f;
   SoundScape s=switch(group){case 0->SoundScapes.kinetic(pitch,AmbienceGroup.KINETIC);case 1->SoundScapes.cogwheel(pitch,AmbienceGroup.COG);case 2->SoundScapes.crushing(pitch,AmbienceGroup.CRUSHING);default->SoundScapes.milling(pitch,AmbienceGroup.MILLING);};
   s.repeating.forEach(RepeatingSound::tick);var events=Minecraft.mc.level.events;System.out.println(events.size()+" "+String.join(" ",events));}
  else if(a[0].equals("M")){SoundScapes.locations.clear();for(int i=1;i<a.length;i++){var v=a[i].split(",");SoundScapes.locations.add(new BlockPos(Integer.parseInt(v[0]),Integer.parseInt(v[1]),Integer.parseInt(v[2])));}
   Vec3 mean=new SoundScape().getMeanPos();System.out.println(mean.x+" "+mean.y+" "+mean.z);}
  else if(a[0].equals("R")){Minecraft.mc.cameraEntity=new Entity(new Vec3(Double.parseDouble(a[1]),Double.parseDouble(a[2]),Double.parseDouble(a[3])));
   System.out.println(!SoundScapes.outOfRange(new BlockPos(Integer.parseInt(a[4]),Integer.parseInt(a[5]),Integer.parseInt(a[6]))));}
  else{Client.flyingSound=null;Client.isClientPlayerInAirCurrent=false;var e=new Entity(Vec3.ZERO);Minecraft.mc.cameraEntity=e;
   for(int i=1;i<a.length;i++){var b=a[i].split(",");if(b[0].equals("B"))Client.tickClientPlayerSounds();else{e.velocity=new Vec3(Double.parseDouble(b[2]),Double.parseDouble(b[3]),Double.parseDouble(b[4]));Client.enableClientPlayerSound(e,Mth.clamp(Math.abs(Float.parseFloat(b[1]))/128f*.4f,.01f,.4f));}
    var s=Client.flyingSound;System.out.print((s==null?.01f:s.volume)+" "+(s==null?1f:s.pitch)+" "+(s==null||s.stopped)+" ");}System.out.println();}
 }}
}
'''

RUST = r'''
use std::io::{self,BufRead};
mod kinetics{pub type Pos=[i32;3];}
#[path="@@AUDIO@@"]mod audio;
@@TURN_CHECK@@
fn main(){for line in io::stdin().lock().lines(){let line=line.unwrap();let a:Vec<_>=line.split_whitespace().collect();
 match a[0]{
 "P"=>println!("{}",audio::pitch_group(a[1].parse().unwrap()) as u8),
 "V"=>{let v:Vec<f64>=a[1..].iter().map(|s|s.parse().unwrap()).collect();println!("{}",audio::volume(v[0]as usize,(v[8]==1.).then_some([v[1],v[2],v[3]]),[v[4],v[5],v[6]],v[7]as f32));},
 "C"=>{if let Some((volume,pitch))=audio::crank_sound(a[2].parse().unwrap(),a[1].parse().unwrap()){println!("1 {} {}",volume,pitch)}else{println!("0")}},
 "U"=>{let (in_use,back,update)=turn(a[1].parse().unwrap(),a[2]=="1",a[3]=="1");println!("{} {} {}",in_use,back,i32::from(update));},
 "D"=>{let group=[audio::Group::Kinetic,audio::Group::Cog,audio::Group::Crushing,audio::Group::Milling][a[1].parse::<usize>().unwrap()];let mut s=audio::SoundScapes::default();s.play(group,[1,0,0],a[3].parse().unwrap(),[0,0,0],true);let (events,_)=s.tick(a[2].parse().unwrap(),Some([0.;3]),true,0.1);print!("{} ",events.len());for e in events{print!("{} {} {} {} {} {} {} ",e.event.trim_start_matches("create:"),e.position[0],e.position[1],e.position[2],e.volume,e.pitch,e.distance_delay);}println!();},
 "M"=>{let mut s=audio::SoundScapes::default();let key=(audio::Group::Kinetic,audio::PitchGroup::Normal);for p in &a[1..]{let v:Vec<i32>=p.split(',').map(|v|v.parse().unwrap()).collect();s.play(audio::Group::Kinetic,[v[0],v[1],v[2]],1.,[0,0,0],true);}let m=s.mean(key);println!("{} {} {}",m[0],m[1],m[2]);},
 "R"=>{let v:Vec<f64>=a[1..].iter().map(|s|s.parse().unwrap()).collect();println!("{}",audio::in_range([v[0].floor()as i32,v[1].floor()as i32,v[2].floor()as i32],[v[3]as i32,v[4]as i32,v[5]as i32]));},
 _=>{let mut f=audio::FanSound::default();for phase in &a[1..]{let b:Vec<_>=phase.split(',').collect();if b[0]=="B"{f.begin_tick()}else{f.enable(b[1].parse().unwrap(),[b[2].parse().unwrap(),b[3].parse().unwrap(),b[4].parse().unwrap()]);}print!("{} {} {} ",f.volume,f.pitch,f.stopped);}println!();}
 }}}
'''


def main():
    java,javac=shutil.which('java'),shutil.which('javac')
    if not java or not javac:raise SystemExit('A JDK is required')
    work=ROOT/'.local/sound-oracle';work.mkdir(parents=True,exist_ok=True)
    exporter=work/'ExportEntityMethod.java';exporter.write_text(EXPORTER)
    subprocess.run([javac,'-d',str(work),str(exporter)],check=True)
    source=JAVA
    for marker,path,owner,method in [
        ('GROUP','foundation/sound/SoundScapes','SoundScapes','getGroupFromPitch'),
        ('RANGE','foundation/sound/SoundScapes','SoundScapes','outOfRange'),
        ('CAMERA','foundation/sound/SoundScapes','SoundScapes','getCameraPos'),
        ('MEAN_GET','foundation/sound/SoundScape','SoundScape','getMeanPos'),
        ('MEAN','foundation/sound/SoundScape','SoundScape','determineMeanPos'),
        ('VOLUME','foundation/sound/SoundScape','SoundScape','getVolume'),
        ('REPEATING_ADD','foundation/sound/SoundScape','SoundScape','repeating'),
        ('REPEATING_TICK','foundation/sound/RepeatingSound','RepeatingSound','tick'),
        ('KINETIC','foundation/sound/SoundScapes','SoundScapes','kinetic'),
        ('COG','foundation/sound/SoundScapes','SoundScapes','cogwheel'),
        ('CRUSHING','foundation/sound/SoundScapes','SoundScapes','crushing'),
        ('MILLING','foundation/sound/SoundScapes','SoundScapes','milling'),
        ('CRANK','content/kinetics/crank/HandCrankBlockEntity','HandCrankBlockEntity','tickAudio'),
        ('TURN','content/kinetics/crank/HandCrankBlockEntity','HandCrankBlockEntity','turn'),
        ('SET_PITCH','content/kinetics/fan/AirCurrentSound','AirCurrentSound','setPitch'),
        ('FADE_IN','content/kinetics/fan/AirCurrentSound','AirCurrentSound','fadeIn'),
        ('FADE_OUT','content/kinetics/fan/AirCurrentSound','AirCurrentSound','fadeOut'),
        ('FADED','content/kinetics/fan/AirCurrentSound','AirCurrentSound','isFaded'),
        ('STOP','content/kinetics/fan/AirCurrentSound','AirCurrentSound','stopSound'),
        ('ENABLE','content/kinetics/fan/AirCurrent','Client','enableClientPlayerSound'),
        ('TICK','content/kinetics/fan/AirCurrent','Client','tickClientPlayerSounds')]:
        file=work/(path.rsplit('/',1)[-1]+'.java')
        file.write_bytes(subprocess.check_output(['git','show',PINS['create_revision']+
            ':src/main/java/com/simibubi/create/'+path+'.java'],cwd=CREATE))
        body=subprocess.check_output([java,'-cp',str(work),'ExportEntityMethod',str(file),owner,method],text=True)
        source=source.replace('@@'+marker+'@@',body)
    file=work/'SoundOracle.java';file.write_text(source)
    subprocess.run([javac,'-d',str(work),str(file)],check=True)
    adapter=(ROOT/'mixins/create/interactions.rs').read_text()
    adapter=adapter[adapter.index('    if block == "create:hand_crank" {'):]
    body=adapter.split('game.native_with_mod_block_entity(pos, |e| {',1)[1].split('        });',1)[0]
    turn=r'''
#[derive(Clone)]enum Tag{Int(i32),Byte(i8)}
struct Entity{nbt:std::collections::BTreeMap<String,Tag>}
mod game{pub mod create_port{pub(super) fn integer(nbt:&std::collections::BTreeMap<String,crate::Tag>,key:&str)->i32{match nbt.get(key){Some(crate::Tag::Int(v))=>*v,Some(crate::Tag::Byte(v))=>i32::from(*v),None=>0}}}}
fn turn(in_use:i32,old_back:bool,back:bool)->(i32,bool,bool){let e=&mut Entity{nbt:std::collections::BTreeMap::from([("InUse".into(),Tag::Int(in_use)),("Backwards".into(),Tag::Byte(i8::from(old_back)))])};let mut update;
'''+body+r'''
(game::create_port::integer(&e.nbt,"InUse"),game::create_port::integer(&e.nbt,"Backwards")!=0,update)}
'''
    turn=turn.replace('pub(super) fn integer','pub(crate) fn integer')
    probe=work/'probe.rs';probe.write_text(RUST.replace('@@AUDIO@@',str(ROOT/'mixins/create/engine/src/core/audio.rs')).replace('@@TURN_CHECK@@',turn))
    subprocess.run([str(ROOT/'.tools/rust/bin/rustc'),'--edition=2024','-Awarnings',str(probe),'-o',str(work/'probe')],env=environment(),check=True)
    cases=[f'P {v}' for v in [0,.69,.7,.7000001,.89,.9,.9000001,1,1.1,1.1000001,1.29,1.3,1.3000001,2]]
    cases += ['V '+' '.join(map(str,[count,x,y,z,1.5,-2.5,3.5,cap,camera]))
              for count,x,y,z,cap,camera in itertools.product([0,1,3,4,15,100,1000],[-17,0,15,16],[-1,2],[0,7],[0,.01,.025,.1,1],[0,1])]
    cases += ['R '+' '.join(map(str,v)) for v in itertools.product([-.001,0,.999],[-1,0],[0,1],[-17,-16,-15,0,15,16],[-1,0],[0,1])]
    cases += ['D '+' '.join(map(str,v)) for v in itertools.product(range(4),range(-2,22),[.7,.85,1,1.3])]
    cases += [f'C {in_use} {ticks}' for in_use,ticks in itertools.product([-1,0,1,5,9,10,11],range(-2,32))]
    cases += [f'U {in_use} {old} {next}' for in_use,old,next in itertools.product([-10,-1,0,1,5,9,10,11],[0,1],[0,1])]
    rng=random.Random(0xA0D106)
    for _ in range(200):
        points=[','.join(str(rng.randrange(-7,8)) for _ in range(3)) for _ in range(rng.randrange(1,30))]
        cases.append('M '+' '.join(points))
    for _ in range(500):
        phases=['B']
        for _ in range(40):
            phases.append('B')
            for _ in range(rng.randrange(3)):
                phases.append('E,'+','.join(map(str,[rng.choice([-256,-32,1,16,128,256]),rng.uniform(-5,5),rng.uniform(-5,5),rng.uniform(-5,5)])))
        phases+=['B']*12
        cases.append('F '+' '.join(phases))
    payload='\n'.join(cases)+'\n'
    expected=subprocess.check_output([java,'-cp',str(work),'SoundOracle'],input=payload,text=True).splitlines()
    actual=subprocess.check_output([str(work/'probe')],input=payload,text=True).splitlines()
    assert len(expected)==len(actual)==len(cases)
    for case,want,got in zip(cases,expected,actual):
        a,b=want.split(),got.split();assert len(a)==len(b),(case,want,got)
        for x,y in zip(a,b):
            try:equal=abs(float(x)-float(y))<=1e-6
            except ValueError:equal=x==y
            assert equal,(case,want,got)
    result={'passed':len(cases),'reference':PINS['create_revision'],
        'scope':'AST Java pitch buckets, strict range, volume/distance/cap, mean positions, factory gains/pitches, repeat cadence, hand crank cadence/gain/pitch and client fan sound lifecycle; not audible mix parity'}
    (work/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


def run(call, log, scratch=None, *, audio_enabled=False):
    """Normal paired-client crank input; requires AUDIO_TRACE and a scratch world."""
    def command(text):return call('command',text)
    def observed(marker,offset):
        records=[]
        for line in __import__('pathlib').Path(log).read_bytes()[offset:].decode(errors='replace').splitlines():
            if marker in line:records.append(json.JSONDecoder().raw_decode(line.split(marker,1)[1])[0])
        return records
    command('tick unfreeze')
    command('gamemode creative')
    command('forceload add 272 -16 296 16')
    command('tp @s 280.5 70 3.5')
    call('wait-ready',120);call('wait',40)
    call('fill',276,69,-3,288,74,6,'minecraft:air')
    call('fill',276,69,-3,288,69,6,'minecraft:smooth_stone')
    command('tp @s 280.5 70 3.5');call('wait',12)
    command('clear @s')
    command('item replace entity @s weapon.offhand with minecraft:air')
    placed=call('setblock',280,70,0,'create:hand_crank[facing=up]')
    assert placed['block'].startswith('create:hand_crank'),placed
    call('look-at-block',280,70,0,'south');call('wait',3)
    state=call('status')
    assert state['player']['on_ground'],state['player']
    assert state['target']['block']=='create:hand_crank',state['target']
    baseline=state['sounds']
    offset=__import__('pathlib').Path(log).stat().st_size
    try:
        call('mouse','right','down');call('wait',35)
        retained=call('status')['sounds']
    finally:call('mouse','right','up')
    if audio_enabled:
        assert ['minecraft:entity.minecart.inside',1] in retained['events'],retained
        assert retained['ticking']>=1 and retained['channels']>=1,retained
    else:
        assert retained['instances']>baseline['instances'],('no retained kinetic SoundInstance',baseline,retained)
        assert retained['playing']==retained['ticking']==retained['channels']==0,retained
    crank=observed('Create crank: ',offset)
    predicted=[r for r in crank if r['event']=='prediction' and r['position']==[280,70,0]]
    packets=[r for r in crank if r['event']=='packet' and r['position']==[280,70,0] and r['in_use']>0]
    assert len(predicted)>=4,('held use did not repeat local turns',crank)
    assert packets and len(packets)<len(predicted),('running same-direction turn must not keep syncing',crank)
    assert max(r['game_time'] for r in packets)<min(r['game_time'] for r in predicted)+5,crank
    sounds=observed('Create local sound: ',offset)
    main=[s for s in sounds if s['event']=='create:cranking']
    compound=[s for s in sounds if s['event']=='create:cranking_compounded_1']
    assert len(main)>=2 and len(main)==len(compound),sounds
    for a,b in zip(main,compound):
        assert a['source']==b['source']==4 and a['distance_delay'] and b['distance_delay'],(a,b)
        assert a['pitch']==b['pitch'] and abs(a['volume']-b['volume']*3)<1e-6,(a,b)
        assert .325-1e-6<=a['pitch']<=.775+1e-6,(a,b)
    call('wait',20)
    offset=__import__('pathlib').Path(log).stat().st_size
    call('wait',12)
    assert not [s for s in observed('Create local sound: ',offset) if s['event'].startswith('create:cranking')]
    released=call('status')['sounds']
    if audio_enabled:
        assert not [event for event in released['events'] if event[0]=='minecraft:entity.minecart.inside'],released
        assert released['ticking']<=baseline['ticking'],(baseline,released)
        # Unrelated animal calls and creative music may start during the
        # fixture. Their live instances are accounted for by playing; a leaked
        # stopped retained instance would increase this remaining balance.
        assert released['instances']-released['playing']<=baseline['instances']-baseline['playing'],(baseline,released)
    else:
        assert released['instances']<=baseline['instances'],('source retirement retained its instance',baseline,retained,released)
    result={'passed':True,'predicted_turns':len(predicted),'startup_server_refreshes':len(packets),'crank_sound_pairs':len(main),
        'audio_enabled':audio_enabled,'baseline':baseline,'retained':retained,'released':released,
        'scope':'actual held client use, source turn sync policy, wrapped cadence/category/gain/pitch and retained-instance release; '+('playing/ticking/backend channels observed; not audible mix equality' if audio_enabled else 'NO_AUDIO: playing/ticking/channels stay zero; no backend playback claim')}
    if scratch:(__import__('pathlib').Path(scratch)/'sound-native-result.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Sound native: held local turns, canonical startup sync, source crank pair cadence and release cleanup passed',flush=True)
    return result


def run_lifecycle(call, scratch=None, *, audio_enabled=False):
    """Actual sound owners retire repeatedly and across a level/dimension unload."""
    def command(text):return call('command',text)
    def census():return call('status')['sounds']
    def events(state):return dict(state['events'])
    wanted={'minecraft:entity.minecart.inside','create:cogs'}
    command('tick unfreeze');command('gamemode creative')
    command('forceload add 296 -16 328 16')
    command('tp @s 307.5 70 4.5');call('wait-ready',120);call('wait',40)
    call('fill',300,69,-3,316,74,7,'minecraft:air')
    call('fill',300,69,-3,316,69,7,'minecraft:smooth_stone')
    command('tp @s 307.5 70 4.5');call('wait',20)
    # Vanilla owns a biome-loop instance in the Nether even without audio.
    # Measure that level's own baseline before any mod source is powered.
    command('execute in minecraft:the_nether run tp @s 0.5 100 0.5')
    call('wait-ready',120);call('wait',40)
    destination_baseline=census()
    command('execute in minecraft:overworld run tp @s 307.5 70 4.5')
    call('wait-ready',120);call('wait',40)
    baseline=census();samples=[]
    def power():
        call('setblock',305,70,0,'create:cogwheel[axis=x]')
        call('setblock',304,70,0,'create:creative_motor[facing=east]')
        command('data merge block 304 70 0 {ScrollValue:128}')
        call('wait',20)
        state=census()
        if audio_enabled:
            assert wanted<=events(state).keys(),state
            assert state['ticking']>=2 and state['channels']>=2,state
        else:
            assert state['instances']>=baseline['instances']+2,(baseline,state)
            assert state['playing']==state['ticking']==state['channels']==0,state
        return state
    def retired(expected=None):
        call('wait',40)
        state=census()
        assert not wanted.intersection(events(state)),state
        expected=baseline if expected is None else expected
        if audio_enabled:
            assert state['instances']-state['playing']<=expected['instances']-expected['playing'],(expected,state)
            assert state['ticking']<=expected['ticking'],(expected,state)
        else:
            assert state['instances']<=expected['instances'],(expected,state)
        return state
    for _ in range(3):
        active=power();call('setblock',304,70,0,'minecraft:air')
        samples.append({'active':active,'retired':retired()})
    before_unload=power()
    command('execute in minecraft:the_nether run tp @s 0.5 100 0.5')
    call('wait-ready',120);unloaded=retired(destination_baseline)
    assert call('status')['dimension']=='minecraft:the_nether'
    command('execute in minecraft:overworld run tp @s 307.5 70 4.5')
    call('wait-ready',120);call('wait',20)
    returned=census()
    if audio_enabled:assert wanted<=events(returned).keys(),returned
    else:assert returned['instances']>=baseline['instances']+2,(baseline,returned)
    call('setblock',304,70,0,'minecraft:air');final=retired()
    result={'passed':True,'audio_enabled':audio_enabled,'baseline':baseline,'cycles':samples,
        'destination_baseline':destination_baseline,'before_unload':before_unload,'unloaded':unloaded,'returned':returned,'final':final,
        'scope':'actual cog and motor sound owners, three source retirement cycles and dimension unload/reentry; '+('engine ticking and backend channels observed; not audible mix equality' if audio_enabled else 'NO_AUDIO instance retention/release only, channels remain zero')}
    if scratch:(__import__('pathlib').Path(scratch)/'sound-native-lifecycle.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Sound native: retained owners, repeated retirement and dimension unload/reentry passed',flush=True)
    return result


if __name__=='__main__':main()
