// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT
// Actual owned ItemEntity movement through the full official-woven bundle.
use super::*;
use crate::game::{create_port_basin as basin, create_port_millstone as mill};
use horizon_client::{chunk::Chunk, containers::ModBlockEntity, items::ItemStack};
use horizon_world::nbt::{Compound, Tag};
use std::{path::PathBuf, sync::Arc};
type Pos = [i32; 3];
const AT: Pos = [4, 64, 4];

fn machine<'a>(game: &'a Game<'_>, pos: Pos) -> &'a ModBlockEntity {
    let BlockEntity::Mod(entity) = &game.world.block_entities[&(pos[0], pos[1], pos[2])] else {
        panic!("expected native machine at {pos:?}")
    };
    entity
}
fn state(
    game: &Game<'_>,
    id: &str,
    properties: &[(&str, &str)],
) -> horizon_world::registry::BlockStateId {
    let registry = game.pack.assets.registry;
    (0..registry.len() as u32)
        .map(horizon_world::registry::BlockStateId)
        .find(|id_state| {
            let value = registry.state(*id_state).unwrap();
            value.name == id
                && properties.iter().all(|(key, want)| {
                    value.properties.get(*key).map(String::as_str) == Some(*want)
                })
        })
        .unwrap_or_else(|| panic!("missing state {id} {properties:?}"))
}
fn put(game: &mut Game<'_>, pos: Pos, id: &str, properties: &[(&str, &str)]) {
    let block = state(game, id, properties);
    game.world.set(pos[0], pos[1], pos[2], block).unwrap();
    game.world.block_entities.remove(&(pos[0], pos[1], pos[2]));
    if let Some(entity) = game.new_block_entity_for_state(block) {
        game.world
            .block_entities
            .insert((pos[0], pos[1], pos[2]), entity);
    }
    crate::game::create_port_kinetic_runtime::invalidate();
}
fn seed(game: &mut Game<'_>, pos: Pos, values: &[(usize, ItemStack)]) {
    game.native_with_mod_block_entity(pos, |entity| {
        if entity.id == "create:basin" {
            basin::initialize(entity);
            entity.items = vec![None; 18];
        } else {
            entity.items = vec![None; 10];
        }
        for (slot, stack) in values {
            entity.items[*slot] = Some(stack.clone());
        }
        if entity.id == "create:basin" {
            basin::data(entity);
        } else {
            mill::data(entity);
        }
    })
    .unwrap();
}
fn incoming() -> ItemStack {
    let mut stack = ItemStack::new("minecraft:wheat", 13);
    stack.data_mut().set_other(
        "minecraft:custom_data",
        Some(Tag::compound([("retained", Tag::Long(907))])),
    );
    stack
}
fn land(
    game: &mut Game<'_>,
    stack: ItemStack,
    at: [f64; 3],
    velocity: [f64; 3],
    client: bool,
) -> (u32, u64) {
    game.dropped.clear();
    game.spawn_item(stack, at, velocity, 32767);
    game.ticked_entities_through = game.next_entity;
    let before = &game.dropped[0];
    let identity = (
        before.id,
        horizon_client::join_seq::Joined::join_seq(before).get(),
    );
    if client {
        game.tick_remote().unwrap();
    } else {
        game.tick_items();
    }
    identity
}
fn assert_remainder(game: &Game<'_>, expected: &ItemStack, count: u32, identity: (u32, u64)) {
    if count == 0 {
        assert!(game.dropped.is_empty());
        return;
    }
    assert_eq!(game.dropped.len(), 1);
    let item = &game.dropped[0];
    assert_eq!(item.stack.count, count);
    assert!(item.stack.same_item_same_components(expected));
    assert_eq!(
        (
            item.id,
            horizon_client::join_seq::Joined::join_seq(item).get()
        ),
        identity
    );
}
fn saved(
    game: &Game<'_>,
    pos: Pos,
) -> (
    crate::containers::ModRevision,
    Compound,
    Vec<Option<ItemStack>>,
) {
    let e = machine(game, pos);
    (e.revision(), e.nbt.clone(), e.items.clone())
}
fn integer(game: &Game<'_>, pos: Pos, key: &str) -> i32 {
    crate::game::create_port::integer(&machine(game, pos).nbt, key)
}

#[test]
#[ignore = "complete official native bundle and private prepared resources"]
fn source_item_contacts_actual_owned_game_and_remote() {
    assert!(
        crate::mod_api::mods().is_empty(),
        "exercise raw hooks, not a trait registration substitute"
    );
    let vanilla = PathBuf::from(std::env::var_os("HORIZON_TEST_RESOURCES").unwrap());
    let mut settings = Settings::default();
    settings.mods.enabled.insert("create".into());
    crate::game::mods::register_components(&vanilla).unwrap();
    crate::game::mods::register_standalone_models();
    let root = crate::game::mods::content_root(&vanilla, &settings.mods.enabled, &[]);
    assert_ne!(root, vanilla);
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
    options.execution_role = execution_role::ExecutionRole::IntegratedServer;
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
    game.player = None;
    game.world = World::new(game.res.facts().air, 1);
    game.world
        .chunks
        .insert((0, 0), Arc::new(Chunk::empty(0, 0)));
    let containers = game.native_containers();
    game.world.block_entities.set_mod_containers(containers);
    assert!(
        mill::can_process(&game, &incoming()),
        "real merged milling recipe fixture"
    );
    let stack = incoming();
    // Fresh constructor admission is synchronous in the actual active owner batch.
    for (id, at) in [
        ("create:basin", [4.5, 64.5, 4.5]),
        ("create:millstone", [4.5, 65.1, 4.5]),
    ] {
        put(&mut game, AT, id, &[]);
        let identity = land(&mut game, stack.clone(), at, [0.0, -0.3, 0.0], false);
        assert_remainder(&game, &stack, 0, identity);
        let entity = machine(&game, AT);
        assert_eq!(
            entity.items.len(),
            if id == "create:basin" { 18 } else { 10 }
        );
        assert_eq!(entity.items[0], Some(stack.clone()));
        assert!(entity.items[1..].iter().all(Option::is_none));
    }
    // First matching input, no spill, output half ignored; retain all component patches.
    for (id, at) in [
        ("create:basin", [4.5, 64.5, 4.5]),
        ("create:millstone", [4.5, 65.1, 4.5]),
    ] {
        for (maximum, occupied) in [(64, 63), (16, 15)] {
            put(&mut game, AT, id, &[]);
            let mut incoming = stack.clone();
            if maximum == 16 {
                incoming
                    .data_mut()
                    .set_other("minecraft:max_stack_size", Some(Tag::Int(16)));
            }
            let mut held = incoming.clone();
            held.count = occupied;
            seed(&mut game, AT, &[(0, held)]);
            let identity = land(&mut game, incoming.clone(), at, [0.0, -0.3, 0.0], false);
            assert_remainder(&game, &incoming, 12, identity);
            let entity = machine(&game, AT);
            assert_eq!(entity.items[0].as_ref().unwrap().count, maximum);
            assert!(
                entity.items[0]
                    .as_ref()
                    .unwrap()
                    .same_item_same_components(&incoming)
            );
            assert!(entity.items[1..].iter().all(Option::is_none));
        }
        // Full input and opaque canonical size refusal may not dirty or rewrite the BE.
        for opaque in [false, true] {
            put(&mut game, AT, id, &[]);
            let mut held = stack.clone();
            held.count = 64;
            seed(&mut game, AT, &[(0, held)]);
            game.native_with_mod_block_entity(AT, |e| {
                e.nbt
                    .insert("UnrecognizedRoot".into(), Tag::ByteArray(vec![0x7f; 4096]));
                if opaque {
                    let key = if id == "create:basin" {
                        "InputItems"
                    } else {
                        "InputInventory"
                    };
                    e.nbt.insert(
                        key.into(),
                        Tag::compound([("Size", Tag::Int(8)), ("Unknown", Tag::Long(923))]),
                    );
                }
            })
            .unwrap();
            let before = saved(&game, AT);
            let identity = land(&mut game, stack.clone(), at, [0.0, -0.3, 0.0], false);
            assert_remainder(&game, &stack, 13, identity);
            assert_eq!(
                saved(&game, AT),
                before,
                "refusal must avoid mutable BE borrow, revision and NBT writes"
            );
        }
        // Separate support above the machine is not contact with that machine.
        put(&mut game, AT, id, &[]);
        put(
            &mut game,
            [4, 65, 4],
            "minecraft:stone_slab",
            &[("type", "bottom")],
        );
        let before = saved(&game, AT);
        let identity = land(
            &mut game,
            stack.clone(),
            [4.5, 65.7, 4.5],
            [0.0, -0.3, 0.0],
            false,
        );
        assert_remainder(&game, &stack, 13, identity);
        assert_eq!(saved(&game, AT), before);
        put(&mut game, [4, 65, 4], "minecraft:air", &[]);
    }
    put(&mut game, AT, "create:basin", &[]);
    let mut held = stack.clone();
    held.count = 63;
    seed(&mut game, AT, &[(5, held), (9, stack.clone())]);
    let identity = land(
        &mut game,
        stack.clone(),
        [4.5, 64.5, 4.5],
        [0.0, -0.3, 0.0],
        false,
    );
    assert_remainder(&game, &stack, 12, identity);
    assert!(machine(&game, AT).items[..5].iter().all(Option::is_none));
    assert_eq!(machine(&game, AT).items[5].as_ref().unwrap().count, 64);
    assert_eq!(machine(&game, AT).items[9], Some(stack.clone()));
    // A distinct patch has its own unique slot; a matching output does not reserve an input.
    put(&mut game, AT, "create:basin", &[]);
    seed(
        &mut game,
        AT,
        &[
            (0, ItemStack::new("minecraft:wheat", 1)),
            (9, stack.clone()),
        ],
    );
    let identity = land(
        &mut game,
        stack.clone(),
        [4.5, 64.5, 4.5],
        [0.0, -0.3, 0.0],
        false,
    );
    assert_remainder(&game, &stack, 0, identity);
    assert_eq!(machine(&game, AT).items[1], Some(stack.clone()));
    assert_eq!(
        machine(&game, AT).items[0],
        Some(ItemStack::new("minecraft:wheat", 1))
    );
    assert_eq!(machine(&game, AT).items[9], Some(stack.clone()));
    // Basin containing-block guard: an inside rim accepts, an outside center only touches it.
    for (x, accepted) in [(4.05, true), (5.05, false)] {
        put(&mut game, AT, "create:basin", &[]);
        let before = saved(&game, AT);
        let identity = land(
            &mut game,
            stack.clone(),
            [x, 64.95, 4.5],
            [0.0, -0.3, 0.0],
            false,
        );
        assert_remainder(&game, &stack, if accepted { 0 } else { 13 }, identity);
        if !accepted {
            assert_eq!(
                game.dropped[0].position.y, 64.8125,
                "real item rim collision occurred"
            );
            assert_eq!(saved(&game, AT), before);
        }
    }
    // Millstone outer base is the here path; center/top exercises the below path.
    put(&mut game, AT, "create:millstone", &[]);
    let identity = land(
        &mut game,
        stack.clone(),
        [4.0, 64.5, 4.5],
        [0.0, -0.3, 0.0],
        false,
    );
    assert_remainder(&game, &stack, 0, identity);
    put(&mut game, AT, "create:millstone", &[]);
    put(&mut game, [4, 65, 4], "create:millstone", &[]);
    let mut full = stack.clone();
    full.count = 64;
    seed(&mut game, [4, 65, 4], &[(0, full)]);
    let lower = saved(&game, AT);
    let identity = land(
        &mut game,
        stack.clone(),
        [4.0, 65.5, 4.5],
        [0.0, -0.3, 0.0],
        false,
    );
    assert_remainder(&game, &stack, 13, identity);
    assert_eq!(saved(&game, AT), lower);
    put(&mut game, [4, 65, 4], "minecraft:air", &[]);
    put(&mut game, AT, "create:millstone", &[]);
    let invalid = ItemStack::new("minecraft:diamond_sword", 1);
    let before = saved(&game, AT);
    let identity = land(
        &mut game,
        invalid.clone(),
        [4.5, 65.1, 4.5],
        [0.0, -0.3, 0.0],
        false,
    );
    assert_remainder(&game, &invalid, 1, identity);
    assert_eq!(saved(&game, AT), before);

    // Public save encoder/early decoder hydrate canonical native slots before
    // the next collision. This is cold codec reload, not a two-process claim.
    for (id, at) in [
        ("create:basin", [4.5, 64.5, 4.5]),
        ("create:millstone", [4.5, 65.1, 4.5]),
    ] {
        put(&mut game, AT, id, &[]);
        let mut held = stack.clone();
        held.count = 63;
        seed(&mut game, AT, &[(0, held)]);
        game.native_with_mod_block_entity(AT, |e| {
            e.nbt.insert(
                "UnrecognizedRoot".into(),
                Tag::compound([("retained", Tag::Long(77))]),
            );
        })
        .unwrap();
        let key = (AT[0], AT[1], AT[2]);
        let encoded = crate::save::encode_block_entity(key, &game.world.block_entities[&key], id);
        let (loaded_pos, loaded) = crate::save::decode_block_entity(&encoded).unwrap();
        assert_eq!(loaded_pos, key);
        game.world.block_entities.insert(key, loaded);
        let identity = land(&mut game, stack.clone(), at, [0.0, -0.3, 0.0], false);
        assert_remainder(&game, &stack, 12, identity);
        assert_eq!(machine(&game, AT).items[0].as_ref().unwrap().count, 64);
        assert_eq!(
            machine(&game, AT).nbt.get(&"UnrecognizedRoot".into()),
            encoded.get("UnrecognizedRoot")
        );
    }
    // The ordinary owner in another dimension uses that dimension's actual BE.
    let overworld = std::mem::replace(&mut game.world, World::new(game.res.facts().air, 1));
    game.dim = Dim::Nether;
    game.world
        .chunks
        .insert((0, 0), Arc::new(Chunk::empty(0, 0)));
    let containers = game.native_containers();
    game.world.block_entities.set_mod_containers(containers);
    put(&mut game, AT, "create:basin", &[]);
    let identity = land(
        &mut game,
        stack.clone(),
        [4.5, 64.5, 4.5],
        [0.0, -0.3, 0.0],
        false,
    );
    assert_remainder(&game, &stack, 0, identity);
    assert_eq!(machine(&game, AT).items[0], Some(stack.clone()));
    game.dim = Dim::Overworld;
    game.world = overworld;

    // A real merged private recipe lets an idle, motor-driven Mixer start
    // only after Basin consumes its contents-changed event. Both BE orders
    // use native ticks; intake still arrives through the active ItemEntity batch.
    let scratch =
        PathBuf::from(std::env::var_os("HORIZON_HOME").unwrap()).join("contact-mixing-world");
    game.world_root = scratch.clone();
    game.session_lock = Some(horizon_client::save::SessionLock::acquire(&scratch).unwrap());
    let pack = scratch.join("datapacks/contact-test");
    let write = |path: &str, value: serde_json::Value| {
        let path = pack.join(path);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(path, serde_json::to_vec(&value).unwrap()).unwrap();
    };
    let format = horizon_core::version::DATA_PACK_FORMAT.0;
    write(
        "pack.mcmeta",
        serde_json::json!({"pack":{"min_format":format,"max_format":format,"description":"owned contact fixture"}}),
    );
    write(
        "data/demo/recipe/contact.json",
        serde_json::json!({"type":"create:mixing","ingredients":["minecraft:nether_star","minecraft:echo_shard"],"results":[{"id":"minecraft:diamond","count":1}]}),
    );
    let (tables, health) = game
        .build_world_tables(false, &["minecraft:vanilla".into()])
        .unwrap();
    game.world_tables = tables;
    game.health_resources = health;
    game.native_server_data_loaded(false);
    assert!(
        game.native_recipes_of_type("create:mixing")
            .iter()
            .any(|r| r.id == "demo:contact")
    );
    let mixer = [4, 66, 4];
    let motor = [3, 65, 4];
    // Observe the ordinary fresh factory and owner padding, without preinitializing
    // its inventory. The constructor's legitimate first wake is consumed first.
    basin::reset(false);
    crate::game::create_port_mixer::reset(false);
    put(&mut game, AT, "create:basin", &[]);
    put(&mut game, mixer, "create:mechanical_mixer", &[]);
    game.world.game_time += 1;
    game.tick_mod_block_entity((4, 64, 4));
    game.tick_mod_block_entity((4, 66, 4));
    assert_eq!(integer(&game, mixer, "NeedsUpdate"), 0);
    game.world.game_time += 1;
    game.tick_mod_block_entity((4, 64, 4));
    let padding_wake = integer(&game, mixer, "NeedsUpdate");
    println!("CONTACT_FRESH_PADDING_WAKE {padding_wake}");
    for mixer_first in [false, true] {
        basin::reset(false);
        crate::game::create_port_mixer::reset(false);
        put(&mut game, AT, "create:basin", &[("facing", "down")]);
        put(&mut game, mixer, "create:mechanical_mixer", &[]);
        put(&mut game, [3, 66, 4], "create:cogwheel", &[("axis", "y")]);
        put(
            &mut game,
            motor,
            "create:creative_motor",
            &[("facing", "up")],
        );
        game.native_with_mod_block_entity(motor, |e| {
            e.nbt.insert("ScrollValue".into(), Tag::Int(32));
        })
        .unwrap();
        seed(
            &mut game,
            AT,
            &[(0, ItemStack::new("minecraft:nether_star", 1))],
        );
        game.world.game_time += 1;
        game.tick_mod_block_entity((4, 64, 4));
        game.tick_mod_block_entity((3, 65, 4));
        game.tick_mod_block_entity((4, 66, 4));
        assert_eq!(integer(&game, mixer, "Running"), 0);
        assert_eq!(integer(&game, mixer, "NeedsUpdate"), 0);
        assert!(
            crate::game::create_port::number(&machine(&game, mixer).nbt, "Speed").abs() >= 30.0,
            "real motor must prime a powered idle Mixer"
        );
        game.world.game_time += 1;
        let input = ItemStack::new("minecraft:echo_shard", 1);
        let identity = land(
            &mut game,
            input.clone(),
            [4.5, 64.5, 4.5],
            [0.0, -0.3, 0.0],
            false,
        );
        assert_remainder(&game, &input, 0, identity);
        assert_eq!(
            integer(&game, mixer, "NeedsUpdate"),
            0,
            "contact sets Basin flag, not operator flag"
        );
        if mixer_first {
            game.tick_mod_block_entity((4, 66, 4));
            assert_eq!(
                integer(&game, mixer, "Running"),
                0,
                "Mixer may not poll new contents before Basin tick"
            );
        }
        game.tick_mod_block_entity((4, 64, 4));
        assert_eq!(integer(&game, mixer, "NeedsUpdate"), 1);
        if mixer_first {
            game.world.game_time += 1;
        }
        game.tick_mod_block_entity((4, 66, 4));
        assert_eq!(
            integer(&game, mixer, "Running"),
            1,
            "order mixer_first={mixer_first}, frozen={}, mixer={:?}, basin={:?}",
            game.clock.frozen(),
            machine(&game, mixer).nbt,
            machine(&game, AT).nbt
        );
    }
    // A notification after this clock's Basin tick survives its duplicate call.
    basin::reset(false);
    crate::game::create_port_mixer::reset(false);
    put(&mut game, AT, "create:basin", &[]);
    put(&mut game, mixer, "create:mechanical_mixer", &[]);
    seed(&mut game, AT, &[]);
    game.world.game_time += 1;
    game.tick_mod_block_entity((4, 64, 4));
    game.tick_mod_block_entity((4, 66, 4));
    assert_eq!(integer(&game, mixer, "NeedsUpdate"), 0);
    let identity = land(
        &mut game,
        stack.clone(),
        [4.5, 64.5, 4.5],
        [0.0, -0.3, 0.0],
        false,
    );
    assert_remainder(&game, &stack, 0, identity);
    game.tick_mod_block_entity((4, 64, 4));
    assert_eq!(
        integer(&game, mixer, "NeedsUpdate"),
        0,
        "duplicate tick must retain, not consume, notification"
    );
    game.world.game_time += 1;
    game.tick_mod_block_entity((4, 64, 4));
    assert_eq!(integer(&game, mixer, "NeedsUpdate"), 1);

    // Actual Remote owner tick: Basin predicts; Millstone is explicitly server-only.
    use horizon_protocol::connection::Pipe;
    game.options.dedicated = None;
    game.options.execution_role = execution_role::ExecutionRole::Client;
    game.world_tables = None;
    game.session_lock = None;
    let (client, server) = Pipe::pair();
    game.connect_local(client, "ContactPredictionProof")
        .unwrap();
    game.world = World::new(game.res.facts().air, 1);
    game.world
        .chunks
        .insert((0, 0), Arc::new(Chunk::empty(0, 0)));
    let containers = game.native_containers();
    game.world.block_entities.set_mod_containers(containers);
    for (id, at, count) in [
        ("create:basin", [4.5, 64.5, 4.5], 0),
        ("create:millstone", [4.5, 65.1, 4.5], 13),
    ] {
        put(&mut game, AT, id, &[]);
        let before = saved(&game, AT);
        let identity = land(&mut game, stack.clone(), at, [0.0, -0.3, 0.0], true);
        assert_remainder(&game, &stack, count, identity);
        if count > 0 {
            assert_eq!(saved(&game, AT), before);
        } else {
            assert_eq!(machine(&game, AT).items[0], Some(stack.clone()));
        }
    }
    server.shutdown();
    assert_eq!(
        padding_wake, 0,
        "empty factory slot padding may not synthesize a contents event"
    );
    assert!(crate::mod_api::mods().is_empty());
    println!(
        "Raw Create contact actual Game+Remote: fresh/partial/full/components/opaque/here/below/rim/above/filter and side authority PASS"
    );
}
