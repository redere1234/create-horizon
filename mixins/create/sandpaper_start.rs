// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn sandpaper_start(
    game: &mut crate::game::Game<'_>,
    stack: &crate::items::ItemStack,
    hand: horizon_client::first_person::Hand,
    duration: &i32,
    canceled: &mut bool,
    _value: (),
) {
    crate::game::create_port_sandpaper::start(game, stack, hand, *duration, canceled);
}
