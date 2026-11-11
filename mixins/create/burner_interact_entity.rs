// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

// ItemStack.interactLivingEntity is reached only after the mob interaction
// passes. Create returns FAIL here: end the hand turn without swinging.
fn create_burner_interact_entity(
    game: &mut crate::game::Game<'_>,
    entity: i32,
    kind: &str,
    swing: &mut Option<bool>,
) {
    if swing.is_none()
        && crate::game::create_port_burner_interactions::interact_entity(game, entity, kind)
    {
        *swing = Some(false);
    }
}
