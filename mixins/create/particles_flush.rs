// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_particles_flush(game: &mut crate::game::Game<'_>, dimension: &str) {
    crate::game::create_port_particles::flush(game, dimension);
}
