// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn super_glue_attack_input(
    game: &mut crate::game::Game<'_>,
    button: i32,
    swing: &mut bool,
    canceled: &mut bool,
) {
    if crate::game::create_port_super_glue::attack_input(game, button) {
        *swing = false;
        *canceled = true;
    }
}
