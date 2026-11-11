// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn motor_hud(game: &mut crate::game::Game<'_>, batch: &mut horizon_client::hud::HudBatch) {
    crate::game::create_port_motor_value_ui::hud(game, batch);
    crate::game::create_port_presentation::hud(game, batch);
}
