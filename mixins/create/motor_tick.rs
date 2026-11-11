// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn motor_tick(game: &mut crate::game::Game<'_>) {
    crate::game::create_port_contraption_contact::finish_tick(game);
    crate::game::create_port_motor_value_world::tick(game);
    crate::game::create_port_motor_value_ui::tick(game);
}
