// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn sandpaper_duration(
    game: &crate::game::Game<'_>,
    stack: &crate::items::ItemStack,
    duration: &mut i32,
) {
    crate::game::create_port_sandpaper::duration(game, stack, duration);
}
