// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn transmission_neighbor(
    level: &crate::game::GameLevel<'_>,
    dimension: horizon_world::level::Dimension,
    pos: horizon_core::position::BlockPos,
    state: horizon_world::registry::BlockStateId,
) {
    use crate::game::create_port_kinetic_runtime::{transmission_block, transmission_changed};
    use crate::game::create_port_sticker as sticker;
    let Some(block) = level.native_state_block(state) else {
        return;
    };
    let id = match dimension {
        horizon_world::level::Dimension::Overworld => "minecraft:overworld",
        horizon_world::level::Dimension::Nether => "minecraft:the_nether",
        horizon_world::level::Dimension::End => "minecraft:the_end",
    };
    let pos = [pos.x, pos.y, pos.z];
    if block == sticker::BLOCK {
        sticker::changed(id, pos);
    } else if transmission_block(block) {
        transmission_changed(id, pos);
    }
}
