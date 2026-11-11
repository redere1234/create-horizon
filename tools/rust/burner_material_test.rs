// Copyright (c) 2026 create-horizon contributors; MIT.
// Actual Game CPU model/vertex proof; no window/device or rendered-pixel claim.
use super::*;
use crate::game::{Audio, Options, Progress, Settings, World, load_resources};
use horizon_client::{chunk::Chunk, containers::ModBlockEntityFields};
use horizon_world::nbt::{Compound, Tag};
use std::{collections::BTreeMap, path::PathBuf, sync::Arc, time::Instant};

fn posed() -> BlockEntityDraw {
    BlockEntityDraw::posed(
        0.375,
        1234,
        0xf0f0,
        [1, 70, 1],
        glam::Mat4::IDENTITY,
        (glam::Vec3::Y, glam::Vec3::Z),
        Vec::new(),
    )
}

fn prime(game: &Game<'_>, entity: &ModBlockEntity, facing: Direction, active: bool, above: bool) {
    reset();
    CLIENT.with(|cache| {
        let mut cache = cache.borrow_mut();
        cache.prepare(game);
        let entry = cache.entry([1, 70, 1], entity.revision(), facing, above);
        for _ in 0..60 {
            entry.animation.tick(active, facing, 0.0);
        }
        entry.phase = 0;
    });
}

#[test]
#[ignore = "requires private models and source public-material observation"]
fn burner_material_actual_game_vertices() {
    let work = PathBuf::from(std::env::var_os("CREATE_BURNER_MATERIAL_PROBE").unwrap());
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
    let source: serde_json::Value =
        serde_json::from_slice(&std::fs::read(work.join("source.json")).unwrap()).unwrap();
    let mut counts = BTreeMap::new();
    let mut model_rows = Vec::new();
    for part in source["models"]["parts"].as_array().unwrap() {
        let id = part["id"].as_str().unwrap();
        let model = game.pack.render.model_catalog.standalone(id).expect(id);
        assert_eq!(
            model.faces.len() as u64,
            part["quad_count"].as_u64().unwrap(),
            "source/native face count {id}"
        );
        assert!(
            model
                .faces
                .iter()
                .all(|face| face.quad.color.is_none_or(|c| c as u32 == u32::MAX))
        );
        counts.insert(id.to_owned(), model.faces.len() * 4);
        model_rows.push(serde_json::json!({"id":id,"faces":model.faces.len(),
            "native_shaded_faces":model.faces.iter().filter(|face|face.quad.shade).count()}));
    }
    let pos = [1, 70, 1];
    let registry = game.pack.assets.registry;
    let burner = registry.default_state("create:blaze_burner").unwrap();
    let basin = registry.default_state("create:basin").unwrap();
    let mut frames = 0;
    let mut vertices = 0;
    let mut off_vertices = 0;
    for (heat_name, heat) in [
        ("smouldering", Heat::Smouldering),
        ("fading", Heat::Fading),
        ("kindled", Heat::Kindled),
        ("seething", Heat::Seething),
    ] {
        for (facing_name, facing) in [
            ("north", Direction::North),
            ("south", Direction::South),
            ("east", Direction::East),
            ("west", Direction::West),
        ] {
            for above in [false, true] {
                let mut state = registry.state(burner).unwrap().clone();
                state.properties.insert("blaze".into(), heat_name.into());
                state.properties.insert("facing".into(), facing_name.into());
                let state = registry.id(&state).unwrap();
                game.world.set(1, 70, 1, state).unwrap();
                game.world
                    .set(1, 71, 1, if above { basin } else { game.res.facts().air })
                    .unwrap();
                game.world.block_entities.remove(&(1, 71, 1));
                if above {
                    game.world.block_entities.insert(
                        (1, 71, 1),
                        BlockEntity::Mod(Box::new(ModBlockEntity::new(ModBlockEntityFields {
                            id: "create:basin".into(),
                            ..Default::default()
                        }))),
                    );
                }
                for goggles in [false, true] {
                    for hat in [false, true] {
                        let mut entity = ModBlockEntity::new(ModBlockEntityFields {
                            id: "create:blaze_heater".into(),
                            ..Default::default()
                        });
                        // Source presence, including explicit zero, activates these cosmetics.
                        if goggles {
                            entity.nbt.insert("Goggles".into(), Tag::Byte(0));
                        }
                        if hat {
                            entity.nbt.insert("TrainHat".into(), Tag::Byte(0));
                        }
                        let before: Compound = entity.nbt.clone();
                        let revision = entity.revision();
                        let active = above && heat >= Heat::Fading;
                        prime(&game, &entity, facing, active, above);
                        let mut old = posed();
                        baseline_draw(&game, pos, state, &entity, &mut old);
                        let old = old.into_vertices();
                        prime(&game, &entity, facing, active, above);
                        let mut candidate = posed();
                        draw(&game, pos, state, &entity, &mut candidate);
                        let candidate = candidate.into_vertices();
                        let mut parts = vec![(rules::head_model(heat, active).path(), true)];
                        if goggles {
                            parts.push(("create:block/blaze_burner/goggles_small", true));
                        }
                        if hat {
                            parts.push(("create:entity/train_hat", true));
                        }
                        if heat >= Heat::Fading {
                            if heat == Heat::Seething {
                                parts.push((
                                    "create:block/blaze_burner/superheated_rods_small",
                                    false,
                                ));
                                parts.push((
                                    "create:block/blaze_burner/superheated_rods_large",
                                    false,
                                ));
                            } else {
                                parts.push(("create:block/blaze_burner/rods_small", false));
                                parts.push(("create:block/blaze_burner/rods_large", false));
                            }
                        }
                        if active {
                            parts.push(("create:block/blaze_burner/flame", false));
                        }
                        let total: usize = parts.iter().map(|(id, _)| counts[*id]).sum();
                        assert_eq!(old.len(), total);
                        assert_eq!(candidate.len(), total);
                        let mut offset = 0;
                        for (id, shaded) in parts {
                            let count = counts[id];
                            for (left, right) in old[offset..offset + count]
                                .iter()
                                .zip(&candidate[offset..offset + count])
                            {
                                assert_eq!(left.pos, right.pos, "pose {id}");
                                assert_eq!(left.uv, right.uv, "uv {id}");
                                assert_eq!(left.layer, right.layer, "material/sprite {id}");
                                assert_eq!(left.color, right.color, "color {id}");
                                assert_eq!(left.light, right.light, "light {id}");
                                assert_eq!(right.light, 0xf0f0);
                                if shaded {
                                    assert_eq!(left.normal, right.normal, "JSON normal {id}");
                                    assert_eq!(left.glint_uv, right.glint_uv, "JSON normal {id}");
                                    assert!(right.normal != [0; 4] || right.glint_uv != [0.0; 2]);
                                } else {
                                    assert!(left.normal != [0; 4] || left.glint_uv != [0.0; 2]);
                                    assert_eq!(right.normal, [0; 4], "OBJ diffuse disabled {id}");
                                    assert_eq!(
                                        right.glint_uv, [0.0; 2],
                                        "OBJ diffuse disabled {id}"
                                    );
                                    off_vertices += 1;
                                }
                            }
                            offset += count;
                        }
                        assert_eq!(entity.nbt, before);
                        assert_eq!(entity.revision(), revision);
                        frames += 1;
                        vertices += total;
                    }
                }
            }
        }
    }
    assert_eq!(frames, 128);
    assert!(off_vertices > 0);
    let result = serde_json::json!({"frames":frames,"vertices":vertices,"off_vertices":off_vertices,
        "models":model_rows,"scope":"Actual Game CPU model catalog/native draw vertices; no GPU pixel claim"});
    std::fs::write(
        work.join("native.json"),
        serde_json::to_vec_pretty(&result).unwrap(),
    )
    .unwrap();
    println!("BURNER_MATERIAL_PROOF {result}");
}
