// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! The soft and hard correction passes in Java Create's `CouplingPhysics`.

type Vector = [f64; 3];

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Cart {
    pub position: Vector,
    pub velocity: Vector,
    pub max_rail_speed: f32,
    pub accepts_motion: bool,
    pub frozen: bool,
}

/// Predict the next position and return replacement velocities for the two
/// carts. `track_at` receives each prediction, from which the host resolves the
/// rail below the predicted cart using the source's rail sampling rule.
/// The `None` path leaves both current velocities intact.
pub fn soft_step(
    carts: [Cart; 2],
    length: f32,
    mut track_at: impl FnMut(usize, Vector) -> Option<Vector>,
) -> Option<[Vector; 2]> {
    if carts.iter().all(|cart| cart.frozen) {
        return None;
    }

    let motion = carts.map(|cart| clamp(cart.velocity, 1.0));
    let next: [Vector; 2] = std::array::from_fn(|i| add(carts[i].position, motion[i]));
    let track: [_; 2] = std::array::from_fn(|i| track_at(i, next[i]));
    let stress = (f64::from(length) - norm(sub(next[0], next[1]))) as f32;
    if f64::from(stress.abs()) < f64::from(1.0e-5_f32) {
        return None;
    }

    Some(std::array::from_fn(|i| {
        let cart = carts[i];
        let mut velocity = motion[i];
        if cart.accepts_motion {
            let other = 1 - i;
            let magnitude = if carts[other].accepts_motion {
                -stress / 2.0
            } else {
                -stress
            };
            let correction = resolve(next[i], next[other], magnitude, track[i]);
            velocity = add(velocity, clamp(correction, cart.max_rail_speed));
        }
        clamp(velocity, cart.max_rail_speed)
    }))
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct HardCorrection {
    pub cart: usize,
    pub displacement: Vector,
    /// The host routes this through `MinecartSim2020.moveCartAlongTrack` for
    /// rail contact. Otherwise it clips a normal SELF move and scales the
    /// cart's resulting velocity by Java's `0.95f`.
    pub on_rail: bool,
}

/// One server correction pass. The host applies each result and reads fresh
/// poses before requesting the next correction so collisions affect the pass.
#[derive(Debug)]
pub struct HardStep {
    length: f32,
    max_speed: [f32; 2],
    first_cart: usize,
    resolved: bool,
    next: usize,
}

impl HardStep {
    pub fn new(carts: [Cart; 2], length: f32) -> Option<Self> {
        if carts.iter().all(|cart| cart.frozen) {
            return None;
        }
        Some(Self {
            length,
            max_speed: carts.map(|cart| 1.75_f32.min(cart.max_rail_speed)),
            first_cart: usize::from(carts[0].accepts_motion && !carts[1].accepts_motion),
            resolved: false,
            next: 0,
        })
    }

    /// `track_at` resolves the rail vector at the current, rather than the
    /// predicted, cart position using the source's current-rail lookup.
    pub fn next(
        &mut self,
        carts: [Cart; 2],
        mut track_at: impl FnMut(usize, Vector) -> Option<Vector>,
    ) -> Option<HardCorrection> {
        while self.next < 3 {
            let i = self.first_cart ^ (self.next % 2);
            self.next += 1;
            let cart = carts[i];
            let other = carts[1 - i];
            let stress = (f64::from(self.length) - norm(sub(cart.position, other.position))) as f32;
            if stress.abs() < 1.0 / 8.0 {
                continue;
            }

            let mut magnitude = if self.resolved {
                -stress
            } else {
                -stress / 2.0
            };
            if !cart.accepts_motion {
                magnitude /= 2.0;
            }
            let track = track_at(i, cart.position);
            let correction = resolve(cart.position, other.position, magnitude, track);
            self.resolved = true;
            return Some(HardCorrection {
                cart: i,
                displacement: clamp(correction, self.max_speed[i]),
                on_rail: track.is_some(),
            });
        }
        None
    }
}

fn resolve(cart: Vector, other: Vector, magnitude: f32, rail: Option<Vector>) -> Vector {
    let link = sub(other, cart);
    let Some(rail) = rail else {
        return scale(normalize(link), f64::from(magnitude));
    };
    sub(follow_link_on_rail(link, cart, magnitude, rail), cart)
}

/// Move along the rail to the nearest sphere intersection chosen by Create.
/// If the rail misses the sphere, use the projected position of the other cart.
pub fn follow_link_on_rail(link: Vector, cart: Vector, magnitude: f32, rail: Vector) -> Vector {
    let alignment = dot(rail, link);
    if alignment.is_nan() || alignment == 0.0 || magnitude == 0.0 {
        return cart;
    }

    let axis = scale(rail, -alignment.signum());
    let unit = if dot(axis, axis) == 1.0 {
        axis
    } else {
        normalize(axis)
    };
    let from_center = sub(cart, add(cart, link));
    let radius = norm(link) - f64::from(magnitude);
    let projection = dot(unit, from_center);
    let discriminant = projection * projection - (dot(from_center, from_center) - radius * radius);
    if discriminant < 0.0 {
        return add(cart, scale(axis, dot(link, axis) / dot(axis, axis)));
    }
    add(cart, scale(unit, -projection + discriminant.sqrt()))
}

fn add(a: Vector, b: Vector) -> Vector {
    std::array::from_fn(|i| a[i] + b[i])
}

fn sub(a: Vector, b: Vector) -> Vector {
    std::array::from_fn(|i| a[i] - b[i])
}

fn scale(v: Vector, amount: f64) -> Vector {
    v.map(|component| component * amount)
}

pub(super) fn dot([x, y, z]: Vector, [a, b, c]: Vector) -> f64 {
    x * a + y * b + z * c
}

pub(super) fn norm(v: Vector) -> f64 {
    dot(v, v).sqrt()
}

pub(super) fn normalize(v: Vector) -> Vector {
    let length = norm(v);
    if length < f64::from(1.0e-5_f32) {
        [0.0; 3]
    } else {
        v.map(|component| component / length)
    }
}

fn clamp(v: Vector, max: f32) -> Vector {
    if dot(v, v) > f64::from(max * max) {
        scale(normalize(v), f64::from(max))
    } else {
        v
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cart(x: f64) -> Cart {
        Cart {
            position: [x, 0.0, 0.0],
            velocity: [0.0; 3],
            max_rail_speed: 2.0,
            accepts_motion: true,
            frozen: false,
        }
    }

    #[test]
    fn rail_motion_finds_the_source_intersection_and_projection() {
        let position = [13.0, 4.0, 1.0];
        let rail = [1.0, 0.0, 0.0];
        assert_eq!(
            follow_link_on_rail([5.0, 0.0, 0.0], position, 0.5, rail),
            [13.5, 4.0, 1.0]
        );
        assert_eq!(
            follow_link_on_rail([5.0, 0.0, 0.0], position, -0.5, rail),
            [12.5, 4.0, 1.0]
        );
        assert_eq!(
            follow_link_on_rail([3.0, 0.0, 4.0], position, 2.0, rail),
            [16.0, 4.0, 1.0]
        );
        assert_eq!(
            follow_link_on_rail([0.0, 0.0, 4.0], position, 2.0, rail),
            position
        );
    }

    #[test]
    fn soft_step_predicts_from_capped_velocity_and_shares_the_correction() {
        let carts = [
            Cart {
                velocity: [1.2, 0.0, 0.0],
                ..cart(0.0)
            },
            cart(6.0),
        ];
        let mut sampled = Vec::new();
        let velocities = soft_step(carts, 4.0, |i, predicted| {
            sampled.push((i, predicted));
            Some([1.0, 0.0, 0.0])
        });
        assert_eq!(sampled, [(0, [1.0, 0.0, 0.0]), (1, [6.0, 0.0, 0.0])]);
        assert_eq!(velocities, Some([[1.5, 0.0, 0.0], [-0.5, 0.0, 0.0]]));
    }

    #[test]
    fn soft_step_can_pull_one_cart_and_skips_both_frozen_or_relaxed_carts() {
        let leading = Cart {
            max_rail_speed: 0.4,
            ..cart(0.0)
        };
        let trailing = Cart {
            accepts_motion: false,
            ..cart(6.0)
        };
        assert_eq!(
            soft_step([leading, trailing], 4.0, |_, _| None),
            Some([[f64::from(0.4_f32), 0.0, 0.0], [0.0; 3]])
        );
        assert!(soft_step([leading, trailing], 6.0, |_, _| None).is_none());
        let frozen = [leading, trailing].map(|cart| Cart {
            frozen: true,
            ..cart
        });
        assert!(soft_step(frozen, 4.0, |_, _| unreachable!()).is_none());
        assert!(HardStep::new(frozen, 4.0).is_none());
    }

    #[test]
    fn hard_step_rechecks_clipped_poses_and_resolves_the_reordered_cart_first() {
        let mut carts = [
            cart(0.0),
            Cart {
                accepts_motion: false,
                ..cart(6.0)
            },
        ];
        let mut step = HardStep::new(carts, 4.0).unwrap();
        let first = step.next(carts, |_, _| None).unwrap();
        assert_eq!(
            first,
            HardCorrection {
                cart: 1,
                displacement: [-0.5, 0.0, 0.0],
                on_rail: false
            }
        );
        carts[1].position[0] -= 0.25;
        let second = step.next(carts, |_, _| Some([1.0, 0.0, 0.0])).unwrap();
        assert_eq!(
            second,
            HardCorrection {
                cart: 0,
                displacement: [1.75, 0.0, 0.0],
                on_rail: true
            }
        );
        carts[0].position[0] += 1.5;
        let third = step.next(carts, |_, _| None).unwrap();
        assert_eq!(
            third,
            HardCorrection {
                cart: 1,
                displacement: [-0.125, 0.0, 0.0],
                on_rail: false
            }
        );
        assert!(step.next(carts, |_, _| None).is_none());
        assert!(
            HardStep::new([cart(0.0), cart(4.0625)], 4.0)
                .unwrap()
                .next([cart(0.0), cart(4.0625)], |_, _| None)
                .is_none()
        );
    }
}
