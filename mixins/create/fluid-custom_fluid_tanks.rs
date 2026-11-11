// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_custom_fluid_tanks(game: &crate::game::Game<'_>, pos: [i32; 3], side: Option<horizon_core::geometry::Direction>, out: &mut Option<Vec<crate::mod_api::NativeFluidTankView>>) {
    crate::game::create_port_basin::fluid_tanks(game, pos, side, out);
}
