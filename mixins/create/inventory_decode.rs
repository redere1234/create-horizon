// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

// Shared canonical load boundary, also used by client block-entity receipt.
fn create_inventory_decode(
    id: &str,
    tag: &horizon_world::nbt::Tag,
) -> std::ops::ControlFlow<Option<crate::containers::ModBlockEntity>> {
    create_inventory_codec::decode(id, tag)
}
