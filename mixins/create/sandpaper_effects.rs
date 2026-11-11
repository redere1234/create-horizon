// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn sandpaper_effects(
    game: &mut crate::game::Game<'_>,
    stack: &crate::items::ItemStack,
    remaining: i32,
) {
    crate::game::create_port_sandpaper::effects(game, stack, remaining);
}
