#!/usr/bin/env python3
"""Test canonical Basin fluid NBT using Horizon's real bounded NBT codec.

Only this developer runner needs a local Horizon source checkout. It generates
a private Cargo project; public portable workspace tests have no such dependency.
An optional original-Java report tests the authored fixture's actual saved tags.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess

from common import HORIZON, ROOT, environment

TESTS = r'''#![allow(dead_code)]
#[path=@@CODEC@@] mod fluid_codec;
use create_engine::basin::Fluid;
use fluid_codec::*;
use horizon_world::nbt::{Compound,Limits,Tag,parse_snbt,write_network};

fn tag(s:&str)->Tag {let(t,n)=parse_snbt(s).unwrap();assert_eq!(n,s.len());t}
fn bytes(t:&Tag)->Vec<u8>{write_network(t,Limits::saved()).unwrap()}
fn half()->Tag {tag(r#"[{Level:{Speed:.25f,Target:0f,Value:0f,Force:1b},TankContent:{}},{Level:{Speed:.25f,Target:.5f,Value:.125f},TankContent:{Fluid:{amount:500,id:"minecraft:lava",components:{"!test:removed":{},"test:value":{x:42}}}}}]"#)}
fn water(n:u32)->Fluid<Key>{Fluid{key:Key{id:"minecraft:water".into(),components:Compound::new()},amount:n}}
fn c(t:&Tag)->&Compound{if let Tag::Compound(c)=t{c}else{panic!("compound")}}
fn list(t:&Tag)->&Vec<Tag>{if let Tag::List(l)=t{l}else{panic!("list")}}

#[test]fn unchanged_roundtrip_preserves_every_byte_and_component_patch(){
 let t=half();let tanks=read_half(Some(&t)).unwrap();assert!(tanks[0].is_none());
 let f=tanks[1].as_ref().unwrap();assert_eq!((f.key.id.as_str(),f.amount),("minecraft:lava",500));
 assert!(f.key.components.contains_key(&"!test:removed".into()));assert_eq!(bytes(&write_half(Some(&t),&tanks).unwrap()),bytes(&t));
}
#[test]fn changed_content_keeps_current_chaser_and_force_updates_only_target(){
 let t=half();let mut tanks=read_half(Some(&t)).unwrap();tanks[0]=Some(water(750));tanks[1].as_mut().unwrap().amount=250;
 let out=write_half(Some(&t),&tanks).unwrap();assert_eq!(read_half(Some(&out)).unwrap(),tanks);
 for(i,target,value)in[(0,0.75f32,0f32),(1,0.25f32,0.125f32)]{
  let l=c(c(&list(&out)[i]).get(&"Level".into()).unwrap());
  assert_eq!(l.get(&"Target".into()),Some(&Tag::Float(target.to_bits())));
  assert_eq!(l.get(&"Value".into()),Some(&Tag::Float(value.to_bits())));
  assert_eq!(l.get(&"Speed".into()),Some(&Tag::Float(0.25f32.to_bits())));
 }
 assert_eq!(c(c(&list(&out)[0]).get(&"Level".into()).unwrap()).get(&"Force".into()),Some(&Tag::Byte(1)));
 assert!(!c(c(&list(&out)[1]).get(&"Level".into()).unwrap()).contains_key(&"Force".into()));
 assert_eq!(read_half(Some(&out)).unwrap()[1].as_ref().unwrap().key.components,tanks[1].as_ref().unwrap().key.components);
 assert_eq!(bytes(&write_half(Some(&out),&tanks).unwrap()),bytes(&out));
}
#[test]fn drained_empty_is_canonical_empty_content(){
 let t=half();let out=write_half(Some(&t),&[None,None]).unwrap();
 assert!(c(c(&list(&out)[1]).get(&"TankContent".into()).unwrap()).is_empty());assert_eq!(read_half(Some(&out)).unwrap(),[None,None]);
}
#[test]fn canonical_server_level_ticks_preserve_tanks_and_force(){
 let mut t=half();let before=read_half(Some(&t)).unwrap();
 let levels=read_levels(Some(&t)).unwrap();
 let mut expected=create_engine::basin::FluidLevel{value:levels[1].value,target:levels[1].target,speed:levels[1].speed,..Default::default()};
 for _ in 0..7 {expected.tick();tick_half(&mut t).unwrap();}
 assert_eq!(read_half(Some(&t)).unwrap(),before);
 assert_eq!(read_levels(Some(&t)).unwrap()[1].value.to_bits(),expected.value.to_bits());
 assert!(read_levels(Some(&t)).unwrap()[0].force);
 let mut unsupported=tag("[]");let original=bytes(&unsupported);assert!(tick_half(&mut unsupported).is_err());assert_eq!(bytes(&unsupported),original);
}
#[test]fn unsupported_original_never_becomes_empty_or_partially_rewritten(){
 let canonical=half();let text=r#"[{Level:{Speed:.25f,Target:1f,Value:.5f},TankContent:{Fluid:{amount:1000,id:"minecraft:water"}}},{Level:{Speed:.25f,Target:0f,Value:0f},TankContent:{}}]"#;
 let cases=[text.replace("minecraft:water","test:unknown"),text.replace("amount:1000","amount:1001"),text.replace("amount:1000","amount:0"),text.replace("amount:1000","amount:1000s"),text.replace("id:","extra:1,id:"),text.replace("Fluid:{","extra:1,Fluid:{"),text.replace("Speed:.25f","Unknown:1,Speed:.25f"),text.replace("Speed:.25f","Speed:1"),text.replace("Value:.5f","Force:2b,Value:.5f"),text.replace("id:\"minecraft:water\"","id:\"minecraft:water\",components:1"),text.replace("Level:{","Unknown:1,Level:{")];
 for s in cases {let original=tag(&s);let before=bytes(&original);assert!(read_half(Some(&original)).is_err(),"{s}");assert!(write_half(Some(&original),&[Some(water(1)),None]).is_err());assert_eq!(bytes(&original),before);}
 for bad in [Tag::List(vec![]),Tag::List(vec![list(&canonical)[0].clone()]),Tag::Compound(Compound::new())]{assert!(read_half(Some(&bad)).is_err());}
 assert!(read_half(None).is_err());
}
#[test]fn reject_invalid_replacement_without_touching_original(){
 let t=half();let before=bytes(&t);for amount in [0,1001,u32::MAX]{assert!(write_half(Some(&t),&[Some(water(amount)),None]).is_err());}
 let mut f=water(1);f.key.id="test:unknown".into();assert!(write_half(Some(&t),&[Some(f),None]).is_err());assert_eq!(bytes(&t),before);
}
#[test]fn both_halves_preflight_before_canonical_commit(){
 let mut be=Compound::from([("InputTanks".into(),half()),("OutputTanks".into(),tag("[]")),("UnknownSibling".into(),Tag::Int(42))]);
 let before=bytes(&Tag::Compound(be.clone()));
 let proposed=(||{let i=write_half(be.get(&"InputTanks".into()),&[Some(water(1)),None])?;let o=write_half(be.get(&"OutputTanks".into()),&[None,None])?;Ok::<_,Unsupported>((i,o))})();
 if let Ok((i,o))=proposed{be.insert("InputTanks".into(),i);be.insert("OutputTanks".into(),o);}
 assert_eq!(bytes(&Tag::Compound(be)),before);
}
#[test]fn optional_empty_patch_and_unchanged_half_bytes_are_retained(){
 let t=tag(r#"[{Level:{Speed:.25f,Target:1f,Value:1f},TankContent:{Fluid:{amount:1000,id:"minecraft:water",components:{}}}},{Level:{Speed:.25f,Target:0f,Value:0f},TankContent:{}}]"#);
 assert_eq!(bytes(&write_half(Some(&t),&read_half(Some(&t)).unwrap()).unwrap()),bytes(&t));
}
#[test]fn authored_original_java_saved_tags_roundtrip(){
 let snapshots=@@SNAPSHOTS@@;
 for s in snapshots {let original=tag(s);let root=c(&original);for name in ["InputTanks","OutputTanks"]{let before=root.get(&name.into()).unwrap();let tanks=read_half(Some(before)).unwrap();assert_eq!(bytes(&write_half(Some(before),&tanks).unwrap()),bytes(before));}}
}
'''


def run(horizon, java_result=None):
    horizon = Path(horizon).resolve()
    work = ROOT / '.local/basin-fluid-codec'
    work.mkdir(parents=True, exist_ok=True)
    snapshots = []
    if java_result:
        report = json.loads(Path(java_result).read_text())
        if report.get('passed') is not True:
            raise ValueError('the original authored-fixture report must have passed')
        snapshots = [case[phase]['basin']['nbt'] for case in report['cases']
                     for phase in ['before', 'after']]
    (work / 'src').mkdir(exist_ok=True)
    (work / 'Cargo.toml').write_text('[package]\nname="basin-fluid-codec-checks"\nversion="0.0.0"\nedition="2024"\n'
                                   '[workspace]\n[dependencies]\n'
                                   'horizon-world={path=' + json.dumps(str(horizon / 'crates/horizon-world')) + '}\n'
                                   'create-engine={path=' + json.dumps(str(ROOT / 'mixins/create/engine')) + '}\n')
    references = '[' + ','.join(json.dumps(s) for s in snapshots) + ']'
    # A typed empty slice also works when no private Java reference is supplied.
    references = '&' + references + ' as &[&str]'
    (work / 'src/lib.rs').write_text(TESTS.replace('@@CODEC@@', json.dumps(str(ROOT / 'mixins/create/fluid_codec.rs')))
                                   .replace('@@SNAPSHOTS@@', references))
    env = environment()
    env['CARGO_TARGET_DIR'] = str(ROOT / '.local/basin-fluid-codec-target')
    command = [str(ROOT / '.tools/rust/bin/cargo'), 'test', '--offline', '--manifest-path', str(work / 'Cargo.toml')]
    completed = subprocess.run(command, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (work / 'checks.log').write_text(completed.stdout)
    match = re.search(r'test result: ok\. (\d+) passed;', completed.stdout)
    result = {'passed': completed.returncode == 0, 'tests': int(match[1]) if match else 0,
              'original_java_snapshots': len(snapshots), 'horizon': str(horizon),
              'horizon_revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=horizon, text=True).strip(),
              'scope': 'canonical tank NBT; no game/bucket/network/render acceptance'}
    (work / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(completed.stdout)
    print(json.dumps(result))
    return completed.returncode


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--horizon', type=Path, default=HORIZON)
    parser.add_argument('--java-result', type=Path)
    args = parser.parse_args()
    raise SystemExit(run(args.horizon, args.java_result))
