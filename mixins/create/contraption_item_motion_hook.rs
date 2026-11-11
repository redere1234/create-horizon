// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn contraption_item_motion(
    game: &mut Game<'_>,
    round: &mut native_ticks::TickRound,
    original: impl FnOnce(&mut Game<'_>, &mut native_ticks::TickRound) -> (),
) {
    crate::game::create_port_contraption_item_motion::tick_items(game, round, original);
}
