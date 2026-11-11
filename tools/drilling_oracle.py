#!/usr/bin/env python3
"""Stationary drill parity against AST-exported pinned Create Java algorithms.

The Java context stubs world IO; actual block loot, player independence, NBT,
six facings and pause/resume are covered by drilling_checks in the native game.
"""
import itertools
import json
import shutil
import subprocess
from common import CREATE, PINS, ROOT, cargo


def main():
    java, javac = shutil.which('java'), shutil.which('javac')
    if not java or not javac:
        raise SystemExit('A JDK is required for the drilling oracle')
    work = ROOT / '.local/drilling-oracle'
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run([javac, '-d', str(work), str(ROOT / 'tools/java/ExportMethod.java')], check=True)
    template = (ROOT / 'tools/java/DrillingOracle.java.in').read_text()
    base = 'src/main/java/com/simibubi/create/content/kinetics/'
    for filename, methods in [
        ('base/BlockBreakingKineticBlockEntity.java', [('BREAKABLE', 'isBreakable'), ('SPEED', 'getBreakSpeed'), ('WAKE', 'destroyNextTick'), ('TICK', 'tick')]),
        ('drill/DrillBlock.java', [('DAMAGE', 'getDamage')]),
    ]:
        source = work / filename.rsplit('/', 1)[-1]
        source.write_bytes(subprocess.check_output(['git', 'show', PINS['create_revision'] + ':' + base + filename], cwd=CREATE))
        for marker, method in methods:
            body = subprocess.check_output([java, '-cp', str(work), 'ExportMethod', str(source), method], text=True)
            template = template.replace('@@' + marker + '@@', body)
    source = work / 'DrillingOracle.java'
    source.write_text(template)
    subprocess.run([javac, '-d', str(work), str(source)], check=True)
    cases = [f'{kind} {rpm / 8}' for kind, rpm in itertools.product(['S', 'D'], range(-8192, 8193))]
    cases += [f'T {rpm} {hardness} {flags} {progress} {delay} {ticks} {wake} {stop} {resume}'
              for rpm, hardness, flags, progress, delay, ticks, wake, stop, resume in itertools.product(
                  [0, .25, -16, 32, 256], [-1, 0, .5, 1.5, 50], [0, 1, 2, 4], [0, 5, 9],
                  [-1, 0, 1, 15], [1, 12, 60], [-1, 3], [5], [22])]
    data = '\n'.join(cases) + '\n'
    expected = subprocess.check_output([java, '-cp', str(work), 'DrillingOracle'], input=data, text=True).splitlines()
    cargo('build', '--locked', '--example', 'drilling_probe', '--target-dir', ROOT / 'target/core')
    actual = subprocess.check_output([str(ROOT / 'target/core/debug/examples/drilling_probe')], input=data, text=True).splitlines()
    assert len(cases) == len(expected) == len(actual)
    for case, original, port in zip(cases, expected, actual):
        equal = abs(float(original) - float(port)) < 1e-5 if case[0] in 'SD' else original == port
        assert equal, {'case': case, 'java': original, 'rust': port}
    result = {'passed': len(cases), 'reference': PINS['create_revision'],
              'scope': 'AST-exported stationary drill tick, breakability, speed, wake, damage; world IO development contexts'}
    (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
