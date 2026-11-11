// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn motor_packet(game: &mut crate::game::Game<'_>, player: u128, channel: &str, data: &[u8]) {
    crate::game::create_port_contraption_menu::receive(game, player, channel, data);
    crate::game::create_port_burner_sync::from_client(game, player, channel, data);
    crate::game::create_port_motor_control::receive(game, player, channel, data);
}
