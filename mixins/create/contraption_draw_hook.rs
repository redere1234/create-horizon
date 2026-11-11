// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn contraption_draw(
    game: &crate::game::Game<'_>,
    draw: &mut crate::game::native_world_draw::NativeWorldDraw,
) {
    super::create_port_contraption::draw_structures(game, draw);
}
