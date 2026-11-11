// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_on_entity(block: &str, entity: &mut Option<(String, horizon_world::nbt::Compound)>) {
    crate::game::create_port::entity(block, entity);
}
