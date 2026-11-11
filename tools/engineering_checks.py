"""0.4 integration checks against real player actions and submitted render poses."""
import json
import math
import re
import shutil
import subprocess
import sys
import time
from common import ROOT
from native_motors import replace_motor
import foundation_checks

X=36
def run(call,graphics,log,scratch):
    def setblock(x,y,z,name):return call('setblock',X+x,y,z,name)
    def block(x,y,z):return call('block',X+x,y,z)
    def tp(x=3.5,y=65,z=5.5):call('command',f'tp @s {X+x} {y} {z}')
    def text(x,y,z):return ' '.join(call('command',f'data get block {X+x} {y} {z}')['chat'])
    def number(x,y,z,key):
        t=text(x,y,z);m=re.search(r'\b'+key+r':\s*(-?[\d.]+(?:[eE][+-]?\d+)?)',t);assert m,t;return float(m[1])
    def clear():call('command','kill @e[type=minecraft:item]');call('command','clear @s');call('wait',3)
    def give(name,count=1):call('command',f'give @s {name} {count}');call('wait',3);call('select',name)
    def reset():call('fill',X-3,64,-4,X+11,73,7,'minecraft:air');clear();tp()
    def click(x,y,z,face='south'):
        call('look-at','block',X+x,y,z,face);call('wait',3);call('interact',X+x,y,z,face);call('wait',8)
    tp();call('wait-ready',120);call('fill',X-4,63,-5,X+12,63,8,'minecraft:smooth_stone')
    # Alias item must consume normally and place the canonical gearbox block.
    for neighboring,expected in [(None,'z'),('create:shaft[axis=x]','z'),('create:shaft[axis=z]','x')]:
        reset();setblock(0,64,0,'minecraft:stone');tp(3,65,.5)
        if neighboring:
            if 'axis=x' in neighboring:setblock(1,65,0,neighboring)
            else:setblock(0,65,1,neighboring)
        call('command','gamemode survival');give('create:vertical_gearbox',2);click(0,64,0,'up')
        placed=block(0,65,0);assert placed['block']=='create:gearbox' and 'axis='+expected in placed['state'],placed
        assert call('inventory')['counts'].get('create:vertical_gearbox')==1
        call('command','gamemode creative')
    print('Engineering: vertical gearbox item alias, neighbour preference and consumption passed',flush=True)
    # Source gauge axis/facing from actual placement against a shaft.
    for axis,d,face in [('x',(1,0,0),'east'),('y',(0,1,0),'up'),('z',(0,0,1),'south')]:
        reset();setblock(0,65,0,f'create:shaft[axis={axis}]');setblock(3,66,3,'minecraft:stone');tp(3.5,67,3.5)
        give('create:speedometer');click(0,65,0,face)
        p=(d[0],65+d[1],d[2]);placed=block(*p);assert placed['block']=='create:speedometer',placed
        # Connect a motor to the opposite end of the original shaft.
        direction={'x':'east','y':'up','z':'south'}[axis]
        setblock(-d[0],65-d[1],-d[2],f'create:creative_motor[facing={direction}]');call('wait',12)
        assert number(*p,'Speed')==16,text(*p)
    print('Engineering: gauges place on and receive rotation along X/Y/Z shafts',flush=True)
    reset();setblock(0,65,0,'create:creative_motor[facing=east]');setblock(1,65,0,'create:speedometer[facing=south,axis_along_first=true]');setblock(2,65,0,'create:stressometer[facing=south,axis_along_first=true]');setblock(3,65,0,'create:mechanical_press[facing=east]')
    call('wait',15)
    assert abs(number(1,65,0,'Value')-.24)<1e-5
    assert number(2,65,0,'Capacity')==262144 and number(2,65,0,'Stress')==128
    # A real comparator reads the source's ceil(target*14), updates after RPM changes.
    setblock(1,64,1,'minecraft:stone');setblock(1,65,1,'minecraft:comparator[facing=north]');setblock(1,64,2,'minecraft:stone');setblock(1,65,2,'minecraft:redstone_wire');call('wait',10)
    assert 'power=4' in block(1,65,2)['state'],block(1,65,2)
    replace_motor(call, (X, 65, 0), 256, 'east');call('wait',20)
    assert abs(number(1,65,0,'Value')-1.125)<1e-5
    assert 'power=15' in block(1,65,2)['state'],block(1,65,2)
    if graphics:
        tp(1.5,65,3.5);clear();call('command','item replace entity @s armor.head with minecraft:air');give('create:goggles');call('look',0,-80);call('mouse','right','click');call('wait',5)
        hud_start=log.stat().st_size
        call('look-at','block',X+1,65,0,'south')
        deadline=time.monotonic()+12
        while True:
            with log.open() as stream:
                stream.seek(hud_start)
                rows=[]
                for line in stream:
                    if 'Create visual: ' not in line:
                        continue
                    try:
                        rows.append(json.loads(line.split('Create visual: ',1)[1]))
                    except json.JSONDecodeError:
                        continue  # The renderer may still be finishing its last line.
            if any(r.get('event')=='goggles_hud' and r.get('pos')==[X+1,65,0]
                   and any(re.search(r'(?<!\d)256(?!\d)',line.get('text','')) for line in r.get('lines',[])) for r in rows):
                break
            assert time.monotonic()<deadline,rows[-5:]
            call('wait',2)
        call('screenshot',scratch/'goggles.png')
        setblock(4,68,5,'minecraft:stone');tp(4.5,69,5.5);call('look',90,0);call('key','f5','tap');call('key','f5','tap');call('key','f1','tap');call('wait',5);call('screenshot',scratch/'goggles-worn.png');call('key','f1','tap');call('key','f5','tap');call('wait',3)
    print('Engineering: gauge dial targets, network SU, actual comparator 4->15 and goggles HUD passed',flush=True)
    if graphics:
        # Real pose matrices must rotate around the SAME world axis at each shared port.
        for kind in ['gearbox','clutch','gearshift']:
            reset();tp(1.5,65,3.5)
            setblock(0,65,0,'create:creative_motor[facing=east]');setblock(1,65,0,'create:shaft[axis=x]');setblock(2,65,0,'create:'+kind+('[axis=y]' if kind=='gearbox' else '[axis=x]'));setblock(3,65,0,'create:shaft[axis=x]')
            call('look-at',X+2,65.5,.5);call('wait',35)
            rows=poses(log,[X+2,65,0]);assert rows,kind
            for sign in [-1,1]:
                half=[r for r in rows if r['model'].endswith('/shaft_half') and r['axis']==[sign,0,0]]
                actual=angular_velocity(half,0)
                expected=16 if sign<0 or kind!='gearbox' else -16
                assert abs(actual-expected)<.05,(kind,sign,actual,expected)
        print('Engineering: actual gearbox/clutch/gearshift half-shaft matrices agree with adjacent canonical RPM',flush=True)
        for facing,axis,sign in [('east',0,1),('west',0,-1),('up',1,1),('down',1,-1),('south',2,1),('north',2,-1)]:
            reset()
            setblock(2,64,3,'minecraft:smooth_stone')
            tp(2.5,65,3.5)
            setblock(0,65,0,'create:hand_crank[facing='+facing+']')
            call('look-at', X + .5, 65.5, .5)
            call('wait', 4)  # Let the visible block catch up with the server write.
            # A live turn publishes generator speed. Reading an InUse NBT
            # edit into an already initialized crank does not perform a turn.
            for _ in range(8):
                call('interact',X,65,0)
                call('wait',3)
            start = log.stat().st_size
            for _ in range(12):
                call('interact',X,65,0)
                call('wait',3)
            assert number(0,65,0,'Speed')==sign*32, text(0,65,0)
            rows = poses(log, [X,65,0], start)
            for model, tolerance in [('block', .05), ('handle', .1)]:
                part = [row for row in rows if row['model'].endswith(f'hand_crank/{model}')]
                # A 20-tick gap at 32 RPM wraps past 180 degrees and aliases.
                pairs = [(a, b) for a, b in zip(part, part[1:]) if 0 < b['time'] - a['time'] < 18]
                assert pairs, (facing, model, part)
                actual = angular_velocity(pairs[-1], axis)
                assert abs(actual - sign * 32) < tolerance, (facing, model, actual, pairs[-1])
        print('Engineering: actual crank base and smoothed handle poses agree on all six facings',flush=True)

    # Brass default pressing is one item per stroke and returns all outputs.
    reset();replace_motor(call, (X, 67, 0), 256, 'east');setblock(1,67,0,'create:mechanical_press[facing=east]');setblock(1,65,0,'create:depot');call('container',X+1,65,0,'create:brass_ingot',8);call('wait',150)
    stacks=call('container',X+1,65,0)['slots'];assert sum(s.get('count',0) for s in stacks if s and s['item']=='create:brass_sheet')==8,stacks
    setblock(1,65,2,'minecraft:stone');tp(1.5,66,2.5);clear();click(1,65,0,'up');assert call('inventory')['counts'].get('create:brass_sheet')==8
    print('Engineering: eight brass ingots press into eight retrievable brass sheets',flush=True)
    # Controlled bubble currents use the game's real flow sampler, in both directions.
    for large in [False,True]:
        reset();r=2 if large else 1;wheel='large_water_wheel' if large else 'water_wheel';rpm=4 if large else 8
        setblock(0,67,0,'create:'+wheel+('[axis=x]' if large else '[facing=east]'));setblock(1,67,0,'create:shaft[axis=x]');call('wait',8)
        if large:
            for y in range(66,69):
                for z in range(-1,2):
                    if (y,z)!=(67,0):assert block(0,y,z)['block']=='create:water_wheel_structure',(y,z,block(0,y,z))
        for y in range(66,71):
            for x,z in [(-1,r),(1,r),(0,r+1),(0,r-1)]:
                if block(x,y,z)['block']=='minecraft:air':setblock(x,y,z,'minecraft:glass')
        setblock(0,65,r,'minecraft:soul_sand')
        for y in range(66,70):setblock(0,y,r,'minecraft:water')
        call('wait',35)
        assert abs(number(1,67,0,'Speed'))==rpm,text(0,67,0)
        assert number(0,67,0,'Capacity')==(512 if large else 256),text(0,67,0)
        before=number(1,67,0,'Speed');setblock(0,65,r,'minecraft:magma_block');call('wait',35)
        assert number(1,67,0,'Speed')==-before,text(0,67,0)
        setblock(1,67,0,'minecraft:air');setblock(2,66,-2,'minecraft:stone');tp(2.5,67,-1.5);give('minecraft:cherry_planks',3);click(0,67,0,'east');setblock(1,67,0,'create:shaft[axis=x]');call('wait',5)
        assert 'cherry_planks' in text(0,67,0) and call('inventory')['counts'].get('minecraft:cherry_planks')==3
        call('screenshot',scratch/('large-wheel.png' if large else 'water-wheel.png')) if graphics else None
    print('Engineering: real fluid currents, reverse flow, 8/4 RPM, capacities, structural ring and material exchange passed',flush=True)
    # Preserve this assembly for reload checking before checking creative break cleanup.
    fixture={'pos':[X,67,0],'rpm':number(1,67,0,'Speed')}
    # Original large-wheel retry above the floor, refusal without item loss, cleanup/drop.
    tp(9.5,64,3.5);setblock(6,65,4,'minecraft:stone');call('command','gamemode survival');clear();give('create:large_water_wheel',2)
    click(6,63,3,'up');assert call('inventory')['counts'].get('create:large_water_wheel')==2
    assert block(6,65,3)['block']!='create:large_water_wheel'
    setblock(6,65,4,'minecraft:air');click(6,63,3,'up');assert block(6,65,3)['block']=='create:large_water_wheel',block(6,65,3)
    assert call('inventory')['counts'].get('create:large_water_wheel')==1
    call('look-at','block',X+6,66,3);call('break',X+6,66,3);call('wait',12)
    assert block(6,65,3)['block']=='minecraft:air'
    for y in range(64,67):
        for z in range(2,5):assert block(6,y,z)['block']!='create:water_wheel_structure'
    tp(6.5,65,3.5);call('wait',20);assert call('inventory')['counts'].get('create:large_water_wheel')==2,call('inventory')
    call('command','gamemode creative')
    print('Engineering: blocked placement preserves items, floor retry works, structural break returns one wheel and clears all parts',flush=True)

    if graphics:
        foundation_checks.crafting(call, X + 8, clear, [
            'kinetics/vertical_gearbox', 'kinetics/vertical_gearbox_from_conversion',
            'kinetics/gearbox_from_conversion', 'kinetics/goggles', 'kinetics/speedometer',
            'kinetics/stressometer_from_conversion', 'kinetics/water_wheel', 'kinetics/large_water_wheel',
            'kinetics/propeller', 'kinetics/millstone', 'kinetics/encased_fan',
            'kinetics/mechanical_drill', 'appliances/dough',
            'kinetics/fluid_tank', 'kinetics/fluid_pipe', 'kinetics/fluid_pipe_vertical',
            'kinetics/mechanical_pump', 'kinetics/fluid_valve',
        ])
    return fixture

def poses(log, pos, start=0):
    with log.open() as stream:
        stream.seek(start)
        rows = (json.loads(line.split('Create pose: ', 1)[1]) for line in stream if 'Create pose: ' in line)
        return [row for row in rows if row['pos'] == pos]

def angular_velocity(rows,axis):
    # Pose columns normalized: Q=M2*M1^T removes static model orientation.
    assert len(rows)>=2,rows
    a,b=rows[-2:];dt=b['time']-a['time'];assert dt>0,rows[-2:]
    def rotation(row):
        cols=[row['matrix'][i:i+3] for i in [0,4,8]]
        return [[cols[c][r]/math.sqrt(sum(v*v for v in cols[c])) for c in range(3)] for r in range(3)]
    m,n=rotation(a),rotation(b);q=[[sum(n[r][k]*m[c][k] for k in range(3)) for c in range(3)] for r in range(3)]
    j,k=(axis+1)%3,(axis+2)%3
    angle=math.atan2((q[k][j]-q[j][k])/2,(sum(q[i][i] for i in range(3))-1)/2)
    return math.degrees(angle)/dt/.3

def source_rotation(rows,axis,rpm,offset=0):
    """Compare submitted poses to actual Java angles at recorded frame times.

    Differentiating ideal RPM is inaccurate: Create computes angles in f32,
    so late frames have quantized angles and apparently uneven instantaneous RPM.
    The Java fixture exports the original method body, independently of Rust.
    """
    work=ROOT/'.local/visual-oracle'
    if not (work/'VisualOracle.class').is_file():
        subprocess.run([sys.executable,str(ROOT/'tools/visual_oracle.py')],check=True)
    a,b=rows[-2:]
    requests=''.join(f"A {p['time']} {rpm} {offset}\n" for p in [a,b])
    values=list(map(float,subprocess.check_output([shutil.which('java'),'-cp',str(work),'VisualOracle'],input=requests,text=True).split()))
    delta=(values[1]-values[0]+math.pi)%(2*math.pi)-math.pi
    expected=math.degrees(delta)/(b['time']-a['time'])/.3
    actual=angular_velocity(rows,axis)
    assert abs(actual-expected)<.05,{'actual':actual,'java':expected,'rpm':rpm,'frames':[a,b]}

def reloaded(call,fixture):
    p=fixture['pos'];text=' '.join(call('command','data get block '+' '.join(map(str,p)))['chat'])
    assert 'cherry_planks' in text and re.search(r'StructureReady"?\s*:\s*1b',text),text
    assert call('block',p[0],p[1]+1,p[2])['block']=='create:water_wheel_structure'
