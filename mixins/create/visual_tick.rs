// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_visual_tick(game: &mut crate::game::Game<'_>) {
    if game.native_window() && game.native_on("create") {
        // The server's vanilla item_slime packets use this sprite cache.
        game.ensure_item_particle_sprites();
        crate::game::create_port_sticker::client_tick(game);
    }
    crate::game::create_port_burner_sync::tick(game);
    crate::game::create_port_nativeaudio::begin_tick(game);
    crate::game::create_port_fan::client_tick(game);
    crate::game::create_port_presentation::tick(game);
    crate::game::create_port_belt::connector_preview(game);
    crate::game::create_port_burner_presentation::client_tick(game);
    crate::game::create_port_millstone::client_tick(game);
    crate::game::create_port_basin::client_tick(game);
    crate::game::create_port_mixer::client_tick(game);
    crate::game::create_port_nativeaudio::end_tick(game);
}
