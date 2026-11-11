// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn replace_unlit_column(
    streaming: &mut Streaming,
    world: &mut crate::world::World,
    mut chunk: crate::chunk::Chunk,
    original: impl FnOnce(&mut Streaming, &mut crate::world::World, crate::chunk::Chunk) -> (),
) {
    crate::streaming::create_contraption_column_attachments::copy_scene(world, &mut chunk);
    original(streaming, world, chunk);
}
