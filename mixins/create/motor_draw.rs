// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn motor_draw(
    game: &crate::game::Game<'_>,
    batch: &mut horizon_client::hud::HudBatch,
    screen: &crate::mod_api::NativeScreenView<'_>,
) {
    crate::game::create_port_motor_value_ui::draw(game, batch, screen);
}
