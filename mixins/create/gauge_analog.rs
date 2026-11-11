// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_gauge_analog(
    game: &crate::game::GameLevel<'_>,
    pos: horizon_core::position::BlockPos,
    state: horizon_world::registry::BlockStateId,
    output: &mut i32,
) {
    crate::game::create_port_basin::analog(game, pos, state, output);
    crate::game::create_port_burner::analog(game, state, output);
    crate::game::create_port_portable_storage::analog(game, pos, state, output);
    if matches!(
        game.facts.get(state).name.as_ref(),
        "create:speedometer" | "create:stressometer"
    ) {
        *output = match game.world.block_entities.get(&(pos.x, pos.y, pos.z)) {
            Some(crate::containers::BlockEntity::Mod(e)) => {
                i32::from(create_engine::visual::comparator(
                    crate::game::create_port::number(&e.nbt, "Value"),
                ))
            }
            _ => 0,
        };
    }
}
