// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT
// Game-stack adapter for DepotBehaviour and BeltPressingCallbacks.
use super::create_port_belt as belt;
use crate::{containers::ModBlockEntity, items::ItemStack};
use create_engine::transport::{ProcessingResult, ProcessingUpdate, Transported, TransportedResult};
use horizon_world::nbt::Tag;

pub(super) fn insert(
    slots: &mut [Option<ItemStack>],
    mut incoming: ItemStack,
    max: u32,
) -> Option<ItemStack> {
    for existing in slots.iter_mut().flatten() {
        let (mut a, mut b) = (existing.clone(), incoming.clone());
        a.count = 1;
        b.count = 1;
        if a == b {
            let moved = incoming.count.min(max.saturating_sub(existing.count));
            existing.count += moved;
            incoming.count -= moved;
            if incoming.count == 0 {
                return None;
            }
        }
    }
    for slot in slots.iter_mut().filter(|s| s.is_none()) {
        let mut part = incoming.clone();
        part.count = part.count.min(max);
        incoming.count -= part.count;
        *slot = Some(part);
        if incoming.count == 0 {
            return None;
        }
    }
    Some(incoming)
}

pub(super) fn process_depot(
    entity: &mut ModBlockEntity,
    item: &Transported<ItemStack>,
    update: ProcessingUpdate<ItemStack>,
) -> (bool, Vec<ItemStack>) {
    let locked = update.decision == ProcessingResult::Hold;
    if let Some(conversion) = update.conversion
        && !conversion.unchanged_from(&item.stack)
        && let TransportedResult::Convert { outputs, held } = conversion
    {
        let mut outputs = outputs.into_iter();
        if let Some(mut selected) = held.or_else(|| outputs.next()) {
            selected.position = 0.5;
            selected.previous_position = 0.5;
            selected.locked = locked;
            entity.items[0] = Some(belt::game_stack(&selected.stack));
            entity.nbt.insert("HeldItem".into(), belt::write_item(&selected));
        } else {
            entity.items[0] = None;
            entity.nbt.remove(&"HeldItem".into());
        }
        let overflow = outputs
            .filter_map(|output| {
                let stack = belt::game_stack(&output.stack);
                insert(&mut entity.items[1..], stack, output.stack.maximum)
            })
            .collect();
        super::create_port::depot_data(entity);
        return (true, overflow);
    }
    let Some(Tag::Compound(held)) = entity.nbt.get_mut(&"HeldItem".into()) else {
        return (false, Vec::new());
    };
    let was_locked = super::create_port::integer(held, "Locked") != 0;
    if locked != was_locked {
        if locked {
            held.insert("Locked".into(), Tag::Byte(1));
        } else {
            held.remove(&"Locked".into());
        }
    }
    (locked != was_locked, Vec::new())
}
