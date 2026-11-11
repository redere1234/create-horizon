// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_super_glue_prediction(
    result: Option<DryPlace>,
    game: &crate::game::Game<'_>,
    stack: &crate::items::ItemStack,
) -> Option<DryPlace> {
    result.filter(|(pos, _)| {
        !crate::game::create_port_super_glue::cancel_prediction(game, stack, [pos.x, pos.y, pos.z])
    })
}
