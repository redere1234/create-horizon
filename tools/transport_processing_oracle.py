#!/usr/bin/env python3
"""Selected unchanged Java transported-result methods versus portable Rust.

The callback, item component keys and queued-record inspection are explicit
development contexts. This does not run Create or establish native belt/press
integration. Original method bodies are read from the pinned MIT source into
the private work directory, never bundled with the mod.
"""
import itertools
import json
import random
import shutil
import subprocess
from pathlib import Path

from common import CREATE, PINS, ROOT, cargo

JAVA = r'''import java.util.*;
import java.util.function.Function;
public class ProcessingOracle {
 static class ItemStack {
  int key,count;ItemStack(int k,int n){key=k;count=n;}
  ItemStack copy(){return new ItemStack(key,count);}
  static boolean matches(ItemStack a,ItemStack b){return a.key==b.key&&a.count==b.count;}
 }
 static class TransportedItemStack {
  ItemStack stack;float beltPosition;int angle,processingTime;
  TransportedItemStack copy(){var t=new TransportedItemStack();t.stack=stack.copy();t.beltPosition=beltPosition;t.angle=angle;t.processingTime=processingTime;return t;}
 }
 static class TransportedResult {
  List<TransportedItemStack> outputs;TransportedItemStack heldOutput;
  TransportedResult(List<TransportedItemStack> o,TransportedItemStack h){outputs=o;heldOutput=h;}
  boolean doesNothing() @@NOTHING@@
  boolean hasHeldOutput() @@HELD@@
  boolean didntChangeFrom(ItemStack stackBefore) @@UNCHANGED@@
  List<TransportedItemStack> getOutputs(){return outputs;}
  TransportedItemStack getHeldOutput(){return heldOutput;}
 }
 static class Belt {int updates;void notifyUpdate(){updates++;}}
 static class Inventory {
  Belt belt=new Belt();boolean beltMovementPositive;
  List<TransportedItemStack> items=new ArrayList<>(),toInsert=new ArrayList<>(),toRemove=new ArrayList<>();
  void applyToEachWithin(float position,float maxDistanceToPosition,Function<TransportedItemStack,TransportedResult> processFunction) @@APPLY@@
 }
 static TransportedResult callback(TransportedItemStack t,int mode){
  t.processingTime--;
  if(mode==0)return null;
  if(mode==1)return new TransportedResult(null,null);
  if(mode==2)return new TransportedResult(List.of(),null);
  var copy=t.copy();copy.angle=271;copy.beltPosition+=1;
  if(mode==3)return new TransportedResult(List.of(copy),null);
  copy.stack.key+=100;
  if(mode==4)return new TransportedResult(List.of(copy),null);
  copy.stack.count=1;
  var left=t.copy();left.stack.count--;
  return new TransportedResult(mode==5?List.of(copy):List.of(),left);
 }
 static void print(List<TransportedItemStack> list){for(var t:list)System.out.print(" "+t.stack.key+":"+t.stack.count+":"+Float.floatToRawIntBits(t.beltPosition)+":"+t.angle+":"+t.processingTime);}
 public static void main(String[] args){var s=new Scanner(System.in);while(s.hasNext()){
  var inv=new Inventory();inv.beltMovementPositive=s.nextInt()!=0;
  float position=s.nextFloat(),distance=s.nextFloat();int mode=s.nextInt(),rounds=s.nextInt(),n=s.nextInt();
  for(int i=0;i<n;i++){var t=new TransportedItemStack();t.stack=new ItemStack(s.nextInt(),s.nextInt());t.beltPosition=s.nextFloat();t.angle=s.nextInt();t.processingTime=17;inv.items.add(t);if(s.nextInt()!=0)inv.toRemove.add(t);}
  int[] calls={0};for(int i=0;i<rounds;i++)inv.applyToEachWithin(position,distance,t->{calls[0]++;return callback(t,mode);});
  System.out.print(calls[0]+" "+inv.belt.updates+" "+inv.items.size()+" "+inv.toInsert.size()+" "+inv.toRemove.size());print(inv.items);System.out.print(" | ");print(inv.toInsert);System.out.println();
 }}
}'''

RUST = r'''use create_horizon_core::transport::*;
use std::io::{self,BufRead};
fn dump(list:&[Transported<i32>]){for t in list{print!(" {}:{}:{}:{}:{}",t.stack.payload,t.stack.count,t.position.to_bits() as i32,t.angle,t.fan.time);}}
fn main(){for line in io::stdin().lock().lines(){let line=line.unwrap();let v=line.split_whitespace().collect::<Vec<_>>();let mut at=0;macro_rules! n{($t:ty)=>{{let x=v[at].parse::<$t>().unwrap();at+=1;x}}}
 let positive=n!(u8)!=0;let position=n!(f32);let distance=n!(f32);let mode=n!(u8);let rounds=n!(usize);let count=n!(usize);
 let mut inv=Inventory{positive,..Default::default()};
 for _ in 0..count{let key=n!(i32);let count=n!(u32);let position=n!(f32);let angle=n!(i32);let removed=n!(u8)!=0;let mut t=Transported::new(Stack{payload:key,count,maximum:64},angle);t.position=position;t.fan.time=17;t.scheduled_removal=removed;inv.items.push(t);}
 let mut calls=0;let mut updates=0;
 for _ in 0..rounds{let changed=inv.apply_to_each_within(position,distance,|t|{calls+=1;t.fan.time-=1;
  if mode==0{return None;}if mode==1{return Some(TransportedResult::DoNothing);}
  if mode==2{return Some(TransportedResult::Convert{outputs:vec![],held:None});}
  let mut copy=t.clone();copy.angle=271;copy.position+=1.0;
  if mode==3{return Some(TransportedResult::Convert{outputs:vec![copy],held:None});}
  copy.stack.payload+=100;
  if mode==4{return Some(TransportedResult::Convert{outputs:vec![copy],held:None});}
  copy.stack.count=1;let mut left=t.clone();left.stack.count-=1;
  Some(TransportedResult::Convert{outputs:if mode==5{vec![copy]}else{vec![]},held:Some(left)})
 });if changed>0{updates+=1;}}
 print!("{} {} {} {} {}",calls,updates,inv.items.len(),inv.pending.len(),inv.items.iter().filter(|t|t.scheduled_removal).count());dump(&inv.items);print!(" | ");dump(&inv.pending);println!();let _=at;
}}
'''


def main():
    java, javac = shutil.which('java'), shutil.which('javac')
    if not java or not javac:
        raise SystemExit('A JDK is required')
    work = ROOT / '.local/transport-processing-oracle'
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run([javac, '-d', str(work), str(ROOT / 'tools/java/ExportMethod.java')], check=True)
    template = JAVA
    base = 'src/main/java/com/simibubi/create/content/kinetics/belt/'
    specs = [
        ('behaviour/TransportedItemStackHandlerBehaviour.java',
         [('NOTHING', 'doesNothing'), ('HELD', 'hasHeldOutput'), ('UNCHANGED', 'didntChangeFrom')]),
        ('transport/BeltInventory.java', [('APPLY', 'applyToEachWithin')]),
    ]
    for relative, methods in specs:
        source = work / Path(relative).name
        source.write_bytes(subprocess.check_output(['git', 'show', PINS['create_revision'] + ':' + base + relative], cwd=CREATE))
        for marker, method in methods:
            body = subprocess.check_output([java, '-cp', str(work), 'ExportMethod', str(source), method], text=True)
            template = template.replace('@@' + marker + '@@', body)
    program = work / 'ProcessingOracle.java'
    program.write_text(template)
    subprocess.run([javac, '-d', str(work), str(program)], check=True)
    probe = work / 'probe'
    (probe / 'src').mkdir(parents=True, exist_ok=True)
    (probe / 'Cargo.toml').write_text('[package]\nname="transport-processing-oracle"\nversion="0.0.0"\nedition="2024"\n[workspace]\n[dependencies]\ncreate-horizon-core={path=' + json.dumps(str(ROOT)) + '}\n')
    (probe / 'src/main.rs').write_text(RUST)
    cargo('build', '--offline', '--manifest-path', probe / 'Cargo.toml', '--target-dir', work / 'target')
    cases = []
    for positive, position, distance, mode, rounds in itertools.product(
            [0, 1], [-2.75, -.5, 0, 2.5], [0, .5, .51, 1], range(7), [1, 2]):
        items = f'1 8 {position - .5} 19 0 1 8 {position} 43 0 2 1 {position + .5} 91 0 9 3 {position} 16 1'
        cases.append(f'{positive} {position} {distance} {mode} {rounds} 4 {items}')
    rng = random.Random(3955)
    for _ in range(1000):
        position = rng.randrange(-64, 97) / 16
        items = ' '.join(f'{rng.randrange(3)} {rng.randrange(1, 65)} {rng.randrange(-64, 97) / 16} {rng.randrange(360)} {rng.randrange(2)}' for _ in range(5))
        cases.append(f'{rng.randrange(2)} {position} {rng.choice([.5, .51, 1, 10])} {rng.randrange(7)} {rng.randrange(1, 4)} 5 {items}')
    data = '\n'.join(cases) + '\n'
    expected = subprocess.check_output([java, '-cp', str(work), 'ProcessingOracle'], input=data, text=True).splitlines()
    actual = subprocess.check_output([str(work / 'target/debug/transport-processing-oracle')], input=data, text=True).splitlines()
    assert len(cases) == len(expected) == len(actual)
    for case, original, port in zip(cases, expected, actual):
        assert original == port, {'case': case, 'java': original, 'rust': port}
    report = {'passed': len(cases), 'reference': PINS['create_revision'], 'methods': 4,
              'scope': 'unchanged AST method bodies; explicit item-key/callback contexts; queued identity, strict distances, mutation/no-op and held-output offsets; no game launched'}
    (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
