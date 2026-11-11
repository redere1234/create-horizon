// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

// ChestMountedStorage, simple barrel storage and the mounted item handler.

use super::{Game, create_port_contraption as contraption};
use crate::{containers::BlockEntity, items::ItemStack};
use create_engine::{
    contraption::QuarterTurn,
    kinetics::{Axis, Pos},
    placement::Direction,
};
use horizon_client_render::create_contraption_scene::{MAX_RECORDS, Record, StrokeKind};
use horizon_items::item_nbt::{encode_items, item_from_nbt};
use horizon_world::{
    attachments::{
        AttachmentCodec, AttachmentError, AttachmentType, Attachments, Holder,
        create_contraption_attachment::{decoded, encoded},
    },
    chunk::BlockState,
    nbt::{Compound, Limits, Tag, write_network},
    registry::BlockStateId,
};
use std::{borrow::Cow, collections::BTreeMap};

const BLOCK: &str = "minecraft:chest";
const BARREL: &str = "minecraft:barrel";
const SIZE: usize = 27;
const MAX_BANKS: usize = 2;
const SLOT_LIMIT: u32 = 64;
const MAX_STORAGE_BYTES: usize = 1024 * 1024;

#[derive(Clone, Debug)]
pub(super) struct Chest {
    // Horizon uses BlockEntity::Chest for both of these 27-slot containers.
    locals: Vec<Pos>,
    slots: Vec<Option<ItemStack>>,
}

type Store = BTreeMap<Pos, Chest>;
type Edit = (Pos, BlockStateId, BlockStateId);

#[derive(Clone, Copy)]
pub(super) struct Mount {
    controller: Pos,
    locals: [Option<Pos>; MAX_BANKS],
}

impl Chest {
    fn matches_mount(&self, mount: Mount) -> bool {
        self.locals
            .iter()
            .copied()
            .eq(mount.locals.into_iter().flatten())
    }
}

// Kept in the same saved chunk as the pose. Unlike the scene attachment,
// inventories must never be sent to tracking clients in chunk updates.
const STORAGE: AttachmentType<Store> = AttachmentType {
    namespace: "create",
    name: "mounted_item_storage",
    default: Store::new,
    codec: Some(AttachmentCodec { encode, decode }),
    copy_on_death: false,
    sync: false,
};

pub(super) fn chest_state(state: &BlockState) -> bool {
    state.name == BLOCK
        && state.properties.len() == 3
        && state
            .properties
            .get("type")
            .is_some_and(|kind| kind == "single")
        && state
            .properties
            .get("waterlogged")
            .is_some_and(|wet| wet == "false")
        && state
            .properties
            .get("facing")
            .is_some_and(|face| matches!(face.as_str(), "north" | "south" | "east" | "west"))
}

pub(super) fn barrel_state(state: &BlockState) -> bool {
    state.name == BARREL
        && state.properties.len() == 2
        && state
            .properties
            .get("open")
            .is_some_and(|open| open == "false")
        && state
            .properties
            .get("facing")
            .is_some_and(|facing| Direction::ALL.into_iter().any(|face| face.name() == facing))
}

pub(super) fn mounted_state(state: &BlockState) -> bool {
    chest_state(state) || barrel_state(state)
}

pub(super) fn can_capture(game: &Game<'_>, position: Pos, state: &BlockState) -> bool {
    let key = (position[0], position[1], position[2]);
    if !mounted_state(state)
        || !matches!(game.world.block_entities.get(&key), Some(BlockEntity::Chest(slots)) if slots.len() == SIZE)
        || game.world.block_names.contains_key(&key)
        || game.world.block_lock(key).is_some()
        || game.container == Some(key)
        || game.lan.as_ref().is_some_and(|host| {
            host.hub.guests.iter().any(|guest| {
                guest.dimension == game.dim.id()
                    && guest.menu.as_ref().is_some_and(|menu| match &menu.slots {
                        crate::lan::menu::Slots::Block(pos) => *pos == key,
                        crate::lan::menu::Slots::Double(first, second) => {
                            *first == key || *second == key
                        }
                        _ => false,
                    })
            })
        })
    {
        return false;
    }
    let column = (position[0] >> 4, position[2] >> 4);
    if game
        .world
        .block_entities
        .chunk_attachments(column.0, column.1)
        .iter()
        .any(|(pos, _)| *pos == key)
    {
        return false;
    }
    let Some(saved) = game
        .world
        .chunks
        .get(&column)
        .and_then(|chunk| chunk.saved.as_ref())
    else {
        return true;
    };
    !saved.rolled_loot.iter().any(|loot| loot.pos == key)
        && !saved
            .block_entity_attachments
            .iter()
            .any(|(pos, _)| *pos == key)
        && saved
            .block_entity_sources
            .iter()
            .find(|(pos, _)| *pos == key)
            .is_none_or(|(_, tag)| plain_source(tag, &state.name))
}

fn plain_source(tag: &Tag, block: &str) -> bool {
    let Tag::Compound(fields) = tag else {
        return false;
    };
    fields
        .iter()
        .all(|(key, value)| match key.to_string().as_deref() {
            Ok("id") => *value == Tag::String(block.into()),
            Ok("x" | "y" | "z") => matches!(value, Tag::Int(_)),
            Ok("keepPacked") => matches!(value, Tag::Byte(0)),
            Ok("components") => matches!(value, Tag::Compound(components) if components.is_empty()),
            Ok("Items") => decode_slots(value).is_some(),
            _ => false,
        })
}

fn local_storage(
    blocks: &[(Pos, BlockState)],
    allow_pair: bool,
) -> Result<Vec<(Pos, &BlockState)>, AttachmentError> {
    let mut result = Vec::new();
    let limit = if allow_pair { MAX_BANKS } else { 1 };
    for (position, block) in blocks
        .iter()
        .filter(|(_, block)| matches!(block.name.as_str(), BLOCK | BARREL))
    {
        if !mounted_state(block)
            || !valid_local(*position)
            || result.len() == limit
            || result.iter().any(|&(local, _)| local == *position)
        {
            return Err(AttachmentError::Decode);
        }
        result.push((*position, block));
    }
    // MountedStorageManager copies a default Java HashMap's iteration order.
    // With at most two banks, a bucket's entries keep their insertion order.
    // Stable sorting preserves the capture traversal order within each bucket.
    result.sort_by_key(|&(local, _)| storage_bucket(local));
    Ok(result)
}

fn storage_bucket([x, y, z]: Pos) -> u32 {
    // Vec3i.hashCode and HashMap.hash. Valid local coordinates are bounded.
    let hash = (x + 31 * (y + 31 * z)) as u32;
    (hash ^ (hash >> 16)) & 15
}

fn valid_local(pos: Pos) -> bool {
    pos.iter().all(|component| component.unsigned_abs() <= 15)
}

fn supports_pair(record: &Record) -> bool {
    record.axis == Axis::Y.index()
        && record.stroke.is_none()
        && record.clock_hand.is_none()
        && !record.return_home
}

pub(super) fn mounted_chest(record: &Record) -> Option<Mount> {
    if record.clock_hand.is_some() || record.return_home {
        return None;
    }
    let banks = local_storage(&record.blocks, supports_pair(record)).ok()?;
    let (_, state) = banks.first()?;
    let supported = match record.stroke_kind() {
        Some(StrokeKind::Gantry | StrokeKind::RopePulley | StrokeKind::Piston) => true,
        None => record.axis == Axis::Y.index() || state.name == BARREL,
    };
    if !supported {
        return None;
    }
    let mut locals = [None; MAX_BANKS];
    for (slot, (local, _)) in locals.iter_mut().zip(banks) {
        *slot = Some(local);
    }
    Some(Mount {
        controller: record.controller,
        locals,
    })
}

pub(super) fn capture(
    game: &Game<'_>,
    anchor: Pos,
    blocks: &[(Pos, BlockState)],
    allow_pair: bool,
) -> Result<Option<Chest>, AttachmentError> {
    let banks = local_storage(blocks, allow_pair)?;
    if banks.is_empty() {
        return Ok(None);
    }
    let mut chest = Chest {
        locals: Vec::with_capacity(banks.len()),
        slots: Vec::with_capacity(banks.len() * SIZE),
    };
    for (local, expected) in banks {
        let position = place(anchor, local).ok_or(AttachmentError::Encode)?;
        let state = game
            .pack
            .assets
            .registry
            .state(contraption::state(game, position))
            .ok_or(AttachmentError::Encode)?;
        if state != expected || !can_capture(game, position, state) {
            return Err(AttachmentError::Encode);
        }
        let Some(BlockEntity::Chest(slots)) =
            game.world
                .block_entities
                .get(&(position[0], position[1], position[2]))
        else {
            return Err(AttachmentError::Encode);
        };
        checked_slots(slots)?;
        chest.locals.push(local);
        chest.slots.extend_from_slice(slots);
    }
    Ok(Some(chest))
}

pub(super) fn commit_capture(
    game: &mut Game<'_>,
    key: [i32; 2],
    records: Vec<Record>,
    edits: &[Edit],
    controller: Pos,
    chest: Option<Chest>,
) -> bool {
    let Some(chest) = chest else {
        return contraption::commit(game, key, records, edits);
    };
    let Ok((mut store, before)) = private_map(game, key) else {
        return false;
    };
    if store.insert(controller, chest).is_some() || write_store(game, key, store).is_err() {
        return false;
    }
    commit(game, key, records, edits, before)
}

pub(super) fn commit_landing(
    game: &mut Game<'_>,
    key: [i32; 2],
    records: Vec<Record>,
    edits: &[Edit],
    record: &Record,
    origin: Pos,
    turn: QuarterTurn,
) -> bool {
    let banks = match local_storage(&record.blocks, supports_pair(record)) {
        Ok(banks) if banks.is_empty() => return contraption::commit(game, key, records, edits),
        Ok(banks) => banks,
        Err(_) => return false,
    };
    let Ok((mut store, before)) = private_map(game, key) else {
        return false;
    };
    let Some(chest) = store.remove(&record.controller).filter(|chest| {
        chest.slots.len() == banks.len() * SIZE
            && chest
                .locals
                .iter()
                .copied()
                .eq(banks.iter().map(|&(local, _)| local))
    }) else {
        return false;
    };
    let mut destinations = Vec::with_capacity(banks.len());
    for ((local, state), slots) in banks.into_iter().zip(chest.slots.chunks_exact(SIZE)) {
        let Some(position) = turn.place(origin, local) else {
            return false;
        };
        let target = (position[0], position[1], position[2]);
        if contraption::column(position) != key
            || game.world.block_entities.contains_key(&target)
            || !edits.iter().any(|(p, _, after)| {
                *p == position
                    && game
                        .pack
                        .assets
                        .registry
                        .state(*after)
                        .is_some_and(|target| target.name == state.name && mounted_state(target))
            })
        {
            return false;
        }
        destinations.push((position, target, slots.to_vec()));
    }
    if write_store(game, key, store).is_err() {
        return false;
    }
    if !commit(game, key, records, edits, before) {
        return false;
    }
    // The world edit creates a vanilla container; install its validated
    // contents before the server can save, tick hoppers, or accept a click.
    for (position, target, slots) in destinations {
        game.world
            .block_entities
            .insert(target, BlockEntity::Chest(slots));
        game.native_block_entity_sync(position);
    }
    true
}

fn place(anchor: Pos, local: Pos) -> Option<Pos> {
    Some([
        anchor[0].checked_add(local[0])?,
        anchor[1].checked_add(local[1])?,
        anchor[2].checked_add(local[2])?,
    ])
}

fn private_map(
    game: &mut Game<'_>,
    key: [i32; 2],
) -> Result<(Store, Attachments), AttachmentError> {
    let attachments = game.attachment_map_quiet(Holder::Chunk(key))?;
    let store = attachments.get_existing(&STORAGE)?.unwrap_or_default();
    Ok((store, attachments.clone()))
}

fn write_store(game: &mut Game<'_>, key: [i32; 2], store: Store) -> Result<(), AttachmentError> {
    let attachments = game.attachment_map_quiet(Holder::Chunk(key))?;
    if store.is_empty() {
        attachments.remove(&STORAGE)?;
        Ok(())
    } else {
        attachments.set(&STORAGE, store)
    }
}

pub(super) fn menu_slots(
    game: &Game<'_>,
    controller: Pos,
    local: Pos,
) -> Option<Vec<Option<ItemStack>>> {
    let [x, z] = contraption::column(controller);
    let map = &game.world.chunks.get(&(x, z))?.saved.as_ref()?.attachments;
    let store = match decoded(map, &STORAGE) {
        Some(store) => Cow::Borrowed(store),
        None => Cow::Owned(decode(encoded(map, STORAGE.namespace, STORAGE.name)?).ok()?),
    };
    let chest = store.get(&controller)?;
    let bank = chest.locals.iter().position(|&pos| pos == local)? * SIZE;
    Some(chest.slots.get(bank..bank + SIZE)?.to_vec())
}

pub(super) fn set_menu_slots(
    game: &mut Game<'_>,
    controller: Pos,
    local: Pos,
    slots: Vec<Option<ItemStack>>,
) -> Result<(), AttachmentError> {
    let key = contraption::column(controller);
    let mut store = game
        .attachment_map_quiet(Holder::Chunk(key))?
        .get_existing(&STORAGE)?
        .ok_or(AttachmentError::MissingHolder)?;
    let chest = store
        .get_mut(&controller)
        .ok_or(AttachmentError::MissingHolder)?;
    let bank = chest
        .locals
        .iter()
        .position(|&pos| pos == local)
        .ok_or(AttachmentError::MissingHolder)?
        * SIZE;
    checked_slots(&slots)?;
    chest.slots[bank..bank + SIZE].clone_from_slice(&slots);
    write_store(game, key, store)
}

fn commit(
    game: &mut Game<'_>,
    key: [i32; 2],
    records: Vec<Record>,
    edits: &[Edit],
    before: Attachments,
) -> bool {
    if contraption::commit(game, key, records, edits) {
        return true;
    }
    restore_map(game, key, before);
    false
}

fn restore_map(game: &mut Game<'_>, key: [i32; 2], before: Attachments) {
    if let Ok(map) = game.attachment_map_quiet(Holder::Chunk(key)) {
        *map = before;
    }
}

/// ItemHelper.extract(EXACTLY, 1) scans the mounted handler in slot order.
/// Publish the withdrawn item only if its recipient commits in the same column.
pub(super) fn withdraw_one(
    game: &mut Game<'_>,
    mount: Mount,
    matches_filter: impl FnMut(&ItemStack) -> bool,
    receive: impl FnOnce(&mut Game<'_>, &ItemStack) -> bool,
) -> Option<ItemStack> {
    withdraw(
        game,
        mount,
        |_, slots| extract_one(slots, matches_filter),
        receive,
    )
}

pub(super) fn withdraw_for_chute(
    game: &mut Game<'_>,
    mount: Mount,
    receive: impl FnOnce(&mut Game<'_>, &ItemStack) -> bool,
) -> Option<ItemStack> {
    use create_engine::chute::{Source, pull_plan};

    withdraw(
        game,
        mount,
        |game, slots| {
            let candidates = slots.iter().enumerate().filter_map(|(slot, item)| {
                let stack = item.as_ref()?;
                Some(Source {
                    slot,
                    stack,
                    count: stack.count,
                    maximum: super::create_port::stack_maximum(game, stack),
                })
            });
            let plan = pull_plan(candidates, ItemStack::same_item_same_components);
            let mut result: Option<ItemStack> = None;
            for (slot, count) in plan {
                let item = take_from_slot(slots.get_mut(slot)?, count)?;
                if let Some(result) = &mut result {
                    result.count += item.count;
                } else {
                    result = Some(item);
                }
            }
            result
        },
        receive,
    )
}

fn withdraw(
    game: &mut Game<'_>,
    mount: Mount,
    extract: impl FnOnce(&Game<'_>, &mut [Option<ItemStack>]) -> Option<ItemStack>,
    receive: impl FnOnce(&mut Game<'_>, &ItemStack) -> bool,
) -> Option<ItemStack> {
    let key = contraption::column(mount.controller);
    let holder = Holder::Chunk(key);
    let mut store = game
        .attachment_map_quiet(holder)
        .ok()?
        .get_existing(&STORAGE)
        .ok()??;
    let chest = store
        .get_mut(&mount.controller)
        .filter(|chest| chest.matches_mount(mount))?;
    let item = extract(game, &mut chest.slots)?;
    let before = game.attachment_map_quiet(holder).ok()?.clone();
    write_store(game, key, store).ok()?;
    if receive(game, &item) {
        Some(item)
    } else {
        restore_map(game, key, before);
        None
    }
}

fn extract_one(
    slots: &mut [Option<ItemStack>],
    mut matches_filter: impl FnMut(&ItemStack) -> bool,
) -> Option<ItemStack> {
    let slot = slots.iter_mut().find(|slot| {
        slot.as_ref()
            .is_some_and(|stack| stack.count > 0 && matches_filter(stack))
    })?;
    take_from_slot(slot, 1)
}

fn take_from_slot(slot: &mut Option<ItemStack>, count: u32) -> Option<ItemStack> {
    let stack = slot.as_mut()?;
    let mut item = stack.clone();
    item.count = count.min(stack.count);
    stack.count -= item.count;
    if stack.count == 0 {
        *slot = None;
    }
    Some(item)
}

/// ChuteBlockEntity uses ItemHandlerHelper.insertItemStacked. A preview
/// mutates only the copied chest, and a commit reports the saved count.
pub(super) fn insert_from_chute(
    game: &mut Game<'_>,
    mount: Mount,
    source: Pos,
    stack: &ItemStack,
    simulate: bool,
) -> u32 {
    let key = contraption::column(mount.controller);
    if contraption::column(source) != key {
        return 0;
    }
    let Ok(Some(mut store)) = game
        .attachment_map_quiet(Holder::Chunk(key))
        .and_then(|map| map.get_existing(&STORAGE))
    else {
        return 0;
    };
    let Some(chest) = store
        .get_mut(&mount.controller)
        .filter(|chest| chest.matches_mount(mount))
    else {
        return 0;
    };
    let limit = super::create_port::stack_maximum(game, stack).min(SLOT_LIMIT);
    let inserted = insert_stacked(&mut chest.slots, stack, limit);
    if inserted == 0 {
        return 0;
    }
    if simulate {
        if chest
            .slots
            .chunks_exact(SIZE)
            .any(|slots| checked_slots(slots).is_err())
        {
            return 0;
        }
    } else if write_store(game, key, store).is_err() {
        return 0;
    }
    inserted
}

fn insert_stacked(slots: &mut [Option<ItemStack>], stack: &ItemStack, limit: u32) -> u32 {
    let merged = insert(slots.iter_mut().filter(|slot| slot.is_some()), stack, limit);
    if merged == stack.count {
        return merged;
    }
    let mut remainder = stack.clone();
    remainder.count -= merged;
    merged
        + insert(
            slots.iter_mut().filter(|slot| slot.is_none()),
            &remainder,
            limit,
        )
}

/// Insert a block's drops in their loot-table order. Suppress accepted stacks
/// only when their new inventory snapshot was saved successfully.
pub(super) fn deposit(game: &mut Game<'_>, mount: Mount, source: Pos, drops: &mut [ItemStack]) {
    let key = contraption::column(mount.controller);
    // The source block and the inventory must persist in one chunk snapshot.
    if contraption::column(source) != key
        || drops.is_empty()
        || !game
            .world
            .chunks
            .get(&(key[0], key[1]))
            .and_then(|chunk| chunk.saved.as_ref())
            .is_some_and(|saved| saved.attachments.has(&STORAGE))
    {
        return;
    }
    let Ok(Some(mut store)) = game
        .attachment_map_quiet(Holder::Chunk(key))
        .and_then(|map| map.get_existing(&STORAGE))
    else {
        return;
    };
    let Some(chest) = store
        .get_mut(&mount.controller)
        .filter(|chest| chest.matches_mount(mount))
    else {
        return;
    };
    let mut accepted = Vec::with_capacity(drops.len());
    for stack in drops.iter() {
        let limit = match stack
            .data()
            .and_then(|data| data.other("minecraft:max_stack_size"))
        {
            Some(Tag::Int(limit @ 1..=99)) => *limit as u32,
            _ => game
                .items()
                .get(&stack.item)
                .map_or(0, |item| item.max_stack),
        };
        accepted.push(insert(&mut chest.slots, stack, limit.min(SLOT_LIMIT)));
    }
    if accepted.iter().all(|&count| count == 0) || write_store(game, key, store).is_err() {
        return;
    }
    for (stack, count) in drops.iter_mut().zip(accepted) {
        stack.count -= count;
    }
}

fn insert<'a>(
    slots: impl IntoIterator<Item = &'a mut Option<ItemStack>>,
    stack: &ItemStack,
    limit: u32,
) -> u32 {
    let mut remaining = stack.count;
    if limit == 0 || stack.item.as_ref() == "minecraft:air" {
        return 0;
    }
    for slot in slots {
        if remaining == 0 {
            break;
        }
        match slot {
            Some(existing) if existing.same_item_same_components(stack) => {
                let amount = limit.saturating_sub(existing.count).min(remaining);
                existing.count += amount;
                remaining -= amount;
            }
            None => {
                let amount = limit.min(remaining);
                let mut stored = stack.clone();
                stored.count = amount;
                *slot = Some(stored);
                remaining -= amount;
            }
            _ => {}
        }
    }
    stack.count - remaining
}

fn encode(store: &Store) -> Result<Compound, AttachmentError> {
    if store.len() > MAX_RECORDS {
        return Err(AttachmentError::Encode);
    }
    let mut entries = Vec::new();
    let mut version = 1;
    for (controller, chest) in store {
        if chest.locals.is_empty()
            || chest.locals.len() > MAX_BANKS
            || chest.slots.len() != chest.locals.len() * SIZE
            || chest.locals.iter().any(|&pos| !valid_local(pos))
        {
            return Err(AttachmentError::Encode);
        }
        if let [first, second] = chest.locals.as_slice() {
            if first == second {
                return Err(AttachmentError::Encode);
            }
            version = 2;
        }
        for (local, slots) in chest.locals.iter().zip(chest.slots.chunks_exact(SIZE)) {
            entries.push(Tag::compound([
                ("Controller", Tag::IntArray(controller.to_vec())),
                ("Pos", Tag::IntArray(local.to_vec())),
                ("Items", checked_slots(slots)?),
            ]));
        }
    }
    Ok(Compound::from([
        ("Version".into(), Tag::Int(version)),
        ("Chests".into(), Tag::List(entries)),
    ]))
}

fn checked_slots(slots: &[Option<ItemStack>]) -> Result<Tag, AttachmentError> {
    let nbt = encode_items(slots);
    let limits = Limits {
        max_bytes: MAX_STORAGE_BYTES,
        ..Limits::default()
    };
    if slots.len() != SIZE
        || write_network(&nbt, limits).is_err()
        || !decode_slots(&nbt).is_some_and(|decoded| decoded == slots)
    {
        return Err(AttachmentError::Encode);
    }
    Ok(nbt)
}

fn decode(saved: &Compound) -> Result<Store, AttachmentError> {
    let invalid = AttachmentError::Decode;
    let Some(Tag::List(entries)) = saved.get(&"Chests".into()) else {
        return Err(invalid);
    };
    let max_banks = match saved.get(&"Version".into()) {
        Some(Tag::Int(1)) => 1,
        Some(Tag::Int(2)) => MAX_BANKS,
        _ => return Err(invalid),
    };
    if saved.len() != 2 || entries.len() > MAX_RECORDS * max_banks {
        return Err(invalid);
    }
    let position = |entry: &Tag, key: &str| match entry.get(key) {
        Some(Tag::IntArray(values)) => <Pos>::try_from(values.as_slice()).map_err(|_| invalid),
        _ => Err(invalid),
    };
    let mut store = Store::new();
    for entry in entries {
        if !matches!(entry, Tag::Compound(fields) if fields.len() == 3) {
            return Err(invalid);
        }
        let controller = position(entry, "Controller")?;
        let local = position(entry, "Pos")?;
        let items = entry.get("Items").ok_or(invalid)?;
        let slots = decode_slots(items).ok_or(invalid)?;
        let limits = Limits {
            max_bytes: MAX_STORAGE_BYTES,
            ..Limits::default()
        };
        if !valid_local(local) || write_network(items, limits).is_err() {
            return Err(invalid);
        }
        let chest = store.entry(controller).or_insert_with(|| Chest {
            locals: Vec::new(),
            slots: Vec::new(),
        });
        if chest.locals.len() == max_banks || chest.locals.contains(&local) {
            return Err(invalid);
        }
        chest.locals.push(local);
        chest.slots.extend(slots);
    }
    if store.len() > MAX_RECORDS {
        return Err(invalid);
    }
    Ok(store)
}

fn decode_slots(tag: &Tag) -> Option<Vec<Option<ItemStack>>> {
    let Tag::List(items) = tag else { return None };
    if items.len() > SIZE {
        return None;
    }
    let mut slots = vec![None; SIZE];
    for item in items {
        let Some(Tag::Byte(slot @ 0..=26)) = item.get("Slot") else {
            return None;
        };
        let target = &mut slots[*slot as usize];
        if target.is_some() {
            return None;
        }
        *target = Some(item_from_nbt(item)?);
    }
    // Horizon's vanilla decoder tolerates malformed counts and unknown
    // fields. Keep the mounted codec strict so nothing is silently altered.
    (encode_items(&slots) == *tag).then_some(slots)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mounted_withdrawal_takes_one_from_first_matching_slot() {
        let sapling = "minecraft:oak_sapling";
        let filter = |stack: &ItemStack| stack.item.as_ref() == sapling;
        let mut slots = vec![None; SIZE];
        slots[0] = Some(ItemStack::new("minecraft:oak_log", 4));
        slots[3] = Some(ItemStack::new(sapling, 2));
        slots[8] = Some(ItemStack::new(sapling, 1));

        for index in [3, 3, 8] {
            let before = slots[index].as_ref().unwrap().count;
            assert_eq!(
                extract_one(&mut slots, filter),
                Some(ItemStack::new(sapling, 1))
            );
            assert_eq!(
                slots[index].as_ref().map_or(0, |stack| stack.count),
                before - 1
            );
        }
        assert_eq!(extract_one(&mut slots, filter), None);
        assert_eq!(slots[0], Some(ItemStack::new("minecraft:oak_log", 4)));
        assert_eq!(
            extract_one(&mut slots, |_| true),
            Some(ItemStack::new("minecraft:oak_log", 1))
        );
    }

    #[test]
    fn moving_storage_uses_java_slot_order_and_component_equality() {
        let mut slots = vec![None; SIZE];
        let mut plain = ItemStack::new("minecraft:wheat", 60);
        let mut named = ItemStack::new("minecraft:wheat", 4);
        named
            .data_mut()
            .set_other("minecraft:custom_name", Some(Tag::String("Seed".into())));
        slots[1] = Some(plain.clone());
        slots[2] = Some(named.clone());
        plain.count = 70;
        assert_eq!(insert(&mut slots, &plain, 64), 70);
        assert_eq!(slots[0].as_ref().unwrap().count, 64);
        assert_eq!(slots[1].as_ref().unwrap().count, 64);
        assert_eq!(slots[2], Some(named));
        assert_eq!(slots[3].as_ref().unwrap().count, 2);
    }

    #[test]
    fn chute_insertion_merges_existing_stacks_before_using_earlier_empty_slots() {
        let item = ItemStack::new("minecraft:oak_sapling", 16);
        let mut slots = [None, Some(ItemStack::new(item.item.as_ref(), 60))];
        assert_eq!(insert_stacked(&mut slots, &item, 64), 16);
        assert_eq!(slots[0], Some(ItemStack::new(item.item.as_ref(), 12)));
        assert_eq!(slots[1], Some(ItemStack::new(item.item.as_ref(), 64)));

        let mut slots = [
            Some(ItemStack::new("minecraft:stone", 64)),
            Some(ItemStack::new(item.item.as_ref(), 60)),
        ];
        assert_eq!(insert_stacked(&mut slots, &item, 64), 4);
        assert_eq!(insert_stacked(&mut slots, &item, 64), 0);
        assert_eq!(slots[1], Some(ItemStack::new(item.item.as_ref(), 64)));
    }

    #[test]
    fn private_codec_keeps_slot_components_and_rejects_duplicate_or_invalid_slots() {
        let mut slots = vec![None; SIZE];
        let mut item = ItemStack::new("minecraft:stick", 17);
        item.data_mut()
            .set_other("minecraft:max_stack_size", Some(Tag::Int(19)));
        slots[26] = Some(item);
        let records = Store::from([(
            [1, 70, 2],
            Chest {
                locals: vec![[1, 0, 0]],
                slots: slots.clone(),
            },
        )]);
        let legacy = Compound::from([
            ("Version".into(), Tag::Int(1)),
            (
                "Chests".into(),
                Tag::List(vec![Tag::compound([
                    ("Controller", Tag::IntArray(vec![1, 70, 2])),
                    ("Pos", Tag::IntArray(vec![1, 0, 0])),
                    ("Items", encode_items(&slots)),
                ])]),
            ),
        ]);
        assert_eq!(encode(&records).unwrap(), legacy);
        assert_eq!(decode(&legacy).unwrap()[&[1, 70, 2]].slots, slots);
        let mut outside = records.clone();
        outside.get_mut(&[1, 70, 2]).unwrap().locals[0] = [0, 16, 0];
        assert!(encode(&outside).is_err());
        let mut attachment = Attachments::default();
        attachment.set(&STORAGE, records).unwrap();
        assert!(attachment.synced().is_empty());
        assert!(attachment.take_sync_changes().is_empty());
        let mut reloaded = Attachments::from_nbt(attachment.to_nbt());
        assert!(reloaded.synced().is_empty());
        assert_eq!(
            reloaded.get_existing(&STORAGE).unwrap().unwrap()[&[1, 70, 2]].slots,
            slots
        );
        let Tag::List(mut entries) = encode_items(&slots) else {
            unreachable!()
        };
        assert!(decode_slots(&Tag::List(vec![entries[0].clone(), entries[0].clone()])).is_none());
        let Tag::Compound(slot) = &mut entries[0] else {
            unreachable!()
        };
        slot.insert("Slot".into(), Tag::Byte(27));
        assert!(decode_slots(&Tag::List(entries)).is_none());
    }

    #[test]
    fn paired_banks_keep_source_order_and_distinguish_actor_and_chute_insertion() {
        let south = [0, 0, 1];
        let east = [1, 0, 0];
        let west = [-1, 0, 0];
        assert_eq!(storage_bucket(south), storage_bucket(east));
        assert!(storage_bucket(west) < storage_bucket(south));

        let barrel = BlockState {
            name: BARREL.into(),
            properties: [
                ("open".into(), "false".into()),
                ("facing".into(), "east".into()),
            ]
            .into_iter()
            .collect(),
        };
        for capture_order in [[south, east], [east, south], [west, south]] {
            let blocks = capture_order.map(|pos| (pos, barrel.clone()));
            let banks = local_storage(&blocks, true).unwrap();
            assert!(banks.into_iter().map(|(pos, _)| pos).eq(capture_order));
        }

        let controller = [1, 70, 2];
        let diamond = "minecraft:diamond";
        let mut slots = vec![None; 2 * SIZE];
        slots[SIZE] = Some(ItemStack::new(diamond, 62));
        let source = Store::from([(
            controller,
            Chest {
                locals: vec![west, south],
                slots: slots.clone(),
            },
        )]);
        let encoded = encode(&source).unwrap();
        assert_eq!(encoded.get(&"Version".into()), Some(&Tag::Int(2)));
        let restored = decode(&encoded).unwrap().remove(&controller).unwrap();
        assert_eq!(restored.locals, [west, south]);
        assert_eq!(restored.slots, slots);

        let input = ItemStack::new(diamond, 4);
        let mut actor = restored.slots.clone();
        assert_eq!(insert(&mut actor, &input, 64), 4);
        assert_eq!(actor[0].as_ref().unwrap().count, 4);
        assert_eq!(actor[SIZE].as_ref().unwrap().count, 62);
        let mut chute = restored.slots;
        assert_eq!(insert_stacked(&mut chute, &input, 64), 4);
        assert_eq!(chute[0].as_ref().unwrap().count, 2);
        assert_eq!(chute[SIZE].as_ref().unwrap().count, 64);

        let mut legacy = encoded.clone();
        legacy.insert("Version".into(), Tag::Int(1));
        assert!(decode(&legacy).is_err());
        let mut duplicate = encoded;
        let Tag::List(entries) = duplicate.get_mut(&"Chests".into()).unwrap() else {
            unreachable!();
        };
        entries[1] = entries[0].clone();
        assert!(decode(&duplicate).is_err());
    }
}
