#!/usr/bin/env python3
"""Compare milling tick, RPM, process and chance rolls to pinned Java method bodies.

Minecraft/NeoForge inventories, recipe lookup and world are development contexts;
the actual Java method bodies are extracted through javac's AST. The native game
checks separately cover components, filtered hopper IO, original NBT and reload.
"""
import itertools
import json
import shutil
import subprocess
from common import CREATE, PINS, ROOT, cargo


def main():
    java, javac = shutil.which('java'), shutil.which('javac')
    if not java or not javac:
        raise SystemExit('A JDK is required for the milling Java oracle')
    work = ROOT / '.local/milling-oracle'
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run([javac, '-d', str(work), str(ROOT / 'tools/java/ExportMethod.java')], check=True)
    template = (ROOT / 'tools/java/MillingOracle.java.in').read_text()
    base = 'src/main/java/com/simibubi/create/'
    for filename, methods in [
        ('content/kinetics/millstone/MillstoneBlockEntity.java', [('SPEED', 'getProcessingSpeed'), ('TICK', 'tick'), ('PROCESS', 'process')]),
        ('content/processing/recipe/ProcessingOutput.java', [('ROLL', 'rollOutput')]),
    ]:
        source = work / filename.rsplit('/', 1)[-1]
        source.write_bytes(subprocess.check_output(['git', 'show', PINS['create_revision'] + ':' + base + filename], cwd=CREATE))
        for marker, method in methods:
            body = subprocess.check_output([java, '-cp', str(work), 'ExportMethod', str(source), method], text=True)
            template = template.replace('@@' + marker + '@@', body)
    source = work / 'MillingOracle.java'
    source.write_text(template)
    subprocess.run([javac, '-d', str(work), str(source)], check=True)
    cases = [f'S {rpm / 8}' for rpm in range(-8193, 8194)]
    cases += [f'S {rpm}' for rpm in [-1e30, -8193, -8192, 8192, 8193, 1e30]]
    cases += [f'T {rpm} {timer} {count} {valid} {duration} {output} {ticks} {remove}'
              for rpm, timer, count, valid, duration, output, ticks, remove in itertools.product(
                  [0, .5, -16, 64, 256, 8192], [0, 1, -15, 100], [0, 1, 4], [0, 1],
                  [0, 1, 200], [0, 63, 64], [1, 12, 205], [-1, 1])]
    cases += [f'R {seed} {count} {chance}' for seed, count, chance in itertools.product(
        [0, 1, 17, 123456789, 281474976710655], [0, 1, 2, 9, 64, 99], [0, .01, .25, .5, .75, .99, 1, 2])]
    inputs = '\n'.join(cases) + '\n'
    expected = subprocess.check_output([java, '-cp', str(work), 'MillingOracle'], input=inputs, text=True).splitlines()
    cargo('build', '--locked', '--example', 'milling_probe', '--target-dir', ROOT / 'target/core')
    actual = subprocess.check_output([str(ROOT / 'target/core/debug/examples/milling_probe')], input=inputs, text=True).splitlines()
    assert len(expected) == len(actual) == len(cases)
    for case, original, port in zip(cases, expected, actual):
        assert original == port, {'case': case, 'java': original, 'rust': port}
    result = {'passed': len(cases), 'reference': PINS['create_revision'],
              'scope': 'AST-exported MillstoneBlockEntity.tick/process/getProcessingSpeed and ProcessingOutput.rollOutput; recipe/inventory development contexts'}
    (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
