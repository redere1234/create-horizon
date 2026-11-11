"""Basin/Mixer integration checks for an owned NativeCheckSession world only.

The authored schematic below is a reusable Java/Horizon comparison input. Its
existence alone does not claim either client has pasted or tested it.
"""
import hashlib
import json
from pathlib import Path
import re

from common import ROOT, PINS
from schematic_checks import _write, _json_reply


def write_shared_fixture(path):
    def palette(name, **properties):
        value = {'Name': (8, name)}
        if properties:
            value['Properties'] = (10, {k: (8, v) for k, v in properties.items()})
        return value

    def block(pos, state, nbt=None):
        value = {'pos': (9, (3, pos)), 'state': (3, state)}
        if nbt:
            value['nbt'] = (10, nbt)
        return value

    root = {'DataVersion': (3, 3955), 'size': (9, (3, [6, 4, 6])),
            'palette': (9, (10, [palette('minecraft:smooth_stone'),
                palette('create:creative_motor', facing='up'),
                palette('create:cogwheel', axis='y', waterlogged='false'),
                palette('create:basin', facing='down'), palette('create:mechanical_mixer')])),
            'blocks': (9, (10, [block([x, 0, z], 0) for x in range(6) for z in range(6)] + [
                block([1, 2, 2], 1, {'id': (8, 'create:motor'), 'ScrollValue': (3, 32)}),
                block([1, 3, 2], 2, {'id': (8, 'create:simple_kinetic')}),
                block([2, 1, 2], 3, {'id': (8, 'create:basin')}),
                block([2, 3, 2], 4, {'id': (8, 'create:mechanical_mixer'), 'Running': (1, 0), 'Ticks': (3, 0)}),
            ])), 'entities': (9, (10, []))}
    path = Path(path)
    _write(path, root)
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'blocks': 40, 'size': [6, 4, 6], 'data_version': 3955,
            'source': PINS['create_revision'], 'tested': False}


def run(call, graphics=False, log=None, scratch=None, *, start_at=None):
    assert start_at in [None, 'dough'], start_at
    scratch = Path(scratch).resolve()
    scratch.relative_to((ROOT / '.local').resolve())
    assert call('state')['world'] == 'CreateParity06', 'Only the harness disposable world is authorized'
    x, y, z = 384, 64, 16
    report = {'passed': False, 'checks': [], 'images': [], 'source': PINS['create_revision'],
              'unsupported': ['unknown/malformed fluid tanks', 'heated recipes', 'complex filters', 'side spouts',
                              'falling-item intake until entity-sensitive contact hook is connected']}
    report['start_at'] = start_at
    report['timing_scope'] = 'bounded live integration; exact normal-tick timing is checked separately by basin_timing_checks.py'
    report['known_differences'] = [
        'stored empty tank Level.Force remains present; original LerpedFloat emits and clears this one-shot flag',
        'full client presentation under debug-freeze is not yet compared',
    ]
    report['shared_fixture'] = write_shared_fixture(scratch / 'schematics/own-basin-mixer.nbt')
    result = scratch / 'basin-native-result.json'
    transcript = scratch / 'basin-native-transcript.jsonl'
    transcript.write_text('')
    result.write_text(json.dumps(report, indent=2) + '\n')

    def ctl(*args):
        reply = call(*args)
        with transcript.open('a') as stream:
            stream.write(json.dumps({'command': list(map(str, args)), 'reply': reply}) + '\n')
        return reply

    def command(line):
        reply = ctl('command', line)
        assert not any('not loaded' in t or 'Unknown block' in t for t in reply.get('chat', [])), (line, reply)
        return reply

    def data(pos=(x, y, z)):
        return ' '.join(command('data get block ' + ' '.join(map(str, pos)))['chat'])

    def number(key, pos=(x, y + 2, z)):
        text = data(pos)
        found = re.search(r'\b' + key + r':\s*(-?[\d.]+)', text)
        assert found, (key, text)
        return float(found[1])

    def slots(pos=(x, y, z)):
        return ctl('container', *pos)['slots']

    def counts(items):
        totals = {}
        for item in items:
            if item and item.get('item'):
                totals[item['item']] = totals.get(item['item'], 0) + item['count']
        return totals

    def setblock(pos, state):
        command('setblock ' + ' '.join(map(str, pos)) + ' ' + state)

    def stack(item, count, slot, marker=None):
        extra = ',components:{"minecraft:custom_data":{basin_marker:' + str(marker) + '}}' if marker else ''
        return '{Slot:' + str(slot) + ',id:"' + item + '",count:' + str(count) + extra + '}'

    def inventories(inputs=(), outputs=()):
        fields = []
        for key, values in [('InputItems', inputs), ('OutputItems', outputs)]:
            fields.append(key + ':{Size:9,Items:[' + ','.join(
                stack(args[0], args[1], i, args[2] if len(args) > 2 else None)
                for i, args in enumerate(values)) + ']}')
        command(f'data merge block {x} {y} {z} ' + '{' + ','.join(fields) + '}')

    def power(rpm):
        command(f'data merge block {x - 1} {y + 1} {z} {{ScrollValue:{rpm}}}')

    def reset():
        command('tick unfreeze')
        command('gamemode creative')
        command(f'tp @s {x + 3.5} {y} {z + 2.5}')
        ctl('wait', 5)
        ctl('wait-ready', 120)
        for attempt in range(12):
            corners = [command(f'execute if loaded {px} {y} {pz} run say basin_corner_loaded')
                       for px in [x - 4, x + 6] for pz in [z - 3, z + 6]]
            if all(any('basin_corner_loaded' in t for t in c['chat']) for c in corners):
                break
            ctl('wait', 5)
        else:
            raise AssertionError(('Fixture chunks are not loaded', corners))
        command(f'fill {x - 4} {y - 1} {z - 3} {x + 6} {y + 5} {z + 6} minecraft:air')
        command(f'fill {x - 4} {y - 1} {z - 3} {x + 6} {y - 1} {z + 6} minecraft:smooth_stone')
        pasted = _json_reply(command(f'create schematic paste own-basin-mixer.nbt {x - 2} {y - 1} {z - 2}'))
        assert pasted['ok'] and pasted['blocks'] == 40, pasted
        report['shared_fixture']['pasted_native'] = True
        power(0)
        command('clear @s')
        command('kill @e[type=minecraft:item]')
        ctl('wait', 5)
        assert ctl('block', x, y, z)['state'] == 'create:basin[facing=down]'
        assert len(slots()) == 18
        assert number('Speed') == 0

    def click():
        support = command(f'execute if block {x + 3} {y - 1} {z + 2} minecraft:smooth_stone run say basin_support_present')
        assert any('basin_support_present' in t for t in support['chat']), support
        command(f'tp @s {x + 3.5} {y} {z + 2.5}')
        ctl('wait', 3)
        player = ctl('state')['player']
        assert player['on_ground'] and abs(player['position'][1] - y) < .001, player
        ctl('look-at', 'block', x, y, z, 'south')
        ctl('wait', 2)
        ctl('interact', x, y, z, 'south')
        ctl('wait', 5)

    def game_time():
        reply = command('time query gametime')
        values = re.findall(r'\b\d+\b', ' '.join(reply['chat']))
        assert len(values) == 1, reply
        return int(values[0])

    def passed(text):
        report['checks'].append(text)
        result.write_text(json.dumps(report, indent=2) + '\n')

    if start_at != 'dough':
        reset()
        original = data()
        assert 'InputTanks' in original and 'OutputTanks' in original and 'TankContent: {}' in original, original
        assert 'FilterAmount: 64' in original, original
        for key in ['InputItems', 'OutputItems']:
            inventory = re.search(r'\b' + key + r':\s*\{([^{}]*)\}', original)
            assert inventory and re.search(r'\bSize:\s*9\b', inventory[1]), original
            assert re.search(r'\bItems:\s*\[\]', inventory[1]), original
        inventories([('minecraft:andesite', 64, 501)])
        setblock((x - 1, y, z), 'minecraft:hopper[facing=east]')
        command(f'data merge block {x - 1} {y} {z} ' + '{Items:[' + stack('minecraft:andesite', 3, 0, 501) + ']}')
        ctl('wait', 32)
        assert counts(slots()[:9]) == {'minecraft:andesite': 64}
        assert counts(slots((x - 1, y, z))) == {'minecraft:andesite': 3}
        command(f'data merge block {x - 1} {y} {z} ' + '{Items:[' + stack('minecraft:andesite', 2, 0, 502) + ']}')
        ctl('wait', 24)
        held = slots()
        assert held[0]['count'] == 64 and held[1]['count'] == 2 and all(v is None for v in held[2:9]), held
        assert 'basin_marker: 501' in data() and 'basin_marker: 502' in data()
        passed('canonical18slots/typed empty tank fields; ordinary hopper respects unique component-bearing stack and first empty input slot')

        reset()
        inventories([('minecraft:andesite', 2, 601)], [('minecraft:iron_nugget', 2, 602)])
        setblock((x, y - 1, z + 1), 'minecraft:chest')
        setblock((x, y - 1, z), 'minecraft:hopper[facing=south]')
        ctl('wait', 80)
        assert counts(slots()) == {}
        assert counts(slots((x, y - 1, z + 1))) == {'minecraft:andesite': 2, 'minecraft:iron_nugget': 2}
        chest = data((x, y - 1, z + 1))
        assert 'basin_marker: 601' in chest and 'basin_marker: 602' in chest, chest
        passed('ordinary extraction hopper reads input and output halves and conserves both component markers')

        reset()
        inventories([('minecraft:andesite', 2, 701)], [('minecraft:iron_nugget', 2, 702)])
        command('give @s minecraft:iron_ingot 1')
        # A normal user interaction tries both hands. Occupy the offhand too so
        # an empty offhand cannot legitimately trigger Basin's empty-stack pickup.
        command('item replace entity @s weapon.offhand with minecraft:iron_ingot 1')
        ctl('wait', 5)
        ctl('select', 'minecraft:iron_ingot')
        assert ctl('inventory')['offhand']['item'] == 'minecraft:iron_ingot'
        click()
        assert counts(slots()) == {'minecraft:andesite': 2, 'minecraft:iron_nugget': 2}
        command('clear @s')
        ctl('wait', 5)
        click()
        assert counts(slots()) == {}
        assert ctl('inventory')['counts'] == {'minecraft:andesite': 2, 'minecraft:iron_nugget': 2}
        player = ' '.join(command('data get entity @s Inventory')['chat'])
        assert 'basin_marker: 701' in player and 'basin_marker: 702' in player, player
        assert ctl('state')['menu'] is None
        passed('both hands occupied do not insert/retrieve; empty-hand interaction retrieves both halves with no chest menu')

        reset()
        inventories([('minecraft:andesite', 2), ('minecraft:iron_nugget', 2)])
        power(32)
        ctl('wait', 180)
        assert abs(number('Speed')) == 32
        assert counts(slots()[9:]) == {'create:andesite_alloy': 2} and counts(slots()[:9]) == {}
        passed('live real32RPM network completes and repeats two dry batches, conserving exact inputs/outputs')
        saved = data((x, y + 2, z))
        assert 'ProcessingTicks' not in saved and 'CurrentRecipe' not in saved, saved

        reset()
        inventories([('minecraft:andesite', 1), ('minecraft:iron_nugget', 1)])
        power(29)
        ctl('wait', 100)
        assert number('Running') == 0 and counts(slots()[9:]) == {}
        power(30)
        ctl('wait', 8)
        assert number('Running') == 1 and abs(number('Speed')) == 30
        power(0)
        ctl('wait', 50)
        assert counts(slots()[:9]) == {'minecraft:andesite': 1, 'minecraft:iron_nugget': 1}
        assert counts(slots()[9:]) == {} and number('Running') == 0
        passed('source minimum30RPM boundary and power-loss retraction preserve unprocessed inputs')

        reset()
        outputs = [('create:andesite_alloy', 64)] + [('minecraft:' + i, 64) for i in ['stone', 'cobblestone', 'andesite', 'diorite', 'granite', 'dirt', 'sand', 'gravel']]
        inventories([('minecraft:andesite', 1), ('minecraft:iron_nugget', 1)], outputs)
        power(32)
        ctl('wait', 100)
        assert number('Running') == 0 and counts(slots()[:9]) == {'minecraft:andesite': 1, 'minecraft:iron_nugget': 1}
        outputs[0] = ('create:andesite_alloy', 63)
        inventories([('minecraft:andesite', 1), ('minecraft:iron_nugget', 1)], outputs)
        ctl('wait', 110)
        assert counts(slots()[:9]) == {} and counts(slots()[9:])['create:andesite_alloy'] == 64
        passed('full output blocks starting/consumption; freeing one matching output space resumes exactly one batch')

    reset()
    inventories([('create:wheat_flour', 2), ('minecraft:water_bucket', 1)])
    power(32)
    ctl('wait', 115)
    assert counts(slots()[:9]) == {'create:wheat_flour': 1}
    assert counts(slots()[9:]) == {'minecraft:bucket': 1, 'create:dough': 1}, slots()
    assert slots()[9]['item'] == 'create:dough' and slots()[10]['item'] == 'minecraft:bucket'
    passed('source shapeless dough recipe consumes bucket/flour units and emits dough then one ordinary bucket remainder in source order')

    for name, patch, retained in [
        ('filter', '{Filter:{id:"minecraft:andesite",count:1,Unported:1b}}',
         r'Filter:\s*\{(?=[^{}]*\bid:\s*"minecraft:andesite")(?=[^{}]*\bUnported:\s*1b)[^{}]*\}'),
        ('tank', '{InputTanks:[{TankContent:{id:"minecraft:water",amount:1000}},{TankContent:{}}]}', r'\bamount:\s*1000\b'),
        ('spout', '{DisabledSpoutput:["north"]}', r'DisabledSpoutput:\s*\["north"\]'),
    ]:
        reset()
        inventories([('minecraft:andesite', 2, 801), ('minecraft:iron_nugget', 2, 802)])
        command(f'data merge block {x} {y} {z} ' + patch)
        power(32)
        ctl('wait', 110)
        current = data()
        assert 'create_horizon:Unsupported' in current and re.search(retained, current), (name, current)
        assert counts(slots()[:9]) == {'minecraft:andesite': 2, 'minecraft:iron_nugget': 2}
        assert counts(slots()[9:]) == {} and number('Running') == 0
        assert 'basin_marker: 801' in current and 'basin_marker: 802' in current
    passed('unsupported filter/tank/spout data is explicitly marked and retained without consuming component-bearing inputs')

    if graphics:
        reset()
        command('clear @s')
        click()
        inventories([('minecraft:andesite', 3), ('minecraft:iron_nugget', 3)])
        power(32)
        ctl('wait', 24)
        command(f'tp @s {x + 3.5} {y} {z + 2.5}')
        ctl('wait', 3)
        assert ctl('state')['player']['on_ground']
        ctl('look-at', x + .5, y + 1.25, z + .5)
        ctl('key', 'f1', 'tap')
        try:
            image = scratch / 'basin-mixer-native.png'
            ctl('screenshot', image)
            report['images'].append(str(image))
        finally:
            ctl('key', 'f1', 'tap')
    fixture = Path(report['shared_fixture']['path'])
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == report['shared_fixture']['sha256']
    report['shared_fixture']['tested_native'] = True
    report['passed'] = True
    result.write_text(json.dumps(report, indent=2) + '\n')
    return report


def prepare_restart(call, scratch):
    """Seed a stopped, component-bearing Basin before a real harness restart."""
    scratch = Path(scratch).resolve()
    scratch.relative_to((ROOT / '.local').resolve())
    assert call('state')['world'] == 'CreateParity06'
    call('command', 'tick unfreeze')
    call('command', 'data merge block 383 65 16 {ScrollValue:0}')
    call('wait', 50)
    call('command', 'data merge block 384 64 16 {InputItems:{Size:9,Items:['
         '{Slot:0,id:"minecraft:andesite",count:4,components:{"minecraft:max_stack_size":16,'
         '"minecraft:custom_data":{basin_marker:901}}}]},OutputItems:{Size:9,Items:['
         '{Slot:0,id:"create:andesite_alloy",count:3,components:{"minecraft:custom_data":{basin_marker:902}}}]}}')
    call('wait', 5)
    fields = {}
    for field in ['InputItems', 'OutputItems']:
        fields[field] = call('command', 'data get block 384 64 16 ' + field)['chat']
    report = {'passed': False, 'before': fields, 'requires_actual_process_restart': True}
    (scratch / 'basin-restart-result.json').write_text(json.dumps(report, indent=2) + '\n')
    call('save-all')
    return report


def after_restart(call, scratch):
    """Verify the saved payload, then require a fresh functional mixing cycle."""
    scratch = Path(scratch).resolve()
    scratch.relative_to((ROOT / '.local').resolve())
    assert call('state')['world'] == 'CreateParity06'
    result = scratch / 'basin-restart-result.json'
    report = json.loads(result.read_text())
    call('command', 'tp @s 387.5 64 18.5')
    call('wait', 5)
    call('wait-ready', 120)
    call('wait', 10)
    fields = {field: call('command', 'data get block 384 64 16 ' + field)['chat']
              for field in report['before']}
    report['after'] = fields
    result.write_text(json.dumps(report, indent=2) + '\n')
    assert fields == report['before'], report
    assert call('container', 384, 64, 16)['slots'][0]['count'] == 4
    assert call('container', 384, 64, 16)['slots'][9]['count'] == 3
    call('command', 'data merge block 384 64 16 {InputItems:{Size:9,Items:['
         '{Slot:0,id:"minecraft:andesite",count:1},{Slot:1,id:"minecraft:iron_nugget",count:1}]},'
         'OutputItems:{Size:9,Items:[]}}')
    call('command', 'data merge block 383 65 16 {ScrollValue:32}')
    call('wait', 110)
    slots = call('container', 384, 64, 16)['slots']
    assert all(stack is None for stack in slots[:9]), slots
    assert slots[9]['item'] == 'create:andesite_alloy' and slots[9]['count'] == 1, slots
    report['passed'] = True
    report['checks'] = ['canonical input/output NBT including max-stack/custom components survives real process restart',
                        'restored Basin/Mixer network completes a fresh dry batch']
    result.write_text(json.dumps(report, indent=2) + '\n')
    return report
