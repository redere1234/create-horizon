#!/usr/bin/env python3
"""Audit a closed CreateFactory07 save on one disposable, rendered native clone.

Cold inventories are checked before opening the copy. Delivered machine inputs
are never replenished. Craft ingredients come only from the authored material
barrel through real survival menus. Two process exits/reopens test persistence.
Screenshots require a separate human/agent inspection; a numeric PASS is not a
claim of pixel, sound, multiplayer or complete Create parity.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct

from common import ROOT
from native_check_session import NativeCheckSession, wait_loaded
from reference_java import CREATE_SHA256
from review_world_07 import CATALOG
from saved_block_checks import read_saved_block

WORLD = 'CreateFactory07'
BARRELS = ((2, 128, 2), (4, 128, 2))
MATERIAL = (6, 128, 2)
TABLE = (8, 128, 2)
DEPOT = (8, 128, 34)
BASIN = (18, 128, 34)
# Independent station coordinates, not the builder's generated rig list.
RIGS = [
    ('x', 'y', [(10, 130, 8), (10, 131, 8), (10, 132, 8)], (9, 130, 8), (11, 132, 8)),
    ('x', 'z', [(26, 130, 8), (26, 130, 9), (26, 130, 10)], (25, 130, 8), (27, 130, 10)),
    ('y', 'x', [(42, 130, 8), (43, 130, 8), (44, 130, 8)], (42, 129, 8), (44, 131, 8)),
    ('y', 'z', [(10, 130, 24), (10, 130, 25), (10, 130, 26)], (10, 129, 24), (10, 131, 26)),
    ('z', 'x', [(26, 130, 24), (27, 130, 24), (28, 130, 24)], (26, 130, 23), (28, 130, 25)),
    ('z', 'y', [(42, 130, 24), (42, 131, 24), (42, 132, 24)], (42, 130, 23), (42, 132, 25)),
]
FANS = ((30, 129, 32), (30, 129, 36))
FAN_DEPOTS = ((34, 128, 32), (34, 128, 36))
MOTORS = ((6, 130, 34), (16, 130, 34), *FANS)
CANONICAL = {DEPOT: ('HeldItem', 'OutputBuffer'),
             BASIN: ('InputItems', 'OutputItems', 'InputTanks', 'OutputTanks'),
             **{pos: ('HeldItem', 'OutputBuffer') for pos in FAN_DEPOTS}}
RECIPES = (
    ('encased_chain_drive', 'minecraft:iron_nugget'),
    ('encased_chain_drive_from_zinc', 'create:zinc_nugget'),
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def manifest(folder):
    folder = Path(folder)
    assert folder.is_dir() and not folder.is_symlink(), folder
    files = {}
    for path in sorted(folder.rglob('*')):
        assert not path.is_symlink(), ('Symlinked save refused', path)
        if path.is_file():
            files[path.relative_to(folder).as_posix()] = sha(path)
    assert 'level.dat' in files, 'A complete closed save is required'
    return files


def xyz(pos):
    return ' '.join(map(str, pos))


def counts(slots):
    result = collections.Counter()
    for stack in slots:
        if stack and stack.get('item'):
            result[stack['item']] += stack['count']
    return dict(result)


def saved_counts(tag):
    result = collections.Counter()
    for entry in tag['value']:
        value = entry['value']
        result[value['id']['value']] += value.get('count', {'value': 1})['value']
    return dict(result)


def typed_float(tag):
    assert tag['type'] == 'float-bits', tag
    return struct.unpack('!f', struct.pack('!I', tag['value']))[0]


def cold_preflight(source):
    """Inspect original serialized stocks without starting any game process."""
    world = source / 'saves' / WORLD
    before = manifest(world)
    outer = json.loads((source / 'result.json').read_text())
    authored = json.loads((source / 'review07-build-result.json').read_text())
    marker = json.loads((source / '.review07-fresh.json').read_text())
    assert outer['passed'] and outer['world_closed'] and outer['world'] == WORLD, outer
    assert Path(outer['scratch']).resolve() == source, outer
    assert marker['world'] == WORLD and Path(marker['fresh_private_home']).resolve() == source, marker
    assert outer['closed_world_files'] == before, 'Source changed after its closed authoring receipt'
    assert authored['passed'] and authored['plan']['world'] == WORLD, authored
    assert authored['plan']['floor_y'] == 127 and authored['plan']['player_y'] == 128
    assert len(authored['plan']['chain_rigs']) == 6
    for supplied, expected in zip(authored['plan']['chain_rigs'], RIGS):
        axis, connection, nodes, motor, output = expected
        assert (supplied['shaft_axis'], supplied['connection_axis'], supplied['nodes'],
                supplied['motor'], supplied['output']) == (
                    axis, connection, list(map(list, nodes)), list(motor), list(output)), supplied
    records = {}

    def fields(pos):
        record = read_saved_block(source, pos, WORLD)
        records[xyz(pos)] = record
        return record['nbt']['value']

    catalog = ['create:' + name for name in CATALOG]
    assert len(catalog) == len(set(catalog)) == 48
    for index, pos in enumerate(BARRELS):
        entries = fields(pos)['Items']
        assert len(entries['value']) == 24
        assert saved_counts(entries) == {item: 1 for item in catalog[index * 24:(index + 1) * 24]}
        assert [entry['value']['Slot']['value'] for entry in entries['value']] == list(range(24))
    material = fields(MATERIAL)['Items']
    delivered = authored['plan']['materials']['stacks']
    assert len(delivered) == 22 and len(material['value']) == 22
    for slot, (entry, expected) in enumerate(zip(material['value'], delivered)):
        item, amount = expected
        actual = entry['value']
        assert (actual['Slot']['value'], actual['id']['value'], actual['count']['value']) == (
            slot, item, amount), (slot, actual, expected)
    stock = saved_counts(material)
    assert stock['create:andesite_casing'] == 8 and stock['create:zinc_nugget'] == 16
    assert stock['minecraft:iron_nugget'] == 32
    depot = fields(DEPOT)
    assert depot['HeldItem']['value']['Item']['value']['id']['value'] == 'minecraft:copper_ingot'
    assert depot['HeldItem']['value']['Item']['value']['count']['value'] == 8
    assert not saved_counts(depot['OutputBuffer']['value']['Items'])
    basin = fields(BASIN)
    assert saved_counts(basin['InputItems']['value']['Items']) == {'minecraft:snowball': 8}
    assert not saved_counts(basin['OutputItems']['value']['Items'])
    for index, pos in enumerate(FAN_DEPOTS):
        data = fields(pos)
        stack = data['HeldItem']['value']['Item']['value']
        assert stack['id']['value'] == 'minecraft:diamond' and stack['count']['value'] == 3
        assert not saved_counts(data['OutputBuffer']['value']['Items'])
        components = stack.get('components', {}).get('value', {})
        assert bool('minecraft:damage_resistant' in components) == bool(index), components
        if index:
            selector = components['minecraft:damage_resistant']['value']['types']
            assert selector == {'type': 'string', 'value': '#minecraft:is_fire'}, selector
    for axis, connection, nodes, motor, output in RIGS:
        for pos in nodes:
            data = fields(pos)
            assert data['id']['value'] == 'create:encased_shaft', data
            assert typed_float(data['Speed']) == 32, (pos, data)
        assert typed_float(fields(output)['Speed']) == 32
        assert fields(motor)['ScrollValue']['value'] == 32
    for motor in MOTORS:
        data = fields(motor)
        assert data['ScrollValue']['value'] == 0 and typed_float(data['Speed']) == 0, (motor, data)
    assert manifest(world) == before, 'Cold reader changed source save'
    return {'passed': True, 'source_manifest': before, 'records': records,
            'material_stock': stock, 'source_game_sha256': outer['game_sha256'],
            'source_build_receipt': outer['build_receipt'],
            'source_build_receipt_sha256': outer['build_receipt_sha256']}


class Audit:
    def __init__(self, session, report, save):
        self.session = session
        self.call = session.call
        self.report = report
        self.save = save

    def record(self, name, **details):
        self.report['checks'].append({'name': name, **details})
        self.save()
        print(name, flush=True)

    def cmd(self, command):
        reply = self.call('command', command)
        assert not any(error in line for line in reply.get('chat', [])
                       for error in ('not loaded', 'Unknown block', 'Unknown item', 'Unknown command')), (command, reply)
        return reply

    def raw(self, pos, path=''):
        return ' '.join(self.cmd('data get block ' + xyz(pos) + ' ' + path)['chat'])

    def number(self, pos, key):
        raw = self.raw(pos)
        found = re.search(r'\b' + re.escape(key) + r':\s*(-?[\d.]+(?:[eE][+-]?\d+)?)', raw)
        assert found, (pos, key, raw)
        return float(found[1])

    def container(self, pos):
        return counts(self.call('container', *pos)['slots'])

    def stand(self, point):
        # Reset flight through the normal game-mode transition, then let gravity
        # settle. Floor Y127 means walking Y128 throughout this map.
        self.cmd('gamemode survival')
        self.cmd('tp @s ' + xyz(point))
        self.call('wait-ready', 120)
        wait_loaded(self.call, [(int(point[0]), 128, int(point[2]))])
        for _ in range(30):
            state = self.call('state')['player']
            if state['on_ground'] and not state['flying'] and not state['fall_flying']:
                break
            self.call('wait', 3)
        assert state['on_ground'] and not state['flying'] and not state['fall_flying'], state
        assert abs(state['position'][1] - 128) < .01, state
        ability = ' '.join(self.cmd('data get entity @s abilities.flying')['chat'])
        assert re.search(r'\b0b(?:\W|$)', ability), ability
        return state

    def aim(self, pos, face='south'):
        wait_loaded(self.call, [pos])
        assert self.call('block', *pos)['loaded'], ('Client column not loaded', pos)
        self.call('look-at', 'block', *pos, face)
        self.call('wait', 3)
        hit = self.call('state').get('looking_at')
        assert hit and hit.get('kind') == 'block' and hit.get('block', {}).get('pos') == list(pos), (pos, hit)

    def click(self, pos, point, face='south'):
        self.stand(point)
        self.aim(pos, face)
        self.call('interact', *pos, face)
        self.call('wait', 6)

    def empty_hand(self):
        inventory = self.call('inventory')
        assert inventory['carried'] is None, inventory
        slot = next((entry['slot'] for entry in inventory['hotbar'] if not entry.get('item')), None)
        assert slot is not None, ('An empty hotbar slot is needed; do not discard acceptance results', inventory)
        self.call('select', slot + 1)
        self.call('wait', 2)
        assert self.call('state')['held'] is None

    def image(self, name, target, point):
        self.stand(point)
        self.call('look-at', *target)
        self.call('wait', 6)
        path = self.session.scratch / (name + '.png')
        self.call('screenshot', path)
        assert path.is_file() and path.stat().st_size > 1024, path
        self.report['images'].append({'path': str(path), 'sha256': sha(path), 'reviewed': False})
        self.save()
        return str(path)

    def choose_motor(self, pos, value, *, point):
        assert value in (32, -32)
        self.stand(point)
        self.empty_hand()
        self.aim(pos)
        offset = self.session.log.stat().st_size
        self.call('mouse', 'right', 'down')
        self.call('wait', 10)
        assert self.call('screen')['screen'] == 'mod', self.call('screen')
        # The trace is changed-only. Move the real GUI pointer using a left
        # click (the right-use board does not commit on left release), so a
        # reopened identical board still provides a fresh layout observation.
        self.call('click-at', 0, 0)
        self.call('wait', 3)
        assert self.call('screen')['screen'] == 'mod'
        with self.session.log.open() as stream:
            stream.seek(offset)
            rows = [json.loads(line.split('Create motor board: ', 1)[1])
                    for line in stream if 'Create motor board: ' in line]
        assert rows, ('No fresh actual motor board layout', pos)
        layout = rows[-1]
        assert layout['size'][1] == 22 and layout['pos'] == list(pos), layout
        row, speed = (0 if value < 0 else 1), abs(value)
        left, top = layout['origin']
        label = layout['size'][0] - 318
        x = left + ((speed - 1) // 32) * 4 + speed + 1.5 + label + 18
        x += (2 if speed % 32 == 0 else 0) + 4
        y = top + (row + .5) * 11 - .5
        image = self.session.scratch / ('motor-' + '-'.join(map(str, pos)) + '-' + str(value) + '.png')
        self.call('screenshot', image)
        self.report['images'].append({'path': str(image), 'sha256': sha(image), 'reviewed': False})
        self.call('click-at', x, y, 'right')
        self.call('release')
        self.call('wait', 12)
        assert self.call('screen')['screen'] == 'playing'
        assert self.number(pos, 'ScrollValue') == value, (pos, value, self.raw(pos))
        self.record('Actual motor hold/release board committed', pos=pos, value=value, layout=layout)

    def loaded_scene(self):
        positions = [p for rig in RIGS for p in [*rig[2], rig[3], rig[4]]]
        wait_loaded(self.call, [*positions, *BARRELS, MATERIAL, DEPOT, BASIN, *FAN_DEPOTS, *MOTORS])
        for pos in positions:
            assert self.call('block', *pos)['loaded'], pos

    def chains(self, expected=32):
        rows = []
        for axis, connection, nodes, motor, output in RIGS:
            first = connection == ('y' if axis == 'x' else 'x')
            readings = []
            for pos, part in zip(nodes, ('start', 'middle', 'end')):
                state = self.call('block', *pos)
                properties = dict(re.findall(r'(\w+)=(\w+)', state['state']))
                assert state['block'] == 'create:encased_chain_drive', state
                assert properties == {'axis': axis, 'axis_along_first': str(first).lower(), 'part': part}, state
                assert 'id: "create:encased_shaft"' in self.raw(pos), self.raw(pos)
                readings.append({'pos': pos, 'state': state['state'], 'rpm': self.number(pos, 'Speed')})
            speeds = [entry['rpm'] for entry in readings] + [self.number(motor, 'Speed'), self.number(output, 'Speed')]
            assert speeds == [expected] * 5, (axis, connection, speeds)
            rows.append({'shaft_axis': axis, 'connection_axis': connection, 'readings': readings})
        self.record('All six delivered chain topologies and five-point RPM readings', rigs=rows)

    def initial(self):
        self.loaded_scene()
        catalog = ['create:' + item for item in CATALOG]
        for index, pos in enumerate(BARRELS):
            slots = self.call('container', *pos)['slots']
            assert len([s for s in slots if s]) == 24
            assert counts(slots) == {item: 1 for item in catalog[index * 24:(index + 1) * 24]}
        assert self.container(DEPOT) == {'minecraft:copper_ingot': 8}
        assert self.container(BASIN) == {'minecraft:snowball': 8}
        for pos in FAN_DEPOTS:
            assert self.container(pos) == {'minecraft:diamond': 3}
        for pos in MOTORS:
            assert self.number(pos, 'ScrollValue') == self.number(pos, 'Speed') == 0
        inventory = self.call('inventory')
        assert [s.get('item') for s in inventory['hotbar']] == ['create:' + item for item in (
            'wrench', 'encased_chain_drive', 'creative_motor', 'shaft', 'cogwheel', 'mechanical_press', 'depot', 'basin', 'encased_fan')]
        assert len([s for s in inventory['hotbar'] + inventory['main'] if s.get('item')]) == 36
        self.record('Cold-delivered 48 catalog entries, carried hotbar and stopped processing inputs verified')
        self.chains()

    def chain_actions(self):
        _, _, nodes, motor, output = RIGS[1]
        middle = nodes[1]
        self.stand((28.5, 128, 9.5))
        self.call('select', 'create:wrench')
        self.aim(middle, 'east')
        self.call('interact', *middle, 'east')
        self.call('wait', 12)
        state = self.call('block', *middle)
        assert all(field in state['state'] for field in ('axis=y', 'part=middle', 'axis_along_first=false')), state
        assert [self.number(pos, 'Speed') for pos in [*nodes, motor, output]] == [32] * 5
        self.record('Ordinary wrench created a powered perpendicular middle shaft', state=state)
        self.image('chain-perpendicular', (26.5, 130.5, 9.5), (29.5, 128, 12.5))
        self.stand((28.5, 128, 9.5))
        self.cmd('gamemode creative')
        self.aim(middle, 'east')
        self.call('break', *middle)
        self.call('wait', 14)
        assert self.call('block', *middle)['block'] == 'minecraft:air'
        assert all('part=none' in self.call('block', *pos)['state'] for pos in (nodes[0], nodes[2]))
        assert self.number(nodes[0], 'Speed') == 32
        assert self.number(nodes[2], 'Speed') == self.number(output, 'Speed') == 0
        self.record('Player removed middle; disconnected endpoint stopped without changing motor')
        self.call('select', 'create:encased_chain_drive')
        self.call('place', *middle)
        self.call('wait', 16)
        assert self.call('block', *middle)['block'] == 'create:encased_chain_drive'
        self.chains()
        self.record('Ordinary player placement reconnected the removed chain from carried spare')
        self.image('chain-restored', (26.5, 130.5, 9.5), (29.5, 128, 12.5))

    def crafts(self):
        self.cmd('clear @s')
        self.call('wait', 3)
        assert self.call('inventory')['counts'] == {}
        self.click(MATERIAL, (6.5, 128, 4.5))
        screen = self.call('screen')
        assert screen['screen'] == 'container' and screen['container'] == list(MATERIAL), screen
        before = self.call('container', *MATERIAL)['slots']
        wanted = {'create:andesite_casing': 8, 'minecraft:iron_nugget': 32, 'create:zinc_nugget': 16}
        chosen = [(i, s) for i, s in enumerate(before) if s and s['item'] in wanted]
        assert counts([s for _, s in chosen]) == wanted
        for slot, _ in chosen:
            self.call('click-slot', 300 + slot, 'shift')
            self.call('wait', 3)
        self.call('close')
        self.call('wait', 4)
        assert self.call('inventory')['counts'] == wanted
        after = self.call('container', *MATERIAL)['slots']
        for slot, stack in enumerate(before):
            assert after[slot] == (None if slot in {s for s, _ in chosen} else stack), (slot, before, after)
        expected = collections.Counter(wanted)
        for name, metal in RECIPES:
            recipe_path = ROOT / 'content/data/create/recipe/crafting/kinetics' / (name + '.json')
            recipe = json.loads(recipe_path.read_text())
            assert recipe['type'] == 'minecraft:crafting_shapeless'
            tag = '#c:nuggets/' + ('iron' if 'iron' in metal else 'zinc')
            assert recipe['ingredients'] == ['create:andesite_casing', tag, tag, tag]
            assert recipe['result'] == {'count': 1, 'id': 'create:encased_chain_drive'}
            self.empty_hand()
            self.click(TABLE, (8.5, 128, 4.5))
            assert self.call('screen')['screen'] == 'inventory'
            inventory = self.call('inventory')
            sources = {s['item']: s['slot'] for s in inventory['hotbar'] + inventory['main'] if s.get('item')}
            cells = {100: 'create:andesite_casing', 101: metal, 102: metal, 103: metal}
            for item in ('create:andesite_casing', metal):
                source = sources[item]
                self.call('click-slot', source)
                for slot, ingredient in cells.items():
                    if ingredient == item:
                        self.call('click-slot', slot, 'right')
                if self.call('inventory')['carried'] is not None:
                    self.call('click-slot', source)
                assert self.call('inventory')['carried'] is None
            self.call('wait', 5)
            output = next(s for s in self.call('screen')['slots'] if s['slot'] == 200)
            assert output.get('item') == 'create:encased_chain_drive' and output.get('count') == 1, output
            path = self.session.scratch / ('craft-' + name + '.png')
            self.call('screenshot', path)
            self.report['images'].append({'path': str(path), 'sha256': sha(path), 'reviewed': False})
            # Shift-click would repeat the recipe. One normal output click
            # consumes exactly one casing and three nuggets.
            self.call('click-slot', 200)
            carried = self.call('inventory')['carried']
            assert carried and carried['item'] == 'create:encased_chain_drive' and carried['count'] == 1, carried
            empty = next(s['slot'] for s in self.call('inventory')['hotbar'] + self.call('inventory')['main'] if not s.get('item'))
            self.call('click-slot', empty)
            self.call('close')
            self.call('wait', 5)
            expected['create:andesite_casing'] -= 1
            expected[metal] -= 3
            expected['create:encased_chain_drive'] += 1
            assert self.call('inventory')['counts'] == dict(+expected), (name, expected, self.call('inventory'))
            assert self.call('inventory')['carried'] is None
            self.record('Survival crafting menu consumed delivered stock', recipe=name,
                        recipe_sha256=sha(recipe_path), inventory=dict(+expected), image=str(path))

    def wait_counts(self, pos, expected, maximum=1600):
        for elapsed in range(0, maximum + 1, 20):
            actual = self.container(pos)
            if actual == expected:
                return elapsed
            if elapsed < maximum:
                self.call('wait', 20)
        raise AssertionError(('Machine did not reach exact expected inventory', pos, expected, actual, self.raw(pos)))

    def collect(self, pos, expected, point):
        before = collections.Counter(self.call('inventory')['counts'])
        self.empty_hand()
        # SharedDepotBlockMethods.onUse accepts the UP face only. A side hit is
        # a valid refusal, even with the exact block and an empty hand.
        self.click(pos, point, 'up' if pos == DEPOT else 'south')
        before.update(expected)
        assert self.call('inventory')['counts'] == dict(before), (pos, before, self.call('inventory'))
        assert self.container(pos) == {}, (pos, self.raw(pos))
        self.record('Empty-hand collection transferred exact complete output', pos=pos, output=expected)

    def machines(self, *, press_ready=False):
        if press_ready:
            assert self.container(DEPOT) == {'create:copper_sheet': 8}
        else:
            self.choose_motor((6, 130, 34), 32, point=(6.5, 128, 36.5))
            elapsed = self.wait_counts(DEPOT, {'create:copper_sheet': 8})
            self.record('Delivered eight copper ingots became eight copper sheets', wait_ticks=elapsed)
        self.image('press-eight-sheets', (8.5, 129, 34.5), (10.5, 128, 36.5))
        self.collect(DEPOT, {'create:copper_sheet': 8}, (8.5, 128, 36.5))
        self.image('press-collected-empty', (8.5, 129, 34.5), (10.5, 128, 36.5))
        self.choose_motor((16, 130, 34), 32, point=(16.5, 128, 36.5))
        elapsed = self.wait_counts(BASIN, {'minecraft:snow_block': 2})
        assert re.search(r'\[\s*\]', self.raw(BASIN, 'InputItems.Items')), self.raw(BASIN)
        self.record('Delivered eight snowballs compacted into exactly two snow blocks', wait_ticks=elapsed)
        self.image('basin-two-blocks', (18.5, 128.7, 34.5), (20.5, 128, 36.5))
        self.collect(BASIN, {'minecraft:snow_block': 2}, (18.5, 128, 36.5))
        for motor in FANS:
            self.choose_motor(motor, 32, point=(motor[0] + .5, 128, motor[2] + 2.5))
        elapsed = self.wait_counts(FAN_DEPOTS[0], {}, maximum=800)
        self.call('wait', 220)
        assert self.container(FAN_DEPOTS[0]) == {}
        assert self.container(FAN_DEPOTS[1]) == {'minecraft:diamond': 3}
        protected = self.raw(FAN_DEPOTS[1], 'HeldItem.Item')
        assert 'minecraft:damage_resistant' in protected and '#minecraft:is_fire' in protected, protected
        self.record('Source blasting destroyed ordinary diamonds and retained full-fire component stack',
                    ordinary_wait_ticks=elapsed, protected_item=protected)
        self.image('fan-ordinary-empty', (34.5, 129, 32.5), (36.5, 128, 34.5))
        self.image('fan-full-fire-three', (34.5, 129, 36.5), (36.5, 128, 38.5))

    def snapshot(self):
        result = {'states': {}, 'canonical': {}, 'motors': {}, 'containers': {}}
        for pos in [p for rig in RIGS for p in [*rig[2], rig[3], rig[4]]]:
            value = self.call('block', *pos)
            result['states'][xyz(pos)] = {'block': value['block'], 'state': value['state'], 'rpm': self.number(pos, 'Speed')}
        for pos, paths in CANONICAL.items():
            result['canonical'][xyz(pos)] = {key: self.raw(pos, key) for key in paths}
        for pos in [*MOTORS, *[rig[3] for rig in RIGS]]:
            result['motors'][xyz(pos)] = self.number(pos, 'ScrollValue')
        for pos in [*BARRELS, MATERIAL, *CANONICAL]:
            result['containers'][xyz(pos)] = self.call('container', *pos)['slots']
        inventory = self.call('inventory')
        result['player'] = {key: inventory[key] for key in ('hotbar', 'main', 'armor', 'offhand', 'carried', 'counts')}
        return result

    def restart(self, name):
        self.cmd('tick freeze')
        self.call('wait', 5)
        self.loaded_scene()
        before = self.snapshot()
        self.call('save-all')
        previous = self.session.process
        starts = self.session.starts
        self.session.restart()
        assert previous.poll() == 0 and self.session.starts == starts + 1
        assert self.session.process.pid != previous.pid
        self.cmd('tick freeze')
        self.loaded_scene()
        after = self.snapshot()
        assert after == before, ('Restart changed canonical inventories/components/state', name, before, after)
        path = self.session.scratch / ('restart-' + name + '.json')
        path.write_text(json.dumps({'passed': True, 'before': before, 'after': after,
                                   'previous_pid': previous.pid, 'next_pid': self.session.process.pid}, indent=2) + '\n')
        self.cmd('tick unfreeze')
        self.call('wait', 5)
        self.record('True process restart preserved exact canonical data', phase=name, artifact=str(path),
                    previous_pid=previous.pid, next_pid=self.session.process.pid)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'resources', 'ctl', 'create-jar', 'build-receipt', 'source'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    source.relative_to((ROOT / '.local').resolve())
    game = args.game.resolve()
    receipt = json.loads(args.build_receipt.read_text())
    assert receipt['passed'] and Path(receipt['game']).resolve() == game
    assert sha(game) == receipt['game_sha256'], 'Binary differs from build receipt'
    assert sha(args.create_jar) == CREATE_SHA256, 'Unexpected original private Create JAR'
    cold = cold_preflight(source)
    assert cold['source_game_sha256'] == sha(game), 'Audit binary differs from source authoring binary'
    assert sha(Path(cold['source_build_receipt'])) == cold['source_build_receipt_sha256']
    session = NativeCheckSession(game, args.resources, args.ctl, args.create_jar,
                                 name='review07-audit', graphics=True, world=WORLD, username='Delete228')
    session.env.update(HORIZON_API_DISCOVERY='http://127.0.0.1:9/', HORIZON_NO_DISCORD='1')
    target = session.scratch / 'saves' / WORLD
    target.parent.mkdir()
    shutil.copytree(source / 'saves' / WORLD, target, copy_function=shutil.copy2)
    assert manifest(target) == cold['source_manifest']
    assert all(path.stat().st_nlink == 1 for path in target.rglob('*') if path.is_file())
    (session.scratch / 'options.txt').write_text('tutorialStep:none\nchatVisibility:2\nlang:en_us\n')
    (session.scratch / 'cold-preflight.json').write_text(json.dumps(cold, indent=2) + '\n')
    report = {'passed': False, 'world': WORLD, 'source': str(source), 'scratch': str(session.scratch),
              'game': str(game), 'game_sha256': sha(game), 'build_receipt': str(args.build_receipt.resolve()),
              'build_receipt_sha256': sha(args.build_receipt), 'source_unchanged': False,
              'cold_preflight': True, 'checks': [], 'images': [], 'images_reviewed': False,
              'release_acceptance': False,
              'scope': 'Delivered six rigs, player wrench/removal/reconnection, real motor UI, supplied press/Basin/fan inputs, two stock-funded survival crafts and two process restarts.',
              'boundaries': ['No cross-client pixel/audio parity claim.',
                             'Removing the middle uses creative player mining and its carried spare; crafting uses survival delivered stock.',
                             'Only ordinary and full minecraft:is_fire diamond selectors are exercised.'],
              'tool_sources': {name: sha(ROOT / 'tools' / name) for name in (
                  'review_world_07_audit.py', 'review_world_07.py', 'native_check_session.py', 'saved_block_checks.py')}}
    output = session.scratch / 'aggregate-result.json'

    def save():
        output.write_text(json.dumps(report, indent=2) + '\n')

    audit = Audit(session, report, save)
    save()
    print(session.scratch, flush=True)
    try:
        with session:
            audit.initial()
            audit.restart('delivered')
            audit.chain_actions()
            audit.crafts()
            audit.choose_motor(RIGS[1][3], -32, point=(25.5, 128, 10.5))
            assert [audit.number(pos, 'Speed') for pos in [*RIGS[1][2], RIGS[1][4]]] == [-32] * 4
            audit.choose_motor(RIGS[1][3], 32, point=(25.5, 128, 10.5))
            audit.chains()
            audit.machines()
            audit.restart('completed')
            assert session.starts == 3
            report['process_starts'] = session.starts
            report['passed'] = True
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        report['source_unchanged'] = manifest(source / 'saves' / WORLD) == cold['source_manifest']
        if not report['source_unchanged']:
            report['passed'] = False
        report['process_stopped'] = session.process is None
        save()
        print(json.dumps({'result': str(output), 'passed': report['passed'],
                          'source_unchanged': report['source_unchanged']}), flush=True)
    assert report['source_unchanged'], 'The closed source save changed'


if __name__ == '__main__':
    main()
