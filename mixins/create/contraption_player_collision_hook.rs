// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn contraption_player_collision(game: &crate::game::Game<'_>, mut result: Vec<Aabb>) -> Vec<Aabb> {
    let (excluded, standing) =
        crate::game::create_port_contraption_contact::player_collision_filter(game);
    horizon_client_render::create_contraption_scene::append_collisions(
        &game.world,
        game.collision,
        &mut result,
        excluded,
        standing,
        false,
    );
    result
}
