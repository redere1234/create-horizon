// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_use_on(
    game: &mut crate::game::Game<'_>,
    stack: &crate::items::ItemStack,
    pos: [i32; 3],
    face: [i32; 3],
    claimed: &mut bool,
) {
    if crate::game::create_port_super_glue::cancels_placement(game, stack) {
        game.use_failed = true;
        *claimed = true;
        return;
    }
    crate::game::create_port::use_on(game, stack, pos, face);
    if crate::game::create_port_placement::alias(game, stack, pos, face) {
        *claimed = true;
    }
}
