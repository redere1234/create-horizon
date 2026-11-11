// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_gauge_has_analog(
    game: &crate::game::GameLevel<'_>,
    state: horizon_world::registry::BlockStateId,
    output: &mut bool,
) {
    crate::game::create_port_basin::has_analog(game, state, output);
    if matches!(
        game.native_state_block(state),
        Some(
            crate::game::create_port_burner::BLOCK
                | crate::game::create_port_portable_storage::BLOCK
        )
    ) {
        *output = true;
    }
    if matches!(
        game.facts.get(state).name.as_ref(),
        "create:speedometer" | "create:stressometer"
    ) {
        *output = true;
    }
}
