// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_fluid_shape(
    game: &crate::game::GameLevel<'_>,
    pos: horizon_core::position::BlockPos,
    state: horizon_world::registry::BlockStateId,
    direction: horizon_core::geometry::Direction,
    neighbour: horizon_world::registry::BlockStateId,
    new: &mut Option<horizon_world::registry::BlockStateId>,
) {
    let direction = match direction {
        horizon_core::geometry::Direction::Down => create_engine::placement::Direction::Down,
        horizon_core::geometry::Direction::Up => create_engine::placement::Direction::Up,
        horizon_core::geometry::Direction::North => create_engine::placement::Direction::North,
        horizon_core::geometry::Direction::South => create_engine::placement::Direction::South,
        horizon_core::geometry::Direction::West => create_engine::placement::Direction::West,
        horizon_core::geometry::Direction::East => create_engine::placement::Direction::East,
    };
    crate::game::create_port_basin::tank::shape(game, state, direction, neighbour, new);
    crate::game::create_port_basin::pump::shape(game, [pos.x, pos.y, pos.z], state, direction, neighbour, new);
}
