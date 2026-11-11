// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! Movement and world-action rules for contraption-mounted tools.

use crate::{kinetics::Pos, placement::Direction};

pub mod breaking;
pub mod harvester;
pub mod saw;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Tool {
    Harvester,
    Plough,
    Saw,
    Drill,
}

impl Tool {
    /// Local-space point to transform with the current contraption pose.
    pub fn active_point(self, local_block: Pos, facing: Direction) -> [f64; 3] {
        let reach = match self {
            Self::Harvester | Self::Plough => 0.45,
            Self::Saw | Self::Drill => f64::from(0.65_f32),
        };
        let normal = facing.vector();
        std::array::from_fn(|i| f64::from(local_block[i]) + 0.5 + f64::from(normal[i]) * reach)
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Sample {
    /// Transformed active point at the end of the current simulation tick.
    pub position: [f64; 3],
    /// The facing in the captured block state.
    pub facing: Direction,
    pub stalled: bool,
    pub disabled: bool,
    /// A train actor can make its first visit before it moves.
    pub allow_stationary_first_visit: bool,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Movement {
    pub motion: [f64; 3],
    pub relative_motion: [f64; 3],
    pub active: bool,
    pub visit: Option<Pos>,
}

/// `AbstractContraptionEntity.tickActors` / `shouldActorTrigger` and the
/// backward-facing checks in `HarvesterMovementBehaviour` / `SawMovementBehaviour`.
#[derive(Clone, Copy, Debug)]
pub struct MotionTracker {
    position: Option<[f64; 3]>,
    motion: [f64; 3],
    relative_motion: [f64; 3],
    first_movement: bool,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct MotionState {
    pub position: Option<[f64; 3]>,
    pub motion: [f64; 3],
    pub relative_motion: [f64; 3],
    pub first_movement: bool,
}

impl Default for MotionTracker {
    fn default() -> Self {
        Self {
            position: None,
            motion: [0.0; 3],
            relative_motion: [0.0; 3],
            first_movement: true,
        }
    }
}

impl MotionTracker {
    pub fn state(self) -> MotionState {
        MotionState {
            position: self.position,
            motion: self.motion,
            relative_motion: self.relative_motion,
            first_movement: self.first_movement,
        }
    }

    pub fn restore(state: MotionState) -> Option<Self> {
        state
            .position
            .into_iter()
            .chain([state.motion, state.relative_motion])
            .flatten()
            .all(f64::is_finite)
            .then_some(Self {
                position: state.position,
                motion: state.motion,
                relative_motion: state.relative_motion,
                first_movement: state.first_movement,
            })
    }

    /// `effective_motion` can normalize carriage motion to actual train speed.
    /// `inverse_rotation` transforms a vector without the pose's translation.
    pub fn sample(
        &mut self,
        sample: Sample,
        effective_motion: impl FnOnce([f64; 3]) -> [f64; 3],
        inverse_rotation: impl FnOnce([f64; 3]) -> [f64; 3],
    ) -> Movement {
        self.sample_with_activation(
            sample,
            effective_motion,
            inverse_rotation,
            |motion, facing| !points_backwards(motion, facing),
        )
    }

    pub(crate) fn sample_with_activation(
        &mut self,
        sample: Sample,
        effective_motion: impl FnOnce([f64; 3]) -> [f64; 3],
        inverse_rotation: impl FnOnce([f64; 3]) -> [f64; 3],
        can_act: impl FnOnce([f64; 3], Direction) -> bool,
    ) -> Movement {
        let cell = sample.position.map(|coordinate| coordinate.floor() as i32);
        let mut trigger = false;
        if let Some(previous) = self.position.replace(sample.position)
            && !sample.stalled
        {
            self.motion =
                effective_motion(std::array::from_fn(|i| sample.position[i] - previous[i]));
            self.relative_motion = inverse_rotation(self.motion);
            let moved = length(self.relative_motion) > 0.0;
            trigger = previous.map(|coordinate| coordinate.floor() as i32) != cell
                || (self.first_movement && (moved || sample.allow_stationary_first_visit));
        }
        let active = !sample.disabled && can_act(self.relative_motion, sample.facing);
        let visit = (active && trigger).then_some(cell);
        if visit.is_some() {
            self.first_movement = false;
        }
        Movement {
            motion: self.motion,
            relative_motion: self.relative_motion,
            active,
            visit,
        }
    }
}

pub fn points_backwards(motion: [f64; 3], facing: Direction) -> bool {
    let speed = length(motion);
    let normal = facing.opposite().vector();
    speed >= 1e-4
        && (0..3)
            .map(|i| f64::from(normal[i]) * (motion[i] / speed))
            .sum::<f64>()
            > 0.125
}

fn length([x, y, z]: [f64; 3]) -> f64 {
    (x * x + y * y + z * z).sqrt()
}

/// Accumulated phase shared by the Flywheel tool visuals.
#[derive(Clone, Copy, Debug, Default)]
pub struct Spin {
    previous: f64,
    rotation: f64,
}

impl Spin {
    pub fn advance(&mut self, degrees: f32) {
        self.previous = self.rotation;
        self.rotation = (self.rotation + f64::from(degrees)) % 360.0;
    }

    pub fn angle(self, partial: f32) -> f32 {
        let difference = (((self.rotation - self.previous) % 360.0 + 540.0) % 360.0 - 180.0) as f32;
        (self.previous + f64::from(difference) * f64::from(partial)) as f32
    }
}

/// MovementContext.getAnimationSpeed on a client.
pub fn animation_speed(distance: f64, stalled: bool) -> f32 {
    if stalled {
        700.0
    } else if distance < 1.0 / 512.0 {
        0.0
    } else {
        ((-distance * 1000.0 - 100.0) as i32 / 100 * 100) as f32
    }
}

/// `BlockBreakingMovementBehaviour.throwEntity` adds a capped world-space
/// impulse. The entity's pre-existing velocity does not count toward the cap.
pub fn throw_boost(mut motion: [f64; 3]) -> [f64; 3] {
    motion[1] += length(motion) / 4.0;
    let speed = length(motion);
    if speed > 4.0 {
        motion = motion.map(|component| component - component / speed * (speed - 4.0));
    }
    motion
}

/// Velocity used for overflow from ordinary movement actors. The caller supplies
/// the world's random float and spawns at the active point.
pub fn drop_velocity(mut motion: [f64; 3], random: f32) -> [f64; 3] {
    motion[1] += 0.5;
    motion.map(|component| component * f64::from(random * 0.3))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn step(tracker: &mut MotionTracker, position: [f64; 3], stalled: bool) -> Movement {
        tracker.sample(
            Sample {
                position,
                facing: Direction::East,
                stalled,
                disabled: false,
                allow_stationary_first_visit: false,
            },
            |motion| motion,
            |motion| motion,
        )
    }

    #[test]
    fn tools_sample_different_points_at_the_start_of_motion() {
        let position = [-2, 8, -5];
        assert_eq!(
            Tool::Harvester.active_point(position, Direction::East),
            [-1.05, 8.5, -4.5]
        );
        let point = Tool::Saw.active_point(position, Direction::East);
        assert_eq!(point, [-1.5 + f64::from(0.65_f32), 8.5, -4.5]);
        let mut tracker = MotionTracker::default();
        assert_eq!(step(&mut tracker, point, false).visit, None);
        assert_eq!(
            step(&mut tracker, [-0.7, 8.5, -4.5], false).visit,
            Some([-1, 8, -5])
        );
        assert_eq!(step(&mut tracker, [-0.6, 8.5, -4.5], false).visit, None);
        assert_eq!(
            step(&mut tracker, [0.01, 8.5, -4.5], false).visit,
            Some([0, 8, -5])
        );
    }

    #[test]
    fn a_saved_stall_keeps_local_motion_without_repeating_the_visit() {
        let mut original = MotionTracker::default();
        step(&mut original, [1.25, 3.0, 2.0], false);
        assert_eq!(
            step(&mut original, [1.5, 3.0, 2.0], false).visit,
            Some([1, 3, 2])
        );
        let saved = original.state();
        let mut restored = MotionTracker::restore(saved).unwrap();
        let held = step(&mut restored, [1.5, 3.0, 2.0], true);
        assert_eq!(held, step(&mut original, [1.5, 3.0, 2.0], true));
        assert_eq!(held.motion, [0.25, 0.0, 0.0]);
        assert_eq!(held.visit, None);
        assert!(
            MotionTracker::restore(MotionState {
                motion: [f64::NAN, 0.0, 0.0],
                ..saved
            })
            .is_none()
        );
    }

    #[test]
    fn fresh_bearing_samples_the_first_advanced_pose_before_visiting() {
        // The first two published 32 RPM poses in the Java portable farm.
        // The Saw leaves the oak cell on the second pose, while the shorter
        // Harvester reach still intersects the wheat in that same cell.
        for (tool, first_visit) in [(Tool::Saw, [3, 0, -2]), (Tool::Harvester, [3, 0, -1])] {
            let [x, y, z] = tool.active_point([3, 0, 0], Direction::North);
            let mut tracker = MotionTracker::default();
            for (angle, visit) in [(9.6_f64, None), (19.2, Some(first_visit))] {
                let (sin, cos) = angle.to_radians().sin_cos();
                let (x, z) = (x - 0.5, z - 0.5);
                let sample = Sample {
                    position: [0.5 + cos * x + sin * z, y, 0.5 - sin * x + cos * z],
                    facing: Direction::North,
                    stalled: false,
                    disabled: false,
                    allow_stationary_first_visit: false,
                };
                let movement = tracker.sample(
                    sample,
                    |motion| motion,
                    |[x, y, z]| [cos * x - sin * z, y, sin * x + cos * z],
                );
                assert_eq!(movement.visit, visit, "{tool:?} at {angle} degrees");
            }
        }
    }

    #[test]
    fn backward_or_stalled_steps_do_not_consume_the_first_active_visit() {
        let mut tracker = MotionTracker::default();
        step(&mut tracker, [1.25, 0.0, 0.0], false);
        let backward = step(&mut tracker, [0.75, 0.0, 0.0], false);
        assert!(!backward.active);
        assert_eq!(backward.visit, None);
        let stalled = step(&mut tracker, [0.75, 0.0, 0.0], true);
        assert_eq!(stalled.relative_motion, [-0.5, 0.0, 0.0]);
        assert_eq!(stalled.visit, None);
        assert_eq!(
            step(&mut tracker, [0.8, 0.0, 0.0], false).visit,
            Some([0, 0, 0])
        );
    }

    #[test]
    fn facing_test_uses_rotated_local_motion_and_normalized_dot_product() {
        let mut tracker = MotionTracker::default();
        step(&mut tracker, [0.0; 3], false);
        let movement = tracker.sample(
            Sample {
                position: [1.0, 0.0, 0.0],
                facing: Direction::North,
                stalled: false,
                disabled: false,
                allow_stationary_first_visit: false,
            },
            |motion| motion,
            |[x, y, z]| [-z, y, x],
        );
        assert!(!movement.active);
        assert_eq!(movement.visit, None);
        assert!(step(&mut tracker, [0.9, 0.0, 1.0], false).active);
        assert!(!step(&mut tracker, [0.7, 0.0, 2.0], false).active);
    }

    #[test]
    fn plough_uses_world_motion_and_caps_only_the_added_boost() {
        assert_eq!(throw_boost([0.0; 3]), [0.0; 3]);
        assert_eq!(throw_boost([0.375, 0.0, -0.5]), [0.375, 0.15625, -0.5]);
        assert_eq!(throw_boost([0.0, -2.0, 0.0]), [0.0, -1.5, 0.0]);
        let boost = throw_boost([3.0, 4.0, 0.0]);
        assert!((length(boost) - 4.0).abs() < 1e-12);
        assert!((boost[1] / boost[0] - 1.75).abs() < 1e-12);
        assert_eq!(boost[2], 0.0);
    }
}
