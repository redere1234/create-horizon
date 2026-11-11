"""Native fan processing and airflow fixtures in the disposable smoke world."""
import re
import engineering_checks
from native_motors import replace_motor

X=96
def run(call,graphics,log,scratch):
    def setblock(x,y,z,name):return call('setblock',X+x,y,z,name)
    def text(x=0,y=65,z=0):return ' '.join(call('command',f'data get block {X+x} {y} {z}')['chat'])
    def counts(x=3,y=64,z=0):
        result={}
        for s in call('container',X+x,y,z)['slots']:
            if s:result[s['item']]=result.get(s['item'],0)+s['count']
        return result
    def reset(rpm=256):
        call('command',f'tp @s {X+3.5} 66 4.5');call('wait-ready',120)
        call('fill',X-3,64,-3,X+9,70,4,'minecraft:air');call('command','clear @s');call('command','kill @e[type=minecraft:item]')
        call('fill',X-3,63,-3,X+9,63,4,'minecraft:smooth_stone')
        replace_motor(call, (X - 1, 65, 0), rpm, 'east')
        setblock(0,65,0,'create:encased_fan[facing=east]');setblock(3,64,0,'create:depot');call('wait',35)
    def supply(item,count=1):call('container',X+3,64,0,item,count)
    def catalyst(name):setblock(1,65,0,name);call('wait',35)
    # Flow only exits the front, the rear shaft is the sole kinetic input.
    reset();assert 'Speed: 256' in text(),text()
    setblock(-1,65,0,'minecraft:air');setblock(1,65,0,'create:creative_motor[facing=west]');call('wait',8)
    assert re.search(r'Speed:\s*0(?:f|[.,}])',text()),text()
    reset();catalyst('minecraft:campfire[lit=true]');supply('create:dough',8);call('wait',170)
    assert counts()=={'minecraft:bread':8},counts()
    print('Fan: rear-only shaft and real smoking dough -> eight bread on depot passed',flush=True)
    reset();catalyst('minecraft:soul_campfire[lit=true]');supply('minecraft:sand',16);call('wait',170)
    assert counts()=={'minecraft:soul_sand':16},counts()
    # Unlit campfires must not process, and blocking cube stops downstream flow.
    reset();catalyst('minecraft:campfire[lit=false]');supply('create:dough');call('wait',170)
    assert counts()=={'create:dough':1},counts()
    catalyst('minecraft:campfire[lit=true]');setblock(2,65,0,'minecraft:stone');call('wait',200)
    assert counts()=={'create:dough':1},counts()
    setblock(2,65,0,'minecraft:air');call('wait',200);assert counts()=={'minecraft:bread':1},counts()
    print('Fan: haunting, unlit catalyst rejection, obstacle stop/resume passed',flush=True)
    # Stable waterlogged permeable catalyst avoids moving fluid fixture changes.
    reset();catalyst('minecraft:oak_fence[waterlogged=true]');supply('create:wheat_flour',16);call('wait',175)
    assert counts()=={'create:dough':16},counts()
    # Same RPM works on a 17-stack but requires twice the processing time.
    reset(16);catalyst('minecraft:oak_fence[waterlogged=true]');supply('create:wheat_flour',17);call('wait',180)
    assert counts()=={'create:wheat_flour':17},counts()
    call('wait',165);assert counts()=={'create:dough':17},counts()
    print('Fan: washing and 16/17 stack threshold independent of RPM passed',flush=True)
    reset();catalyst('minecraft:oak_fence[waterlogged=true]');setblock(4,65,0,'minecraft:glass')
    call('command',f'summon minecraft:item {X+3.5} 65.5 .5 {{Tags:["create_smoke_washed"],Item:{{id:"create:wheat_flour",count:4}},NoGravity:1b,PickupDelay:32767}}')
    call('wait',175)
    value=' '.join(call('command','data get entity @e[type=minecraft:item,tag=create_smoke_washed,limit=1] Item')['chat'])
    assert 'create:dough' in value and re.search(r'count:\s*4',value),value
    print('Fan: four loose items processed through the real air current without inventory duplication',flush=True)
    # Blasting lava column, retained by adjacent glass, smelts ore but burns food.
    reset()
    for x,z in [(1,-1),(1,1),(2,0)]:setblock(x,65,z,'minecraft:glass')
    setblock(1,64,0,'minecraft:glass');catalyst('minecraft:lava');setblock(2,65,0,'minecraft:air')
    supply('minecraft:raw_iron',4);call('wait',180);assert counts()=={'minecraft:iron_ingot':4},counts()
    setblock(3,64,0,'minecraft:air');setblock(3,64,0,'create:depot');supply('minecraft:beef',3);call('wait',180)
    assert counts()=={},counts()
    print('Fan: furnace recipes through lava; smokeable food is destroyed by blasting as in Java',flush=True)
    # A thrown entity must accelerate both ways; no client-only smoke substitute.
    for rpm,sign in [(256,1),(-256,-1)]:
        reset(rpm)
        call('command',f'summon minecraft:item {X+3.5} 65.5 .5 {{Tags:["create_smoke_velocity"],Item:{{id:"minecraft:diamond",count:1}},NoGravity:1b,PickupDelay:32767}}')
        call('wait',8)
        value=' '.join(call('command','data get entity @e[type=minecraft:item,tag=create_smoke_velocity,limit=1] Motion')['chat'])
        numbers=re.findall(r'(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)d',value)
        assert numbers and float(numbers[0])*sign>0,(rpm,value)
    if graphics:
        reset(16);call('look-at',X+.5,65.5,.5);call('wait',35)
        rows=engineering_checks.poses(log,[X,65,0]);parts=[r for r in rows if r['model'].endswith('encased_fan/propeller')]
        engineering_checks.source_rotation(parts,0,80)
        call('screenshot',scratch/'fan.png')
    print('Fan: real item velocity reverses with rotation; ' +
          ('original rotating propeller poses passed' if graphics else
           'renderer poses were not checked in headless mode'), flush=True)
    # Keep a stopped transported stack with canonical timer/type through reload.
    reset(16);catalyst('minecraft:campfire[lit=true]');supply('create:dough',17);call('wait',30)
    setblock(-1,65,0,'minecraft:air');call('wait',8)
    before=text(3,64);m=re.search(r'FanProcessingTime:\s*(-?\d+)',before);assert m,before
    return {'pos':[X+3,64,0],'timer':int(m[1])}

def reloaded(call,fixture):
    pos=fixture['pos'];call('command',f'tp @s {pos[0]+2.5} {pos[1]+1} {pos[2]+3.5}');call('wait-ready',120)
    text=' '.join(call('command','data get block '+' '.join(map(str,fixture['pos'])))['chat'])
    assert 'create:smoking' in text and f"FanProcessingTime: {fixture['timer']}" in text,text
    call('setblock',X-1,65,0,'create:creative_motor[facing=east]');call('wait',350)
    slots=call('container',*fixture['pos'])['slots']
    assert sum(s['count'] for s in slots if s and s['item']=='minecraft:bread')==17,slots
    print('Fan: canonical transported type/timer survived reload and resumed into seventeen bread',flush=True)
