// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_placed(game: &mut crate::game::Game<'_>, stack: &crate::items::ItemStack, pos: [i32; 3]) {
    if game.native_on("create") && stack.item.as_ref() == crate::game::create_port_deployer::BLOCK {
        crate::game::create_port_deployer::placed(game, pos);
    }
    if game.native_on("create") && crate::game::create_port_chassis::is_chassis(&stack.item) {
        crate::game::create_port_chassis::placed(game, pos);
    }
    if game.native_on("create") && stack.item.as_ref() == crate::game::create_port_sticker::BLOCK {
        crate::game::create_port_sticker::placed(game, pos);
    }
    crate::game::create_port::placed(game, stack, pos);
    crate::game::create_port_super_glue::placed(game, stack, pos);
    if game.native_on("create") && crate::game::create_port::node(game, pos).is_some() {
        crate::game::create_port_particles::queue_rotation(game, pos);
    }
}
