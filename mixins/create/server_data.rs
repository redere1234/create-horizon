// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_server_data(game: &mut crate::game::Game<'_>, reload: bool) {
    crate::game::create_port_burner_sync::data_loaded(game, reload);
    crate::game::create_port_belt::reset(reload);
    crate::game::create_port_basin::reset(reload);
    crate::game::create_port_basin_recipes::reset(reload);
    crate::game::create_port_press_basin::reset(reload);
    crate::game::create_port_mixer::reset(reload);
    crate::game::create_port_burner_presentation::reset();
    crate::game::create_port_particles::reset();
    crate::game::create_port_motor_control::reset();
    crate::game::create_port_fan::reset(reload);
    crate::game::create_port_drill::reset(reload);
    crate::game::create_port_millstone::invalidate_recipes();
    crate::game::create_port_millstone::refresh_recipes(game);
}
