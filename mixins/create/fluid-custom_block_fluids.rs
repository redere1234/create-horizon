// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_custom_block_fluids(block: &str, custom: &mut bool) {
    crate::game::create_port_basin::custom_fluids(block, custom);
}
