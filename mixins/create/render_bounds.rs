// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_render_bounds(
    game: &crate::game::Game<'_>,
    pos: [i32; 3],
    block: &str,
    entity: &crate::containers::ModBlockEntity,
    bounds: &mut [f32; 6],
) {
    crate::game::create_port_belt::render_bounds(game, pos, entity, bounds);
    crate::game::create_port_mixer::bounds(entity, bounds);
    if block == "create:large_water_wheel" {
        *bounds = [-2.0, -2.0, -2.0, 3.0, 3.0, 3.0];
    }
}
