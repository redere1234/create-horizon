// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn contraption_collision(game: &crate::game::Game<'_>, mut result: Vec<Aabb>) -> Vec<Aabb> {
    let (excluded_controller, exclude_upright) =
        super::create_port_contraption_item_motion::collision_filter();
    horizon_client_render::create_contraption_scene::append_collisions(
        &game.world,
        game.collision,
        &mut result,
        excluded_controller,
        None,
        exclude_upright,
    );
    result
}
