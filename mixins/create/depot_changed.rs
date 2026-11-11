// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

// A successful automation transfer ending the exposed stack destroys its
// transported identity immediately, even if another hopper refills this tick.
fn create_depot_changed(game: &mut crate::game::Game<'_>, pos: (i32, i32, i32)) {
    crate::game::create_port_chute::external_change(game, pos);
    // Successful native/automation slot mutations reach this callback. Basin
    // only raises its contents flag; its next BE tick schedules the operator.
    crate::game::create_port_basin::notify_contents(game, [pos.0, pos.1, pos.2]);
    let cleared = if let Some(crate::containers::BlockEntity::Mod(entity)) =
        game.world.block_entities.get_mut(&pos)
        && entity.id == "create:depot"
        && entity.items.first().is_none_or(Option::is_none)
    {
        entity.nbt.remove(&"HeldItem".into()).is_some()
    } else {
        false
    };
    if cleared {
        // The following machine tick already sees no HeldItem, so it cannot
        // discover this transition again. Publish the explicit empty update
        // now, including when another hopper refills the slot this tick.
        game.native_block_entity_sync([pos.0, pos.1, pos.2]);
    }
}
