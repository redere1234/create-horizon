// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT
// Include inside create_port_press_basin only in the private, complete
// official-source-woven Game test. No substitute trait hooks or fake recipe IO.
#[test]
#[ignore = "requires private resources and the complete source-woven native stage"]
fn press_basin_actual_game_lifecycle() {
    use super::*;
    use crate::{
        game::{
            Audio, Options, Progress, Settings, World, execution_role::ExecutionRole,
            load_resources,
        },
        items::ItemStack,
    };
    use horizon_client::{chunk::Chunk, containers::BlockEntity};
    use horizon_core::version::DATA_PACK_FORMAT;
    use horizon_world::registry::BlockStateId;
    use std::path::PathBuf;

    const B: Pos = [1, 70, 1];
    const P: Pos = [1, 72, 1];
    fn entity<'a>(game: &'a Game<'_>, pos: Pos) -> &'a ModBlockEntity {
        let BlockEntity::Mod(entity) = &game.world.block_entities[&(pos[0], pos[1], pos[2])] else {
            unreachable!()
        };
        entity
    }
    fn value(game: &Game<'_>, key: &str) -> i32 {
        super::super::create_port::integer(&entity(game, P).nbt, key)
    }
    fn state(game: &Game<'_>, name: &str, property: &str, value: &str) -> BlockStateId {
        (0..game.pack.assets.registry.len() as u32)
            .map(BlockStateId)
            .find(|id| {
                let state = game.pack.assets.registry.state(*id).unwrap();
                state.name == name
                    && state.properties.get(property).map(String::as_str) == Some(value)
            })
            .unwrap_or_else(|| panic!("missing fixture state {name}[{property}={value}]"))
    }
    fn put(game: &mut Game<'_>, pos: Pos, state: BlockStateId) {
        game.world.block_entities.remove(&(pos[0], pos[1], pos[2]));
        game.world.set(pos[0], pos[1], pos[2], state).unwrap();
        if let Some(entity) = game.new_block_entity_for_state(state) {
            game.world
                .block_entities
                .insert((pos[0], pos[1], pos[2]), entity);
        }
        super::super::create_port_kinetic_runtime::invalidate();
    }
    fn pair(game: &mut Game<'_>) {
        reset(false);
        basin::reset(false);
        game.world.game_time += 1000;
        let basin = state(game, "create:basin", "facing", "down");
        let press = state(game, ID, "facing", "east");
        put(game, B, basin);
        put(game, P, press);
        game.native_with_mod_block_entity(B, basin::initialize)
            .unwrap();
        game.native_with_mod_block_entity(P, |e| {
            e.nbt.insert("Speed".into(), Tag::Float(32f32.to_bits()));
            e.nbt.insert("NeedsUpdate".into(), Tag::Byte(0));
        })
        .unwrap();
    }
    fn seed(game: &mut Game<'_>, item: &str, count: u32) {
        game.native_with_mod_block_entity(B, |e| {
            e.items = vec![None; 18];
            e.items[0] = Some(ItemStack::new(item, count));
            basin::data(e);
        })
        .unwrap();
    }
    fn count(game: &Game<'_>, output: bool, item: &str) -> u32 {
        let basin = basin::read(game, B).unwrap();
        let slots = if output { &basin.output } else { &basin.input };
        slots
            .iter()
            .flatten()
            .filter(|stack| stack.key.0.item.as_ref() == item)
            .map(|stack| stack.count)
            .sum()
    }
    fn step(game: &mut Game<'_>, full_runtime: bool) -> Option<bool> {
        game.world.game_time += 1;
        let BlockEntity::Mod(mut entity) = game
            .world
            .block_entities
            .remove(&(P[0], P[1], P[2]))
            .unwrap()
        else {
            unreachable!()
        };
        let result = if full_runtime {
            super::super::create_port::tick(game, P, &mut entity);
            None
        } else {
            tick(game, P, &mut entity, 32.0)
        };
        game.world
            .block_entities
            .insert((P[0], P[1], P[2]), BlockEntity::Mod(entity));
        result
    }
    fn until(game: &mut Game<'_>, label: &str, ready: impl Fn(&Game<'_>) -> bool) {
        for _ in 0..200 {
            if ready(game) {
                return;
            }
            step(game, false);
        }
        panic!("bounded Press fixture did not reach {label}");
    }
    fn tag(game: &Game<'_>) -> Compound {
        let mut tag = None;
        super::super::create_port::update_tag(entity(game, P), &mut tag);
        tag.unwrap()
    }
    fn particles(tag: &Compound) -> Vec<ItemStack> {
        let Some(Tag::List(items)) = tag.get(&"ParticleItems".into()) else {
            panic!("Press update omitted ParticleItems")
        };
        items
            .iter()
            .map(|item| horizon_items::item_nbt::item_from_nbt(item).unwrap())
            .collect()
    }

    assert!(crate::mod_api::mods().is_empty(), "requires actual weaving");
    let vanilla = PathBuf::from(std::env::var_os("HORIZON_TEST_RESOURCES").unwrap());
    let scratch =
        PathBuf::from(std::env::var_os("HORIZON_HOME").unwrap()).join("press-basin-lifecycle");
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
    options.execution_role = ExecutionRole::IntegratedServer;
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
    game.options.dedicated = Some(Vec::new());
    game.world_root = scratch.clone();
    game.session_lock = Some(horizon_client::save::SessionLock::acquire(&scratch).unwrap());
    let (tables, health) = game
        .build_world_tables(false, &["minecraft:vanilla".into()])
        .unwrap();
    game.world_tables = tables;
    game.health_resources = health;
    game.native_server_data_loaded(false);
    game.world = World::new(game.res.facts().air, 1);
    game.world
        .chunks
        .insert((0, 0), Arc::new(Chunk::empty(0, 0)));
    let containers = game.native_containers();
    game.world.block_entities.set_mod_containers(containers);

    // Deferral starts before behavior tick; completion's repeat starts after
    // behavior tick. Source PressingBehaviour/MechanicalPress differ here.
    pair(&mut game);
    seed(&mut game, "minecraft:snowball", 8);
    schedule(&mut game, P);
    assert_eq!(step(&mut game, false), Some(true));
    assert_eq!(
        (
            value(&game, "Running"),
            value(&game, "Mode"),
            value(&game, "Ticks")
        ),
        (1, 2, 4)
    );
    until(&mut game, "first snow block", |g| {
        count(g, true, "minecraft:snow_block") == 1
    });
    assert_eq!(count(&game, false, "minecraft:snowball"), 4);
    assert_eq!(value(&game, "Ticks"), 124);
    assert!(!entity(&game, P).nbt.contains_key(&"ParticleItems".into()));
    // Saving must neither serialize nor consume pending client-only fields.
    let saved = horizon_client::save::encode_block_entity(
        (P[0], P[1], P[2]),
        &game.world.block_entities[&(P[0], P[1], P[2])],
        ID,
    );
    assert!(saved.get("ParticleItems").is_none());
    let first = tag(&game);
    assert_eq!(particles(&first), [ItemStack::new("minecraft:snowball", 4)]);
    assert!(particles(&tag(&game)).is_empty(), "client field replayed");
    assert_eq!(particles(&first).len(), 1, "prior tag mutated after drain");
    until(&mut game, "same-call completion restart", |g| {
        value(g, "Finished") != 0
    });
    assert_eq!((value(&game, "Running"), value(&game, "Ticks")), (1, 0));
    step(&mut game, false);
    assert_eq!(value(&game, "Ticks"), 4);
    until(&mut game, "two snow blocks", |g| {
        count(g, true, "minecraft:snow_block") == 2
    });
    assert_eq!(count(&game, false, "minecraft:snowball"), 0);
    assert!(
        particles(&tag(&game)).is_empty(),
        "consumed input became particles"
    );
    until(&mut game, "exhausted completion", |g| {
        value(g, "Running") == 0
    });
    assert_eq!(value(&game, "NeedsUpdate"), 1);

    // No recipe must not invent a running cycle or consume unsupported input.
    pair(&mut game);
    seed(&mut game, "minecraft:nether_star", 1);
    schedule(&mut game, P);
    assert_eq!(step(&mut game, false), Some(false));
    assert_eq!(
        (value(&game, "Running"), value(&game, "NeedsUpdate")),
        (0, 0)
    );
    assert_eq!(count(&game, false, "minecraft:nether_star"), 1);

    // A real reload invalidates the lookup cache without replacing a live
    // cycle's Recipe Arc. Exhaust it before a fresh lookup of the new output.
    let pack = scratch.join("datapacks/press-basin-lifecycle");
    let write = |path: &str, json: serde_json::Value| {
        let path = pack.join(path);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(path, serde_json::to_vec(&json).unwrap()).unwrap();
    };
    write(
        "pack.mcmeta",
        serde_json::json!({"pack":{
            "min_format":DATA_PACK_FORMAT.0,"max_format":DATA_PACK_FORMAT.0,
            "description":"Press live recipe reload regression"
        }}),
    );
    let recipe = |output: &str| {
        serde_json::json!({
            "type":"create:compacting", "ingredients":vec!["minecraft:feather";4],
            "results":[{"id":output}]
        })
    };
    write(
        "data/demo/recipe/press_lifecycle.json",
        recipe("minecraft:diamond"),
    );
    game.reload_datapacks(true);
    pair(&mut game);
    seed(&mut game, "minecraft:feather", 4);
    schedule(&mut game, P);
    step(&mut game, false);
    let before = with_world(&game, |world| {
        Arc::clone(world[&P].recipe.as_ref().unwrap())
    });
    assert_eq!(before.id, "demo:press_lifecycle");
    write(
        "data/demo/recipe/press_lifecycle.json",
        recipe("minecraft:emerald"),
    );
    game.reload_datapacks(true);
    let retained = with_world(&game, |world| {
        Arc::clone(world[&P].recipe.as_ref().unwrap())
    });
    assert!(Arc::ptr_eq(&before, &retained));
    until(&mut game, "retained old recipe output", |g| {
        count(g, true, "minecraft:diamond") == 1
    });
    until(&mut game, "old recipe exhaustion", |g| {
        value(g, "Running") == 0
    });
    seed(&mut game, "minecraft:feather", 4);
    schedule(&mut game, P);
    step(&mut game, false);
    let fresh = with_world(&game, |world| {
        Arc::clone(world[&P].recipe.as_ref().unwrap())
    });
    assert!(!Arc::ptr_eq(&before, &fresh));
    until(&mut game, "fresh recipe output", |g| {
        count(g, true, "minecraft:emerald") == 1
    });

    // A removal event belongs to the replacement's birth even if an old
    // operator at this coordinate populated the transient table earlier.
    let old = entity(&game, P).revision();
    let press = state(&game, ID, "facing", "east");
    put(&mut game, P, press);
    assert!(!old.same_entity(entity(&game, P).revision()));
    game.native_with_mod_block_entity(P, |e| {
        e.nbt.insert("Running".into(), Tag::Byte(1));
        e.nbt.insert("Mode".into(), Tag::Int(2));
        e.nbt.insert("Ticks".into(), Tag::Int(80));
        e.set_client_update_fields(Compound::from([(
            "ParticleItems".into(),
            Tag::List(Vec::new()),
        )]));
    })
    .unwrap();
    let air = game.res.facts().air;
    put(&mut game, B, air);
    basin::removed(&mut game, B);
    assert_eq!(step(&mut game, false), Some(true));
    assert_eq!((value(&game, "Running"), value(&game, "Ticks")), (0, 0));
    assert!(entity(&game, P).take_client_update_fields().is_empty());

    // Cold load of running Mode2 with no Basin has no currentRecipe/removal
    // event. Source continues the animation, and the impact still synchronizes.
    reset(false);
    game.native_with_mod_block_entity(P, |e| {
        e.nbt.insert("Running".into(), Tag::Byte(1));
        e.nbt.insert("Mode".into(), Tag::Int(2));
        e.nbt.insert("Ticks".into(), Tag::Int(120));
        e.nbt.insert("Applied".into(), Tag::Int(0));
        e.nbt.insert("NeedsUpdate".into(), Tag::Byte(0));
    })
    .unwrap();
    let saved = horizon_client::save::encode_block_entity(
        (P[0], P[1], P[2]),
        &game.world.block_entities[&(P[0], P[1], P[2])],
        ID,
    );
    let (position, cold) = horizon_client::save::decode_block_entity(&saved).unwrap();
    assert_eq!(position, (P[0], P[1], P[2]));
    game.world.block_entities.insert(position, cold);
    assert_eq!(step(&mut game, false), Some(true));
    assert_eq!((value(&game, "Running"), value(&game, "Ticks")), (1, 124));
    assert!(particles(&tag(&game)).is_empty());

    // An old WORLD/BELT cycle completing above a newly available Basin must
    // schedule the ordinary Deferral rather than wait for the lazy backup.
    for mode in [0, 1] {
        pair(&mut game);
        seed(&mut game, "minecraft:snowball", 4);
        // This motor is east of the press, so its one shaft port must point
        // WEST toward the shaft. Facing east would leave the operator at RPM0;
        // completion still runs at zero, but the next Deferral cannot start.
        let motor = state(&game, "create:creative_motor", "facing", "west");
        let shaft = state(&game, "create:shaft", "axis", "x");
        put(&mut game, [3, 72, 1], motor);
        put(&mut game, [2, 72, 1], shaft);
        game.native_with_mod_block_entity([3, 72, 1], |e| {
            e.nbt.insert("ScrollValue".into(), Tag::Int(32));
        })
        .unwrap();
        game.native_with_mod_block_entity(P, |e| {
            e.nbt.insert("Speed".into(), Tag::Float(32f32.to_bits()));
            e.nbt.insert("Running".into(), Tag::Byte(1));
            e.nbt.insert("Mode".into(), Tag::Int(mode));
            e.nbt.insert("Ticks".into(), Tag::Int(244));
            e.nbt.insert("Applied".into(), Tag::Int(1));
            e.nbt.insert("NeedsUpdate".into(), Tag::Byte(0));
        })
        .unwrap();
        step(&mut game, true);
        assert_eq!(
            super::super::create_port::number(&entity(&game, P).nbt, "Speed").abs(),
            32.0,
            "legacy transition fixture is disconnected"
        );
        assert_eq!(
            super::super::create_port::running_speed(&game, &entity(&game, P).nbt).abs(),
            32.0,
            "legacy transition fixture is frozen"
        );
        assert_eq!(
            (value(&game, "Running"), value(&game, "NeedsUpdate")),
            (0, 1)
        );
        step(&mut game, true);
        assert_eq!(
            (
                value(&game, "Running"),
                value(&game, "Mode"),
                value(&game, "Ticks")
            ),
            (1, 2, 4)
        );
    }
    println!(
        "Press Basin actual Game PASS: Deferral/completion ordering, 8->2 conservation, no-recipe, one-shot update vs save, retained reload recipe, birth/removal, cold missing Basin and WORLD/BELT handoff"
    );
}
