#[test]
#[ignore = "needs prepared resources in HORIZON_TEST_RESOURCES"]
fn burner_source_prediction_sound_particles_and_state() {
    use super::*;
    use crate::game::{
        load_resources, Audio, Game, Options, PlayerMotion, Progress, Settings, World,
    };
    use horizon_client::{
        chunk::{
            block_entity::{Next, SpawnData, Spawner},
            Chunk,
        },
        items::ItemStack,
        particles::ParticleType,
    };
    use horizon_core::random::{LegacyRandom, RandomSource};
    use horizon_world::nbt::Tag;
    use std::{path::PathBuf, sync::Arc};
    const BLOCK: &str = "create:blaze_burner";
    const LIT: &str = "create:lit_blaze_burner";
    const EMPTY: &str = "create:empty_blaze_burner";
    let base = PathBuf::from(std::env::var_os("HORIZON_TEST_RESOURCES").unwrap());
    let mut settings = Settings::default();
    settings.mods.enabled.insert("create".into());
    crate::game::mods::register_components(&base).unwrap();
    crate::game::mods::register_standalone_models();
    let root = crate::game::mods::content_root(&base, &settings.mods.enabled, &[]);
    assert_ne!(root, base, "full native bundled content must load");
    let loaded = load_resources(
        root.clone(),
        None,
        &base,
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
    game.player = Some(
        PlayerMotion::new(
            game.motion,
            horizon_core::geometry::Vec3::new(0.5, 70.0, 0.5),
        )
        .unwrap(),
    );
    game.set_mode_id(0);
    game.selected = 0;
    let pos = [1, 70, 1];
    let empty = game.pack.assets.registry.default_state(BLOCK).unwrap();
    let lit = game.pack.assets.registry.default_state(LIT).unwrap();
    game.world.set(1, 70, 1, empty).unwrap();
    assert_eq!(clone_item(&game, pos), Some(EMPTY));
    let flint = ItemStack::new("minecraft:flint_and_steel", 1);
    game.inventory[0] = Some(flint.clone());
    game.audio.capture = Some(Vec::new());
    game.particles.seed_randoms(22, 12345, 44);
    let world_random = game.world.random.state();
    let mut expected = LegacyRandom::new(12345);
    let pitch = expected.next_float() * 0.4 + 0.8;
    assert!(predict_block(&mut game, pos, Some(&flint)));
    assert_eq!(
        game.audio.capture.as_ref().unwrap().as_slice(),
        &[(
            "minecraft:item.flintandsteel.use".into(),
            [1.5, 70.5, 1.5],
            1.0,
            pitch,
            4
        )]
    );
    assert_eq!(game.world.random.state(), world_random);
    assert_eq!(game.world.block(1, 70, 1), empty);
    assert_eq!(game.inventory[0], Some(flint.clone()));
    game.keys.insert(winit::keyboard::KeyCode::ShiftLeft);
    assert!(!predict_block(&mut game, pos, Some(&flint)));
    assert_eq!(game.audio.capture.as_ref().unwrap().len(), 1);
    game.keys.clear();
    game.world.set(1, 70, 1, lit).unwrap();
    game.audio.capture.as_mut().unwrap().clear();
    let shovel = ItemStack::new("minecraft:iron_shovel", 1);
    assert!(predict_block(&mut game, pos, Some(&shovel)));
    assert_eq!(
        game.audio.capture.as_ref().unwrap().as_slice(),
        &[(
            "minecraft:entity.generic.extinguish_fire".into(),
            [1.5, 70.5, 1.5],
            0.5,
            2.0,
            4
        )]
    );
    let soul = ItemStack::new("minecraft:soul_sand", 2);
    game.audio.capture.as_mut().unwrap().clear();
    assert!(predict_block(&mut game, pos, Some(&soul)));
    assert_eq!(game.audio.capture.as_ref().unwrap().len(), 1);
    assert_eq!(
        game.audio.capture.as_ref().unwrap()[0].0,
        "minecraft:block.soul_sand.place"
    );
    assert_eq!(clone_item(&game, pos), Some(EMPTY));
    game.world
        .set(
            1,
            70,
            1,
            game.pack
                .assets
                .registry
                .default_state("minecraft:spawner")
                .unwrap(),
        )
        .unwrap();
    let data = |id: &str| SpawnData {
        entity: [("id".into(), Tag::String(id.into()))].into(),
        ..Default::default()
    };
    let mut sp = Spawner {
        next: Some(Next::Own(data("minecraft:blaze"))),
        ..Default::default()
    };
    game.world
        .block_entities
        .insert((1, 70, 1), BlockEntity::Spawner(Box::new(sp.clone())));
    assert!(reacts(&game, pos, Some(&ItemStack::new(EMPTY, 1))));
    sp.potentials = vec![(data("minecraft:zombie"), 1)];
    game.world
        .block_entities
        .insert((1, 70, 1), BlockEntity::Spawner(Box::new(sp.clone())));
    assert!(!reacts(&game, pos, Some(&ItemStack::new(EMPTY, 1))));
    sp.potentials.push((data("minecraft:blaze"), 1));
    game.world
        .block_entities
        .insert((1, 70, 1), BlockEntity::Spawner(Box::new(sp)));
    assert!(reacts(&game, pos, Some(&ItemStack::new(EMPTY, 1))));
    game.particles.requested = Some(Vec::new());
    game.particles.seed_randoms(22, 12345, 44);
    let mut expected = LegacyRandom::new(12345);
    let held = ItemStack::new(EMPTY, 1);
    game.inventory[0] = Some(held.clone());
    game.audio.capture.as_mut().unwrap().clear();
    assert!(predict_block(&mut game, pos, Some(&held)));
    assert!(game.audio.capture.as_ref().unwrap().is_empty());
    assert_eq!(game.inventory[0], Some(held));
    let particles = game.particles.requested.as_ref().unwrap();
    assert_eq!(particles.len(), 80);
    for pair in particles.as_chunks::<2>().0 {
        assert_eq!(pair[0].0.ty, ParticleType::Flame);
        assert_eq!(pair[0].1, [1.5, 70.5, 1.5]);
        assert!(pair[0].2.iter().all(|v| (-0.125..0.125).contains(v)));
        assert_eq!(
            pair[0].2,
            std::array::from_fn(|_| f64::from((expected.next_float() - 0.5) * 2.0 * 0.125))
        );
        assert_eq!(pair[1].0.ty, ParticleType::Smoke);
        assert_eq!(pair[1].1[1], 70.5);
        assert!(pair[1].1[0].abs() <= 0.5 && pair[1].1[2].abs() <= 0.5);
        assert_eq!(pair[1].2, [0.0, -0.125, 0.0]);
    }
    assert!(hand_operated(BLOCK) && hand_operated(LIT));
    assert!(!hand_operated("minecraft:stone"));

    // Normal server callbacks, rather than directly invoking Create's helper.
    // This actual world pack expands the source tag without replacing the
    // registry or simulating an ingredient admission result.
    let world = PathBuf::from(std::env::var_os("HORIZON_HOME").unwrap()).join("burner-world");
    let pack = world.join("datapacks/capture-priority");
    let write = |name: &str, value: serde_json::Value| {
        let file = pack.join(name);
        std::fs::create_dir_all(file.parent().unwrap()).unwrap();
        std::fs::write(file, serde_json::to_vec(&value).unwrap()).unwrap();
    };
    let format = horizon_core::version::DATA_PACK_FORMAT.0;
    write(
        "pack.mcmeta",
        serde_json::json!({"pack":{"min_format":format,"max_format":format,"description":"burner interaction priority"}}),
    );
    write(
        "data/create/tags/entity_type/blaze_burner_capturable.json",
        serde_json::json!({"replace":true,"values":["minecraft:blaze","minecraft:zombie","minecraft:panda","minecraft:villager"]}),
    );
    game.world_root = world;
    game.reload_datapacks(true);
    game.build_registries();
    game.set_allow_commands(true);
    assert!(game.run_command("tick freeze"));
    assert!(game.clock.frozen());
    let capturable = game.tag_entries("entity_type", "create:blaze_burner_capturable");
    assert!(capturable.iter().any(|id| id == "minecraft:villager"));
    let setup = |game: &mut Game<'_>, kind: &str, offhand: bool| {
        game.world = World::new(game.res.facts().air, 1);
        game.world
            .chunks
            .insert((0, 0), Arc::new(Chunk::empty(0, 0)));
        game.mobs.clear();
        let kind = game.res.mob_types().get(kind).unwrap().clone();
        game.mobs.push(horizon_client::mobs::Mob::new(
            42,
            kind,
            horizon_core::geometry::Vec3::new(0.5, 70.0, 2.5),
            0.0,
        ));
        game.player = Some(
            PlayerMotion::new(
                game.motion,
                horizon_core::geometry::Vec3::new(0.5, 70.0, 0.5),
            )
            .unwrap(),
        );
        game.set_mode_id(0);
        game.yaw = 0.0;
        // Aim at the actual body, including a Panda below the player's eyes.
        let eye = game.eye_position().unwrap();
        let center = game.mobs[0].center();
        let horizontal = ((center[0] - eye[0]).powi(2) + (center[2] - eye[2]).powi(2)).sqrt();
        game.pitch = (eye[1] - center[1]).atan2(horizontal).to_degrees() as f32;
        game.tick_hit = None;
        game.tick_mob = None;
        game.station = None;
        game.screen = crate::game::Screen::Playing;
        game.inventory.fill(None);
        game.inventory[0] = Some(ItemStack::new(
            if offhand { "minecraft:stick" } else { EMPTY },
            1,
        ));
        game.offhand = offhand.then(|| ItemStack::new(EMPTY, 1));
        game.swing = Default::default();
        game.swings_started = 0;
        game.audio.capture = Some(Vec::new());
        game.particles.requested = Some(Vec::new());
    };
    let target = Some(crate::game::InteractTarget {
        id: 42,
        location: [0.0, 1.0, 0.0],
    });
    use horizon_client::merchant::{ItemCost, MerchantOffer, Trader};
    setup(&mut game, "minecraft:villager", false);
    game.mobs[0].extra.trade = Some(Box::new(Trader {
        offers: vec![MerchantOffer {
            base_cost_a: ItemCost {
                stack: ItemStack::new("minecraft:emerald", 1),
            },
            cost_b: None,
            result: ItemStack::new("minecraft:bread", 1),
            uses: 0,
            max_uses: 12,
            reward_exp: true,
            special_price_diff: 0,
            demand: 0,
            price_multiplier: 0.0,
            xp: 1,
        }],
        ..Default::default()
    }));
    assert!(game.interact_entity(target).unwrap());
    assert_eq!(
        game.station
            .as_ref()
            .unwrap()
            .merchant
            .as_ref()
            .unwrap()
            .mob,
        Some(42)
    );
    assert!(
        !game.mobs[0].removed,
        "tagged villager must trade before item capture"
    );
    assert_eq!(game.inventory[0].as_ref().unwrap().item.as_ref(), EMPTY);
    assert!(game.particles.requested.as_ref().unwrap().is_empty());
    for (kind, offhand) in [
        ("minecraft:blaze", false),
        ("minecraft:panda", false),
        ("minecraft:zombie", true),
    ] {
        setup(&mut game, kind, offhand);
        assert!(game.run_command(&format!(
            "execute if entity @e[type={kind}] run data merge storage burner:discard {{present:1b}}"
        )));
        assert_eq!(
            game.score.storage.get("burner:discard").get("present"),
            Some(&Tag::Byte(1))
        );
        assert!(game.run_command("data remove storage burner:discard present"));
        let before = game.swings_started;
        assert!(
            game.with_hand(
                if offhand {
                    crate::game::Hand::Off
                } else {
                    crate::game::Hand::Main
                },
                |g| g.interact_entity(target)
            )
            .unwrap(),
            "{kind}"
        );
        assert!(
            game.mobs[0].removed,
            "normal injected item callback must capture {kind}"
        );
        // No world/entity tick between capture and this ordinary command.
        // Discard immediately leaves entity selection, even while frozen.
        assert!(game.run_command(&format!(
            "execute unless entity @e[type={kind}] run data merge storage burner:discard {{gone:1b}}"
        )));
        assert_eq!(
            game.score.storage.get("burner:discard").get("gone"),
            Some(&Tag::Byte(1)),
            "captured {kind} remains selectable"
        );
        assert!(game.run_command("data remove storage burner:discard gone"));
        let mut saved = std::collections::HashMap::new();
        game.save_every_entity(&[(0, 0)].into(), &mut saved);
        assert!(
            saved.values().all(Vec::is_empty),
            "discarded mob must not save"
        );
        assert_eq!(game.swings_started, before, "source FAIL suppresses swing");
        assert!(
            game.dropped.is_empty(),
            "discard must not create death loot"
        );
        let held = if offhand {
            game.offhand.as_ref()
        } else {
            game.inventory[0].as_ref()
        }
        .unwrap();
        assert_eq!(held.item.as_ref(), BLOCK);
        assert_eq!(held.count, 1);
        if offhand {
            assert_eq!(
                game.inventory[0].as_ref().unwrap().item.as_ref(),
                "minecraft:stick"
            );
        }
        assert!(
            game.particles.requested.as_ref().unwrap().is_empty(),
            "capture particles are client-owned"
        );
    }
    setup(&mut game, "minecraft:cow", false);
    let old = game.inventory[0].clone();
    assert!(!game.interact_entity(target).unwrap());
    assert!(!game.mobs[0].removed);
    assert_eq!(game.inventory[0], old);
    assert_eq!(game.swings_started, 0);

    // Normal Remote constructor, normal packet-sending prediction adapters,
    // and the real injected synchronized-data callback. No joined handshake or
    // rendered/audio output is inferred from this controlled memory-Pipe Game.
    use crate::game::create_port_burner_sync_protocol as wire;
    use horizon_protocol::connection::Pipe;
    let definitions = wire::Snapshot {
        capturable: capturable.into_iter().collect(),
        ..Default::default()
    };
    let frames = wire::frames(
        wire::Generation {
            world: 1,
            reload: 1,
        },
        &definitions,
    )
    .unwrap();
    game.options.execution_role = crate::game::execution_role::ExecutionRole::Client;
    game.world_tables = None;
    let (client, server) = Pipe::pair();
    game.connect_local(client, "BurnerAdapterTest").unwrap();
    for frame in &frames {
        game.native_net_from_server("create:burner_data_v1", frame);
    }
    setup(&mut game, "minecraft:villager", false);
    let rng = game.particles.level_random().state();
    let inventory = game.inventory.clone();
    assert!(
        !game.create_burner_predict_entity(crate::game::Hand::Main),
        "vanilla client trade result owns first"
    );
    assert_eq!(game.particles.level_random().state(), rng);
    assert!(game.particles.requested.as_ref().unwrap().is_empty());
    assert_eq!(game.inventory, inventory);
    for offhand in [false, true] {
        setup(&mut game, "minecraft:blaze", offhand);
        let inventory = game.inventory.clone();
        let off = game.offhand.clone();
        assert!(game.create_burner_predict_entity(if offhand {
            crate::game::Hand::Off
        } else {
            crate::game::Hand::Main
        }));
        assert_eq!(game.inventory, inventory);
        assert_eq!(game.offhand, off);
        assert!(
            !game.mobs[0].removed,
            "client predicts effects, server owns discard"
        );
        assert_eq!(game.swings_started, 0);
        let requested = game.particles.requested.as_ref().unwrap();
        assert_eq!(requested.len(), 80);
        assert_eq!(
            requested
                .iter()
                .filter(|p| p.0.ty == ParticleType::Flame)
                .count(),
            40
        );
        assert_eq!(
            requested
                .iter()
                .filter(|p| p.0.ty == ParticleType::Smoke)
                .count(),
            40
        );
    }
    setup(&mut game, "minecraft:panda", false);
    assert_eq!(game.mob_hit().map(|(index, _)| index), Some(0));
    assert!(game.create_burner_predict_entity(crate::game::Hand::Main));
    assert_eq!(game.particles.requested.as_ref().unwrap().len(), 80);
    setup(&mut game, "minecraft:cow", false);
    let rng = game.particles.level_random().state();
    assert!(!game.create_burner_predict_entity(crate::game::Hand::Main));
    assert_eq!(game.particles.level_random().state(), rng);
    assert!(game.particles.requested.as_ref().unwrap().is_empty());
    for offhand in [false, true] {
        setup(&mut game, "minecraft:blaze", offhand);
        game.set_mode_id(3);
        let rng = game.particles.level_random().state();
        let world_rng = game.world.random.state();
        let inventory = game.inventory.clone();
        let off = game.offhand.clone();
        assert!(!game.create_burner_predict_entity(if offhand {
            crate::game::Hand::Off
        } else {
            crate::game::Hand::Main
        }));
        assert_eq!(game.particles.level_random().state(), rng);
        assert_eq!(game.world.random.state(), world_rng);
        assert_eq!(game.inventory, inventory);
        assert_eq!(game.offhand, off);
        assert!(game.particles.requested.as_ref().unwrap().is_empty());
        assert!(game.audio.capture.as_ref().unwrap().is_empty());
        assert_eq!(game.swings_started, 0);
    }
    // Verify the block target first in survival, so spectator rejection cannot
    // pass merely because the ray missed an otherwise valid burner action.
    setup(&mut game, "minecraft:blaze", false);
    game.mobs.clear();
    game.world.set(0, 70, 2, empty).unwrap();
    game.inventory[0] = Some(flint);
    game.pitch = 45.0;
    assert!(game.create_burner_predict_block(crate::game::Hand::Main));
    game.audio.capture.as_mut().unwrap().clear();
    game.particles.requested.as_mut().unwrap().clear();
    game.set_mode_id(3);
    let rng = game.particles.level_random().state();
    let world_rng = game.world.random.state();
    let inventory = game.inventory.clone();
    assert!(!game.create_burner_predict_block(crate::game::Hand::Main));
    assert_eq!(game.particles.level_random().state(), rng);
    assert_eq!(game.world.random.state(), world_rng);
    assert_eq!(game.inventory, inventory);
    assert!(game.particles.requested.as_ref().unwrap().is_empty());
    assert!(game.audio.capture.as_ref().unwrap().is_empty());
    server.shutdown();
}
