// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_destroy(game: &mut crate::game::Game<'_>, pos: [i32; 3], canceled: &mut bool) {
    if crate::game::create_port::inventory_blocked(game, pos) {
        *canceled = true;
        return;
    }
    if game.native_block(pos) == "create:basin" {
        crate::game::create_port_basin::removed(game, pos);
    }
    crate::game::create_port_belt::destroy(game, pos);
    crate::game::create_port_placement::destroy(game, pos, canceled);
}
