// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! ClockworkContraption split capture and ClockworkBearingBlockEntity
//! server-side motion. The host commits both hands together.

use std::collections::HashSet;

use crate::{kinetics::Pos, placement::Direction};

use super::{Assembly, CaptureError, CaptureView, Cell};

pub const STRESS_IMPACT_PER_RPM: f32 = 4.0;
pub const RESTORE_ANGLE: f32 = 0.0;

#[derive(Debug)]
pub struct Hands<B> {
    pub hour: Assembly<B>,
    pub minute: Option<Assembly<B>>,
}

/// Capture the hour structure first. The minute pivot sits just beyond the
/// contiguous part of the hour structure along the bearing axis.
pub fn capture<W: CaptureView>(
    world: &W,
    controller: Pos,
    facing: Direction,
    max_blocks_per_hand: usize,
) -> Result<Option<Hands<W::Block>>, CaptureError> {
    let vector = facing.vector();
    let offset = |distance: i32| vector.map(|component| component * distance);
    let anchor = add(controller, vector)?;
    let hour = Assembly::capture(world, anchor, Some(controller), None, max_blocks_per_hand)?;
    if hour.blocks().is_empty() {
        return Ok(None);
    }

    let hour_positions: HashSet<_> = hour.blocks().iter().map(|(pos, _)| *pos).collect();
    let minute = if let Some(distance) = (1..16).find(|&i| !hour_positions.contains(&offset(i))) {
        let ignored = hour_positions
            .into_iter()
            .map(|pos| add(anchor, pos))
            .collect::<Result<HashSet<_>, _>>()?;
        let view = WithoutHour { world, ignored };
        let minute_anchor = add(anchor, offset(distance))?;
        let minute = Assembly::capture(
            &view,
            minute_anchor,
            Some(controller),
            None,
            max_blocks_per_hand,
        )?;
        (!minute.blocks().is_empty()).then_some(minute)
    } else {
        None
    };
    Ok(Some(Hands { hour, minute }))
}

fn add(left: Pos, right: Pos) -> Result<Pos, CaptureError> {
    let err = CaptureError::CoordinateOverflow;
    Ok([
        left[0].checked_add(right[0]).ok_or(err)?,
        left[1].checked_add(right[1]).ok_or(err)?,
        left[2].checked_add(right[2]).ok_or(err)?,
    ])
}

struct WithoutHour<'a, W> {
    world: &'a W,
    ignored: HashSet<Pos>,
}

impl<W: CaptureView> CaptureView for WithoutHour<'_, W> {
    type Block = W::Block;

    fn inspect(&self, pos: Pos) -> Cell {
        if self.ignored.contains(&pos) {
            Cell::Empty
        } else {
            self.world.inspect(pos)
        }
    }

    fn snapshot(&self, pos: Pos) -> Option<Self::Block> {
        self.world.snapshot(pos)
    }

    fn glued(&self, pos: Pos, face: Direction) -> bool {
        self.world.glued(pos, face)
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Mode {
    #[default]
    HourFirst,
    MinuteFirst,
    HourFirst24,
}

impl Mode {
    pub fn from_scroll_value(value: i32) -> Option<Self> {
        match value {
            0 => Some(Self::HourFirst),
            1 => Some(Self::MinuteFirst),
            2 => Some(Self::HourFirst24),
            _ => None,
        }
    }
}

/// Named by the hand structure, even when the selected mode swaps their dials.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Angles {
    pub hour: f32,
    pub minute: f32,
}

#[derive(Clone, Copy, Debug)]
pub struct ClockTime {
    pub day_time: i64,
    pub natural_dimension: bool,
    pub facing: Direction,
}

impl ClockTime {
    pub fn targets(self, mode: Mode) -> Angles {
        let time_scale = if self.natural_dimension { 1 } else { 24 };
        let day_time = (self.day_time.wrapping_mul(time_scale) % 24_000) as i32;
        let hours = (day_time / 1_000 + 6) % 24;
        let minutes = (day_time % 1_000) * 60 / 1_000;
        let facing_step = self.facing.vector()[self.facing.axis().index()];
        let sign = (facing_step * -360) as f32;
        let hour = sign / 12.0 * (hours % 12) as f32;
        let minute = sign / 60.0 * minutes as f32;
        match mode {
            Mode::HourFirst => Angles { hour, minute },
            Mode::MinuteFirst => Angles {
                hour: minute,
                minute: hour,
            },
            Mode::HourFirst24 => Angles {
                hour: sign / 24.0 * hours as f32,
                minute,
            },
        }
    }
}

/// Catnip AngleHelper.getShortestAngleDiff promotes both inputs to double.
/// The exact half-turn goes negative, regardless of the target's sign.
fn shortest_angle_diff(angle: f32, target: f32) -> f32 {
    let angle = f64::from(angle) % 360.0;
    let target = f64::from(target) % 360.0;
    (((target - angle) % 360.0 + 540.0) % 360.0 - 180.0) as f32
}

impl Angles {
    pub fn advance(self, targets: Self, rpm: f32, stalled: [bool; 2]) -> Self {
        let angular_speed = (rpm * 3.0 / 10.0).abs();
        let step = |angle, target, limit: f32, stalled| {
            if stalled {
                return angle;
            }
            let delta = shortest_angle_diff(angle, target).clamp(-limit, limit);
            // The Java server adds its zero-valued client correction before
            // applying the delta, which canonicalizes a negative-zero delta.
            (angle + (delta + 0.0)) % 360.0
        };
        Self {
            hour: step(self.hour, targets.hour, angular_speed / 2.0, stalled[0]),
            minute: step(self.minute, targets.minute, angular_speed, stalled[1]),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TickAction {
    None,
    Assembled,
    Disassemble,
}

#[derive(Debug, Default)]
pub struct Clockwork {
    running: bool,
    assembly_requested: bool,
    angles: Angles,
}

impl Clockwork {
    pub fn restored(running: bool, angles: Angles) -> Self {
        Self {
            running,
            angles,
            ..Self::default()
        }
    }

    pub fn running(&self) -> bool {
        self.running
    }

    pub fn angles(&self) -> Angles {
        self.angles
    }

    /// Returns true when a manual use requests immediate disassembly.
    pub fn toggle(&mut self) -> bool {
        if self.running {
            return true;
        }
        self.assembly_requested = true;
        false
    }

    pub fn speed_changed(&mut self) {
        self.assembly_requested = true;
    }

    /// Java skips angle advancement on the turn that handles a pending
    /// assembly or speed change, including while power stays on.
    pub fn tick(
        &mut self,
        time: ClockTime,
        mode: Mode,
        theoretical_rpm: f32,
        effective_rpm: f32,
        stalled: [bool; 2],
        assemble: impl FnOnce() -> bool,
    ) -> TickAction {
        if std::mem::take(&mut self.assembly_requested) {
            if self.running {
                return if theoretical_rpm == 0.0 {
                    TickAction::Disassemble
                } else {
                    TickAction::None
                };
            }
            if assemble() {
                self.running = true;
                self.angles = Angles::default();
                return TickAction::Assembled;
            }
        } else if self.running {
            self.angles = self
                .angles
                .advance(time.targets(mode), effective_rpm, stalled);
        }
        TickAction::None
    }

    /// Acknowledge successful restoration of both hands at RESTORE_ANGLE.
    pub fn disassembled(&mut self) {
        *self = Self::default();
    }
}

#[cfg(test)]
mod tests {
    use super::{super::BlockRules, *};

    #[test]
    fn splits_disconnected_hands_without_capturing_the_controller_or_first_hand_twice() {
        struct World;
        impl CaptureView for World {
            type Block = Pos;

            fn inspect(&self, pos: Pos) -> Cell {
                match pos {
                    [0..=3, 0, 0] => Cell::Block(BlockRules::default()),
                    _ => Cell::Empty,
                }
            }

            fn snapshot(&self, pos: Pos) -> Option<Pos> {
                Some(pos)
            }

            fn glued(&self, [x, _, _]: Pos, face: Direction) -> bool {
                (face == Direction::East && x < 2) || (face == Direction::West && x <= 3)
            }
        }

        let hands = capture(&World, [0; 3], Direction::East, 16)
            .unwrap()
            .unwrap();
        assert_eq!(hands.hour.anchor(), [1, 0, 0]);
        assert_eq!(
            hands.hour.blocks(),
            &[([0, 0, 0], [1, 0, 0]), ([1, 0, 0], [2, 0, 0])]
        );
        let minute = hands.minute.unwrap();
        assert_eq!(minute.anchor(), [3, 0, 0]);
        assert_eq!(minute.blocks(), &[([0, 0, 0], [3, 0, 0])]);
    }

    #[test]
    fn a_sixteen_block_hour_hand_does_not_scan_for_a_minute_hand_beyond_it() {
        struct World;
        impl CaptureView for World {
            type Block = Pos;

            fn inspect(&self, pos: Pos) -> Cell {
                match pos {
                    [1..=17, 0, 0] => Cell::Block(BlockRules::default()),
                    _ => Cell::Empty,
                }
            }

            fn snapshot(&self, pos: Pos) -> Option<Pos> {
                Some(pos)
            }

            fn glued(&self, [x, _, _]: Pos, face: Direction) -> bool {
                face == Direction::East && x < 16
            }
        }

        let hands = capture(&World, [0; 3], Direction::East, 32)
            .unwrap()
            .unwrap();
        assert_eq!(hands.hour.blocks().len(), 16);
        assert!(hands.minute.is_none());
    }

    #[test]
    fn clock_modes_follow_local_time_and_facing_sign() {
        let mut time = ClockTime {
            day_time: 7_250,
            natural_dimension: true,
            facing: Direction::South,
        };
        assert_eq!(
            time.targets(Mode::HourFirst),
            Angles {
                hour: -30.0,
                minute: -90.0
            }
        );
        assert_eq!(
            time.targets(Mode::MinuteFirst),
            Angles {
                hour: -90.0,
                minute: -30.0
            }
        );
        assert_eq!(
            time.targets(Mode::HourFirst24),
            Angles {
                hour: -195.0,
                minute: -90.0
            }
        );
        time.facing = Direction::North;
        assert_eq!(
            time.targets(Mode::HourFirst24),
            Angles {
                hour: 195.0,
                minute: 90.0
            }
        );
        time.natural_dimension = false;
        assert_eq!(
            time.targets(Mode::HourFirst24),
            Angles {
                hour: 180.0,
                minute: 0.0
            }
        );
    }

    #[test]
    fn half_turn_tie_goes_negative_and_stall_only_freezes_one_hand() {
        let angles = Angles::default().advance(
            Angles {
                hour: 180.0,
                minute: 15.0,
            },
            -64.0,
            [false; 2],
        );
        assert_eq!(
            angles,
            Angles {
                hour: -9.6,
                minute: 15.0
            }
        );
        let angles = angles.advance(
            Angles {
                hour: -180.0,
                minute: 5.0,
            },
            64.0,
            [true, false],
        );
        assert_eq!(
            angles,
            Angles {
                hour: -9.6,
                minute: 5.0
            }
        );
    }

    #[test]
    fn stationary_hand_normalizes_its_pose_unless_stalled() {
        let angles = Angles {
            hour: -0.0,
            minute: -0.0,
        }
        .advance(
            Angles {
                hour: -90.0,
                minute: -90.0,
            },
            0.0,
            [false, true],
        );
        assert_eq!(angles.hour.to_bits(), 0.0f32.to_bits());
        assert_eq!(angles.minute.to_bits(), (-0.0f32).to_bits());
    }

    #[test]
    fn manual_assembly_at_zero_rpm_and_speed_change_skip_the_angle_turn() {
        let mut clock = Clockwork::default();
        let time = ClockTime {
            day_time: 6_500,
            natural_dimension: true,
            facing: Direction::East,
        };
        let mode = Mode::HourFirst;
        assert!(!clock.toggle());
        assert_eq!(
            clock.tick(time, mode, 0.0, 0.0, [false; 2], || true),
            TickAction::Assembled
        );
        assert!(clock.running());
        assert_eq!(clock.angles(), Angles::default());
        clock.speed_changed();
        assert_eq!(
            clock.tick(time, mode, 32.0, 32.0, [false; 2], || unreachable!()),
            TickAction::None
        );
        assert_eq!(clock.angles(), Angles::default());
        clock.tick(time, mode, 32.0, 32.0, [false; 2], || unreachable!());
        assert_eq!(
            clock.angles(),
            Angles {
                hour: 0.0,
                minute: -9.6
            }
        );
        clock.speed_changed();
        assert_eq!(
            clock.tick(time, mode, 0.0, 0.0, [false; 2], || unreachable!()),
            TickAction::Disassemble
        );
        assert!(clock.running());
        clock.disassembled();
        assert!(!clock.running());
    }
}
