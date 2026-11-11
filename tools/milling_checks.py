"""Real-game millstone checks; run/reloaded share the disposable smoke driver.

The container control command supplies fixtures, while falling items, hopper IO,
player retrieval, kinetic stress and renderer poses run through actual game code.
"""
import json
import re
import engineering_checks
from native_motors import replace_motor

X = 72


def run(call, graphics, log, scratch):
    def setblock(x, y, z, name):
        return call('setblock', X + x, y, z, name)

    def slots(x=0, y=65, z=0):
        return call('container', X + x, y, z)['slots']

    def counts(stacks):
        result = {}
        for stack in stacks:
            if stack:
                result[stack['item']] = result.get(stack['item'], 0) + stack['count']
        return result

    def text():
        return ' '.join(call('command', f'data get block {X} 65 0')['chat'])

    def number(key):
        value = text()
        match = re.search(r'\b' + key + r':\s*(-?[\d.]+(?:[eE][+-]?\d+)?)', value)
        assert match, value
        return float(match[1])

    def clear():
        call('command', 'clear @s')
        call('command', 'kill @e[type=minecraft:item]')
        call('wait', 3)

    def reset():
        call('fill', X - 2, 64, -2, X + 8, 70, 4, 'minecraft:air')
        clear()
        call('command', f'tp @s {X + 3.5} 65 3.5')
        setblock(0, 65, 0, 'create:millstone')

    def drive(rpm=256):
        # Millstone is a small cog: a horizontal Y cog drives it in reverse.
        setblock(1, 65, 0, 'create:cogwheel[axis=y]')
        replace_motor(call, (X + 1, 64, 0), rpm, 'up')
        call('wait', 8)

    def stop():
        setblock(1, 64, 0, 'minecraft:air')
        call('wait', 8)

    def click():
        call('command', f'tp @s {X + .5} 65 2.5')
        call('look-at', 'block', X, 65, 0, 'south')
        call('interact', X, 65, 0, 'south')
        call('wait', 5)

    call('command', f'tp @s {X + 3.5} 67 3.5')
    call('wait-ready', 120)
    call('fill', X - 3, 63, -3, X + 9, 63, 5, 'minecraft:smooth_stone')
    reset()
    call('command', 'give @s minecraft:wheat 2')
    call('wait',3)
    call('select', 'minecraft:wheat')
    click()
    assert counts(slots()) == {}, slots()
    assert call('inventory')['counts'].get('minecraft:wheat') == 2
    clear()
    # Falling invalid input is rejected; valid input preserves its components.
    call('command', f'summon minecraft:item {X + .5} 66.4 .5 {{Item:{{id:"minecraft:diamond",count:2}},PickupDelay:32767}}')
    call('wait', 25)
    assert counts(slots()) == {}, slots()
    call('command', 'kill @e[type=minecraft:item]')
    # A grounded item on a separate support above the machine did not land on
    # the millstone. Extending its query must not turn that into valid input.
    setblock(0, 66, 0, 'minecraft:stone_slab[type=bottom]')
    call('command', f'summon minecraft:item {X + .5} 67.4 .5 {{Item:{{id:"minecraft:wheat",count:1}},PickupDelay:32767}}')
    call('wait', 25)
    assert counts(slots()) == {}, slots()
    above = call('entities', 24, 'minecraft:item')['entities']
    assert any(e.get('item', {}).get('item') == 'minecraft:wheat' for e in above), above
    call('command', 'kill @e[type=minecraft:item]')
    setblock(0, 66, 0, 'minecraft:air')
    call('command', f'summon minecraft:item {X + .5} 66.4 .5 {{Item:{{id:"minecraft:wheat",count:4,components:{{"minecraft:custom_data":{{milling_marker:501}}}}}},PickupDelay:32767}}')
    call('wait', 25)
    assert counts(slots()) == {'minecraft:wheat': 4}, slots()
    assert 'milling_marker' in text(), text()
    # Hopper extraction can never remove the input, regardless of side.
    setblock(0, 64, 0, 'minecraft:hopper[facing=east]')
    call('wait', 25)
    assert counts(slots()) == {'minecraft:wheat': 4} and counts(slots(0, 64)) == {}
    click()
    assert call('inventory')['counts'].get('minecraft:wheat') == 4
    marked = call('inventory')['hotbar'] + call('inventory')['main']
    assert any(s and s.get('item') == 'minecraft:wheat' and 'milling_marker' in s.get('components', '') for s in marked), marked
    print('Milling: recipe-filtered falling input, preserved components, no hand insertion or hopper input extraction', flush=True)

    reset()
    # Fill through original NBT, then collect outputs before the remaining input.
    call('command', f'data merge block {X} 65 0 {{InputInventory:{{Size:1,Items:[{{Slot:0,id:"minecraft:wheat",count:3}}]}},OutputInventory:{{Size:9,Items:[{{Slot:0,id:"create:wheat_flour",count:2}}]}}}}')
    call('wait', 5)
    assert counts(slots()) == {'minecraft:wheat': 3, 'create:wheat_flour': 2}, slots()
    click()
    assert call('inventory')['counts'] == {'create:wheat_flour': 2}, call('inventory')
    assert counts(slots()) == {'minecraft:wheat': 3}, slots()
    clear()
    click()
    assert call('inventory')['counts'] == {'minecraft:wheat': 3}
    assert counts(slots()) == {}
    print('Milling: original inventory NBT restored; empty-hand collection prioritises output then input', flush=True)

    reset()
    drive()
    assert number('Speed') == -256, text()
    assert number('Stress') == 1024, text()
    # A top shaft must not power a millstone; the bottom shaft does.
    stop()
    setblock(1, 65, 0, 'minecraft:air')
    setblock(0, 66, 0, 'create:shaft[axis=y]')
    setblock(0, 67, 0, 'create:creative_motor[facing=down]')
    call('wait', 10)
    assert number('Speed') == 0, text()
    setblock(0, 66, 0, 'minecraft:air')
    setblock(0, 67, 0, 'minecraft:air')
    setblock(0, 64, 0, 'create:creative_motor[facing=up]')
    call('wait', 10)
    assert number('Speed') == 16, text()
    setblock(0, 64, 0, 'minecraft:air')
    drive()
    setblock(0, 66, 0, 'minecraft:hopper[facing=down]')
    setblock(0, 64, 0, 'minecraft:hopper[facing=east]')
    # The extraction hopper points into a chest without disturbing the drive.
    setblock(0, 64, 1, 'minecraft:chest')
    setblock(0, 64, 0, 'minecraft:hopper[facing=south]')
    call('container', X, 66, 0, 'minecraft:diamond', 3)
    call('wait', 25)
    assert counts(slots(0, 66)) == {'minecraft:diamond': 3}, slots(0, 66)
    assert counts(slots()) == {}, slots()
    # Reset the top hopper to replace the rejected fixture.
    setblock(0, 66, 0, 'minecraft:air')
    setblock(0, 66, 0, 'minecraft:hopper[facing=down]')
    call('container', X, 66, 0, 'minecraft:sandstone', 3)
    call('wait', 150)
    result = counts(slots(0, 64, 1))
    assert result.get('minecraft:sand') == 3, {'chest':result,'mill':slots(),'upper':slots(0,66),'lower':slots(0,64),'nbt':text()}
    assert not result.get('minecraft:sandstone'), result
    assert counts(slots()) == {}, slots()
    print('Milling: bottom-only shaft, reverse side-cog RPM, 4 SU/RPM and filtered hopper input/output automation', flush=True)

    reset()
    drive(64)
    call('container', X, 65, 0, 'minecraft:sandstone', 4)
    call('wait', 8)
    stop()
    timer = number('Timer')
    before = counts(slots())
    assert timer > 0 and before == {'minecraft:sandstone': 4}, (timer, before)
    call('wait', 30)
    assert number('Timer') == timer and counts(slots()) == before
    # A single full result slot pauses all progress, even when other slots are free.
    call('command', f'data merge block {X} 65 0 {{OutputInventory:{{Size:9,Items:[{{Slot:8,id:"minecraft:sand",count:64}}]}}}}')
    drive(256)
    call('wait', 25)
    assert number('Timer') == timer and counts(slots()).get('minecraft:sandstone') == 4
    call('command', f'data merge block {X} 65 0 {{OutputInventory:{{Size:9,Items:[]}}}}')
    call('wait', 150)
    assert counts(slots()) == {'minecraft:sand': 4}, slots()
    if graphics:
        call('command', f'tp @s {X + 2.5} 66 3.5')
        call('look-at', X + .5, 65.5, .5)
        call('wait', 20)
        poses = [p for p in engineering_checks.poses(log, [X, 65, 0]) if p['model'].endswith('millstone/inner')]
        engineering_checks.source_rotation(poses,1,-256,22.5)
        call('screenshot', scratch / 'millstone.png')
    print('Milling: RPM-dependent processing pauses without power/full buffer and resumes with input/output conservation', flush=True)

    # Original wheat milling rolls two independent bonus flour units and a seed.
    reset()
    drive(256)
    call('container', X, 65, 0, 'minecraft:wheat', 16)
    call('wait', 220)
    result = counts(slots())
    assert 16 <= result.get('create:wheat_flour', 0) <= 48, result
    assert 0 <= result.get('minecraft:wheat_seeds', 0) <= 16, result
    assert set(result) <= {'create:wheat_flour', 'minecraft:wheat_seeds'}, result
    print('Milling: original multi-result wheat recipe consumed sixteen inputs with valid independent bonus output rolls', flush=True)

    # Save a partially processed, stopped machine, with original input data.
    reset()
    drive(16)
    call('container', X, 65, 0, 'minecraft:sandstone', 3)
    call('wait', 12)
    stop()
    fixture = {'pos': [X, 65, 0], 'timer': number('Timer'), 'input': counts(slots())}
    assert fixture['timer'] > 0 and fixture['input'] == {'minecraft:sandstone': 3}, fixture
    return fixture


def reloaded(call, fixture):
    pos = fixture['pos']
    call('command',f'tp @s {pos[0]+2.5} {pos[1]+1} {pos[2]+3.5}');call('wait-ready',120)
    text = ' '.join(call('command', 'data get block ' + ' '.join(map(str, pos)))['chat'])
    match = re.search(r'\bTimer:\s*(-?\d+)', text)
    assert match and int(match[1]) == fixture['timer'], (fixture, text)
    assert 'InputInventory' in text and 'OutputInventory' in text, text
    slots = call('container', *pos)['slots']
    assert slots[0]['item'] == 'minecraft:sandstone' and slots[0]['count'] == 3, slots
    replace_motor(call, (X + 1, 64, 0), 256, 'up')
    call('wait', 150)
    slots = call('container', *pos)['slots']
    assert sum(s['count'] for s in slots if s and s['item'] == 'minecraft:sand') == 3, slots
    assert not any(s and s['item'] == 'minecraft:sandstone' for s in slots), slots
    print('Milling: original NBT timer/inventories survive save/reload and resume into exactly three outputs', flush=True)
