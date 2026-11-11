// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn sandpaper_finish(
    game: &mut crate::game::Game<'_>,
    stack: &crate::items::ItemStack,
    hand: horizon_client::first_person::Hand,
    result: &mut Option<crate::items::ItemStack>,
) {
    crate::game::create_port_sandpaper::finish(game, stack, hand, result);
}
