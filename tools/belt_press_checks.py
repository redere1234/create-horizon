"""Black-box press/belt acceptance in a caller-owned disposable native world.

Uses real connector clicks, ordinary dropped stacks, independent motors and
depot output. This is an integration check, separate from Java method oracles.
It does not claim arbitrary belt schematics or sequenced-assembly support.
"""
import json
from pathlib import Path
import re
from native_motors import replace_motor

from common import ROOT, PINS
from native_check_session import wait_loaded


def run(call, graphics=False, log=None, scratch=None, *, prepare_restart=False, check_freeze=False):
    scratch = Path(scratch).resolve()
    scratch.relative_to((ROOT / '.local').resolve())
    assert call('state')['world'] == 'CreateParity06'
    x, y, z = 352, 80, 12
    report = {'passed': False, 'checks': [], 'images': [], 'reference': PINS['create_revision'],
              'scope': 'Real native connector/drop/press/depot integration; default nonbulk, deterministic sheet recipes'}
    path = scratch / 'belt-press-result.json'
    transcript = scratch / 'belt-press-transcript.jsonl'
    transcript.write_text('')

    def save():
        path.write_text(json.dumps(report, indent=2) + '\n')

    def ctl(*args):
        reply = call(*args)
        with transcript.open('a') as stream:
            stream.write(json.dumps({'command': list(map(str, args)), 'reply': reply}) + '\n')
        return reply

    def command(line):
        reply = ctl('command', line)
        assert not any('not loaded' in text or 'Unknown block' in text for text in reply.get('chat', [])), (line, reply)
        return reply

    def data(pos, key=''):
        return ' '.join(command('data get block ' + ' '.join(map(str, pos)) + (' ' + key if key else ''))['chat'])

    def inventory():
        return data((x, y, z), 'Inventory')

    def counts():
        slots = ctl('container', x + 1, y - 1, z + 6)['slots']
        return {item: sum(slot['count'] for slot in slots
                          if slot and slot['item'] == item)
                for item in ['minecraft:copper_ingot', 'create:copper_sheet', 'minecraft:diamond']}

    def power(belt=None, press=None):
        if belt is not None:
            replace_motor(ctl, (x - 1, y, z), belt, 'east')
        if press is not None:
            replace_motor(ctl, (x - 1, y + 2, z + 2), press, 'east')
        ctl('wait', 8)

    def stand(offset):
        command(f'tp @s {x + 2.5} {y} {z + offset - 1.5}')
        ctl('wait', 3)
        player = ctl('state')['player']
        assert player['on_ground'] and abs(player['position'][1] - y) < .001, player

    def setup():
        command('tick unfreeze')
        command('gamemode creative')
        command(f'tp @s {x + 2.5} {y} {z + 2.5}')
        ctl('wait-ready', 120)
        wait_loaded(ctl, [(px, y, pz) for px in [x - 3, x + 5] for pz in [z - 3, z + 8]])
        command(f'fill {x - 3} {y - 3} {z - 3} {x + 5} {y + 5} {z + 8} minecraft:air')
        command(f'fill {x - 3} {y - 1} {z - 3} {x + 5} {y - 1} {z + 8} minecraft:smooth_stone')
        command('kill @e[type=minecraft:item]')
        command('clear @s')
        for pos, block in [((x - 1, y, z), 'create:creative_motor[facing=east]'),
                           ((x, y, z), 'create:shaft[axis=x]'),
                           ((x, y, z + 5), 'create:shaft[axis=x]'),
                           ((x, y, z + 6), 'create:depot'),
                           ((x + 1, y - 1, z + 6), 'minecraft:chest'),
                           ((x, y - 1, z + 6), 'minecraft:hopper[facing=east]'),
                           ((x - 1, y + 2, z + 2), 'create:creative_motor[facing=east]'),
                           ((x, y + 2, z + 2), 'create:mechanical_press[facing=east]')]:
            command('setblock ' + ' '.join(map(str, pos)) + ' ' + block)
        command('give @s create:belt_connector 1')
        ctl('wait', 5)
        ctl('select', 'create:belt_connector')
        for offset in [0, 5]:
            stand(offset)
            ctl('look-at', 'block', x, y, z + offset, 'east')
            ctl('wait', 2)
            ctl('interact', x, y, z + offset, 'east')
            ctl('wait', 8)
        for offset in range(6):
            assert ctl('block', x, y, z + offset)['block'] == 'create:belt'
        stand(3)
        power(belt=0, press=128)
        assert re.search(r'\bSpeed:\s*128(?:\.0)?f', data((x, y + 2, z + 2)))

    def feed(item, count, marker=71):
        command(f'summon minecraft:item {x + .5} {y + 1.05} {z + .5} '
                + '{PickupDelay:32767,Item:{id:"' + item + '",count:' + str(count)
                + ',components:{"minecraft:custom_data":{press_belt_marker:' + str(marker) + '}}}}')
        ctl('wait', 12)
        saved = inventory()
        assert item in saved and f'press_belt_marker: {marker}' in saved, saved
        return saved

    def until_output(item, amount, limit=600):
        for _ in range(limit // 5):
            current = counts()
            if current[item] == amount:
                return current
            assert current[item] < amount, current
            ctl('wait', 5)
        raise AssertionError(('Output timed out', item, amount, counts(), inventory(), data((x, y + 2, z + 2))))

    def passed(text):
        report['checks'].append(text)
        save()

    save()
    setup()
    held = feed('minecraft:copper_ingot', 8)
    ctl('wait', 30)
    assert inventory() == held, (held, inventory())
    assert counts()['create:copper_sheet'] == 0
    passed('Stopped belt retains the full component-bearing stack without starting the press')
    power(belt=32)
    for _ in range(100):
        current = inventory()
        if 'create:copper_sheet' in current and 'minecraft:copper_ingot' in current:
            report['first_conversion'] = current
            assert 'press_belt_marker: 71' in current, current
            break
        ctl('wait', 2)
    else:
        raise AssertionError(('No nonbulk split observed', inventory(), counts(), data((x, y + 2, z + 2))))
    until_output('create:copper_sheet', 8)
    assert 'minecraft:copper_ingot' not in inventory() and 'create:copper_sheet' not in inventory(), inventory()
    assert 'press_belt_marker' not in data((x + 1, y - 1, z + 6)), 'Recipe results must not inherit arbitrary input components'
    passed('Eight ingots process one at a time into eight sheets; held leftovers retain components and recipe results do not copy them')
    if graphics:
        stand(5)
        ctl('look-at', x + .5, y + 1.2, z + 2.5)
        image = scratch / 'belt-press-native.png'
        ctl('key', 'f1', 'tap')
        try:
            ctl('wait', 3)
            ctl('screenshot', image)
        finally:
            ctl('key', 'f1', 'tap')
        report['images'].append(str(image))

    setup()
    power(press=0)
    feed('minecraft:copper_ingot', 3, 72)
    power(belt=32)
    until_output('minecraft:copper_ingot', 3)
    assert counts()['create:copper_sheet'] == 0
    passed('Unpowered press passes all input unchanged to the output depot')

    setup()
    feed('minecraft:diamond', 3, 73)
    power(belt=32)
    until_output('minecraft:diamond', 3)
    assert counts()['create:copper_sheet'] == 0
    passed('Unsupported input passes a powered press without consumption or replacement')

    setup()
    feed('minecraft:copper_ingot', 3, 74)
    power(belt=32)
    for _ in range(60):
        text = data((x, y + 2, z + 2))
        if re.search(r'\bRunning:\s*1b', text) and re.search(r'\bTicks:\s*(?:[1-9]|[1-9]\d)', text):
            break
        ctl('wait', 1)
    else:
        raise AssertionError(('Press did not start', text, inventory()))
    # Independent power loss releases the held item through the source callback;
    # processing must not fabricate a result after the press becomes unpowered.
    power(press=0)
    until_output('minecraft:copper_ingot', 3)
    assert counts()['create:copper_sheet'] == 0
    passed('Removing press power during its early cycle releases the original stack without an output')
    if check_freeze:
        setup()
        feed('minecraft:copper_ingot', 3, 76)
        power(belt=32)
        for _ in range(100):
            text = data((x, y + 2, z + 2))
            ticks = re.search(r'\bTicks:\s*(\d+)', text)
            if re.search(r'\bRunning:\s*1b', text) and ticks and int(ticks[1]) < 90:
                break
            ctl('wait', 1)
        else:
            raise AssertionError(('Frozen fixture did not enter an early cycle', text))
        command('tick freeze')

        def game_time():
            reply = command('time query gametime')
            values = re.findall(r'\b\d+\b', ' '.join(reply['chat']))
            assert len(values) == 1, reply
            return int(values[0])

        def frozen_state():
            text = data((x, y + 2, z + 2))
            fields = {key: int(re.search(r'\b' + key + r':\s*(-?\d+)', text)[1])
                      for key in ['Running', 'Ticks', 'Mode', 'Finished']}
            return {'inventory': inventory(), 'press': fields,
                    'press_speed': data((x, y + 2, z + 2), 'Speed'),
                    'belt_speed': data((x, y, z), 'Speed')}

        before_time = game_time()
        before = frozen_state()
        assert before['press']['Running'] == 1 and before['press']['Ticks'] < 120, before
        command('tick step 20')
        for _ in range(100):
            now = game_time()
            if now >= before_time + 20:
                break
            ctl('wait', 1)
        else:
            raise AssertionError(('Frozen clock did not step', before_time, now))
        assert now == before_time + 20, (before_time, now)
        after = frozen_state()
        assert after == before, (before, after)
        command('tick unfreeze')
        until_output('create:copper_sheet', 3)
        assert counts()['minecraft:copper_ingot'] == 0
        report['frozen_clock'] = {'before_time': before_time, 'after_time': now,
                                  'before': before, 'after': after}
        passed('Twenty frozen step ticks retain the exact belt inventory and running press fields at stored128/32RPM; normal ticking resumes into exactly three sheets')
    if prepare_restart:
        setup()
        power(press=16)
        feed('minecraft:copper_ingot', 3, 75)
        power(belt=32)
        for _ in range(100):
            text = data((x, y + 2, z + 2))
            running = re.search(r'\bRunning:\s*1b', text)
            ticks = re.search(r'\bTicks:\s*(\d+)', text)
            if running and ticks and 0 < int(ticks[1]) < 60:
                break
            ctl('wait', 1)
        else:
            raise AssertionError(('Restart fixture did not enter an early cycle', text, inventory()))
        power(belt=0, press=0)
        saved = inventory()
        assert 'press_belt_marker: 75' in saved and 'create:copper_sheet' not in saved, saved
        text = data((x, y + 2, z + 2))
        fields = {key: int(re.search(r'\b' + key + r':\s*(-?\d+)', text)[1])
                  for key in ['Running', 'Ticks', 'Mode', 'Finished']}
        assert fields['Running'] == 1 and fields['Ticks'] < 120, fields
        report['restart_fixture'] = {'controller': [x, y, z], 'press': [x, y + 2, z + 2],
                                     'inventory': saved, 'press_fields': fields}
        report['restart_pending'] = True
    report['passed'] = True
    save()
    return report


def run_reload(call, scratch):
    """Verify the prepared mid-cycle fixture after a genuine process restart."""
    scratch = Path(scratch).resolve()
    scratch.relative_to((ROOT / '.local').resolve())
    path = scratch / 'belt-press-result.json'
    report = json.loads(path.read_text())
    assert report['passed'] and report['restart_pending']
    fixture = report['restart_fixture']
    x, y, z = fixture['controller']

    def command(line):
        return call('command', line)

    def data(pos, key=''):
        return ' '.join(command('data get block ' + ' '.join(map(str, pos)) + (' ' + key if key else ''))['chat'])

    command(f'tp @s {x + 2.5} {y} {z + 2.5}')
    call('wait-ready', 120)
    wait_loaded(call, [(px, y, pz) for px in [x - 3, x + 5] for pz in [z - 3, z + 8]])
    saved = data((x, y, z), 'Inventory')
    assert saved == fixture['inventory'], (fixture['inventory'], saved)
    text = data(fixture['press'])
    fields = {key: int(re.search(r'\b' + key + r':\s*(-?\d+)', text)[1])
              for key in fixture['press_fields']}
    assert fields == fixture['press_fields'], (fixture['press_fields'], fields)
    replace_motor(call, (x - 1, y + 2, z + 2), 16, 'east')
    replace_motor(call, (x - 1, y, z), 32, 'east')
    for _ in range(160):
        slots = call('container', x + 1, y - 1, z + 6)['slots']
        amount = sum(item['count'] for item in slots if item and item['item'] == 'create:copper_sheet')
        assert amount <= 3, slots
        if amount == 3:
            break
        call('wait', 5)
    else:
        raise AssertionError(('Restarted press did not finish', slots, data(fixture['press']), data((x, y, z))))
    assert 'minecraft:copper_ingot' not in data((x, y, z), 'Inventory')
    report['checks'].append('Real process restart preserves the stopped mid-cycle press and exact component-bearing belt record; resuming yields exactly three sheets')
    report['restart_pending'] = False
    report['reload_passed'] = True
    path.write_text(json.dumps(report, indent=2) + '\n')
    return report
