// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn contraption_sync(game: &mut crate::game::Game<'_>, data: &[u8]) {
    super::create_port_contraption_contact::sync(game, data);
}
