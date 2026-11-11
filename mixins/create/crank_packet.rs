// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

// API 359 has no client block-entity tag receipt hook. This narrow raw adapter
// is pinned to Game::remote_block_entity_data's type/block/tag validation.
fn create_crank_packet(
    game: &mut crate::game::Game<'_>,
    pos: [i32; 3],
    kind: i32,
    tag: &horizon_world::nbt::Tag,
) {
    crate::game::create_port_press_client::packet(game, pos, kind, tag);
    crate::game::create_port_inventory_packet::packet(game, pos, kind, tag);
    crate::game::create_port_burner::packet(game, pos, kind, tag);
    crate::game::create_port_nativeaudio::crank_packet(game, pos, kind, tag);
}
