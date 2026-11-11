// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn sandpaper_sync(game: &crate::game::Game<'_>, recipe_types: &mut Vec<String>) {
    if game.native_on("create") {
        recipe_types.push(crate::game::create_port_sandpaper::RECIPE.into());
    }
}
