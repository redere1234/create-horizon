#!/usr/bin/env python3
"""Unchanged Java fan processing, transported copies and handler queues.

Recipe applicability/results, upright/package classification and random seeds are
explicit contexts. This verifies portable logic, not native adapter persistence,
client effects or full Create compatibility. Source bodies stay in .local.
"""
import hashlib
import itertools
import json
from pathlib import Path
import random
import shutil
import subprocess

from common import CREATE, PINS, ROOT, cargo
from fan_oracle import EXPORTER

JAVA = r'''import java.util.*;import java.util.function.Function;
public class FanBeltOracle {
 enum Direction{DOWN,UP,NORTH,SOUTH,WEST,EAST}
 static class ItemStack{int key,count,maximum;ItemStack(int k,int n,int m){key=k;count=n;maximum=m;}
 ItemStack copy(){return new ItemStack(key,count,maximum);}int getCount(){return count;}
 static boolean matches(ItemStack a,ItemStack b){return a.key==b.key&&a.count==b.count;}}
 static class BeltHelper{static boolean isItemUpright(ItemStack s){return s.key%2==0;}}
 static class PackageItem{static boolean isPackage(ItemStack s){return s.key==99;}}
 static class Setting{Integer get(){return 150;}}static class Kinetics{Setting fanProcessingTime=new Setting();}
 static class Config{Kinetics kinetics=new Kinetics();}static class AllConfigs{static Config server(){return new Config();}}
 static class Level{boolean valid;int mode,checks,processes;}
 enum FanProcessingType{Blasting,Haunting,Smoking,Splashing;
 boolean canProcess(ItemStack s,Level l){l.checks++;return l.valid;}
 List<ItemStack> process(ItemStack s,Level l){l.processes++;return switch(l.mode){
 case 0->null;case 1->List.of();case 2->List.of(s.copy());case 3->List.of(new ItemStack(s.key+100,3,16));
 default->List.of(new ItemStack(s.key+100,3,16),new ItemStack(s.key+200,1,64));};}}
 static class TransportedItemStack{static Random R;ItemStack stack;float beltPosition,prevBeltPosition,sideOffset,prevSideOffset;
 int angle,insertedAt,processingTime;Direction insertedFrom;boolean locked,lockedExternally;FanProcessingType processedBy;
 TransportedItemStack(ItemStack stack) @@CONSTRUCTOR@@
 float getTargetSideOffset() @@TARGET@@
 TransportedItemStack getSimilar() @@SIMILAR@@
 }
 static class TransportedResult{List<TransportedItemStack> outputs;TransportedItemStack heldOutput;
 TransportedResult(List<TransportedItemStack> o,TransportedItemStack h){outputs=o;heldOutput=h;}
 static TransportedResult doNothing(){return new TransportedResult(null,null);}
 static TransportedResult convertTo(List<TransportedItemStack> o){return new TransportedResult(o,null);}
 boolean doesNothing() @@NOTHING@@
 boolean hasHeldOutput() @@HELD@@
 boolean didntChangeFrom(ItemStack stackBefore) @@UNCHANGED@@
 List<TransportedItemStack> getOutputs(){return outputs;}TransportedItemStack getHeldOutput(){return heldOutput;}}
 static TransportedResult applyProcessing(TransportedItemStack transported,Level world,FanProcessingType type) @@PROCESS@@
 static class Belt{int updates;void notifyUpdate(){updates++;}}
 static class Inventory{Belt belt=new Belt();boolean beltMovementPositive;
 List<TransportedItemStack> items=new ArrayList<>(),toInsert=new ArrayList<>(),toRemove=new ArrayList<>();
 void applyToEachWithin(float position,float maxDistanceToPosition,Function<TransportedItemStack,TransportedResult> processFunction) @@APPLY@@
 }
 static void dump(TransportedItemStack t){System.out.print(" "+t.stack.key+":"+t.stack.count+":"+t.stack.maximum+":"+Float.floatToRawIntBits(t.beltPosition)+":"+Float.floatToRawIntBits(t.prevBeltPosition)+":"+Float.floatToRawIntBits(t.sideOffset)+":"+Float.floatToRawIntBits(t.prevSideOffset)+":"+t.angle+":"+t.insertedAt+":"+t.insertedFrom.ordinal()+":"+t.locked+":"+t.lockedExternally+":"+(t.processedBy==null?-1:t.processedBy.ordinal())+":"+t.processingTime);}
 public static void main(String[]args){var s=new Scanner(System.in);while(s.hasNext()){
 long seed=s.nextLong();int key=s.nextInt(),count=s.nextInt(),old=s.nextInt(),time=s.nextInt(),kind=s.nextInt(),valid=s.nextInt(),mode=s.nextInt(),rounds=s.nextInt();
 float at=s.nextFloat(),distance=s.nextFloat();int n=s.nextInt();var level=new Level();level.valid=valid!=0;level.mode=mode;var inv=new Inventory();inv.beltMovementPositive=true;
 TransportedItemStack.R=new Random(123);
 for(int i=0;i<n;i++){var t=new TransportedItemStack(new ItemStack(key,count,64));t.beltPosition=at;t.prevBeltPosition=2.25f;t.sideOffset=.14f;t.prevSideOffset=-.2f;t.angle=49;t.insertedAt=4;t.insertedFrom=Direction.EAST;t.locked=true;t.lockedExternally=true;t.processedBy=old<0?null:FanProcessingType.values()[old];t.processingTime=time;inv.items.add(t);}
 TransportedItemStack.R=new Random(seed);for(int i=0;i<rounds;i++)inv.applyToEachWithin(2.5f,distance,t->applyProcessing(t,level,FanProcessingType.values()[kind]));
 System.out.print(level.checks+" "+level.processes+" "+inv.belt.updates+" "+inv.toRemove.size()+" "+TransportedItemStack.R.nextInt(1073741824));
 for(var t:inv.items)dump(t);System.out.print(" | "+inv.toInsert.size());for(var t:inv.toInsert)dump(t);System.out.println();
 }}
}'''

RUST = r'''use create_horizon_core::{fan::*,transport::*,placement::Direction};use std::io::{self,BufRead};
struct Random(u64);impl Random{fn new(s:i64)->Self{Self((s as u64^0x5deece66d)&((1<<48)-1))}fn bits(&mut self,n:u32)->u32{self.0=self.0.wrapping_mul(0x5deece66d).wrapping_add(11)&((1<<48)-1);(self.0>>(48-n))as u32}fn int(&mut self,b:i32)->i32{if b&(b-1)==0{return((i64::from(b)*i64::from(self.bits(31)))>>31)as i32}loop{let n=self.bits(31)as i32;let v=n%b;if n.wrapping_sub(v).wrapping_add(b-1)>=0{return v}}}}
struct Context{valid:bool,mode:i32,checks:i32,processes:i32,r:Random}
impl TransportedContext<i32> for Context{
 fn can_process(&mut self,_:&Stack<i32>,_:ProcessingType)->bool{self.checks+=1;self.valid}
 fn process(&mut self,s:&Stack<i32>,_:ProcessingType)->Option<Vec<Stack<i32>>>{self.processes+=1;match self.mode{0=>None,1=>Some(vec![]),2=>Some(vec![s.clone()]),3=>Some(vec![Stack{payload:s.payload+100,count:3,maximum:16}]),_=>Some(vec![Stack{payload:s.payload+100,count:3,maximum:16},Stack{payload:s.payload+200,count:1,maximum:64}])}}
 fn similar_angle(&mut self,s:&Stack<i32>)->i32{let mut a=if s.payload%2==0{180}else{self.r.int(360)};if s.payload==99{a=self.r.int(4)*90+self.r.int(20)-10;}a}}
fn dump(t:&Transported<i32>){print!(" {}:{}:{}:{}:{}:{}:{}:{}:{}:{}:{}:{}:{}:{}",t.stack.payload,t.stack.count,t.stack.maximum,t.position.to_bits()as i32,t.previous_position.to_bits()as i32,t.side_offset.to_bits()as i32,t.previous_side_offset.to_bits()as i32,t.angle,t.inserted_at,t.inserted_from as u8,t.locked,t.externally_locked,t.fan.kind.map_or(-1,|k|k as i32),t.fan.time);}
fn kind(i:i32)->Option<ProcessingType>{if i<0{None}else{Some([ProcessingType::Blasting,ProcessingType::Haunting,ProcessingType::Smoking,ProcessingType::Splashing][i as usize])}}
fn main(){for line in io::stdin().lock().lines(){let line=line.unwrap();let a=line.split_whitespace().collect::<Vec<_>>();let seed=a[0].parse::<i64>().unwrap();let key=a[1].parse().unwrap();let count=a[2].parse().unwrap();let old=kind(a[3].parse().unwrap());let time=a[4].parse().unwrap();let k=kind(a[5].parse().unwrap()).unwrap();let valid=a[6]=="1";let mode=a[7].parse().unwrap();let rounds=a[8].parse::<usize>().unwrap();let at=a[9].parse().unwrap();let distance=a[10].parse().unwrap();let n=a[11].parse::<usize>().unwrap();
 let mut inv=Inventory{positive:true,..Inventory::default()};for _ in 0..n{let mut t=Transported::new(Stack{payload:key,count,maximum:64},49);t.position=at;t.previous_position=2.25;t.side_offset=0.14;t.previous_side_offset=-0.2;t.inserted_at=4;t.inserted_from=Direction::East;t.locked=true;t.externally_locked=true;t.fan=Processing{kind:old,time};inv.items.push(t);}
 let mut ctx=Context{valid,mode,checks:0,processes:0,r:Random::new(seed)};let mut updates=0;for _ in 0..rounds{if inv.apply_to_each_within(2.5,distance,|t|Some(process_transported(t,k,&mut ctx)))>0{updates+=1;}}
 print!("{} {} {} {} {}",ctx.checks,ctx.processes,updates,inv.items.iter().filter(|t|t.scheduled_removal).count(),ctx.r.int(1073741824));for t in &inv.items{dump(t);}print!(" | {}",inv.pending.len());for t in &inv.pending{dump(t);}println!();
}}
'''


def main():
    java, javac = shutil.which('java'), shutil.which('javac')
    if not java or not javac:
        raise SystemExit('A JDK is required')
    work = ROOT / '.local/fan-belt-oracle'
    work.mkdir(parents=True, exist_ok=True)
    tracked = [ROOT / 'mixins/create/engine/src/core/fan.rs', ROOT / 'mixins/create/engine/src/core/transport.rs', Path(__file__).resolve()]
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
    (work / 'ExportFanMethod.java').write_text(EXPORTER)
    subprocess.run([javac, '-d', str(work), str(work / 'ExportFanMethod.java')], check=True)
    source = JAVA
    specs = [
        ('fan/processing/FanProcessing.java', [('PROCESS', 'applyProcessing', 'TransportedItemStack')]),
        ('belt/transport/TransportedItemStack.java', [('CONSTRUCTOR', '<init>', None), ('TARGET', 'getTargetSideOffset', None), ('SIMILAR', 'getSimilar', None)]),
        ('belt/behaviour/TransportedItemStackHandlerBehaviour.java', [('NOTHING', 'doesNothing', None), ('HELD', 'hasHeldOutput', None), ('UNCHANGED', 'didntChangeFrom', None)]),
        ('belt/transport/BeltInventory.java', [('APPLY', 'applyToEachWithin', None)]),
    ]
    for relative, methods in specs:
        path = work / Path(relative).name
        path.write_bytes(subprocess.check_output(['git', 'show', PINS['create_revision'] + ':src/main/java/com/simibubi/create/content/kinetics/' + relative], cwd=CREATE))
        for marker, method, first in methods:
            command = [java, '-cp', str(work), 'ExportFanMethod', str(path), method]
            if first:
                command.append(first)
            source = source.replace('@@' + marker + '@@', subprocess.check_output(command, text=True))
    (work / 'FanBeltOracle.java').write_text(source)
    subprocess.run([javac, '-d', str(work), str(work / 'FanBeltOracle.java')], check=True)
    probe = work / 'probe'
    (probe / 'src').mkdir(parents=True, exist_ok=True)
    (probe / 'Cargo.toml').write_text('[package]\nname="fan-belt-oracle"\nversion="0.0.0"\nedition="2024"\n[workspace]\n[dependencies]\ncreate-horizon-core={path=' + json.dumps(str(ROOT)) + '}\n')
    (probe / 'src/main.rs').write_text(RUST)
    cargo('build', '--offline', '--manifest-path', probe / 'Cargo.toml', '--target-dir', work / 'target')
    cases = []
    for key, count, old, time, valid, mode, rounds in itertools.product([1, 2, 99], [1, 16, 17, 64], [-1, 0, 1, 2, 3], [-3, -2, -1, 0, 1, 151], [0, 1], range(5), [1, 2, 153, 303, 603]):
        cases.append(f'{0xFBE17 + len(cases)} {key} {count} {old} {time} {len(cases) % 4} {valid} {mode} {rounds} 2.5 0.51 2')
    rng = random.Random(0xFBE17)
    for _ in range(500):
        cases.append(' '.join(map(str, [rng.randrange(-2**63, 2**63), rng.choice([1, 2, 99]), rng.choice([1, 16, 17, 64]), rng.randrange(-1, 4), rng.choice([-3, -1, 0, 1, 151]), rng.randrange(4), rng.randrange(2), rng.randrange(5), rng.choice([1, 2, 153, 603]), rng.choice([1.99, 2, 2.5, 3, 3.01, 3.011]), rng.choice([0.5, 0.51]), rng.choice([1, 2, 3])])))
    payload = '\n'.join(cases) + '\n'
    expected = subprocess.check_output([java, '-cp', str(work), 'FanBeltOracle'], input=payload, text=True).splitlines()
    actual = subprocess.check_output([str(work / 'target/debug/fan-belt-oracle')], input=payload, text=True).splitlines()
    assert len(expected) == len(actual) == len(cases)
    for case, want, got in zip(cases, expected, actual):
        assert want == got, {'case': case, 'java': want, 'rust': got}
    assert hashes == {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}, 'source changed during comparison'
    result = {'passed': len(cases), 'methods': 8, 'reference': PINS['create_revision'], 'sources_sha256': hashes,
              'scope': 'unchanged AST transported fan timer/conversion, getSimilar constructor and strict .51 handler queue; explicit recipe/classification contexts; Java RNG consumption, component keys, pending identity, null/empty/equal/multiple results; not native persistence or audiovisual parity'}
    (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
