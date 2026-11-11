// Actual Game/WorldTables/Basin integration; no recipe or RNG host substitutes.
#[test]
#[ignore = "requires private prepared resources and the complete native mod stage"]
fn mixer_reload_actual_game_and_client_rng() {
    use super::*;
    use crate::items::ItemStack;
    use crate::game::{Audio,Game,Options,Progress,Settings,World,execution_role::ExecutionRole,load_resources};
    use crate::game::create_port_basin as basin;
    use horizon_client::{chunk::Chunk,containers::ModBlockEntityFields};
    use horizon_core::{position::BlockPos,random::LegacyRandom,version::DATA_PACK_FORMAT};
    use horizon_protocol::connection::Pipe;
    use horizon_world::registry::BlockStateId;
    use std::path::PathBuf;
    let vanilla=PathBuf::from(std::env::var_os("HORIZON_TEST_RESOURCES").unwrap());
    let scratch=PathBuf::from(std::env::var_os("HORIZON_HOME").unwrap()).join("mixer-reload-world");
    let mut settings=Settings::default();settings.mods.enabled.insert("create".into());
    crate::game::mods::register_components(&vanilla).unwrap();crate::game::mods::register_standalone_models();
    let root=crate::game::mods::content_root(&vanilla,&settings.mods.enabled,&[]);
    let loaded=load_resources(root.clone(),None,&vanilla,&settings,std::time::Instant::now(),false,true,&Progress::new(),&mut|_,_|unreachable!()).unwrap();
    let mut options=Options::parse(std::iter::empty()).unwrap().unwrap();options.resources=root.clone();options.execution_role=ExecutionRole::IntegratedServer;
    let mut game=Game::new(&loaded.resources,loaded.pack,loaded.gui.unwrap(),options,settings,Audio::silent(&root),None).unwrap();
    game.options.dedicated=Some(Vec::new());game.world_root=scratch.clone();
    game.session_lock=Some(horizon_client::save::SessionLock::acquire(&scratch).unwrap());
    let (tables,health)=game.build_world_tables(false,&["minecraft:vanilla".into()]).unwrap();game.world_tables=tables;game.health_resources=health;
    game.native_server_data_loaded(false);
    let pack=scratch.join("datapacks/mixer-reload");
    let write=|path:&str,value:serde_json::Value|{let file=pack.join(path);std::fs::create_dir_all(file.parent().unwrap()).unwrap();std::fs::write(file,serde_json::to_vec(&value).unwrap()).unwrap();};
    let format=DATA_PACK_FORMAT.0;
    write("pack.mcmeta",serde_json::json!({"pack":{"min_format":format,"max_format":format,"description":"bounded mixer reload proof"}}));
    // Ordinary Horizon pack policy: a valid world with no custom mixing pool.
    write("data/demo/recipe_filter/mixing.json",serde_json::json!({"filters":[{"type":"create:mixing","remove":true}]}));
    let definition=|output:&str|serde_json::json!({"type":"minecraft:crafting_shapeless","ingredients":["#demo:mixer_input","minecraft:cobblestone"],"result":{"id":output,"count":1}});
    write("data/demo/recipe/reload_test.json",definition("minecraft:diamond"));
    write("data/demo/tags/item/mixer_input.json",serde_json::json!({"replace":true,"values":["minecraft:stick"]}));
    game.reload_datapacks(true);
    assert!(game.native_recipes_of_type("create:mixing").is_empty());
    game.world=World::new(game.res.facts().air,1);game.world.chunks.insert((0,0),Arc::new(Chunk::empty(0,0)));
    let basin_pos=[1,70,1];let mixer_pos=[1,72,1];
    let basin_state=game.pack.assets.registry.default_state("create:basin").unwrap();
    let basin_state=game.pack.assets.registry.state(basin_state).unwrap().clone();
    let basin_state=(0..game.pack.assets.registry.len() as u32).map(BlockStateId).find(|id|{let state=game.pack.assets.registry.state(*id).unwrap();state.name==basin_state.name&&state.properties.get("facing").map(String::as_str)==Some("down")}).unwrap();
    game.world.set(1,70,1,basin_state).unwrap();game.world.set(1,72,1,game.pack.assets.registry.default_state(ID).unwrap()).unwrap();
    let fresh=game.new_block_entity_for_state(basin_state).unwrap();game.world.block_entities.insert((1,70,1),fresh);
    let fresh=game.new_block_entity_for_state(game.pack.assets.registry.default_state(ID).unwrap()).unwrap();game.world.block_entities.insert((1,72,1),fresh);
    let seed=|game:&mut Game<'_>,item:&str|{game.native_with_mod_block_entity(basin_pos,|e|{basin::initialize(e);e.items=vec![None;18];e.items[0]=Some(ItemStack::new(item,1));e.items[1]=Some(ItemStack::new("minecraft:cobblestone",1));basin::data(e);});};
    let output=|game:&Game<'_>|{let BlockEntity::Mod(e)=&game.world.block_entities[&(1,70,1)]else{unreachable!()};e.items.iter().flatten().map(|s|(s.item.to_string(),s.count)).collect::<Vec<_>>()};
    seed(&mut game,"minecraft:stick");
    let mut state=basin::read(&game,basin_pos).unwrap();let first=choose(&mut game,basin_pos,&mut state).expect("initial shapeless recipe");
    assert_eq!(first.id,"demo:reload_test");assert_eq!(first.core.outputs[0].stack.key.0.item.as_ref(),"minecraft:diamond");
    let owner=match &game.world.block_entities[&(1,72,1)]{BlockEntity::Mod(e)=>e.revision(),_=>unreachable!()};
    with_world(&game,|world|{world.running.insert(mixer_pos,Running{owner:Some(owner),cycle:rules::Mixer{running:true,ticks:20,processing_ticks:1},recipe:Some(first.clone()),..Default::default()});});
    game.native_with_mod_block_entity(mixer_pos,|e|{e.nbt.insert("Running".into(),Tag::Byte(1));e.nbt.insert("Ticks".into(),Tag::Int(20));});
    let address=std::ptr::from_ref(game.recipes())as usize;
    write("data/demo/recipe/reload_test.json",definition("minecraft:emerald"));
    game.reload_datapacks(true);
    assert_eq!(std::ptr::from_ref(game.recipes())as usize,address,"the address is not a table generation");
    assert!(game.native_recipes_of_type("create:mixing").is_empty());
    with_world(&game,|world|{let run=&world.running[&mixer_pos];assert!(Arc::ptr_eq(run.recipe.as_ref().unwrap(),&first));assert_eq!(run.cycle.processing_ticks,1);});
    let mut old=basin::read(&game,basin_pos).unwrap();
    let updated=choose(&mut game,basin_pos,&mut old).unwrap();
    assert_eq!(updated.core.outputs[0].stack.key.0.item.as_ref(),"minecraft:emerald","new lookup retained the pre-reload tag/recipe");
    // Source checkBasin returns while running; applyBasinRecipe uses the
    // existing currentRecipe object. Its last real tick must finish old output.
    game.world.game_time=1;
    let BlockEntity::Mod(mut mixer)=game.world.block_entities.remove(&(1,72,1)).unwrap()else{unreachable!()};
    tick(&mut game,mixer_pos,&mut mixer,32.0);game.world.block_entities.insert((1,72,1),BlockEntity::Mod(mixer));
    assert_eq!(output(&game),vec![("minecraft:diamond".into(),1)]);
    // Test tag rebinding separately: no claim that an in-flight Java tag
    // Ingredient snapshots its old holder members across a resource reload.
    write("data/demo/tags/item/mixer_input.json",serde_json::json!({"replace":true,"values":["minecraft:coal"]}));
    game.reload_datapacks(true);
    seed(&mut game,"minecraft:stick");let mut obsolete=basin::read(&game,basin_pos).unwrap();assert!(choose(&mut game,basin_pos,&mut obsolete).is_none());
    seed(&mut game,"minecraft:coal");let mut state=basin::read(&game,basin_pos).unwrap();let next=choose(&mut game,basin_pos,&mut state).expect("new tag and recipe admitted");
    assert_eq!(next.core.outputs[0].stack.key.0.item.as_ref(),"minecraft:emerald");
    let _=apply(&mut game,basin_pos,Some(&next));assert_eq!(output(&game),vec![("minecraft:emerald".into(),1)]);

    // Actual GameLevel comparator boundary with an intentionally short native
    // object. Normal canonical decoder results are already18slots; this is a
    // fail-closed native creation guarantee, not edited Java Size compatibility.
    let opaque=horizon_world::nbt::Compound::from([
        ("InputItems".into(),Tag::compound([("Size",Tag::Int(1)),("Unknown",Tag::compound([("retain",Tag::Long(923))]))])),
        ("root_unknown".into(),Tag::ByteArray(vec![255,2,3])),
    ]);
    let unsupported=ModBlockEntity::new(ModBlockEntityFields{id:"create:basin".into(),nbt:opaque.clone(),..Default::default()});
    let revision=unsupported.revision();game.world.block_entities.insert((1,70,1),BlockEntity::Mod(Box::new(unsupported)));
    let mut analog=99;game.with_level(|_,level,_|basin::analog(level,BlockPos::new(1,70,1),basin_state,&mut analog));assert_eq!(analog,0);
    let BlockEntity::Mod(e)=&game.world.block_entities[&(1,70,1)]else{unreachable!()};assert!(e.items.is_empty());assert_eq!(e.nbt,opaque);assert_eq!(e.revision(),revision);

    // Actual client Game emits one item request. Only particle construction is
    // intercepted; this tests the source ClientLevel RNG identity/continuation,
    // not sprite rendering or constructor RNG parity.
    game.options.dedicated=None;game.options.execution_role=ExecutionRole::Client;game.session_lock=None;game.world_tables=None;
    let(client,server)=Pipe::pair();game.connect_local(client,"MixerRngProof").unwrap();
    game.world=World::new(game.res.facts().air,1);game.world.chunks.insert((0,0),Arc::new(Chunk::empty(0,0)));
    game.world.set(1,70,1,basin_state).unwrap();game.world.set(1,72,1,game.pack.assets.registry.default_state(ID).unwrap()).unwrap();
    let fresh=game.new_block_entity_for_state(basin_state).unwrap();game.world.block_entities.insert((1,70,1),fresh);
    seed(&mut game,"minecraft:stick");game.native_with_mod_block_entity(basin_pos,|e|{e.items[1]=None;basin::data(e);});
    let fresh=game.new_block_entity_for_state(game.pack.assets.registry.default_state(ID).unwrap()).unwrap();game.world.block_entities.insert((1,72,1),fresh);
    game.native_with_mod_block_entity(mixer_pos,|e|{e.nbt.insert("Running".into(),Tag::Byte(1));e.nbt.insert("Ticks".into(),Tag::Int(20));e.nbt.insert("Speed".into(),Tag::Float(32f32.to_bits()));});
    reset(false);game.world.game_time=1000;
    game.world.random=LegacyRandom::new(81);let server_random=game.world.random.state();
    *game.particles.level_random()=LegacyRandom::new(923);let mut expected=LegacyRandom::new(923);for _ in 0..4{expected.next_float();}
    assert!(game.native_window() && game.remote.is_some() && game.native_on("create"));
    let available=basin::read(&game,basin_pos).expect("client sees real supported Basin state");
    assert_eq!(available.input.iter().flatten().map(|s|s.count).sum::<u32>(),1);
    let BlockEntity::Mod(mixer)=&game.world.block_entities[&(1,72,1)]else{unreachable!()};assert_eq!(saved(mixer),(true,20));
    game.particles.requested=Some(Vec::new());client_tick(&mut game);
    assert_eq!(game.particles.level_random().state(),expected.state(),"emission must advance ClientLevel.random by four draws");
    assert_eq!(game.world.random.state(),server_random,"client emission must not use server/world simulation RNG");
    let requested=game.particles.requested.as_ref().unwrap();assert_eq!(requested.len(),1);assert_eq!(requested[0].0.ty,horizon_client::particles::ParticleType::Item);
    server.shutdown();
    println!("Mixer actual Game: reload/new-tag/new-output + in-flight old output + opaque analog + client RNG PASS");
}
