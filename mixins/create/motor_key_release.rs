// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn motor_key_release(
    game: &crate::game::Game<'_>,
    screen: &crate::mod_api::NativeScreenView<'_>,
    key: &str,
    canceled: &mut bool,
) {
    crate::game::create_port_motor_value_ui::key_release(game, screen, key, canceled);
}
