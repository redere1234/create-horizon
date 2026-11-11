// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use super::{BlockEntityRenderer, ChestPart, FULL_BRIGHT, Kind, extended_christmas};
use crate::{hud::HudAtlas, mesher::Vertex};
use glam::{Mat4, Vec3};

/// Draw the same closed single chest model that Horizon uses on a fixed block,
/// with the contraption's pose applied to its cached geometry.
pub fn closed(
    renderer: &BlockEntityRenderer,
    atlas: &HudAtlas,
    state: u32,
    nether: bool,
    pose: Mat4,
    light: u32,
    output: &mut Vec<Vertex>,
) -> bool {
    let Kind::Chest {
        block,
        texture,
        part: ChestPart::Single,
        y_rot,
        ..
    } = renderer.kind(state)
    else {
        return false;
    };
    if block != "chest" {
        return false;
    }
    let Ok(shapes) = renderer.shapes.read() else {
        return false;
    };
    let texture = shapes.texture(
        "chest",
        if extended_christmas() {
            "entity/chest/christmas"
        } else {
            texture
        },
        &atlas.sprites,
    );
    let Some(geometry) = shapes.closed_chests.get("chest") else {
        return false;
    };
    let Some(rect) = atlas.sprites.get(texture) else {
        return false;
    };
    let overlay = atlas
        .emissive
        .overlay(texture)
        .and_then(|name| atlas.sprites.get(name));
    let vertices = &geometry[usize::from(nether)][*y_rot as usize / 90];
    for (sprite, light) in std::iter::once((rect, light)).chain(overlay.map(|r| (r, FULL_BRIGHT))) {
        output.extend(vertices.iter().map(|vertex| {
            Vertex {
                pos: pose
                    .transform_point3(Vec3::from_array(vertex.pos))
                    .to_array(),
                uv: [
                    sprite.u0 + (sprite.u1 - sprite.u0) * vertex.uv[0],
                    sprite.v0 + (sprite.v1 - sprite.v0) * vertex.uv[1],
                ],
                light,
                ..*vertex
            }
        }));
    }
    true
}
