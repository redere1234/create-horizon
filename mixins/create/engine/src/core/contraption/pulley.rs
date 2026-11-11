// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! Rope Pulley assembly and movement from `PulleyBlockEntity` and `PulleyContraption`.

use super::{
    Assembly, CaptureError, CaptureView,
    linear::{Action, LinearActuator, Mode, Motion, Tick, Track},
};
use crate::{kinetics::Pos, placement::Direction};

pub const DEFAULT_MAX_ROPE_LENGTH: u32 = 384;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Part {
    Rope,
    Magnet,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Segment {
    pub part: Part,
    pub waterlogged: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Cell {
    Rope(Segment),
    Pulley,
    Other,
    Unloaded,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Layout {
    pub controller: Pos,
    pub initial_offset: u32,
    pub extension_range: u32,
    /// Source segments in Java's bottom-to-top removal order.
    pub remove: Vec<(Pos, Segment)>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Probe {
    pub anchor: Pos,
    pub direction: Direction,
}

impl Layout {
    /// Scan all consecutive rope/magnet states, even if the last one is rope.
    /// The adapter restores each source cell's fluid when removing its segment.
    pub fn scan(
        controller: Pos,
        min_build_height: i32,
        max_rope_length: u32,
        mut read: impl FnMut(Pos) -> Cell,
    ) -> Result<Self, CaptureError> {
        let depth = (i64::from(controller[1]) - i64::from(min_build_height)).max(0) as u32;
        let extension_range = depth.saturating_sub(1).min(max_rope_length);
        let mut remove = Vec::new();
        for distance in 1..=depth.min(max_rope_length) {
            let position = below(controller, distance)?;
            match read(position) {
                Cell::Rope(segment) => remove.push((position, segment)),
                Cell::Unloaded => return Err(CaptureError::Unloaded(position)),
                Cell::Pulley | Cell::Other => break,
            }
        }
        let initial_offset = remove.len() as u32;
        remove.reverse();
        Ok(Self {
            controller,
            initial_offset,
            extension_range,
            remove,
        })
    }

    pub fn anchor(&self) -> Result<Pos, CaptureError> {
        shift_y(self.controller, -i64::from(self.initial_offset) - 1)
    }

    /// The fixed rope column includes the controller but ends above the payload.
    pub fn anchors(&self, position: Pos) -> bool {
        if position[0] != self.controller[0] || position[2] != self.controller[2] {
            return false;
        }
        let below_controller = i64::from(self.controller[1]) - i64::from(position[1]);
        (0..=i64::from(self.initial_offset)).contains(&below_controller)
    }

    pub fn capture<B>(
        &self,
        world: &impl CaptureView<Block = B>,
        limit: usize,
    ) -> Result<Assembly<B>, CaptureError> {
        let anchor = self.anchor()?;
        Assembly::capture_from(
            world,
            anchor,
            [anchor],
            |position| self.anchors(position),
            None,
            limit,
        )
    }

    pub fn assembly_probe(&self, rpm: f32) -> Option<Probe> {
        let direction = if rpm > 0.0 {
            Direction::Down
        } else if rpm < 0.0 {
            Direction::Up
        } else {
            return None;
        };
        let anchor = shift_y(self.anchor().ok()?, i64::from(direction.vector()[1])).ok()?;
        Some(Probe { anchor, direction })
    }

    /// Empty assemblies can lower the line. While lowering, a failed
    /// structure or collision check prevents the assembly from starting.
    pub fn start(&self, rpm: f32, assembled: bool, has_payload: bool) -> Option<Drive> {
        if rpm == 0.0
            || !rpm.is_finite()
            || (rpm > 0.0 && (!assembled || self.initial_offset >= self.extension_range))
            || (rpm < 0.0 && self.initial_offset == 0)
        {
            return None;
        }
        Some(Drive {
            actuator: LinearActuator::start(self.initial_offset, self.extension_range)?,
            has_payload,
        })
    }
}

/// The pulley uses the same positive RPM and offset convention on both shaft axes.
pub fn directional_speed(rpm: f32) -> f32 {
    (rpm / 512.0).clamp(-0.49, 0.49)
}

pub fn position_at(controller: Pos, offset: f32) -> [f64; 3] {
    [
        f64::from(controller[0]),
        f64::from(controller[1]) - 1.0 - f64::from(offset),
        f64::from(controller[2]),
    ]
}

#[derive(Clone, Debug)]
pub struct Drive {
    pub actuator: LinearActuator,
    pub has_payload: bool,
}

impl Drive {
    /// `catches` returns true for a necessary, non-brittle block when an empty
    /// line reaches it. The host lands the line before retrying assembly.
    pub fn tick(
        &mut self,
        controller: Pos,
        rpm: f32,
        mode: Mode,
        stalled: bool,
        collides: impl FnOnce(Probe) -> bool,
        catches: impl FnOnce(Pos) -> bool,
    ) -> Action {
        let has_payload = self.has_payload;
        self.actuator.tick_track(
            Tick {
                rpm,
                directional_speed: directional_speed(rpm),
                mode,
                stalled,
                track: Track::Pulley,
            },
            |motion| has_payload && collision_probe(controller, motion).is_none_or(collides),
            |next| {
                !has_payload
                    && rpm > 0.0
                    && shift_y(controller, -(next as i64) - 1).is_ok_and(catches)
            },
        )
    }
}

/// `ContraptionCollider.collideBlocks` uses a floor plus one cell for
/// positive world-axis motion, even for a fractional last step.
fn collision_probe(controller: Pos, motion: Motion) -> Option<Probe> {
    let direction = if motion.to < motion.from {
        Direction::Up
    } else {
        Direction::Down
    };
    let [x, _, z] = controller;
    let y = position_at(controller, motion.to)[1].floor()
        + f64::from(i32::from(direction == Direction::Up));
    if !(f64::from(i32::MIN)..=f64::from(i32::MAX)).contains(&y) {
        return None;
    }
    let anchor = [x, y as i32, z];
    Some(Probe { anchor, direction })
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LandingCell {
    Present {
        breakable: bool,
        collision_empty: bool,
        source_water: bool,
    },
    Unloaded,
    OutsideWorld,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RopeEdit {
    Destroy { position: Pos, drops: bool },
    Place { position: Pos, segment: Segment },
}

/// Plan the magnet's break/place first, then destroy the whole rope span
/// before placing the new segments. Unbreakable cells are left untouched by
/// Java. The host may choose a stricter landing policy before applying edits.
pub fn plan_rope_landing(
    controller: Pos,
    offset: u32,
    controller_removed: bool,
    mut read: impl FnMut(Pos) -> LandingCell,
) -> Result<Vec<RopeEdit>, CaptureError> {
    if controller_removed || offset == 0 {
        return Ok(Vec::new());
    }
    let mut edits = Vec::new();
    let mut rope = Vec::new();
    for (distance, part) in [(offset, Part::Magnet)]
        .into_iter()
        .chain((1..offset).map(|distance| (distance, Part::Rope)))
    {
        let position = below(controller, distance)?;
        let (collision_empty, source_water) = match read(position) {
            LandingCell::Present {
                breakable: false, ..
            } => continue,
            LandingCell::Present {
                collision_empty,
                source_water,
                ..
            } => (collision_empty, source_water),
            LandingCell::Unloaded => return Err(CaptureError::Unloaded(position)),
            LandingCell::OutsideWorld => return Err(CaptureError::Unsupported(position)),
        };
        edits.push(RopeEdit::Destroy {
            position,
            drops: collision_empty,
        });
        let place = RopeEdit::Place {
            position,
            segment: Segment {
                part,
                waterlogged: source_water,
            },
        };
        if part == Part::Magnet {
            edits.push(place);
        } else {
            rope.push(place);
        }
    }
    edits.extend(rope);
    Ok(edits)
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RopeBreak {
    /// Other segments to break, nearest above first, then nearest below.
    pub segments: Vec<Pos>,
    /// The pulley above this contiguous span resets its length to zero.
    pub reset_controller: Option<Pos>,
}

/// Call after an external removal of a segment, never while moving it or
/// while only changing its waterlogged state.
pub fn plan_rope_break(
    broken: Pos,
    limit: usize,
    mut read: impl FnMut(Pos) -> Cell,
) -> Result<RopeBreak, CaptureError> {
    let mut result = RopeBreak::default();
    for direction in [1, -1] {
        let mut position = broken;
        loop {
            position = shift_y(position, direction)?;
            match read(position) {
                Cell::Rope(_) if result.segments.len() == limit => {
                    return Err(CaptureError::TooLarge { limit });
                }
                Cell::Rope(_) => result.segments.push(position),
                Cell::Unloaded => return Err(CaptureError::Unloaded(position)),
                Cell::Pulley if direction == 1 => {
                    result.reset_controller = Some(position);
                    break;
                }
                Cell::Other | Cell::Pulley => break,
            }
        }
    }
    Ok(result)
}

fn shift_y([x, y, z]: Pos, delta: i64) -> Result<Pos, CaptureError> {
    let y = i32::try_from(i64::from(y) + delta).map_err(|_| CaptureError::CoordinateOverflow)?;
    Ok([x, y, z])
}

fn below(position: Pos, distance: u32) -> Result<Pos, CaptureError> {
    shift_y(position, -i64::from(distance))
}

#[cfg(test)]
mod tests {
    use super::*;

    const TOP: Pos = [10, 12, -2];
    const ROPE: Segment = Segment {
        part: Part::Rope,
        waterlogged: false,
    };
    const MAGNET: Segment = Segment {
        part: Part::Magnet,
        waterlogged: true,
    };

    #[test]
    fn scan_preserves_a_waterlogged_magnet_and_the_fixed_rope_column() {
        let layout = Layout::scan(TOP, -64, DEFAULT_MAX_ROPE_LENGTH, |[_, y, _]| match y {
            11 => Cell::Rope(ROPE),
            10 => Cell::Rope(MAGNET),
            _ => Cell::Other,
        })
        .unwrap();
        assert_eq!(layout.initial_offset, 2);
        assert_eq!(layout.extension_range, 75);
        assert_eq!(
            layout.remove,
            [([10, 10, -2], MAGNET), ([10, 11, -2], ROPE)]
        );
        assert_eq!(layout.anchor(), Ok([10, 9, -2]));
        assert!(layout.anchors(TOP));
        assert!(layout.anchors([10, 10, -2]));
        assert!(!layout.anchors([10, 9, -2]));
        assert!(!layout.anchors([9, 10, -2]));
        assert_eq!(
            layout.assembly_probe(32.0),
            Some(Probe {
                anchor: [10, 8, -2],
                direction: Direction::Down
            })
        );
        assert_eq!(
            layout.assembly_probe(-32.0),
            Some(Probe {
                anchor: [10, 10, -2],
                direction: Direction::Up
            })
        );
    }

    #[test]
    fn scan_respects_config_world_floor_and_unloaded_cells() {
        let layout = Layout::scan(TOP, -2000, DEFAULT_MAX_ROPE_LENGTH, |_| Cell::Other).unwrap();
        assert_eq!(layout.extension_range, DEFAULT_MAX_ROPE_LENGTH);
        assert!(layout.start(32.0, true, false).is_some());
        assert!(layout.start(-32.0, true, false).is_none());
        assert!(layout.start(32.0, false, false).is_none());
        assert_eq!(
            Layout::scan(TOP, -64, 5, |_| Cell::Unloaded),
            Err(CaptureError::Unloaded([10, 11, -2]))
        );
        let floor = Layout::scan(TOP, 11, 50, |_| Cell::Other).unwrap();
        assert_eq!(floor.extension_range, 0);
        assert!(floor.start(32.0, true, false).is_none());
    }

    #[test]
    fn restored_rope_has_magnet_first_then_two_ordered_rope_passes() {
        let plan = plan_rope_landing(TOP, 4, false, |[_, y, _]| LandingCell::Present {
            breakable: y != 10,
            collision_empty: y != 8,
            source_water: y <= 9,
        })
        .unwrap();
        assert_eq!(
            plan,
            [
                RopeEdit::Destroy {
                    position: [10, 8, -2],
                    drops: false
                },
                RopeEdit::Place {
                    position: [10, 8, -2],
                    segment: MAGNET
                },
                RopeEdit::Destroy {
                    position: [10, 11, -2],
                    drops: true
                },
                RopeEdit::Destroy {
                    position: [10, 9, -2],
                    drops: true
                },
                RopeEdit::Place {
                    position: [10, 11, -2],
                    segment: ROPE
                },
                RopeEdit::Place {
                    position: [10, 9, -2],
                    segment: Segment {
                        waterlogged: true,
                        ..ROPE
                    }
                },
            ]
        );
        assert!(
            plan_rope_landing(TOP, 4, true, |_| unreachable!())
                .unwrap()
                .is_empty()
        );
        assert_eq!(
            plan_rope_landing(TOP, 4, false, |_| LandingCell::Unloaded),
            Err(CaptureError::Unloaded([10, 8, -2]))
        );
    }

    #[test]
    fn a_lowering_empty_line_lands_and_retries_when_it_catches_payload() {
        let layout = Layout::scan(TOP, 1, 16, |_| Cell::Other).unwrap();
        let mut drive = layout.start(128.0, true, false).unwrap();
        for _ in 0..3 {
            assert_eq!(
                drive.tick(
                    TOP,
                    128.0,
                    Mode::NeverPlace,
                    false,
                    |_| unreachable!(),
                    |_| unreachable!()
                ),
                Action::Move {
                    crossed_cell: false,
                    sequence_locked: false
                }
            );
        }
        assert_eq!(
            drive.tick(
                TOP,
                128.0,
                Mode::NeverPlace,
                false,
                |_| unreachable!(),
                |position| {
                    assert_eq!(position, [10, 10, -2]);
                    true
                }
            ),
            Action::Place {
                grid_offset: 1,
                retry_extension: true
            }
        );
    }

    #[test]
    fn pulley_probes_a_full_final_step_and_does_not_retry_after_a_collision() {
        let mut drive = Drive {
            actuator: LinearActuator::resume(0, 4, 3.9, false, None).unwrap(),
            has_payload: true,
        };
        let action = drive.tick(
            TOP,
            256.0,
            Mode::Place,
            false,
            |probe| {
                assert_eq!(
                    probe,
                    Probe {
                        anchor: [10, 6, -2],
                        direction: Direction::Down
                    }
                );
                true
            },
            |_| unreachable!(),
        );
        assert_eq!(
            action,
            Action::Place {
                grid_offset: 4,
                retry_extension: false
            }
        );
        assert_eq!(directional_speed(-256.0), -0.49);
        assert_eq!(position_at(TOP, 1.5), [10.0, 9.5, -2.0]);
    }

    #[test]
    fn a_broken_rope_trims_only_its_contiguous_run_and_resets_its_controller() {
        let result = plan_rope_break([10, 10, -2], 8, |[_, y, _]| match y {
            12 => Cell::Pulley,
            11 | 9 | 8 => Cell::Rope(ROPE),
            6 => Cell::Rope(MAGNET),
            _ => Cell::Other,
        })
        .unwrap();
        assert_eq!(
            result,
            RopeBreak {
                segments: vec![[10, 11, -2], [10, 9, -2], [10, 8, -2]],
                reset_controller: Some(TOP),
            }
        );
        assert_eq!(
            plan_rope_break(TOP, 2, |_| Cell::Rope(ROPE)),
            Err(CaptureError::TooLarge { limit: 2 })
        );
    }
}
