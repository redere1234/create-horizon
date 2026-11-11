// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn contraption_menu_close(game: &mut crate::game::Game<'_>, player: u128, window: i32) {
    crate::game::create_port_contraption_menu::closed(game, player, window);
}
