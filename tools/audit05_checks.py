"""Independent adversarial 0.5 checks for a disposable real-game smoke world.

The driver supplies a horizon-ctl call function. These check actual graph edges,
opposite processing-media traversal, collision blocking and fresh depot inputs.
They do not derive expected outputs from the implementation under test.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess

from common import ROOT
from native_motors import replace_motor


X = 108
DIRECTIONS = [
    ('down', (0, -1, 0), 'up', 'y', -1),
    ('up', (0, 1, 0), 'down', 'y', 1),
    ('north', (0, 0, -1), 'south', 'z', -1),
    ('south', (0, 0, 1), 'north', 'z', 1),
    ('west', (-1, 0, 0), 'east', 'x', -1),
    ('east', (1, 0, 0), 'west', 'x', 1),
]


def sprint_ticks(call, ticks):
    """Run an exact unfrozen interval, then return to the frozen fixture."""
    def game_time():
        chat = call('command', 'time query gametime')['chat']
        match = re.search(r'\b(\d+) tick', ' '.join(chat))
        assert match, chat
        return int(match[1])

    before = game_time()
    # Create exposes zero RPM during vanilla /tick step. A sprint runs the
    # requested ticks unfrozen and restores the earlier frozen state.
    call('command', f'tick sprint {ticks}t')
    call('wait', ticks + 4)
    after = game_time()
    assert after - before == ticks, (before, after, ticks)


def run(call, graphics=False, log=None, scratch=None):
    def setblock(x, y, z, block):
        return call('setblock', X + x, y, z, block)

    def slots(x, y=68, z=0):
        return call('container', X + x, y, z)['slots']

    def counts(items):
        result = {}
        for item in items:
            if item:
                result[item['item']] = result.get(item['item'], 0) + item['count']
        return result

    def text(x, y=69, z=0):
        return ' '.join(call('command', f'data get block {X + x} {y} {z}')['chat'])

    def number(x, key, y=69, z=0):
        value = text(x, y, z)
        match = re.search(r'\b' + key + r':\s*(-?[\d.]+(?:[eE][+-]?\d+)?)', value)
        assert match, value
        return float(match[1])

    def reset():
        call('fill', X - 4, 64, -4, X + 10, 76, 5, 'minecraft:air')
        call('command', 'kill @e[type=minecraft:item]')
        call('command', 'clear @s')
        call('command', 'gamemode creative')
        call('command', f'tp @s {X + 5.5} 69 3.5')
        call('wait', 4)

    def drive(rpm):
        replace_motor(call, (X - 1, 69, 0), rpm, 'east')

    def fan_line(rpm=256, catalyst='minecraft:soul_campfire[lit=true]'):
        setblock(0, 69, 0, 'create:encased_fan[facing=east]')
        setblock(1, 68, 0, 'minecraft:stone')
        setblock(1, 69, 0, catalyst)
        drive(rpm)

    call('command', f'tp @s {X + 5.5} 70 3.5')
    call('wait-ready', 120)
    call('fill', X - 5, 63, -5, X + 11, 63, 6, 'minecraft:smooth_stone')

    # EncasedFanBlock.hasShaftTowards exposes only the back face. The motor's
    # positive setting produces canonical +/-16 according to world axis sign.
    for facing, delta, opposite, axis, sign in DIRECTIONS:
        reset()
        setblock(0, 69, 0, f'create:encased_fan[facing={facing}]')
        setblock(-delta[0], 69 - delta[1], -delta[2], f'create:creative_motor[facing={facing}]')
        setblock(delta[0], 69 + delta[1], delta[2], f'create:shaft[axis={axis}]')
        call('wait', 12)
        assert number(0, 'Speed') == sign * 16, (facing, text(0))
        assert number(0, 'Stress') == 32, (facing, text(0))
        assert number(delta[0], 'Speed', 69 + delta[1], delta[2]) == 0
        setblock(-delta[0], 69 - delta[1], -delta[2], 'minecraft:air')
        setblock(delta[0], 69 + delta[1], delta[2], f'create:creative_motor[facing={opposite}]')
        call('wait', 12)
        assert number(0, 'Speed') == 0, (facing, text(0))
    print('Audit 0.5: all six fan back-only shaft edges, canonical RPM and 2 SU/RPM passed', flush=True)

    # Stable catalysts avoid a changing water fixture: smoke at cell1 and
    # haunting at cell3. Cobblestone can only haunt into blackstone. Reversing
    # flow reverses which of the two depots receives haunting air.
    for rpm, expected in [
        (256, [{'minecraft:cobblestone': 1}, {'minecraft:blackstone': 1}]),
        (-256, [{'minecraft:blackstone': 1}, {'minecraft:cobblestone': 1}]),
    ]:
        reset()
        fan_line(rpm, 'minecraft:campfire[lit=true]')
        setblock(3, 68, 0, 'minecraft:stone')
        setblock(3, 69, 0, 'minecraft:soul_campfire[lit=true]')
        for x in (2, 4):
            setblock(x, 68, 0, 'create:depot')
        call('wait', 40)
        for x in (2, 4):
            call('container', X + x, 68, 0, 'minecraft:cobblestone', 1)
        call('wait', 200)
        actual = [counts(slots(x)) for x in (2, 4)]
        assert actual == expected, (rpm, expected, actual)
    print('Audit 0.5: pushing/pulling reverse catalyst traversal and process depots one block below air', flush=True)

    # A full cube blocks all five source depth rays; a bottom slab has clear
    # upper rays and must pass the entire current. Unlit soul campfires are
    # excluded as catalysts.
    for obstruction, catalyst, expected in [
        ('minecraft:stone', 'minecraft:soul_campfire[lit=true]', 'minecraft:cobblestone'),
        ('minecraft:stone_slab[type=bottom]', 'minecraft:soul_campfire[lit=true]', 'minecraft:blackstone'),
        ('minecraft:air', 'minecraft:soul_campfire[lit=false]', 'minecraft:cobblestone'),
    ]:
        reset()
        fan_line(catalyst=catalyst)
        setblock(3, 69, 0, obstruction)
        setblock(4, 68, 0, 'create:depot')
        call('wait', 40)
        call('container', X + 4, 68, 0, 'minecraft:cobblestone', 1)
        call('wait', 200)
        assert counts(slots(4)) == {expected: 1}, (obstruction, catalyst, slots(4))
    print('Audit 0.5: full collision blocks air, partial clear ray passes, unlit catalyst has no processing', flush=True)

    # A newly inserted transported stack has a fresh timer even if the depot
    # previously held an identical almost-processed item. Taking the old input
    # must also preserve exactly one item in the player's inventory.
    reset()
    fan_line()
    setblock(2, 68, 0, 'create:depot')
    call('wait', 40)
    call('container', X + 2, 68, 0, 'minecraft:cobblestone', 1)
    call('wait', 115)
    setblock(-1, 69, 0, 'minecraft:air')
    call('wait', 5)
    before = number(2, 'FanProcessingTime', 68)
    assert 0 < before < 70, text(2, 68)
    setblock(2, 68, 2, 'minecraft:smooth_stone')
    call('command', f'tp @s {X + 2.5} 69 2.5')
    call('look-at', 'block', X + 2, 68, 0, 'up')
    call('interact', X + 2, 68, 0, 'up')
    call('wait', 5)
    assert call('inventory')['counts'] == {'minecraft:cobblestone': 1}
    assert counts(slots(2)) == {}
    call('command', 'clear @s')
    call('container', X + 2, 68, 0, 'minecraft:cobblestone', 1)
    drive(256)
    call('wait', 80)
    assert counts(slots(2)) == {'minecraft:cobblestone': 1}, slots(2)
    call('wait', 100)
    assert counts(slots(2)) == {'minecraft:blackstone': 1}, slots(2)
    print('Audit 0.5: taking/reinserting identical depot input resets progress and converts exactly once', flush=True)

    # Exact simulation steps remove wall-clock/control-command races. A source
    # transported stack converts on call 153 for <=16 items, 303 for 17 items.
    # The fixture supplies HeldItem directly, so container bookkeeping order is
    # not mistaken for an additional processing tick.
    for count, ticks in [(16, 153), (17, 303)]:
        reset()
        call('command', 'tick freeze')
        try:
            fan_line()
            setblock(2, 68, 0, 'create:depot')
            sprint_ticks(call, 1)
            call('container', X + 2, 68, 0, 'minecraft:cobblestone', count)
            call('command', f'data merge block {X + 2} 68 0 '
                 f'{{HeldItem:{{Item:{{id:"minecraft:cobblestone",count:{count}}}}}}}')
            sprint_ticks(call, ticks - 1)
            assert counts(slots(2)) == {'minecraft:cobblestone': count}, (count, slots(2))
            sprint_ticks(call, 1)
            assert counts(slots(2)) == {'minecraft:blackstone': count}, (count, slots(2))
        finally:
            call('command', 'tick unfreeze')
    print('Audit 0.5: exact native 16/17 stack boundary converts on source calls 153/303', flush=True)

    # The lower hopper empties the previous transported item and the side
    # hopper replaces it in the SAME simulation tick. A finished -1 sentinel
    # belongs to the old item; it must not disable the new input.
    reset()
    call('command', 'tick freeze')
    try:
        fan_line()
        setblock(2, 68, 0, 'create:depot')
        sprint_ticks(call, 1)
        call('container', X + 2, 68, 0, 'minecraft:blackstone', 1)
        call('command', f'data merge block {X + 2} 68 0 '
             '{HeldItem:{Item:{id:"minecraft:blackstone",count:1},'
             'FanProcessingType:"create:haunting",FanProcessingTime:-1}}')
        setblock(2, 66, 0, 'minecraft:redstone_block')
        setblock(2, 67, 0, 'minecraft:hopper[facing=east]')
        setblock(3, 68, 0, 'minecraft:hopper[facing=west]')
        call('container', X + 3, 68, 0, 'minecraft:cobblestone', 1)
        # Let the side hopper's insertion cooldown expire while the occupied
        # depot refuses its input and the lower hopper remains powered.
        sprint_ticks(call, 8)
        assert counts(slots(2)) == {'minecraft:blackstone': 1}, slots(2)
        setblock(2, 66, 0, 'minecraft:air')
        sprint_ticks(call, 1)
        assert counts(slots(2)) == {'minecraft:cobblestone': 1}, slots(2)
        assert counts(slots(2, 67)) == {'minecraft:blackstone': 1}, slots(2, 67)
        assert counts(slots(3)) == {}, slots(3)
        setblock(2, 66, 0, 'minecraft:redstone_block')
        sprint_ticks(call, 3)
        timer = number(2, 'FanProcessingTime', 68)
        assert 0 < timer <= 151, text(2, 68)
        sprint_ticks(call, 160)
        assert counts(slots(2)) == {'minecraft:blackstone': 1}, slots(2)
        assert counts(slots(2, 67)) == {'minecraft:blackstone': 1}, slots(2, 67)
    finally:
        call('command', 'tick unfreeze')
    print('Audit 0.5: same-tick hopper drain/refill creates fresh processing identity and conserves both items', flush=True)
    return {'passed': True, 'scope': 'fan shaft topology, media direction, collision permeability, exact stack timing and fresh depot identity after hand/hopper transfers'}


DROP_X = X + 24
DROP_SELECTOR = '@e[type=minecraft:item,tag=audit05_dropped_progress,limit=1]'


def dropped_text(call, path=None):
    suffix = '' if path is None else ' ' + path
    return ' '.join(call('command', 'data get entity ' + DROP_SELECTOR + suffix)['chat'])


def dropped_timer(call):
    value = dropped_text(call, 'NeoForgeData.CreateData.Processing')
    match = re.search(r'\bTime:\s*(-?\d+)', value)
    assert match and 'create:haunting' in value, value
    return int(match[1])


def check_dropped_siblings(call):
    value = dropped_text(call, 'NeoForgeData')
    for marker in ['audit05_neoforge_sibling: 501', 'audit05_create_sibling: 502']:
        assert marker in value, value
    stack = dropped_text(call, 'Item')
    assert 'NeoForgeData' not in stack and 'Processing' not in stack, stack


def prepare_dropped_reload(call):
    """Leave a stopped dropped stack for the caller to save and reopen."""
    call('command', f'tp @s {DROP_X + 3.5} 70 3.5')
    call('wait-ready', 120)
    call('fill', DROP_X - 3, 66, -2, DROP_X + 6, 72, 2, 'minecraft:air')
    call('command', 'kill @e[tag=audit05_dropped_progress]')
    call('command', 'tick freeze')
    try:
        for x, y, name in [
            (0, 69, 'create:encased_fan[facing=east]'),
            (1, 68, 'minecraft:stone'),
            (1, 69, 'minecraft:soul_campfire[lit=true]'),
            (4, 69, 'minecraft:stone'),
        ]:
            call('setblock', DROP_X + x, y, 0, name)
        replace_motor(call, (DROP_X - 1, 69, 0), 256, 'east')
        sprint_ticks(call, 1)
        # The barrier keeps the item inside airflow; no gravity/pickup or depot
        # may move the stack out before processing. Unknown neighboring keys
        # must survive each timer update in the raw entity compound.
        call('command', f'summon minecraft:item {DROP_X + 3.5} 69.25 .5 '
             '{Tags:["audit05_dropped_progress"],NoGravity:1b,PickupDelay:32767,'
             'Item:{id:"minecraft:cobblestone",count:17},NeoForgeData:{'
             'audit05_neoforge_sibling:501,CreateData:{audit05_create_sibling:502}}}')
        sprint_ticks(call, 20)
        timer = dropped_timer(call)
        assert 0 < timer < 301, (timer, dropped_text(call))
        check_dropped_siblings(call)
        call('setblock', DROP_X - 1, 69, 0, 'minecraft:air')
        sprint_ticks(call, 1)
        assert dropped_timer(call) == timer, dropped_text(call)
        call('command', 'data merge entity ' + DROP_SELECTOR +
             ' {Motion:[0d,0d,0d],NeoForgeData:{CreateData:{Processing:{audit05_processing_sibling:503}}}}')
        check_dropped_siblings(call)
        assert dropped_timer(call) == timer
        return {'timer': timer, 'count': 17, 'selector': DROP_SELECTOR, 'fan': [DROP_X, 69, 0]}
    finally:
        call('command', 'tick unfreeze')


def reloaded_dropped(call, fixture):
    """Verify saved state and exact continuation after reopening the world."""
    call('command', f'tp @s {DROP_X + 3.5} 70 3.5')
    call('wait-ready', 120)
    assert dropped_timer(call) == fixture['timer'], (fixture, dropped_text(call))
    check_dropped_siblings(call)
    assert 'audit05_processing_sibling: 503' in dropped_text(call, 'NeoForgeData.CreateData.Processing')
    call('command', 'tick freeze')
    try:
        replace_motor(call, (DROP_X - 1, 69, 0), 256, 'east')
        # Source initialization may precede the fan's first powered turn.
        for _ in range(5):
            sprint_ticks(call, 1)
            timer = dropped_timer(call)
            if timer != fixture['timer']:
                break
        assert timer == fixture['timer'] - 1, dropped_text(call)
        sprint_ticks(call, timer - 1)
        stack = dropped_text(call, 'Item')
        assert 'minecraft:cobblestone' in stack and re.search(r'\bcount:\s*17\b', stack), stack
        assert dropped_timer(call) == 1, dropped_text(call)
        sprint_ticks(call, 1)
        stack = dropped_text(call, 'Item')
        assert 'minecraft:blackstone' in stack and re.search(r'\bcount:\s*17\b', stack), stack
        assert dropped_timer(call) == 0, dropped_text(call)
        check_dropped_siblings(call)
        assert 'audit05_processing_sibling: 503' in dropped_text(call, 'NeoForgeData.CreateData.Processing')
        sprint_ticks(call, 3)
        assert dropped_timer(call) == -1, dropped_text(call)
        assert 'minecraft:blackstone' in dropped_text(call, 'Item')
        call('setblock', DROP_X - 1, 69, 0, 'minecraft:air')
    finally:
        call('command', 'tick unfreeze')
    print('Audit 0.5: canonical dropped progress and neighboring NBT survive reload; exact remaining time converts once without item components', flush=True)
    return {'passed': True, 'scope': 'dropped canonical NeoForgeData persistence, exact remaining time and neighboring raw NBT preservation'}


def press_resets_fan_progress(call):
    """BeltPressingCallbacks clears prior fan state for output AND remainder.

    The source does this before transported.copy() in both bulk/count-one and
    non-bulk branches. A nearly completed blasting timer must therefore restart
    after a stroke, rather than burning a fresh sheet or remaining ingot early.
    The normal press starts and locks the transported stack. Original NBT then
    seeds its prior fan progress before the real stroke and subsequent airflow.
    """
    origin = 180

    def block(x, y, z, name):
        return call('setblock', origin + x, y, z, name)

    def data(x, y, path=''):
        return ' '.join(call('command', f'data get block {origin + x} {y} 0' + (' ' + path if path else ''))['chat'])

    def counts():
        result = {}
        for stack in call('container', origin + 3, 68, 0)['slots']:
            if stack:
                result[stack['item']] = result.get(stack['item'], 0) + stack['count']
        return result

    for count, expected in [
        (1, {'create:iron_sheet': 1}),
        (2, {'minecraft:iron_ingot': 1, 'create:iron_sheet': 1}),
    ]:
        call('command', f'tp @s {origin + 5.5} 70 3.5')
        call('wait-ready', 120)
        call('fill', origin - 3, 66, -3, origin + 7, 73, 4, 'minecraft:air')
        call('command', 'clear @s')
        call('command', 'kill @e[type=minecraft:item]')
        call('command', 'tick freeze')
        try:
            replace_motor(call, (origin - 1, 69, 0), 0, 'east')
            block(0, 69, 0, 'create:encased_fan[facing=east]')
            # Iron bars pass source fan air but keep the lava catalyst in its
            # glass cell. This fixture cannot flood the depot or press.
            for x, y, z in [(1, 68, 0), (1, 70, 0), (1, 69, -1), (1, 69, 1)]:
                block(x, y, z, 'minecraft:glass')
            block(2, 69, 0, 'minecraft:iron_bars')
            block(1, 69, 0, 'minecraft:lava')
            block(3, 68, 0, 'create:depot')
            replace_motor(call, (origin + 2, 70, 0), 256, 'east')
            block(3, 70, 0, 'create:mechanical_press[facing=east]')
            # Newly placed depots allocate their item slot on the first tick.
            sprint_ticks(call, 1)
            call('container', origin + 3, 68, 0, 'minecraft:iron_ingot', count)
            for _ in range(35):
                sprint_ticks(call, 1)
                held = data(3, 68, 'HeldItem')
                if 'Locked: 1b' in held:
                    break
            else:
                raise AssertionError(('Press did not lock the item', held, data(3, 70)))
            call('command', f'data merge block {origin + 3} 68 0 '
                 '{HeldItem:{FanProcessingType:"create:blasting",'
                 'FanProcessingTime:5,audit05_transport_marker:504}}')
            assert 'audit05_transport_marker: 504' in data(3, 68, 'HeldItem')
            for _ in range(35):
                sprint_ticks(call, 1)
                if counts() == expected:
                    break
            else:
                raise AssertionError(('Press did not process the item', count, counts(), data(3, 70)))
            held = data(3, 68, 'HeldItem')
            assert 'FanProcessingType' not in held and 'FanProcessingTime' not in held, held
            # TransportedItemStack.read/copy/serializeNBT keep canonical fields.
            assert 'audit05_transport_marker' not in held, held
            # Stop further strokes; the real fan now receives power and must
            # initialize a fresh 151 timer for the new held transported stack.
            replace_motor(call, (origin + 2, 70, 0), 0, 'east')
            replace_motor(call, (origin - 1, 69, 0), 256, 'east')
            for _ in range(5):
                sprint_ticks(call, 1)
                held = data(3, 68, 'HeldItem')
                if 'FanProcessingTime' in held:
                    break
            assert 'create:blasting' in held and re.search(r'\bFanProcessingTime:\s*151\b', held), held
            sprint_ticks(call, 10)
            assert counts() == expected, (count, counts())
            held = data(3, 68, 'HeldItem')
            assert re.search(r'\bFanProcessingTime:\s*141\b', held), held
        finally:
            call('command', 'tick unfreeze')
    print('Audit 0.5: pressing clears stale fan state for held output/residual input; real blasting restarts its timer and preserves both cases', flush=True)
    return {'passed': True, 'scope': 'press/fan reset for count-one output and non-bulk residual input with canonical transported NBT'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ctl', type=Path, required=True)
    parser.add_argument('--socket', type=Path, required=True)
    parser.add_argument('--scratch', type=Path, required=True)
    args = parser.parse_args()
    scratch = args.scratch.resolve()
    socket = args.socket.resolve()
    # Deliberately require the standard disposable smoke folder; this tool
    # must never attach to a user's normal review/play instance.
    if scratch.parent != (ROOT / '.local').resolve() or not scratch.name.startswith('smoke-'):
        raise SystemExit('--scratch must identify a disposable .local/smoke-* world')
    if socket.parent != scratch:
        raise SystemExit('The control socket must belong to that scratch folder')
    output = scratch / 'audit05'
    output.mkdir(exist_ok=True)
    transcript = []

    def call(*words, timeout=120):
        reply = subprocess.run([str(args.ctl), '--socket', str(socket), *map(str, words)],
                               text=True, capture_output=True, timeout=timeout)
        if reply.returncode:
            raise RuntimeError(str(words) + ': ' + reply.stdout + reply.stderr)
        data = json.loads(reply.stdout)
        transcript.append({'command': list(map(str, words)), 'reply': data})
        return data

    try:
        result = run(call, scratch=scratch)
        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result))
    finally:
        (output / 'transcript.json').write_text(json.dumps(transcript, indent=2) + '\n')


if __name__ == '__main__':
    main()
