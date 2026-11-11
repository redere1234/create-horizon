// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn motor_world(
    game: &crate::game::Game<'_>,
    draw: &mut crate::game::native_world_draw::NativeWorldDraw,
) {
    crate::game::create_port_motor_value_world::render(game, draw);
}
