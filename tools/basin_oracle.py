#!/usr/bin/env python3
"""Portable basin/mixer comparison with pinned, unchanged AST method bodies.

Original MIT source is read by git at the pin and stays in .local. Contexts
explicitly model inventories, component-key equality, sized-fluid predicates,
fixed RNG inputs, heat and destination capability presence. This is not a native
mixer, fluid API, audiovisual or cross-client test. Source partial-consumption
failures are intentional expected results, including60+[3,3] output overbooking.
"""
import copy
import itertools
import json
from pathlib import Path
import random
import re
import shutil
import subprocess

from common import CREATE, PINS, ROOT

EXPORT = r'''import com.sun.source.tree.*;import com.sun.source.util.*;import javax.tools.*;import java.nio.file.*;import java.util.*;
public class BasinExport {
 public static void main(String[] a)throws Exception{
  var c=ToolProvider.getSystemJavaCompiler();try(var f=c.getStandardFileManager(null,null,null)){
   var t=(JavacTask)c.getTask(null,f,null,List.of("-proc:none"),null,f.getJavaFileObjects(a[0]));var tree=t.parse().iterator().next();var p=Trees.instance(t).getSourcePositions();var s=Files.readString(Path.of(a[0]));var found=new ArrayList<String>();
   new TreeScanner<Void,Void>(){public Void visitMethod(MethodTree m,Void unused){if(m.getName().contentEquals(a[1])&&m.getParameters().size()==Integer.parseInt(a[2])&&m.getBody()!=null){var b=m.getBody();found.add(s.substring((int)p.getStartPosition(tree,b),(int)p.getEndPosition(tree,b)));}return super.visitMethod(m,unused);}}.scan(tree,null);
   if(found.size()!=1)throw new IllegalStateException(a[1]+" matches "+found.size());System.out.print(found.getFirst());
  }
 }
}'''

JAVA = r'''import java.util.*;import java.util.function.*;
public class BasinOracle {
 enum HeatLevel{NONE,SMOULDERING,FADING,KINDLED,SEETHING}
 enum HeatCondition{NONE,HEATED,SUPERHEATED;boolean testBlazeBurner(HeatLevel level) @@HEAT@@}
 static class ItemStack {
  static final ItemStack EMPTY=new ItemStack(-1,0,64);int key,count,max;
  ItemStack(int k,int c,int m){key=k;count=c;max=m;}boolean isEmpty(){return count==0;}int getCount(){return count;}void setCount(int n){count=n;}
  int getMaxStackSize(){return max;}ItemStack copy(){return new ItemStack(key,count,max);}
  static boolean isSameItemSameComponents(ItemStack a,ItemStack b){return !a.isEmpty()&&!b.isEmpty()&&a.key==b.key;}
 }
 interface IItemHandler{int getSlots();ItemStack getStackInSlot(int s);ItemStack insertItem(int s,ItemStack a,boolean sim);ItemStack extractItem(int s,int n,boolean sim);}
 static class SmartInventory implements IItemHandler {
  ItemStack[] slots=new ItemStack[9];SmartInventory(){Arrays.fill(slots,ItemStack.EMPTY);}int consumed;
  public int getSlots(){return 9;}public ItemStack getStackInSlot(int s){return slots[s];}
  public ItemStack insertItem(int s,ItemStack a,boolean sim){if(a.isEmpty())return a;var old=slots[s];if(!old.isEmpty()&&old.key!=a.key)return a;int n=Math.min(a.count,Math.max(0,Math.min(64,a.max)-old.count));if(!sim&&n>0)slots[s]=new ItemStack(a.key,old.count+n,a.max);return new ItemStack(a.key,a.count-n,a.max);}
  public ItemStack extractItem(int s,int n,boolean sim){var a=slots[s];int take=Math.min(n,a.count);if(take==0)return ItemStack.EMPTY;var out=new ItemStack(a.key,take,a.max);if(!sim){consumed+=take;slots[s]=new ItemStack(a.key,a.count-take,a.max);}return out;}
 }
 static class BasinInventory extends SmartInventory {boolean packagerMode;IItemHandler inv=new IItemHandler(){public int getSlots(){return 9;}public ItemStack getStackInSlot(int s){return slots[s];}public ItemStack insertItem(int s,ItemStack a,boolean sim){return BasinInventory.super.insertItem(s,a,sim);}public ItemStack extractItem(int s,int n,boolean sim){return BasinInventory.super.extractItem(s,n,sim);}};
  public ItemStack insertItem(int slot,ItemStack stack,boolean simulate) @@INSERT@@
  void allowInsertion(){}void forbidInsertion(){}
 }
 static class CombinedItems implements IItemHandler{BasinInventory a,b;CombinedItems(BasinInventory a,BasinInventory b){this.a=a;this.b=b;}public int getSlots(){return 18;}IItemHandler at(int s){return s<9?a:b;}public ItemStack getStackInSlot(int s){return at(s).getStackInSlot(s%9);}public ItemStack insertItem(int s,ItemStack a,boolean sim){return at(s).insertItem(s%9,a,sim);}public ItemStack extractItem(int s,int n,boolean sim){return at(s).extractItem(s%9,n,sim);}}
 static class ItemHandlerHelper {
  static ItemStack insertItemStacked(IItemHandler h,ItemStack a,boolean sim){if(a.isEmpty())return a;if(a.max>1)for(int i=0;i<h.getSlots();i++)if(ItemStack.isSameItemSameComponents(h.getStackInSlot(i),a)){a=h.insertItem(i,a,sim);if(a.isEmpty())return a;}for(int i=0;i<h.getSlots();i++)if(h.getStackInSlot(i).isEmpty()){a=h.insertItem(i,a,sim);if(a.isEmpty())return a;}return a;}
 }
 static class FluidStack{int key,amount;static final FluidStack EMPTY=new FluidStack(-1,0);FluidStack(int k,int n){key=k;amount=n;}int getAmount(){return amount;}boolean isEmpty(){return amount==0;}void shrink(int n){amount-=n;}FluidStack copy(){return new FluidStack(key,amount);}static boolean isSameFluidSameComponents(FluidStack a,FluidStack b){return !a.isEmpty()&&!b.isEmpty()&&a.key==b.key;}}
 enum FluidAction{SIMULATE,EXECUTE}
 interface IFluidHandler{int getTanks();FluidStack getFluidInTank(int s);int fill(FluidStack f,FluidAction action);}
 static class OneTank implements IFluidHandler{FluidStack stack=FluidStack.EMPTY;public int getTanks(){return 1;}public FluidStack getFluidInTank(int i){return stack;}public int fill(FluidStack f,FluidAction action){if(!stack.isEmpty()&&!FluidStack.isSameFluidSameComponents(stack,f))return 0;int n=Math.min(f.amount,Math.max(0,1000-stack.amount));if(action==FluidAction.EXECUTE&&n>0)stack=new FluidStack(f.key,stack.amount+n);return n;}}
 static class CombinedTank implements IFluidHandler{IFluidHandler[] itemHandler;boolean enforceVariety=true;CombinedTank(IFluidHandler...h){itemHandler=h;}public int getTanks(){return Arrays.stream(itemHandler).mapToInt(IFluidHandler::getTanks).sum();}public FluidStack getFluidInTank(int i){for(var h:itemHandler){if(i<h.getTanks())return h.getFluidInTank(i);i-=h.getTanks();}return FluidStack.EMPTY;}
  public int fill(FluidStack resource,FluidAction action) @@FILL@@
 }
 static class SmartFluidTankBehaviour{static final int INPUT=0,OUTPUT=1;List<TankSegment> segments;SmartFluidTankBehaviour(BasinBlockEntity b){segments=List.of(new TankSegment(b),new TankSegment(b));}void forEach(Consumer<TankSegment> c){segments.forEach(c);}boolean isEmpty(){return true;}static class InternalFluidHandler extends CombinedTank{InternalFluidHandler(IFluidHandler...h){super(h);}int forceFill(FluidStack f,FluidAction a){return fill(f,a);}void allowInsertion(){}void forbidInsertion(){}IFluidHandler getCapability(){return this;}}}
 static class TankSegment{BasinBlockEntity b;TankSegment(BasinBlockEntity b){this.b=b;}void onFluidStackChanged(){b.notifications++;}}
 static class Ingredient{int mask;Ingredient(int m){mask=m;}boolean test(ItemStack s){return !s.isEmpty()&&(mask&(1<<s.key))!=0;}}
 static class SizedFluidIngredient{int key,n;SizedFluidIngredient(int k,int a){key=k;n=a;}int amount(){return n;}boolean test(FluidStack f){return !f.isEmpty()&&f.key==key&&f.amount>=n;}}
 static class RandomSource{int cursor;float nextFloat(){return new float[]{0,.25f,.5f,.75f}[cursor++%4];}}
 static class ProcessingOutput{ItemStack stack;float chance;int count;ProcessingOutput(ItemStack s,float c){stack=s;count=s.count;chance=c;}ItemStack getStack(){return stack.copy();}ItemStack getStack(int n){var a=stack.copy();a.count=n;return a;}ItemStack rollOutput(RandomSource randomSource) @@ROLL@@}
 static class CraftingInput{List<ItemStack> items;CraftingInput(List<ItemStack> i){items=i;}}
 static class NonNullList<T> extends ArrayList<T>{static <T>NonNullList<T> create(){return new NonNullList<T>();}}
 static class DummyCraftingContainer{NonNullList<ItemStack> inv;DummyCraftingContainer(IItemHandler h,int[] n){inv=createInventory(h,n);}CraftingInput asCraftInput(){return new CraftingInput(inv);}static NonNullList<ItemStack> createInventory(IItemHandler itemHandler,int[] extractedItemsFromSlot) @@DUMMY@@}
 interface Recipe<T>{List<Ingredient>getIngredients();ItemStack getResultItem(Object registry);}
 static class CraftingRecipe implements Recipe<Object>{List<Ingredient> ingredients=new ArrayList<>();List<ProcessingOutput> outputs=new ArrayList<>();public List<Ingredient>getIngredients(){return ingredients;}public ItemStack getResultItem(Object r){return outputs.isEmpty()?ItemStack.EMPTY:outputs.getFirst().getStack();}List<ItemStack> getRemainingItems(CraftingInput input){var out=new ArrayList<ItemStack>();for(var a:input.items)if(a.key==9)out.add(new ItemStack(10,1,64));return out;}}
 static class BasinRecipe extends CraftingRecipe{List<SizedFluidIngredient> fluidIngredients=new ArrayList<>();List<FluidStack>fluidOutputs=new ArrayList<>();HeatCondition heat;HeatCondition getRequiredHeat(){return heat;}List<SizedFluidIngredient>getFluidIngredients(){return fluidIngredients;}List<FluidStack>getFluidResults(){return fluidOutputs;}List<ItemStack>rollResults(RandomSource r){var a=new ArrayList<ItemStack>();for(var o:outputs){var s=o.rollOutput(r);if(!s.isEmpty())a.add(s);}return a;}
  static boolean apply(BasinBlockEntity basin,Recipe<?> recipe,boolean test) @@APPLY@@
 }
 static class Capability<T>{int kind;Capability(int k){kind=k;}}
 static class Capabilities{static class ItemHandler{static final Capability<IItemHandler> BLOCK=new Capability<>(0);}static class FluidHandler{static final Capability<IFluidHandler> BLOCK=new Capability<>(1);}}
 enum Direction{DOWN,EAST;Direction getOpposite(){return this;}}
 static class BasinBlock{static final Object FACING=new Object();}
 static class BlockState{int mode;boolean valid;BlockState(int m,boolean v){mode=m;valid=v;}Object getBlock(){return valid?new BasinBlock():new Object();}Direction getValue(Object p){return mode==0?Direction.DOWN:Direction.EAST;}}
 record Pos(int x,int y,int z){Pos below(){return new Pos(x,y-1,z);}Pos relative(Direction d){return new Pos(x+1,y,z);}}
 static class BlockEntity{Pos getBlockPos(){return new Pos(1,0,0);}}
 static class InvManipulationBehaviour{static final int TYPE=1;IItemHandler getInventory(){return null;}}
 static class BlockEntityBehaviour{static InvManipulationBehaviour get(Level l,Pos p,int type){return null;}}
 static class Iterate{static final boolean[]trueAndFalse={true,false};}
 static class Level{BasinBlockEntity b;RandomSource random=new RandomSource();Level(BasinBlockEntity b){this.b=b;}Object registryAccess(){return null;}@SuppressWarnings("unchecked")<T>T getCapability(Capability<T> type,Pos p,Object face){if(p.x==0)return (T)(type.kind==0?(b.itemsPresent?b.combined:null):(b.fluidsPresent?b.combinedFluids:null));return(T)(type.kind==0?(b.itemDest?new SmartInventory():null):(b.fluidDest?new OneTank():null));}BlockEntity getBlockEntity(Pos p){return b.itemDest||b.fluidDest?new BlockEntity():null;}}
 static class BasinBlockEntity{
  BasinInventory input=new BasinInventory(),outputInventory=new BasinInventory();CombinedItems combined=new CombinedItems(input,outputInventory);
  OneTank[] tanks={new OneTank(),new OneTank(),new OneTank(),new OneTank()};SmartFluidTankBehaviour.InternalFluidHandler outputTank=new SmartFluidTankBehaviour.InternalFluidHandler(tanks[0],tanks[1]);CombinedTank combinedFluids=new CombinedTank(tanks[0],tanks[1],tanks[2],tanks[3]);
  List<ItemStack>spoutputBuffer=new ArrayList<>();List<FluidStack>spoutputFluidBuffer=new ArrayList<>();boolean itemDest,fluidDest,valid=true,itemsPresent=true,fluidsPresent=true;int mode,notifications;Pos worldPosition=new Pos(0,0,0);Level level=new Level(this);HeatLevel heat;
  Level getLevel(){return level;}Pos getBlockPos(){return worldPosition;}HeatLevel getHeatLevel(){return heat;}BlockState getBlockState(){return new BlockState(mode,valid);}Couple<SmartFluidTankBehaviour>getTanks(){return null;}SmartFluidTankBehaviour getBehaviour(int k){return new SmartFluidTankBehaviour(this);}
  boolean acceptOutputs(List<ItemStack>outputItems,List<FluidStack>outputFluids,boolean simulate) @@ACCEPT@@
  boolean acceptOutputsInner(List<ItemStack>outputItems,List<FluidStack>outputFluids,boolean simulate) @@ACCEPT_INNER@@
  boolean acceptFluidOutputsIntoBasin(List<FluidStack>outputFluids,boolean simulate,IFluidHandler targetTank) @@ACCEPT_FLUID@@
  boolean acceptItemOutputsIntoBasin(List<ItemStack>outputItems,boolean simulate,IItemHandler targetInv) @@ACCEPT_ITEM@@
 }
 static class Mth{static int log2(int n){return n==0?-1:31-Integer.numberOfLeadingZeros(n);}static int ceil(float n){return (int)Math.ceil(n);}}
 static class SoundEvents{static final int BUBBLE_COLUMN_WHIRLPOOL_AMBIENT=0;}static class SoundSource{static final int BLOCKS=0;}
 static class Couple<T>{T getFirst(){return null;}T getSecond(){return null;}}
 static class StandardProcessingRecipe<T>{int t;StandardProcessingRecipe(int t){this.t=t;}int getProcessingDuration(){return t;}}
 static class MixerLevel{boolean isClientSide;void playSound(Object a,Object b,int c,int d,float e,float f){}}
 static class Checker{Mixer owner;Checker(Mixer m){owner=m;}void scheduleUpdate(){owner.scheduled++;}}
 static class BaseMixer{void tick(){}void startProcessingBasin(){}}
 static class Mixer extends BaseMixer{boolean running;int runningTicks,processingTicks,applied,scheduled;float speed,minimum;boolean repeat;Object currentRecipe,worldPosition;MixerLevel level=new MixerLevel();Checker basinChecker=new Checker(this);float getSpeed(){return speed;}boolean isSpeedRequirementFulfilled(){return Math.abs(speed)>=minimum;}boolean isVirtual(){return false;}void renderParticles(){}Optional<BasinBlockEntity>getBasin(){return Optional.empty();}void applyBasinRecipe(){applied++;if(repeat)runningTicks=20;}void sendData(){}
  public void tick() @@TICK@@
  public void startProcessingBasin() @@START@@
  void onBasinRemoved() @@REMOVE@@
 }
 static String item(ItemStack s){return s.isEmpty()?"-1:0:64":s.key+":"+s.count+":"+s.max;}static String fluid(FluidStack f){return f.isEmpty()?"-1:0":f.key+":"+f.amount;}
 public static void main(String[]args){var in=new Scanner(System.in);var out=new StringBuilder();while(in.hasNext()){
  String op=in.next();if(op.equals("A")){
   var b=new BasinBlockEntity();boolean test=in.nextInt()!=0;boolean basin=in.nextInt()!=0;b.heat=HeatLevel.values()[in.nextInt()];int heat=in.nextInt();b.mode=in.nextInt();b.itemDest=in.nextInt()!=0;b.fluidDest=in.nextInt()!=0;b.itemsPresent=in.nextInt()!=0;b.fluidsPresent=in.nextInt()!=0;b.valid=in.nextInt()!=0;
   CraftingRecipe r=basin?new BasinRecipe():new CraftingRecipe();if(basin)((BasinRecipe)r).heat=HeatCondition.values()[heat];int n=in.nextInt();for(int i=0;i<n;i++)r.ingredients.add(new Ingredient(in.nextInt()));
   n=in.nextInt();for(int i=0;i<n;i++){int key=in.nextInt(),amount=in.nextInt();if(basin)((BasinRecipe)r).fluidIngredients.add(new SizedFluidIngredient(key,amount));}
   n=in.nextInt();for(int i=0;i<n;i++)r.outputs.add(new ProcessingOutput(new ItemStack(in.nextInt(),in.nextInt(),in.nextInt()),in.nextFloat()));
   n=in.nextInt();for(int i=0;i<n;i++){var f=new FluidStack(in.nextInt(),in.nextInt());if(basin)((BasinRecipe)r).fluidOutputs.add(f);}
   for(int i=0;i<18;i++){var a=new ItemStack(in.nextInt(),in.nextInt(),in.nextInt());(i<9?b.input:b.outputInventory).slots[i%9]=a;}
   for(int i=0;i<4;i++)b.tanks[i].stack=new FluidStack(in.nextInt(),in.nextInt());
   boolean success=BasinRecipe.apply(b,r,test);out.append(success?1:0).append(' ').append(b.level.random.cursor).append(' ').append(b.notifications>0?1:0);
   for(int i=0;i<18;i++)out.append(' ').append(item(b.combined.getStackInSlot(i)));for(var t:b.tanks)out.append(' ').append(fluid(t.stack));out.append(" I");for(var a:b.spoutputBuffer)out.append(' ').append(item(a));out.append(" F");for(var f:b.spoutputFluidBuffer)out.append(' ').append(fluid(f));out.append('\n');
  }else{
   var m=new Mixer();m.speed=in.nextFloat();m.minimum=in.nextFloat();m.currentRecipe=new StandardProcessingRecipe(in.nextInt());m.running=in.nextInt()!=0;m.runningTicks=in.nextInt();m.processingTicks=in.nextInt();int ticks=in.nextInt(),cut=in.nextInt();m.repeat=in.nextInt()!=0;int start=in.nextInt(),remove=in.nextInt();if(start!=0)m.startProcessingBasin();if(remove!=0)m.onBasinRemoved();for(int i=0;i<ticks;i++){if(i==cut)m.speed=0;m.tick();}out.append(m.running?1:0).append(' ').append(m.runningTicks).append(' ').append(m.processingTicks).append(' ').append(m.applied).append(' ').append(m.scheduled).append('\n');
  }
 }System.out.print(out);}
}'''

RUST = r'''#![allow(dead_code)]
#[path="@@BASIN@@"] mod basin;
use basin::*;use std::io::{self,BufRead};
#[derive(Default)]struct C{items:Vec<u32>,fluids:Vec<i32>,cursor:u32}
impl Context<i32,i32> for C{fn item_matches(&mut self,i:usize,s:&Item<i32>)->bool{self.items[i]&(1u32<<s.key)!=0}fn fluid_matches(&mut self,i:usize,s:&Fluid<i32>)->bool{self.fluids[i]==s.key}fn remainder(&mut self,s:&Item<i32>)->Option<Item<i32>>{(s.key==9).then_some(Item{key:10,count:1,maximum:64})}fn random(&mut self)->f32{let v=[0.,0.25,0.5,0.75][self.cursor as usize%4];self.cursor+=1;v}}
fn item(s:Option<&Item<i32>>)->String{s.filter(|s|s.count>0).map_or("-1:0:64".into(),|s|format!("{}:{}:{}",s.key,s.count,s.maximum))}
fn fluid(s:Option<&Fluid<i32>>)->String{s.filter(|s|s.amount>0).map_or("-1:0".into(),|s|format!("{}:{}",s.key,s.amount))}
fn main(){for line in io::stdin().lock().lines(){let line=line.unwrap();let fields=line.split_whitespace().collect::<Vec<_>>();let mut at=1;macro_rules! n{($t:ty)=>{{let v=fields[at].parse::<$t>().unwrap();at+=1;v}}}
if fields[0]=="A"{let test=n!(u8)!=0;let kind=if n!(u8)!=0{RecipeKind::Basin}else{RecipeKind::Crafting};let heat=[Heat::None,Heat::Smouldering,Heat::Fading,Heat::Kindled,Heat::Seething][n!(usize)];let required=[HeatRequirement::None,HeatRequirement::Heated,HeatRequirement::Superheated][n!(usize)];let mode=n!(u8);let item_destination=n!(u8)!=0;let fluid_destination=n!(u8)!=0;let item_capability=n!(u8)!=0;let fluid_capability=n!(u8)!=0;let valid_block=n!(u8)!=0;
let mode=if mode==0{OutputMode::Internal}else{OutputMode::Spout{item_destination,fluid_destination}};let mut b=Basin{heat,mode,item_capability,fluid_capability,valid_block,..Default::default()};let mut c=C::default();let item_ingredients=n!(usize);for _ in 0..item_ingredients{c.items.push(n!(u32));}let count=n!(usize);let mut fluid_amounts=Vec::new();for _ in 0..count{c.fluids.push(n!(i32));fluid_amounts.push(n!(u32));}let count=n!(usize);let mut outputs=Vec::new();for _ in 0..count{outputs.push(Roll{stack:Item{key:n!(i32),count:n!(u32),maximum:n!(u32)},chance:n!(f32)});}let count=n!(usize);let mut fluid_outputs=Vec::new();for _ in 0..count{fluid_outputs.push(Fluid{key:n!(i32),amount:n!(u32)});}for i in 0..18{let s=Item{key:n!(i32),count:n!(u32),maximum:n!(u32)};if s.count>0{if i<9{b.input[i]=Some(s)}else{b.output[i-9]=Some(s)}}}for i in 0..4{let f=Fluid{key:n!(i32),amount:n!(u32)};if f.amount>0{if i<2{b.output_fluids[i]=Some(f)}else{b.input_fluids[i-2]=Some(f)}}}
let recipe=Recipe{kind,item_ingredients,fluid_amounts,outputs,fluid_outputs,heat:required,duration:0};let r=b.apply(&recipe,test,&mut c);print!("{} {} {}",u8::from(r.success()),c.cursor,u8::from(r.notify_all_fluid_tanks));for i in 0..18{print!(" {}",item(b.item(i)));}for i in 0..4{print!(" {}",fluid(b.fluid(i)));}print!(" I");for a in &b.overflow{print!(" {}",item(Some(a)));}print!(" F");for f in &b.fluid_overflow{print!(" {}",fluid(Some(f)));}println!();
}else{let mut speed=n!(f32);let min=n!(f32);let duration=n!(i32);let mut m=Mixer{running:n!(u8)!=0,ticks:n!(i32),processing_ticks:n!(i32)};let ticks=n!(usize);let cut=n!(i32);let repeat=n!(u8)!=0;let start=n!(u8)!=0;let remove=n!(u8)!=0;if start{m.start();}if remove{m.basin_removed();}let(mut applied,mut scheduled)=(0,0);for i in 0..ticks{if i as i32==cut{speed=0.;}let e=m.tick(speed,min,duration,||repeat);applied+=u32::from(e.apply_called);scheduled+=u32::from(e.schedule_basin_check);}println!("{} {} {} {} {}",u8::from(m.running),m.ticks,m.processing_ticks,applied,scheduled);}
let _=at;
}}
'''


def encode(case):
    out = ['A', case['test'], case['basin'], case['heat'], case['required'], case['mode'], case['item_dest'], case['fluid_dest'], case['items_present'], case['fluids_present'], case['valid']]
    out += [len(case['ingredients']), *case['ingredients'], len(case['fluid_ingredients'])]
    for entry in case['fluid_ingredients']:
        out += list(entry)
    out += [len(case['outputs'])]
    for entry in case['outputs']:
        out += list(entry)
    out += [len(case['fluid_outputs'])]
    for entry in case['fluid_outputs']:
        out += list(entry)
    for entry in case['items'] + case['fluids']:
        out += list(entry)
    return ' '.join(map(str, out))


def fixture():
    return {'test': 0, 'basin': 1, 'heat': 0, 'required': 0, 'mode': 0,
            'item_dest': 0, 'fluid_dest': 0, 'items_present': 1, 'fluids_present': 1,
            'valid': 1, 'ingredients': [], 'fluid_ingredients': [], 'outputs': [],
            'fluid_outputs': [], 'items': [(-1, 0, 64)] * 18, 'fluids': [(-1, 0)] * 4}


def cases():
    result = []
    named = {}
    c = fixture()
    c['ingredients'] = [1 << 1]
    c['items'][0] = (1, 1, 64)
    c['items'][9] = (2, 60, 64)
    c['outputs'] = [(2, 3, 64, 1), (2, 3, 64, 1)]
    result.append(encode(c)); named['source_overbooking_60_plus_3_plus_3'] = 0
    c = fixture();c['fluids'][0] = (1, 500);c['fluid_ingredients'] = [(1, 300), (1, 300)]
    named['source_partial_drain_500_for_300_plus_300'] = len(result);result.append(encode(c))
    c = fixture();c['fluids'][0] = (1, 700);c['fluid_outputs'] = [(1, 200), (1, 200)]
    named['source_fluid_overbooking_700_plus_200_plus_200'] = len(result);result.append(encode(c))
    c = fixture();c['fluid_outputs'] = [(1, 1500)]
    named['new_fluid_spans_both_empty_tanks'] = len(result);result.append(encode(c))
    c = fixture();c['fluids'][0] = (1, 1000);c['fluids'][1] = (1, 500);c['fluid_outputs'] = [(1, 100)]
    named['existing_full_matching_tank_stops_search'] = len(result);result.append(encode(c))
    c = fixture();c['items'][0] = (1, 1, 64);c['items'][1] = (2, 1, 64);c['ingredients'] = [6, 2]
    named['greedy_ingredient_order_does_not_backtrack'] = len(result);result.append(encode(c))
    c = fixture();c['items'][0] = (9, 2, 64);c['items'][9] = (2, 1, 64);c['ingredients'] = [4, 512, 512]
    named['combined_output_consumption_and_slot_order_remainders'] = len(result);result.append(encode(c))
    c = fixture();c['test'] = 1;c['outputs'] = [(1, 5, 64, .5)]
    named['matching_simulation_consumes_rng_without_inventory_change'] = len(result);result.append(encode(c))
    for requirement, heat, mode, item_dest, fluid_dest in itertools.product(range(3), range(5), range(2), range(2), range(2)):
        c = fixture();c.update(required=requirement, heat=heat, mode=mode, item_dest=item_dest, fluid_dest=fluid_dest)
        c['outputs'] = [(1, 1, 64, 1)];c['fluid_outputs'] = [(1, 100)];result.append(encode(c))
    rng = random.Random(0xBA510610)
    for i in range(2500):
        c = fixture();c.update(test=rng.randrange(4)==0, basin=rng.randrange(4)!=0, heat=rng.randrange(5), required=rng.randrange(3), mode=rng.randrange(3)==0, item_dest=rng.randrange(2), fluid_dest=rng.randrange(2), items_present=rng.randrange(20)!=0, fluids_present=rng.randrange(20)!=0, valid=rng.randrange(20)!=0)
        c['test']=int(c['test']);c['basin']=int(c['basin']);c['mode']=int(c['mode']);c['items_present']=int(c['items_present']);c['fluids_present']=int(c['fluids_present']);c['valid']=int(c['valid'])
        c['ingredients'] = [rng.randrange(1, 32) for _ in range(rng.randrange(6))]
        for slot in range(18):
            if rng.randrange(4)==0:
                key=rng.randrange(5);c['items'][slot]=(key,rng.choice([1,2,3,15,16,60,63,64]),64)
        if c['basin']:
            c['fluid_ingredients']=[(rng.randrange(3),rng.choice([100,200,300,500,1000])) for _ in range(rng.randrange(3))]
            c['outputs']=[(rng.randrange(5),rng.randrange(5),64,rng.choice([0,.25,.5,1])) for _ in range(rng.randrange(5))]
            c['fluid_outputs']=[(rng.randrange(3),rng.choice([0,100,200,300,700,1000,1500,2000])) for _ in range(rng.randrange(3))]
        else:
            c['outputs']=[(rng.randrange(5),1,64,1)]
        for tank in range(4):
            if rng.randrange(3)==0:c['fluids'][tank]=(rng.randrange(3),rng.choice([100,200,300,500,700,900,1000]))
        result.append(encode(c))
    for rpm, duration, ticks, processing, running, repeat in itertools.product([0,29,30,32,64,128,256,512,1024,-32], [0,1,100,250], [0,10,19,20,21,39,40], [-1,0,1,61], [0,1], [0,1]):
        result.append('M ' + ' '.join(map(str,[rpm,30,duration,running,ticks,processing,160,-1,repeat,0,0])))
    for cut, remove, start in itertools.product([-1,0,1,10,19,20,21,80,100],range(2),range(2)):
        result.append('M ' + ' '.join(map(str,[32,30,0,1,10,0,180,cut,0,start,remove])))
    # MechanicalMixer.read changes saved runningTicks on the existing object;
    # it does not reconstruct its transient processingTicks/currentRecipe.
    for name,case in [
        ('mixer_tick40_before_same_entity_saved_counter_update','M 32 30 0 1 0 0 40 -1 0 0 0'),
        ('mixer_same_entity_counter19_countdown_retained_before_completion','M 32 30 0 1 19 43 43 -1 0 0 0'),
        ('mixer_same_entity_counter19_countdown_retained_completion_tick84','M 32 30 0 1 19 43 44 -1 0 0 0'),
    ]:
        named[name]=len(result);result.append(case)
    return result, named


def main():
    java, javac = shutil.which('java'), shutil.which('javac')
    if not java or not javac:
        raise SystemExit('JDK required for source AST basin oracle')
    work = ROOT / '.local/basin-oracle'
    work.mkdir(parents=True, exist_ok=True)
    (work / 'BasinExport.java').write_text(EXPORT)
    subprocess.run([javac, '-d', str(work), str(work / 'BasinExport.java')], check=True)
    base = 'src/main/java/com/simibubi/create/'
    specs = [
        ('content/processing/basin/BasinRecipe.java', [('APPLY', 'apply', 3)]),
        ('content/processing/basin/BasinInventory.java', [('INSERT', 'insertItem', 3)]),
        ('content/processing/basin/BasinBlockEntity.java', [('ACCEPT', 'acceptOutputs', 3), ('ACCEPT_INNER', 'acceptOutputsInner', 3), ('ACCEPT_FLUID', 'acceptFluidOutputsIntoBasin', 3), ('ACCEPT_ITEM', 'acceptItemOutputsIntoBasin', 3)]),
        ('foundation/fluid/CombinedTankWrapper.java', [('FILL', 'fill', 2)]),
        ('content/processing/recipe/ProcessingOutput.java', [('ROLL', 'rollOutput', 1)]),
        ('foundation/recipe/DummyCraftingContainer.java', [('DUMMY', 'createInventory', 2)]),
        ('content/processing/recipe/HeatCondition.java', [('HEAT', 'testBlazeBurner', 1)]),
        ('content/kinetics/mixer/MechanicalMixerBlockEntity.java', [('TICK', 'tick', 0), ('START', 'startProcessingBasin', 0), ('REMOVE', 'onBasinRemoved', 0)]),
    ]
    program = JAVA
    for filename, methods in specs:
        path = work / Path(filename).name
        path.write_bytes(subprocess.check_output(['git','show',PINS['create_revision']+':'+base+filename],cwd=CREATE))
        for marker, method, arity in methods:
            body = subprocess.check_output([java,'-cp',str(work),'BasinExport',str(path),method,str(arity)],text=True)
            assert '@@'+marker+'@@' in program
            program=program.replace('@@'+marker+'@@',body)
    (work/'BasinOracle.java').write_text(program)
    subprocess.run([javac,'-d',str(work),str(work/'BasinOracle.java')],check=True)
    source = ROOT/'mixins/create/engine/src/core/basin.rs'
    (work/'probe.rs').write_text(RUST.replace('@@BASIN@@',str(source)))
    rustc=ROOT/'.tools/rust/bin/rustc'
    subprocess.run([str(rustc),'--edition','2024','--test',str(source),'-o',str(work/'tests')],check=True)
    test_output = subprocess.check_output([str(work/'tests')], text=True)
    print(test_output, end='')
    portable_tests = int(re.search(r'test result: ok\. (\d+) passed', test_output)[1])
    subprocess.run([str(rustc),'--edition','2024',str(work/'probe.rs'),'-o',str(work/'probe')],check=True)
    inputs,named=cases();stdin='\n'.join(inputs)+'\n'
    expected=subprocess.check_output([java,'-cp',str(work),'BasinOracle'],input=stdin,text=True).splitlines()
    actual=subprocess.check_output([str(work/'probe')],input=stdin,text=True).splitlines()
    assert len(inputs)==len(expected)==len(actual),(len(inputs),len(expected),len(actual))
    for case,want,got in zip(inputs,expected,actual):
        assert want==got,{'case':case,'java':want,'rust':got}
    report={'passed':True,'cases':len(inputs),'source_methods':13,'portable_tests':portable_tests,'reference':PINS['create_revision'],'named_cases':{name:{'input':inputs[i],'result':actual[i]} for name,i in named.items()},'scope':'unchanged AST source apply/output simulation/unique slots/fluid fill/RNG/dummy remainders/heat/server mixer tick; explicit host contexts, no native machine/fluids/effects or GUI'}
    (work/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='named_cases'}))
    return report


if __name__=='__main__':
    main()
