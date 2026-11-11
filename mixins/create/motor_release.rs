// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn motor_release(
    game: &crate::game::Game<'_>,
    screen: &crate::mod_api::NativeScreenView<'_>,
    button: i32,
    canceled: &mut bool,
) {
    crate::game::create_port_motor_value_ui::mouse_release(game, screen, button, canceled);
}
