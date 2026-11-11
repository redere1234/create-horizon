// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn burner_stateful(block: &str, stateful: &mut bool) {
    crate::game::create_port_burner::stateful(block, stateful);
}
