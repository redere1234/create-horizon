#!/usr/bin/env python3
"""Unchanged Create belt-press callbacks versus portable Rust.

Recipes, item upright/package classification and particle/client-data effects
are explicit contexts. The real source constructor/copy/start/callback bodies
are AST-extracted into .local. This is not native belt/press integration.
"""
import hashlib
import itertools
import json
from pathlib import Path
import random
import shutil
import subprocess

from common import CREATE, PINS, ROOT, cargo


JAVA = r'''import java.util.*;
import java.util.stream.Collectors;
public class BeltPressOracle {
 enum ProcessingResult{PASS,HOLD}static final ProcessingResult PASS=ProcessingResult.PASS,HOLD=ProcessingResult.HOLD;
 enum Direction{DOWN,UP,NORTH,SOUTH,WEST,EAST}
 static class ItemStack{int key,count,maximum;ItemStack(int k,int n,int m){key=k;count=n;maximum=m;}
  ItemStack copy(){return new ItemStack(key,count,maximum);}int getCount(){return count;}void shrink(int n){count=Math.max(0,count-n);}}
 static class BeltHelper{static boolean isItemUpright(ItemStack s){return s.key%2==0;}}
 static class PackageItem{static boolean isPackage(ItemStack s){return s.key==99;}}
 static class Create{static Random RANDOM;}
 static class TransportedItemStack{
  static Random R;ItemStack stack;float beltPosition,prevBeltPosition,sideOffset,prevSideOffset;
  int angle,insertedAt,processingTime;Direction insertedFrom;boolean locked,lockedExternally;Integer processedBy;
  TransportedItemStack(ItemStack stack) @@CONSTRUCTOR@@
  float getTargetSideOffset() @@TARGET@@
  TransportedItemStack getSimilar() @@SIMILAR@@
  TransportedItemStack copy() @@COPY@@
  void clearFanProcessingData() @@CLEAR@@
 }
 static class TransportedResult{
  List<TransportedItemStack> outputs;TransportedItemStack held;
  TransportedResult(List<TransportedItemStack> o,TransportedItemStack h){outputs=o;held=h;}
  static TransportedResult removeItem(){return new TransportedResult(List.of(),null);}
  static TransportedResult convertTo(List<TransportedItemStack> o){return new TransportedResult(o,null);}
  static TransportedResult convertTo(TransportedItemStack o){return convertTo(List.of(o));}
  static TransportedResult convertToAndLeaveHeld(List<TransportedItemStack> o,TransportedItemStack h){return new TransportedResult(o,h);}
 }
 static class TransportedItemStackHandlerBehaviour{
  TransportedResult result;void handleProcessingOnItem(TransportedItemStack t,TransportedResult r){result=r;}}
 static class BlockEntity{int sends;void sendData(){sends++;}}
 enum Mode{WORLD,BELT,BASIN}
 static class Specifics{
  PressingBehaviour owner;float rpm;boolean valid,bulk;List<ItemStack> outputs;int simulations,processes,oldFan=-2;
  float getKineticSpeed(){return rpm;}boolean canProcessInBulk(){return bulk;}
  boolean tryProcessOnBelt(TransportedItemStack input,List<ItemStack> out,boolean simulate){
   if(simulate)simulations++;else{processes++;oldFan=input.processingTime;}
   if(!valid)return false;
   if(!simulate){owner.particleItems.add(input.stack);outputs.forEach(s->out.add(s.copy()));}return true;
  }
 }
 static class PressingBehaviour{
  static final int CYCLE=240;Specifics specifics=new Specifics();BlockEntity blockEntity=new BlockEntity();
  List<ItemStack> particleItems=new ArrayList<>();boolean running;int runningTicks,prevRunningTicks=7;Mode mode=Mode.WORLD;
  PressingBehaviour(){specifics.owner=this;particleItems.add(new ItemStack(77,1,64));}
  void start(Mode mode) @@START@@
 }
 static ProcessingResult onItemReceived(TransportedItemStack transported,TransportedItemStackHandlerBehaviour handler,PressingBehaviour behaviour) @@RECEIVED@@
 static ProcessingResult whenItemHeld(TransportedItemStack transported,TransportedItemStackHandlerBehaviour handler,PressingBehaviour behaviour) @@HELD@@
 static void dump(TransportedItemStack t){
  System.out.print(" "+t.stack.key+":"+t.stack.count+":"+t.stack.maximum+":"+Float.floatToRawIntBits(t.beltPosition)+":"+Float.floatToRawIntBits(t.prevBeltPosition)+":"+Float.floatToRawIntBits(t.sideOffset)+":"+Float.floatToRawIntBits(t.prevSideOffset)+":"+t.angle+":"+t.insertedAt+":"+t.insertedFrom.ordinal()+":"+t.locked+":"+t.lockedExternally+":"+(t.processedBy==null?-1:t.processedBy)+":"+t.processingTime);
 }
 public static void main(String[]args){var scan=new Scanner(System.in);while(scan.hasNextLine()){
  var a=scan.nextLine().split(" ");String mode=a[0];long seed=Long.parseLong(a[1]);
  var b=new PressingBehaviour();b.specifics.rpm=Float.parseFloat(a[2]);b.running=a[3].equals("1");b.runningTicks=Integer.parseInt(a[4]);
  b.specifics.bulk=a[5].equals("1");b.specifics.valid=a[6].equals("1");int key=Integer.parseInt(a[7]),count=Integer.parseInt(a[8]),n=Integer.parseInt(a[9]);
  b.specifics.outputs=new ArrayList<>();for(int i=0;i<n;i++){var v=a[10+i].split(",");b.specifics.outputs.add(new ItemStack(Integer.parseInt(v[0]),Integer.parseInt(v[1]),Integer.parseInt(v[2])));}
  TransportedItemStack.R=new Random(123);var t=new TransportedItemStack(new ItemStack(key,count,64));
  t.beltPosition=2.75f;t.prevBeltPosition=2.25f;t.sideOffset=.14f;t.prevSideOffset=-.2f;t.angle=49;t.insertedAt=4;t.insertedFrom=Direction.EAST;t.locked=true;t.lockedExternally=true;t.processedBy=1;t.processingTime=37;
  TransportedItemStack.R=new Random(seed);Create.RANDOM=new Random(seed^0x7395);
  var handler=new TransportedItemStackHandlerBehaviour();var result=mode.equals("E")?onItemReceived(t,handler,b):whenItemHeld(t,handler,b);
  System.out.print(result.ordinal()+" "+b.running+" "+b.runningTicks+" "+b.prevRunningTicks+" "+b.mode.ordinal()+" "+b.blockEntity.sends+" "+b.particleItems.size()+" "+b.specifics.simulations+" "+b.specifics.processes+" "+b.specifics.oldFan+" "+TransportedItemStack.R.nextInt(1073741824)+" "+Create.RANDOM.nextInt(1073741824));
  dump(t);var r=handler.result;System.out.print(" | "+(r==null?-1:r.outputs.size()));if(r!=null){r.outputs.forEach(BeltPressOracle::dump);System.out.print(" | "+(r.held!=null));if(r.held!=null)dump(r.held);}System.out.println();
 }}
}'''


RUST = r'''use create_horizon_core::{pressing::*,transport::*,fan::{Processing,ProcessingType},placement::Direction};
use std::io::{self,BufRead};
struct Random(u64);impl Random{
 fn new(s:i64)->Self{Self((s as u64^0x5deece66d)&((1<<48)-1))}
 fn bits(&mut self,b:u32)->u32{self.0=(self.0.wrapping_mul(0x5deece66d).wrapping_add(11))&((1<<48)-1);(self.0>>(48-b))as u32}
 fn int(&mut self,b:i32)->i32{if b&(b-1)==0{return ((i64::from(b)*i64::from(self.bits(31)))>>31)as i32}loop{let n=self.bits(31)as i32;let v=n%b;if n.wrapping_sub(v).wrapping_add(b-1)>=0{return v}}}
}
struct Context{valid:bool,outputs:Vec<Stack<i32>>,r:Random,create:Random,particles:usize,processes:i32,old_fan:i32}
impl BeltPressContext<i32> for Context{
 fn clear_particles(&mut self){self.particles=0;}
 fn process(&mut self,t:&Transported<i32>)->Option<Vec<Stack<i32>>>{self.processes+=1;self.old_fan=t.fan.time;if !self.valid{return None}self.particles+=1;Some(self.outputs.clone())}
 fn upright(&mut self,s:&Stack<i32>)->bool{s.payload%2==0}
 fn create_angle(&mut self)->i32{self.create.int(360)}
 fn on_source_copy(&mut self,s:&Stack<i32>){if s.payload%2!=0{self.r.int(360);}if s.payload==99{self.r.int(4);self.r.int(20);}}
}
fn dump(t:&Transported<i32>){print!(" {}:{}:{}:{}:{}:{}:{}:{}:{}:{}:{}:{}:{}:{}",t.stack.payload,t.stack.count,t.stack.maximum,t.position.to_bits()as i32,t.previous_position.to_bits()as i32,t.side_offset.to_bits()as i32,t.previous_side_offset.to_bits()as i32,t.angle,t.inserted_at,t.inserted_from as u8,t.locked,t.externally_locked,t.fan.kind.map_or(-1,|_|1),t.fan.time);}
fn main(){for line in io::stdin().lock().lines(){let line=line.unwrap();let a=line.split_whitespace().collect::<Vec<_>>();let seed=a[1].parse::<i64>().unwrap();let rpm=a[2].parse::<f32>().unwrap();let running=a[3]=="1";let ticks=a[4].parse().unwrap();let bulk=a[5]=="1";let valid=a[6]=="1";let key=a[7].parse().unwrap();let count=a[8].parse().unwrap();let n=a[9].parse::<usize>().unwrap();
 let outputs=a[10..10+n].iter().map(|s|{let v=s.split(',').map(|v|v.parse::<i32>().unwrap()).collect::<Vec<_>>();Stack{payload:v[0],count:v[1]as u32,maximum:v[2]as u32}}).collect();
 let mut ctx=Context{valid,outputs,r:Random::new(seed),create:Random::new(seed^0x7395),particles:1,processes:0,old_fan:-2};
 let mut t=Transported::new(Stack{payload:key,count,maximum:64},49);t.position=2.75;t.previous_position=2.25;t.side_offset=0.14;t.previous_side_offset=-0.2;t.inserted_at=4;t.inserted_from=Direction::East;t.locked=true;t.externally_locked=true;t.fan=Processing{kind:Some(ProcessingType::Smoking),time:37};
 let mut cycle=PressCycle{running,ticks,applied:true};let mut sends=0;let mut simulations=0;let mut previous=7;let mut mode=0;let decision;let conversion;
 if a[0]=="E"{let result=belt_received(&mut cycle,rpm,||{simulations+=1;valid});decision=result.decision;conversion=TransportedResult::DoNothing;if result.started{sends+=1;previous=0;mode=1;ctx.particles=0;}}
 else{let result=belt_held(&mut t,BeltPressState{running,ticks,rpm,bulk},&mut ctx);decision=result.decision;conversion=result.conversion;sends+=i32::from(result.send_data);}
 print!("{} {} {} {} {} {} {} {} {} {} {} {}",if decision==BeltDecision::Pass{0}else{1},cycle.running,cycle.ticks,previous,mode,sends,ctx.particles,simulations,ctx.processes,ctx.old_fan,ctx.r.int(1073741824),ctx.create.int(1073741824));dump(&t);
 match conversion{TransportedResult::DoNothing=>print!(" | -1"),TransportedResult::Convert{outputs,held}=>{print!(" | {}",outputs.len());for o in outputs{dump(&o);}print!(" | {}",held.is_some());if let Some(h)=held{dump(&h);}}}println!();
}}
'''


def main():
    java, javac = shutil.which('java'), shutil.which('javac')
    if not java or not javac:
        raise SystemExit('A JDK is required')
    work = ROOT / '.local/belt-pressing-oracle'
    work.mkdir(parents=True, exist_ok=True)
    tracked = [ROOT / 'mixins/create/engine/src/core/pressing.rs', ROOT / 'mixins/create/engine/src/core/transport.rs', Path(__file__).resolve()]
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
    subprocess.run([javac, '-d', str(work), str(ROOT / 'tools/java/ExportMethod.java')], check=True)
    source = JAVA
    specs = [
        ('press/BeltPressingCallbacks.java', [('RECEIVED', 'onItemReceived'), ('HELD', 'whenItemHeld')]),
        ('press/PressingBehaviour.java', [('START', 'start')]),
        ('belt/transport/TransportedItemStack.java', [('CONSTRUCTOR', '<init>'), ('TARGET', 'getTargetSideOffset'), ('SIMILAR', 'getSimilar'), ('COPY', 'copy'), ('CLEAR', 'clearFanProcessingData')]),
    ]
    for relative, methods in specs:
        path = work / Path(relative).name
        path.write_bytes(subprocess.check_output(['git', 'show', PINS['create_revision'] + ':src/main/java/com/simibubi/create/content/kinetics/' + relative], cwd=CREATE))
        for marker, method in methods:
            body = subprocess.check_output([java, '-cp', str(work), 'ExportMethod', str(path), method], text=True)
            source = source.replace('@@' + marker + '@@', body)
    path = work / 'BeltPressOracle.java'
    path.write_text(source)
    subprocess.run([javac, '-d', str(work), str(path)], check=True)
    probe = work / 'probe'
    (probe / 'src').mkdir(parents=True, exist_ok=True)
    (probe / 'Cargo.toml').write_text('[package]\nname="belt-pressing-oracle"\nversion="0.0.0"\nedition="2024"\n[workspace]\n[dependencies]\ncreate-horizon-core={path=' + json.dumps(str(ROOT)) + '}\n')
    (probe / 'src/main.rs').write_text(RUST)
    cargo('build', '--offline', '--manifest-path', probe / 'Cargo.toml', '--target-dir', work / 'target')
    cases = []
    patterns = [[], ['2,3,64'], ['3,1,16', '2,1,64'], ['99,0,64', '99,64,64']]
    for mode, rpm, running, ticks, count, bulk, valid, key, pattern in itertools.product(
            ['E', 'H'], ['0', '-0.0', '32', '-32', 'NaN'], [0, 1], [-120, 0, 119, 120, 121, 241], [1, 2, 64], [0, 1], [0, 1], [1, 2, 99], range(4)):
        outputs = patterns[pattern]
        cases.append(' '.join(map(str, [mode, 0x3955 + len(cases), rpm, running, ticks, bulk, valid, key, count, len(outputs), *outputs])))
    rng = random.Random(0xB3955)
    for _ in range(500):
        outputs = [f'{rng.choice([1,2,3,99])},{rng.randrange(65)},{rng.choice([1,16,64])}' for _ in range(rng.randrange(6))]
        cases.append(' '.join(map(str, ['H', rng.randrange(-2**63, 2**63), rng.choice([-512, -1, 1, 512]), rng.randrange(2), rng.choice([119, 120, 121]), rng.randrange(2), rng.randrange(2), rng.choice([1, 2, 99]), rng.randrange(65), len(outputs), *outputs])))
    payload = '\n'.join(cases) + '\n'
    expected = subprocess.check_output([java, '-cp', str(work), 'BeltPressOracle'], input=payload, text=True).splitlines()
    actual = subprocess.check_output([str(work / 'target/debug/belt-pressing-oracle')], input=payload, text=True).splitlines()
    assert len(expected) == len(actual) == len(cases)
    for case, want, got in zip(cases, expected, actual):
        assert want == got, {'case': case, 'java': want, 'rust': got}
    assert hashes == {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}, 'source changed during comparison'
    result = {'passed': len(cases), 'methods': 8, 'reference': PINS['create_revision'], 'sources_sha256': hashes,
              'scope': 'unchanged AST receive/held/start/constructor/copy/fan-clear bodies; explicit recipe, upright/package and particle contexts; independent Java RNG consumption, all conversion branches and transport metadata; no native integration or audiovisual claim'}
    (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
