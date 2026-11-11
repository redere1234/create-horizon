// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_burner_hand_operated(name: &str) -> std::ops::ControlFlow<bool> {
    if crate::game::create_port_burner_interactions::hand_operated(name) {
        std::ops::ControlFlow::Break(true)
    } else {
        std::ops::ControlFlow::Continue(())
    }
}
