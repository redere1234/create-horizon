#!/usr/bin/env python3
"""Strict schematic codec checks and reusable isolated native import checks.

Default CLI runs portable Rust checks and a JDK modified-UTF8 oracle, never a
game. `run(call, ..., scratch=...)` is for the existing disposable-game harness;
it neither starts a client nor operates on the prepared review/user world.
All schematic geometry below is authored here, not copied from Create assets.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import random
import re
import shutil
import struct
import subprocess
import tempfile

from common import ROOT, cargo


def _mutf8(text):
    # Independent fixture writer: Java's UTF-16 units, not UTF-8 code points.
    result = bytearray()
    units = text.encode('utf-16-be')
    for index in range(0, len(units), 2):
        unit = int.from_bytes(units[index:index + 2], 'big')
        if 0 < unit < 128:
            result.append(unit)
        elif unit < 2048:
            result.extend((192 | unit >> 6, 128 | unit & 63))
        else:
            result.extend((224 | unit >> 12, 128 | unit >> 6 & 63, 128 | unit & 63))
    return bytes(result)


def _string(text):
    encoded = _mutf8(text)
    return struct.pack('>H', len(encoded)) + encoded


def _payload(tag):
    kind, value = tag
    if kind in {1, 2, 3, 4, 5, 6}:
        return struct.pack({1: '>b', 2: '>h', 3: '>i', 4: '>q', 5: '>f', 6: '>d'}[kind], value)
    if kind == 8:
        return _string(value)
    if kind == 9:
        element, values = value
        return bytes([element]) + struct.pack('>i', len(values)) + b''.join(_payload((element, child)) for child in values)
    if kind == 10:
        return b''.join(bytes([child[0]]) + _string(name) + _payload(child) for name, child in value.items()) + b'\0'
    if kind in {7, 11, 12}:
        return struct.pack('>i', len(value)) + b''.join(struct.pack({7: '>b', 11: '>i', 12: '>q'}[kind], child) for child in value)
    raise ValueError(f'Unsupported fixture tag {kind}')


def _write(path, root):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(b'\x0a\0\0' + _payload((10, root)), mtime=0))


def _fixture():
    def palette(name, **properties):
        value = {'Name': (8, name)}
        if properties:
            value['Properties'] = (10, {key: (8, item) for key, item in properties.items()})
        return value

    def block(pos, state, nbt=None):
        value = {'pos': (9, (3, pos)), 'state': (3, state)}
        if nbt is not None:
            value['nbt'] = (10, nbt)
        return value

    return {
        'DataVersion': (3, 3955), 'size': (9, (3, [4, 3, 2])),
        'palette': (9, (10, [
            palette('minecraft:smooth_stone'), palette('create:creative_motor', facing='east'),
            palette('create:shaft', axis='x', waterlogged='true'),
            palette('create:mechanical_press', facing='east'), palette('create:depot'), palette('minecraft:air'),
        ])),
        'blocks': (9, (10, [
            block([0, 0, 0], 0),
            block([0, 2, 0], 1, {'id': (8, 'create:motor'), 'ScrollValue': (3, 128), 'Speed': (5, 999.0), 'x': (3, 900), 'y': (3, 80), 'z': (3, -500)}),
            block([1, 2, 0], 2), block([2, 2, 0], 3, {'id': (8, 'create:mechanical_press')}),
            block([2, 0, 0], 4, {'id': (8, 'create:depot')}), block([3, 2, 0], 5),
        ])),
        'entities': (9, (10, [])),
    }


def write_fixtures(directory):
    """Write independent valid and invalid inputs; return names and SHA256s."""
    import copy
    directory = Path(directory)
    _write(directory / 'own-press.nbt', _fixture())
    mutations = {
        'unsupported-id': lambda root: root['palette'][1][1].append({'Name': (8, 'unported:missing')}),
        'unsupported-belt': lambda root: root['palette'][1][1].append({'Name': (8, 'create:belt'), 'Properties': (10, {'facing': (8, 'south'), 'slope': (8, 'horizontal'), 'part': (8, 'start'), 'casing': (8, 'false'), 'waterlogged': (8, 'false')})}),
        'unsupported-cased-belt': lambda root: root['palette'][1][1].append({'Name': (8, 'create:belt'), 'Properties': (10, {'facing': (8, 'south'), 'slope': (8, 'horizontal'), 'part': (8, 'start'), 'casing': (8, 'true'), 'waterlogged': (8, 'false')})}),
        'invalid-property': lambda root: root['palette'][1][1][2]['Properties'][1].update(axis=(8, 'diagonal')),
        'unknown-be-field': lambda root: root['blocks'][1][1][1]['nbt'][1].update(Mystery=(3, 7)),
        'wrong-be-id': lambda root: root['blocks'][1][1][1]['nbt'][1].update(id=(8, 'create:drill')),
        'wrong-be-type': lambda root: root['blocks'][1][1][1]['nbt'][1].update(ScrollValue=(4, 128)),
        'unknown-version': lambda root: root.update(DataVersion=(3, 3465)),
        'unsupported-entity': lambda root: root['entities'][1][1].append({'pos': (9, (6, [0., 0., 0.])), 'blockPos': (9, (3, [0, 0, 0])), 'nbt': (10, {'id': (8, 'create:super_glue')})}),
        'bad-index': lambda root: root['blocks'][1][1][0].update(state=(3, 99)),
        'outside-bounds': lambda root: root['blocks'][1][1][0].update(pos=(9, (3, [-1, 0, 0]))),
        'duplicate-pos': lambda root: root['blocks'][1][1].append(copy.deepcopy(root['blocks'][1][1][0])),
    }
    for name, mutate in mutations.items():
        root = copy.deepcopy(_fixture())
        mutate(root)
        _write(directory / (name + '.nbt'), root)
    (directory / 'malformed-gzip.nbt').write_bytes(b'not a gzip member')
    names = ['own-press.nbt', 'malformed-gzip.nbt'] + [name + '.nbt' for name in mutations]
    return {name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in sorted(names)}


def _json_reply(reply):
    for message in reply.get('chat', []):
        try:
            report = json.loads(message)
        except (ValueError, TypeError):
            continue
        if isinstance(report, dict) and 'ok' in report:
            return report
    if isinstance(reply, dict) and 'ok' in reply and 'issues' in reply:
        return reply
    raise AssertionError(('No schematic JSON command reply', reply))


def run(call, graphics=False, log=None, scratch=None, schematics_dir=None):
    """Run only inside a caller-owned disposable `.local` instance.

    `schematics_dir` can name the adapter's actual home/schematics directory;
    otherwise the source Create game-dir convention is scratch/schematics.
    """
    scratch = Path(scratch).resolve()
    scratch.relative_to((ROOT / '.local').resolve())
    directory = Path(schematics_dir or scratch / 'schematics').resolve()
    directory.relative_to(scratch)
    hashes = write_fixtures(directory)
    anchor = (144, 64, 0)
    x, y, z = anchor
    transcript = []
    (scratch / 'schematic-native-result.json').write_text(json.dumps({'passed': False, 'status': 'running'}) + '\n')

    def command(mode, name):
        line = f'create schematic {mode} {name}'
        if mode == 'paste':
            line += f' {x} {y} {z}'
        report = _json_reply(call('command', line))
        transcript.append({'command': line, 'report': report})
        return report

    def snapshot():
        return [call('block', x + dx, y + dy, z + dz)['state']
                for dx in range(4) for dy in range(3) for dz in range(2)]

    def data(dx, dy, dz):
        return ' '.join(call('command', f'data get block {x + dx} {y + dy} {z + dz}')['chat'])

    call('command', f'tp @s {x + 2.5} {y + 4} {z + 4.5}')
    call('wait', 5)
    call('wait-ready', 120)
    # A TP acknowledgement can precede the next server chunk request. Scene
    # readiness alone must not make a failed server fill look like setup.
    for attempt in range(12):
        corners = [call('command', f'execute if loaded {px} {y} {pz} run say schematic_corner_loaded')
                   for px in [x - 1, x + 7] for pz in [z - 1, z + 6]]
        if all(any('schematic_corner_loaded' in line for line in c['chat']) for c in corners):
            break
        call('wait', 5)
    else:
        raise AssertionError(('Schematic fixture corner not loaded', corners))
    for state, top in [('minecraft:air', y + 4), ('minecraft:smooth_stone', y - 1)]:
        filled = call('command', f'fill {x - 1} {y - 1} {z - 1} {x + 7} {top} {z + 6} {state}')
        assert not any('not loaded' in line for line in filled['chat']), filled
    call('command', f'setblock {x} {y + 2} {z} minecraft:diamond_block')
    call('command', f'setblock {x + 3} {y + 2} {z} minecraft:gold_block')
    call('wait', 5)
    assert call('block', x, y + 2, z)['block'] == 'minecraft:diamond_block'
    assert call('block', x + 3, y + 2, z)['block'] == 'minecraft:gold_block'
    server_gold = call('command', f'execute if block {x + 3} {y + 2} {z} minecraft:gold_block run say schematic_air_before_gold')
    assert any('schematic_air_before_gold' in line for line in server_gold.get('chat', [])), server_gold
    call('command', 'tick freeze')
    try:
        before = snapshot()
        report = command('inspect', 'own-press.nbt')
        assert report['ok'] and report['blocks'] == 5 and report['skipped_air'] == 1, report
        assert report['size'] == [4, 3, 2], report
        assert snapshot() == before, 'Inspect changed destination blocks'
        for name in sorted(set(hashes) - {'own-press.nbt'}):
            for mode in ['inspect', 'paste']:
                report = command(mode, name)
                assert not report['ok'] and report['issues'], (name, mode, report)
            assert snapshot() == before, (name, 'Rejected paste changed the world')
        report = command('paste', '../own-press.nbt')
        assert not report['ok'] and report['issues'], report
        assert snapshot() == before, 'Traversal rejection changed the world'
        report = command('paste', 'own-press.nbt')
        assert report['ok'] and report['blocks'] == 5, report
        call('wait', 5)
        server_gold = call('command', f'execute if block {x + 3} {y + 2} {z} minecraft:gold_block run say schematic_air_after_gold')
        assert any('schematic_air_after_gold' in line for line in server_gold.get('chat', [])), server_gold
        assert call('block', x, y + 2, z)['block'] == 'create:creative_motor'
        shaft = call('block', x + 1, y + 2, z)['state']
        assert 'axis=x' in shaft and 'waterlogged=false' in shaft, shaft
        assert call('block', x + 3, y + 2, z)['block'] == 'minecraft:gold_block', 'Default air policy must preserve destination'
        assert 'ScrollValue: 128' in data(0, 2, 0), data(0, 2, 0)
    finally:
        call('command', 'tick unfreeze')
        (scratch / 'schematic-native-transcript.json').write_text(json.dumps(transcript, indent=2) + '\n')
    call('wait', 12)
    motor = data(0, 2, 0)
    press = data(2, 2, 0)
    assert re.search(r'\bSpeed:\s*128(?:[f.,}])', motor), motor
    assert re.search(r'\bSpeed:\s*128(?:[f.,}])', press), press
    call('container', x + 2, y, z, 'minecraft:copper_ingot', 1)
    call('wait', 180)
    slots = call('container', x + 2, y, z)['slots']
    assert sum(slot['count'] for slot in slots if slot and slot['item'] == 'create:copper_sheet') == 1, slots
    assert hashes == {name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in hashes}, 'Import changed input files'
    images = []
    if graphics:
        support = call('command', f'execute if block {x + 5} {y - 1} {z + 4} minecraft:smooth_stone run say schematic_support_present')
        assert any('schematic_support_present' in line for line in support['chat']), support
        call('command', f'tp @s {x + 5.5} {y} {z + 4.5}')
        call('wait', 3)
        player = call('state')['player']
        assert player['on_ground'] and abs(player['position'][1] - y) < .001, player
        call('look-at', x + 1.5, y + 1.5, z + .5)
        call('wait', 8)
        image = scratch / 'schematic-native.png'
        call('key', 'f1', 'tap')
        try:
            call('wait', 2)
            call('screenshot', image)
        finally:
            call('key', 'f1', 'tap')
        images.append(str(image))
    report = {'passed': True, 'anchor': anchor, 'fixture_hashes': hashes,
              'rejected_fixtures': len(hashes) - 1, 'blocks': 5, 'source_safe_nbt': True,
              'press_output': {'create:copper_sheet': 1}, 'images': images}
    (scratch / 'schematic-native-result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'Schematics: inspect read-only, {len(hashes) - 1} unsupported/malformed inputs rejected before writes; source-safe paste drives actual pressing', flush=True)
    return report


UTF_ORACLE = r'''import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.HexFormat;
public class SchematicUtfOracle {
 public static void main(String[] args) throws Exception {
  var reader = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.US_ASCII));
  for(String line; (line=reader.readLine())!=null;) {
   var text = new String(HexFormat.of().parseHex(line), StandardCharsets.UTF_8);
   var bytes = new ByteArrayOutputStream(); new DataOutputStream(bytes).writeUTF(text);
   var encoded = bytes.toByteArray();
   var decoded = new DataInputStream(new ByteArrayInputStream(encoded)).readUTF();
   System.out.println(HexFormat.of().formatHex(encoded,2,encoded.length)+" "+HexFormat.of().formatHex(decoded.getBytes(StandardCharsets.UTF_8)));
  }
 }
}'''


def portable_checks():
    work = Path(tempfile.mkdtemp(prefix='schematic-checks-', dir=ROOT / '.local'))
    cargo('test', '--offline', '-p', 'create-schematics')
    cargo('build', '--offline', '--example', 'schematic_probe')
    probe = ROOT / 'target/debug/examples/schematic_probe'
    hashes = write_fixtures(work / 'schematics')
    for name in hashes:
        reply = subprocess.run([str(probe), 'inspect', str(work / 'schematics' / name)], capture_output=True, text=True)
        report = json.loads(reply.stdout)
        assert report['valid'] == (name == 'own-press.nbt'), (name, report)
    java, javac = shutil.which('java'), shutil.which('javac')
    if not java or not javac:
        raise RuntimeError('A JDK is required for the independent DataInput/DataOutput modified-UTF8 check')
    source = work / 'SchematicUtfOracle.java'
    source.write_text(UTF_ORACLE)
    subprocess.run([javac, '-d', str(work), str(source)], check=True)
    rng = random.Random(0x3955)
    samples = ['', '\0', 'A\0Ж😀', 'x' * 2048, '\u007f\u0080\u07ff\u0800\uffff', '𐀀\U0010ffff']
    for _ in range(40):
        points = [rng.randrange(0x110000) for _ in range(rng.randrange(1, 40))]
        samples.append(''.join(chr(p) for p in points if not 0xd800 <= p <= 0xdfff))
    lines = [text.encode().hex() for text in samples]
    oracle = subprocess.run([java, '-cp', str(work), 'SchematicUtfOracle'], input='\n'.join(lines) + '\n', text=True, capture_output=True, check=True).stdout.splitlines()
    assert len(oracle) == len(samples)
    for text, utf8, expected in zip(samples, lines, oracle):
        actual = json.loads(subprocess.check_output([str(probe), 'utf', utf8], text=True))
        encoded, decoded = expected.split(' ', 1)
        assert actual['encoded'] == encoded and actual['decoded'] == text and decoded == utf8, (utf8, expected, actual)
        assert _mutf8(text).hex() == encoded
    result = {'passed': True, 'scope': 'portable codec/preflight and JDK string oracle; no game launched',
              'utf_vectors': len(samples), 'fixture_hashes': hashes, 'work': str(work)}
    (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    portable_checks()
