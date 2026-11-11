// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT
// Authored native method fixtures; no original assets or implementation copied.
use super::*;
use crate::game::{Audio, Options, Progress, Settings, World, load_resources};
use horizon_client::{chunk::Chunk, containers::ModBlockEntityFields};
use horizon_core::position::BlockPos;
use std::{hint::black_box, path::PathBuf, sync::Arc, time::Instant};

fn fixture(len: usize, variant: usize, payload: usize) -> ModBlockEntity {
    let mut entity = ModBlockEntity::new(ModBlockEntityFields {
        id: ID.into(),
        ..Default::default()
    });
    initialize(&mut entity);
    entity.items = (0..len)
        .map(|i| {
            if i % 4 == 2 {
                return None;
            }
            let mut stack = ItemStack::new(
                if i % 2 == 0 {
                    "minecraft:copper_ingot"
                } else {
                    "create:zinc_ingot"
                },
                if i % 5 == 0 { 0 } else { (i * 7 % 65) as u32 },
            );
            stack.damage = i as u32;
            stack.data_mut().set_other(
                "example:opaque",
                Some(Tag::compound([
                    ("slot", Tag::Int(i as i32)),
                    ("payload", Tag::ByteArray(vec![i as u8; 32])),
                ])),
            );
            if i % 3 == 0 {
                stack.data_mut().set_other(
                    "!minecraft:max_stack_size",
                    Some(Tag::Compound(Compound::new())),
                );
            } else if i % 3 == 1 {
                stack.data_mut().set_other(
                    "minecraft:max_stack_size",
                    Some(Tag::Double(16.75f64.to_bits())),
                );
            }
            Some(stack)
        })
        .collect();
    entity.nbt.insert(
        "UnrecognizedRoot".into(),
        Tag::ByteArray(vec![0x5a; payload]),
    );
    match variant {
        0 => {}
        1 => {
            entity.nbt.remove(&"InputTanks".into());
            entity.nbt.remove(&"OutputTanks".into());
        }
        2 | 3 => {
            let components = if variant == 3 {
                Compound::from([
                    ("!example:removed".into(), Tag::Compound(Compound::new())),
                    (
                        "example:opaque".into(),
                        Tag::compound([("long", Tag::Long(77))]),
                    ),
                ])
            } else {
                Compound::new()
            };
            for (half, id) in [
                ("InputTanks", "minecraft:water"),
                ("OutputTanks", "minecraft:lava"),
            ] {
                let tanks = [
                    Some(rules::Fluid {
                        key: fluids::Key {
                            id: id.into(),
                            components: components.clone(),
                        },
                        amount: 777,
                    }),
                    None,
                ];
                let mut encoded = fluids::write_half(Some(&empty_tanks()), &tanks).unwrap();
                if let Tag::List(segments) = &mut encoded {
                    if let Tag::Compound(s) = &mut segments[0] {
                        if let Some(Tag::Compound(level)) = s.get_mut(&"Level".into()) {
                            for key in ["Value", "Target"] {
                                level.insert(key.into(), Tag::Float((777.0f32 / 1000.0).to_bits()));
                            }
                        }
                    }
                }
                entity.nbt.insert(half.into(), encoded);
            }
        }
        4 => {
            entity.nbt.insert("InputTanks".into(), Tag::Int(4));
        }
        5 => {
            entity.nbt.insert(
                "Filter".into(),
                Tag::compound([("id", Tag::String("minecraft:stone".into()))]),
            );
        }
        6 => {
            entity
                .nbt
                .get_mut(&"InputItems".into())
                .unwrap()
                .get_mut("Size")
                .map(|v| *v = Tag::Int(8));
        }
        7 => {
            entity
                .nbt
                .get_mut(&"OutputItems".into())
                .unwrap()
                .get_mut("Size")
                .map(|v| *v = Tag::Byte(8));
        }
        8 => {
            entity
                .nbt
                .insert("Overflow".into(), Tag::List(vec![Tag::Int(1)]));
        }
        9 => {
            if let Some(Tag::Compound(v)) = entity.nbt.get_mut(&"InputItems".into()) {
                v.remove(&"Size".into());
            }
        }
        10 => {
            entity
                .nbt
                .get_mut(&"InputItems".into())
                .unwrap()
                .get_mut("Size")
                .map(|v| *v = Tag::String("opaque".into()));
        }
        11 => {
            entity
                .nbt
                .get_mut(&"OutputItems".into())
                .unwrap()
                .get_mut("Size")
                .map(|v| *v = Tag::Int(8));
        }
        _ => unreachable!(),
    }
    entity
}
fn snapshot(
    e: &ModBlockEntity,
) -> (
    String,
    Compound,
    Vec<Option<ItemStack>>,
    Vec<i32>,
    ModRevision,
) {
    (
        e.id.clone(),
        e.nbt.clone(),
        e.items.clone(),
        e.data.clone(),
        e.revision(),
    )
}
fn render(
    game: &Game<'_>,
    pos: Pos,
    entity: &ModBlockEntity,
    candidate: bool,
) -> Vec<crate::mesher::Vertex> {
    let mut draw = BlockEntityDraw::posed(
        0.375,
        1234,
        0xf0f0,
        pos,
        glam::Mat4::IDENTITY,
        (glam::Vec3::Y, glam::Vec3::Z),
        Vec::new(),
    );
    assert!(if candidate {
        perf_candidate_draw(game, pos, entity, &mut draw)
    } else {
        perf_baseline_draw(game, pos, entity, &mut draw)
    });
    draw.into_vertices()
}
fn measure<T>(f: impl Fn() -> T) -> ([u64; 5], u64, u64) {
    for _ in 0..4 {
        black_box(f());
    }
    PERF_ALLOCS.store(0, std::sync::atomic::Ordering::Relaxed);
    PERF_BYTES.store(0, std::sync::atomic::Ordering::Relaxed);
    PERF_RECORD.set(true);
    black_box(f());
    PERF_RECORD.set(false);
    let allocation = PERF_ALLOCS.load(std::sync::atomic::Ordering::Relaxed);
    let bytes = PERF_BYTES.load(std::sync::atomic::Ordering::Relaxed);
    let mut samples = [0; 5];
    for sample in &mut samples {
        let now = Instant::now();
        for _ in 0..32 {
            black_box(f());
        }
        *sample = now.elapsed().as_nanos() as u64 / 32;
    }
    (samples, allocation, bytes)
}
fn emit<T>(operation: &str, path: &str, payload: usize, f: impl Fn() -> T) {
    let (samples, allocs, bytes) = measure(f);
    let mut sorted = samples;
    sorted.sort_unstable();
    println!(
        "BASIN_PERF_SAMPLE {{\"operation\":{operation:?},\"path\":{path:?},\"root_payload_bytes\":{payload},\"allocations\":{allocs},\"allocated_bytes\":{bytes},\"median_ns\":{},\"samples_ns\":{samples:?}}}",
        sorted[2]
    );
}

#[test]
#[ignore = "requires the private owned resource copy"]
fn basin_read_perf_actual_game() {
    let base = PathBuf::from(std::env::var_os("HORIZON_TEST_RESOURCES").unwrap());
    let mut settings = Settings::default();
    settings.mods.enabled.insert("create".into());
    crate::game::mods::register_components(&base).unwrap();
    crate::game::mods::register_standalone_models();
    let root = crate::game::mods::content_root(&base, &settings.mods.enabled, &[]);
    // Load normal CPU model/atlas resources. The server-headless resource path
    // intentionally omits models; no window, renderer/device or GPU is created.
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
    let point = BlockPos {
        x: pos[0],
        y: pos[1],
        z: pos[2],
    };
    let state = game.pack.assets.registry.default_state(ID).unwrap();
    game.world.set(pos[0], pos[1], pos[2], state).unwrap();
    let mut cases = 0;
    let mut geometry_cases = 0;
    let mut geometry_vertices = 0;
    for len in [0, 1, 8, 9, 10, 17, 18, 19, 24] {
        for variant in 0..12 {
            reset(false);
            let entity = fixture(len, variant, 4096);
            let before = snapshot(&entity);
            game.world
                .block_entities
                .insert((pos[0], pos[1], pos[2]), BlockEntity::Mod(Box::new(entity)));
            let old = perf_baseline_read(&game, pos);
            let candidate = perf_candidate_read(&game, pos);
            assert_eq!(old, candidate, "read len{len} variant{variant}");
            if matches!(variant, 4 | 5 | 6 | 8 | 11) {
                assert!(candidate.is_none(), "required rejection variant{variant}");
            } else {
                assert!(candidate.is_some());
            }
            if let Some(b) = candidate.as_ref() {
                assert!(b.input[0].is_none(), "zero count must stay empty");
                if len > 3 {
                    assert_eq!(b.input[3].as_ref().unwrap().maximum, 1);
                }
                if len > 1 {
                    assert_eq!(b.input[1].as_ref().unwrap().maximum, 16);
                }
                if len > 9 {
                    assert_eq!(b.output[0].as_ref().unwrap().key.0.count, 1);
                    assert_eq!(b.output[0].as_ref().unwrap().count, 63);
                }
            }
            if matches!(variant, 2 | 3) {
                let b = candidate.as_ref().unwrap();
                assert_eq!(b.input_fluids[0].as_ref().unwrap().amount, 777);
                assert_eq!(
                    b.input_fluids[0].as_ref().unwrap().key.id,
                    "minecraft:water"
                );
                assert_eq!(
                    b.output_fluids[0].as_ref().unwrap().key.id,
                    "minecraft:lava"
                );
                assert_eq!(
                    b.input_fluids[0]
                        .as_ref()
                        .unwrap()
                        .key
                        .components
                        .is_empty(),
                    variant == 2
                );
            }
            game.with_level(|_, level, _| {
                let (mut a, mut b) = (-1, -1);
                perf_baseline_analog(level, point, state, &mut a);
                perf_candidate_analog(level, point, state, &mut b);
                assert_eq!(a, b, "analog len{len} variant{variant}");
                if matches!(variant, 6 | 11) {
                    assert_eq!(b, 0);
                }
            });
            let BlockEntity::Mod(entity) = &game.world.block_entities[&(pos[0], pos[1], pos[2])]
            else {
                unreachable!()
            };
            let old = render(&game, pos, entity, false);
            let candidate = render(&game, pos, entity, true);
            assert_eq!(
                bytemuck::cast_slice::<_, u8>(&old),
                bytemuck::cast_slice::<_, u8>(&candidate),
                "draw len{len} variant{variant}"
            );
            if len >= 9 {
                assert!(
                    !old.is_empty(),
                    "actual known item geometry must be submitted"
                );
            }
            geometry_cases += 1;
            geometry_vertices += old.len();
            assert_eq!(
                snapshot(entity),
                before,
                "live BE mutated len{len} variant{variant}"
            );
            assert!(entity.revision().same_entity(before.4));
            cases += 1;
        }
    }
    // Exact output-half exclusion and malformed-facing behavior are independent
    // of equality between old and candidate functions.
    let mut entity = fixture(18, 0, 0);
    entity.items.fill(None);
    entity.items[9] = Some(ItemStack::new("minecraft:copper_ingot", 64));
    game.world
        .block_entities
        .insert((pos[0], pos[1], pos[2]), BlockEntity::Mod(Box::new(entity)));
    game.with_level(|_, level, _| {
        let mut analog = -1;
        perf_candidate_analog(level, point, state, &mut analog);
        assert_eq!(analog, 0);
    });
    let mut desc = game.pack.assets.registry.state(state).unwrap().clone();
    desc.properties.insert("facing".into(), "north".into());
    let north = game.pack.assets.registry.id(&desc).unwrap();
    game.world.set(pos[0], pos[1], pos[2], north).unwrap();
    assert!(perf_baseline_read(&game, pos).is_none());
    assert!(perf_candidate_read(&game, pos).is_none());
    game.world.set(pos[0], pos[1], pos[2], state).unwrap();
    game.world.block_entities.remove(&(pos[0], pos[1], pos[2]));
    assert!(perf_baseline_read(&game, pos).is_none());
    assert!(perf_candidate_read(&game, pos).is_none());
    // Full real read includes the unchanged strict tank path and owned stack
    // keys; their remaining allocations are intentionally included.
    for payload in [0, 4096, 1 << 20] {
        let entity = fixture(18, 3, payload);
        let before = snapshot(&entity);
        game.world
            .block_entities
            .insert((pos[0], pos[1], pos[2]), BlockEntity::Mod(Box::new(entity)));
        emit("read", "old", payload, || {
            perf_baseline_read(black_box(&game), pos)
        });
        emit("read", "candidate", payload, || {
            perf_candidate_read(black_box(&game), pos)
        });
        game.with_level(|_, level, _| {
            emit("analog", "old", payload, || {
                let mut out = -1;
                perf_baseline_analog(level, point, state, &mut out);
                out
            });
            emit("analog", "candidate", payload, || {
                let mut out = -1;
                perf_candidate_analog(level, point, state, &mut out);
                out
            });
        });
        let BlockEntity::Mod(entity) = &game.world.block_entities[&(pos[0], pos[1], pos[2])] else {
            unreachable!()
        };
        emit("draw", "old", payload, || render(&game, pos, entity, false));
        emit("draw", "candidate", payload, || {
            render(&game, pos, entity, true)
        });
        assert_eq!(snapshot(entity), before);
    }
    println!(
        "BASIN_PERF_PROOF {{\"actual_game_cases\":{cases},\"geometry_cases\":{geometry_cases},\"geometry_vertices\":{geometry_vertices},\"additional_guard_cases\":3}}"
    );
}
