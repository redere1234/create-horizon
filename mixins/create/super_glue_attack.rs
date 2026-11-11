// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn super_glue_attack(game: &mut crate::game::Game<'_>, canceled: &mut bool) {
    if crate::game::create_port_super_glue::left_click(game) {
        *canceled = true;
    }
}
