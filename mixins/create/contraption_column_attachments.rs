// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

pub(super) fn copy_scene(world: &crate::world::World, chunk: &mut crate::chunk::Chunk) {
    use crate::create_contraption_scene::{ACTOR_VISUAL_KEY, KEY, POSE_KEY, RECORDS};
    use horizon_world::attachments::create_contraption_attachment::copy_entry;

    let Some(saved) = world
        .chunks
        .get(&(chunk.x, chunk.z))
        .and_then(|old| old.saved.as_ref())
    else {
        return;
    };
    if !saved.attachments.has(&RECORDS) {
        return;
    }
    // A bulk resend replaces the resident column without another attachment
    // snapshot. Keep its moving scene until the separate attachment delta.
    let incoming = std::sync::Arc::make_mut(chunk.saved.get_or_insert_with(Default::default));
    copy_entry(&saved.attachments, &mut incoming.attachments, "create", KEY);
    copy_entry(
        &saved.attachments,
        &mut incoming.attachments,
        "create",
        POSE_KEY,
    );
    copy_entry(
        &saved.attachments,
        &mut incoming.attachments,
        "create",
        ACTOR_VISUAL_KEY,
    );
}
