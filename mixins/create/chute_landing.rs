// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_chute_landing(
    game: &mut crate::game::Game<'_>,
    client: bool,
    pos: [i32; 3],
    item_pos: [f64; 3],
    stack: &mut crate::items::ItemStack,
    discard: &mut bool,
) {
    let inlet = [
        item_pos[0].floor() as i32,
        (item_pos[1] + 0.5).floor() as i32 - 1,
        item_pos[2].floor() as i32,
    ];
    if !client
        && !*discard
        && inlet == pos
        && crate::game::create_port_chute::landed(game, inlet, stack)
    {
        *discard = stack.count == 0;
    }
}
