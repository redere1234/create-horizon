// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use super::{
    Game, GameLevel, create_port_contraption as contraption,
    create_port_contraption_storage as storage, native_block_entity_draw::BlockEntityDraw,
};
use crate::{
    containers::{BlockEntity, ModBlockEntity},
    items::ItemStack,
};
use create_engine::{
    contraption::portable_storage::{
        Actor, DEFAULT_TIMEOUT, Endpoint, PowerUpdate, Probe, Station, TickUpdate,
    },
    kinetics::{Axis, Pos},
    placement::Direction,
};
use glam::DVec3;
use horizon_client_render::create_contraption_scene::Record;
use horizon_core::{geometry::Direction as Face, position::BlockPos};
use horizon_world::{
    attachments::{AttachmentType, Holder},
    chunk::BlockState,
    nbt::{Compound, Tag},
    registry::BlockStateId,
};
use std::{collections::BTreeMap, ops::ControlFlow};

pub(super) const BLOCK: &str = "create:portable_storage_interface";

#[derive(Clone, Default)]
struct Runtime {
    docks: BTreeMap<Pos, Station>,
    movers: BTreeMap<Pos, Moving>,
}

#[derive(Clone, Default)]
struct Moving {
    actor: Actor,
    previous: Option<Probe>,
    motion: [f64; 3],
    visited: bool,
    refresh: bool,
}

const LINKS: AttachmentType<Runtime> = AttachmentType {
    namespace: "create",
    name: "portable_storage_links",
    default: Runtime::default,
    codec: None,
    copy_on_death: false,
    sync: false,
};

fn load(game: &mut Game<'_>, key: [i32; 2]) -> Option<Runtime> {
    let map = game.attachment_map_quiet(Holder::Chunk(key)).ok()?;
    Some(map.get_existing(&LINKS).ok()?.unwrap_or_default())
}

fn save(game: &mut Game<'_>, key: [i32; 2], runtime: Runtime) {
    if let Ok(map) = game.attachment_map_quiet(Holder::Chunk(key)) {
        if runtime.docks.is_empty() && runtime.movers.is_empty() {
            let _ = map.remove(&LINKS);
        } else {
            let _ = map.set(&LINKS, runtime);
        }
    }
}

fn read_nbt(nbt: &Compound) -> Station {
    let timer = u32::try_from(super::create_port::integer(nbt, "Timer")).unwrap_or(0);
    let distance = super::create_port::number(nbt, "Distance");
    let powered = super::create_port::integer(nbt, "Powered") != 0;
    Station::from_saved(timer, distance, powered).unwrap_or_default()
}

fn write_nbt(entity: &mut ModBlockEntity, station: Station) {
    entity
        .nbt
        .insert("Timer".into(), Tag::Int(station.timer() as i32));
    entity
        .nbt
        .insert("Distance".into(), Tag::Float(station.distance().to_bits()));
    entity
        .nbt
        .insert("Powered".into(), Tag::Byte(i8::from(station.powered())));
}

fn remember(runtime: &mut Runtime, pos: Pos, station: Station) {
    if station.owner().is_some() || station.timer() != 0 {
        runtime.docks.insert(pos, station);
    } else {
        runtime.docks.remove(&pos);
    }
}

fn powered(game: &mut Game<'_>, pos: Pos) -> bool {
    game.native_neighbor_signal(game.dim.id(), pos) > 0
}

fn endpoint(game: &mut Game<'_>, key: [i32; 2], pos: Pos) -> Option<Endpoint> {
    if contraption::column(pos) != key || game.native_block(pos) != BLOCK {
        return None;
    }
    station_entity(game, pos)?;
    Some(Endpoint {
        facing: contraption::facing(game, pos)?,
        powered: powered(game, pos),
    })
}

fn station_entity<'g>(game: &'g Game<'_>, pos: Pos) -> Option<&'g ModBlockEntity> {
    match game.world.block_entities.get(&(pos[0], pos[1], pos[2]))? {
        BlockEntity::Mod(entity) if entity.id == BLOCK => Some(entity),
        _ => None,
    }
}

fn station_at(game: &Game<'_>, runtime: &Runtime, pos: Pos) -> Option<Station> {
    Some(reconcile(
        runtime.docks.get(&pos).copied(),
        read_nbt(&station_entity(game, pos)?.nbt),
    ))
}

fn reconcile(live: Option<Station>, saved: Station) -> Station {
    live.filter(|live| {
        live.timer() == saved.timer()
            && live.distance() == saved.distance()
            && live.powered() == saved.powered()
    })
    .unwrap_or(saved)
}

pub(super) fn block_state(state: &BlockState) -> bool {
    state.name == BLOCK && state.properties.len() == 1 && local_facing(state).is_some()
}

fn local_facing(state: &BlockState) -> Option<Direction> {
    let facing = state.properties.get("facing")?;
    Direction::ALL
        .into_iter()
        .find(|direction| direction.name() == facing)
}

pub(super) fn can_capture(game: &Game<'_>, pos: Pos, state: &BlockState) -> bool {
    let key = (pos[0], pos[1], pos[2]);
    if !block_state(state)
        || !station_entity(game, pos).is_some_and(|entity| {
            entity.items.iter().all(Option::is_none)
                && entity.nbt.iter().all(|(key, value)| {
                    clean_field(key.to_string().as_deref().unwrap_or_default(), value)
                })
        })
        || game.world.block_names.contains_key(&key)
        || game.world.block_lock(key).is_some()
    {
        return false;
    }
    let [x, z] = contraption::column(pos);
    if game
        .world
        .block_entities
        .chunk_attachments(x, z)
        .iter()
        .any(|(p, _)| *p == key)
    {
        return false;
    }
    game.world
        .chunks
        .get(&(x, z))
        .and_then(|chunk| chunk.saved.as_ref())
        .is_none_or(|saved| {
            !saved.rolled_loot.iter().any(|loot| loot.pos == key)
                && !saved
                    .block_entity_attachments
                    .iter()
                    .any(|(p, _)| *p == key)
                && saved
                    .block_entity_sources
                    .iter()
                    .find(|(p, _)| *p == key)
                    .is_none_or(|(_, tag)| clean_source(tag))
        })
}

fn clean_field(name: &str, value: &Tag) -> bool {
    match name {
        "Timer" => *value == Tag::Int(0),
        "Distance" => {
            matches!(value, Tag::Float(bits) if (0.0..=2.0).contains(&f32::from_bits(*bits)))
        }
        "Powered" => matches!(value, Tag::Byte(0 | 1)),
        _ => false,
    }
}

fn clean_source(source: &Tag) -> bool {
    let Tag::Compound(fields) = source else {
        return false;
    };
    fields
        .iter()
        .all(|(key, value)| match key.to_string().as_deref() {
            Ok("id") => *value == Tag::String(BLOCK.into()),
            Ok("x" | "y" | "z") => matches!(value, Tag::Int(_)),
            Ok("keepPacked") => *value == Tag::Byte(0),
            Ok("components") => matches!(value, Tag::Compound(fields) if fields.is_empty()),
            Ok("Items") => matches!(value, Tag::List(items) if items.is_empty()),
            Ok(name) => clean_field(name, value),
            Err(_) => false,
        })
}

fn probe(record: &Record, local: Pos, facing: Direction) -> Option<Probe> {
    let rotation = record.orientation(record.angle);
    let center = DVec3::splat(0.5);
    let local = DVec3::from_array(Probe::local_center(local, facing)) - center;
    let point = DVec3::from_array(record.origin_at(1.0)) + center + rotation * local;
    let direction = rotation * DVec3::from_array(facing.vector().map(f64::from));
    Probe::new(point.to_array(), direction.to_array())
}

fn mover(record: &Record) -> Option<(Pos, Direction)> {
    if record.axis != Axis::Y.index()
        || record.stroke.is_some()
        || record.clock_hand.is_some()
        || record.return_home
    {
        return None;
    }
    let (local, state) = record
        .blocks
        .iter()
        .find(|(_, state)| state.name == BLOCK)?;
    Some((*local, local_facing(state)?))
}

fn publish(game: &mut Game<'_>, pos: Pos, station: Station, sync: bool, compare: bool) {
    if game
        .native_with_mod_block_entity(pos, |entity| write_nbt(entity, station))
        .is_none()
    {
        return;
    }
    if sync {
        game.native_block_entity_sync(pos);
    }
    if compare {
        game.native_update_output_neighbors(game.dim.id(), pos);
    }
}

/// The contraption samples the bearing's previously published pose before
/// the next angle is selected, as the separate original entity tick does.
pub(super) fn advance(game: &mut Game<'_>, record: &Record) -> bool {
    let Some((local, facing)) = mover(record) else {
        return false;
    };
    let key = contraption::column(record.controller);
    let Some(mut runtime) = load(game, key) else {
        return false;
    };
    let mut moving = runtime
        .movers
        .remove(&record.controller)
        .unwrap_or_default();
    let current = probe(record, local, facing);
    let visit = if let Some((old, current)) = moving.previous.zip(current)
        && !moving.actor.stalled()
    {
        moving.motion = std::array::from_fn(|i| current.position()[i] - old.position()[i]);
        !moving.visited || old.grid() != current.grid()
    } else {
        false
    };
    if (visit || moving.refresh)
        && let Some(dock) = moving.actor.visit(current, |pos| endpoint(game, key, pos))
        && let Some(mut station) = station_at(game, &runtime, dock.position)
    {
        let _ = station.set_powered(false);
        if station.start(record.controller, dock.distance) {
            remember(&mut runtime, dock.position, station);
            publish(game, dock.position, station, true, true);
        }
    }
    moving.visited |= visit;
    moving.refresh = false;
    moving.previous = current;
    if let Some((pos, end, mut station)) = moving.actor.working().and_then(|pos| {
        Some((
            pos,
            endpoint(game, key, pos)?,
            station_at(game, &runtime, pos)?,
        ))
    }) {
        let started = moving.actor.tick(
            record.controller,
            current,
            moving.motion,
            Some((end, &mut station)),
        );
        remember(&mut runtime, pos, station);
        if started {
            publish(game, pos, station, true, true);
        }
    } else {
        moving.actor.reset();
    }
    let stalled = moving.actor.stalled();
    runtime.movers.insert(record.controller, moving);
    save(game, key, runtime);
    stalled
}

pub(super) fn remove(game: &mut Game<'_>, owner: Pos) {
    let key = contraption::column(owner);
    let Some(mut runtime) = load(game, key) else {
        return;
    };
    runtime.movers.remove(&owner);
    for station in runtime.docks.values_mut() {
        if station.owner() == Some(owner) {
            station.disconnect();
        }
    }
    save(game, key, runtime);
}

pub(super) fn tick(game: &mut Game<'_>, pos: Pos, entity: &mut ModBlockEntity) {
    let key = contraption::column(pos);
    let Some(mut runtime) = load(game, key) else {
        return;
    };
    let old = read_nbt(&entity.nbt);
    let mut station = reconcile(runtime.docks.remove(&pos), old);
    let power = station.set_powered(powered(game, pos));
    if power == PowerUpdate::RefreshActors
        || (!station.powered() && !entity.nbt.contains_key(&"Timer".into()))
    {
        for moving in runtime.movers.values_mut() {
            moving.refresh = true;
        }
    }
    let update = station.tick(DEFAULT_TIMEOUT);
    remember(&mut runtime, pos, station);
    save(game, key, runtime);
    write_nbt(entity, station);
    if power != PowerUpdate::Unchanged
        || matches!(
            update,
            TickUpdate::Sync | TickUpdate::Disconnect { sync: true }
        )
        || (old.timer() <= 4 && old.timer() != station.timer())
    {
        game.native_block_entity_sync(pos);
    }
    // A powered station notifies neighbours on each ordinary countdown
    // decrement. The keepalive expiry writes its retract timer after the
    // notification, so the first off-state query comes on the next tick.
    let powered_stop = station.powered()
        && !station.connected(DEFAULT_TIMEOUT)
        && matches!(update, TickUpdate::Disconnect { sync: false });
    if old.timer() != 0 && (station.timer() == 0 || powered_stop) {
        game.native_update_output_neighbors(game.dim.id(), pos);
    }
}

pub(super) fn analog(game: &GameLevel<'_>, pos: BlockPos, state: BlockStateId, output: &mut i32) {
    if game.native_state_block(state) != Some(BLOCK) {
        return;
    }
    *output = match game.world.block_entities.get(&(pos.x, pos.y, pos.z)) {
        Some(BlockEntity::Mod(entity)) => i32::from(read_nbt(&entity.nbt).signal(DEFAULT_TIMEOUT)),
        _ => 0,
    };
}

fn draw_parts(
    game: &Game<'_>,
    draw: &mut BlockEntityDraw,
    facing: Direction,
    extension: f32,
    lit: bool,
) {
    draw.push();
    match facing {
        Direction::Up => {}
        Direction::Down => draw.rotate_about([1.0, 0.0, 0.0], 180.0, [0.5; 3]),
        _ => {
            super::create_port::face_south(draw, facing);
            draw.rotate_about([1.0, 0.0, 0.0], 90.0, [0.5; 3]);
        }
    }
    draw.push();
    draw.translate([0.0, extension / 2.0 + 0.375, 0.0]);
    let middle = if lit {
        "create:block/portable_storage_interface/block_middle_powered"
    } else {
        "create:block/portable_storage_interface/block_middle"
    };
    game.native_draw_model(draw, middle, 0xFFFFFF);
    draw.pop();
    draw.translate([0.0, extension, 0.0]);
    game.native_draw_model(
        draw,
        "create:block/portable_storage_interface/block_top",
        0xFFFFFF,
    );
    draw.pop();
}

pub(super) fn draw_station(
    game: &Game<'_>,
    pos: Pos,
    entity: &ModBlockEntity,
    draw: &mut BlockEntityDraw,
) {
    if let Some(facing) = contraption::facing(game, pos) {
        let station = read_nbt(&entity.nbt);
        draw_parts(
            game,
            draw,
            facing,
            station.extension(DEFAULT_TIMEOUT),
            station.connected(DEFAULT_TIMEOUT),
        );
    }
}

pub(super) fn draw_moving(
    game: &Game<'_>,
    draw: &mut BlockEntityDraw,
    record: &Record,
    local: Pos,
    state: &BlockState,
) {
    let Some(facing) = local_facing(state) else {
        return;
    };
    let paired = probe(record, local, facing).and_then(|probe| {
        probe.find(|pos| {
            if contraption::column(pos) != contraption::column(record.controller) {
                return None;
            }
            let station = read_nbt(&station_entity(game, pos)?.nbt);
            station.connected(DEFAULT_TIMEOUT).then_some(Endpoint {
                facing: contraption::facing(game, pos)?,
                powered: station.powered(),
            })
        })
    });
    let extension = paired
        .and_then(|dock| station_entity(game, dock.position))
        .map_or(0.0, |entity| {
            read_nbt(&entity.nbt).extension(DEFAULT_TIMEOUT)
        });
    draw_parts(game, draw, facing, extension, paired.is_some());
}

fn connected_mount(game: &mut Game<'_>, pos: Pos) -> Option<(Runtime, Station, storage::Mount)> {
    let key = contraption::column(pos);
    if !game.native_on("create") || game.native_block(pos) != BLOCK || powered(game, pos) {
        return None;
    }
    let runtime = load(game, key)?;
    let station = station_at(game, &runtime, pos).filter(|s| s.can_transfer(DEFAULT_TIMEOUT))?;
    let owner = station.owner().filter(|owner| {
        contraption::column(*owner) == key && game.native_block(*owner) == contraption::BLOCK
    })?;
    let records = contraption::entries(game, key).ok()?;
    let record = records.iter().find(|record| record.controller == owner)?;
    Some((runtime, station, storage::mounted_chest(record)?))
}

fn finish_transfer(
    game: &mut Game<'_>,
    pos: Pos,
    mut runtime: Runtime,
    mut station: Station,
    count: u32,
) {
    if station.transferred(DEFAULT_TIMEOUT, count, false) {
        remember(&mut runtime, pos, station);
        save(game, contraption::column(pos), runtime);
        publish(game, pos, station, true, false);
    }
}

fn withdraw(
    game: &mut Game<'_>,
    pos: Pos,
    take: impl FnOnce(&mut Game<'_>, storage::Mount) -> Option<ItemStack>,
) -> Option<ItemStack> {
    let (runtime, station, mount) = connected_mount(game, pos)?;
    let item = take(game, mount)?;
    finish_transfer(game, pos, runtime, station, item.count);
    Some(item)
}

pub(super) fn push_chute(
    game: &mut Game<'_>,
    station_pos: Pos,
    source: Pos,
    stack: &ItemStack,
    simulate: bool,
) -> u32 {
    let Some((runtime, station, mount)) = connected_mount(game, station_pos) else {
        return 0;
    };
    let inserted = storage::insert_from_chute(game, mount, source, stack, simulate);
    if !simulate && inserted != 0 {
        finish_transfer(game, station_pos, runtime, station, inserted);
    }
    inserted
}

pub(super) fn pull_chute(
    game: &mut Game<'_>,
    station: Pos,
    receive: impl FnOnce(&mut Game<'_>, &ItemStack) -> bool,
) -> bool {
    withdraw(game, station, |game, mount| {
        storage::withdraw_for_chute(game, mount, receive)
    })
    .is_some()
}

pub(super) fn hopper_suck(game: &mut Game<'_>, hopper: Pos) -> ControlFlow<bool> {
    let pos = [hopper[0], hopper[1] + 1, hopper[2]];
    let pulled = withdraw(game, pos, |game, mount| {
        let slots = game.native_container_slots(game.dim.id(), hopper, Face::Up)?;
        let limits: Vec<_> = slots
            .into_iter()
            .map(|slot| {
                slot.stack.map(|stack| {
                    let limit = super::create_port::stack_maximum(game, &stack);
                    (stack, limit)
                })
            })
            .collect();
        storage::withdraw_one(
            game,
            mount,
            |candidate| {
                limits.iter().any(|slot| match slot {
                    None => true,
                    Some((stack, limit)) => {
                        stack.count == 0
                            || (stack.count < *limit && stack.same_item_same_components(candidate))
                    }
                })
            },
            |game, item| {
                game.native_insert_item(hopper, Face::Up, item.clone())
                    .is_none()
            },
        )
    })
    .is_some();
    if pulled {
        ControlFlow::Break(true)
    } else {
        ControlFlow::Continue(())
    }
}
