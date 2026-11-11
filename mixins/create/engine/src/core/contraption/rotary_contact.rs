// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! Single-axis bearings in Create's `ContinuousOBBCollider`.
use super::contact::ContactBox;
use crate::{
    kinetics::{Axis, Pos},
    source_trig::{cos, sin},
};

const BODY_INFLATION: f64 = 1.0e-7;
const SEPARATION_EPSILON: f64 = 1.0e-4;
const Y: usize = 1;
const AXES: [[f64; 3]; 3] = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]];

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct RotaryContact {
    pub separation: [f64; 3],
    pub impact_fraction: f64,
    pub surface: bool,
}

fn dot(left: [f64; 3], right: [f64; 3]) -> f64 {
    left[0] * right[0] + left[1] * right[1] + left[2] * right[2]
}

fn projected_extent(axis: [f64; 3], extent: [f64; 3]) -> f64 {
    dot(axis.map(f64::abs), extent)
}

fn signed_epsilon(depth: f64) -> f64 {
    if depth == 0.0 {
        depth
    } else {
        depth + SEPARATION_EPSILON.copysign(depth)
    }
}

struct AxisTest {
    direction: [f64; 3],
    offset: f64,
    combined_extent: f64,
    velocity: f64,
}

fn box_response(
    axes: impl IntoIterator<Item = AxisTest>,
    up: [f64; 3],
    max_step: f32,
) -> Option<([f64; 3], f64)> {
    let mut minimum = (f64::MAX, [0.0; 3]);
    let mut step = f64::MAX;
    let mut entry = -1.0f64;
    let mut exit = f64::MAX;
    for axis in axes {
        let distance = axis.offset.abs();
        let gap = distance - axis.combined_extent;
        if gap > 0.0 {
            if axis.velocity * axis.offset >= 0.0 || gap > axis.velocity.abs() {
                return None;
            }
            entry = entry.max(gap / axis.velocity.abs());
            exit = exit.min((gap + axis.combined_extent) / axis.velocity.abs());
        } else {
            let projected_up = dot(axis.direction, up);
            if projected_up != 0.0 {
                let lift = (axis.combined_extent - axis.offset * projected_up.signum())
                    / projected_up.abs();
                step = step.min(lift);
            }
        }
        // A centered axis has no separating sign. Original later axes win ties.
        if distance != 0.0 && -gap <= minimum.0.abs() {
            minimum = (gap.abs().copysign(axis.offset), axis.direction);
        }
    }
    let mut separation = [0.0; 3];
    if entry == -1.0 {
        separation = if step <= f64::from(max_step) {
            up.map(|n| n * signed_epsilon(step))
        } else {
            minimum.1.map(|n| n * signed_epsilon(minimum.0))
        };
    }
    // Java keeps a vertical-pass surface candidate even when the swept
    // intervals miss in time. Only a discrete or in-tick hit changes motion.
    let impact = if entry > 0.0 && entry <= exit && entry < 1.0 {
        entry
    } else {
        1.0
    };
    Some((separation, impact))
}

/// Resolve the local player's body against payload collision boxes. The source
/// uses only its vertical pass for a bearing rotating around X or Z.
pub fn rotary_contact(
    axis: Axis,
    anchor: Pos,
    angle: f32,
    body: ContactBox,
    velocity: [f64; 3],
    shapes: impl IntoIterator<Item = ContactBox>,
    max_step: f32,
) -> RotaryContact {
    // AngleHelper.rad and Matrix3d are distinct from the rendered
    // transform. Preserve the 1.21.1 float table lookups used by the collider.
    let radians = (f64::from(-angle) / 180.0 * std::f64::consts::PI) as f32;
    let (sin, cos) = if radians == 0.0 {
        (0.0, 1.0)
    } else {
        (f64::from(sin(radians)), f64::from(cos(radians)))
    };
    let rows = match axis {
        Axis::X => [AXES[0], [0.0, cos, -sin], [0.0, sin, cos]],
        Axis::Y => [[cos, 0.0, sin], AXES[Y], [-sin, 0.0, cos]],
        Axis::Z => [[cos, -sin, 0.0], [sin, cos, 0.0], AXES[2]],
    };
    let columns: [[f64; 3]; 3] = std::array::from_fn(|i| rows.map(|row| row[i]));
    let directions = columns.map(|axis| {
        let length = dot(axis, axis).sqrt();
        axis.map(|v| v / length)
    });
    let center: [f64; 3] = std::array::from_fn(|i| (body.min[i] + body.max[i]) * 0.5);
    let relative = std::array::from_fn(|i| center[i] - f64::from(anchor[i]) - 0.5);
    let mut center = rows.map(|row| dot(row, relative) + 0.5);
    let mut extent = std::array::from_fn(|i| (body.max[i] - body.min[i]) * 0.5 + BODY_INFLATION);
    if body.max[Y] - body.min[Y] > 1.0 {
        // Java locates the body using its full center, then contracts the
        // local player's head by 2/16 before constructing the OBB.
        center[Y] -= 1.0 / 16.0;
        extent[Y] -= 1.0 / 16.0;
    }
    let rotated_extent = rows.map(|axis| projected_extent(axis, extent));
    let broad_extent: [f64; 3] =
        std::array::from_fn(|i| projected_extent(rows[i], [extent[i]; 3]) + 0.5);
    let motion = rows.map(|axis| dot(axis, velocity));
    let original_motion = columns.map(|axis| dot(axis, motion));
    let candidates: Vec<_> = shapes
        .into_iter()
        .filter_map(|shape| {
            let at: [f64; 3] = std::array::from_fn(|i| (shape.min[i] + shape.max[i]) * 0.5);
            let radius = std::array::from_fn(|i| (shape.max[i] - shape.min[i]) * 0.5);
            (0..3)
                .all(|i| (center[i] + motion[i] - at[i]).abs() <= broad_extent[i] + radius[i])
                .then_some((at, radius))
        })
        .collect();
    let mut separation = [0.0; 3];
    let mut impact_fraction = 1.0f64;
    let mut surface = false;
    for vertical_pass in [false, true] {
        if axis != Axis::Y && !vertical_pass {
            continue;
        }
        for (block, radius) in &candidates {
            let delta = std::array::from_fn::<_, 3, _>(|i| center[i] + separation[i] - block[i]);
            let delta_original = columns.map(|axis| dot(axis, delta));
            let local_axes = (0..3).map(|i| AxisTest {
                direction: AXES[i],
                offset: delta[i],
                combined_extent: radius[i] + rotated_extent[i],
                velocity: motion[i],
            });
            let entity_axes = (0..3).map(|i| AxisTest {
                direction: directions[i],
                offset: delta_original[i],
                combined_extent: projected_extent(columns[i], *radius) + extent[i],
                velocity: original_motion[i],
            });
            if let Some((response, impact)) =
                box_response(local_axes.chain(entity_axes), directions[Y], max_step)
            {
                for i in 0..3 {
                    separation[i] += response[i];
                }
                impact_fraction = impact_fraction.min(impact);
                surface |= vertical_pass;
            }
        }
        if vertical_pass || (separation[Y] == 0.0 && impact_fraction == 1.0) {
            break;
        }
        separation[0] *= 129.0 / 128.0;
        separation[2] *= 129.0 / 128.0;
    }
    RotaryContact {
        separation: columns.map(|axis| dot(axis, separation)),
        impact_fraction,
        surface,
    }
}
