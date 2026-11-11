#!/usr/bin/env python3
"""Compare exact source heat predicates/cache methods in explicit state fixtures.

Original MIT method bodies stay private. This is not a burner fuel/world test;
state tags/properties and nullable level presence are controlled host inputs.
"""
import itertools
import json
from pathlib import Path
import random
import re
import shutil
import subprocess

from basin_oracle import EXPORT
from common import ROOT, CREATE, PINS

JAVA=r'''import java.util.*;
public class BasinHeatOracle {
 enum HeatLevel{NONE,SMOULDERING,FADING,KINDLED,SEETHING}
 enum HeatCondition{NONE,HEATED,SUPERHEATED;boolean testBlazeBurner(HeatLevel level)@@REQUIRE@@}
 static class BlazeBurnerBlock{static final int HEAT_LEVEL=1;}
 static class CampfireBlock{static final int LIT=2;}
 static class BlockTags{static final int CAMPFIRES=1;}
 static class AllTags{static class AllBlockTags{static final Passive PASSIVE_BOILER_HEATERS=new Passive();}}
 static class Passive{boolean matches(BlockState s){return s.passive;}}
 static class BlockState {
  boolean blaze,passive,campfire,litProperty,lit;HeatLevel heat;
  boolean hasProperty(int p){return p==1?blaze:litProperty;}
  @SuppressWarnings("unchecked")<T>T getValue(int p){return(T)(p==1?heat:Boolean.valueOf(lit));}
  boolean is(int tag){return campfire;}
 }
 static class BlockHelper{static boolean isNotUnheated(BlockState state)@@NOT_UNHEATED@@}
 record Pos(int y){Pos below(int d){return new Pos(y-d);}}
 static int reads;
 static class World{BlockState state;World(BlockState s){state=s;}BlockState getBlockState(Pos p){if(p.y()!=63)throw new AssertionError("not below1");reads++;return state;}}
 static class Basin{
  World level;HeatLevel cachedHeatLevel;Pos getBlockPos(){return new Pos(64);}
  static HeatLevel getHeatLevelOf(BlockState state)@@BLOCK_HEAT@@
  HeatLevel getHeatLevel()@@CACHE@@
  // Only the exact first statement of original tick is relevant here; the
  // remaining SmartBE/client/IO tick is outside this controlled cache fixture.
  void tick()@@RESET@@
 }
 static BlockState state(Scanner s){var b=new BlockState();b.blaze=s.nextInt()!=0;b.heat=HeatLevel.values()[s.nextInt()];b.passive=s.nextInt()!=0;b.campfire=s.nextInt()!=0;b.litProperty=s.nextInt()!=0;b.lit=s.nextInt()!=0;return b;}
 public static void main(String[]args){var in=new Scanner(System.in);var out=new StringBuilder();while(in.hasNext()){
  String mode=in.next();if(mode.equals("P")){var s=state(in);var heat=Basin.getHeatLevelOf(s);int mask=0;for(var r:HeatCondition.values())if(r.testBlazeBurner(heat))mask|=1<<r.ordinal();out.append(heat.ordinal()).append(' ').append(BlockHelper.isNotUnheated(s)?1:0).append(' ').append(mask);}
  else {boolean first=in.nextInt()!=0;var a=state(in);boolean second=in.nextInt()!=0;var b=state(in);var basin=new Basin();reads=0;basin.level=first?new World(a):null;int x=basin.getHeatLevel().ordinal();basin.level=second?new World(b):null;int y=basin.getHeatLevel().ordinal();basin.tick();int z=basin.getHeatLevel().ordinal();out.append(x).append(' ').append(y).append(' ').append(z).append(' ').append(reads);}
  out.append('\n');
 }System.out.print(out);}
}'''
RUST=r'''#![allow(dead_code)]
#[path=@@SOURCE@@]mod basin;use basin::*;use std::io::{self,BufRead};
fn heat(n:i32)->Heat{[Heat::None,Heat::Smouldering,Heat::Fading,Heat::Kindled,Heat::Seething][n as usize]}
fn ordinal(h:Heat)->usize{[Heat::None,Heat::Smouldering,Heat::Fading,Heat::Kindled,Heat::Seething].iter().position(|x|*x==h).unwrap()}
fn state(n:&[i32])->(Option<Heat>,bool,bool,Option<bool>){((n[0]!=0).then(||heat(n[1])),n[2]!=0,n[3]!=0,(n[4]!=0).then_some(n[5]!=0))}
fn level(n:&[i32])->Heat{let(b,p,c,l)=state(n);heat_for_block(b,p,c,l)}
fn main(){for line in io::stdin().lock().lines(){let line=line.unwrap();let t=line.split_whitespace().collect::<Vec<_>>();let n=t[1..].iter().map(|s|s.parse::<i32>().unwrap()).collect::<Vec<_>>();if t[0]=="P"{let(b,_,c,l)=state(&n);let h=level(&n);let mask=[HeatRequirement::None,HeatRequirement::Heated,HeatRequirement::Superheated].iter().enumerate().fold(0,|mask,(i,r)|mask|if r.accepts(h){1<<i}else{0});println!("{} {} {}",ordinal(h),i32::from(is_not_unheated(c,l,b)),mask);}else{let mut cache=HeatCache::default();let mut reads=0;let x=cache.get_or_read(||if n[0]!=0{reads+=1;Some(level(&n[1..7]))}else{None});let y=cache.get_or_read(||if n[7]!=0{reads+=1;Some(level(&n[8..14]))}else{None});cache.reset();let z=cache.get_or_read(||if n[7]!=0{reads+=1;Some(level(&n[8..14]))}else{None});println!("{} {} {} {}",ordinal(x),ordinal(y),ordinal(z),reads);}}}
'''


def main():
    work=ROOT/'.local/basin-heat-oracle';work.mkdir(parents=True,exist_ok=True)
    javac,java=shutil.which('javac'),shutil.which('java')
    assert javac and java,'JDK required'
    (work/'BasinExport.java').write_text(EXPORT)
    subprocess.run([javac,'-d',str(work),str(work/'BasinExport.java')],check=True)
    specs=[('content/processing/basin/BasinBlockEntity.java',[('BLOCK_HEAT','getHeatLevelOf',1),('CACHE','getHeatLevel',0),('RESET','tick',0)]),
           ('foundation/utility/BlockHelper.java',[('NOT_UNHEATED','isNotUnheated',1)]),
           ('content/processing/recipe/HeatCondition.java',[('REQUIRE','testBlazeBurner',1)])]
    program=JAVA
    for name,methods in specs:
        path=work/Path(name).name
        path.write_bytes(subprocess.check_output(['git','show',PINS['create_revision']+':src/main/java/com/simibubi/create/'+name],cwd=CREATE))
        for marker,method,arity in methods:
            body=subprocess.check_output([java,'-cp',str(work),'BasinExport',str(path),method,str(arity)],text=True)
            if marker=='RESET':
                match=re.match(r'\{\s*(cachedHeatLevel\s*=\s*null\s*;)',body)
                assert match,'source reset changed';body='{'+match[1]+'}'
            program=program.replace('@@'+marker+'@@',body)
    (work/'BasinHeatOracle.java').write_text(program)
    subprocess.run([javac,'-d',str(work),str(work/'BasinHeatOracle.java')],check=True)
    (work/'probe.rs').write_text(RUST.replace('@@SOURCE@@',json.dumps(str(ROOT/'mixins/create/engine/src/core/basin.rs'))))
    subprocess.run([str(ROOT/'.tools/rust/bin/rustc'),'--edition','2024',str(work/'probe.rs'),'-o',str(work/'probe')],check=True)
    states=list(itertools.product(range(2),range(5),range(2),range(2),range(2),range(2)))
    cases=['P '+' '.join(map(str,s)) for s in states]
    # Exhaust every property state against null/non-null level and representative
    # changing heaters, including removing a level while a cached value exists.
    representatives=[(0,0,0,0,0,0),(1,0,1,0,0,0),(1,3,0,0,0,0),(1,4,1,1,1,0),(0,0,1,1,1,0),(0,0,1,1,1,1)]
    for a,b,p,q in itertools.product(states,representatives,range(2),range(2)):
        cases.append('C '+' '.join(map(str,[p,*a,q,*b])))
    stream='\n'.join(cases)+'\n';(work/'cases.txt').write_text(stream)
    expected=subprocess.check_output([java,'-cp',str(work),'BasinHeatOracle'],input=stream,text=True).splitlines()
    actual=subprocess.check_output([str(work/'probe')],input=stream,text=True).splitlines()
    (work/'java.txt').write_text('\n'.join(expected)+'\n');(work/'rust.txt').write_text('\n'.join(actual)+'\n')
    assert len(expected)==len(actual)==len(cases)
    for case,wanted,got in zip(cases,expected,actual):assert wanted==got,{'case':case,'java':wanted,'rust':got}
    report={'passed':True,'cases':len(cases),'reference':PINS['create_revision'],
            'source_methods':4,'tick_scope':'exact original first heat-cache reset statement only',
            'scope':__doc__}
    (work/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__':main()
