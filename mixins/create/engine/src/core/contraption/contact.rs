// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use super::Rotation;
use crate::kinetics::{Axis, Pos};

const CONTACT_EPSILON: f64 = 1.0e-7;
const SEPARATION_EPSILON: f64 = 1.0e-4;

#[derive(Clone, Copy, Debug)]
pub struct ContactBox {
    pub min: [f64; 3],
    pub max: [f64; 3],
}

impl ContactBox {
    pub fn cube(min: [f64; 3]) -> Self {
        Self {
            min,
            max: min.map(|value| value + 1.0),
        }
    }

    pub fn penetrates(self, other: Self) -> bool {
        (0..3).all(|i| {
            self.max[i].min(other.max[i]) - self.min[i].max(other.min[i]) > CONTACT_EPSILON
        })
    }
}

/// The discrete, axis-aligned branch of Java's ContinuousOBBCollider.
/// Evaluate every shape against the accumulated response, since clearing one
/// shape can intersect another part of the moving structure.
pub fn linear_overlap_response(
    body: ContactBox,
    shapes: &[ContactBox],
    max_step: f32,
) -> Option<[f64; 3]> {
    let min = body.min.map(|value| value - CONTACT_EPSILON);
    let max = body.max.map(|value| value + CONTACT_EPSILON);
    let radius: [f64; 3] = std::array::from_fn(|i| (max[i] - min[i]) * 0.5);
    let center: [f64; 3] = std::array::from_fn(|i| min[i] + radius[i]);
    let mut response = [0.0; 3];
    for pass in 0..2 {
        for shape in shapes {
            let offset: [f64; 3] = std::array::from_fn(|i| {
                center[i] + response[i] - (shape.min[i] + shape.max[i]) * 0.5
            });
            let combined: [f64; 3] =
                std::array::from_fn(|i| (shape.max[i] - shape.min[i]) * 0.5 + radius[i]);
            let depth: [f64; 3] = std::array::from_fn(|i| combined[i] - offset[i].abs());
            if depth.iter().any(|&depth| depth < 0.0) {
                continue;
            }
            let step = combined[1] - offset[1];
            if step <= f64::from(max_step) {
                if step > 0.0 {
                    response[1] += step + SEPARATION_EPSILON;
                }
                continue;
            }
            // Java tests X, Y and Z in this order and replaces equal minima.
            // A centered axis supplies no direction, so it cannot win the tie.
            let mut selected = None;
            for axis in 0..3 {
                if offset[axis] != 0.0 && selected.is_none_or(|other| depth[axis] <= depth[other]) {
                    selected = Some(axis);
                }
            }
            if let Some(axis) = selected
                && depth[axis] != 0.0
            {
                response[axis] += (depth[axis] + SEPARATION_EPSILON).copysign(offset[axis]);
            }
        }
        if pass == 1 || response[1] == 0.0 {
            break;
        }
        response[0] *= 129.0 / 128.0;
        response[2] *= 129.0 / 128.0;
    }
    response
        .iter()
        .any(|&component| component != 0.0)
        .then_some(response)
}

/// Contact from a grounded body on a translating collision box.
/// Rising tops supply lift, while gravity follows a receding surface.
pub fn linear_top_motion(
    previous_origin: [f64; 3],
    current_origin: [f64; 3],
    tops: impl IntoIterator<Item = ContactBox>,
    feet: [f64; 3],
    [half_x, half_z]: [f64; 2],
) -> Option<[f64; 3]> {
    let [x, y, z] = std::array::from_fn(|i| feet[i] - previous_origin[i]);
    let supported = tops.into_iter().any(|top| {
        (y - top.max[1]).abs() <= CONTACT_EPSILON
            && x + half_x > top.min[0]
            && x - half_x < top.max[0]
            && z + half_z > top.min[2]
            && z - half_z < top.max[2]
    });
    supported.then(|| {
        let [dx, dy, dz] = std::array::from_fn(|i| current_origin[i] - previous_origin[i]);
        [dx, dy.max(0.0), dz]
    })
}

/// Separation of an initially external body crossed by the leading face of
/// a translating full block. The host clips the resulting displacement.
pub fn linear_face_separation(
    previous: [f64; 3],
    current: [f64; 3],
    full_blocks: impl IntoIterator<Item = Pos>,
    body_min: [f64; 3],
    body_max: [f64; 3],
) -> Option<[f64; 3]> {
    let delta: [f64; 3] = std::array::from_fn(|i| current[i] - previous[i]);
    let axis = delta.iter().position(|&step| step != 0.0)?;
    if !delta[axis].is_finite()
        || delta
            .iter()
            .enumerate()
            .any(|(i, &step)| i != axis && step != 0.0)
    {
        return None;
    }
    let positive = delta[axis] > 0.0;
    let mut separation = 0.0f64;
    for block in full_blocks {
        let low: [f64; 3] = std::array::from_fn(|i| previous[i] + f64::from(block[i]));
        if (0..3)
            .filter(|&i| i != axis)
            .any(|i| low[i] + 1.0 <= body_min[i] || low[i] >= body_max[i])
        {
            continue;
        }
        let (gap, overlap) = if positive {
            let face = low[axis] + 1.0;
            (body_min[axis] - face, face + delta[axis] - body_min[axis])
        } else {
            let face = low[axis];
            (face - body_max[axis], body_max[axis] - (face + delta[axis]))
        };
        if gap >= -CONTACT_EPSILON && overlap > 0.0 {
            separation = separation.max(overlap);
        }
    }
    if separation == 0.0 {
        return None;
    }
    let mut response = [0.0; 3];
    response[axis] = (separation + CONTACT_EPSILON).copysign(delta[axis]);
    Some(response)
}

/// Horizontal contact displacement on the top of a Y-axis rotary contraption.
/// The host supplies a grounded body's feet center and horizontal half extents,
/// then clips the returned movement through the world collision resolver.
pub fn rotary_top_motion(
    anchor: Pos,
    [previous_angle, current_angle]: [f32; 2],
    tops: impl IntoIterator<Item = ContactBox>,
    feet: [f64; 3],
    [half_x, half_z]: [f64; 2],
) -> Option<[f64; 3]> {
    let previous = Rotation::new(anchor, Axis::Y, previous_angle)?;
    let current = Rotation::new(anchor, Axis::Y, current_angle)?;
    let local = previous.to_local(feet);
    let [cos, _, neg_sin] = previous.rotate_vector([1.0, 0.0, 0.0]);
    let (cos, sin) = (cos.abs(), neg_sin.abs());
    let player_local_x = cos * half_x + sin * half_z;
    let player_local_z = sin * half_x + cos * half_z;
    let supported = tops.into_iter().any(|top| {
        // ContraptionCollider inflates the entity's collision bounds by 1e-7.
        if (local[1] - top.max[1]).abs() > CONTACT_EPSILON {
            return false;
        }
        // Check both pairs of separating axes in the horizontal plane.
        let width = (top.max[0] - top.min[0]) * 0.5;
        let depth = (top.max[2] - top.min[2]) * 0.5;
        let x = local[0] - top.min[0] - width;
        let z = local[2] - top.min[2] - depth;
        if x.abs() >= width + player_local_x || z.abs() >= depth + player_local_z {
            return false;
        }
        let [x, _, z] = previous.rotate_vector([x, 0.0, z]);
        x.abs() < cos * width + sin * depth + half_x && z.abs() < sin * width + cos * depth + half_z
    });
    if !supported {
        return None;
    }

    // AbstractContraptionEntity.getContactPointMotion maps the previous local
    // point into the current transform. ContraptionCollider applies its X/Z
    // displacement after clipping it against the world's normal collision shapes.
    let next = current.to_world(local);
    Some([next[0] - feet[0], 0.0, next[2] - feet[2]])
}

#[cfg(test)]
mod tests {
    use super::*;

    fn assert_motion(actual: Option<[f64; 3]>, expected: [f64; 3]) {
        let actual = actual.expect("body must be supported");
        for (actual, expected) in actual.into_iter().zip(expected) {
            assert!(
                (actual - expected).abs() < 1.0e-12,
                "{actual} != {expected}"
            );
        }
    }

    #[test]
    fn a_leading_face_separates_bodies_on_both_sides() {
        let start = [0.0; 3];
        let east = linear_face_separation(
            start,
            [0.25, 0.0, 0.0],
            [[0; 3]],
            [1.125, 0.0, 0.2],
            [1.725, 1.675, 0.8],
        )
        .unwrap();
        let west = linear_face_separation(
            start,
            [-0.25, 0.0, 0.0],
            [[0; 3]],
            [-0.725, 0.0, 0.2],
            [-0.125, 1.675, 0.8],
        )
        .unwrap();
        assert_eq!(east, [0.125 + CONTACT_EPSILON, 0.0, 0.0]);
        assert_eq!(west, [-0.125 - CONTACT_EPSILON, 0.0, 0.0]);
        for (min, max) in [
            ([1.26, 0.0, 0.2], [1.86, 1.675, 0.8]),
            ([1.10, 1.0, 0.2], [1.70, 2.675, 0.8]),
            ([-0.5, 0.0, 0.2], [0.1, 1.675, 0.8]),
        ] {
            assert!(linear_face_separation(start, [0.25, 0.0, 0.0], [[0; 3]], min, max).is_none());
        }
    }

    #[test]
    fn overlap_response_uses_the_nearer_edge_of_a_narrow_piston_arm() {
        let arm = ContactBox {
            min: [0.0, 0.375, 0.375],
            max: [0.75, 0.625, 0.625],
        };
        for (z, side) in [(0.55, 1.0), (0.45, -1.0)] {
            let body = ContactBox {
                min: [0.3, 0.0, z - 0.3],
                max: [0.9, 1.675, z + 0.3],
            };
            assert_motion(
                linear_overlap_response(body, &[arm], 0.6),
                [0.0, 0.0, side * 0.3751001],
            );
        }
    }

    #[test]
    fn touching_a_platform_top_is_not_a_hard_overlap() {
        let platform = ContactBox {
            min: [0.0; 3],
            max: [1.0; 3],
        };
        let mut body = ContactBox {
            min: [0.2, 1.0, 0.2],
            max: [0.8, 2.675, 0.8],
        };
        assert!(!body.penetrates(platform));
        body.min[1] -= 0.01;
        assert!(body.penetrates(platform));
    }

    #[test]
    fn rider_moves_around_the_center_of_the_anchor_block() {
        let anchor = [10, 64, -3];
        assert_motion(
            rotary_top_motion(
                anchor,
                [0.0, 90.0],
                [ContactBox::cube([2.0, 0.0, 0.0])],
                [12.5, 65.0, -2.5],
                [0.3; 2],
            ),
            [-2.0, 0.0, -2.0],
        );
        assert_motion(
            rotary_top_motion(
                anchor,
                [0.0, 90.0],
                [ContactBox::cube([0.0; 3])],
                [10.5, 65.0, -2.5],
                [0.3; 2],
            ),
            [0.0; 3],
        );
    }

    #[test]
    fn rotation_wrap_keeps_contact_motion_continuous() {
        let (sin, cos) = 10_f64.to_radians().sin_cos();
        assert_motion(
            rotary_top_motion(
                [0; 3],
                [350.0, 10.0],
                [ContactBox::cube([2.0, 0.0, 0.0])],
                [0.5 + 2.0 * cos, 1.0, 0.5 + 2.0 * sin],
                [0.3; 2],
            ),
            [0.0, 0.0, -4.0 * sin],
        );
    }

    #[test]
    fn only_a_footprint_over_the_actual_top_is_supported() {
        let motion = |feet| {
            rotary_top_motion(
                [0; 3],
                [45.0, 55.0],
                [ContactBox::cube([0.0; 3])],
                feet,
                [0.025; 2],
            )
        };
        assert!(motion([0.68, 1.0, 0.68]).is_some());
        assert!(motion([1.10, 1.0, 1.10]).is_none());
        assert!(motion([0.68, 0.0, 0.68]).is_none());
        assert!(motion([0.68, 1.25, 0.68]).is_none());
        // A rider can stand with the center of their feet outside the block.
        assert!(
            rotary_top_motion(
                [0; 3],
                [0.0, 1.0],
                [ContactBox::cube([0.0; 3])],
                [1.25, 1.0, 0.5],
                [0.3; 2]
            )
            .is_some()
        );
    }

    #[test]
    fn rider_follows_horizontal_stroke_and_upward_lift() {
        let previous = [4.25, 16.0, -2.0];
        let feet = [4.45, 17.0, -1.5];
        let motion = |current| {
            linear_top_motion(
                previous,
                current,
                [ContactBox::cube([0.0; 3])],
                feet,
                [0.3; 2],
            )
        };
        assert_motion(motion([4.0, 16.0, -2.0]), [-0.25, 0.0, 0.0]);
        assert_motion(motion([4.25, 16.25, -2.0]), [0.0, 0.25, 0.0]);
        assert_motion(motion([4.25, 15.75, -2.0]), [0.0; 3]);
        assert!(
            linear_top_motion(
                previous,
                [4.5, 16.0, -2.0],
                [ContactBox::cube([0.0; 3])],
                [3.9, 17.0, -1.5],
                [0.3; 2]
            )
            .is_none()
        );
    }

    #[test]
    fn rider_uses_the_lower_slab_surface() {
        let slab = [ContactBox {
            min: [2.0, 0.0, 0.0],
            max: [3.0, 0.5, 1.0],
        }];
        let rotary = |y| rotary_top_motion([0; 3], [0.0, 90.0], slab, [2.5, y, 0.5], [0.3; 2]);
        assert_motion(rotary(0.5), [-2.0, 0.0, -2.0]);
        assert!(rotary(1.0).is_none());
        let linear =
            |y| linear_top_motion([0.0; 3], [0.25, 0.0, 0.0], slab, [2.5, y, 0.5], [0.3; 2]);
        assert_motion(linear(0.5), [0.25, 0.0, 0.0]);
        assert!(linear(1.0).is_none());
    }

    #[test]
    fn tread_motion_respects_the_partial_upper_footprint() {
        let upper = ContactBox {
            min: [2.0, 0.5, 0.0],
            max: [3.0, 1.0, 0.5],
        };
        let lower = ContactBox {
            min: [2.0, 0.0, 0.0],
            max: [3.0, 0.5, 1.0],
        };
        let tops = [upper, lower];
        let rotary = |feet| rotary_top_motion([0; 3], [0.0, 90.0], tops, feet, [0.3; 2]);
        let linear = |feet| linear_top_motion([0.0; 3], [0.25, 0.0, 0.0], tops, feet, [0.3; 2]);
        assert_motion(rotary([2.5, 1.0, 0.25]), [-2.25, 0.0, -1.75]);
        assert_motion(rotary([2.5, 0.5, 0.95]), [-1.55, 0.0, -2.45]);
        assert_motion(linear([2.5, 1.0, 0.25]), [0.25, 0.0, 0.0]);
        assert_motion(linear([2.5, 0.5, 0.95]), [0.25, 0.0, 0.0]);
        assert!(rotary([2.5, 1.0, 0.95]).is_none());
        assert!(linear([2.5, 1.0, 0.95]).is_none());
    }
}
