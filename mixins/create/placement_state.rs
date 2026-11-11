// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_placement_state(
    game: &crate::game::GameLevel<'_>,
    state: horizon_world::registry::BlockStateId,
    context: &horizon_world::level::PlacementContext,
    fluid: horizon_world::fluid::FluidState,
    answer: &mut Option<Option<horizon_world::registry::BlockStateId>>,
) {
    crate::game::create_port_placement::state(game, state, context, fluid, answer);
}
