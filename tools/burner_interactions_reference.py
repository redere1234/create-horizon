#!/usr/bin/env python3
"""Exercise pinned original burner interactions through the isolated Java client."""
import argparse
import json
from pathlib import Path
import re
import tempfile
import time
from reference_java import BASE, ROOT, call


class Reference:
    def __init__(self, root, output):
        self.root, self.output = root, output
        self.transcript, self.cases = [], []

    def invoke(self, method, **body):
        result = call(self.root, method, body)
        self.transcript.append({'method': method, 'body': body, 'result': result})
        (self.output / 'transcript.json').write_text(json.dumps(self.transcript, indent=2) + '\n')
        return result

    def command(self, text):
        return self.invoke('command', command=text)

    def block(self):
        return self.invoke('block', pos=[482, 63, 10])

    def selected(self):
        result = self.command('data get entity @s SelectedItem')
        text = ' '.join(result['messages'])
        item = re.search(r'\bid:\s*"([^"]+)"', text)
        count = re.search(r'\bcount:\s*(\d+)', text)
        damage = re.search(r'"minecraft:damage":\s*(\d+)', text)
        return {'id': item[1] if item else None, 'count': int(count[1]) if count else 0,
                'damage': int(damage[1]) if damage else 0, 'raw': text}

    def wait(self, predicate, seconds=5):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(.05)
        raise AssertionError('Timed out waiting for original client state')

    def setup(self, state, item, count=1, creative=False):
        self.invoke('input', key='use', down=False)
        self.invoke('input', key='shift', down=False)
        self.command('gamemode creative' if creative else 'gamemode survival')
        self.command('clear @s')
        self.command('setblock 482 63 11 air')
        self.command('setblock 482 63 10 air')
        self.command(f'setblock 482 63 10 {state}')
        self.command(f'item replace entity @s weapon.mainhand with {item} {count}')
        self.invoke('camera', position=[482.5, 63, 13], target=[482.5, 63.5, 10.5])
        self.wait(lambda: self.invoke('state').get('hit', {}).get('pos') == [482.0, 63.0, 10.0])
        time.sleep(.25)

    def click(self):
        self.invoke('input', key='use')
        time.sleep(.25)

    def record(self, name, **details):
        self.cases.append({'case': name, **details})
        (self.output / 'result.json').write_text(json.dumps({'status': 'running', 'cases': self.cases}, indent=2) + '\n')

    def has_filled(self):
        return any('Test passed' in line for slots in ['hotbar.*', 'inventory.*'] for line in
                   self.command(f'execute if items entity @s {slots} create:blaze_burner')['messages'])

    def capture_cases(self):
        next_blaze = 'SpawnData:{entity:{id:"minecraft:blaze"}}'
        next_zombie = 'SpawnData:{entity:{id:"minecraft:zombie"}}'
        zombie = '{weight:1,data:{entity:{id:"minecraft:zombie"}}}'
        blaze = '{weight:1,data:{entity:{id:"minecraft:blaze"}}}'
        for name, data, count, creative in [
            ('spawner_empty_potentials_uses_next', next_blaze + ',SpawnPotentials:[]', 1, False),
            ('spawner_any_potential_captures', next_zombie + ',SpawnPotentials:[' + zombie + ',' + blaze + ']', 2, False),
            ('creative_capture_keeps_empty', next_blaze + ',SpawnPotentials:[]', 1, True),
        ]:
            self.setup('minecraft:spawner{' + data + '}', 'create:empty_blaze_burner', count, creative)
            before = self.block()
            self.click()
            held = self.wait(lambda: value if (value := self.selected())['id'] ==
                             ('create:empty_blaze_burner' if creative or count > 1 else 'create:blaze_burner') else None)
            assert held['count'] == (count if creative else max(1, count - 1)), held
            if creative or count > 1:
                assert self.has_filled()
            after = self.block()
            assert before == after, (before, after)
            self.record(name, block=after, held=held)
        self.setup('minecraft:spawner{' + next_blaze + ',SpawnPotentials:[' + zombie + ']}', 'create:empty_blaze_burner')
        self.click()
        adjacent = self.invoke('block', pos=[482, 63, 11])
        assert adjacent['id'] == 'create:blaze_burner' and adjacent['properties']['blaze'].lower() == 'none', adjacent
        assert not self.has_filled()
        self.record('nonempty_potentials_do_not_fallback_to_next', adjacent=adjacent, held=self.selected())

        self.command('gamemode survival')
        self.command('clear @s')
        self.command('fill -3 199 -3 3 199 5 stone')
        self.command('fill -3 200 -3 3 204 5 air')
        self.command('item replace entity @s weapon.mainhand with create:empty_blaze_burner 1')
        self.command('summon minecraft:blaze 0.5 200 0.5 {NoAI:1b,Silent:1b,PersistenceRequired:1b,Tags:["burner_interaction_probe"]}')
        self.invoke('camera', position=[.5, 200, 3], target=[.5, 200.8, .5])
        self.wait(lambda: self.invoke('state').get('hit', {}).get('type') == 'ENTITY')
        # Normal client simulation drains ParticleEngine's pending-add queue.
        # Frozen engine snapshots alone cannot prove a capture burst's count.
        self.invoke('tick', frozen=False)
        time.sleep(.15)
        before_particles = self.invoke('particles', limit=2048)
        self.click()
        def gone():
            value = self.invoke('entities', center=[.5, 200, .5], radius=3)
            return value if not any(e['type'] == 'minecraft:blaze' for e in value['entities']) else None
        entities = self.wait(gone)
        held = self.selected()
        assert held['id'] == 'create:blaze_burner' and held['count'] == 1, held
        particles = self.invoke('particles', limit=2048)
        self.invoke('tick', frozen=True)
        previous = {sample['instance_id'] for sample in before_particles['samples']}
        new = [sample for sample in particles['samples'] if sample['instance_id'] not in previous]
        assert sum(sample['class'].endswith('.FlameParticle') for sample in new) == 40, particles['counts']
        assert sum(sample['class'].endswith('.SmokeParticle') for sample in new) == 40, particles['counts']
        self.record('living_blaze_capture_discards_without_loot', held=held, entities=entities,
                    particles_before=before_particles, particles_after=particles)

    def wrench_cases(self):
        for state, expected in [('create:blaze_burner', 'create:empty_blaze_burner'),
                                ('create:blaze_burner[blaze=smouldering]', 'create:blaze_burner'),
                                ('create:lit_blaze_burner', 'create:empty_blaze_burner')]:
            self.setup(state, 'create:wrench')
            self.invoke('input', key='shift', down=True)
            time.sleep(.2)
            self.invoke('camera', position=[482.5, 63, 13], target=[482.5, 63.5, 10.5])
            self.wait(lambda: self.invoke('state').get('hit', {}).get('pos') == [482.0, 63.0, 10.0])
            self.click()
            self.invoke('input', key='shift', down=False)
            removed = self.wait(lambda: value if (value := self.block())['id'] == 'minecraft:air' else None)
            check = [self.command(f'execute if items entity @s {slots} {expected}') for slots in ['hotbar.*', 'inventory.*']]
            assert any('Test passed' in line for result in check for line in result['messages']), check
            self.record('sneak_wrench_' + state, removed=removed, expected=expected, inventory=check)

    def run(self):
        state = self.invoke('state')
        if state.get('screen') == 'PauseScreen':
            self.invoke('input', kind='escape')
            state = self.invoke('state')
        assert state['ready'], state
        assert state['data_version'] == 3955, state
        self.invoke('tick', frozen=True)
        for command in ['fill 478 63 8 490 68 16 air', 'fill 478 62 8 490 62 16 stone',
                        'difficulty normal', 'gamerule doMobSpawning false', 'time set day']:
            self.command(command)
        self.setup('create:blaze_burner', 'minecraft:flint_and_steel')
        original = self.block()
        assert original['properties']['blaze'].lower() == 'none'
        self.click()
        lit = self.wait(lambda: (value if (value := self.block())['id'] == 'create:lit_blaze_burner' else None))
        held = self.selected()
        assert lit['properties']['flame_type'].lower() == 'regular' and held['damage'] == 1, (lit, held)
        self.record('empty_flint_to_regular', default_state=original, block=lit, held=held)
        self.setup('create:lit_blaze_burner', 'minecraft:iron_shovel')
        self.click()
        empty = self.wait(lambda: (value if (value := self.block())['id'] == 'create:blaze_burner' else None))
        held = self.selected()
        assert empty['properties']['blaze'].lower() == 'none' and held['damage'] == 1, (empty, held)
        self.record('shovel_extinguishes', block=empty, held=held)
        self.setup('create:lit_blaze_burner', 'minecraft:soul_sand', 2)
        self.click()
        soul = self.wait(lambda: (value if (value := self.block())['properties'].get('flame_type', '').lower() == 'soul' else None))
        held = self.selected()
        assert held['id'] == 'minecraft:soul_sand' and held['count'] == 2, held
        self.record('soul_conversion_does_not_consume', block=soul, held=held)
        self.setup('create:lit_blaze_burner', 'minecraft:water_bucket')
        self.click()
        self.invoke('tick', step=2)
        block = self.block()
        assert block['id'] == 'create:lit_blaze_burner', block
        self.record('water_does_not_directly_extinguish', block=block, held=self.selected())
        self.capture_cases()
        self.wrench_cases()
        result = {'status': 'pass', 'source': 'Create6.0.10 ac0c444d9828da3453ae8cc65338e8de063286fb',
                  'cases': self.cases, 'limitations': ['Clone/pick requires a separate original input case. No pixel parity claim.']}
        (self.output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=BASE)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = args.output or Path(tempfile.mkdtemp(prefix='burner-interactions-java-', dir=ROOT / '.local'))
    output.mkdir(parents=True, exist_ok=True)
    reference = Reference(args.root.resolve(), output.resolve())
    try:
        result = reference.run()
    except Exception as error:
        (output / 'result.json').write_text(json.dumps({'status': 'fail', 'error': str(error), 'cases': reference.cases}, indent=2) + '\n')
        raise
    print(json.dumps({'status': result['status'], 'cases': len(result['cases']), 'output': str(output.resolve())}))


if __name__ == '__main__':
    main()
