// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

// Level.tickBlockEntities: before the particle engine admits this tick's new effects.
fn create_burner_particle_tick(game: &mut crate::game::Game<'_>) {
    crate::game::create_port_press_client::tick(game);
    crate::game::create_port_burner_presentation::client_particles(game);
}
