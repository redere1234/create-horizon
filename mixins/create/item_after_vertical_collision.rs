// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

// Pinned pending native fragment: the actual active stack is owned by the
// movement caller. Setting discard removes that entity without undoing collision.
fn create_item_after_vertical_collision(
    game: &mut crate::game::Game<'_>,
    dimension: &str,
    client: bool,
    state: horizon_world::registry::BlockStateId,
    item_pos: [f64; 3],
    stack: &mut crate::items::ItemStack,
    discard: &mut bool,
) {
    crate::game::create_port_item_contact::after_vertical_collision(
        game, dimension, client, state, item_pos, stack, discard,
    );
}
