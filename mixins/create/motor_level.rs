// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn motor_level(game: &mut crate::game::Game<'_>) {
    crate::game::create_port_motor_control::level_tick(game);
    crate::game::create_port_contraption::recover_orphans(game);
    crate::game::create_port_contraption_menu::tick(game);
    crate::game::create_port_gantry::maintenance(game);
    crate::game::create_port_belt::maintenance(game);
    crate::game::create_port_basin::maintenance(game);
    crate::game::create_port_mixer::maintenance(game);
    crate::game::create_port_press_basin::maintenance(game);
    crate::game::create_port_instruments::flush(game);
    crate::game::create_port_millstone::refresh_recipes(game);
    crate::game::create_port_fan::maintenance(game);
    crate::game::create_port_drill::maintenance(game);
}
