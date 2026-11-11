// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_custom_fluid_drain(game: &mut crate::game::Game<'_>, pos: [i32; 3], side: Option<horizon_core::geometry::Direction>, request: &crate::mod_api::NativeFluidDrain, action: crate::mod_api::NativeFluidAction, out: &mut Option<crate::mod_api::NativeFluidStack>) {
    crate::game::create_port_basin::fluid_drain(game, pos, side, request, action, out);
}
