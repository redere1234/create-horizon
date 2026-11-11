// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn super_glue_player_tick(game: &mut crate::game::Game<'_>) {
    crate::game::create_port_super_glue::player_tick(game);
}
