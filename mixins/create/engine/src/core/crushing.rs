// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT
//! CrushingWheelBlock.updateControllers and the controller's inventory cycle.

use crate::{kinetics::Axis, placement::Direction};

/// The controller's output direction from a wheel toward its partner.
pub fn direction(wheel_axis: Axis, side: Direction, rpm: f32, other_rpm: f32) -> Option<Direction> {
    if side.axis() == wheel_axis
        || rpm == 0.0
        || other_rpm == 0.0
        || (rpm > 0.0) == (other_rpm > 0.0)
    {
        return None;
    }
    let [x, y, z] = side.vector();
    let cross = match wheel_axis {
        Axis::X => [0, -z, y],
        Axis::Y => [z, 0, -x],
        Axis::Z => [-y, x, 0],
    };
    let sign = if rpm > 0.0 { 1 } else { -1 };
    Direction::from_vector(cross.map(|component| component * sign))
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Cycle {
    pub remaining: f32,
    pub recipe_time: f32,
    pub applied: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Action {
    Idle,
    Apply,
    Eject,
}

impl Cycle {
    pub fn start(&mut self, duration: i32) {
        self.remaining = duration as f32;
        self.applied = false;
    }

    /// Advances one occupied controller tick at its stored `abs(wheel_rpm / 50)`.
    pub fn tick(&mut self, crushing_speed: f32, input_count: u32) -> Action {
        if crushing_speed == 0.0 {
            return Action::Idle;
        }
        let divisor = if self.applied {
            1.0
        } else {
            f64::from(input_count).ln() as f32 / 2.0_f64.ln() as f32
        };
        let processing_speed = (crushing_speed * 4.0 / divisor).clamp(0.25, 20.0);
        self.remaining -= processing_speed;
        if self.remaining < 20.0 && !self.applied {
            // Both applyRecipe branches clear the original ProcessingInventory.
            *self = Self {
                applied: true,
                ..Self::default()
            };
            return Action::Apply;
        }
        if self.remaining > 0.0 {
            return Action::Idle;
        }
        self.remaining = 0.0;
        Action::Eject
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn opposite_wheels_agree_on_the_same_output_even_at_unequal_speeds() {
        assert_eq!(
            direction(Axis::Z, Direction::East, -64.0, 96.0),
            Some(Direction::Down)
        );
        assert_eq!(
            direction(Axis::Z, Direction::West, 96.0, -64.0),
            Some(Direction::Down)
        );
        assert_eq!(
            direction(Axis::X, Direction::South, -32.0, 32.0),
            Some(Direction::Up)
        );
        assert_eq!(
            direction(Axis::Y, Direction::East, 32.0, -32.0),
            Some(Direction::North)
        );
        assert_eq!(direction(Axis::Z, Direction::East, -64.0, -96.0), None);
        assert_eq!(direction(Axis::Z, Direction::East, -64.0, 0.0), None);
        assert_eq!(direction(Axis::Z, Direction::North, -64.0, 96.0), None);
    }

    #[test]
    fn one_item_always_advances_twenty_and_applies_strictly_below_twenty() {
        let mut cycle = Cycle::default();
        cycle.start(100);
        for expected in [80.0, 60.0, 40.0, 20.0] {
            assert_eq!(cycle.tick(1.0 / 50.0, 1), Action::Idle);
            assert_eq!(cycle.remaining, expected);
        }
        assert_eq!(cycle.tick(1.0 / 50.0, 1), Action::Apply);
        assert_eq!(
            cycle,
            Cycle {
                applied: true,
                ..Cycle::default()
            }
        );
        assert_eq!(cycle.tick(0.0, 0), Action::Idle);
        assert_eq!(cycle.tick(1.0 / 50.0, 0), Action::Eject);
    }

    #[test]
    fn four_items_use_the_logarithmic_rate_and_retain_progress_without_power() {
        let mut cycle = Cycle::default();
        cycle.start(250);
        assert_eq!(cycle.tick(128.0 / 50.0, 4), Action::Idle);
        assert_eq!(cycle.remaining, 244.88);
        let paused = cycle;
        assert_eq!(cycle.tick(0.0, 4), Action::Idle);
        assert_eq!(cycle, paused);
        for _ in 1..44 {
            assert_eq!(cycle.tick(128.0 / 50.0, 4), Action::Idle);
        }
        assert_eq!(cycle.tick(128.0 / 50.0, 4), Action::Apply);
        assert_eq!(cycle.tick(128.0 / 50.0, 0), Action::Eject);
    }
}
