// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT
// Actual registered Game/provider + CPU widget fixture. No window/device.
use super::*;
use crate::game::{Audio, Options, Progress, Settings, World, load_resources};
use horizon_client::{chunk::Chunk, containers::ModBlockEntityFields, items::ItemStack};
use std::{path::PathBuf, sync::Arc, time::Instant};

#[test]
#[ignore = "requires private resources and source-oracle inputs"]
fn kinetic_goggles_actual_game_source_inputs() {
    let work = PathBuf::from(std::env::var_os("CREATE_GOGGLES_PROBE").unwrap());
    let base = PathBuf::from(std::env::var_os("HORIZON_TEST_RESOURCES").unwrap());
    let mut settings = Settings::default();
    settings.mods.enabled.insert("create".into());
    crate::game::mods::register_components(&base).unwrap();
    crate::game::mods::register_standalone_models();
    let root = crate::game::mods::content_root(&base, &settings.mods.enabled, &[]);
    let loaded = load_resources(
        root.clone(),
        None,
        &base,
        &settings,
        Instant::now(),
        false,
        false,
        &Progress::new(),
        &mut |_, _| unreachable!(),
    )
    .unwrap();
    let mut options = Options::parse(std::iter::empty()).unwrap().unwrap();
    options.resources = root.clone();
    options.execution_role = crate::game::execution_role::ExecutionRole::IntegratedServer;
    let mut game = Game::new(
        &loaded.resources,
        loaded.pack,
        loaded.gui.unwrap(),
        options,
        settings,
        Audio::silent(&root),
        None,
    )
    .unwrap();
    game.world = World::new(game.res.facts().air, 1);
    game.world
        .chunks
        .insert((0, 0), Arc::new(Chunk::empty(0, 0)));
    game.options.dedicated = Some(Vec::new());
    let pos = [1, 70, 1];
    let words: Vec<serde_json::Value> =
        serde_json::from_slice(&std::fs::read(work.join("words.json")).unwrap()).unwrap();
    let cases: Vec<serde_json::Value> =
        serde_json::from_slice(&std::fs::read(work.join("cases.json")).unwrap()).unwrap();
    let mut rows = Vec::new();
    let mut widths = Vec::new();
    let mut widget_vertices = 0;
    for locale in ["en_us", "ru_ru"] {
        let source = work.join("languages");
        let language = horizon_client::lang::Language::load(&[&source], locale);
        let (_, misses) = horizon_client::lang::scoped(language, || {
            for word in words.iter().filter(|w| w["locale"] == locale) {
                widths.push(serde_json::json!({"locale":locale,"encoded":word["encoded"],"width":game.gui.atlas.font.width(word["text"].as_str().unwrap()).ceil() as i32}));
            }
            for case in cases.iter().filter(|c| c["locale"] == locale) {
                let block = format!("create:{}", case["block"].as_str().unwrap());
                let state = game.pack.assets.registry.default_state(&block).unwrap();
                game.world.set(pos[0], pos[1], pos[2], state).unwrap();
                let rpm = case["rpm"]
                    .as_f64()
                    .unwrap_or_else(|| case["rpm"].as_str().unwrap().parse().unwrap())
                    as f32;
                let overload = case["overload"].as_bool().unwrap();
                let frozen = case["frozen"].as_bool().unwrap();
                let goggles = case["goggles"].as_bool().unwrap();
                game.clock.set_frozen(frozen);
                game.armor[0] = goggles.then(|| ItemStack::new("create:goggles", 1));
                let mut nbt = Compound::from([
                    (
                        "Speed".into(),
                        Tag::Float((if overload { 0.0f32 } else { rpm }).to_bits()),
                    ),
                    (
                        "create_horizon".into(),
                        Tag::compound([("TheoreticalSpeed", Tag::Float(rpm.to_bits()))]),
                    ),
                    ("UnknownSibling".into(), Tag::ByteArray(vec![0x37; 4096])),
                ]);
                if overload {
                    nbt.insert("NetworkStatus".into(), Tag::String("Overstressed".into()));
                }
                let entity = crate::containers::ModBlockEntity::new(ModBlockEntityFields {
                    id: block.clone(),
                    nbt,
                    items: vec![None; 3],
                    data: vec![1, 2],
                });
                let before = (
                    entity.nbt.clone(),
                    entity.items.clone(),
                    entity.data.clone(),
                    entity.revision(),
                );
                game.world
                    .block_entities
                    .insert((pos[0], pos[1], pos[2]), BlockEntity::Mod(Box::new(entity)));
                let BlockEntity::Mod(entity) =
                    &game.world.block_entities[&(pos[0], pos[1], pos[2])]
                else {
                    unreachable!()
                };
                let equipped = game.armor[0]
                    .as_ref()
                    .is_some_and(|s| s.item.as_ref() == "create:goggles");
                let lines = providers(&game, pos, &block, &entity.nbt, equipped);
                let components: Vec<_> = lines.iter().map(|line|serde_json::json!({"text":line.plain(),"width":game.gui.atlas.font.width_text(line),"component":line.component()})).collect();
                let count = lines.len();
                if goggles {
                    assert_eq!(
                        lines[0].plain(),
                        format!("    {}", tr("gui.goggles.kinetic_stats").plain())
                    );
                    let impact = if block == "create:mechanical_mixer" {
                        4.0
                    } else {
                        8.0
                    };
                    assert!(
                        lines[2]
                            .plain()
                            .contains(&numeral(f64::from(impact * rpm.abs())).plain())
                    );
                }
                let warning = overload
                    || (!frozen
                        && rpm != 0.0
                        && (rpm.is_nan()
                            || (block == "create:mechanical_mixer" && rpm.abs() < 30.0)));
                if !goggles && !warning {
                    assert!(lines.is_empty());
                }
                if goggles && !warning {
                    assert_eq!(count, 3);
                }
                if warning {
                    let title = if overload {
                        tr("gui.stressometer.overstressed")
                    } else {
                        tr("tooltip.speedRequirement")
                    };
                    assert_eq!(
                        lines[if goggles { 4 } else { 0 }].plain(),
                        format!("    {}", title.plain())
                    );
                    if goggles {
                        assert!(lines[3].plain().is_empty());
                    }
                }
                if !lines.is_empty() {
                    let tooltip = tooltip(&game, lines, [340.0, 180.0], [640.0, 360.0]);
                    assert!(tooltip.width > 0.0 && tooltip.x >= 4.0 && tooltip.y >= 4.0);
                    let mut batch = HudBatch::new([2560, 1440]);
                    background(&game, &mut batch, &tooltip, 0.0, 1.0);
                    let mut y = tooltip.y;
                    for (i, line) in tooltip.lines.iter().enumerate() {
                        batch.text_styled(
                            &game.gui.atlas,
                            line,
                            tooltip.x,
                            y,
                            rgba(255, 255, 255, 255),
                            true,
                        );
                        if i + 1 == tooltip.title_lines {
                            y += 2.0;
                        }
                        y += 10.0;
                    }
                    assert!(!batch.vertices.is_empty());
                    widget_vertices += batch.vertices.len();
                }
                assert_eq!(
                    (
                        entity.nbt.clone(),
                        entity.items.clone(),
                        entity.data.clone(),
                        entity.revision()
                    ),
                    before
                );
                assert!(entity.revision().same_entity(before.3));
                rows.push(serde_json::json!({"id":case["id"],"lines":components}));
            }
        });
        assert!(
            misses.is_empty(),
            "Missing private source language keys: {misses:?}"
        );
    }
    std::fs::write(work.join("native.json"), serde_json::to_vec(&rows).unwrap()).unwrap();
    std::fs::write(
        work.join("widths.json"),
        serde_json::to_vec(&widths).unwrap(),
    )
    .unwrap();
    let old: Vec<serde_json::Value> =
        serde_json::from_slice(&std::fs::read(work.join("legacy.json")).unwrap()).unwrap();
    let mut legacy = Vec::new();
    for case in old {
        let locale = case["language"].as_str().unwrap();
        let language = horizon_client::lang::Language::load(&[&work.join("languages")], locale);
        let (output, misses) = horizon_client::lang::scoped(language, || {
            let block = case["block"].as_str().unwrap();
            let state = game.pack.assets.registry.default_state(block).unwrap();
            game.world.set(pos[0], pos[1], pos[2], state).unwrap();
            game.clock.set_frozen(false);
            let nbt = Compound::from([
                ("Speed".into(), Tag::Float(128.0f32.to_bits())),
                ("ScrollValue".into(), Tag::Int(128)),
                ("Capacity".into(), Tag::Float(2_097_152.0f32.to_bits())),
                ("Stress".into(), Tag::Float(1024.0f32.to_bits())),
            ]);
            let entity = crate::containers::ModBlockEntity::new(ModBlockEntityFields {
                id: block.into(),
                nbt,
                ..Default::default()
            });
            game.world
                .block_entities
                .insert((pos[0], pos[1], pos[2]), BlockEntity::Mod(Box::new(entity)));
            let BlockEntity::Mod(e) = &game.world.block_entities[&(pos[0], pos[1], pos[2])] else {
                unreachable!()
            };
            let lines = providers(&game, pos, block, &e.nbt, true);
            let max_width = lines
                .iter()
                .map(|line| game.gui.atlas.font.width_text(line))
                .fold(0.0, f32::max);
            let height = 8.0
                + if lines.len() > 1 {
                    2.0 + (lines.len() - 1) as f32 * 10.0
                } else {
                    0.0
                };
            let anchor = [
                340.0f32.min(640.0 - max_width - 20.0),
                180.0f32.min(360.0 - height - 20.0),
            ];
            let tooltip = tooltip(&game, lines, anchor, [640.0, 360.0]);
            serde_json::json!({"anchor":anchor,"tooltip":[tooltip.x,tooltip.y,tooltip.width,tooltip.height],
                "lines":tooltip.lines.iter().map(|line|serde_json::json!({"text":line.plain(),"width":game.gui.atlas.font.width_text(line),"component":line.component()})).collect::<Vec<_>>()})
        });
        assert!(misses.is_empty(), "Legacy language keys: {misses:?}");
        legacy.push(output);
    }
    std::fs::write(
        work.join("native-legacy.json"),
        serde_json::to_vec(&legacy).unwrap(),
    )
    .unwrap();
    println!(
        "GOGGLES_PROVIDER_PROOF {{\"cases\":{},\"widget_vertices\":{widget_vertices}}}",
        rows.len()
    );
}
