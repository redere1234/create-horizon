#!/usr/bin/env python3
"""Compare Basin capability math with unchanged pinned MIT CombinedTankWrapper.

The actual original class is compiled privately. Minimal single-tank fixtures
provide ordinary 1000mB fill/drain and opaque full component-key equality. This
proves wrapper ordering/variety/discard quirks, not NeoForge codecs or a game.
No original assets or Java source are committed by this developer oracle.
"""
import hashlib
import itertools
import json
import random
import shutil
import subprocess
from pathlib import Path

from common import CREATE, PINS, ROOT

FLUID = r'''package net.neoforged.neoforge.fluids;
public class FluidStack {
 public static final FluidStack EMPTY=new FluidStack(-1,0); public final int key; private int amount;
 public FluidStack(int key,int amount){this.key=key;this.amount=amount;}
 public FluidStack(int holder,int amount,int patch){this(patch,amount);if(!isEmpty()&&getFluidHolder()!=holder)throw new AssertionError();}
 public int getAmount(){return amount;} public boolean isEmpty(){return key<0||amount<=0;}
 public FluidStack copy(){return new FluidStack(key,amount);} public void shrink(int n){amount-=n;}
 public int getFluidHolder(){return key==1?1:0;} public int getComponentsPatch(){return key;}
 public static boolean isSameFluidSameComponents(FluidStack a,FluidStack b){return !a.isEmpty()&&!b.isEmpty()&&a.getFluidHolder()==b.getFluidHolder()&&a.key==b.key;}
}'''
HANDLER = r'''package net.neoforged.neoforge.fluids.capability;
import net.neoforged.neoforge.fluids.FluidStack;
public interface IFluidHandler {
 enum FluidAction {SIMULATE,EXECUTE}
 int getTanks(); FluidStack getFluidInTank(int tank); int getTankCapacity(int tank);
 boolean isFluidValid(int tank,FluidStack stack); int fill(FluidStack resource,FluidAction action);
 FluidStack drain(FluidStack resource,FluidAction action); FluidStack drain(int maximum,FluidAction action);
}'''
EMPTY = r'''package net.neoforged.neoforge.fluids.capability.templates;
import net.neoforged.neoforge.fluids.FluidStack;import net.neoforged.neoforge.fluids.capability.IFluidHandler;
public class EmptyFluidHandler implements IFluidHandler {
 public static final EmptyFluidHandler INSTANCE=new EmptyFluidHandler();
 public int getTanks(){return 0;}public FluidStack getFluidInTank(int tank){return FluidStack.EMPTY;}
 public int getTankCapacity(int tank){return 0;}public boolean isFluidValid(int tank,FluidStack stack){return false;}
 public int fill(FluidStack resource,FluidAction action){return 0;}
 public FluidStack drain(FluidStack resource,FluidAction action){return FluidStack.EMPTY;}
 public FluidStack drain(int maximum,FluidAction action){return FluidStack.EMPTY;}
}'''
JAVA = r'''import java.util.*;
import com.simibubi.create.foundation.fluid.CombinedTankWrapper;
import net.neoforged.neoforge.fluids.FluidStack;
import net.neoforged.neoforge.fluids.capability.IFluidHandler;
public class BasinFluidOracle {
 static class Single implements IFluidHandler {
  FluidStack held; Single(int k,int n){held=n==0?FluidStack.EMPTY:new FluidStack(k,n);}
  public int getTanks(){return 1;}public FluidStack getFluidInTank(int tank){return held;}
  public int getTankCapacity(int tank){return 1000;}public boolean isFluidValid(int tank,FluidStack stack){return true;}
  public int fill(FluidStack resource,FluidAction action){if(resource.isEmpty()||!held.isEmpty()&&!FluidStack.isSameFluidSameComponents(resource,held))return 0;int n=Math.min(resource.getAmount(),1000-held.getAmount());if(n>0&&action==FluidAction.EXECUTE)held=new FluidStack(resource.key,held.getAmount()+n);return n;}
  public FluidStack drain(FluidStack resource,FluidAction action){if(resource.isEmpty()||!FluidStack.isSameFluidSameComponents(resource,held))return FluidStack.EMPTY;return drain(resource.getAmount(),action);}
  public FluidStack drain(int maximum,FluidAction action){int n=Math.min(maximum,held.getAmount());if(n<=0)return FluidStack.EMPTY;var out=new FluidStack(held.key,n);if(action==FluidAction.EXECUTE)held=new FluidStack(held.key,held.getAmount()-n);return out;}
 }
 static class Half extends CombinedTankWrapper {
  boolean input; Half(boolean input,Single...tanks){super(tanks);this.input=input;enforceVariety();}
  public int fill(FluidStack resource,FluidAction action){return input?super.fill(resource,action):0;}
 }
 static class Fixture {
  Single[] tanks=new Single[4];CombinedTankWrapper full;
  Fixture(int[] initial){for(int i=0;i<4;i++)tanks[i]=new Single(initial[2*i],initial[2*i+1]);full=new CombinedTankWrapper(new Half(false,tanks[0],tanks[1]),new Half(true,tanks[2],tanks[3]));}
  int sum(){return Arrays.stream(tanks).mapToInt(t->t.held.getAmount()).sum();}
  FluidStack drain(String op,int key,int amount,IFluidHandler.FluidAction action){return op.equals("A")?full.drain(amount,action):full.drain(new FluidStack(key,amount),action);}
 }
 static String show(FluidStack f){return f.isEmpty()?"-1:0":f.key+":"+f.getAmount();}
 public static void main(String[]args){var in=new Scanner(System.in);var out=new StringBuilder();while(in.hasNext()){
  String op=in.next();boolean simulate=in.nextInt()!=0;int key=in.nextInt(),amount=in.nextInt();int[] initial=new int[8];for(int i=0;i<8;i++)initial[i]=in.nextInt();var f=new Fixture(initial);var action=simulate?IFluidHandler.FluidAction.SIMULATE:IFluidHandler.FluidAction.EXECUTE;
  int consumed=0,discarded=0;FluidStack result;
  if(op.equals("F")){int accepted=f.full.fill(new FluidStack(key,amount),action);result=new FluidStack(key,accepted);}
  else {result=f.drain(op,key,amount,action);var planned=new Fixture(initial);var executed=planned.drain(op,key,amount,IFluidHandler.FluidAction.EXECUTE);if(!show(result).equals(show(executed)))throw new AssertionError("simulate/execute returned mismatch");consumed=new Fixture(initial).sum()-planned.sum();discarded=consumed-result.getAmount();}
  out.append(show(result)).append(' ').append(consumed).append(' ').append(discarded);for(var t:f.tanks)out.append(' ').append(show(t.held));out.append('\n');
 }System.out.print(out);}
}'''
RUST = r'''#![allow(dead_code)]
#[path="@@SOURCE@@"]mod basin;use basin::*;use std::io::{self,BufRead};
fn show(f:Option<&Fluid<i32>>)->String{f.filter(|f|f.amount>0).map_or("-1:0".into(),|f|format!("{}:{}",f.key,f.amount))}
fn main(){for line in io::stdin().lock().lines(){let line=line.unwrap();let fields=line.split_whitespace().collect::<Vec<_>>();let mut i=1;macro_rules! n{($t:ty)=>{{let v=fields[i].parse::<$t>().unwrap();i+=1;v}}}
 let simulate=n!(u8)!=0;let key=n!(i32);let amount=n!(u32);let mut b:Basin<i32,i32>=Basin::default();for t in 0..4{let key=n!(i32);let amount=n!(u32);let f=(amount>0).then_some(Fluid{key,amount});if t<2{b.output_fluids[t]=f;}else{b.input_fluids[t-2]=f;}}
 let(result,consumed,discarded)=if fields[0]=="F"{let amount=b.fill_input_fluid(&Fluid{key,amount},simulate);((amount>0).then_some(Fluid{key,amount}),0,0)}else{let selected=Fluid{key,amount};let request=if fields[0]=="A"{FluidRequest::Any(amount)}else{FluidRequest::Exact(&selected)};let report=b.drain_fluid(request,simulate);(report.returned,report.consumed,report.source_discarded)};
 print!("{} {} {}",show(result.as_ref()),consumed,discarded);for t in 0..4{print!(" {}",show(b.fluid(t)));}println!();let _=i;
}}
'''


def cases():
    inputs, named = [], {}

    def add(name, op, amount, tanks, key=0, simulate=False):
        if name:
            named[name] = len(inputs)
        inputs.append(' '.join(map(str, [op, int(simulate), key, amount,
                                        *itertools.chain.from_iterable(tanks)])))

    empty = [(-1, 0)] * 4
    add('new-water-2000-spans-empty-inputs', 'F', 2000, empty)
    add('repeat-water-1000-full-first-keeps-second-empty', 'F', 1000,
        [(-1, 0), (-1, 0), (0, 1000), (-1, 0)])
    mixed = [(0, 100), (1, 100), (0, 200), (1, 200)]
    add('nested-any250-consumes350-returns250', 'A', 250, mixed)
    add('selected250-output-first-no-discard', 'E', 250, mixed)
    add('removed-component-does-not-select-plain', 'E', 250, mixed, key=3)
    add('same-fluid-patch-is-distinct', 'F', 1000,
        [(-1, 0), (-1, 0), (0, 1000), (-1, 0)], key=2)
    states = [(-1, 0), (0, 250), (0, 1000), (1, 1000), (2, 500), (3, 500)]
    for tanks in itertools.product(states, repeat=4):
        for op in ['F', 'A', 'E']:
            for simulate in [False, True]:
                add(None, op, 750, tanks, simulate=simulate)
    randomizer = random.Random(0xBA5106)
    for _ in range(1000):
        tanks = [(randomizer.randrange(4), randomizer.choice([0, 1, 249, 500, 999, 1000])) for _ in range(4)]
        op, amount, key = randomizer.choice(['F', 'A', 'E']), randomizer.choice([0, 1, 249, 250, 333, 1000, 1500, 2000, 2500]), randomizer.randrange(4)
        for simulate in [False, True]:
            add(None, op, amount, tanks, key, simulate)
    return inputs, named


def main():
    work = ROOT / '.local/basin-fluid-oracle'
    work.mkdir(parents=True, exist_ok=True)
    source_path = 'src/main/java/com/simibubi/create/foundation/fluid/CombinedTankWrapper.java'
    original = subprocess.check_output(['git', 'show', PINS['create_revision'] + ':' + source_path], cwd=CREATE)
    files = {
        'com/simibubi/create/foundation/fluid/CombinedTankWrapper.java': original.decode(),
        'net/createmod/catnip/data/Iterate.java': 'package net.createmod.catnip.data;public class Iterate{public static final boolean[] trueAndFalse={true,false};}',
        'net/neoforged/neoforge/fluids/FluidStack.java': FLUID,
        'net/neoforged/neoforge/fluids/capability/IFluidHandler.java': HANDLER,
        'net/neoforged/neoforge/fluids/capability/templates/EmptyFluidHandler.java': EMPTY,
        'BasinFluidOracle.java': JAVA,
    }
    paths = []
    for name, text in files.items():
        path = work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        paths.append(str(path))
    java, javac = shutil.which('java'), shutil.which('javac')
    if not java or not javac:
        raise SystemExit('JDK required for the unchanged-source fluid wrapper oracle')
    subprocess.run([javac, '-d', str(work), *paths], check=True)
    source = ROOT / 'mixins/create/engine/src/core/basin.rs'
    (work / 'probe.rs').write_text(RUST.replace('@@SOURCE@@', str(source)))
    subprocess.run([str(ROOT / '.tools/rust/bin/rustc'), '--edition', '2024', str(work / 'probe.rs'), '-o', str(work / 'probe')], check=True)
    inputs, named = cases()
    stream = '\n'.join(inputs) + '\n'
    (work / 'cases.txt').write_text(stream)
    expected = subprocess.check_output([java, '-cp', str(work), 'BasinFluidOracle'], input=stream, text=True).splitlines()
    actual = subprocess.check_output([str(work / 'probe')], input=stream, text=True).splitlines()
    (work / 'java.txt').write_text('\n'.join(expected) + '\n')
    (work / 'rust.txt').write_text('\n'.join(actual) + '\n')
    assert len(inputs) == len(expected) == len(actual)
    for case, wanted, got in zip(inputs, expected, actual):
        assert wanted == got, {'case': case, 'java': wanted, 'rust': got}
    report = {'passed': True, 'cases': len(inputs), 'reference': PINS['create_revision'],
              'source_sha256': hashlib.sha256(original).hexdigest(),
              'scope': 'unchanged complete MIT CombinedTankWrapper class, nested input/output halves; own minimal single-tank and component-key fixtures; not NeoForge codec/native game proof',
              'named': {name: {'input': inputs[i], 'result': actual[i]} for name, i in named.items()}}
    (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'named'}))
    return report


if __name__ == '__main__':
    main()
