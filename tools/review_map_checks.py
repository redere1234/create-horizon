#!/usr/bin/env python3
"""Audit the actual CreateProcessing05 gallery, exclusively on an isolated copy.

Before launch, copy the prepared save into SCRATCH/saves/CreateProcessing05 and
write SCRATCH/.review-map-clone.json with world, source and clone paths. Launch
with --game-dir SCRATCH --name Delete228 and a socket inside SCRATCH. Never point
this module at the review instance itself: inventory and station inputs change.
The expected positions below are independent of review_world.py's builder.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess

import foundation_checks


CATALOG = set('''creative_motor shaft cogwheel large_cogwheel mechanical_press depot
gearbox clutch gearshift hand_crank andesite_encased_shaft brass_encased_shaft
andesite_casing brass_casing andesite_alloy_block brass_block zinc_block speedometer
stressometer water_wheel large_water_wheel millstone encased_fan mechanical_drill
iron_sheet golden_sheet copper_sheet andesite_alloy brass_ingot brass_nugget
zinc_ingot zinc_nugget wrench brass_sheet vertical_gearbox goggles propeller
wheat_flour dough'''.split())
FANS = [(7, 'create:wheat_flour', 'create:dough', 'create:splashing'),
        (11, 'create:dough', 'minecraft:bread', 'create:smoking'),
        (15, 'minecraft:sand', 'minecraft:soul_sand', 'create:haunting'),
        (19, 'minecraft:raw_iron', 'minecraft:iron_ingot', 'create:blasting')]


def _clone(scratch):
    if scratch is None:
        raise AssertionError('An explicitly marked isolated clone is required')
    scratch = Path(scratch).resolve()
    marker = json.loads((scratch / '.review-map-clone.json').read_text())
    world = marker['world']
    assert world == 'CreateProcessing05', marker
    clone = Path(marker['clone']).resolve()
    source = Path(marker['source']).resolve()
    assert clone == scratch / 'saves' / world and clone != source, marker
    assert clone.is_dir() and (clone / 'level.dat').is_file(), marker
    assert not (scratch / 'saves' / world).is_symlink(), marker
    return scratch, marker


def _counts(slots):
    result = {}
    for stack in slots:
        if stack and stack.get('item'):
            result[stack['item']] = result.get(stack['item'], 0) + stack['count']
    return result


def run(call, graphics=False, log=None, scratch=None):
    scratch, marker = _clone(scratch)
    assert call('state')['world'] == marker['world']
    report = {'passed': False, 'world': marker['world'], 'clone': marker['clone'],
              'source_world_modified': False, 'graphics': graphics, 'checks': [], 'images': []}

    def record(name, **details):
        report['checks'].append({'name': name, **details})
        (scratch / 'review-map-progress.json').write_text(json.dumps(report, indent=2) + '\n')
        print('Prepared map:', name, flush=True)

    def block(pos):
        return call('block', *pos)

    def expect(pos, name, *properties):
        value = block(pos)
        assert value['block'] == name and all(p in value['state'] for p in properties), (pos, value)
        return value

    def counts(pos):
        return _counts(call('container', *pos)['slots'])

    def text(pos, path=None):
        command = 'data get block ' + ' '.join(map(str, pos))
        if path:
            command += ' ' + path
        return ' '.join(call('command', command)['chat'])

    def number(pos, key):
        value = text(pos)
        found = re.search(r'\b' + re.escape(key) + r':\s*(-?[\d.]+(?:[eE][+-]?\d+)?)', value)
        assert found, (pos, key, value)
        return float(found[1])

    def rpm(pos, value):
        call('command', 'data merge block ' + ' '.join(map(str, pos)) + f' {{ScrollValue:{value}}}')

    def clear():
        call('command', 'clear @s')
        call('wait', 3)

    def click(pos, face='up', player=None):
        if player:
            call('command', 'tp @s ' + ' '.join(map(str, player)))
        side = () if face is None else (face,)
        call('look-at', 'block', *pos, *side)
        call('wait', 3)
        call('interact', *pos, *side)
        call('wait', 8)
        assert call('screen')['screen'] == 'playing', pos

    def capture(name, player, target):
        if not graphics:
            return
        call('command', 'gamemode spectator')
        call('command', 'tp @s ' + ' '.join(map(str, player)))
        call('look-at', *target)
        call('wait', 10)
        image = scratch / (name + '.png')
        call('screenshot', image)
        assert image.is_file() and image.stat().st_size > 1024, image
        report['images'].append(str(image))
        call('command', 'gamemode creative')

    # Read the delivered inventory, armor, barrel and signage before clear().
    inventory = call('inventory')
    carried = [s['item'] for s in inventory['hotbar'] + inventory['main'] if s.get('item')]
    overflow = counts((45, 64, 7))
    assert len(carried) == len(set(carried)) == 36, inventory
    assert overflow == {'create:brass_sheet': 16, 'create:vertical_gearbox': 16, 'create:goggles': 1}, overflow
    assert set(carried) | set(overflow) == {'create:' + name for name in CATALOG}
    hotbar = ['wrench', 'creative_motor', 'shaft', 'cogwheel', 'millstone',
              'encased_fan', 'mechanical_drill', 'depot', 'hand_crank']
    assert [s.get('item') for s in inventory['hotbar']] == ['create:' + name for name in hotbar]
    assert any(s.get('part') == 'head' and s.get('item') == 'create:goggles' for s in inventory['armor']), inventory
    materials = counts((43, 64, 3))
    assert materials == {name: 32 for name in ['minecraft:wheat', 'create:wheat_flour', 'create:dough',
                                              'minecraft:sand', 'minecraft:gravel', 'minecraft:raw_iron']}, materials
    assert counts((47, 64, 13)) == {'minecraft:cobblestone': 32, 'minecraft:stone': 32}
    for pos, expected in [((2, 64, 2), {'create:brass_sheet': 8}),
                          ((6, 64, 8), {}), ((17, 64, 3), {}),
                          ((20, 64, 12), {'minecraft:copper_ingot': 2})]:
        actual = counts(pos)
        assert actual == expected, ('old prepared depot contains unexpected material', pos, actual, expected)
    for pos, label in [((36, 64, 3), 'ЖЁРНОВ'), ((38, 64, 9), 'ПРОМЫВКА'),
                       ((38, 64, 13), 'КОПЧЕНИЕ'), ((38, 64, 17), 'ОГОНЬ ДУШ'),
                       ((38, 64, 21), 'ОБЖИГ'), ((45, 64, 16), 'МЕХАНИЧЕСКИЙ БУР'),
                       ((43, 64, 5), 'МАТЕРИАЛЫ'), ((45, 64, 9), 'ОСТАЛЬНОЙ КАТАЛОГ')]:
        expect(pos, 'minecraft:oak_sign')
        assert label in text(pos, 'front_text.messages'), (pos, text(pos))
    for pos, name, properties in [
        ((2, 66, 2), 'create:mechanical_press', ['facing=east']),
        ((2, 64, 2), 'create:depot', []), ((2, 66, 8), 'create:speedometer', []),
        ((13, 67, 2), 'create:water_wheel', ['facing=east']),
        ((24, 67, 2), 'create:large_water_wheel', ['axis=x']),
        ((36, 65, 0), 'create:millstone', []), ((35, 65, 0), 'create:cogwheel', ['axis=y']),
        ((36, 66, 0), 'minecraft:hopper', ['facing=down']),
        ((36, 64, 0), 'minecraft:hopper', ['facing=east']),
        ((45, 65, 13), 'create:mechanical_drill', ['facing=east', 'waterlogged=false']),
        ((44, 66, 13), 'minecraft:lever', ['powered=true']), ((46, 65, 13), 'minecraft:stone', []),
    ]:
        expect(pos, name, *properties)
    assert number((35, 64, 0), 'ScrollValue') == 128
    for z, _, _, _ in FANS:
        expect((35, 65, z), 'create:encased_fan', 'facing=east')
        expect((34, 65, z), 'create:shaft', 'axis=x')
        expect((38, 64, z), 'create:depot')
        assert number((33, 65, z), 'ScrollValue') == 32
    for z, input_item, output_item, _ in FANS:
        initial = call('container', 38, 64, z)['slots']
        assert initial[0] in [{'item': input_item, 'count': 8}, {'item': output_item, 'count': 8}], ('prepared fan input obstructed', z, initial)
        assert all(s is None for s in initial[1:]), ('prepared fan has unexpected buffer', z, initial)
    expect((36, 65, 7), 'minecraft:oak_fence', 'waterlogged=true')
    expect((36, 65, 11), 'minecraft:campfire', 'lit=true')
    expect((36, 65, 15), 'minecraft:soul_campfire', 'lit=true')
    expect((36, 65, 19), 'minecraft:lava')
    expect((37, 65, 19), 'minecraft:iron_bars')
    record('initial catalog39, carried36, overflow3, goggles, materials, signs and original stations',
           catalog_entries=len(CATALOG), carried_entries=len(carried), overflow=overflow, materials=materials)
    capture('map05-overview-before', (47, 74, 21), (38, 65, 8))

    # Use this map's real original press/depot, not a recreated machine.
    assert counts((2, 64, 2)) == {'create:brass_sheet': 8}
    clear()
    click((2, 64, 2), player=(2.5, 65, 4.5))
    assert call('inventory')['counts'].get('create:brass_sheet') == 8
    assert counts((2, 64, 2)) == {}
    clear()
    rpm((0, 66, 2), 256)
    call('command', 'give @s minecraft:copper_ingot 8')
    call('wait', 3)
    call('select', 'minecraft:copper_ingot')
    click((2, 64, 2))
    call('wait', 150)
    assert counts((2, 64, 2)) == {'create:copper_sheet': 8}, counts((2, 64, 2))
    assert not call('inventory')['held']
    click((2, 64, 2))
    assert call('inventory')['counts'].get('create:copper_sheet') == 8
    assert counts((2, 64, 2)) == {}
    rpm((0, 66, 2), 16)
    capture('map05-press-cleared', (5.5, 66, 5.5), (2.5, 65, 2.5))
    if graphics and log is not None:
        rows = [json.loads(line.split('Create render depot: ', 1)[1])
                for line in Path(log).read_text().splitlines() if 'Create render depot: ' in line]
        rows = [r for r in rows if r['pos'] == [2, 64, 2]]
        assert rows and rows[-1]['stack'] is None, rows[-5:]
    record('actual brass8 pickup, copper8 pressing/pickup, empty server/client depot')

    for speed, target, power in [(16, .24, 4), (256, 1.125, 15), (16, .24, 4)]:
        rpm((0, 66, 8), speed)
        call('wait', 25)
        assert number((2, 66, 8), 'Speed') == speed
        assert abs(number((2, 66, 8), 'Value') - target) < 1e-5
        expect((2, 66, 10), 'minecraft:redstone_wire', 'power=' + str(power))
    assert number((3, 66, 8), 'Stress') > 0
    record('prepared gauges and actual comparator 4->15->4')

    for wheel, shaft, base, magnitude, capacity in [
        ((13, 67, 2), (14, 67, 2), (13, 65, 3), 8, 256),
        ((24, 67, 2), (25, 67, 2), (24, 65, 4), 4, 512),
    ]:
        original = number(shaft, 'Speed')
        assert abs(original) == magnitude and number(wheel, 'Capacity') == capacity
        expect(base, 'minecraft:magma_block')
        call('setblock', *base, 'minecraft:soul_sand')
        call('wait', 40)
        assert number(shaft, 'Speed') == -original
        call('setblock', *base, 'minecraft:magma_block')
        call('wait', 40)
        assert number(shaft, 'Speed') == original
    assert abs(number((16, 66, 3), 'Speed')) == 16
    record('prepared water channels, 8/4 RPM, 256/512 SU and reversible real flow')

    # Drain the originally supplied wheat naturally before an exact delta test.
    for _ in range(30):
        if not counts((36, 66, 0)) and not counts((36, 65, 0)) and not counts((36, 64, 0)):
            break
        call('wait', 40)
    else:
        raise AssertionError(('prepared millstone did not drain original wheat', counts((36, 65, 0))))
    before = counts((37, 64, 0))
    assert before.get('create:wheat_flour', 0) >= 32, before
    assert set(before) <= {'create:wheat_flour', 'minecraft:wheat_seeds'}, before
    assert abs(number((36, 65, 0), 'Speed')) == 128
    call('container', 36, 66, 0, 'minecraft:sandstone', 4)
    call('wait', 220)
    after = counts((37, 64, 0))
    expected = dict(before)
    expected['minecraft:sand'] = expected.get('minecraft:sand', 0) + 4
    assert after == expected, (before, after)
    assert counts((36, 66, 0)) == counts((36, 65, 0)) == counts((36, 64, 0)) == {}
    call('container', 36, 66, 0, 'minecraft:diamond', 2)
    call('wait', 40)
    assert counts((36, 66, 0)) == {'minecraft:diamond': 2}
    assert counts((36, 65, 0)) == {} and counts((37, 64, 0)) == after
    call('command', 'item replace block 36 66 0 container.0 with minecraft:air')
    capture('map05-millstone', (39, 68, 4), (36, 65.5, 0))
    record('original wheat32 processed, actual hopper sandstone4->sand4 delta, diamonds rejected',
           original_wheat_outputs=before, after_sandstone=after)

    # Reuse all four delivered fan lines with fresh hand-supplied inputs.
    for z, input_item, output_item, _ in FANS:
        initial = counts((38, 64, z))
        assert initial in [{input_item: 8}, {output_item: 8}], (z, initial)
        clear()
        click((38, 64, z), player=(39.5, 64, z + 1.5))
        assert counts((38, 64, z)) == {}
        clear()
        call('command', f'give @s {input_item} 8')
        call('wait', 3)
        call('select', input_item)
        click((38, 64, z))
    call('wait', 200)
    fan_outputs = {}
    for z, _, output_item, kind in FANS:
        actual = counts((38, 64, z))
        assert actual == {output_item: 8}, (z, actual)
        assert kind in text((38, 64, z))
        assert number((35, 65, z), 'Speed') == 32
        fan_outputs[str(z)] = actual
    # Check that the lava remained in the intended one-block enclosure.
    for pos in [(36, 64, 19), (36, 66, 19), (36, 65, 18), (36, 65, 20)]:
        expect(pos, 'minecraft:glass')
    expect((37, 65, 19), 'minecraft:iron_bars')
    expect((37, 64, 19), 'minecraft:air')
    capture('map05-fan-lines', (43, 70, 21), (36, 65, 13))
    capture('map05-washing', (39.5, 66.5, 9.5), (36.5, 65.5, 7.5))
    record('four original fan lines: washing, smoking, haunting, contained lava blasting', outputs=fan_outputs)

    # Activate the map's own real lever, then stop and replace its front target.
    clear()
    expect((44, 66, 13), 'minecraft:lever', 'powered=true')
    assert number((45, 65, 13), 'Speed') == 0
    before = counts((47, 64, 13))
    # A lever's small outline need not expose the full-block south face.
    # Stand on the existing motor and use the actual visible outline instead.
    click((44, 66, 13), None, player=(43.5, 66, 13.5))
    expect((44, 66, 13), 'minecraft:lever', 'powered=false')
    call('wait', 140)
    expect((46, 65, 13), 'minecraft:air')
    after = counts((47, 64, 13))
    expected = dict(before)
    expected['minecraft:cobblestone'] += 1
    assert after == expected and counts((46, 64, 13)) == {}, (before, after)
    assert number((45, 65, 13), 'Speed') == 128
    click((44, 66, 13), None)
    expect((44, 66, 13), 'minecraft:lever', 'powered=true')
    call('wait', 8)
    call('setblock', 46, 65, 13, 'minecraft:stone')
    call('wait', 40)
    expect((46, 65, 13), 'minecraft:stone')
    assert number((45, 65, 13), 'Speed') == 0 and counts((47, 64, 13)) == after
    capture('map05-drill', (48, 68, 17), (45, 65.5, 13))
    record('prepared drill lever -> stone -> exactly one new cobblestone -> off/new target intact',
           chest_before=before, chest_after=after)

    if graphics:
        foundation_checks.crafting(call, 46, clear,
            ['kinetics/propeller', 'kinetics/millstone', 'kinetics/encased_fan',
             'kinetics/mechanical_drill', 'appliances/dough'])
        crafted = call('inventory')['counts']
        assert crafted.get('create:dough') == 1 and crafted.get('minecraft:bucket') == 1, crafted
        assert not crafted.get('minecraft:water_bucket') and not crafted.get('create:wheat_flour'), crafted
        record('five new recipes crafted in actual vanilla menu; dough returns exactly one bucket')
    else:
        report['crafting_not_run'] = 'Vanilla crafting menus require graphics'
    call('command', 'item replace entity @s armor.head with create:goggles')
    capture('map05-overview-after', (47, 74, 21), (38, 65, 8))
    call('save')
    report['passed'] = True
    (scratch / 'review-map-progress.json').write_text(json.dumps(report, indent=2) + '\n')
    (scratch / 'review-map-result.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ctl', type=Path, required=True)
    parser.add_argument('--socket', type=Path, required=True)
    parser.add_argument('--scratch', type=Path, required=True)
    parser.add_argument('--graphics', action='store_true')
    parser.add_argument('--log', type=Path)
    args = parser.parse_args()
    scratch, _ = _clone(args.scratch)
    assert args.socket.resolve().is_relative_to(scratch), 'Socket must belong to this isolated clone'
    transcript = []

    def call(*words):
        command = [str(args.ctl), '--socket', str(args.socket), *map(str, words)]
        result = subprocess.run(command, text=True, capture_output=True, timeout=180)
        if result.returncode:
            raise RuntimeError(str(words) + result.stdout + result.stderr)
        value = json.loads(result.stdout)
        transcript.append({'command': list(map(str, words)), 'reply': value})
        return value

    try:
        print(json.dumps(run(call, args.graphics, args.log, scratch), indent=2))
    except Exception as error:
        (scratch / 'review-map-failure.json').write_text(json.dumps({
            'passed': False, 'error': repr(error), 'clone': str(scratch),
            'source_world_modified': False, 'last_commands': transcript[-12:],
        }, indent=2) + '\n')
        raise
    finally:
        (scratch / 'review-map-transcript.json').write_text(json.dumps(transcript, indent=2) + '\n')


if __name__ == '__main__':
    main()
