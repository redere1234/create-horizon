// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_pull_portable_storage(
    game: &mut crate::game::Game<'_>,
    pos: (i32, i32, i32),
) -> std::ops::ControlFlow<bool> {
    crate::game::create_port_portable_storage::hopper_suck(game, [pos.0, pos.1, pos.2])
}
