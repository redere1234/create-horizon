#[test]
#[ignore = "requires private prepared resources; full official native-mod stage"]
fn burner_sync_actual_merged_reload_and_client_prediction() {
    use super::*;
    use crate::game::{
        Audio, Game, Options, Progress, Settings, World, execution_role::ExecutionRole,
        load_resources,
    };
    use crate::game::{Hand, create_port_burner as burner, lan::LanSettings};
    use create_engine::burner::{Candidate, Fuel};
    use horizon_client::{
        chunk::Chunk,
        containers::BlockEntity,
        lan::{Joined, NetConfig, Out, PlayerSender, guest::Guest, hub::HubConfig},
        particles::ParticleType,
    };
    use horizon_protocol::{connection::Pipe, mod_net, packets::play::Clientbound as C};
    use horizon_world::{nbt::Tag, registry::BlockStateId};
    use std::{
        path::PathBuf,
        sync::{Arc, atomic::AtomicI32, mpsc},
    };
    let vanilla =
        PathBuf::from(std::env::var_os("HORIZON_TEST_RESOURCES").expect("private resources"));
    let scratch =
        PathBuf::from(std::env::var_os("HORIZON_HOME").unwrap()).join("burner-sync-world");
    let mut settings = Settings::default();
    settings.mods.enabled.insert("create".into());
    crate::game::mods::register_components(&vanilla).unwrap();
    crate::game::mods::register_standalone_models();
    let root = crate::game::mods::content_root(&vanilla, &settings.mods.enabled, &[]);
    assert_ne!(root, vanilla, "normal bundled content root must be built");
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
    assert!(
        game.pack
            .assets
            .registry
            .default_state("create:blaze_burner")
            .is_some(),
        "normal compiled content must register"
    );
    game.options.dedicated = Some(Vec::new());
    game.world_root = scratch.clone();
    game.session_lock = Some(horizon_client::save::SessionLock::acquire(&scratch).unwrap());
    let (tables, health) = game
        .build_world_tables(false, &["minecraft:vanilla".into()])
        .unwrap();
    game.world_tables = tables;
    game.health_resources = health;
    game.native_server_data_loaded(false);
    let pointer = id(&game);
    let (first_key, initial) = SERVERS.with(|s| {
        let servers = s.borrow();
        let server = &servers[&pointer];
        (server.key, server.frames.clone().unwrap())
    });
    let source = snapshot(&game).unwrap();
    assert_eq!(
        source.special.get("create:blaze_cake"),
        Some(&3200),
        "actual bundled map contribution"
    );
    assert_eq!(source.ordinary.get("minecraft:coal"), Some(&1600));
    assert!(source.capturable.contains("minecraft:blaze"));
    assert!(!compile(&game), "one compile per generation");
    assert!(SERVERS.with(|s| Arc::ptr_eq(&initial, s.borrow()[&pointer].frames.as_ref().unwrap())));
    game.lan_host(
        LanSettings {
            port: 0,
            guest_commands: false,
            force_game_mode: false,
        },
        NetConfig {
            listen: false,
            announce: false,
            ..NetConfig::lan(0, "BurnerSyncTest".into(), 2)
        },
        HubConfig {
            default_game_mode: 0,
            guest_commands: false,
            force_game_mode: false,
            hardcore: false,
            view_distance: 2,
            simulation_distance: 2,
            dimension: "minecraft:overworld".into(),
            allow_flight: false,
            seed: 0,
            max_players: 20,
            integrated: false,
            levels: Default::default(),
        },
    )
    .unwrap();
    let (tx, rx) = mpsc::channel();
    let mut guest = Guest::new(
        Joined {
            conn: 42,
            uuid: 42,
            name: "FuelObserver".into(),
            properties: Vec::new(),
            info: horizon_protocol::packets::configuration::ClientInformation::new(2),
            brand: "horizon".into(),
            sender: PlayerSender::new(tx, Arc::default()),
            latency: Arc::new(AtomicI32::new(0)),
            address: "127.0.0.1:25565".parse().unwrap(),
        },
        42,
        [1.5, 70.0, 1.5],
        2,
    );
    guest.placed = true;
    guest.dimension = "minecraft:overworld".into();
    game.lan.as_mut().unwrap().hub.guests.push(guest);
    let deliver = |game: &mut Game<'_>| {
        game.ticks += 1;
        tick(game);
        let mut host = game.lan.take().unwrap();
        game.flush_native_net(&mut host);
        game.lan = Some(host);
        let mut frames = Vec::new();
        while let Ok(Out::Packet(body)) = rx.try_recv() {
            let mut reader = horizon_protocol::buf::Reader::new(&body);
            let packet_id = reader.varint().unwrap();
            if let C::CustomPayload(payload) = C::decode(packet_id, reader.rest()).unwrap() {
                assert_eq!(payload.channel, mod_net::CHANNEL);
                let message = mod_net::decode(&payload.data).unwrap();
                assert_eq!(message.channel, DATA);
                frames.push(message.data);
            }
        }
        frames
    };
    game.native_player_logged_in(42, "FuelObserver");
    assert!(SERVERS.with(|s| Arc::ptr_eq(&initial, &s.borrow()[&pointer].pending[&42].frames)));
    assert_eq!(deliver(&mut game), *initial);
    assert!(SERVERS.with(|s| s.borrow()[&pointer].pending.is_empty()));
    let pack = scratch.join("datapacks/fuel-test");
    let write = |path: &str, value: serde_json::Value| {
        let file = pack.join(path);
        std::fs::create_dir_all(file.parent().unwrap()).unwrap();
        std::fs::write(file, serde_json::to_vec(&value).unwrap()).unwrap();
    };
    let format = horizon_core::version::DATA_PACK_FORMAT.0;
    write(
        "pack.mcmeta",
        serde_json::json!({"pack":{"min_format":format,"max_format":format,"description":"fuel sync"}}),
    );
    write(
        "data/create/data_maps/item/superheated_blaze_burner_fuels.json",
        serde_json::json!({"values":{},"remove":["create:blaze_cake"]}),
    );
    write(
        "data/create/data_maps/item/regular_blaze_burner_fuels.json",
        serde_json::json!({"values":{"minecraft:coal":{"burn_time":2500}}}),
    );
    write(
        "data/create/tags/item/blaze_burner_fuel/special.json",
        serde_json::json!({"replace":true,"values":["minecraft:iron_ingot"]}),
    );
    write(
        "data/create/tags/item/blaze_burner_fuel/regular.json",
        serde_json::json!({"replace":true,"values":["minecraft:dirt"]}),
    );
    write(
        "data/create/tags/entity_type/blaze_burner_capturable.json",
        serde_json::json!({"replace":true,"values":["minecraft:zombie"]}),
    );
    game.reload_datapacks(true);
    let reloaded = snapshot(&game).unwrap();
    assert!(!reloaded.special.contains_key("create:blaze_cake"));
    assert_eq!(reloaded.regular.get("minecraft:coal"), Some(&2500));
    assert!(
        reloaded.special_tag.contains("minecraft:iron_ingot")
            && reloaded.regular_tag.contains("minecraft:dirt")
    );
    assert_eq!(reloaded.capturable, ["minecraft:zombie".to_owned()].into());
    let updated = SERVERS.with(|s| {
        let servers = s.borrow();
        let server = &servers[&pointer];
        assert_eq!(server.key.world, first_key.world);
        assert_eq!(server.key.reload, first_key.reload + 1);
        server.frames.clone().unwrap()
    });
    assert!(!Arc::ptr_eq(&initial, &updated));
    assert_eq!(
        deliver(&mut game),
        *updated,
        "reload is broadcast to the joined guest"
    );
    // The ordinary incoming mod packet route validates/queues a bounded
    // re-request. It cannot produce a duplicate during the throttle interval.
    let request = mod_net::encode(&mod_net::Message {
        channel: REQUEST.into(),
        data: wire::REQUEST.to_vec(),
    })
    .unwrap();
    let host = game.lan.take().unwrap();
    game.guest_native_net(&host, 42, &request);
    game.lan = Some(host);
    game.run_native_net();
    assert!(SERVERS.with(|s| s.borrow()[&pointer].pending.is_empty()));
    game.ticks += 100;
    let host = game.lan.take().unwrap();
    game.guest_native_net(&host, 42, &request);
    game.lan = Some(host);
    game.run_native_net();
    assert!(SERVERS.with(|s| s.borrow()[&pointer].pending.contains_key(&42)));
    game.lan.as_mut().unwrap().hub.guests.clear();
    game.native_player_logged_out(42, "FuelObserver");
    assert!(SERVERS.with(|s| {
        let state = s.borrow();
        state[&pointer].pending.is_empty() && state[&pointer].sent.is_empty()
    }));
    game.lan = None;
    // A real normal Remote is constructed over the local in-memory transport.
    // This controlled Game test drives packet callbacks; a joined live game is
    // separately checked by the disposable native acceptance runner.
    game.options.dedicated = None;
    game.options.execution_role = ExecutionRole::Client;
    game.session_lock = None;
    game.world_tables = None;
    let (client_pipe, server_pipe) = Pipe::pair();
    game.connect_local(client_pipe, "BurnerSyncTest").unwrap();
    assert!(game.remote.is_some());
    game.world = World::new(game.res.facts().air, 1);
    game.world
        .chunks
        .insert((0, 0), Arc::new(Chunk::empty(0, 0)));
    game.set_mode_id(0);
    game.selected = 0;
    let pos = [1, 70, 1];
    let setup = |game: &mut Game<'_>, heat: &str, fuel: i32, time: i32, item: &str, hand: Hand| {
        let state = (0..game.pack.assets.registry.len() as u32)
            .map(BlockStateId)
            .find(|id| {
                let s = game.pack.assets.registry.state(*id).unwrap();
                s.name == "create:blaze_burner"
                    && s.properties.get("blaze").map(String::as_str) == Some(heat)
                    && s.properties.get("facing").map(String::as_str) == Some("north")
            })
            .unwrap();
        game.world.set(1, 70, 1, state).unwrap();
        let entity = game.new_block_entity_for_state(state).unwrap();
        game.world.block_entities.insert((1, 70, 1), entity);
        game.native_with_mod_block_entity(pos, |e| {
            e.nbt.insert("fuelLevel".into(), Tag::Int(fuel));
            e.nbt.insert("burnTimeRemaining".into(), Tag::Int(time));
            e.nbt.remove(&"isCreative".into());
        });
        game.inventory[0] = Some(ItemStack::new(
            if hand == Hand::Off {
                "minecraft:stick"
            } else {
                item
            },
            3,
        ));
        game.offhand = (hand == Hand::Off).then(|| ItemStack::new(item, 2));
        game.particles.requested = Some(Vec::new());
        state
    };
    let field = |game: &Game<'_>, key: &str| {
        let Some(BlockEntity::Mod(e)) = game.world.block_entities.get(&(1, 70, 1)) else {
            panic!()
        };
        e.nbt.get(&key.into()).cloned()
    };
    setup(&mut game, "smouldering", 0, 0, "minecraft:coal", Hand::Main);
    let random = game.particles.level_random().state();
    assert!(candidate(&game, &ItemStack::new("create:blaze_cake", 1)).is_none());
    assert!(!burner::predict_client(&mut game, pos));
    assert_eq!(random, game.particles.level_random().state());
    assert!(game.particles.requested.as_ref().unwrap().is_empty());
    for frame in initial.iter() {
        from_server(&game, DATA, frame);
    }
    assert_eq!(
        candidate(&game, &ItemStack::new("create:blaze_cake", 1)),
        Some(Candidate {
            fuel: Fuel::Special,
            burn_time: 3200
        })
    );
    assert_eq!(capturable(&game, "blaze"), Some(true));
    for (item, fuel, time, particle) in [
        ("minecraft:coal", 1, 1600, ParticleType::Flame),
        ("create:blaze_cake", 2, 3200, ParticleType::SoulFireFlame),
    ] {
        let state = setup(&mut game, "smouldering", 0, 0, item, Hand::Main);
        let held = game.held().cloned();
        assert!(burner::predict_client(&mut game, pos));
        assert_eq!(game.world.block(1, 70, 1), state);
        assert_eq!(game.held().cloned(), held);
        assert_eq!(field(&game, "fuelLevel"), Some(Tag::Int(fuel)));
        assert_eq!(field(&game, "burnTimeRemaining"), Some(Tag::Int(time)));
        let particles = game.particles.requested.as_ref().unwrap();
        assert_eq!(particles.len(), 20);
        assert!(particles.iter().all(|p| p.0.ty == particle));
    }
    for heat in ["smouldering", "fading", "kindled", "seething"] {
        let state = setup(
            &mut game,
            heat,
            1,
            700,
            "create:creative_blaze_cake",
            Hand::Main,
        );
        let held = game.held().cloned();
        assert!(burner::predict_client(&mut game, pos));
        assert_eq!(game.world.block(1, 70, 1), state);
        assert_eq!(game.held().cloned(), held);
        assert_eq!(field(&game, "isCreative"), Some(Tag::Byte(1)));
        assert_eq!(field(&game, "fuelLevel"), None);
        assert_eq!(field(&game, "burnTimeRemaining"), None);
        let particles = game.particles.requested.as_ref().unwrap();
        assert_eq!(particles.len(), 20);
        let kind = if heat == "kindled" {
            ParticleType::SoulFireFlame
        } else {
            ParticleType::Flame
        };
        assert!(particles.iter().all(|p| p.0.ty == kind));
    }
    setup(
        &mut game,
        "smouldering",
        0,
        0,
        "create:blaze_cake",
        Hand::Off,
    );
    let main = game.inventory[0].clone();
    let off = game.offhand.clone();
    assert!(game.with_hand(Hand::Off, |g| burner::predict_client(g, pos)));
    assert_eq!(game.inventory[0], main);
    assert_eq!(game.offhand, off);
    assert_eq!(game.particles.requested.as_ref().unwrap().len(), 20);
    setup(&mut game, "seething", 2, 501, "minecraft:coal", Hand::Main);
    let random = game.particles.level_random().state();
    assert!(!burner::predict_client(&mut game, pos));
    assert_eq!(random, game.particles.level_random().state());
    assert!(game.particles.requested.as_ref().unwrap().is_empty());
    for frame in updated.iter() {
        from_server(&game, DATA, frame);
    }
    assert_eq!(
        candidate(&game, &ItemStack::new("create:blaze_cake", 1)),
        Some(Candidate {
            fuel: Fuel::None,
            burn_time: 0
        })
    );
    assert_eq!(
        candidate(&game, &ItemStack::new("minecraft:coal", 1)),
        Some(Candidate {
            fuel: Fuel::Normal,
            burn_time: 2500
        })
    );
    assert_eq!(
        candidate(&game, &ItemStack::new("minecraft:iron_ingot", 1)),
        Some(Candidate {
            fuel: Fuel::Special,
            burn_time: 3200
        })
    );
    assert_eq!(
        candidate(&game, &ItemStack::new("minecraft:dirt", 1)),
        Some(Candidate {
            fuel: Fuel::Normal,
            burn_time: 1600
        })
    );
    assert_eq!(capturable(&game, "minecraft:blaze"), Some(false));
    assert_eq!(capturable(&game, "zombie"), Some(true));
    let mut malformed = updated[0].clone();
    malformed[4] = 255;
    from_server(&game, DATA, &malformed);
    assert_eq!(capturable(&game, "zombie"), Some(true));
    // Same-connection replacement installs its new dimension before the old
    // unload callback. Definitions remain connection-global in that phase.
    game.create_burner_sync_test_level(Some("minecraft:the_nether"));
    assert!(game.create_burner_sync_has_level());
    assert!(SERVERS.with(|s| s.borrow().contains_key(&pointer)));
    clear(&game);
    assert_eq!(capturable(&game, "zombie"), Some(true));
    assert!(!SERVERS.with(|s| s.borrow().contains_key(&pointer)));
    // Disconnect/reconfiguration removes the level before unload; it cannot
    // carry definitions into a later connection reusing this Game allocation.
    game.create_burner_sync_test_level(None);
    assert!(!game.create_burner_sync_has_level());
    clear(&game);
    assert_eq!(capturable(&game, "zombie"), None);
    assert_eq!(candidate(&game, &ItemStack::new("minecraft:coal", 1)), None);
    server_pipe.shutdown();
}
