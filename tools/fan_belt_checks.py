"""Real fan/belt acceptance in caller-owned disposable native worlds.

Uses ordinary ticks, real connector clicks and dropped stacks. A stopped belt is
independent of the active fan. prepare/reloaded must straddle a true client exit
and restart; neither /tick freeze nor a fabricated fan timer is used.
"""
import json
from pathlib import Path
import re

from common import ROOT, PINS
from native_check_session import wait_loaded
from native_motors import replace_motor

X, Y, Z = 448, 80, 12


class Check:
    def __init__(self, call, scratch):
        self.call = call
        self.scratch = Path(scratch).resolve()
        self.scratch.relative_to((ROOT / '.local').resolve())
        assert call('state')['world'] == 'CreateParity06'

    def command(self, line):
        reply = self.call('command', line)
        assert not any('not loaded' in s or 'Unknown block' in s for s in reply.get('chat', [])), (line, reply)
        return reply

    def data(self, path='Inventory'):
        reply = self.command(f'data get block {X} {Y} {Z} {path}')
        return ' '.join(reply['chat'])

    def snapshot(self):
        raw = self.data()
        identity = re.search(r'\bid:\s*"([^"]+)"', raw)
        count = re.search(r'\bcount:\s*(\d+)', raw)
        position = re.search(r'\bPos:\s*(-?[\d.eE+-]+)f', raw)
        timer = re.search(r'\bFanProcessingTime:\s*(-?\d+)', raw)
        kind = re.search(r'\bFanProcessingType:\s*"([^"]+)"', raw)
        return {'raw': raw, 'item': identity[1] if identity else None,
                'count': int(count[1]) if count else 0,
                'position': float(position[1]) if position else None,
                'timer': int(timer[1]) if timer else None,
                'kind': kind[1] if kind else None}

    def power(self, *, belt=None, fan=None):
        """Publish new drive speeds by replacement, then retain the eight-tick settle."""
        if belt is not None:
            replace_motor(self.call, (X - 1, Y, Z), belt, 'east')
        if fan is not None:
            replace_motor(self.call, (X - 4, Y + 1, Z + 2), fan, 'east')
        self.call('wait', 8)

    def stand(self, offset):
        self.command(f'tp @s {X + 2.5} {Y} {Z + offset - 1.5}')
        self.call('wait', 3)
        player = self.call('status')['player']
        assert player['on_ground'] and abs(player['position'][1] - Y) < .001, player

    def setup(self, medium):
        self.command('tick unfreeze')
        self.command('tick rate 20')
        self.command('gamemode creative')
        self.command('gamerule minecraft:spawn_mobs false')
        self.command(f'tp @s {X + 2.5} {Y} {Z + 2.5}')
        self.command(f'forceload add {X - 16} {Z - 16} {X + 16} {Z + 16}')
        self.call('wait-ready', 120)
        wait_loaded(self.call, [(x, Y, z) for x in [X - 7, X + 8]
                               for z in [Z - 3, Z + 8]])
        self.command(f'fill {X - 7} {Y - 3} {Z - 3} {X + 8} {Y + 6} {Z + 8} minecraft:air')
        self.command(f'fill {X - 7} {Y - 1} {Z - 3} {X + 8} {Y - 1} {Z + 8} minecraft:smooth_stone')
        self.command('kill @e[type=minecraft:item]')
        self.command('clear @s')
        for pos, block in [((X - 1, Y, Z), 'create:creative_motor[facing=east]'),
                           ((X, Y, Z), 'create:shaft[axis=x]'),
                           ((X, Y, Z + 5), 'create:shaft[axis=x]'),
                           ((X, Y, Z + 6), 'create:depot'),
                           ((X - 4, Y + 1, Z + 2), 'create:creative_motor[facing=east]'),
                           ((X - 3, Y + 1, Z + 2), 'create:encased_fan[facing=east]'),
                           ((X - 2, Y, Z + 2), 'minecraft:glass')]:
            self.command('setblock ' + ' '.join(map(str, pos)) + ' ' + block)
        self.power(belt=0, fan=0)
        self.medium(medium)
        self.command('give @s create:belt_connector 1')
        self.call('wait', 5)
        self.call('select', 'create:belt_connector')
        for offset in [0, 5]:
            self.stand(offset)
            self.call('look-at', 'block', X, Y, Z + offset, 'east')
            self.call('wait', 2)
            self.call('interact', X, Y, Z + offset, 'east')
            self.call('wait', 8)
        for offset in range(6):
            assert self.call('block', X, Y, Z + offset)['block'] == 'create:belt'
        self.stand(5)
        self.command('clear @s')

    def medium(self, kind):
        block = {'splashing': 'minecraft:oak_fence[waterlogged=true]',
                 'smoking': 'minecraft:campfire[lit=true]',
                 'haunting': 'minecraft:soul_campfire[lit=true]',
                 'blasting': 'minecraft:lava'}[kind]
        if kind == 'blasting':
            for p in [(X - 2, Y + 2, Z + 2), (X - 2, Y + 1, Z + 1),
                      (X - 2, Y + 1, Z + 3)]:
                self.command('setblock ' + ' '.join(map(str, p)) + ' minecraft:glass')
            self.command(f'setblock {X - 1} {Y + 1} {Z + 2} minecraft:iron_bars')
        self.command(f'setblock {X - 2} {Y + 1} {Z + 2} {block}')

    def feed(self, item, count, marker):
        self.power(belt=8, fan=0)
        self.command(f'summon minecraft:item {X + .5} {Y + 1.05} {Z + 2.5} '
                     + '{PickupDelay:32767,Item:{id:"' + item + '",count:' + str(count)
                     + ',components:{"minecraft:custom_data":{fan_belt_marker:' + str(marker) + '}}}}')
        self.call('wait', 8)
        self.power(belt=0)
        state = self.snapshot()
        assert state['item'] == item and state['count'] == count, state
        assert f'fan_belt_marker: {marker}' in state['raw'], state
        assert abs(state['position'] - 2.5) < .51, state
        self.call('wait', 8)
        assert self.snapshot()['position'] == state['position'], (state, self.snapshot())
        return state

    def until(self, predicate, *, ticks=800):
        for _ in range(ticks // 5):
            state = self.snapshot()
            if predicate(state):
                return state
            self.call('wait', 5)
        raise AssertionError(('Fan belt condition timed out', self.snapshot()))

    def depot(self, item):
        return sum(slot['count'] for slot in self.call('container', X, Y, Z + 6)['slots']
                   if slot and slot['item'] == item)


def prepare(call, *, graphics=False, log=None, scratch=None):
    check = Check(call, scratch)
    check.setup('splashing')
    initial = check.feed('create:wheat_flour', 17, 617)
    check.power(fan=256)
    first = check.until(lambda s: s['kind'] == 'create:splashing' and s['timer'] is not None)
    assert first['item'] == 'create:wheat_flour' and 0 < first['timer'] <= 301, first
    call('wait', 10)
    progressed = check.snapshot()
    assert 0 < progressed['timer'] < first['timer'], (first, progressed)
    assert progressed['position'] == initial['position'] and progressed['count'] == 17, progressed
    assert 'fan_belt_marker: 617' in progressed['raw'], progressed
    check.power(fan=0)
    saved = check.snapshot()
    call('wait', 10)
    assert check.snapshot() == saved, (saved, check.snapshot())
    fixture = {'saved': saved, 'reference': PINS['create_revision'],
               'scope': 'Ordinary dropped input, stopped belt, active fan NoOp metadata persisted; requires actual process restart before reloaded'}
    (check.scratch / 'fan-belt-prepared.json').write_text(json.dumps(fixture, indent=2) + '\n')
    print('Fan belt: real stopped-belt progress saved before restart', flush=True)
    return fixture


def overlap_queue(check):
    """Two active, different-media fans before the next serialization boundary.

    The controller is created before both fan tickers. No timer is fabricated:
    a naturally progressing one is observed at 1 TPS to activate the second
    fan on the exact conversion tick. The conditional read also proves that
    secondary fan's previous tick already reached its real -256 RPM.
    """
    check.setup('splashing')
    check.command(f'setblock {X - 3} {Y + 1} {Z + 2} minecraft:air')
    check.command(f'setblock {X - 3} {Y + 1} {Z + 2} create:encased_fan[facing=east]')
    for pos, block in [((X + 2, Y, Z + 2), 'minecraft:glass'),
                       ((X + 2, Y + 1, Z + 2), 'minecraft:campfire[lit=true]'),
                       ((X + 4, Y + 1, Z + 2), 'create:creative_motor[facing=west]')]:
        check.command('setblock ' + ' '.join(map(str, pos)) + ' ' + block)
    replace_motor(check.call, (X + 4, Y + 1, Z + 2), 0, 'west')
    check.command(f'setblock {X + 3} {Y + 1} {Z + 2} create:encased_fan[facing=west]')
    check.feed('create:wheat_flour', 1, 819)
    check.power(fan=256)
    check.until(lambda s: s['timer'] is not None and 0 < s['timer'] <= 8)
    check.command('tick rate 1')
    try:
        for _ in range(12):
            before = check.snapshot()
            assert before['item'] == 'create:wheat_flour' and before['timer'] > 0, before
            if before['timer'] == 1:
                break
        else:
            raise AssertionError(('Did not observe natural final timer tick', before))
        replace_motor(check.call, (X + 4, Y + 1, Z + 2), 256, 'west')
        reply = check.command(
            f'execute if data block {X + 3} {Y + 1} {Z + 2} {{Speed:-256.0f}} '
            f'run data get block {X} {Y} {Z} Inventory')
        observed = ' '.join(reply['chat'])
        assert 'create:dough' in observed and 'create:wheat_flour' not in observed, observed
        assert 'create:splashing' in observed and 'create:smoking' not in observed, observed
        assert re.search(r'\bFanProcessingTime:\s*-1\b', observed), observed
        return {'before': before, 'conditional_native_inventory': observed,
                'secondary_speed_condition': -256,
                'scope': 'One actual stopped-belt conversion with two different-media fan handlers before flush; no exhaustive overlap or cross-client timing claim'}
    finally:
        check.command('tick rate 20')
        replace_motor(check.call, (X + 4, Y + 1, Z + 2), 0, 'west')
        check.power(fan=0)


def reloaded(call, fixture, *, graphics=False, log=None, scratch=None):
    check = Check(call, scratch)
    check.command(f'tp @s {X + 2.5} {Y} {Z + 3.5}')
    call('wait-ready', 120)
    call('wait', 10)
    restored = check.snapshot()
    for field in ['item', 'count', 'position', 'timer', 'kind']:
        assert restored[field] == fixture['saved'][field], (field, fixture, restored)
    assert 'fan_belt_marker: 617' in restored['raw'], restored
    check.power(fan=256)
    converted = check.until(lambda s: s['item'] == 'create:dough')
    assert converted['count'] == 17 and converted['position'] == restored['position'], converted
    assert converted['timer'] == -1 and converted['kind'] == 'create:splashing', converted
    assert 'fan_belt_marker' not in converted['raw'] and 'Locked:' not in converted['raw'], converted
    call('wait', 15)
    assert check.snapshot() == converted, (converted, check.snapshot())
    if graphics:
        check.stand(5)
        call('look-at', X - .5, Y + .7, Z + 2.5)
        call('wait', 3)
        call('screenshot', check.scratch / 'fan-belt-native.png')
    check.power(fan=0, belt=32)
    for _ in range(100):
        if check.depot('create:dough') == 17:
            break
        call('wait', 5)
    else:
        raise AssertionError(('Converted stack did not travel into depot', check.data(), check.depot('create:dough')))
    assert check.snapshot()['count'] == 0, check.data()
    print('Fan belt: exact timer/component restart, source conversion, normal transport and depot output PASS', flush=True)

    check.setup('smoking')
    unsupported = check.feed('minecraft:diamond', 3, 718)
    check.power(fan=256)
    refused = check.until(lambda s: s['kind'] == 'create:smoking' and s['timer'] == -1)
    call('wait', 20)
    assert check.snapshot() == refused and refused['count'] == 3, refused
    assert refused['position'] == unsupported['position'] and 'fan_belt_marker: 718' in refused['raw'], refused
    check.power(fan=0)
    check.medium('blasting')
    check.power(fan=256)
    burning = check.until(lambda s: s['kind'] == 'create:blasting' and s['timer'] is not None)
    assert burning['item'] == 'minecraft:diamond' and 0 < burning['timer'] <= 151, burning
    destroyed = check.until(lambda s: s['count'] == 0)
    assert check.depot('minecraft:diamond') == 0, check.data()
    queue = overlap_queue(check)
    report = {'passed': True, 'reference': PINS['create_revision'], 'restored': restored,
              'converted': converted, 'unsupported': refused, 'burning': burning, 'destroyed': destroyed,
              'overlap_queue': queue,
              'checks': ['ordinary dropped stack captured through connector-built belt',
                         'stopped belt processes while fan active; NoOp progress persists',
                         'true restart retains exact timer, position, count and custom components',
                         'getSimilar output retains completed fan sentinel and unlocks; clean recipe result',
                         'normal belt movement delivers exactly17 dough to depot',
                         'unsupported smoking caches -1 and preserves full input/components',
                         'switching medium restarts timer; blasting removes item without output',
                         'two different-media active fans cannot process a pending conversion before flush'],
              'scope': 'Native integration and actual process restart; deterministic supported recipes. No arbitrary recipe/addon, audiovisual pixel parity, or exhaustive overlapping-fan claim.'}
    (check.scratch / 'fan-belt-result.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Fan belt: unsupported medium cache, medium switch and queued destruction PASS', flush=True)
    return report
