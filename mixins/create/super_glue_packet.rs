// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn super_glue_packet(game: &mut crate::game::Game<'_>, player: u128, channel: &str, data: &[u8]) {
    crate::game::create_port_super_glue::receive_attack(game, player, channel, data);
}
