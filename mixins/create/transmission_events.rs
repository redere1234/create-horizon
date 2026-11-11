// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn transmission_events(game: &mut crate::game::Game<'_>) {
    crate::game::create_port_kinetic_runtime::refresh_transmissions(game);
    crate::game::create_port_sticker::refresh(game);
}
