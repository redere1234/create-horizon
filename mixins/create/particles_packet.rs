// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_particles_packet(game: &mut crate::game::Game<'_>, channel: &str, data: &[u8]) {
    crate::game::create_port_burner_sync::from_server(game, channel, data);
    crate::game::create_port_particles::packet(game, channel, data);
    crate::game::create_port_super_glue::receive_face(game, channel, data);
}
