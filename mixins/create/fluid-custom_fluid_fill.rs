// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_custom_fluid_fill(game: &mut crate::game::Game<'_>, pos: [i32; 3], side: Option<horizon_core::geometry::Direction>, resource: &crate::mod_api::NativeFluidStack, action: crate::mod_api::NativeFluidAction, out: &mut Option<i32>) {
    crate::game::create_port_basin::fluid_fill(game, pos, side, resource, action, out);
}
