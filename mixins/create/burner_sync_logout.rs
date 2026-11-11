// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_burner_sync_logout(game: &crate::game::Game<'_>, player: u128) {
    crate::game::create_port_burner_sync::logged_out(game, player);
}
