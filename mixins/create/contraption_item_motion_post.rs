// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn contraption_item_motion_post(game: &mut crate::game::Game<'_>) {
    crate::game::create_port_contraption_item_motion::tick_post(game);
}
