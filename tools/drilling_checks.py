"""Stationary mechanical drill scenarios driven through a disposable real game."""
import re
import engineering_checks
from native_motors import replace_motor

X = 156
DIRECTIONS = [('east', (1, 0, 0)), ('west', (-1, 0, 0)), ('up', (0, 1, 0)),
              ('down', (0, -1, 0)), ('south', (0, 0, 1)), ('north', (0, 0, -1))]


def run(call, graphics, log, scratch):
    def setblock(x, y, z, name):
        return call('setblock', X + x, y, z, name)

    def block(x=1, y=67, z=0):
        return call('block', X + x, y, z)['block']

    def text():
        return ' '.join(call('command', f'data get block {X} 67 0')['chat'])

    def number(key):
        value = text()
        match = re.search(r'\b' + key + r':\s*(-?[\d.]+)', value)
        assert match, value
        return float(match[1])

    def loose():
        counts = {}
        for entity in call('entities', 24, 'minecraft:item')['entities']:
            stack = entity.get('item', {})
            item = stack.get('item', stack.get('id'))
            if item:
                counts[item] = counts.get(item, 0) + stack['count']
        return counts

    def reset():
        call('command', f'tp @s {X + 3.5} 67 4.5')
        call('wait-ready', 120)
        call('fill', X - 5, 64, -3, X + 6, 72, 5, 'minecraft:air')
        call('fill', X - 5, 63, -3, X + 6, 63, 5, 'minecraft:smooth_stone')
        call('command', 'clear @s')
        call('command', 'kill @e[type=minecraft:item]')
        call('wait', 3)

    def gated(rpm):
        replace_motor(call, (X - 3, 67, 0), rpm, 'east')
        setblock(-2, 67, 0, 'create:clutch[axis=x]')
        setblock(-1, 67, 0, 'create:shaft[axis=x]')
        setblock(0, 67, 0, 'create:mechanical_drill[facing=east]')

    def power(on):
        setblock(-2, 67, 1, 'minecraft:air' if on else 'minecraft:redstone_block')
        call('wait', 8)

    # All facings receive rotation solely through the rear and drop ordinary
    # block loot even while the acting player is creative and empty-handed.
    call('command', 'gamemode creative')
    for facing, delta in DIRECTIONS:
        reset()
        x, y, z = delta
        replace_motor(call, (X - x, 67 - y, -z), 64, facing)
        setblock(0, 67, 0, f'create:mechanical_drill[facing={facing}]')
        setblock(x, 67 + y, z, 'minecraft:stone')
        call('wait', 100)
        assert block(x, 67 + y, z) == 'minecraft:air', (facing, text())
        assert loose().get('minecraft:cobblestone') == 1, (facing, loose())
        assert abs(number('Speed')) == 64 and number('Stress') == 256, text()
        assert 'id: "create:drill"' in text(), text()
        if graphics:
            call('look-at', X + .5, 67.5, .5)
            call('wait', 20)
            poses = [p for p in engineering_checks.poses(log, [X, 67, 0]) if p['model'].endswith('mechanical_drill/head')]
            axis = next(i for i, v in enumerate(delta) if v)
            # Earlier facings share this position; only use the latest poses.
            offset=22.5 if sum(v for i,v in enumerate([X,67,0]) if i!=axis)%2==0 else 0
            engineering_checks.source_rotation(poses,axis,delta[axis]*64,offset)
    print('Drill: all six facings, rear shaft, source 4 SU/RPM and ordinary stone loot in creative mode', flush=True)

    reset()
    gated(256)
    setblock(1, 67, 0, 'minecraft:bedrock')
    call('wait', 80)
    assert block() == 'minecraft:bedrock' and number('Progress') == 0, text()
    assert loose() == {}, loose()
    # No player tool/correct-tool gate participates in automated loot.
    setblock(1, 67, 0, 'minecraft:diamond_ore')
    call('wait', 100)
    assert block() == 'minecraft:air' and loose().get('minecraft:diamond') == 1, loose()
    print('Drill: unbreakable blocks remain intact; diamond-ore loot uses the normal empty-tool block table', flush=True)

    reset()
    gated(256)
    call('command', 'gamerule minecraft:block_drops false')
    try:
        setblock(1, 67, 0, 'minecraft:stone')
        call('wait', 80)
        assert block() == 'minecraft:air' and loose() == {}, loose()
    finally:
        call('command', 'gamerule minecraft:block_drops true')
    print('Drill: block_drops gamerule suppresses drops while retaining destruction', flush=True)

    reset()
    gated(16)
    setblock(1, 67, 0, 'minecraft:stone')
    call('wait', 12)
    power(False)
    progress, delay = number('Progress'), number('NextTick')
    assert progress > 0 and block() == 'minecraft:stone', text()
    call('wait', 35)
    assert number('Progress') == progress and number('NextTick') == delay, text()
    power(True)
    call('wait', 160)
    assert block() == 'minecraft:air' and loose().get('minecraft:cobblestone') == 1
    print('Drill: clutch interruption preserves partial progress/delay and resumes exactly one block break', flush=True)

    # Check crack reset against a newly unbreakable target. Source keeps
    # accumulated progress across replacement by another breakable target.
    reset()
    gated(16)
    setblock(1, 67, 0, 'minecraft:stone')
    call('wait', 12)
    assert number('Progress') > 0, text()
    setblock(1, 67, 0, 'minecraft:bedrock')
    call('wait', 8)
    assert number('Progress') == 0 and block() == 'minecraft:bedrock', text()
    print('Drill: replacing an active target with an unbreakable block clears partial progress', flush=True)

    # Leave a stopped, partially drilled hard block for real save/reload.
    reset()
    gated(256)
    setblock(1, 67, 0, 'minecraft:obsidian')
    call('wait', 8)
    power(False)
    fixture = {'pos': [X, 67, 0], 'progress': number('Progress'), 'next_tick': number('NextTick')}
    assert fixture['progress'] > 0 and block() == 'minecraft:obsidian', (fixture, text())
    assert 'Breaking: [I;' in text(), text()
    if graphics:
        call('look-at', X + .5, 67.5, .5)
        call('screenshot', scratch / 'drill.png')
    return fixture


def reloaded(call, fixture):
    call('command', f'tp @s {X + 3.5} 67 4.5')
    call('wait-ready', 120)
    text = ' '.join(call('command', 'data get block ' + ' '.join(map(str, fixture['pos'])))['chat'])
    for key, field in [('Progress', 'progress'), ('NextTick', 'next_tick')]:
        match = re.search(r'\b' + key + r':\s*(-?\d+)', text)
        assert match and int(match[1]) == fixture[field], (fixture, text)
    call('setblock', X - 2, 67, 1, 'minecraft:air')
    call('wait', 250)
    assert call('block', X + 1, 67, 0)['block'] == 'minecraft:air'
    drops = call('entities', 24, 'minecraft:item')['entities']
    assert sum(e.get('item', {}).get('count', 0) for e in drops if e.get('item', {}).get('item') == 'minecraft:obsidian') == 1, drops
    print('Drill: canonical Progress/NextTick/Breaking survive a real restart and finish into one obsidian drop', flush=True)
