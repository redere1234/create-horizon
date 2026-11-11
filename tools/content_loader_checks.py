#!/usr/bin/env python3
"""Validate generated declarations with the selected real Horizon content loader.

This developer check creates an isolated private Cargo harness. Public portable
tests keep no dependency on a developer's local Horizon checkout. No client,
world, original assets or mod code executes; Content::read is the same parser
that accepts or refuses the pack before game registration.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from catalog import BLOCKS, INTERNAL_BLOCKS, ITEMS
from common import ROOT, environment

TESTS = r'''
#![cfg(test)]
use horizon_mods::{content::{Content, Rarity}, manifest::Manifest};
use std::path::Path;

fn load(path:&str)->Result<Content,String>{
 let path=Path::new(path);
 let manifest=Manifest::parse(&std::fs::read_to_string(path.join("horizon-mod.toml")).unwrap()).unwrap();
 Content::read(path,&manifest)
}

#[test]
fn every_public_declaration_is_accepted_by_the_actual_loader(){
 let loaded=load(@@PUBLIC@@).unwrap();
 let mut blocks:Vec<_>=loaded.blocks.iter().map(|b|b.id.as_str()).collect();blocks.sort();
 let mut items:Vec<_>=loaded.items.iter().map(|i|i.id.as_str()).collect();items.sort();
 assert_eq!(blocks,@@BLOCKS@@);assert_eq!(items,@@ITEMS@@);
 let cake=loaded.items.iter().find(|i|i.id=="create:creative_blaze_cake").unwrap();
 assert_eq!(cake.rarity,Some(Rarity::Epic));assert!(!cake.components.contains_key("minecraft:rarity"));
 let alias=loaded.items.iter().find(|i|i.id=="create:empty_blaze_burner").unwrap();
 assert_eq!(alias.place_block.as_deref(),Some("create:blaze_burner"));
 let goggles=loaded.items.iter().find(|i|i.id=="create:goggles").unwrap();
 assert_eq!(goggles.max_stack_size,Some(1));
 assert_eq!(goggles.components["minecraft:equippable"]["slot"],"head");
}

#[test]
fn exact_native_embedded_bundle_is_accepted_too(){
 let folder=load(@@PUBLIC@@).unwrap();let bundle=load(@@BUNDLE@@).unwrap();
 assert_eq!(folder.blocks,bundle.blocks);assert_eq!(folder.items,bundle.items);
 assert_eq!(folder.files,bundle.files);
}

#[test]
fn pre_regression_component_rarity_rejects_the_entire_pack(){
 let error=load(@@BAD@@).unwrap_err();
 assert!(error.contains("creative_blaze_cake.json")&&error.contains("set rarity instead"),"{error}");
}
'''


def run(horizon, target=None):
    horizon=Path(horizon).resolve()
    assert (horizon/'crates/horizon-mods/src/content.rs').is_file(),horizon
    work=Path(tempfile.mkdtemp(prefix='content-loader-',dir=ROOT/'.local'))
    public=work/'public';shutil.copytree(ROOT/'content',public)
    bundle=work/'embedded';bundle.mkdir()
    files=json.loads((ROOT/'mixins/create/data/content.json').read_text())
    for name,text in files.items():
        relative=Path(name);assert not relative.is_absolute() and '..' not in relative.parts,name
        path=bundle/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
    manifest=(public/'horizon-mod.toml').read_text()
    (bundle/'horizon-mod.toml').write_text(manifest)
    bad=work/'invalid-rarity';path=bad/'data/create/horizon/item/creative_blaze_cake.json';path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'template':'minecraft:iron_ingot','components':{'minecraft:rarity':'epic'}}))
    (bad/'horizon-mod.toml').write_text(manifest)
    (work/'src').mkdir()
    (work/'Cargo.toml').write_text('[package]\nname="create-content-loader-checks"\nversion="0.0.0"\nedition="2024"\n[workspace]\n[dependencies]\nhorizon-mods={path='+json.dumps(str(horizon/'crates/horizon-mods'))+'}\n')
    tests=TESTS
    for key,value in [('PUBLIC',str(public)),('BUNDLE',str(bundle)),('BAD',str(bad)),
        ('BLOCKS',sorted('create:'+v for v in BLOCKS+INTERNAL_BLOCKS)),('ITEMS',sorted('create:'+v for v in ITEMS))]:
        tests=tests.replace('@@'+key+'@@',json.dumps(value))
    (work/'src/lib.rs').write_text(tests)
    report={'passed':False,'scope':__doc__,'horizon':str(horizon),
        'horizon_revision':subprocess.check_output(['git','-C',str(horizon),'rev-parse','HEAD'],text=True).strip(),
        'actual_loader_sha256':hashlib.sha256((horizon/'crates/horizon-mods/src/content.rs').read_bytes()).hexdigest(),
        'native_bundle_sha256':hashlib.sha256((ROOT/'mixins/create/data/content.json').read_bytes()).hexdigest(),
        'expected_blocks':len(BLOCKS+INTERNAL_BLOCKS),'expected_items':len(ITEMS),'log':str(work/'cargo.log')}
    target=Path(target or ROOT/'.local/content-loader-target').resolve();target.relative_to((ROOT/'.local').resolve())
    env=environment();env['CARGO_TARGET_DIR']=str(target)
    print(json.dumps({'work':str(work),'target':str(target)}),flush=True)
    try:
        with (work/'cargo.log').open('w') as log:
            process=subprocess.run([str(ROOT/'.tools/rust/bin/cargo'),'test','--offline','--manifest-path',str(work/'Cargo.toml')],
                cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
        assert process.returncode==0,(process.returncode,str(work/'cargo.log'))
        report['passed']=True
    except BaseException as error:report['error']=repr(error);raise
    finally:
        (work/'result.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({'passed':report['passed'],'result':str(work/'result.json')}),flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--horizon',type=Path,required=True)
    parser.add_argument('--target',type=Path)
    args=parser.parse_args();run(args.horizon,args.target)
