// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

// Pinned raw tick_lan boundary: normal networking serializes changed BEs here.
fn create_belt_processing_flush(game: &mut crate::game::Game<'_>) {
    crate::game::create_port_belt::flush_processing(game);
}
