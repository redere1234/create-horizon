// Actual full-mod Game integration. This file is included inside
// create_port_mixer in a caller-owned official source-woven stage.
#[test]
#[ignore = "requires private prepared resources and the complete source-woven native mod stage"]
fn mixer_deferred_scheduling_actual_game() {
    use super::*;
    use crate::items::ItemStack;
    use crate::game::{
        Audio, Game, Options, Progress, Settings, World, execution_role::ExecutionRole,
        load_resources,
    };
    use horizon_client::{
        chunk::Chunk,
        mod_api::{NativeFluidAction, NativeFluidDrain, NativeFluidStack},
    };
    use horizon_core::{random::LegacyRandom, version::DATA_PACK_FORMAT};
    use horizon_world::{nbt::Compound, registry::BlockStateId};
    use std::path::PathBuf;

    const B: Pos = [1, 70, 1];
    const M: Pos = [1, 72, 1];
    fn mixer<'a>(game: &'a Game<'_>) -> &'a ModBlockEntity {
        let BlockEntity::Mod(e) = &game.world.block_entities[&(M[0], M[1], M[2])] else {
            unreachable!()
        };
        e
    }
    fn snapshot(game: &Game<'_>) -> (Compound, Vec<Option<ItemStack>>, ModRevision) {
        let BlockEntity::Mod(e) = &game.world.block_entities[&(1, 70, 1)] else {
            unreachable!()
        };
        (e.nbt.clone(), e.items.clone(), e.revision())
    }
    fn edit(game: &mut Game<'_>, f: impl FnOnce(&mut ModBlockEntity)) {
        game.native_with_mod_block_entity(M, f).unwrap();
    }
    fn mixer_tick(game: &mut Game<'_>, rpm: f32) {
        let BlockEntity::Mod(mut entity) = game
            .world
            .block_entities
            .remove(&(M[0], M[1], M[2]))
            .unwrap()
        else {
            unreachable!()
        };
        tick(game, M, &mut entity, rpm);
        game.world
            .block_entities
            .insert((M[0], M[1], M[2]), BlockEntity::Mod(entity));
    }
    fn basin_tick(game: &mut Game<'_>) {
        let BlockEntity::Mod(mut entity) = game
            .world
            .block_entities
            .remove(&(B[0], B[1], B[2]))
            .unwrap()
        else {
            unreachable!()
        };
        basin::tick(game, B, &mut entity);
        game.world
            .block_entities
            .insert((B[0], B[1], B[2]), BlockEntity::Mod(entity));
    }
    fn pair(game: &mut Game<'_>, state: BlockStateId, prime: bool) {
        reset(false);
        basin::reset(false);
        game.world.game_time += 1000;
        game.world.set(B[0], B[1], B[2], state).unwrap();
        game.world
            .set(
                M[0],
                M[1],
                M[2],
                game.pack.assets.registry.default_state(ID).unwrap(),
            )
            .unwrap();
        let entity = game.new_block_entity_for_state(state).unwrap();
        game.world.block_entities.insert((B[0], B[1], B[2]), entity);
        let entity = game
            .new_block_entity_for_state(game.pack.assets.registry.default_state(ID).unwrap())
            .unwrap();
        game.world.block_entities.insert((M[0], M[1], M[2]), entity);
        game.native_with_mod_block_entity(B, basin::initialize)
            .unwrap();
        edit(game, |e| {
            initialize(e);
            e.nbt.insert("Speed".into(), Tag::Float(32f32.to_bits()));
            e.nbt.insert("NeedsUpdate".into(), Tag::Byte(0));
        });
        if prime {
            basin_tick(game);
            mixer_tick(game, 32.0);
            assert_eq!(saved(mixer(game)), (false, 0));
            game.world.game_time += 1;
        }
    }
    fn insert(game: &mut Game<'_>, count: u32) {
        game.native_with_mod_block_entity(B, |e| {
            e.items[0] = Some(ItemStack::new("minecraft:nether_star", count));
            e.items[1] = Some(ItemStack::new("minecraft:echo_shard", count));
            basin::data(e);
        })
        .unwrap();
    }
    fn idle(game: &mut Game<'_>, context: &str) {
        let rng = game.world.random.state();
        mixer_tick(game, 32.0);
        assert_eq!(
            saved(mixer(game)),
            (false, 0),
            "premature Mixer start: {context}"
        );
        assert_eq!(
            game.world.random.state(),
            rng,
            "premature recipe simulation RNG: {context}"
        );
    }
    fn pending(game: &Game<'_>) -> i32 {
        super::super::create_port::integer(&mixer(game).nbt, "NeedsUpdate")
    }
    fn fill(game: &mut Game<'_>, amount: i32, action: NativeFluidAction) -> Option<i32> {
        let mut out = None;
        game.native_custom_fluid_fill(
            B,
            None,
            &NativeFluidStack {
                fluid: "minecraft:water".into(),
                amount,
                components: Compound::new(),
            },
            action,
            &mut out,
        );
        out
    }
    let vanilla = PathBuf::from(std::env::var_os("HORIZON_TEST_RESOURCES").unwrap());
    let scratch =
        PathBuf::from(std::env::var_os("HORIZON_HOME").unwrap()).join("mixer-schedule-world");
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
    let pack = scratch.join("datapacks/mixer-schedule");
    let write = |path: &str, value: serde_json::Value| {
        let file = pack.join(path);
        std::fs::create_dir_all(file.parent().unwrap()).unwrap();
        std::fs::write(file, serde_json::to_vec(&value).unwrap()).unwrap();
    };
    let format = DATA_PACK_FORMAT.0;
    write(
        "pack.mcmeta",
        serde_json::json!({"pack":{"min_format":format,"max_format":format,"description":"bounded deferred Mixer scheduling"}}),
    );
    let recipe = |chance: f32| serde_json::json!({"type":"create:mixing","ingredients":["minecraft:nether_star","minecraft:echo_shard"],"results":[{"id":"minecraft:diamond","count":1,"chance":chance}]});
    write("data/demo/recipe/schedule.json", recipe(0.5));
    game.reload_datapacks(true);
    assert!(
        horizon_client::mod_api::mods().is_empty(),
        "fixture must exercise official source weaving, without a trait-hook substitute"
    );
    assert!(
        game.native_recipes_of_type("create:mixing")
            .iter()
            .any(|r| r.id == "demo:schedule")
    );
    game.world = World::new(game.res.facts().air, 1);
    game.world
        .chunks
        .insert((0, 0), Arc::new(Chunk::empty(0, 0)));
    let containers = game.native_containers();
    game.world.block_entities.set_mod_containers(containers);
    let state = (0..game.pack.assets.registry.len() as u32)
        .map(BlockStateId)
        .find(|id| {
            let s = game.pack.assets.registry.state(*id).unwrap();
            s.name == "create:basin"
                && s.properties.get("facing").map(String::as_str) == Some("down")
        })
        .unwrap();

    // Ordinary native inventory changes use the actual container_changed raw
    // hook. They only raise Basin's flag, for BOTH controlled BE tick orders.
    for basin_first in [false, true] {
        pair(&mut game, state, true);
        insert(&mut game, 1);
        game.world.random = LegacyRandom::new(923);
        assert_eq!(pending(&game), 0);
        if !basin_first {
            idle(&mut game, "accepted inventory, Mixer before Basin");
        }
        basin_tick(&mut game);
        assert_eq!(
            pending(&game),
            1,
            "accepted inventory must schedule only at Basin.tick"
        );
        if !basin_first {
            game.world.game_time += 1;
        }
        let before = game.world.random.state();
        mixer_tick(&mut game, 32.0);
        assert!(saved(mixer(&game)).0);
        assert_ne!(
            game.world.random.state(),
            before,
            "chance recipe proves real lookup ran after Basin.tick"
        );
    }

    // Native no-op/refusal preserves state and does not wake. A net-zero pair
    // of real mutations DOES wake even though the final contents compare equal.
    pair(&mut game, state, true);
    let before = snapshot(&game);
    game.native_with_mod_block_entity(B, |_| ()).unwrap();
    assert_eq!(snapshot(&game), before);
    basin_tick(&mut game);
    assert_eq!(pending(&game), 0);
    insert(&mut game, 1);
    game.native_with_mod_block_entity(B, |e| {
        e.items.fill(None);
        basin::data(e);
    })
    .unwrap();
    game.world.game_time += 1;
    basin_tick(&mut game);
    assert_eq!(
        pending(&game),
        1,
        "net-zero inventory events cannot be lost to snapshot polling"
    );
    game.world.game_time += 1;
    idle(&mut game, "net-zero contents");

    // Fluid capability simulation/refusal is observationally read-only. A
    // successful execute waits for Basin.tick; draining back to empty still
    // carries the event. This uses source-woven normal capability dispatch.
    pair(&mut game, state, true);
    let before = snapshot(&game);
    assert_eq!(
        fill(&mut game, 1000, NativeFluidAction::Simulate),
        Some(1000)
    );
    assert_eq!(fill(&mut game, 0, NativeFluidAction::Execute), Some(0));
    assert_eq!(snapshot(&game), before);
    basin_tick(&mut game);
    assert_eq!(pending(&game), 0);
    assert_eq!(
        fill(&mut game, 1000, NativeFluidAction::Execute),
        Some(1000)
    );
    idle(&mut game, "successful fluid execute before Basin tick");
    game.world.game_time += 1;
    basin_tick(&mut game);
    assert_eq!(pending(&game), 1);
    game.world.game_time += 1;
    idle(&mut game, "water has no matching recipe");
    let before = snapshot(&game);
    assert_eq!(fill(&mut game, 1, NativeFluidAction::Execute), Some(0));
    assert_eq!(
        snapshot(&game),
        before,
        "full matching tank refusal is read-only"
    );
    game.world.game_time += 1;
    basin_tick(&mut game);
    assert_eq!(
        pending(&game),
        0,
        "refused full-tank fill cannot raise a contents event"
    );
    let mut drained = None;
    game.native_custom_fluid_drain(
        B,
        None,
        &NativeFluidDrain::Any(1000),
        NativeFluidAction::Execute,
        &mut drained,
    );
    assert_eq!(drained.unwrap().amount, 1000);
    assert_eq!(pending(&game), 0);
    game.world.game_time += 1;
    basin_tick(&mut game);
    assert_eq!(pending(&game), 1);

    // The original Java accepts these public /data inventory encodings but
    // does NOT set Basin.contentsChanged. Exercise the real command decoder,
    // preserving the same native BE birth, and normalize on the real next
    // Basin tick without synthesizing a recipe lookup/schedule event.
    for (size, slots, counts, descending) in [
        ("9", ["0", "1"], "1", false),
        ("9", ["0", "1"], "1", true),
        ("9", ["0b", "1b"], "1", false),
        ("9s", ["0", "1"], "1b", false),
    ] {
        pair(&mut game, state, true);
        let original = snapshot(&game).2;
        let mut entries = [
            format!(
                "{{Slot:{},id:\"minecraft:nether_star\",count:{counts}}}",
                slots[0]
            ),
            format!(
                "{{Slot:{},id:\"minecraft:echo_shard\",count:{counts}}}",
                slots[1]
            ),
        ];
        if descending {
            entries.reverse();
        }
        let command = format!(
            "data merge block 1 70 1 {{InputItems:{{Size:{size},Items:[{}]}},OutputItems:{{Size:9,Items:[]}},fixture_unknown:{{retained:923L}}}}",
            entries.join(",")
        );
        // Match the ordinary command harness/control source: a fresh Game
        // has no player cheats, while these fixture commands are console IO.
        assert!(
            game.as_console(|game| game.run_command(&command)),
            "{command}"
        );
        let loaded = snapshot(&game);
        assert!(original.same_entity(loaded.2));
        assert_eq!(
            loaded.1[0].as_ref().unwrap().item.as_ref(),
            "minecraft:nether_star"
        );
        assert_eq!(
            loaded.1[1].as_ref().unwrap().item.as_ref(),
            "minecraft:echo_shard"
        );
        assert_eq!(loaded.1.iter().flatten().map(|s| s.count).sum::<u32>(), 2);
        let encoded = loaded.0.get(&"InputItems".into()).cloned();
        assert_eq!(pending(&game), 0);
        idle(&mut game, "real /data load before Basin tick");
        basin_tick(&mut game);
        assert_eq!(
            pending(&game),
            0,
            "serialization normalization is not a Basin contents event"
        );
        let normalized = snapshot(&game);
        assert!(original.same_entity(normalized.2));
        assert_eq!(normalized.1, loaded.1);
        assert_eq!(
            normalized.0.get(&"fixture_unknown".into()),
            loaded.0.get(&"fixture_unknown".into())
        );
        if descending || slots[0] != "0" || size != "9" {
            assert_ne!(
                normalized.0.get(&"InputItems".into()).cloned(),
                encoded,
                "fixture must really normalize accepted data"
            );
        }
        game.world.game_time += 1;
        idle(&mut game, "real /data load after Basin normalization");
        edit(&mut game, |entity| on_speed_changed(entity, 32.0, 64.0));
        game.world.game_time += 1;
        mixer_tick(&mut game, 64.0);
        assert!(
            saved(mixer(&game)).0,
            "same decoded recipe is eligible after a real speed-change notification"
        );
    }

    // DeferralBehaviour.read ASSIGNS NeedsUpdate. An absent or explicit false
    // canonical field clears a scheduled event on the same live BE identity.
    for remove in [false, true] {
        pair(&mut game, state, true);
        insert(&mut game, 1);
        basin_tick(&mut game);
        assert_eq!(pending(&game), 1);
        let owner = mixer(&game).revision();
        edit(&mut game, |e| {
            if remove {
                e.nbt.remove(&"NeedsUpdate".into());
            } else {
                e.nbt.insert("NeedsUpdate".into(), Tag::Byte(0));
            }
        });
        assert!(owner.same_entity(mixer(&game).revision()));
        game.world.game_time += 1;
        idle(&mut game, "canonical false/removal clears deferred flag");
    }

    // A new source Basin schedules on its first tick. Merely observing a
    // loaded powered Mixer is not onSpeedChanged and must not schedule it.
    pair(&mut game, state, false);
    insert(&mut game, 1);
    game.world.random = LegacyRandom::new(923);
    idle(&mut game, "fresh Mixer before first Basin tick");
    basin_tick(&mut game);
    assert_eq!(pending(&game), 1);
    game.world.game_time += 1;
    mixer_tick(&mut game, 32.0);
    assert!(saved(mixer(&game)).0);
    for (previous, current, wakes) in [
        (32.0, 32.0, false),
        (0.0, 32.0, true),
        (32.0, 0.0, true),
        (128.0, 0.0, true),
        (0.0, 128.0, true),
    ] {
        pair(&mut game, state, true);
        insert(&mut game, 1);
        edit(&mut game, |e| on_speed_changed(e, previous, current));
        assert_eq!(pending(&game), i32::from(wakes));
        mixer_tick(&mut game, current);
        assert_eq!(saved(mixer(&game)).0, wakes && current != 0.0);
    }

    // Real native recipe/inventory application preserves the pinned first
    // batch tick83 and repeated batch interval62 relative to startProcessing.
    write("data/demo/recipe/schedule.json", recipe(1.0));
    game.reload_datapacks(true);
    pair(&mut game, state, true);
    insert(&mut game, 2);
    basin_tick(&mut game);
    let mut applied = Vec::new();
    let mut previous = 0;
    for step in 1..=145 {
        game.world.game_time += 1;
        mixer_tick(&mut game, 32.0);
        basin_tick(&mut game);
        let BlockEntity::Mod(b) = &game.world.block_entities[&(1, 70, 1)] else {
            unreachable!()
        };
        let count = b
            .items
            .iter()
            .flatten()
            .filter(|s| s.item.as_ref() == "minecraft:diamond")
            .map(|s| s.count)
            .sum::<u32>();
        if count != previous {
            applied.push(step);
            previous = count;
        }
    }
    assert_eq!(applied, vec![83, 145]);
    assert_eq!(previous, 2);
    println!(
        "Mixer deferred actual Game PASS: native item both orders, no-op/net-zero, fluid simulate/refuse/execute/drain, canonical flag clear, initial/speed controls, cycles83/62"
    );
}
