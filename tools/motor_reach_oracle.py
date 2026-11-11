#!/usr/bin/env python3
"""Source motor admission boundary against the cached original Minecraft AABB.

No game is started. The complete Rust adapter runs with a small acting-player
context; actual Horizon player swapping/dimension integration needs native checks.
Player.canInteractWithBlock bytecode and Create's maxRange/Adventure policy are
verified before comparing independently supplied eyes, attributes and permissions.
"""
import json
from pathlib import Path
import random
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]

JAVA = r'''
import java.io.*;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;
public class MotorReachOracle {
 public static void main(String[] args) throws Exception {
  var reader = new BufferedReader(new InputStreamReader(System.in));
  for (String line; (line=reader.readLine())!=null;) {
   String[] v=line.split(" ");
   double x=Double.parseDouble(v[0]),y=Double.parseDouble(v[1]),z=Double.parseDouble(v[2]);
   int bx=Integer.parseInt(v[3]),by=Integer.parseInt(v[4]),bz=Integer.parseInt(v[5]);
   double reach=Double.parseDouble(v[6])+@@EXTRA@@;
   var box=new AABB(bx,by,bz,(double)bx+1,(double)by+1,(double)bz+1);
   boolean allowed=v[7].equals("1") && v[8].equals("0") && v[9].equals("1");
   System.out.println(allowed && box.distanceToSqr(new Vec3(x,y,z)) < reach*reach);
  }
 }
}
'''

# This context supplies arbitrary real-player values to the unchanged complete
# adapter, so hardcoded mode/range/height substitutions fail the same cases.
RUST_CONTEXT = r'''
mod game {
 pub struct Game<'a> {pub eye:[f64;3],pub reach:f64,pub build:bool,pub spectate:bool,pub present:bool,pub marker:std::marker::PhantomData<&'a ()>}
 impl Game<'_> {
  pub fn native_as_player(&mut self,id:u128,f:impl FnOnce(&mut Self))->bool {if !self.present || id!=1 {false} else {f(self);true}}
  pub fn spectator(&self)->bool {self.spectate}
  pub fn may_build(&self)->bool {self.build}
  pub fn eye_position(&self)->Option<[f64;3]> {Some(self.eye)}
  pub fn interaction_range(&mut self,key:&str,_:f64,_:f64)->f64 {assert_eq!(key,"minecraft:block_interaction_range");self.reach}
 }
 pub mod adapter { @@ADAPTER@@ }
 pub fn allows(game:&mut Game<'_>,pos:[i32;3])->bool {game.create_motor_configuration_allowed(1,pos)}
}
fn main() {
 use std::io::BufRead;
 for line in std::io::stdin().lock().lines() {
  let line=line.unwrap();let v:Vec<&str>=line.split_whitespace().collect();
  let mut game=game::Game{eye:[v[0].parse().unwrap(),v[1].parse().unwrap(),v[2].parse().unwrap()],reach:v[6].parse().unwrap(),build:v[7]=="1",spectate:v[8]=="1",present:v[9]=="1",marker:std::marker::PhantomData};
  println!("{}",game::allows(&mut game,[v[3].parse().unwrap(),v[4].parse().unwrap(),v[5].parse().unwrap()]));
 }
}
'''


def main():
    pins = json.loads((ROOT / 'compatibility.json').read_text())
    manifest = json.loads((ROOT / '.local/java-reference/manifest.json').read_text())
    java = Path(manifest['java']) / 'bin'
    classpath = ':'.join(manifest['classpath'])
    source = subprocess.check_output(['git', 'show', pins['create_revision'] +
        ':src/main/java/com/simibubi/create/foundation/networking/BlockEntityConfigurationPacket.java'],
        cwd=ROOT.parent / 'Create', text=True)
    match = re.search(r'protected int maxRange\(\)\s*\{\s*return (\d+);\s*\}', source)
    assert match and 'AdventureUtil.isAdventure(player)' in source
    assert 'player.canInteractWithBlock(this.pos, maxRange())' in source
    extra = int(match[1])
    bytecode = subprocess.check_output([str(java / 'javap'), '-classpath', classpath,
        '-c', 'net.minecraft.world.entity.player.Player'], text=True)
    method = bytecode.split('public boolean canInteractWithBlock(')[1].split('\n  public ')[0]
    for required in ('blockInteractionRange', 'dadd', 'getEyePosition', 'AABB.distanceToSqr', 'dmul', 'dcmpg', 'ifge'):
        assert required in method, (required, method)
    work = ROOT / '.local/motor-reach-oracle'
    work.mkdir(parents=True, exist_ok=True)
    (work / 'player-reach-bytecode.txt').write_text(method)
    original = work / 'MotorReachOracle.java'
    original.write_text(JAVA.replace('@@EXTRA@@', str(extra)))
    subprocess.run([str(java / 'javac'), '--release', '21', '-proc:none', '-classpath', classpath,
        '-d', str(work), str(original)], check=True)
    rust = work / 'probe.rs'
    rust.write_text(RUST_CONTEXT.replace('@@ADAPTER@@', (ROOT / 'mixins/create/motor_reach.rs').read_text()))
    probe = work / 'probe'
    subprocess.run([str(ROOT / '.tools/rust/bin/rustc'), '--edition=2024', '-Dwarnings',
        str(rust), '-o', str(probe)], check=True)
    cases = []

    def case(eye, pos=(0, 0, 0), reach=4.5, build=1, spectator=0, present=1):
        cases.append([*eye, *pos, reach, build, spectator, present])

    # Include exact strict boundaries, the former 8-block rejection, the AABB
    # versus center distinction, custom attribute ranges and pose/scale eyes.
    for reach in (0, 1, 4.5, 5, 12, 64):
        limit = reach + extra
        for delta in (-1e-9, 0, 1e-9):
            case((1 + limit + delta, .5, .5), reach=reach)
    case((10, 1.62, .5))
    case((25.4, .5, .5))
    for height in (1.62, 1.27, .4, 3.24):
        case((.5, height, .5), pos=(0, 27, 0))
    for build, spectator, present in ((0, 0, 1), (0, 1, 1), (1, 1, 1), (1, 0, 0)):
        case((.5, .5, .5), build=build, spectator=spectator, present=present)
    rng = random.Random(6010)
    for _ in range(8000):
        pos = tuple(rng.randint(-30_000_000, 30_000_000) for _ in range(3))
        reach = rng.choice((0, 4.5, 5, 12, 64))
        eye = tuple(pos[i] + rng.uniform(-100, 100) for i in range(3))
        case(eye, pos, reach, rng.randrange(2), rng.randrange(2), rng.randrange(2))
    data = ''.join(' '.join(map(str, row)) + '\n' for row in cases)
    expected = subprocess.check_output([str(java / 'java'), '-classpath', str(work) + ':' + classpath,
        'MotorReachOracle'], input=data, text=True).splitlines()
    actual = subprocess.check_output([str(probe)], input=data, text=True).splitlines()
    assert len(expected) == len(actual) == len(cases), (len(expected), len(actual), len(cases))
    for row, a, b in zip(cases, actual, expected):
        assert a == b, (row, a, b)
    report = {'cases': len(cases), 'passed': True, 'create_revision': pins['create_revision'],
        'minecraft': manifest['minecraft'], 'extra_range': extra,
        'scope': 'unchanged full Rust adapter in acting-player context versus actual original AABB; Player bytecode and Create policy verified; no native world/dimension integration claim'}
    (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
