#[test]
#[ignore = "requires the private prepared resource copy"]
fn burner_loot_actual_game_registry_and_wrench() {
    use crate::game::{
        Audio, Game, Options, PlayerMotion, Progress, Settings, World, load_resources,
    };
    use horizon_client::{chunk::Chunk, containers::BlockEntity, items::ItemStack};
    use horizon_core::{geometry::Vec3, random::LegacyRandom};
    use horizon_world::{
        loot::PackOverlay,
        nbt::{Compound, Tag},
    };
    use std::{path::PathBuf, sync::Arc};

    let base = PathBuf::from(std::env::var_os("HORIZON_TEST_RESOURCES").unwrap());
    let mut settings = Settings::default();
    settings.mods.enabled.insert("create".into());
    crate::game::mods::register_components(&base).unwrap();
    crate::game::mods::register_standalone_models();
    let root = crate::game::mods::content_root(&base, &settings.mods.enabled, &[]);
    assert_ne!(root, base);
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
    game.player = Some(PlayerMotion::new(game.motion, Vec3::new(0.5, 70.0, 0.5)).unwrap());
    // Same in-memory authoritative setup as Horizon state_block_entity_tests.
    // This admits normal Level writes; run_dedicated/listeners are never called.
    game.options.dedicated = Some(Vec::new());
    game.set_mode_id(0);
    game.selected = 0;
    let pos = [1, 70, 1];
    let wrench = ItemStack::new("create:wrench", 1);
    let registry = game.pack.assets.registry;
    let burner = registry.default_state("create:blaze_burner").unwrap();
    let lit = registry.default_state("create:lit_blaze_burner").unwrap();
    let with_property = |state, key: &str, value: &str| {
        let mut descriptor = registry.state(state).unwrap().clone();
        descriptor.properties.insert(key.into(), value.into());
        registry.id(&descriptor).unwrap()
    };
    let mut cases = Vec::new();
    for heat in ["none", "smouldering", "fading", "kindled", "seething"] {
        for facing in ["north", "south", "east", "west"] {
            let state = with_property(burner, "blaze", heat);
            let state = with_property(state, "facing", facing);
            cases.push((
                state,
                if heat == "none" {
                    "create:empty_blaze_burner"
                } else {
                    "create:blaze_burner"
                },
            ));
        }
    }
    for flame in ["regular", "soul"] {
        cases.push((
            with_property(lit, "flame_type", flame),
            "create:empty_blaze_burner",
        ));
    }
    // The real Block.getDrops context includes BE NBT. Source burner loot has
    // no copy-components/custom-data function and must return a fresh item.
    let saved = Tag::Compound(Compound::from([
        ("id".into(), Tag::String("create:blaze_heater".into())),
        ("fuelLevel".into(), Tag::Int(2)),
        ("burnTimeRemaining".into(), Tag::Int(1777)),
        ("Goggles".into(), Tag::Byte(1)),
        ("UnknownSibling".into(), Tag::Int(42)),
    ]));
    for &(state, expected) in &cases {
        game.world.set(pos[0], pos[1], pos[2], state).unwrap();
        let drops = game.block_loot_at(pos, state, Some(&wrench), Some(saved.clone()));
        assert_eq!(
            drops,
            vec![ItemStack::new(expected, 1)],
            "state {}",
            state.0
        );
    }
    println!("BURNER_LOOT_PHASE actual_game_state_cases=22");
    // Regression counterexample: replacing only the discriminator reproduces
    // the original failure under the actual table loader/evaluator.
    let raw: std::collections::BTreeMap<String, String> =
        serde_json::from_slice(horizon_client::native_data!("create", "content.json")).unwrap();
    let files: Vec<_> = ["blaze_burner", "lit_blaze_burner"]
        .into_iter()
        .map(|name| {
            let path = format!("data/create/loot_table/blocks/{name}.json");
            let old = raw[&path]
                .replace(
                    "\"type\": \"minecraft:survives_explosion\"",
                    "\"condition\": \"minecraft:survives_explosion\"",
                )
                .replace(
                    "\"type\": \"minecraft:block_state_property\"",
                    "\"condition\": \"minecraft:block_state_property\"",
                );
            assert_ne!(old, raw[&path]);
            (
                format!("loot_table/create:blocks/{name}"),
                vec![old.into_bytes()],
            )
        })
        .collect();
    let old = horizon_items::items::Items::catalog(&root, &PackOverlay { files: &files }).unwrap();
    for &(state, _) in &cases {
        assert!(
            old.block_drops_by_player(
                registry,
                state,
                Some(&wrench),
                &[],
                &mut LegacyRandom::new(5)
            )
            .is_empty()
        );
    }
    println!("BURNER_LOOT_PHASE old_discriminator_empty_cases=22");
    // Target-engine explosion boundary, not a paired original explosion-event
    // test: the same conditions allow radius1 and reject this deterministic
    // effectively-zero chance. No explosion parameter is present for wrenching.
    for &(state, expected) in &cases {
        let items = game.items();
        assert_eq!(
            items.block_drops_exploded(
                registry,
                state,
                Some(&wrench),
                &[],
                &mut LegacyRandom::new(5),
                None,
                Some(1.0),
                false
            ),
            vec![ItemStack::new(expected, 1)]
        );
        assert!(
            items
                .block_drops_exploded(
                    registry,
                    state,
                    Some(&wrench),
                    &[],
                    &mut LegacyRandom::new(5),
                    None,
                    Some(f32::MAX),
                    false
                )
                .is_empty()
        );
    }
    println!("BURNER_LOOT_PHASE target_explosion_cases=44");
    // Actual native server callback, including Block.getDrops and inventory
    // return. These are method calls; ordinary mouse acceptance is separate.
    for &(state, expected) in [cases[0], cases[4], cases[20]].iter() {
        game.inventory.fill(None);
        game.inventory[0] = Some(wrench.clone());
        game.world.set(pos[0], pos[1], pos[2], state).unwrap();
        game.world.block_entities.remove(&(pos[0], pos[1], pos[2]));
        if let Some(entity) = game.new_block_entity_for_state(state) {
            game.world
                .block_entities
                .insert((pos[0], pos[1], pos[2]), entity);
        }
        game.keys.insert(winit::keyboard::KeyCode::ShiftLeft);
        assert!(super::create_port_interactions::right_click(
            &mut game,
            pos,
            [0, 0, 1]
        ));
        assert_eq!(
            game.world.block(pos[0], pos[1], pos[2]),
            game.res.facts().air
        );
        let mut inventory: Vec<_> = game.inventory.iter().flatten().cloned().collect();
        inventory.sort_by(|a, b| a.item.cmp(&b.item));
        let mut expected_items = vec![wrench.clone(), ItemStack::new(expected, 1)];
        expected_items.sort_by(|a, b| a.item.cmp(&b.item));
        assert_eq!(inventory, expected_items);
        assert!(!matches!(
            game.world.block_entities.get(&(pos[0], pos[1], pos[2])),
            Some(BlockEntity::Mod(_))
        ));
    }
    println!(
        "BURNER_LOOT_PROOF {{\"actual_game_state_cases\":22,\"pre_regression_empty_cases\":22,\"target_explosion_cases\":44,\"actual_server_wrench_callbacks\":3}}"
    );
}
