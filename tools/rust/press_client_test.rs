// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT
// Include in the full official-woven create_port_press_client module.
use super::*;

#[test]
#[ignore = "requires private resources and the complete source-woven native stage"]
fn press_actual_client_receipt_tick_identity_and_particle_rng() {
    assert!(
        crate::mod_api::mods().is_empty(),
        "requires actual source weaving"
    );
    use crate::game::{
        Audio, Options, Progress, Settings, World, execution_role::ExecutionRole, load_resources,
    };
    use horizon_client::{chunk::Chunk, containers::ModBlockEntityFields};
    use horizon_core::random::LegacyRandom;
    use horizon_protocol::{connection::Pipe, registry::Builtin};
    use std::{path::PathBuf, sync::Arc};
    let vanilla = PathBuf::from(std::env::var_os("HORIZON_TEST_RESOURCES").unwrap());
    let mut settings = Settings::default();
    settings.mods.enabled.insert("create".into());
    crate::game::mods::register_components(&vanilla).unwrap();
    crate::game::mods::register_standalone_models();
    let root = crate::game::mods::content_root(&vanilla, &settings.mods.enabled, &[]);
    let loaded = load_resources(
        root.clone(),
        None,
        &vanilla,
        &settings,
        std::time::Instant::now(),
        false,
        true,
        &Progress::new(),
        &mut |_, _| unreachable!(),
    )
    .unwrap();
    let mut options = Options::parse(std::iter::empty()).unwrap().unwrap();
    options.resources = root.clone();
    options.execution_role = ExecutionRole::Client;
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
    let (client, server) = Pipe::pair();
    game.connect_local(client, "PressClientProof").unwrap();
    // An explicit wire registry context; actual receipt, validation, merging,
    // particle admission and owned client state use their real Game paths.
    game.remote.as_mut().unwrap().builtin = Arc::new(Builtin::parse(
        r#"{"minecraft:block_entity_type":{"entries":{"create:mechanical_press":{"protocol_id":49},"test:wrong":{"protocol_id":50}}}}"#,
    ).unwrap());
    game.world = World::new(game.res.facts().air, 1);
    game.world
        .chunks
        .insert((0, 0), Arc::new(Chunk::empty(0, 0)));
    let pos = [4, 70, 4];
    let state = game.pack.assets.registry.default_state(ID).unwrap();
    game.world.set(pos[0], pos[1], pos[2], state).unwrap();
    let entity = game.new_block_entity_for_state(state).unwrap();
    game.world
        .block_entities
        .insert((pos[0], pos[1], pos[2]), entity);
    reset();
    let item = ItemStack::new("minecraft:iron_ingot", 7);
    let packet = |mode, ticks, particles| {
        Tag::compound([
            ("Running", Tag::Byte(1)),
            ("Finished", Tag::Byte(1)),
            ("Mode", Tag::Int(mode)),
            ("Ticks", Tag::Int(ticks)),
            ("Speed", Tag::Float(32f32.to_bits())),
            (
                "ParticleItems",
                Tag::List(if particles {
                    vec![horizon_items::item_nbt::item_to_nbt(&item)]
                } else {
                    Vec::new()
                }),
            ),
        ])
    };
    let server_rng = game.world.random.state();
    for (mode, amount, y) in [(0, 15, 69.0), (1, 15, 68.75), (2, 20, 68.5)] {
        game.particles.requested = Some(Vec::new());
        *game.particles.level_random() = LegacyRandom::new(923);
        let mut expected = LegacyRandom::new(923);
        let tag = packet(mode, 120, true);
        // The actual named remote handler passes through the raw HEAD helper;
        // an unchanged NBT merge must not suppress the second receipt.
        for repeated in 1..=2 {
            game.remote_block_entity_data(pos, 49, &tag);
            for _ in 0..amount * 3 {
                expected.next_float();
            }
            assert_eq!(game.particles.level_random().state(), expected.state());
            let requests = game.particles.requested.as_ref().unwrap();
            assert_eq!(requests.len(), amount * repeated);
            assert!(requests.iter().all(|(options, p, v)| {
                options.ty == crate::particles::ParticleType::Item
                    && *p == [4.5, y, 4.5]
                    && v[1] == if mode == 2 { 0.25 } else { 0.125 }
            }));
        }
        let before = game.particles.level_random().state();
        let count = game.particles.requested.as_ref().unwrap().len();
        game.remote_block_entity_data(pos, 50, &tag);
        assert_eq!(
            game.particles.level_random().state(),
            before,
            "wrong wire type emitted"
        );
        assert_eq!(game.particles.requested.as_ref().unwrap().len(), count);
        assert_eq!(game.world.random.state(), server_rng);
    }

    // Real ParticleEngine.add performs Decreased admission between offsets.
    // No request/constructor capture is enabled for this row. Particle-local
    // random and sprite selection remain the engine's normal responsibility.
    game.particles.requested = None;
    game.particles.created_requests = None;
    game.particles.camera = [4.5, 69.0, 4.5];
    game.particles.particle_level = 1;
    *game.particles.level_random() = LegacyRandom::new(81);
    let mut expected = LegacyRandom::new(81);
    for _ in 0..15 {
        for _ in 0..3 {
            expected.next_float();
        }
        expected.next_int_bound(3).unwrap();
    }
    game.remote_block_entity_data(pos, 49, &packet(0, 120, true));
    assert_eq!(game.particles.level_random().state(), expected.state());
    assert_eq!(game.world.random.state(), server_rng);
    game.particles.clear();

    let cycle = |game: &Game<'_>| {
        CLIENTS.with(|cache| {
            cache
                .borrow_mut()
                .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
                .entries[&pos]
                .cycle
                .clone()
        })
    };
    game.remote_block_entity_data(pos, 49, &packet(2, 116, false));
    game.ticks += 1;
    tick(&mut game);
    assert_eq!(
        (cycle(&game).previous_ticks, cycle(&game).ticks),
        (116, -120)
    );
    tick(&mut game); // Same actual tick callback cannot tick a second time.
    assert_eq!(cycle(&game).previous_ticks, 116);
    game.ticks += 1;
    tick(&mut game);
    assert_eq!(
        (cycle(&game).previous_ticks, cycle(&game).ticks),
        (120, -120)
    );
    game.remote_block_entity_data(pos, 49, &packet(2, 120, false));
    game.ticks += 1;
    tick(&mut game);
    assert_eq!(
        (cycle(&game).previous_ticks, cycle(&game).ticks),
        (120, 124)
    );
    // Stored ParticleItems do not replay during a tick or draw. A replacement
    // at the same position is a fresh scalar state, not the old paused cycle.
    game.particles.requested = Some(Vec::new());
    let fresh = ModBlockEntity::new(ModBlockEntityFields {
        id: ID.into(),
        nbt: Compound::from([
            ("Running".into(), Tag::Byte(0)),
            ("Mode".into(), Tag::Int(2)),
            (
                "ParticleItems".into(),
                Tag::List(vec![horizon_items::item_nbt::item_to_nbt(&item)]),
            ),
        ]),
        ..Default::default()
    });
    game.world
        .block_entities
        .insert((pos[0], pos[1], pos[2]), BlockEntity::Mod(Box::new(fresh)));
    let BlockEntity::Mod(entity) = &game.world.block_entities[&(pos[0], pos[1], pos[2])] else {
        unreachable!()
    };
    assert_eq!(travel(&game, pos, entity, 0.5), 0.0);
    game.ticks += 1;
    tick(&mut game);
    assert!(!cycle(&game).running);
    assert!(game.particles.requested.as_ref().unwrap().is_empty());
    reset();
    server.shutdown();
    println!(
        "Press actual client: identical/raw receipt,3 modes,real Decreased RNG,negative120 pause,identity/no stored replay PASS"
    );
}
