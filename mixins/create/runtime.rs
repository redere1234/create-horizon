// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT
// Game-side adapter. The engine crate contains the portable algorithms.
use super::{
    Game,
    create_port_basin_recipes::item_drain,
    create_port_saw_processing::{crafter, crushing as crusher},
    native_block_entity_draw::BlockEntityDraw,
};
use crate::{
    containers::{BlockEntity, ModBlockEntity, ModContainer},
    items::ItemStack,
};
use create_engine::{
    kinetics::{Axis, Kind, Node},
    placement::{self, Direction},
    pressing::{Action, PressCycle},
};
use horizon_world::{
    nbt::{Compound, Tag},
    registry::BlockStateId,
};
use serde_json::Value;

static ORIGINAL_ASSETS: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);
pub(super) const FLYWHEEL: &str = "create:flywheel";

pub(super) fn original_assets() -> bool {
    ORIGINAL_ASSETS.load(std::sync::atomic::Ordering::Relaxed)
}

/// Feed bundled content through Horizon's ordinary content loader, before it
/// registers blocks or announces mods. The native mod uses the same enable flag.
pub(super) fn prepare_content(enabled: &std::collections::BTreeSet<String>) {
    if enabled.contains("create") {
        match create_assets::bundled_content(
            &Game::game_dir(),
            horizon_client::native_data!("create", "content.json"),
            horizon_client::native_data!("create", "textures.zip"),
        ) {
            Ok(path) => {
                log::info!("Create: bundled content enabled in {}", path.display());
            }
            Err(error) => log::error!("Create: bundled content could not be loaded: {error}"),
        }
    }
}

/// Imports the user's JAR before the initial load, and again on pack reload.
/// Uses Horizon's own pack loader/cache; the installed content archive is untouched.
pub(super) fn asset_root(root: std::path::PathBuf) -> std::path::PathBuf {
    ORIGINAL_ASSETS.store(false, std::sync::atomic::Ordering::Relaxed);
    // Horizon consumes registry declarations while building the root; their
    // source data/*/horizon files are deliberately absent from that overlay.
    if !root
        .join("data/create/recipe/pressing/iron_ingot.json")
        .is_file()
        || !root.join("assets/create/items/shaft.json").is_file()
    {
        return root;
    }
    let home = Game::game_dir();
    let result = (|| -> std::io::Result<Option<std::path::PathBuf>> {
        let Some(imported) = create_assets::prepare(&home, horizon_client::packs::RESOURCE_FORMAT)?
        else {
            log::warn!(
                "Create: using provisional resources. Place the original Create {} JAR in {}",
                create_assets::CREATE_VERSION,
                home.join(create_assets::INPUT_DIR).display()
            );
            return Ok(None);
        };
        let packs = horizon_client::packs::folder(
            imported.pack.parent().expect("pack parent"),
            horizon_client::packs::RESOURCE_FORMAT,
        );
        if packs.len() != 1 {
            return Err(std::io::Error::other(
                "The locally imported Create resource pack could not be read",
            ));
        }
        let overlay = horizon_client::packs::resource_root(
            &root,
            &packs,
            &home.join(".horizon-cache/create-assets/overlay"),
        )?;
        log::info!(
            "Create: {} local resources from Create {} ({}); JAR and installed mod unchanged",
            imported.files,
            create_assets::CREATE_VERSION,
            if imported.cached {
                "cache verified"
            } else {
                "imported"
            }
        );
        Ok(Some(overlay))
    })();
    match result {
        Ok(Some(overlay)) => {
            ORIGINAL_ASSETS.store(true, std::sync::atomic::Ordering::Relaxed);
            overlay
        }
        Ok(None) => root,
        Err(error) => {
            log::warn!(
                "Create: local resource import failed; using provisional resources: {error}"
            );
            root
        }
    }
}

pub(super) fn owns(block: &str) -> bool {
    matches!(
        block,
        "create:creative_motor"
            | "create:shaft"
            | FLYWHEEL
            | crusher::WHEEL
            | crafter::BLOCK
            | "create:cogwheel"
            | "create:large_cogwheel"
            | super::create_port_contraption::BLOCK
            | super::create_port_contraption::WINDMILL
            | super::create_port_clockwork::BLOCK
            | super::create_port_piston::NORMAL
            | super::create_port_piston::STICKY
            | super::create_port_gantry::SHAFT
            | super::create_port_gantry::CARRIAGE
            | super::create_port_pulley::BLOCK
            | super::create_port_deployer::BLOCK
            | "create:mechanical_press"
            | "create:depot"
            | "create:gearbox"
            | "create:clutch"
            | "create:gearshift"
            | "create:hand_crank"
            | "create:andesite_encased_shaft"
            | "create:brass_encased_shaft"
            | "create:encased_chain_drive"
            | super::create_port_chain::ADJUSTABLE
            | "create:speedometer"
            | "create:stressometer"
            | "create:water_wheel"
            | "create:large_water_wheel"
            | "create:water_wheel_structure"
            | "create:millstone"
            | "create:encased_fan"
            | "create:mechanical_drill"
            | super::create_port_drill::SAW
            | "create:mechanical_harvester"
            | "create:basin"
            | "create:mechanical_mixer"
            | super::create_port_basin::pump::PUMP
            | super::create_port_basin::pump::VALVE
            | "create:blaze_burner"
            | "create:belt"
    ) || super::create_port_interactions::encased_cog_size(block).is_some()
}

pub(super) fn entity(block: &str, entity: &mut Option<(String, Compound)>) {
    if block == super::create_port_basin::pump::PIPE && entity.is_none() {
        *entity = Some((block.into(), Compound::new()));
        return;
    }
    use super::create_port_basin::tank;
    if block == tank::BLOCK && entity.is_none() {
        *entity = Some((block.into(), tank::default_nbt()));
        return;
    }
    if block == item_drain::BLOCK && entity.is_none() {
        *entity = Some((block.into(), item_drain::default_nbt()));
        return;
    }
    if block == crafter::BLOCK && entity.is_none() {
        *entity = Some((block.into(), crafter::default_nbt()));
        return;
    }
    if block == crusher::CONTROLLER && entity.is_none() {
        *entity = Some((block.into(), crusher::default_nbt()));
        return;
    }
    if block == super::create_port_sticker::BLOCK && entity.is_none() {
        *entity = Some((block.into(), super::create_port_sticker::default_nbt()));
        return;
    }
    if super::create_port_chute::is_chute(block) && entity.is_none() {
        let nbt = if block == super::create_port_chute::SMART {
            super::create_port_chute::smart_nbt()
        } else {
            super::create_port_chute::default_nbt()
        };
        *entity = Some((block.into(), nbt));
        return;
    }
    if super::create_port_chute::funnel::is_funnel(block) && entity.is_none() {
        let funnel = super::create_port_chute::funnel::ENTITY;
        *entity = Some((
            funnel.into(),
            super::create_port_chute::funnel::default_nbt(),
        ));
        return;
    }
    if block == super::create_port_portable_storage::BLOCK && entity.is_none() {
        *entity = Some((block.into(), Compound::new()));
        return;
    }
    if entity.is_none()
        && let Some(chassis) = super::create_port_chassis::factory(block)
    {
        *entity = Some(chassis);
        return;
    }
    if block == super::create_port_deployer::BLOCK && entity.is_none() {
        *entity = Some((block.into(), super::create_port_deployer::default_nbt()));
        return;
    }
    if owns(block) && block != "create:blaze_burner" && entity.is_none() {
        let id = match block {
            "create:creative_motor" => "create:motor",
            "create:mechanical_drill" => "create:drill",
            super::create_port_drill::SAW => "create:saw",
            "create:mechanical_harvester" => "create:harvester",
            super::create_port_piston::STICKY => super::create_port_piston::NORMAL,
            super::create_port_gantry::CARRIAGE => super::create_port_gantry::entity_id(block),
            "create:shaft" | "create:cogwheel" | "create:large_cogwheel" => "create:simple_kinetic",
            "create:andesite_encased_shaft"
            | "create:brass_encased_shaft"
            | "create:encased_chain_drive" => "create:encased_shaft",
            block if let Some(large) = super::create_port_interactions::encased_cog_size(block) => {
                if large {
                    "create:encased_large_cogwheel"
                } else {
                    "create:encased_cogwheel"
                }
            }
            _ => block,
        };
        let mut nbt = Compound::new();
        if block == "create:creative_motor" {
            nbt.insert("ScrollValue".into(), Tag::Int(16));
        } else if block == super::create_port_chain::ADJUSTABLE {
            nbt.insert("Signal".into(), Tag::Int(0));
        } else if block == super::create_port_drill::SAW {
            nbt = super::create_port_saw_processing::default_nbt();
        } else if block == super::create_port_basin::pump::VALVE {
            nbt = super::create_port_basin::pump::valve_nbt();
        }
        *entity = Some((id.to_owned(), nbt));
    }
}

pub(super) fn ticks(block: &str, ticks: &mut bool) {
    if (owns(block) && block != "create:mechanical_harvester")
        || block == super::create_port_portable_storage::BLOCK
        || super::create_port_chute::is_chute(block)
        || super::create_port_chute::funnel::is_funnel(block)
        || block == crusher::CONTROLLER
        || block == item_drain::BLOCK
        || block == super::create_port_basin::tank::BLOCK
        || block == super::create_port_basin::pump::PIPE
    {
        *ticks = true;
    }
}

pub(super) fn number(nbt: &Compound, key: &str) -> f32 {
    match nbt.get(&key.into()) {
        Some(Tag::Float(n)) => f32::from_bits(*n),
        Some(Tag::Int(n)) => *n as f32,
        Some(Tag::Long(n)) => *n as f32,
        _ => 0.0,
    }
}

/// KineticBlockEntity.getSpeed: debug stepping a frozen world does not expose
/// theoretical network RPM to a machine. Keep the stored Speed/port diagnostics
/// intact so unfreezing resumes the same network instead of propagating zero.
pub(super) fn running_speed(game: &Game<'_>, nbt: &Compound) -> f32 {
    if game.clock.frozen() {
        0.0
    } else {
        number(nbt, "Speed")
    }
}

pub(super) fn integer(nbt: &Compound, key: &str) -> i32 {
    match nbt.get(&key.into()) {
        Some(Tag::Int(n)) => *n,
        Some(Tag::Byte(n)) => i32::from(*n),
        _ => 0,
    }
}

/// ItemStack.getMaxStackSize after the component patch. Persistent numeric
/// values use Number.intValue; removing the prototype component defaults to1.
pub(super) fn stack_maximum_override(stack: &ItemStack) -> Option<u32> {
    let data = stack.data()?;
    if data.other("!minecraft:max_stack_size").is_some() {
        return Some(1);
    }
    let value = match data.other("minecraft:max_stack_size")? {
        Tag::Byte(v) => i32::from(*v),
        Tag::Short(v) => i32::from(*v),
        Tag::Int(v) => *v,
        Tag::Long(v) => *v as i32,
        Tag::Float(v) => f32::from_bits(*v) as i32,
        Tag::Double(v) => f64::from_bits(*v) as i32,
        _ => return None,
    };
    (1..=99).contains(&value).then_some(value as u32)
}

pub(super) fn stack_maximum(game: &Game<'_>, stack: &ItemStack) -> u32 {
    stack_maximum_override(stack)
        .unwrap_or_else(|| game.native_max_stack_size(&stack.item).unwrap_or(64))
}

thread_local! {
    static PLACEMENT_HIT: std::cell::Cell<Option<([i32; 3], [i32; 3])>> = const { std::cell::Cell::new(None) };
}

pub(super) fn use_on(game: &Game<'_>, stack: &ItemStack, pos: [i32; 3], face: [i32; 3]) {
    PLACEMENT_HIT.set((game.native_on("create") && owns(&stack.item)).then_some((pos, face)));
}

// Direction.orderedByNearest, adapted from Horizon's MIT level/place.rs.
// Uses the engine's vanilla-compatible trigonometric table.
pub(super) fn nearest(yaw: f32, pitch: f32) -> Direction {
    use horizon_core::geometry::trig;
    let pitch = pitch * (std::f32::consts::PI / 180.0);
    let yaw = -yaw * (std::f32::consts::PI / 180.0);
    let (ps, pc) = (trig::sin(f64::from(pitch)), trig::cos(f64::from(pitch)));
    let (ys, yc) = (trig::sin(f64::from(yaw)), trig::cos(f64::from(yaw)));
    let (x, y, z) = (ys.abs(), ps.abs(), yc.abs());
    let ax = if ys > 0.0 {
        Direction::East
    } else {
        Direction::West
    };
    let ay = if ps < 0.0 {
        Direction::Up
    } else {
        Direction::Down
    };
    let az = if yc > 0.0 {
        Direction::South
    } else {
        Direction::North
    };
    if x > z {
        if y > x * pc { ay } else { ax }
    } else if y > z * pc {
        ay
    } else {
        az
    }
}

pub(super) fn placed(game: &mut Game<'_>, stack: &ItemStack, pos: [i32; 3]) {
    if game.native_on("create") && super::create_port_chute::funnel::is_funnel(&stack.item) {
        super::create_port_chute::funnel::refresh_power(game, pos);
    }
    if game.native_on("create") && stack.item.as_ref() == super::create_port_chute::SMART {
        super::create_port_chute::refresh_power(game, pos);
    }
    if game.native_on("create") && super::create_port_chute::is_chute(&stack.item) {
        super::create_port_chute::placed(game, pos);
    }
    let Some((clicked, face)) = PLACEMENT_HIT.take() else {
        return;
    };
    if !owns(&stack.item) {
        return;
    }
    let Some(face) = Direction::from_vector(face) else {
        return;
    };
    let ports = Direction::ALL.map(|d| {
        let offset = d.vector();
        node(game, std::array::from_fn(|i| pos[i] + offset[i]))
            .is_some_and(|n| n.shaft_port(offset.map(|v| -v)))
    });
    let sneaking = game.keys.contains(&winit::keyboard::KeyCode::ShiftLeft);
    let look = nearest(game.yaw, game.pitch);
    let axis = match stack.item.as_ref() {
        "create:shaft"
        | FLYWHEEL
        | crusher::WHEEL
        | "create:andesite_encased_shaft"
        | "create:brass_encased_shaft"
        | "create:clutch"
        | "create:gearshift" => Some(placement::shaft(look, face, sneaking, ports)),
        "create:cogwheel" | "create:large_cogwheel" => {
            let against = if super::create_port_placement::cog_size(&game.native_block(clicked))
                == Some(false)
            {
                node(game, clicked).map(|n| n.axis)
            } else {
                None
            };
            Some(placement::cog(face, sneaking, ports, against))
        }
        _ => None,
    };
    if let Some(axis) = axis {
        game.native_set_block_property(
            pos,
            "axis",
            match axis {
                Axis::X => "x",
                Axis::Y => "y",
                Axis::Z => "z",
            },
        );
        if super::create_port_kinetic_runtime::transmission_block(&stack.item) {
            let dimension = game.dim.id().to_owned();
            if game.native_neighbor_signal(&dimension, pos) > 0 {
                game.native_set_block_property_with(
                    pos,
                    "powered",
                    "true",
                    horizon_world::level::flags::UPDATE_CLIENTS,
                );
            }
        }
    } else {
        let facing = match stack.item.as_ref() {
            "create:creative_motor" => Some(placement::motor(look, sneaking, ports)),
            "create:mechanical_press" => Some(
                [
                    Direction::North,
                    Direction::East,
                    Direction::South,
                    Direction::West,
                ][((f64::from(game.yaw) / 90.0 + 0.5).floor() as i64 & 3) as usize],
            ),
            _ => None,
        };
        if let Some(facing) = facing {
            game.native_set_block_property(pos, "facing", facing.name());
        }
    }
}

/// Ordinary native inventories support only their pinned canonical sizes.
/// An explicitly edited different handler size stays opaque until restored.
pub(super) fn inventory_supported(entity: &ModBlockEntity) -> bool {
    let inventories: &[(&str, i32)] = match entity.id.as_str() {
        "create:depot" => &[("OutputBuffer", 8)],
        "create:basin" => &[("InputItems", 9), ("OutputItems", 9)],
        "create:millstone" => &[("InputInventory", 1), ("OutputInventory", 9)],
        crusher::CONTROLLER => &[("Inventory", 32)],
        crafter::BLOCK => &[("Inventory", 1)],
        _ => return true,
    };
    inventories.iter().all(|&(key, count)| {
        !matches!(entity.nbt.get(&key.into()).and_then(|v| v.get("Size")),
            Some(Tag::Int(size)) if *size != count)
    })
}

pub(super) fn inventory_blocked(game: &Game<'_>, pos: [i32; 3]) -> bool {
    matches!(game.world.block_entities.get(&(pos[0],pos[1],pos[2])),
        Some(BlockEntity::Mod(entity)) if !inventory_supported(entity))
}

pub(super) fn predicts_use(game: &Game<'_>, pos: [i32; 3], face: [i32; 3]) -> bool {
    !inventory_blocked(game, pos)
        && (crate::game::create_port_burner::reacts(game, pos)
            || crate::game::create_port_basin::reacts(game, pos)
            || crate::game::create_port_basin::tank::predicts_use(game, pos)
            || crate::game::create_port_basin::pump::reacts(game, pos)
            || item_drain::predicts_use(game, pos)
            || super::create_port_belt::predicts_dye(game, pos)
            || super::create_port_belt::predicts_casing(game, pos, face)
            || crate::game::create_port_millstone::reacts(game, pos)
            || crate::game::create_port_chute::predicts_use(game, pos)
            || super::create_port_chute::funnel::predicts_use(game, pos, face)
            || crate::game::create_port_interactions::reacts(game, pos)
            || crafter::predicts_use(game, pos, face)
            || depot_reacts(game, pos, face))
}

fn depot_reacts(game: &Game<'_>, pos: [i32; 3], face: [i32; 3]) -> bool {
    if !game.native_on("create") || game.native_block(pos) != "create:depot" || face != [0, 1, 0] {
        return false;
    }
    if game.keys.contains(&winit::keyboard::KeyCode::ShiftLeft)
        && (game
            .inventory
            .get(game.selected)
            .is_some_and(Option::is_some)
            || game.offhand.is_some())
    {
        return false;
    }
    true
}

pub(super) fn right_click(game: &mut Game<'_>, pos: [i32; 3], face: [i32; 3], canceled: &mut bool) {
    if inventory_blocked(game, pos) {
        *canceled = true;
        return;
    }
    if crafter::right_click(game, pos, face)
        || super::create_port_saw_filter::right_click(game, pos)
        || super::create_port_basin_filter::right_click(game, pos)
        || super::create_port_chute::funnel::right_click(game, pos, face)
        || super::create_port_contraption::right_click(game, pos)
        || super::create_port_piston::right_click(game, pos, face)
        || super::create_port_pulley::right_click(game, pos)
        || super::create_port_gantry::right_click(game, pos)
        || super::create_port_deployer::right_click(game, pos)
    {
        *canceled = true;
        game.swing_arm();
        return;
    }
    if crate::game::create_port_burner_interactions::right_click(game, pos) {
        *canceled = true;
        game.swing_arm();
        return;
    }
    if crate::game::create_port_burner::right_click(game, pos) {
        *canceled = true;
        game.swing_arm();
        return;
    }
    if crate::game::create_port_basin::right_click(game, pos)
        || crate::game::create_port_basin::tank::right_click(game, pos)
        || crate::game::create_port_basin::pump::right_click(game, pos)
        || item_drain::right_click(game, pos)
    {
        *canceled = true;
        game.swing_arm();
        return;
    }
    if crate::game::create_port_belt::right_click(game, pos, face) {
        *canceled = true;
        game.swing_arm();
        return;
    }
    if crate::game::create_port_interactions::right_click(game, pos, face) {
        game.swing_arm();
        *canceled = true;
        return;
    }
    if crate::game::create_port_millstone::right_click(game, pos) {
        *canceled = true;
        game.swing_arm();
        return;
    }
    if !depot_reacts(game, pos, face) {
        return;
    }
    let held = game.held();
    let put = held.is_some_and(|s| s.count > 0 && s.item.as_ref() != "create:mechanical_arm");
    let Some(taken) = game.native_with_mod_block_entity(pos, |e| {
        let taken = e
            .items
            .iter_mut()
            .filter_map(Option::take)
            .collect::<Vec<_>>();
        e.nbt.remove(&"HeldItem".into());
        taken
    }) else {
        return;
    };
    let uuid = game.native_acting_id();
    if !taken.is_empty() {
        crate::game::create_port_sounds::pickup(game, pos);
    }
    for stack in taken {
        if let Some(rest) = game.native_give_stack(uuid, stack)
            && let Some(player) = game.native_player()
        {
            game.spawn_item(
                rest,
                [player.x, player.y + 1.0, player.z],
                [0.0, 0.2, 0.0],
                10,
            );
        }
    }
    // Read the hand after returning the old stack: Inventory.add may have
    // merged equal items into it. Creative players also empty their hand.
    if put {
        crate::game::create_port_sounds::depot(game, pos);
        let incoming = game.held_mut().take();
        let record = incoming.as_ref().map(|stack| {
            super::create_port_belt::depot_item(
                game,
                stack,
                0.25,
                super::create_port_placement::horizontal(game.yaw),
            )
        });
        game.native_with_mod_block_entity(pos, |e| {
            e.items[0] = incoming;
            if let Some(record) = record {
                e.nbt.insert("HeldItem".into(), record);
            }
        });
    }
    game.native_with_mod_block_entity(pos, |e| {
        depot_data(e);
    });
    game.native_block_entity_sync(pos);
    game.swing_arm();
    *canceled = true;
}

/// Match DepotBehaviour/TransportedItemStack's public data names. Horizon also
/// saves its generic Items slots; Create ignores that additional container field.
fn depot_field(fields: &mut Compound, key: &str, value: Tag) -> bool {
    if fields.get(&key.into()) == Some(&value) {
        false
    } else {
        fields.insert(key.into(), value);
        true
    }
}

pub(super) fn depot_data(entity: &mut ModBlockEntity) -> bool {
    if !inventory_supported(entity) {
        return false;
    }
    let mut changed = false;
    if let Some(item) = entity
        .items
        .first()
        .and_then(Option::as_ref)
        .map(horizon_items::item_nbt::item_to_nbt)
    {
        let key: horizon_world::nbt::JavaString = "HeldItem".into();
        if !matches!(entity.nbt.get(&key), Some(Tag::Compound(_))) {
            entity.nbt.insert(
                key.clone(),
                Tag::Compound(Compound::from([
                    ("Pos".into(), Tag::Float(0.25f32.to_bits())),
                    ("PrevPos".into(), Tag::Float(0.25f32.to_bits())),
                    ("Offset".into(), Tag::Float(0.0f32.to_bits())),
                    ("PrevOffset".into(), Tag::Float(0.0f32.to_bits())),
                    ("InSegment".into(), Tag::Int(0)),
                    ("Angle".into(), Tag::Int(0)),
                    ("InDirection".into(), Tag::Int(3)),
                ])),
            );
            changed = true;
        }
        if let Some(Tag::Compound(held)) = entity.nbt.get_mut(&key) {
            changed |= depot_field(held, "Item", item);
        }
    } else {
        changed |= entity.nbt.remove(&"HeldItem".into()).is_some();
    }
    let buffer = entity
        .items
        .iter()
        .skip(1)
        .enumerate()
        .filter_map(|(slot, item)| {
            let Tag::Compound(mut tag) = horizon_items::item_nbt::item_to_nbt(item.as_ref()?)
            else {
                return None;
            };
            tag.insert("Slot".into(), Tag::Int(slot as i32));
            Some(Tag::Compound(tag))
        })
        .collect();
    let key: horizon_world::nbt::JavaString = "OutputBuffer".into();
    if !matches!(entity.nbt.get(&key), Some(Tag::Compound(_))) {
        entity
            .nbt
            .insert(key.clone(), Tag::Compound(Compound::new()));
        changed = true;
    }
    if let Some(Tag::Compound(fields)) = entity.nbt.get_mut(&key) {
        changed |= depot_field(fields, "Size", Tag::Int(8));
        changed |= depot_field(fields, "Items", Tag::List(buffer));
    }
    changed |= entity.nbt.remove(&"DisplayItem".into()).is_some();
    changed |= entity.nbt.remove(&"DisplayCount".into()).is_some();
    changed
}

fn facing(value: &str) -> [i32; 3] {
    match value {
        "west" => [-1, 0, 0],
        "east" => [1, 0, 0],
        "up" => [0, 1, 0],
        "down" => [0, -1, 0],
        "south" => [0, 0, 1],
        _ => [0, 0, -1],
    }
}

pub(super) fn node(game: &Game<'_>, pos: [i32; 3]) -> Option<Node> {
    let block = game.native_block(pos);
    let axis_property = game.native_block_property(pos, "axis");
    let direction = facing(
        &game
            .native_block_property(pos, "facing")
            .unwrap_or_else(|| "north".into()),
    );
    let mut axis = match axis_property.as_deref() {
        Some("x") => Axis::X,
        Some("y") => Axis::Y,
        Some("z") => Axis::Z,
        _ if direction[0] != 0 => Axis::X,
        _ if direction[1] != 0 => Axis::Y,
        _ => Axis::Z,
    };
    if matches!(block.as_str(), "create:speedometer" | "create:stressometer")
        || super::create_port_piston::is_piston(&block)
        || block == super::create_port_gantry::CARRIAGE
        || block == super::create_port_deployer::BLOCK
        || block == super::create_port_basin::pump::VALVE
        || (block == super::create_port_drill::SAW && axis == Axis::Y)
    {
        let first = game
            .native_block_property(pos, "axis_along_first")
            .as_deref()
            == Some("true");
        axis = match axis {
            Axis::X => {
                if first {
                    Axis::Y
                } else {
                    Axis::Z
                }
            }
            Axis::Y => {
                if first {
                    Axis::X
                } else {
                    Axis::Z
                }
            }
            Axis::Z => {
                if first {
                    Axis::X
                } else {
                    Axis::Y
                }
            }
        };
    }
    if matches!(
        block.as_str(),
        "create:millstone" | "create:mechanical_mixer"
    ) {
        axis = Axis::Y;
    }
    if block == "create:belt" {
        axis = if game.native_block_property(pos, "slope").as_deref() == Some("sideways") {
            Axis::Y
        } else if direction[0] != 0 {
            Axis::Z
        } else {
            Axis::X
        };
    }
    let kind = match block.as_str() {
        "create:belt" => {
            let (controller, index) =
                crate::game::create_port_belt::node_data(game, pos).unwrap_or((pos, 0));
            Kind::Belt {
                controller,
                index,
                pulley: game.native_block_property(pos, "part").as_deref() != Some("middle"),
                diagonal: matches!(
                    game.native_block_property(pos, "slope").as_deref(),
                    Some("upward" | "downward")
                ),
            }
        }
        super::create_port_piston::NORMAL
        | super::create_port_piston::STICKY
        | super::create_port_pulley::BLOCK
        | super::create_port_deployer::BLOCK => Kind::LinearActuator,
        super::create_port_drill::SAW if direction[1] == 0 => Kind::Consumer {
            facing: direction.map(|v| -v),
            impact: 4.0,
        },
        super::create_port_drill::SAW => Kind::LinearActuator,
        "create:millstone" => Kind::Millstone,
        crafter::BLOCK => Kind::Crafter,
        super::create_port_basin::pump::PUMP => Kind::Pump,
        "create:mechanical_mixer" => Kind::Mixer,
        "create:encased_fan" | "create:mechanical_drill" => Kind::Consumer {
            facing: direction.map(|v| -v),
            impact: if block == "create:mechanical_drill" {
                4.0
            } else {
                2.0
            },
        },
        super::create_port_contraption::WINDMILL => Kind::Motor {
            facing: direction.map(|v| -v),
            rpm: match game.world.block_entities.get(&(pos[0], pos[1], pos[2])) {
                Some(BlockEntity::Mod(entity)) => {
                    number(&entity.nbt, super::create_port_contraption::LAST_GENERATED)
                }
                _ => 0.0,
            },
            capacity: 512.0,
        },
        super::create_port_contraption::BLOCK | super::create_port_clockwork::BLOCK => {
            Kind::Consumer {
                facing: direction.map(|v| -v),
                impact: 4.0,
            }
        }
        "create:speedometer" | "create:stressometer" | super::create_port_basin::pump::VALVE => Kind::Shaft,
        "create:water_wheel" | "create:large_water_wheel" => Kind::WaterWheel {
            rpm: match game.world.block_entities.get(&(pos[0], pos[1], pos[2])) {
                Some(BlockEntity::Mod(e)) => create_engine::waterwheel::rpm(
                    integer(&e.nbt, "FlowScore"),
                    block == "create:large_water_wheel",
                ),
                _ => 0.0,
            },
            capacity: if block == "create:large_water_wheel" {
                128.0
            } else {
                32.0
            },
        },
        "create:creative_motor" => Kind::Motor {
            facing: direction,
            rpm: {
                let speed = match game.world.block_entities.get(&(pos[0], pos[1], pos[2])) {
                    Some(BlockEntity::Mod(e)) => e
                        .nbt
                        .get(&"ScrollValue".into())
                        .map(|_| integer(&e.nbt, "ScrollValue") as f32)
                        .unwrap_or(16.0),
                    _ => 16.0,
                };
                if direction.iter().any(|v| *v < 0) {
                    -speed
                } else {
                    speed
                }
            },
            capacity: 16384.0,
        },
        "create:shaft"
        | FLYWHEEL
        | "create:andesite_encased_shaft"
        | "create:brass_encased_shaft" => Kind::Shaft,
        crusher::WHEEL => Kind::CrushingWheel,
        super::create_port_gantry::SHAFT => Kind::GantryShaft {
            facing: Direction::from_vector(direction)?,
            powered: game.native_block_property(pos, "powered").as_deref() == Some("true"),
        },
        super::create_port_gantry::CARRIAGE => Kind::GantryCarriage {
            facing: Direction::from_vector(direction)?,
        },
        "create:gearbox" => Kind::Gearbox,
        "create:encased_chain_drive" | super::create_port_chain::ADJUSTABLE => Kind::Chain {
            state: super::create_port_chain::read(
                game.pack.assets.registry,
                game.world.block(pos[0], pos[1], pos[2]),
            )?,
            signal: if block == super::create_port_chain::ADJUSTABLE {
                match game.world.block_entities.get(&(pos[0], pos[1], pos[2])) {
                    Some(BlockEntity::Mod(entity)) => {
                        integer(&entity.nbt, "Signal").clamp(0, 15) as u8
                    }
                    _ => 0,
                }
            } else {
                0
            },
        },
        "create:clutch" | "create:gearshift"
            if super::create_port_kinetic_runtime::transmission_detached(game, pos) =>
        {
            Kind::Clutch { powered: true }
        }
        "create:clutch" => Kind::Clutch {
            powered: game.native_block_property(pos, "powered").as_deref() == Some("true"),
        },
        "create:gearshift" => Kind::Gearshift {
            powered: game.native_block_property(pos, "powered").as_deref() == Some("true"),
        },
        "create:hand_crank" => {
            let (active, back) = match game.world.block_entities.get(&(pos[0], pos[1], pos[2])) {
                Some(BlockEntity::Mod(e)) => (
                    integer(&e.nbt, "InUse") > 0,
                    integer(&e.nbt, "Backwards") != 0,
                ),
                _ => (false, false),
            };
            let sign = if direction.iter().any(|v| *v < 0) {
                -1.0
            } else {
                1.0
            };
            Kind::Motor {
                facing: direction.map(|v| -v),
                rpm: if active {
                    32.0 * sign * if back { -1.0 } else { 1.0 }
                } else {
                    0.0
                },
                capacity: 8.0,
            }
        }
        "create:cogwheel" => Kind::Cog { large: false },
        "create:large_cogwheel" => Kind::Cog { large: true },
        block if let Some(large) = super::create_port_interactions::encased_cog_size(block) => {
            Kind::EncasedCog {
                large,
                top_shaft: game.native_block_property(pos, "top_shaft").as_deref() == Some("true"),
                bottom_shaft: game.native_block_property(pos, "bottom_shaft").as_deref()
                    == Some("true"),
            }
        }
        "create:mechanical_press" => Kind::Press,
        _ => return None,
    };
    Some(Node { pos, axis, kind })
}

pub(super) fn ingredient(json: &Value) -> Option<Value> {
    if json.is_string() {
        return Some(json.clone());
    }
    if let Some(id) = json.get("item").and_then(Value::as_str) {
        return Some(id.into());
    }
    if let Some(tag) = json.get("tag").and_then(Value::as_str) {
        return Some(format!("#{tag}").into());
    }
    json.as_array()
        .map(|values| Value::Array(values.iter().filter_map(ingredient).collect()))
}

pub(super) fn result(game: &Game<'_>, stack: &ItemStack) -> Option<ItemStack> {
    for recipe in game.native_recipes_of_type("create:pressing") {
        let Some(inputs) = recipe.json["ingredients"].as_array() else {
            continue;
        };
        let Some(outputs) = recipe.json["results"].as_array() else {
            continue;
        };
        // The first milestone supports deterministic, single-input/single-output bulk pressing.
        if inputs.len() != 1
            || outputs.len() != 1
            || outputs[0]
                .get("chance")
                .and_then(Value::as_f64)
                .is_some_and(|c| c != 1.0)
        {
            continue;
        }
        let Some(input) = ingredient(&inputs[0]).and_then(|i| game.native_recipe_ingredient(&i))
        else {
            continue;
        };
        if !input.test(stack) {
            continue;
        }
        let Some(output) = game.native_recipe_result(&outputs[0]) else {
            continue;
        };
        if output.count <= game.native_max_stack_size(&output.item)? {
            return Some(output);
        }
    }
    None
}

fn slide_depot(game: &mut Game<'_>, pos: [i32; 3], entity: &mut ModBlockEntity) -> bool {
    let Some(stack) = entity.items.first().and_then(Option::as_ref) else {
        return false;
    };
    let upright = super::create_port_belt::upright(game, stack);
    let Some(tag) = entity.nbt.get_mut(&"HeldItem".into()) else {
        return false;
    };
    let Tag::Compound(held) = tag else {
        return false;
    };
    let old = number(held, "Pos");
    let side = number(held, "Offset");
    let (next, angle, ready) = create_engine::depot::slide(old, integer(held, "Angle"), upright);
    let changed = depot_field(held, "PrevPos", Tag::Float(old.to_bits()))
        | depot_field(held, "Pos", Tag::Float(next.to_bits()))
        | depot_field(held, "PrevOffset", Tag::Float(side.to_bits()))
        | depot_field(held, "Angle", Tag::Int(angle));
    let above = [pos[0], pos[1] + 2, pos[2]];
    let Some(processor) = super::create_port_belt::Processor::at(game, above).filter(|_| ready) else {
        return changed;
    };
    let Some(mut item) = super::create_port_belt::read_item(game, tag) else {
        return changed;
    };
    let locked = item.locked;
    if !locked && !game.native_block_collision([pos[0], pos[1] + 1, pos[2]]).is_empty() {
        return changed;
    }
    let update = processor.process(game, above, &mut item, locked);
    let (processed, overflow) = super::create_port_inventory::process_depot(entity, &item, update);
    for stack in overflow {
        game.spawn_item(
            stack,
            [
                f64::from(pos[0]) + 0.5,
                f64::from(pos[1]) + 1.0,
                f64::from(pos[2]) + 0.5,
            ],
            [0.0; 3],
            10,
        );
    }
    changed || processed
}

pub(super) fn network_rpm(
    network: &create_engine::kinetics::Network,
    other_half: Option<&create_engine::kinetics::Network>,
    pos: [i32; 3],
) -> f32 {
    let rpm = network.speed(pos);
    other_half
        .filter(|other| other.speed(pos).abs() > rpm.abs())
        .map_or(rpm, |other| other.speed(pos))
}

pub(super) fn network_matches(
    entity: &ModBlockEntity,
    network: &create_engine::kinetics::Network,
    other_half: Option<&create_engine::kinetics::Network>,
    pos: [i32; 3],
) -> bool {
    let Some(Tag::Compound(data)) = entity.nbt.get(&"create_horizon".into()) else {
        return false;
    };
    let Some(Tag::Compound(ports)) = data.get(&"Ports".into()) else {
        return false;
    };
    number(&entity.nbt, "Speed") == network_rpm(network, other_half, pos)
        && number(&entity.nbt, "Capacity") == network.capacity
        && number(&entity.nbt, "Stress") == network.stress
        && number(data, "TheoreticalSpeed") == network.theoretical.get(&pos).copied().unwrap_or(0.0)
        && entity.nbt.get(&"NetworkStatus".into())
            == Some(&Tag::String(
                format!("{:?}", network.status).as_str().into(),
            ))
        && Direction::ALL.into_iter().all(|d| {
            let delta = d.vector();
            let speed = network.port_speed(pos, delta);
            let speed = other_half
                .filter(|other| other.port_speed(pos, delta).abs() > speed.abs())
                .map_or(speed, |other| other.port_speed(pos, delta));
            number(ports, d.name()) == speed
        })
}

/// A kinetic event updates neighbours before their own behaviour turns. Keep
/// this operation separate from ticking a machine (no recursive BE tick).
pub(super) fn apply_network(
    entity: &mut ModBlockEntity,
    network: &create_engine::kinetics::Network,
    other_half: Option<&create_engine::kinetics::Network>,
    pos: [i32; 3],
) {
    let old_theoretical = match entity.nbt.get(&"create_horizon".into()) {
        Some(Tag::Compound(data)) => number(data, "TheoreticalSpeed"),
        _ => number(&entity.nbt, "Speed"),
    };
    let mut ports = Compound::new();
    for d in Direction::ALL {
        let delta = d.vector();
        let mut speed = network.port_speed(pos, delta);
        if let Some(other) = &other_half
            && other.port_speed(pos, delta).abs() > speed.abs()
        {
            speed = other.port_speed(pos, delta);
        }
        ports.insert(d.name().into(), Tag::Float(speed.to_bits()));
    }
    entity.nbt.insert(
        "create_horizon".into(),
        Tag::Compound(Compound::from([
            ("Ports".into(), Tag::Compound(ports)),
            (
                "TheoreticalSpeed".into(),
                Tag::Float(
                    network
                        .theoretical
                        .get(&pos)
                        .copied()
                        .unwrap_or(0.0)
                        .to_bits(),
                ),
            ),
        ])),
    );
    let old_rpm = number(&entity.nbt, "Speed");
    let rpm = network_rpm(network, other_half, pos);
    entity.nbt.insert("Speed".into(), Tag::Float(rpm.to_bits()));
    entity
        .nbt
        .insert("Capacity".into(), Tag::Float(network.capacity.to_bits()));
    entity
        .nbt
        .insert("Stress".into(), Tag::Float(network.stress.to_bits()));
    entity.nbt.insert(
        "NetworkStatus".into(),
        Tag::String(format!("{:?}", network.status).as_str().into()),
    );
    let theoretical = network.theoretical.get(&pos).copied().unwrap_or(0.0);
    crate::game::create_port_mixer::on_speed_changed(entity, old_theoretical, theoretical);
    crate::game::create_port_press_basin::on_speed_changed(entity, old_theoretical, theoretical);
    crate::game::create_port_mixer::on_speed_changed(entity, old_rpm, rpm);
    crate::game::create_port_press_basin::on_speed_changed(entity, old_rpm, rpm);
}

pub(super) fn tick(game: &mut Game<'_>, pos: [i32; 3], entity: &mut ModBlockEntity) {
    let block = game.native_block(pos);
    if block == super::create_port_basin::pump::PIPE {
        if super::create_port_basin::pump::tick(game, pos, entity, 0.0) {
            game.native_block_entity_sync(pos);
        }
        return;
    }
    if block == super::create_port_basin::tank::BLOCK {
        super::create_port_basin::tank::tick(game, pos, entity);
        return;
    }
    if block == item_drain::BLOCK {
        item_drain::tick(game, pos, entity);
        return;
    }
    if block == crusher::CONTROLLER && entity.id == crusher::CONTROLLER {
        crusher::tick(game, pos, entity);
        return;
    }
    if super::create_port_chute::is_chute(&block) {
        super::create_port_chute::tick(game, pos, entity);
        return;
    }
    if super::create_port_chute::funnel::is_funnel(&block) {
        super::create_port_chute::funnel::tick(game, pos, entity);
        return;
    }
    if block == super::create_port_portable_storage::BLOCK {
        super::create_port_portable_storage::tick(game, pos, entity);
        return;
    }
    if !owns(&block) {
        return;
    }
    if !inventory_supported(entity) {
        return;
    }
    if block == "create:blaze_burner" {
        crate::game::create_port_burner::tick(game, pos, entity);
        return;
    }
    if block == "create:basin" {
        if crate::game::create_port_basin::tick(game, pos, entity) {
            game.native_block_entity_sync(pos);
        }
        return;
    }
    if block == "create:depot" {
        if !inventory_supported(entity) {
            return;
        }
        crate::game::create_port_world_items::catch(game, pos, entity);
        let mut changed = depot_data(entity);
        changed |= slide_depot(game, pos, entity);
        if changed {
            game.native_block_entity_sync(pos);
        }
        return;
    }
    crate::game::create_port_belt::prepare(game, pos, entity);
    let old_flow_score = integer(&entity.nbt, "FlowScore");
    if crate::game::create_port_generators::tick(game, pos, entity, &block) {
        return;
    }
    let Some(mut start) = node(game, pos) else {
        return;
    };
    let mut chain_signal_changed = false;
    if block == super::create_port_chain::ADJUSTABLE
        && let Kind::Chain { signal, .. } = &mut start.kind
    {
        // The host removes the ticking entity from the level's map. Override
        // its graph input with the signal sampled on its own turn.
        (*signal, chain_signal_changed) =
            super::create_port_chain::refresh_signal(game, pos, entity);
    }
    let mut windmill_changed = false;
    if block == super::create_port_contraption::WINDMILL {
        if let Kind::Motor { rpm, .. } = &mut start.kind {
            (*rpm, windmill_changed) =
                super::create_port_contraption::windmill_source(game, pos, entity);
        }
    } else if let Kind::Motor { rpm, .. } = &mut start.kind {
        let direction = facing(
            &game
                .native_block_property(pos, "facing")
                .unwrap_or_else(|| "north".into()),
        );
        let sign = if direction.iter().any(|v| *v < 0) {
            -1.0
        } else {
            1.0
        };
        let value = if block == "create:hand_crank" {
            if integer(&entity.nbt, "InUse") > 0 {
                if integer(&entity.nbt, "Backwards") != 0 {
                    -32.0
                } else {
                    32.0
                }
            } else {
                0.0
            }
        } else {
            entity
                .nbt
                .get(&"ScrollValue".into())
                .map(|_| integer(&entity.nbt, "ScrollValue") as f32)
                .unwrap_or(16.0)
        };
        *rpm = sign * value;
    }
    if let Kind::WaterWheel { rpm, .. } = &mut start.kind {
        *rpm = create_engine::waterwheel::rpm(
            integer(&entity.nbt, "FlowScore"),
            block == "create:large_water_wheel",
        );
    }
    let mut publish_source = windmill_changed;
    if windmill_changed {
        super::create_port_kinetic_runtime::invalidate();
    }
    if block != super::create_port_contraption::WINDMILL
        && let Kind::Motor { rpm, .. } | Kind::WaterWheel { rpm, .. } = &mut start.kind
    {
        (*rpm, publish_source) = crate::game::create_port_kinetic_runtime::source_turn(
            game,
            pos,
            entity,
            *rpm,
            block == "create:creative_motor",
            old_flow_score != integer(&entity.nbt, "FlowScore"),
        );
    }
    let network = crate::game::create_port_kinetic_runtime::network(game, start, 0);
    let other_half = matches!(start.kind, Kind::Clutch { powered: true })
        .then(|| crate::game::create_port_kinetic_runtime::network(game, start, 1));
    let (first_attachment, blocked_attachment) = crate::game::create_port_kinetic_runtime::attach(
        game,
        start,
        entity,
        network_rpm(&network, other_half.as_deref(), pos),
    );
    let blocked_attachment = blocked_attachment && !publish_source;
    let old_rpm = number(&entity.nbt, "Speed");
    let first_wheel_tick = block == crusher::WHEEL && !entity.nbt.contains_key(&"Speed".into());
    let old_running_rpm = running_speed(game, &entity.nbt);
    let rpm = if blocked_attachment {
        0.0
    } else {
        network_rpm(&network, other_half.as_deref(), pos)
    };
    if !blocked_attachment {
        apply_network(entity, &network, other_half.as_deref(), pos);
    } else {
        entity
            .nbt
            .insert("Speed".into(), Tag::Float(0.0f32.to_bits()));
    }
    if publish_source || (first_attachment || chain_signal_changed) && !blocked_attachment {
        crate::game::create_port_kinetic_runtime::publish(game, &network, pos);
        if let Some(other) = &other_half {
            crate::game::create_port_kinetic_runtime::publish(game, other, pos);
        }
    }
    if block == crusher::WHEEL
        && (first_wheel_tick || old_rpm != rpm || game.world.game_time.rem_euclid(20) == 0)
    {
        crusher::wheel_updated(game, pos, start.axis, rpm);
    }
    let generated = match start.kind {
        Kind::Motor { rpm, .. } | Kind::WaterWheel { rpm, .. } => Some(rpm),
        _ => None,
    };
    crate::game::create_port_particles::server_tick(game, pos, entity, old_rpm, rpm, generated);
    if block == "create:hand_crank" {
        let in_use = integer(&entity.nbt, "InUse");
        if in_use > 0 {
            entity.nbt.insert("InUse".into(), Tag::Int(in_use - 1));
            if in_use == 1 {
                if let Kind::Motor { rpm, .. } = &mut start.kind {
                    (*rpm, _) = crate::game::create_port_kinetic_runtime::source_turn(
                        game, pos, entity, 0.0, false, true,
                    );
                }
                let stopped = crate::game::create_port_kinetic_runtime::network(game, start, 0);
                apply_network(entity, &stopped, None, pos);
                crate::game::create_port_kinetic_runtime::publish(game, &stopped, pos);
                game.native_block_entity_sync(pos);
            }
        }
    }
    let mut sync = old_rpm != rpm || chain_signal_changed;
    let running_rpm = running_speed(game, &entity.nbt);
    if block == super::create_port_basin::pump::PUMP {
        sync |= super::create_port_basin::pump::tick(game, pos, entity, running_rpm);
    } else if block == super::create_port_basin::pump::VALVE {
        sync |= super::create_port_basin::pump::tick_valve(game, pos, entity, running_rpm);
    }
    if block == super::create_port_contraption::BLOCK {
        let theoretical = super::create_port_kinetic_runtime::theoretical(entity);
        super::create_port_contraption::tick(game, pos, entity, theoretical, running_rpm);
    } else if block == super::create_port_contraption::WINDMILL {
        super::create_port_contraption::tick_windmill(game, pos, entity, running_rpm);
    } else if block == super::create_port_clockwork::BLOCK {
        let theoretical = super::create_port_kinetic_runtime::theoretical(entity);
        super::create_port_clockwork::tick(game, pos, entity, theoretical, running_rpm);
    } else if super::create_port_piston::is_piston(&block) {
        super::create_port_piston::tick(game, pos, entity, running_rpm);
    } else if block == super::create_port_gantry::CARRIAGE {
        super::create_port_gantry::tick_carriage(game, pos, entity);
    } else if block == super::create_port_pulley::BLOCK {
        sync |= super::create_port_pulley::tick(game, pos, entity, running_rpm);
    } else if block == super::create_port_deployer::BLOCK {
        sync |= super::create_port_deployer::tick_station(game, pos, entity, running_rpm);
    }
    sync |= crate::game::create_port_belt::tick(game, pos, entity, running_rpm);
    if block == "create:millstone" {
        sync |= crate::game::create_port_millstone::tick(game, pos, entity, running_rpm);
    }
    if block == crafter::BLOCK {
        sync |= crafter::tick(game, pos, entity, running_rpm);
    }
    if block == "create:mechanical_mixer" {
        crate::game::create_port_mixer::on_speed_changed(entity, old_rpm, rpm);
        crate::game::create_port_mixer::on_speed_changed(entity, old_running_rpm, running_rpm);
        sync |= crate::game::create_port_mixer::tick(game, pos, entity, running_rpm);
    }
    if block == "create:encased_fan" {
        crate::game::create_port_fan::tick(game, pos, entity, running_rpm);
    }
    if matches!(
        block.as_str(),
        "create:mechanical_drill" | super::create_port_drill::SAW
    ) {
        sync |= crate::game::create_port_drill::tick(game, pos, entity, running_rpm);
    }
    if block == super::create_port_drill::SAW
        && game.native_block_property(pos, "facing").as_deref() == Some("up")
    {
        sync |= super::create_port_saw_processing::tick(game, pos, entity, running_rpm);
    }
    if matches!(block.as_str(), "create:speedometer" | "create:stressometer") {
        let value = if block == "create:speedometer" {
            create_engine::visual::speed_dial(rpm)
        } else {
            create_engine::visual::stress_dial(
                network.capacity,
                network.stress,
                network.status == create_engine::kinetics::Status::Overstressed,
            )
        };
        let before = number(&entity.nbt, "Value");
        entity
            .nbt
            .insert("Value".into(), Tag::Float(value.to_bits()));
        let mix = |a: i32, b: i32, t: f32| {
            (0..3)
                .map(|i| {
                    let x = (a >> (i * 8)) & 255;
                    let y = (b >> (i * 8)) & 255;
                    ((x as f32 + (y - x) as f32 * t) as i32) << (i * 8)
                })
                .sum::<i32>()
        };
        let color = if block == "create:speedometer" {
            let base = if rpm == 0.0 {
                0
            } else if rpm.abs() < 30.0 {
                0x22FF22
            } else if rpm.abs() < 100.0 {
                0x0084FF
            } else {
                0xFF55FF
            };
            mix(base, 0xFFFFFF, 0.25)
        } else if value <= 0.0 {
            integer(&entity.nbt, "Color")
        } else if value < 0.5 {
            mix(0x00FF00, 0xFFFF00, value * 2.0)
        } else if value < 1.0 {
            mix(0xFFFF00, 0xFF0000, value * 2.0 - 1.0)
        } else {
            0xFF0000
        };
        entity.nbt.insert("Color".into(), Tag::Int(color));
        if before != value {
            sync = true;
            crate::game::create_port_instruments::changed(game, pos);
        }
    }
    if block == "create:mechanical_press" {
        // ParticleItems is source client-only/transient data, not saved state.
        entity.nbt.remove(&"ParticleItems".into());
        crate::game::create_port_press_basin::on_speed_changed(entity, old_rpm, rpm);
        crate::game::create_port_press_basin::on_speed_changed(
            entity,
            old_running_rpm,
            running_rpm,
        );
        if let Some(changed) =
            crate::game::create_port_press_basin::tick(game, pos, entity, running_rpm)
        {
            sync |= changed;
        } else {
            // PressingBehaviour.write always emits these defaults, including an
            // untouched first belt cycle (start(BELT) does not reset Finished).
            entity.nbt.entry("Finished".into()).or_insert(Tag::Byte(0));
            entity.nbt.entry("Mode".into()).or_insert(Tag::Int(0));
            let depot = [pos[0], pos[1] - 2, pos[2]];
            let mut cycle = PressCycle {
                running: integer(&entity.nbt, "Running") != 0,
                ticks: integer(&entity.nbt, "Ticks"),
                applied: integer(&entity.nbt, "Applied") != 0,
            };
            let mode = if cycle.running {
                integer(&entity.nbt, "Mode")
            } else {
                i32::from(matches!(
                    game.native_block(depot).as_str(),
                    "create:depot" | "create:belt"
                ))
            };
            let world_plan = if mode == 0 {
                crate::game::create_port_world_items::inputs(game, pos)
                    .into_iter()
                    .find_map(|input| result(game, &input.stack).map(|output| (input, output)))
            } else {
                None
            };
            let action = cycle.tick(running_rpm, world_plan.is_some());
            if action == Action::Started {
                entity.clear_client_update_fields();
                entity.nbt.remove(&"ParticleItems".into());
                entity.nbt.insert("Mode".into(), Tag::Int(mode));
            }
            if action == Action::Finished {
                entity.clear_client_update_fields();
                entity.nbt.insert("Finished".into(), Tag::Byte(1));
                entity.nbt.insert("NeedsUpdate".into(), Tag::Byte(1));
            }
            if action == Action::Press {
                let mut particle = world_plan.as_ref().map(|(input, _)| input.stack.clone());
                // tryProcessInWorld stores the original stack reference, then
                // shrinks that stack in the nonbulk count>1 branch before writeClient.
                if world_plan.is_some()
                    && let Some(item) = &mut particle
                    && item.count > 1
                {
                    item.count -= 1;
                }
                if let Some(item) = particle {
                    entity.set_client_update_fields(Compound::from([(
                        "ParticleItems".into(),
                        Tag::List(vec![horizon_items::item_nbt::item_to_nbt(&item)]),
                    )]));
                }
                crate::game::create_port_sounds::press(game, pos, rpm);
                if let Some((input, output)) = world_plan {
                    crate::game::create_port_world_items::press(game, input, output);
                }
            }
            entity
                .nbt
                .insert("Running".into(), Tag::Byte(i8::from(cycle.running)));
            entity.nbt.insert("Ticks".into(), Tag::Int(cycle.ticks));
            entity
                .nbt
                .insert("Applied".into(), Tag::Int(i32::from(cycle.applied)));
            entity
                .nbt
                .insert("LastTick".into(), Tag::Long(game.world.game_time));
            sync |= action != Action::None;
        }
    }
    if sync {
        game.native_block_entity_sync(pos);
    }
}

pub(super) fn update_tag(entity: &ModBlockEntity, tag: &mut Option<Compound>) {
    if entity.id == crusher::CONTROLLER && tag.is_none() {
        *tag = Some(super::create_port_crusher_client::update_tag(entity));
        return;
    }
    if matches!(entity.id.as_str(), item_drain::BLOCK | super::create_port_basin::tank::BLOCK | super::create_port_basin::pump::PIPE) && tag.is_none() {
        *tag = Some(entity.nbt.clone());
        return;
    }
    if (super::create_port_chute::is_chute(&entity.id)
        || entity.id == super::create_port_chute::funnel::ENTITY)
        && tag.is_none()
    {
        *tag = Some(entity.nbt.clone());
        return;
    }
    if entity.id == super::create_port_deployer::BLOCK && tag.is_none() {
        *tag = Some(super::create_port_deployer::update_tag(entity));
        return;
    }
    if (owns(&entity.id)
        || matches!(
            entity.id.as_str(),
            "create:motor"
                | "create:simple_kinetic"
                | "create:encased_shaft"
                | "create:encased_cogwheel"
                | "create:encased_large_cogwheel"
                | "create:drill"
                | "create:saw"
                | "create:blaze_heater"
        ))
        && tag.is_none()
    {
        let mut snapshot = entity.nbt.clone();
        if entity.id == crafter::BLOCK {
            crafter::render_update(entity, &mut snapshot);
        }
        super::create_port_belt::dye_update(entity, &mut snapshot);
        if entity.id == "create:depot"
            && inventory_supported(entity)
            && entity.items.first().is_none_or(Option::is_none)
        {
            // Horizon merges update tags. Absence would leave the old rendered
            // stack alive; send an explicit empty value on the wire only.
            snapshot.insert("HeldItem".into(), Tag::Compound(Compound::new()));
        }
        if entity.id == "create:mechanical_press" {
            snapshot.remove(&"ParticleItems".into());
            snapshot.extend(entity.take_client_update_fields());
            snapshot
                .entry("ParticleItems".into())
                .or_insert(Tag::List(Vec::new()));
        }
        *tag = Some(snapshot);
    }
}

pub(super) fn container(block: &str, container: &mut Option<ModContainer>) {
    if block == item_drain::BLOCK && container.is_none() {
        *container = Some(ModContainer {
            slots: 1,
            faces: std::array::from_fn(|_| Vec::new()),
            inputs: Vec::new(),
            outputs: Vec::new(),
            menu: None,
        });
    }
    crate::game::create_port_basin::container(block, container);
    crate::game::create_port_millstone::container(block, container);
    if super::create_port_chute::is_chute(block) && container.is_none() {
        *container = Some(super::create_port_chute::container(block));
    }
    if matches!(block, super::create_port_drill::SAW | crusher::CONTROLLER) && container.is_none() {
        *container = Some(super::create_port_saw_processing::container());
    }
    if matches!(block, super::create_port_deployer::BLOCK | crafter::BLOCK) && container.is_none() {
        *container = Some(ModContainer {
            slots: 1,
            faces: std::array::from_fn(|_| Vec::new()),
            inputs: Vec::new(),
            outputs: Vec::new(),
            menu: None,
        });
    }
    if block == "create:depot" && container.is_none() {
        *container = Some(ModContainer {
            slots: 9,
            faces: std::array::from_fn(|_| (0..9).collect()),
            inputs: vec![0],
            outputs: (0..9).collect(),
            menu: None,
        });
    }
}

pub(super) fn models(models: &mut Vec<String>) {
    crate::game::create_port_mixer::models(models);
    crate::game::create_port_belt::models(models);
    models.extend([
        "create:block/blaze_burner/fallback_fire".to_owned(),
        "create:block/blaze_burner/fallback_soul_fire".to_owned(),
    ]);
    for part in create_assets::WHEEL_PARTS {
        for wood in create_assets::WOODS {
            models.push(format!("create:block/{part}_material_{wood}"));
        }
    }
    models.extend(
        create_assets::PARTS
            .iter()
            .map(|name| format!("create:block/{name}")),
    );
    models.extend(
        create_assets::MOVING_BLADES
            .iter()
            .map(|(model, _)| format!("create:block/{model}")),
    );
    models.extend(
        create_assets::EXTRA_MODELS
            .iter()
            .map(|name| format!("create:{name}")),
    );
    models.extend(create_assets::pipe_attachment_models().map(str::to_owned));
}

pub(super) fn face_south(draw: &mut BlockEntityDraw, direction: Direction) {
    match direction {
        Direction::Up => draw.rotate_about([1.0, 0.0, 0.0], -90.0, [0.5; 3]),
        Direction::Down => draw.rotate_about([1.0, 0.0, 0.0], 90.0, [0.5; 3]),
        Direction::North => draw.rotate_about([0.0, 1.0, 0.0], 180.0, [0.5; 3]),
        Direction::East => draw.rotate_about([0.0, 1.0, 0.0], 90.0, [0.5; 3]),
        Direction::West => draw.rotate_about([0.0, 1.0, 0.0], -90.0, [0.5; 3]),
        Direction::South => {}
    }
}
fn port_speed(entity: &ModBlockEntity, direction: Direction) -> f32 {
    match entity
        .nbt
        .get(&"create_horizon".into())
        .and_then(|t| t.get("Ports"))
        .and_then(|t| t.get(direction.name()))
    {
        Some(Tag::Float(v)) => f32::from_bits(*v),
        _ => 0.0,
    }
}
fn trace_depot(pos: [i32; 3], stack: Option<&ItemStack>) {
    static TRACE: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
    if !*TRACE.get_or_init(|| std::env::var_os("CREATE_HORIZON_TRACE").is_some()) {
        return;
    }
    thread_local! {static LAST: std::cell::RefCell<std::collections::BTreeMap<[i32;3],Option<(String,u32)>>> = const {std::cell::RefCell::new(std::collections::BTreeMap::new())};}
    let value = stack.map(|s| (s.item.to_string(), s.count));
    LAST.with(|last| {
        let mut last=last.borrow_mut();
        if last.get(&pos) == Some(&value) {return;}
        last.insert(pos,value);
        log::info!("Create render depot: {}",serde_json::json!({"pos":pos,"stack":stack.map(|s|serde_json::json!({"item":s.item.as_ref(),"count":s.count}))}));
    });
}

pub(super) fn orient(draw: &mut BlockEntityDraw, axis: Axis) {
    match axis {
        Axis::X => draw.rotate_about([0.0, 0.0, 1.0], -90.0, [0.5; 3]),
        Axis::Z => draw.rotate_about([1.0, 0.0, 0.0], 90.0, [0.5; 3]),
        Axis::Y => {}
    }
}

pub(super) fn draw(
    game: &Game<'_>,
    pos: [i32; 3],
    block: &str,
    state: BlockStateId,
    entity: &ModBlockEntity,
    draw: &mut BlockEntityDraw,
) {
    if matches!(block, super::create_port_basin::pump::PUMP | super::create_port_basin::pump::PIPE | super::create_port_basin::pump::VALVE) {
        super::create_port_basin::pump::draw(game, pos, entity, draw);
        return;
    }
    if block == super::create_port_basin::tank::BLOCK {
        super::create_port_basin::tank::draw(game, pos, entity, draw);
        return;
    }
    if block == item_drain::BLOCK {
        item_drain::draw(game, pos, entity, draw);
        return;
    }
    if block == crafter::BLOCK {
        crafter::draw(game, pos, entity, draw);
        return;
    }
    if block == super::create_port_sticker::BLOCK {
        if let Some(state) = game.pack.assets.registry.state(state) {
            super::create_port_sticker::draw_station(game, pos, draw, state);
        }
        return;
    }
    if super::create_port_chute::is_chute(block) {
        super::create_port_chute::draw(game, pos, entity, draw);
        return;
    }
    if block == super::create_port_chute::funnel::BRASS {
        super::create_port_chute::funnel::draw(game, pos, entity, draw);
        return;
    }
    if block == super::create_port_portable_storage::BLOCK {
        super::create_port_portable_storage::draw_station(game, pos, entity, draw);
        return;
    }
    if block == super::create_port_deployer::BLOCK {
        super::create_port_deployer::draw_station(game, pos, entity, draw);
        return;
    }
    if !owns(block) {
        return;
    }
    if super::create_port_contraption::is_bearing(block) {
        super::create_port_contraption::draw_bearing(game, pos, draw);
        return;
    }
    if block == super::create_port_pulley::BLOCK {
        super::create_port_pulley::draw_controller(game, pos, entity, draw);
    }
    if block == "create:blaze_burner" {
        crate::game::create_port_burner_presentation::draw(game, pos, state, entity, draw);
        return;
    }
    if block == "create:depot" {
        // The depot's exposed top and displayed item are lit from the air above it.
        let (block_light, sky_light) = game.native_light([pos[0], pos[1] + 1, pos[2]]);
        draw.light =
            horizon_client::block_entity_render::vertex_light((sky_light << 4) | block_light);
        game.native_draw_model(draw, "create:block/depot/block", 0xFFFFFF);
        let stack = entity
            .nbt
            .get(&"HeldItem".into())
            .and_then(|held| held.get("Item"))
            .and_then(horizon_items::item_nbt::item_from_nbt);
        trace_depot(pos, stack.as_ref());
        crate::game::create_port_presentation::depot(game, pos, entity, draw);
        return;
    }
    if crate::game::create_port_belt::draw(game, pos, entity, draw) {
        return;
    }
    if crate::game::create_port_basin::draw(game, pos, entity, draw)
        || crate::game::create_port_mixer::draw(game, pos, entity, draw)
    {
        return;
    }
    if crate::game::create_port_millstone::draw(game, pos, entity, draw) {
        return;
    }
    if block == "create:mechanical_harvester" {
        if let Some(facing) = super::create_port_contraption::facing(game, pos) {
            draw.push();
            face_south(draw, facing);
            game.native_draw_model(
                draw,
                "create:block/mechanical_harvester/moving_blade",
                0xFFFFFF,
            );
            draw.pop();
        }
        return;
    }
    if block == super::create_port_drill::SAW {
        let Some(node) = node(game, pos) else { return };
        let Some(facing) = super::create_port_contraption::facing(game, pos) else {
            return;
        };
        let speed = number(&entity.nbt, "Speed");
        let angle = create_engine::visual::angle(
            draw.game_time as f64 + f64::from(draw.partial),
            speed,
            create_engine::visual::rotation_offset(pos, node.axis, false),
        );
        draw.push();
        if facing.axis() == Axis::Y {
            orient(draw, node.axis);
            draw.rotate_about([0.0, 1.0, 0.0], angle, [0.5; 3]);
            game.native_draw_model(draw, "create:block/shaft", 0xFFFFFF);
        } else {
            draw.rotate_about(
                create_engine::visual::positive_axis(node.axis),
                angle,
                [0.5; 3],
            );
            face_south(draw, facing.opposite());
            game.native_draw_model(draw, "create:block/shaft_half", 0xFFFFFF);
        }
        draw.pop();
        draw.push();
        face_south(draw, facing);
        if facing.axis() == Axis::Y
            && game
                .native_block_property(pos, "axis_along_first")
                .as_deref()
                == Some("true")
        {
            draw.rotate_about([0.0, 0.0, 1.0], 90.0, [0.5; 3]);
        }
        let model = if facing.axis() == Axis::Y {
            if speed > 0.0 {
                "create:block/mechanical_saw/moving_vertical"
            } else if speed < 0.0 {
                "create:block/mechanical_saw/moving_vertical_reverse"
            } else {
                "create:block/mechanical_saw/moving_vertical_idle"
            }
        } else if speed > 0.0 {
            "create:block/mechanical_saw/moving_horizontal"
        } else if speed < 0.0 {
            "create:block/mechanical_saw/moving_horizontal_reverse"
        } else {
            "create:block/mechanical_saw/moving_horizontal_idle"
        };
        game.native_draw_model(draw, model, 0xFFFFFF);
        draw.pop();
        if facing == Direction::Up {
            super::create_port_saw_processing::draw(game, pos, entity, draw);
            super::create_port_saw_filter::draw(game, pos, entity, draw);
        }
        return;
    }
    if crate::game::create_port_drill::draw(game, pos, entity, draw) {
        return;
    }
    if block == "create:encased_fan" {
        crate::game::create_port_fan::draw(game, pos, entity, draw);
        return;
    }
    let Some(node) = node(game, pos) else { return };
    let direction = game.native_block_property(pos, "facing");
    crate::game::create_port_presentation::hints(game, pos, draw);
    let time = draw.game_time as f64 + f64::from(draw.partial);
    if let Kind::EncasedCog { large, .. } = node.kind {
        draw_encased_cog(game, node, entity, draw, time, large);
        return;
    }
    if block == crusher::WHEEL {
        draw.push();
        orient(draw, node.axis);
        let angle = create_engine::visual::angle(
            time,
            number(&entity.nbt, "Speed"),
            create_engine::visual::rotation_offset(pos, node.axis, false),
        );
        draw.rotate_about([0.0, 1.0, 0.0], angle, [0.5; 3]);
        game.native_draw_model(draw, "create:block/crushing_wheel/block", 0xFFFFFF);
        draw.pop();
        return;
    }
    if block == FLYWHEEL {
        draw.push();
        orient(draw, node.axis);
        let angle = super::create_port_presentation::flywheel_angle(game, pos, draw.partial);
        draw.rotate_about([0.0, 1.0, 0.0], angle, [0.5; 3]);
        game.native_draw_model(draw, "create:block/flywheel/block", 0xFFFFFF);
        draw.pop();
        // The ordinary shaft below follows the network directly.
    }
    if block == "create:hand_crank" {
        let facing = Direction::from_vector(facing(direction.as_deref().unwrap_or("up"))).unwrap();
        let axis = create_engine::visual::positive_axis(node.axis);
        draw.push();
        draw.rotate_about(
            axis,
            create_engine::visual::angle(
                time,
                number(&entity.nbt, "Speed"),
                create_engine::visual::rotation_offset(pos, node.axis, false),
            ),
            [0.5; 3],
        );
        // The base model's axis is +Y; its short shaft reaches into the support.
        match facing {
            Direction::Down => draw.rotate_about([1.0, 0.0, 0.0], 180.0, [0.5; 3]),
            Direction::North => draw.rotate_about([1.0, 0.0, 0.0], -90.0, [0.5; 3]),
            Direction::South => draw.rotate_about([1.0, 0.0, 0.0], 90.0, [0.5; 3]),
            Direction::East => draw.rotate_about([0.0, 0.0, 1.0], -90.0, [0.5; 3]),
            Direction::West => draw.rotate_about([0.0, 0.0, 1.0], 90.0, [0.5; 3]),
            Direction::Up => {}
        }
        game.native_draw_model(draw, "create:block/hand_crank/block", 0xFFFFFF);
        draw.pop();
        draw.push();
        let handle_angle =
            crate::game::create_port_presentation::crank_angle(game, pos, draw.partial);
        draw.rotate_about(axis, handle_angle, [0.5; 3]);
        face_south(draw, facing.opposite());
        game.native_draw_model(draw, "create:block/hand_crank/handle", 0xFFFFFF);
        draw.pop();
        return;
    }
    if matches!(block, "create:speedometer" | "create:stressometer") {
        crate::game::create_port_instruments::draw(game, pos, entity, draw, node.axis);
    }
    if matches!(node.kind, Kind::WaterWheel { .. }) {
        crate::game::create_port_generators::draw(game, pos, entity, draw, node.axis, block);
        return;
    }
    if matches!(
        node.kind,
        Kind::Gearbox | Kind::Clutch { .. } | Kind::Gearshift { .. }
    ) {
        for direction in Direction::ALL {
            if !node.shaft_port(direction.vector()) {
                continue;
            }
            let angle = create_engine::visual::angle(
                time,
                port_speed(entity, direction),
                create_engine::visual::rotation_offset(pos, direction.axis(), false),
            );
            draw.push();
            // Rotate about the positive WORLD axis before orienting the model.
            // Rotating about local +Z after facing West/Down/North reverses it.
            draw.rotate_about(
                create_engine::visual::positive_axis(direction.axis()),
                angle,
                [0.5; 3],
            );
            face_south(draw, direction);
            game.native_draw_model(draw, "create:block/shaft_half", 0xFFFFFF);
            draw.pop();
        }
        return;
    }
    if matches!(node.kind, Kind::Motor { .. } | Kind::Press) {
        draw.push();
        let model = if node.kind == Kind::Press {
            let yaw = match direction.as_deref() {
                Some("east") => -90.0,
                Some("south") => 180.0,
                Some("west") => 90.0,
                _ => 0.0,
            };
            draw.rotate_about([0.0, 1.0, 0.0], yaw, [0.5; 3]);
            "create:block/mechanical_press/block"
        } else if matches!(direction.as_deref(), Some("up" | "down")) {
            if direction.as_deref() == Some("down") {
                draw.rotate_about([1.0, 0.0, 0.0], 180.0, [0.5; 3]);
            }
            "create:block/creative_motor/block_vertical"
        } else {
            let yaw = match direction.as_deref() {
                Some("east") => 90.0,
                Some("north") => 180.0,
                Some("west") => -90.0,
                _ => 0.0,
            };
            draw.rotate_about([0.0, 1.0, 0.0], yaw, [0.5; 3]);
            "create:block/creative_motor/block"
        };
        game.native_draw_model(draw, model, 0xFFFFFF);
        if node.kind == Kind::Press {
            let travel =
                crate::game::create_port_press_client::travel(game, pos, entity, draw.partial);
            draw.translate([0.0, -travel, 0.0]);
            game.native_draw_model(draw, "create:block/mechanical_press/head", 0xFFFFFF);
        }
        draw.pop();
    }
    draw.push();
    let angle = create_engine::visual::angle(
        time,
        number(&entity.nbt, "Speed"),
        create_engine::visual::rotation_offset(
            pos,
            node.axis,
            matches!(node.kind, Kind::Cog { large: true }),
        ),
    );
    if matches!(node.kind, Kind::Motor { .. }) {
        draw.rotate_about(
            create_engine::visual::positive_axis(node.axis),
            angle,
            [0.5; 3],
        );
        // The half shaft's untransformed output points south (+Z).
        match direction.as_deref() {
            Some("up") => draw.rotate_about([1.0, 0.0, 0.0], -90.0, [0.5; 3]),
            Some("down") => draw.rotate_about([1.0, 0.0, 0.0], 90.0, [0.5; 3]),
            Some("east") => draw.rotate_about([0.0, 1.0, 0.0], 90.0, [0.5; 3]),
            Some("west") => draw.rotate_about([0.0, 1.0, 0.0], -90.0, [0.5; 3]),
            Some("north") => draw.rotate_about([0.0, 1.0, 0.0], 180.0, [0.5; 3]),
            _ => {}
        }
        game.native_draw_model(draw, "create:block/shaft_half", 0xFFFFFF);
        draw.pop();
        return;
    }
    orient(draw, node.axis);
    draw.rotate_about([0.0, 1.0, 0.0], angle, [0.5; 3]);
    let model = match node.kind {
        Kind::Cog { large: false } => "create:block/cogwheel",
        Kind::Cog { large: true } => "create:block/large_cogwheel",
        _ => "create:block/shaft",
    };
    game.native_draw_model(
        draw,
        model,
        crate::game::create_port_presentation::kinetic_tint(game, pos),
    );
    draw.pop();
}

fn draw_encased_cog(
    game: &Game<'_>,
    node: Node,
    entity: &ModBlockEntity,
    draw: &mut BlockEntityDraw,
    time: f64,
    large: bool,
) {
    use create_engine::visual::{angle, positive_axis, rotation_offset};
    let rpm = number(&entity.nbt, "Speed");
    let tint = super::create_port_presentation::kinetic_tint(game, node.pos);
    draw.push();
    orient(draw, node.axis);
    draw.rotate_about(
        [0.0, 1.0, 0.0],
        angle(time, rpm, rotation_offset(node.pos, node.axis, large)),
        [0.5; 3],
    );
    game.native_draw_model(
        draw,
        if large {
            "create:block/large_cogwheel_shaftless"
        } else {
            "create:block/cogwheel_shaftless"
        },
        tint,
    );
    draw.pop();
    let shaft_angle = angle(time, rpm, rotation_offset(node.pos, node.axis, false));
    for direction in Direction::ALL {
        if !node.shaft_port(direction.vector()) {
            continue;
        }
        draw.push();
        draw.rotate_about(positive_axis(node.axis), shaft_angle, [0.5; 3]);
        face_south(draw, direction);
        game.native_draw_model(draw, "create:block/shaft_half", tint);
        draw.pop();
    }
}
