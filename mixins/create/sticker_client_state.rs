// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn sticker_client_state(
    game: &crate::game::Game<'_>,
    pos: (i32, i32, i32),
    previous: Option<horizon_world::registry::BlockStateId>,
    state: horizon_world::registry::BlockStateId,
) {
    crate::game::create_port_sticker::client_changed(game, [pos.0, pos.1, pos.2], previous, state);
}
