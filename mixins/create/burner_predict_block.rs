// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_burner_predict_block(
    game: &mut crate::game::Game<'_>,
    hand: crate::game::Hand,
) -> std::ops::ControlFlow<bool> {
    if game.create_burner_predict_block(hand) {
        std::ops::ControlFlow::Break(true)
    } else {
        std::ops::ControlFlow::Continue(())
    }
}
