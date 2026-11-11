// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_crank_shape(
    game: &crate::game::GameLevel<'_>,
    ticks: &mut horizon_world::level::Ticks,
    pos: horizon_core::position::BlockPos,
    state: horizon_world::registry::BlockStateId,
    direction: horizon_core::geometry::Direction,
    neighbour_pos: horizon_core::position::BlockPos,
    new: &mut Option<horizon_world::registry::BlockStateId>,
) {
    crate::game::create_port_placement::crank_update_shape(
        game, ticks, pos, state, direction, neighbour_pos, new,
    );
}
