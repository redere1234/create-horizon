// Shared Basin recipe integration against actual Game/WorldTables/ItemStack codecs.
// Included inside create_port_basin_recipes only by the private test driver.
#[test]
#[ignore = "requires private prepared resources and the complete source-woven mod"]
fn basin_recipe_operators_reload_and_compacting_actual_game() {
    use super::*;
    use crate::game::{
        Audio, Game, Options, Progress, Settings, World, execution_role::ExecutionRole,
        load_resources,
    };
    use horizon_client::{chunk::Chunk, containers::BlockEntity};
    use horizon_core::version::DATA_PACK_FORMAT;
    use std::path::PathBuf;

    let vanilla = PathBuf::from(std::env::var_os("HORIZON_TEST_RESOURCES").unwrap());
    let scratch = PathBuf::from(std::env::var_os("HORIZON_HOME").unwrap()).join("basin-recipes");
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
    let pos = [1, 70, 1];
    let state = (0..game.pack.assets.registry.len() as u32)
        .map(horizon_world::registry::BlockStateId)
        .find(|id| {
            let state = game.pack.assets.registry.state(*id).unwrap();
            state.name == "create:basin"
                && state.properties.get("facing").map(String::as_str) == Some("down")
        })
        .unwrap();
    game.world.set(pos[0], pos[1], pos[2], state).unwrap();
    let fresh = game.new_block_entity_for_state(state).unwrap();
    game.world
        .block_entities
        .insert((pos[0], pos[1], pos[2]), fresh);
    let pack = scratch.join("datapacks/basin-recipes");
    let write = |path: &str, value: serde_json::Value| {
        let file = pack.join(path);
        std::fs::create_dir_all(file.parent().unwrap()).unwrap();
        std::fs::write(file, serde_json::to_vec(&value).unwrap()).unwrap();
    };
    write(
        "pack.mcmeta",
        serde_json::json!({"pack": {
            "min_format": DATA_PACK_FORMAT.0, "max_format": DATA_PACK_FORMAT.0,
            "description": "Basin operator/recipe generation regression"
        }}),
    );
    let basin_recipe = |kind: &str, output: &str| {
        serde_json::json!({
            "type": kind, "ingredients": ["minecraft:stick"], "results": [{"id": output}]
        })
    };
    write(
        "data/demo/recipe/one_mix.json",
        basin_recipe("create:mixing", "minecraft:emerald"),
    );
    write(
        "data/demo/recipe/one_compact.json",
        basin_recipe("create:compacting", "minecraft:diamond"),
    );
    let shaped = |output: &str| {
        serde_json::json!({
            "type":"minecraft:crafting_shaped", "pattern":["##","##"],
            "key":{"#":"minecraft:feather"}, "result":{"id":output}
        })
    };
    write("data/demo/recipe/square.json", shaped("minecraft:diamond"));
    write(
        "data/demo/recipe/hollow.json",
        serde_json::json!({
            "type":"minecraft:crafting_shaped", "pattern":["# #","   ","# #"],
            "key":{"#":"minecraft:feather"}, "result":{"id":"minecraft:emerald"}
        }),
    );
    write(
        "data/demo/recipe/ignored_manual_only.json",
        serde_json::json!({
            "type":"minecraft:crafting_shapeless", "ingredients":vec!["minecraft:paper";4],
            "result":{"id":"minecraft:diamond"}
        }),
    );
    write(
        "data/demo/recipe/same_shapeless.json",
        serde_json::json!({
            "type":"minecraft:crafting_shapeless", "ingredients":vec!["minecraft:flint";4],
            "result":{"id":"minecraft:gold_ingot"}
        }),
    );
    write(
        "data/demo/recipe/different_order.json",
        serde_json::json!({
            "type":"minecraft:crafting_shapeless", "ingredients":[
                ["minecraft:flint","minecraft:stick"], ["minecraft:stick","minecraft:flint"],
                ["minecraft:flint","minecraft:stick"], ["minecraft:flint","minecraft:stick"]],
            "result":{"id":"minecraft:copper_ingot"}
        }),
    );
    game.reload_datapacks(true);
    let ids = |game: &Game<'_>, operator| {
        recipes(game, operator)
            .into_iter()
            .map(|r| r.id.clone())
            .collect::<std::collections::BTreeSet<_>>()
    };
    let mixing = ids(&game, Operator::Mixing);
    let compacting = ids(&game, Operator::Compacting);
    for id in ["demo:one_mix", "demo:different_order"] {
        assert!(mixing.contains(id), "missing Mixer recipe {id}");
        assert!(
            !compacting.contains(id),
            "Mixer recipe leaked into Press: {id}"
        );
    }
    for id in ["demo:one_compact", "demo:square", "demo:same_shapeless"] {
        assert!(compacting.contains(id), "missing Press recipe {id}");
        assert!(!mixing.contains(id), "Press recipe leaked into Mixer: {id}");
    }
    for id in ["demo:hollow", "demo:ignored_manual_only"] {
        assert!(
            !mixing.contains(id) && !compacting.contains(id),
            "unsupported crafting accepted: {id}"
        );
    }
    let seed = |game: &mut Game<'_>, item: &str, count| {
        game.native_with_mod_block_entity(pos, |e| {
            basin::initialize(e);
            e.items = vec![None; 18];
            e.items[0] = Some(ItemStack::new(item, count));
            basin::data(e);
        })
        .unwrap();
    };
    seed(&mut game, "minecraft:stick", 1);
    for (operator, expected) in [
        (Operator::Mixing, "minecraft:emerald"),
        (Operator::Compacting, "minecraft:diamond"),
    ] {
        let mut state = basin::read(&game, pos).unwrap();
        let recipe = choose(&mut game, pos, &mut state, operator).unwrap();
        assert_eq!(recipe.core.outputs[0].stack.key.0.item.as_ref(), expected);
    }
    // Exact bounded fluid/ingredient codecs fail closed for unsupported fields.
    let invalid = [
        serde_json::json!({"type":"neoforge:tag","tag":"minecraft:lava","amount":100}),
        serde_json::json!({"type":"neoforge:single","fluid":"minecraft:lava","amount":100,"components":{}}),
        serde_json::json!({"item":"minecraft:flint","unknown_predicate":true}),
    ];
    for ingredient in invalid {
        let recipe = serde_json::json!({"type":"create:compacting","ingredients":[ingredient],"results":[{"id":"minecraft:andesite"}]});
        assert!(
            compile(&game, "demo:unsupported", &recipe).is_none(),
            "unsupported predicate was weakened"
        );
    }
    // Positive water/lava singles keep their real amount and consume actual
    // Basin storage, with the complete key/component semantics in the core.
    let definition = serde_json::json!({"type":"create:compacting","ingredients":[
        "minecraft:flint","minecraft:flint","minecraft:gravel",
        {"type":"neoforge:single","fluid":"minecraft:lava","amount":100}],
        "results":[{"id":"minecraft:andesite"}]});
    let recipe = compile(&game, "demo:andesite", &definition).unwrap();
    assert_eq!(recipe.core.fluid_amounts, [100]);
    seed(&mut game, "minecraft:flint", 2);
    let mut state = basin::read(&game, pos).unwrap();
    state.input[1] = Some(basin::core_stack(
        &game,
        &ItemStack::new("minecraft:gravel", 1),
    ));
    state.input_fluids[0] = Some(rules::Fluid {
        key: fluids::Key {
            id: "minecraft:lava".into(),
            components: Default::default(),
        },
        amount: 100,
    });
    basin::write(&mut game, pos, &state);
    assert!(matching(&mut game, pos, &mut state, &recipe));
    let _ = apply(&mut game, pos, Some(&recipe));
    let consumed = basin::read(&game, pos).unwrap();
    assert!(consumed.input.iter().all(Option::is_none));
    assert!(consumed.input_fluids.iter().all(Option::is_none));
    assert_eq!(
        consumed
            .output
            .iter()
            .flatten()
            .map(|s| (s.key.0.item.as_ref(), s.count))
            .collect::<Vec<_>>(),
        [("minecraft:andesite", 1)]
    );

    // Empty custom pools cannot invalidate a same-address vanilla table by
    // Arc identity. Both operators must observe the shared reload generation.
    for kind in ["mixing", "compacting"] {
        write(
            &format!("data/demo/recipe_filter/{kind}.json"),
            serde_json::json!({"filters":[{"type":format!("create:{kind}"),"remove":true}]}),
        );
    }
    let vanilla_mix = |output: &str| serde_json::json!({"type":"minecraft:crafting_shapeless","ingredients":["minecraft:stick","minecraft:cobblestone"],"result":{"id":output}});
    write(
        "data/demo/recipe/reload_compact.json",
        shaped("minecraft:diamond"),
    );
    write(
        "data/demo/recipe/reload_mix.json",
        vanilla_mix("minecraft:diamond"),
    );
    game.reload_datapacks(true);
    assert!(game.native_recipes_of_type("create:mixing").is_empty());
    assert!(game.native_recipes_of_type("create:compacting").is_empty());
    let find = |game: &Game<'_>, operator, id: &str| {
        recipes(game, operator)
            .into_iter()
            .find(|r| r.id == id)
            .unwrap()
    };
    let old_press = find(&game, Operator::Compacting, "demo:reload_compact");
    let old_mix = find(&game, Operator::Mixing, "demo:reload_mix");
    let address = std::ptr::from_ref(game.recipes()) as usize;
    write(
        "data/demo/recipe/reload_compact.json",
        shaped("minecraft:emerald"),
    );
    write(
        "data/demo/recipe/reload_mix.json",
        vanilla_mix("minecraft:emerald"),
    );
    game.reload_datapacks(true);
    assert_eq!(std::ptr::from_ref(game.recipes()) as usize, address);
    for (operator, id, old) in [
        (Operator::Compacting, "demo:reload_compact", old_press),
        (Operator::Mixing, "demo:reload_mix", old_mix),
    ] {
        let new = find(&game, operator, id);
        assert!(!Arc::ptr_eq(&old, &new));
        assert_eq!(
            old.core.outputs[0].stack.key.0.item.as_ref(),
            "minecraft:diamond"
        );
        assert_eq!(
            new.core.outputs[0].stack.key.0.item.as_ref(),
            "minecraft:emerald"
        );
    }
    let BlockEntity::Mod(entity) = &game.world.block_entities[&(pos[0], pos[1], pos[2])] else {
        unreachable!()
    };
    assert_eq!(entity.id, "create:basin");
    println!(
        "Basin actual Game: operator partition, exact crafting filters, strict ingredient codecs, lava consumption and both vanilla-only reload generations PASS"
    );
}
