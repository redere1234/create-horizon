// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_contraption_chunk(world: &crate::world::World, chunk: &mut crate::chunk::Chunk) {
    crate::streaming::create_contraption_column_attachments::copy_scene(world, chunk);
}
