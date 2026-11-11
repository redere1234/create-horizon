// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn motor_scroll(
    game: &crate::game::Game<'_>,
    screen: &crate::mod_api::NativeScreenView<'_>,
    scroll: [f64; 2],
    modifiers: u32,
    canceled: &mut bool,
) {
    crate::game::create_port_motor_value_ui::scroll(game, screen, scroll, modifiers, canceled);
}
