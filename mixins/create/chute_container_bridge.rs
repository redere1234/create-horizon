// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use super::{Game, Kind, Pos, View};
use horizon_client::items::ItemStack;
use horizon_core::geometry::Direction;

fn ordinary(view: &View, pos: Pos) -> bool {
    !matches!(view.kind, Kind::Composter(_) | Kind::Mod | Kind::Jukebox)
        && view
            .parts
            .iter()
            .all(|&((x, _, z), _)| (x >> 4, z >> 4) == (pos.0 >> 4, pos.2 >> 4))
}

impl Game<'_> {
    pub(in crate::game) fn chute_source_available(&self, pos: Pos) -> bool {
        self.containers()
            .view(pos, false)
            .is_some_and(|view| ordinary(&view, pos))
    }

    /// ItemHandlerHelper.insertItemStacked tries occupied matching slots before
    /// empties. Use Horizon's ordinary container predicates and writes.
    pub(in crate::game) fn chute_insert(
        &mut self,
        pos: Pos,
        stack: &ItemStack,
        simulate: bool,
    ) -> Option<u32> {
        let containers = self.containers();
        let view = containers.view(pos, false)?;
        if !ordinary(&view, pos) {
            return Some(0);
        }
        let max = containers.max_stack(stack);
        let mut matching = Vec::new();
        let mut empty = Vec::new();
        for slot in view.slots_to_add(Some(Direction::Up)) {
            if !containers.can_place(&view, slot, stack) {
                continue;
            }
            match containers.get(&view, slot) {
                Some(current) if current.count > 0 => {
                    if current.count < max && current.same_item_same_components(stack) {
                        matching.push((slot, max - current.count));
                    }
                }
                _ => empty.push((slot, max)),
            }
        }
        let mut moved = 0;
        for (slot, room) in matching.into_iter().chain(empty) {
            let count = (stack.count - moved).min(room);
            if count == 0 {
                break;
            }
            if simulate {
                moved += count;
            } else {
                let portion = ItemStack {
                    count,
                    ..stack.clone()
                };
                let (rest, _) =
                    self.move_in_item(None, &view, portion, slot, Some(Direction::Up));
                moved += count - rest.map_or(0, |stack| stack.count);
            }
        }
        if moved != 0 && !simulate {
            self.view_changed(&view);
        }
        Some(moved)
    }
}
