// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn sandpaper_release(game: &mut crate::game::Game<'_>, stack: &crate::items::ItemStack) {
    crate::game::create_port_sandpaper::release(game, stack);
}
