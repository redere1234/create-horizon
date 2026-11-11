// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_on_draw(
    game: &crate::game::Game<'_>,
    pos: [i32; 3],
    block: &str,
    state: horizon_world::registry::BlockStateId,
    entity: &crate::containers::ModBlockEntity,
    draw: &mut crate::game::native_block_entity_draw::BlockEntityDraw,
) {
    crate::game::create_port::draw(game, pos, block, state, entity, draw);
}
