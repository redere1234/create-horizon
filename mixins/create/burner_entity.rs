// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn burner_entity(
    block: &str,
    entity: &mut Option<(String, horizon_world::nbt::Compound)>,
) {
    crate::game::create_port_burner::entity(block, entity);
}
