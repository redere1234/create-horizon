// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn motor_world_reset(game: &mut crate::game::Game<'_>) {
    crate::game::create_port_burner_sync::clear(game);
    crate::game::create_port_nativeaudio::unload(game);
    crate::game::create_port_motor_value_world::reset();
    crate::game::create_port_contraption::reset_render_motion();
    crate::game::create_port_contraption_contact::reset();
    crate::game::create_port_kinetic_runtime::reset();
    crate::game::create_port_basin::reset(false);
    crate::game::create_port_basin_recipes::reset(false);
    crate::game::create_port_press_basin::reset(false);
    crate::game::create_port_mixer::reset(false);
    crate::game::create_port_press_client::reset();
    crate::game::create_port_burner_presentation::reset();
}
