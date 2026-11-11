// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn sandpaper_animation(
    game: &crate::game::Game<'_>,
    stack: &crate::items::ItemStack,
    animation: &mut horizon_world::consumable::UseAnimation,
) {
    crate::game::create_port_sandpaper::animation(game, stack, animation);
}
