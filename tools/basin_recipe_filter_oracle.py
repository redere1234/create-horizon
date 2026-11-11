#!/usr/bin/env python3
"""Compare the default compression predicate with pinned MIT Java method bodies.

Ingredient display arrays are controlled (including empty arrays and order).
This does not claim recipe-manager, native item predicate or world parity.
"""
import argparse
import hashlib
import json
from pathlib import Path
import random
import shutil
import subprocess
import tempfile

from basin_oracle import EXPORT
from common import CREATE, PINS, ROOT


JAVA = r'''import java.util.*;
public class BasinRecipeFilterOracle {
 static class ItemStack {String item;ItemStack(String s){item=s;}
  static boolean isSameItem(ItemStack a,ItemStack b){return a.item.equals(b.item);}}
 static class Ingredient {ItemStack[] display;Ingredient(List<String> ids){display=ids.stream().map(ItemStack::new).toArray(ItemStack[]::new);}ItemStack[] getItems(){return display;}}
 static class NonNullList<T> extends ArrayList<T>{}
 interface Recipe<T>{NonNullList<Ingredient> getIngredients();}
 static class CraftingRecipe implements Recipe<Object>{NonNullList<Ingredient> inputs=new NonNullList<>();public NonNullList<Ingredient> getIngredients(){return inputs;}}
 static class ConfigValue {boolean get(){return true;}}
 static class RecipeConfig {ConfigValue allowShapedSquareInPress=new ConfigValue();}
 static class Config {RecipeConfig recipes=new RecipeConfig();}
 static class AllConfigs {static Config server(){return new Config();}}
 static class ItemHelper {
  static boolean matchIngredients(Ingredient i1,Ingredient i2) @@MATCH@@
  static boolean matchAllIngredients(NonNullList<Ingredient> ingredients) @@ALL@@
 }
 static boolean canCompress(Recipe<?> recipe) @@COMPRESS@@
 public static void main(String[] args){var in=new Scanner(System.in);while(in.hasNextInt()){
  var recipe=new CraftingRecipe();int count=in.nextInt();for(int i=0;i<count;i++){
   int n=in.nextInt();var display=new ArrayList<String>();for(int j=0;j<n;j++)display.add(in.next());
   recipe.inputs.add(new Ingredient(display));
  }System.out.println(canCompress(recipe)?1:0);
 }}
}'''


def rust_function(text, name):
    start = text.index('fn ' + name + '(')
    brace = text.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


def run(source):
    source = Path(source).resolve()
    before = source.read_bytes()
    work = Path(tempfile.mkdtemp(prefix='basin-recipe-filter-', dir=ROOT / '.local'))
    report = {'passed': False, 'scope': __doc__, 'create': PINS['create_revision'],
              'native_source': str(source),
              'native_sha256': hashlib.sha256(before).hexdigest(), 'source_bodies_sha256': {}}
    print(json.dumps({'work': str(work)}), flush=True)
    javac, java = shutil.which('javac'), shutil.which('java')
    assert javac and java, 'JDK required'
    (work / 'BasinExport.java').write_text(EXPORT)
    subprocess.run([javac, '-d', str(work), str(work / 'BasinExport.java')], check=True)
    program = JAVA
    specs = [('content/kinetics/press/MechanicalPressBlockEntity.java', [('COMPRESS', 'canCompress', 1)]),
             ('foundation/item/ItemHelper.java', [('MATCH', 'matchIngredients', 2), ('ALL', 'matchAllIngredients', 1)])]
    try:
        for name, methods in specs:
            relative = 'src/main/java/com/simibubi/create/' + name
            original = subprocess.check_output(['git', 'show', PINS['create_revision'] + ':' + relative], cwd=CREATE)
            path = work / Path(name).name
            path.write_bytes(original)
            for marker, method, arity in methods:
                body = subprocess.check_output([java, '-cp', str(work), 'BasinExport', str(path), method, str(arity)], text=True)
                report['source_bodies_sha256'][method] = hashlib.sha256(body.encode()).hexdigest()
                program = program.replace('@@' + marker + '@@', body)
        assert '@@' not in program
        (work / 'BasinRecipeFilterOracle.java').write_text(program)
        subprocess.run([javac, '-d', str(work), str(work / 'BasinRecipeFilterOracle.java')], check=True)
        predicate = rust_function(before.decode(), 'can_compress')
        rust = '''use std::io::{self,Read};
struct Ingredient {order: Vec<String>}
''' + predicate + '''
fn main(){let mut input=String::new();io::stdin().read_to_string(&mut input).unwrap();let mut words=input.split_whitespace();while let Some(n)=words.next(){let n=n.parse::<usize>().unwrap();let mut inputs=Vec::new();for _ in 0..n{let count=words.next().unwrap().parse::<usize>().unwrap();inputs.push(Ingredient{order:(0..count).map(|_|words.next().unwrap().to_owned()).collect()});}println!("{}",u8::from(can_compress(&inputs)));}}
'''
        (work / 'probe.rs').write_text(rust)
        subprocess.run([str(ROOT / '.tools/rust/bin/rustc'), '--edition=2024', str(work / 'probe.rs'), '-o', str(work / 'probe')], check=True)
        displays = [[], ['minecraft:iron_ingot'], ['minecraft:iron_ingot', 'minecraft:gold_ingot'],
                    ['minecraft:gold_ingot', 'minecraft:iron_ingot'], ['minecraft:iron_ingot', 'minecraft:iron_ingot']]
        cases = []
        for n in range(13):
            for display in displays:
                cases.append([display] * n)
                for at in range(n):
                    for alternative in displays:
                        row = [display] * n
                        row[at] = alternative
                        cases.append(row)
        rng = random.Random(923)
        cases.extend([rng.choice(displays) for _ in range(rng.randrange(13))] for _ in range(1000))
        inputs = ''.join(str(len(row)) + ' ' + ' '.join(str(len(d)) + ' ' + ' '.join(d) for d in row) + '\n' for row in cases)
        (work / 'inputs.txt').write_text(inputs)
        outputs = []
        for name, command in [('java', [java, '-cp', str(work), 'BasinRecipeFilterOracle']), ('rust', [str(work / 'probe')])]:
            result = subprocess.run(command, input=inputs, capture_output=True, text=True, check=True)
            (work / (name + '.txt')).write_text(result.stdout)
            outputs.append(result.stdout.splitlines())
        assert len(outputs[0]) == len(outputs[1]) == len(cases)
        for i, (expected, actual) in enumerate(zip(*outputs)):
            assert expected == actual, (i, cases[i], expected, actual)
        assert before == source.read_bytes(), 'candidate changed during comparison'
        report.update(passed=True, cases=len(cases), predicate_sha256=hashlib.sha256(predicate.encode()).hexdigest())
    finally:
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'passed': report['passed'], 'result': str(work / 'result.json')}), flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'mixins/create/basin_recipes.rs')
    args = parser.parse_args()
    run(args.source)
