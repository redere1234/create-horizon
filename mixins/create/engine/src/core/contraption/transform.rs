// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use crate::{
    kinetics::{Axis, Pos},
    placement::Direction,
};
use std::collections::VecDeque;

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct RenderPose {
    pub angle: f32,
    pub offset: f32,
}

impl RenderPose {
    fn between(self, next: Self, fraction: f32) -> Self {
        let delta = (next.angle - self.angle + 180.0).rem_euclid(360.0) - 180.0;
        Self {
            angle: self.angle + delta * fraction,
            offset: self.offset + (next.offset - self.offset) * fraction,
        }
    }
}

#[derive(Default)]
pub struct RenderMotion {
    // Client time in ticks, paired with authoritative positions. A half-tick
    // cushion absorbs packet arrival differences without extrapolating a pose.
    samples: VecDeque<(f64, RenderPose)>,
}

impl RenderMotion {
    pub fn sample(
        &mut self,
        now: f64,
        period: f64,
        previous: RenderPose,
        current: RenderPose,
    ) -> RenderPose {
        while self.samples.get(1).is_some_and(|sample| sample.0 <= now) {
            self.samples.pop_front();
        }
        if self.samples.len() >= 6 {
            // A sprint or a burst of packets should not queue old motion.
            self.samples.clear();
        }
        if self.samples.is_empty() {
            self.samples.push_back((now + period * 0.5, previous));
        }
        if self
            .samples
            .back()
            .is_some_and(|sample| sample.1 != current)
        {
            self.queue(previous, now, period);
            self.queue(current, now, period);
        }
        let (start, pose) = self.samples[0];
        let Some(&(end, target)) = self.samples.get(1) else {
            return pose;
        };
        pose.between(
            target,
            ((now - start) / (end - start)).clamp(0.0, 1.0) as f32,
        )
    }

    fn queue(&mut self, pose: RenderPose, now: f64, period: f64) {
        let last = self.samples.back_mut().unwrap();
        if last.1 != pose {
            last.0 = last.0.max(now);
            let next = last.0 + period;
            self.samples.push_back((next, pose));
        }
    }
}

#[cfg(test)]
mod render_motion_tests {
    use super::*;

    fn pose(angle: f32, offset: f32) -> RenderPose {
        RenderPose { angle, offset }
    }

    #[test]
    fn early_and_repeated_packets_do_not_replay_the_previous_tick() {
        let mut motion = RenderMotion::default();
        let zero = pose(0.0, 0.0);
        let one = pose(10.0, 0.25);
        let two = pose(20.0, 0.5);
        let three = pose(30.0, 0.75);
        assert_eq!(motion.sample(0.0, 1.0, zero, one), zero);
        assert_eq!(motion.sample(1.0, 1.0, one, two), pose(5.0, 0.125));
        assert_eq!(motion.sample(2.0, 1.0, one, two), pose(15.0, 0.375));
        assert_eq!(motion.sample(2.25, 1.0, two, three), pose(17.5, 0.4375));
        assert_eq!(motion.sample(3.0, 1.0, two, three), pose(25.0, 0.625));
        assert_eq!(motion.sample(10.0, 1.0, two, three), three);
    }

    #[test]
    fn angles_wrap_and_an_idle_track_resumes_from_its_held_pose() {
        let mut motion = RenderMotion::default();
        let before = pose(354.0, 1.0);
        let after = pose(2.0, 0.5);
        motion.sample(0.0, 1.0, before, after);
        assert_eq!(motion.sample(1.0, 1.0, before, after), pose(358.0, 0.75));
        assert_eq!(motion.sample(20.0, 1.0, after, after), after);
        let reverse = pose(354.0, 1.0);
        assert_eq!(motion.sample(21.0, 1.0, after, reverse), after);
        assert_eq!(motion.sample(21.5, 1.0, after, reverse), pose(-2.0, 0.75));
    }
}

/// The centre of the local origin block is the pivot. Points are expressed
/// relative to its lower corner, as in ControlledContraptionEntity.
#[derive(Clone, Copy, Debug)]
pub struct Rotation {
    anchor: Pos,
    turn: QuarterTurn,
    sin: f64,
    cos: f64,
}

impl Rotation {
    pub fn new(anchor: Pos, axis: Axis, degrees: f32) -> Option<Self> {
        if !degrees.is_finite() {
            return None;
        }
        let (sin, cos) = f64::from(degrees).to_radians().sin_cos();
        let steps = java_round(degrees / 90.0).rem_euclid(4.0) as u8;
        Some(Self {
            anchor,
            turn: QuarterTurn { axis, steps },
            sin,
            cos,
        })
    }

    pub fn to_world(self, local: [f64; 3]) -> [f64; 3] {
        let rotated = self.rotate_vector(local.map(|coordinate| coordinate - 0.5));
        std::array::from_fn(|i| rotated[i] + 0.5 + f64::from(self.anchor[i]))
    }

    pub fn to_local(self, world: [f64; 3]) -> [f64; 3] {
        let relative = std::array::from_fn(|i| world[i] - f64::from(self.anchor[i]) - 0.5);
        self.rotate(relative, -self.sin)
            .map(|coordinate| coordinate + 0.5)
    }

    pub fn rotate_vector(self, vector: [f64; 3]) -> [f64; 3] {
        self.rotate(vector, self.sin)
    }

    fn rotate(self, [x, y, z]: [f64; 3], sin: f64) -> [f64; 3] {
        let cos = self.cos;
        match self.turn.axis {
            Axis::X => [x, y * cos - z * sin, y * sin + z * cos],
            Axis::Y => [x * cos + z * sin, y, -x * sin + z * cos],
            Axis::Z => [x * cos - y * sin, x * sin + y * cos, z],
        }
    }

    pub fn snapped(self) -> QuarterTurn {
        self.turn
    }
}

/// StructureTransform uses Java's rounding towards positive infinity at ties.
pub(super) fn java_round(value: f32) -> f64 {
    (f64::from(value) + 0.5).floor()
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct QuarterTurn {
    axis: Axis,
    steps: u8,
}

impl QuarterTurn {
    pub const IDENTITY: Self = Self {
        axis: Axis::Y,
        steps: 0,
    };

    fn rotate(self, mut position: [i64; 3]) -> [i64; 3] {
        for _ in 0..self.steps {
            let [x, y, z] = position;
            position = match self.axis {
                Axis::X => [x, -z, y],
                Axis::Y => [z, y, -x],
                Axis::Z => [-y, x, z],
            };
        }
        position
    }

    pub fn place(self, anchor: Pos, local: Pos) -> Option<Pos> {
        let rotated = self.rotate(local.map(i64::from));
        Some([
            i32::try_from(i64::from(anchor[0]) + rotated[0]).ok()?,
            i32::try_from(i64::from(anchor[1]) + rotated[1]).ok()?,
            i32::try_from(i64::from(anchor[2]) + rotated[2]).ok()?,
        ])
    }

    pub fn facing(self, direction: Direction) -> Direction {
        let vector = self.rotate(direction.vector().map(i64::from));
        Direction::from_vector(vector.map(|coordinate| coordinate as i32))
            .expect("quarter turns preserve cardinal unit vectors")
    }

    pub fn axis(self, axis: Axis) -> Axis {
        self.facing(match axis {
            Axis::X => Direction::East,
            Axis::Y => Direction::Up,
            Axis::Z => Direction::South,
        })
        .axis()
    }
}
