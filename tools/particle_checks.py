#!/usr/bin/env python3
"""Native renderer checks in a fresh world; compare traced source invariants.

This runs the real paired client/server and ordinary particle engine. It does
not label screenshots or independently seeded clouds as pixel parity. Set
CREATE_HORIZON_PARTICLE_TRACE=1 when embedding run() in another smoke driver.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from common import ROOT
from native_check_session import wait_loaded
from native_motors import replace_motor
from value_settings_checks import motor_board_coordinate


def records(path, offset=0):
    result = []
    for line in Path(path).read_bytes()[offset:].decode(errors='replace').splitlines():
        marker = 'Create particle: '
        if marker in line:
            result.append(json.JSONDecoder().raw_decode(line.split(marker, 1)[1])[0])
    return result


def run(call, log, scratch=None, graphics=True):
    """Only use on a disposable world. Reserves x237..270/y68..74/z-3..10."""
    origin, y = 240, 70
    motor = (origin - 1, y, 0)
    log = Path(log)

    def command(text):
        return call('command', text)

    def mark():
        return log.stat().st_size

    def scoped(offset, kind=None, event=None, pos=None):
        return [r for r in records(log, offset)
                if (kind is None or r['kind'] == kind)
                and (event is None or r['event'] == event)
                and (pos is None or r['origin'] == list(pos))]

    def speed(rpm):
        if rpm == 0:
            replace_motor(call, motor, rpm, 'east')
            return
        command(f'tp @s {motor[0] + .5} {y} 3.5')
        call('look-at', 'block', *motor, 'south')
        call('wait', 3)
        call('mouse', 'right', 'down')
        call('wait', 10)
        assert call('screen')['screen'] == 'mod'
        boards = [json.loads(line.split('Create motor board: ', 1)[1])
                  for line in log.read_text().splitlines() if 'Create motor board: ' in line]
        assert boards and boards[-1]['pos'] == list(motor), boards[-1:]
        point = motor_board_coordinate(boards[-1], int(rpm > 0), abs(rpm))
        call('click-at', *point, 'right')
        call('release')
        call('wait', 8)
        assert call('screen')['screen'] == 'playing'
        state = command('data get block %d %d %d' % motor)
        assert f'ScrollValue: {rpm}' in ' '.join(state['chat']), state
        command(f'tp @s {origin + 5.5} {y} 4.5')

    def wait(ticks=10):
        call('wait', ticks)

    command('tick unfreeze')
    command('gamemode creative')
    command(f'tp @s {origin + 5.5} {y} 4.5')
    wait_loaded(call, [(x, y, z) for x in (237, 255, 270) for z in (-3, 10)])
    call('fill', origin - 3, 68, -3, origin + 30, 74, 10, 'minecraft:air')
    call('fill', origin - 3, 69, -3, origin + 30, 69, 10, 'minecraft:smooth_stone')
    # Clearing the platform can let the live player fall before the following
    # command places its floor. Restore the camera after construction.
    command(f'tp @s {origin + 5.5} {y} 4.5')
    command('item replace entity @s armor.head with create:goggles')
    before = mark()
    call('setblock', origin - 1, y, 0, 'create:creative_motor[facing=east]')
    wait(10)
    bursts = scoped(before, 'rotation_indicator', 'spawn', motor)
    assert len(bursts) == 20, ('first source generator tier burst', len(bursts),
                               'requires CREATE_HORIZON_PARTICLE_TRACE=1')
    for sample in bursts:
        assert 10 <= sample['lifetime'] <= 41, sample
        assert sample['age'] == 0 and sample['position'] == sample['previous'], sample
        assert sample['quad'] and sample['quad']['sprite'].endswith('glitter_7'), sample
        assert sample['quad']['light'] == 0xF000F0, sample
        assert sample['quad']['rgba'] == [144 / 255, 1.0, 144 / 255, 1.0] or all(
            abs(a - b) < 1e-6 for a, b in zip(sample['quad']['rgba'], [144/255, 1, 144/255, 1])), sample
        assert .075 <= sample['quad']['size'][0] <= .15, sample

    before = mark()
    speed(128)
    wait()
    assert len(scoped(before, 'rotation_indicator', 'spawn', motor)) == 20
    before = mark()
    speed(256)
    wait()
    assert not scoped(before, 'rotation_indicator', 'spawn', motor), 'same speed tier must not queue'
    before = mark()
    speed(-256)
    wait()
    assert not scoped(before, 'rotation_indicator', 'spawn', motor), 'sign-only change must not queue'
    command('item replace entity @s armor.head with minecraft:air')
    before = mark()
    speed(32)
    wait()
    hidden = scoped(before, 'rotation_indicator', 'spawn', motor)
    assert len(hidden) == 20 and all(s['quad'] is None for s in hidden), hidden
    command('item replace entity @s armor.head with create:goggles')
    print('Particles: source20 burst, tiers, sign, lifetime, sprite, light and goggles gate passed', flush=True)

    # Actual Java regression:32RPM generator overdriven at64RPM resumes with
    #20 particles although both running speeds have the same MEDIUM tier.
    # removeSource clears the source's raw speed before reActivateSource runs.
    left = (origin+3, y, 6)
    right = (origin+5, y, 6)
    replace_motor(call, left, 32, 'east')
    call('setblock', origin+4, y, 6, 'create:shaft[axis=x]')
    replace_motor(call, right, -64, 'west')
    wait(50)
    before = mark()
    call('setblock', *right, 'minecraft:air')
    wait(10)
    recovered = scoped(before, 'rotation_indicator', 'spawn', left)
    assert len(recovered) == 20, ('same-tier generator recovery', len(recovered))
    print('Particles: Java-confirmed same-tier generator recovery delivered20 particles', flush=True)

    # More simultaneous events than NativeNet's32 per-player messages: every
    # event must arrive through the per-recipient batch, without silent loss.
    command('tick freeze')
    gallery = {(origin + 20 + i % 8, y, 4 + i // 8) for i in range(40)}
    for p in sorted(gallery):
        call('setblock', *p, 'create:creative_motor[facing=up]')
    before = mark()
    command('tick unfreeze')
    wait(10)
    batch = [r for r in scoped(before, 'rotation_indicator', 'spawn') if tuple(r['origin']) in gallery]
    assert Counter(tuple(r['origin']) for r in batch) == Counter({p:20 for p in gallery}), len(batch)
    print('Particles:40 simultaneous source bursts delivered800 controlled particles through native batching', flush=True)

    call('setblock', origin, y, 0, 'create:encased_fan[facing=east]')
    call('setblock', origin + 13, y, 0, 'minecraft:stone')
    speed(256)
    wait(35)
    before = mark()
    wait(45)
    samples = scoped(before, 'air_flow', 'tick', (origin, y, 0))
    live = [s for s in samples if not s['removed']]
    assert live, 'no real airflow controller ticks'
    for sample in live:
        previous, current = sample['previous'], sample['position']
        distance = previous[0] - origin - 1
        expected = (12 - (distance - 1)) / 16
        assert abs(sample['velocity'][0] - expected) < 1e-10, sample
        assert abs(current[0] - previous[0] - expected) < 1e-10, sample
        assert current[1:] == previous[1:] and sample['velocity'][1:] == [0, 0], sample
        assert sample['lifetime'] == 40 and 1 <= sample['age'] <= 40, sample
        assert 0 <= sample['frame'] <= 6, sample
    created = scoped(before, 'air_flow', 'spawn', (origin, y, 0))
    assert created and all(s['quad']['sprite'].endswith('generic_1') for s in created), created

    media = {
        'smoking': 'minecraft:campfire[lit=true]',
        'haunting': 'minecraft:soul_campfire[lit=true]',
        'splashing': 'minecraft:oak_fence[waterlogged=true]',
        'blasting': 'minecraft:lava',
    }
    for kind, catalyst in media.items():
        call('setblock', origin + 1, y, 0, 'minecraft:air')
        if kind == 'blasting':
            for p in [(origin+1,y-1,0),(origin+1,y+1,0),(origin+1,y,-1),(origin+1,y,1)]:
                call('setblock', *p, 'minecraft:glass')
            call('setblock', origin+2,y,0,'minecraft:iron_bars')
        call('setblock', origin+1,y,0,catalyst)
        wait(35)
        before = mark()
        wait(50)
        colored = [s for s in scoped(before,'air_flow','tick',(origin,y,0))
                   if not s['removed'] and s['rgba'][3] != .25]
        assert colored, (kind, 'no source morph')
        for sample in colored:
            r,g,b,a=sample['rgba']
            assert sample['frame'] in (0,1), sample
            if kind == 'smoking': assert r==g==b and 0<=r<=85/255+1e-6 and a==1, sample
            elif kind == 'haunting': assert 0<=r<=18/255+1e-6 and 0<=g<=101/255+1e-6 and 0<=b<=104/255+1e-6 and a==1,sample
            elif kind == 'splashing': assert 34/255-1e-6<=r<=68/255+1e-6 and 119/255-1e-6<=g<=153/255+1e-6 and b==1 and a==1,sample
            else: assert r==1 and 68/255-1e-6<=g<=136/255+1e-6 and 0<=b<=85/255+1e-6 and a==.5,sample
        if graphics and scratch:
            call('look-at',origin+5.5,y+.5,.5)
            call('screenshot',Path(scratch)/('fan-particles-'+kind+'.png'))
    before = mark()
    speed(-256)
    wait(40)
    pulled = [s for s in scoped(before,'air_flow','tick',(origin,y,0)) if not s['removed']]
    assert pulled and any(s['velocity'][0]<0 for s in pulled), pulled[-4:]
    before = mark()
    speed(0)
    wait(10)
    # Allow the already queued client/server change to arrive, then all old
    # particles must retire against the empty current; no new ones can spawn.
    before = mark()
    wait(8)
    assert not scoped(before,'air_flow','spawn',(origin,y,0))
    assert not [s for s in scoped(before,'air_flow','tick',(origin,y,0)) if not s['removed']]
    saved=' '.join(command(f'data get block {origin} {y} 0')['chat'])
    assert 'CreateHorizonAirCurrent' not in saved and 'CreateHorizonRotationParticle' not in saved, saved
    print('Particles: real airflow velocity, bounds, all4 media, source sprite mapping, reversal and stop cleanup passed',flush=True)
    result={'passed':True,'scope':'native paired renderer/transport/source invariants; source and native screenshots need separate matched-fixture review','rotation_particles':len(bursts)+len(hidden)+len(batch)+len(recovered),'airflow_ticks':len(live),'media':list(media)}
    if scratch:
        (Path(scratch)/'particle-result.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def capture_media(call, scratch):
    """Capture a stable, matched source fixture; use a disposable world only."""
    def command(text):return call('command',text)
    command('tick unfreeze')
    command('gamemode creative')
    command('time set day')
    command('weather clear')
    command('tp @s 245.5 70 4.5')
    wait_loaded(call, [(x, 70, z) for x in (237, 255, 270) for z in (-3, 10)])
    call('fill',237,68,-3,270,74,10,'minecraft:air')
    call('fill',237,69,-3,270,69,10,'minecraft:smooth_stone')
    command('tp @s 245.5 70 4.5')
    call('wait',12)
    camera=call('status')['player']
    assert camera['on_ground'] and abs(camera['position'][1]-70)<1e-4,camera
    replace_motor(call, (239, 70, 0), 256, 'east')
    call('setblock',240,70,0,'create:encased_fan[facing=east]')
    call('setblock',253,70,0,'minecraft:stone')
    call('key','f1','tap')
    call('look-at',247.5,70.5,.5)
    for kind,catalyst in [('normal','minecraft:air'),('smoking','minecraft:campfire[lit=true]'),
                          ('haunting','minecraft:soul_campfire[lit=true]'),
                          ('splashing','minecraft:oak_fence[waterlogged=true]'),
                          ('blasting','minecraft:lava')]:
        call('setblock',241,70,0,'minecraft:air')
        if kind=='blasting':
            for p in [(241,69,0),(241,71,0),(241,70,-1),(241,70,1)]:call('setblock',*p,'minecraft:glass')
            call('setblock',242,70,0,'minecraft:iron_bars')
        call('setblock',241,70,0,catalyst)
        call('wait',60)
        state=call('status')['player']
        position=state['position']
        if isinstance(position,dict):position=[position[k] for k in ('x','y','z')]
        assert position[1]>=69.9,('camera fell below platform',position)
        assert state['on_ground'],('camera not grounded',state)
        target=call('status').get('target')
        assert not target or target.get('block') not in ('minecraft:water','minecraft:bubble_column'),target
        call('screenshot',Path(scratch)/('fan-particles-'+kind+'.png'))
    call('key','f1','tap')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resources',type=Path,required=True)
    parser.add_argument('--game',type=Path,required=True)
    parser.add_argument('--ctl',type=Path,required=True)
    parser.add_argument('--create-jar',type=Path,required=True)
    args=parser.parse_args()
    scratch=Path(tempfile.mkdtemp(prefix='particle-smoke-',dir=ROOT/'.local'))
    resources=scratch/'resources'
    if os.uname().sysname=='Darwin':subprocess.run(['cp','-cR',str(args.resources.resolve()),str(resources)],check=True)
    else:shutil.copytree(args.resources,resources)
    (scratch/'horizon-mods.txt').write_text('mod.create:true\n')
    inputs=scratch/'horizon-mods/create-resources';inputs.mkdir(parents=True)
    shutil.copy2(args.create_jar,inputs/'create.jar')
    env=os.environ.copy()
    for key,folder in [('HORIZON_HOME','home'),('HORIZON_LAUNCHER_HOME','launcher'),('XDG_DATA_HOME','data'),('XDG_CONFIG_HOME','config'),('HORIZON_LAUNCHER_TRASH','trash'),('HORIZON_LAUNCHER_CLIPBOARD','clipboard'),('HORIZON_LAUNCHER_DESKTOP','desktop')]:env[key]=str(scratch/folder)
    env.update({'HORIZON_NO_AUDIO':'1','HORIZON_LAUNCHER_NO_SELF_UPDATE':'1',
                'CREATE_HORIZON_PARTICLE_TRACE':'1','CREATE_HORIZON_TRACE':'1'})
    socket=scratch/'control.sock';log_path=scratch/'game.log';transcript=[]
    def call(*words,timeout=120):
        reply=subprocess.run([str(args.ctl.resolve()),'--socket',str(socket),*map(str,words)],env=env,text=True,capture_output=True,timeout=timeout)
        if reply.returncode:raise RuntimeError(str(words)+': '+reply.stdout+reply.stderr)
        value=json.loads(reply.stdout);transcript.append({'command':list(map(str,words)),'reply':value});return value
    print('Particle scratch:',scratch,flush=True)
    with log_path.open('w') as log:
        process=subprocess.Popen([str(args.game.resolve()),'--resources',str(resources),'--world','ParticleReview','--seed','5','--creative','--render-distance','2','--control-socket',str(socket),'--offscreen'],cwd=scratch,env=env,stdout=log,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+180
            while True:
                if process.poll() is not None:raise RuntimeError(log_path.read_text()[-8000:])
                try:call('state',timeout=5);break
                except (RuntimeError,subprocess.TimeoutExpired):
                    if time.monotonic()>deadline:raise
                    time.sleep(.25)
            call('wait-ready',120,timeout=150)
            run(call,log_path,scratch)
        finally:
            (scratch/'transcript.json').write_text(json.dumps(transcript,indent=2)+'\n')
            if process.poll() is None:
                try:call('quit',timeout=30);process.wait(timeout=30)
                except (RuntimeError,subprocess.TimeoutExpired):process.terminate();process.wait(timeout=10)
            for temporary in (resources, scratch/'.horizon-cache', scratch/'horizon-mods'):
                shutil.rmtree(temporary, ignore_errors=True)


if __name__=='__main__':main()
