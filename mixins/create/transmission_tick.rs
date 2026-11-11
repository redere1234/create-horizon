// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn transmission_tick(game: &mut crate::game::Game<'_>) {
    crate::game::create_port_kinetic_runtime::begin_transmission_tick(game);
}
