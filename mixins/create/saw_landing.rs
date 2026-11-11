// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_saw_landing(
    game: &mut crate::game::Game<'_>,
    client: bool,
    pos: [i32; 3],
    item_pos: [f64; 3],
    stack: &mut crate::items::ItemStack,
    discard: &mut bool,
) {
    if !client
        && !*discard
        && item_pos.map(|v| v.floor() as i32) == pos
        && crate::game::create_port_saw_processing::landed(game, pos, stack)
    {
        *discard = stack.count == 0;
    }
}
