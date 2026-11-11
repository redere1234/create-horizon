// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT
// Actual Game CPU catalog/native-draw regression. The independent Java pose
// records and original model face counts are generated privately by
// tools/belt_render_oracle.py. No GPU/device or whole-client claim.
use super::*;
use crate::game::{Audio, Options, Progress, Settings, World, load_resources};
use horizon_client::{chunk::Chunk, containers::ModBlockEntityFields};
use std::{collections::BTreeMap, path::PathBuf, sync::Arc, time::Instant};

fn cyclic_quad_order(order: [usize; 4]) -> bool {
    order
        .iter()
        .enumerate()
        .all(|(index, &corner)| corner == (order[0] + index) % 4)
}

#[test]
#[ignore = "requires the player's original models and private Java pose records"]
fn belt_render_actual_game_mesh() {
    let work = PathBuf::from(std::env::var_os("CREATE_BELT_RENDER_PROBE").unwrap());
    let base = PathBuf::from(std::env::var_os("HORIZON_TEST_RESOURCES").unwrap());
    let source: serde_json::Value =
        serde_json::from_slice(&std::fs::read(work.join("source-frames.json")).unwrap()).unwrap();
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
    assert!(super::super::create_port::original_assets());
    for suffix in ["scroll", "diagonal_scroll"] {
        let names = std::iter::once(format!("belt_{suffix}")).chain(
            create_assets::BELT_DYES
                .iter()
                .map(|dye| format!("belt/{dye}_{suffix}")),
        );
        for name in names {
            let id = format!("create:gui/scrolling/{name}");
            let sprite = game.gui.atlas.sprites[&id];
            assert_eq!((sprite.w, sprite.h), (16, 32), "cropped scroll strip {id}");
        }
    }
    game.world = World::new(game.res.facts().air, 1);
    game.ticks = 10;
    game.world.game_time = 80_010;
    assert_eq!(game.visual_ticks(), 10);
    game.world
        .chunks
        .insert((0, 0), Arc::new(Chunk::empty(0, 0)));
    game.options.dedicated = Some(Vec::new());
    let mut counts = BTreeMap::new();
    for (name, expected) in source["face_counts"].as_object().unwrap() {
        let id = format!("create:block/belt/{name}");
        let baked = game.pack.render.model_catalog.standalone(&id).unwrap();
        assert_eq!(baked.faces.len() as u64, expected.as_u64().unwrap(), "{id}");
        counts.insert(name.clone(), baked.faces.len());
    }
    assert_eq!(counts["middle"] + counts["middle_bottom"], 14);
    assert_eq!(counts["diagonal_middle"], 32);
    let registry = game.pack.assets.registry;
    let belt = registry.default_state(ID).unwrap();
    let pos = [4, 70, 4];
    let mut frames = 0;
    let mut total_vertices = 0;
    let mut observed = Vec::new();
    for row in source["rows"].as_array().unwrap() {
        let rpm = row["rpm"].as_f64().unwrap() as f32;
        if row["part"] != "middle"
            || row["clock"] != 10
            || row["partial"] != 0.125
            || ![-32.0, 0.0, 32.0].contains(&rpm)
        {
            continue;
        }
        let mut state = registry.state(belt).unwrap().clone();
        for property in ["facing", "slope", "part"] {
            state
                .properties
                .insert(property.into(), row[property].as_str().unwrap().into());
        }
        let state = registry.id(&state).unwrap();
        game.world.set(pos[0], pos[1], pos[2], state).unwrap();
        let mut entity = ModBlockEntity::new(ModBlockEntityFields {
            id: ID.into(),
            ..Default::default()
        });
        entity.nbt.insert("Speed".into(), Tag::Float(rpm.to_bits()));
        entity.nbt.insert("IsController".into(), Tag::Byte(0));
        entity.nbt.insert("Length".into(), Tag::Int(6));
        entity.nbt.insert("Index".into(), Tag::Int(2));
        entity
            .nbt
            .insert("UnknownSibling".into(), Tag::String("retained".into()));
        let before = entity.nbt.clone();
        let revision = entity.revision();
        let mut output = BlockEntityDraw::posed(
            0.125,
            game.world.game_time,
            0xf0f0,
            pos,
            glam::Mat4::IDENTITY,
            (glam::Vec3::Y, glam::Vec3::Z),
            Vec::new(),
        );
        assert!(draw(&game, pos, &entity, &mut output));
        let vertices = output.into_vertices();
        let expected_frames = row["frames"].as_array().unwrap();
        let expected_count: usize = expected_frames
            .iter()
            .map(|frame| counts[frame["model"].as_str().unwrap()] * 4)
            .sum();
        assert_eq!(
            vertices.len(),
            expected_count,
            "middle surface omitted: {row}"
        );
        let mut offset = 0;
        for frame in expected_frames {
            let model = format!("create:block/belt/{}", frame["model"].as_str().unwrap());
            let baked = game.pack.render.model_catalog.standalone(&model).unwrap();
            let matrix: [f32; 16] =
                std::array::from_fn(|i| frame["matrix"][i].as_f64().unwrap() as f32);
            let source_pose = glam::Mat4::from_cols_array(&matrix);
            for face in &baked.faces {
                let emitted = &vertices[offset..offset + 4];
                let expected = face
                    .quad
                    .positions
                    .map(|point| source_pose.transform_point3(glam::Vec3::from_array(point)));
                // UV rectangle conversion may cyclically reorder a face; its
                // geometric winding and all four unique corners must survive.
                let mut matched = [false; 4];
                let mut corner_order = [0; 4];
                for (vertex_index, vertex) in emitted.iter().enumerate() {
                    let point = glam::Vec3::from_array(vertex.pos);
                    assert!(point.is_finite());
                    let index = expected
                        .iter()
                        .enumerate()
                        .find(|(index, wanted)| {
                            !matched[*index] && point.abs_diff_eq(**wanted, 1e-5)
                        })
                        .map(|(index, _)| index)
                        .expect("native vertex disagrees with the original Java pose");
                    matched[index] = true;
                    corner_order[vertex_index] = index;
                    let [u, mut v] = face.quad.uv[index];
                    let sprite = if frame["shifted"].as_bool().unwrap() {
                        v = v * 0.5 + frame["scroll"].as_f64().unwrap() as f32;
                        if row["slope"] == "upward" || row["slope"] == "downward" {
                            "create:gui/scrolling/belt_diagonal_scroll"
                        } else {
                            "create:gui/scrolling/belt_scroll"
                        }
                    } else {
                        face.quad.material.sprite.as_str()
                    };
                    let rect = game.gui.atlas.sprites[sprite];
                    let uv = [
                        rect.u0 + u * (rect.u1 - rect.u0),
                        rect.v0 + v * (rect.v1 - rect.v0),
                    ];
                    assert!(
                        glam::Vec2::from_array(vertex.uv)
                            .abs_diff_eq(glam::Vec2::from_array(uv), 1e-6)
                    );
                    assert_eq!(vertex.light, 0xf0f0);
                }
                assert!(
                    cyclic_quad_order(corner_order),
                    "native quad is not a winding-preserving cyclic reorder: {corner_order:?}"
                );
                let normal = |points: [glam::Vec3; 4]| {
                    (points[1] - points[0])
                        .cross(points[2] - points[0])
                        .normalize_or_zero()
                };
                let actual = std::array::from_fn(|i| glam::Vec3::from_array(emitted[i].pos));
                assert!(normal(actual).dot(normal(expected)) > 0.999);
                offset += 4;
            }
        }
        assert_eq!(offset, vertices.len());
        assert_eq!(entity.nbt, before, "draw changed canonical/unknown NBT");
        assert_eq!(entity.revision(), revision, "draw dirtied the entity");
        observed.push(serde_json::json!({
            "facing": row["facing"], "slope": row["slope"], "rpm": rpm,
            "vertices": vertices.len(),
        }));
        frames += 1;
        total_vertices += vertices.len();
    }
    assert_eq!(frames, 60);
    let result = serde_json::json!({
        "passed": true, "frames": frames, "vertices": total_vertices,
        "source_model_face_counts": counts, "observed": observed,
        "scope": "Actual Game imported middle meshes at all 20 orientations and 0/±32 RPM; original Java poses and scroll offsets, atlas dimensions, winding, and immutable NBT/revision.",
    });
    std::fs::write(
        work.join("native-mesh.json"),
        serde_json::to_vec_pretty(&result).unwrap(),
    )
    .unwrap();
    println!("BELT_RENDER_MESH_PROOF {result}");
}
