"""Compare server burner transitions to four unchanged pinned Java method bodies.

World writes, data-map lookup and item fuel values are explicit test contexts;
the original methods own fuel precedence, simulation, timer and heat transitions.
This does not assert a registered native burner or client presentation.
"""
import hashlib
import itertools
import json
import random
import shutil
import subprocess

from common import CREATE, PINS, ROOT, cargo


def main():
    java, javac = shutil.which('java'), shutil.which('javac')
    assert java and javac, 'JDK required'
    work = ROOT / '.local/burner-oracle'
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run([javac, '-d', str(work), str(ROOT/'tools/java/ExportMethod.java')], check=True)
    path = 'src/main/java/com/simibubi/create/content/processing/burner/BlazeBurnerBlockEntity.java'
    original = subprocess.check_output(['git', 'show', PINS['create_revision']+':'+path], cwd=CREATE)
    source = work/'BlazeBurnerBlockEntity.java'
    source.write_bytes(original)
    template = (ROOT/'tools/java/BurnerOracle.java.in').read_text()
    methods = [('HEAT', 'getHeatLevel'), ('TICK', 'tick'),
               ('INSERT', 'tryUpdateFuel'), ('CREATIVE', 'applyCreativeFuel')]
    for marker, method in methods:
        body = subprocess.check_output([java, '-cp', str(work), 'ExportMethod', str(source), method], text=True)
        template = template.replace('@@'+marker+'@@', body)
    generated = work/'BurnerOracle.java'
    generated.write_text(template)
    subprocess.run([javac, '-d', str(work), str(generated)], check=True)
    times = [-2147483648, -1, 0, 1, 2, 124, 125, 126, 500, 501, 9999, 10000, 2147483647]
    cases = ['R '+' '.join(map(str, values)) for values in itertools.product(
        [-1, 0, 7, 3200], [-1, 0, 8, 1600], [0,1], [-1,0,1,9,1600,2147483647], [0,1])]
    cases += ['T '+' '.join(map(str, values)) for values in itertools.product(
        range(3), times, [0,1], range(5), [1,2,126,5001])]
    cases += ['C '+' '.join(map(str, values)) for values in itertools.product(
        range(3), [-1,0,1,500,10000], [0,1], range(5))]
    cases += ['I '+' '.join(map(str, values)) for values in itertools.product(
        range(3), times, [0,1], [1,3,4], [1,2], [1,1600,2147483647], [0,1], [0,1])]
    rng = random.Random(610)
    for _ in range(10000):
        candidate = rng.randrange(3)
        cases.append('I '+' '.join(map(str, [rng.randrange(3), rng.randint(-2147483648,2147483647),
            rng.randrange(2), rng.randrange(5), candidate,
            rng.randint(-2147483648,2147483647) if candidate else 0, rng.randrange(2), rng.randrange(2)])))
    stdin = '\n'.join(cases)+'\n'
    expected = subprocess.check_output([java, '-cp', str(work), 'BurnerOracle'], input=stdin, text=True).splitlines()
    cargo('build', '--locked', '--example', 'burner_probe', '--target-dir', ROOT/'target/core')
    actual = subprocess.check_output([str(ROOT/'target/core/debug/examples/burner_probe')], input=stdin, text=True).splitlines()
    assert len(expected) == len(actual) == len(cases)
    for case, want, got in zip(cases, expected, actual):
        assert want == got, {'case':case, 'java':want, 'rust':got}
    result = {'passed':len(cases), 'reference':PINS['create_revision'],
              'java_source_sha256':hashlib.sha256(original).hexdigest(),
              'methods':[method for _,method in methods], 'scope':__doc__}
    (work/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
