#!/usr/bin/env python3
"""Compare fan algorithms against unchanged AST-exported Create method bodies.

The fixture supplies default configuration and minimal item/registry/NBT contexts.
It verifies range, direction, propeller speed and every timer transition, not
airflow collision sampling, entity movement, recipe results or Horizon IO.
"""
import itertools
import json
import random
import shutil
import subprocess

from common import CREATE, PINS, ROOT, cargo


EXPORTER = r'''
import com.sun.source.tree.*;
import com.sun.source.util.*;
import javax.tools.*;
import java.nio.file.*;
import java.util.*;
public class ExportFanMethod {
 public static void main(String[] args)throws Exception {
  var compiler=ToolProvider.getSystemJavaCompiler();
  try(var files=compiler.getStandardFileManager(null,null,null)) {
   var task=(JavacTask)compiler.getTask(null,files,null,List.of("-proc:none"),null,files.getJavaFileObjects(args[0]));
   var tree=task.parse().iterator().next();var positions=Trees.instance(task).getSourcePositions();
   var source=Files.readString(Path.of(args[0]));var bodies=new ArrayList<String>();
   new TreeScanner<Void,Void>() {
    public Void visitMethod(MethodTree method,Void unused) {
     if(method.getName().contentEquals(args[1]) && method.getBody()!=null
       && (args.length<3 || method.getParameters().getFirst().getType().toString().equals(args[2]))) {
      var body=method.getBody();bodies.add(source.substring((int)positions.getStartPosition(tree,body),(int)positions.getEndPosition(tree,body)));
     }return super.visitMethod(method,unused);
    }
   }.scan(tree,null);
   if(bodies.size()!=1)throw new IllegalStateException("Expected one method: "+Arrays.toString(args));
   System.out.print(bodies.getFirst());
  }
 }
}
'''


def cases():
    result = [f'M {rpm / 8}' for rpm in range(-4096, 4097)]
    result += [f'V {rpm / 8}' for rpm in range(-4096, 4097)]
    result += [f'P {rpm} {direction}' for rpm, direction in
               itertools.product([-256, -16, -.125, 0, .125, 16, 256], range(6))]
    # Record each call, including the first conversion, post-conversion -1 and
    # transported post-decrement semantics. Counts straddle every 16-item step.
    sizes = [1, 2, 15, 16, 17, 31, 32, 33, 47, 48, 49, 63, 64]
    for mode, kind, count, valid in itertools.product('DT', range(4), sizes, range(2)):
        result.append(f'{mode} -1 0 {kind},{count},{valid},{150 * ((count - 1) // 16 + 1) + 5}')
    # Applicability is cached for a type; count changes do not restart a timer.
    # Switching away and back restarts even when the new medium is invalid.
    for mode, a, b, count in itertools.product('DT', range(4), range(4), sizes):
        other = (a + 1) % 4
        result.append(f'{mode} -1 0 {a},{count},1,3 {a},64,0,3 '
                      f'{b},1,0,3 {other},17,1,302 {a},{count},1,4')
    # Restored boundary states exercise the source's distinguished -1 sentinel.
    for mode, kind, time, valid in itertools.product('DT', range(4), [-3, -2, -1, 0, 1, 2, 150, 151], range(2)):
        result.append(f'{mode} {kind} {time} {kind},17,{valid},4')
    rng = random.Random(0xCFE05)
    for mode in 'DT':
        for _ in range(250):
            phases = ' '.join(f'{rng.randrange(4)},{rng.choice(sizes)},{rng.randrange(2)},{rng.randrange(1, 180)}'
                              for _ in range(8))
            result.append(f'{mode} -1 0 {phases}')
    return result


def main():
    java, javac = shutil.which('java'), shutil.which('javac')
    if not java or not javac:
        raise SystemExit('A JDK is required for this development-only oracle')
    work = ROOT / '.local/fan-oracle'
    work.mkdir(parents=True, exist_ok=True)
    exporter = work / 'ExportFanMethod.java'
    exporter.write_text(EXPORTER)
    subprocess.run([javac, '-d', str(work), str(exporter)], check=True)
    template = (ROOT / 'tools/java/FanOracle.java.in').read_text()
    methods = [
        ('RANGE', 'fan/IAirCurrentSource', 'getMaxDistance', None),
        ('DIRECTION', 'fan/EncasedFanBlockEntity', 'getAirFlowDirection', None),
        ('CONVERT', 'base/KineticBlockEntity', 'convertToDirection', None),
        ('PROPELLER', 'fan/FanVisual', 'getFanSpeed', None),
        ('CAN_PROCESS', 'fan/processing/FanProcessing', 'canProcess', None),
        ('DROPPED', 'fan/processing/FanProcessing', 'applyProcessing', 'ItemEntity'),
        ('TRANSPORTED', 'fan/processing/FanProcessing', 'applyProcessing', 'TransportedItemStack'),
        ('DECREMENT', 'fan/processing/FanProcessing', 'decrementProcessingTime', None),
    ]
    for marker, path, method, first_type in methods:
        source = work / (path.rsplit('/', 1)[-1] + '.java')
        source.write_bytes(subprocess.check_output([
            'git', 'show', PINS['create_revision'] + ':src/main/java/com/simibubi/create/content/kinetics/' + path + '.java'
        ], cwd=CREATE))
        command = [java, '-cp', str(work), 'ExportFanMethod', str(source), method]
        if first_type:
            command.append(first_type)
        body = subprocess.check_output(command, text=True)
        template = template.replace('@@' + marker + '@@', body)
    source = work / 'FanOracle.java'
    source.write_text(template)
    subprocess.run([javac, '-d', str(work), str(source)], check=True)
    inputs = cases()
    stdin = '\n'.join(inputs) + '\n'
    expected = subprocess.check_output([java, '-cp', str(work), 'FanOracle'], input=stdin, text=True).splitlines()
    cargo('build', '--locked', '--example', 'fan_probe', '--target-dir', ROOT / 'target/core')
    actual = subprocess.check_output([str(ROOT / 'target/core/debug/examples/fan_probe')], input=stdin, text=True).splitlines()
    assert len(expected) == len(actual) == len(inputs)
    transitions = 0
    for case, java_result, rust_result in zip(inputs, expected, actual):
        if case[0] in 'MV':
            equal = abs(float(java_result) - float(rust_result)) < 1e-6
        else:
            equal = java_result == rust_result
        assert equal, {'case': case, 'java': java_result, 'rust': rust_result}
        if case[0] in 'DT':
            transitions += len(java_result.split())
    result = {'passed': len(inputs), 'timer_transitions': transitions, 'reference': PINS['create_revision'],
              'scope': 'AST-exported default range, all-six facing direction, propeller speed and full dropped/transported timer traces; minimal recipe/NBT/registry context'}
    (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
