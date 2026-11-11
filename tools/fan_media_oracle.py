"""Check all four unmodified AllFanProcessingTypes.isValidAt methods.

Exhaustive tag/property test contexts include contradictory custom tags. Native
registry loading, flow occlusion, entities and recipe application are separate.
"""
import hashlib
import itertools
import json
import shutil
import subprocess
from common import CREATE, PINS, ROOT, cargo


def main():
    java, javac = shutil.which('java'), shutil.which('javac')
    assert java and javac, 'JDK required'
    work = ROOT / '.local/fan-media-oracle'
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run([javac, '-d', str(work), str(ROOT/'tools/java/ExportMethod.java')], check=True)
    path = 'src/main/java/com/simibubi/create/content/kinetics/fan/processing/AllFanProcessingTypes.java'
    original = subprocess.check_output(['git', 'show', PINS['create_revision']+':'+path], cwd=CREATE)
    source = work/'AllFanProcessingTypes.java'
    source.write_bytes(original)
    template = (ROOT/'tools/java/FanMediaOracle.java.in').read_text()
    for kind in ['BlastingType', 'HauntingType', 'SmokingType', 'SplashingType']:
        body = subprocess.check_output([java, '-cp', str(work), 'ExportMethod', str(source), 'isValidAt', kind], text=True)
        template = template.replace('@@'+kind+'@@', body)
    generated = work/'FanMediaOracle.java'
    generated.write_text(template)
    subprocess.run([javac, '-d', str(work), str(generated)], check=True)
    cases = [' '.join(map(str,v)) for v in itertools.product(range(16),range(16),range(2),range(3),range(3),range(6))]
    stdin = '\n'.join(cases)+'\n'
    expected = subprocess.check_output([java, '-cp', str(work), 'FanMediaOracle'], input=stdin, text=True).splitlines()
    cargo('build', '--locked', '--example', 'fan_media_probe', '--target-dir', ROOT/'target/core')
    actual = subprocess.check_output([str(ROOT/'target/core/debug/examples/fan_media_probe')], input=stdin, text=True).splitlines()
    assert len(expected) == len(actual) == len(cases)
    for case, want, got in zip(cases, expected, actual):
        assert want == got, {'case':case,'java':want,'rust':got}
    result = {'passed':len(cases),'reference':PINS['create_revision'],'java_source_sha256':hashlib.sha256(original).hexdigest(),'scope':__doc__}
    (work/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
