// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! MechanicalPistonBlockEntity and PistonContraption geometry and assembly.
//! The world adapter classifies cells and owns the move's block snapshots.

use super::{BlockRules, CaptureError};
use crate::{
    kinetics::{Axis, Pos},
    placement::Direction,
};

pub const MAX_POLES: u32 = 64;
pub const MAX_CHASSIS_RANGE: u32 = 16;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Part {
    Pole { waterlogged: bool },
    Head { sticky: bool, waterlogged: bool },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Cell {
    Empty,
    OutsideWorld,
    Unloaded,
    Extension {
        facing: Direction,
        part: Part,
    },
    Block {
        rules: BlockRules,
        wool_carpet: bool,
    },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PlanError {
    Capture(CaptureError),
    NoPoles,
    TooManyPoles,
}

impl From<CaptureError> for PlanError {
    fn from(error: CaptureError) -> Self {
        Self::Capture(error)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct MovingPart {
    pub local: Pos,
    pub part: Part,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Layout {
    pub base: Pos,
    pub anchor: Pos,
    pub facing: Direction,
    pub sticky: bool,
    pub initial_offset: u32,
    pub extension_length: u32,
    pub parts: Vec<MovingPart>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Placement {
    World { pos: Pos, part: Part },
    Base { retracted: bool },
}

impl Layout {
    /// Collect the contiguous front train (extended bases only) and the
    /// aligned rear poles. A head, when present, counts as one front block.
    pub fn scan(
        base: Pos,
        facing: Direction,
        sticky: bool,
        extended: bool,
        max_poles: u32,
        mut cell: impl FnMut(Pos) -> Cell,
    ) -> Result<Self, PlanError> {
        let anchor = advance(base, facing, 1)?;
        let mut parts = Vec::new();
        let mut front = 0;
        if extended {
            loop {
                let pos = advance(base, facing, i64::from(front) + 1)?;
                let Some(part) = extension(cell(pos), pos, facing, true)? else {
                    break;
                };
                front += 1;
                if front > max_poles {
                    return Err(PlanError::TooManyPoles);
                }
                parts.push((i64::from(front), part));
                if matches!(part, Part::Head { .. }) {
                    break;
                }
            }
        }

        let base_part = if front == 0 {
            Part::Head {
                sticky,
                waterlogged: false,
            }
        } else {
            Part::Pole { waterlogged: false }
        };
        parts.push((0, base_part));

        let mut rear = 0;
        loop {
            let pos = advance(base, facing, -i64::from(rear) - 1)?;
            let Some(part) = extension(cell(pos), pos, facing, false)? else {
                break;
            };
            rear += 1;
            if rear > max_poles - front {
                return Err(PlanError::TooManyPoles);
            }
            parts.push((-i64::from(rear), part));
        }
        let extension_length = front + rear;
        if extension_length == 0 {
            return Err(PlanError::NoPoles);
        }

        let parts = parts
            .into_iter()
            .map(|(from_base, part)| {
                Ok(MovingPart {
                    local: advance([0; 3], facing, from_base - i64::from(front) - 1)?,
                    part,
                })
            })
            .collect::<Result<Vec<_>, CaptureError>>()?;
        Ok(Self {
            base,
            anchor,
            facing,
            sticky,
            initial_offset: front,
            extension_length,
            parts,
        })
    }

    pub fn can_start(&self, directional_speed: f32) -> bool {
        let direction = if directional_speed > 0.0 {
            0.5
        } else if directional_speed < 0.0 {
            -0.5
        } else {
            return false;
        };
        let next = self.initial_offset as f32 + direction;
        next > 0.0 && next < self.extension_length as f32
    }

    /// All cells in the pole corridor must be excluded when following glue
    /// and adjacent blocks from the seed payload.
    pub fn anchors(&self, pos: Pos) -> bool {
        let vector = self.facing.vector();
        let mut distance = 0;
        for index in 0..3 {
            let delta = i64::from(pos[index]) - i64::from(self.base[index]);
            if vector[index] == 0 {
                if delta != 0 {
                    return false;
                }
            } else {
                distance = delta * i64::from(vector[index]);
            }
        }
        (-i64::from(self.extension_length)..=0).contains(&distance)
    }

    /// World cells for the initial payload queue. A non-sticky piston
    /// retracts its pole train alone. A sticky piston can seed just one block
    /// and then follow the normal contraption attachment rules from it.
    pub fn payload_frontier(
        &self,
        retracting: bool,
        chassis_range: u32,
        mut cell: impl FnMut(Pos) -> Cell,
    ) -> Result<Vec<Pos>, CaptureError> {
        if retracting && !self.sticky {
            return Ok(Vec::new());
        }
        let movement = if retracting {
            self.facing.opposite()
        } else {
            self.facing
        };
        let mut seeds = Vec::new();
        let range = if retracting { 0 } else { chassis_range };
        for reach in 0..=range {
            let pos = advance(
                self.anchor,
                self.facing,
                i64::from(self.initial_offset) + i64::from(reach),
            )?;
            let rules = match cell(pos) {
                Cell::Empty | Cell::OutsideWorld => break,
                Cell::Unloaded => return Err(CaptureError::Unloaded(pos)),
                Cell::Extension {
                    facing,
                    part: Part::Head { .. },
                } if facing == movement.opposite() => break,
                Cell::Extension { .. } => BlockRules::default(),
                Cell::Block { rules, wool_carpet } => {
                    if rules.brittle && !wool_carpet {
                        break;
                    }
                    rules
                }
            };
            if !rules.movable {
                if retracting {
                    break;
                }
                return Err(CaptureError::Immovable(pos));
            }
            if retracting && rules.push_only {
                break;
            }
            seeds.push(pos);
            if rules.unsupported_faces[self.facing as usize] {
                break;
            }
        }
        Ok(seeds)
    }

    pub fn world_cell(&self, local: Pos, grid_offset: u32) -> Result<Pos, CaptureError> {
        let origin = advance(self.anchor, self.facing, i64::from(grid_offset))?;
        let [x, y, z] = std::array::from_fn(|i| origin[i].checked_add(local[i]));
        Ok([
            x.ok_or(CaptureError::CoordinateOverflow)?,
            y.ok_or(CaptureError::CoordinateOverflow)?,
            z.ok_or(CaptureError::CoordinateOverflow)?,
        ])
    }

    /// Shift a payload's source position into its stable local frame.
    pub fn payload_local(&self, world: Pos) -> Result<Pos, CaptureError> {
        let origin = advance(self.anchor, self.facing, i64::from(self.initial_offset))?;
        let [x, y, z] = std::array::from_fn(|i| world[i].checked_sub(origin[i]));
        Ok([
            x.ok_or(CaptureError::CoordinateOverflow)?,
            y.ok_or(CaptureError::CoordinateOverflow)?,
            z.ok_or(CaptureError::CoordinateOverflow)?,
        ])
    }

    pub fn origin(&self, offset: f32) -> [f64; 3] {
        let axis = self.facing.vector();
        std::array::from_fn(|i| f64::from(self.anchor[i]) + f64::from(axis[i]) * f64::from(offset))
    }

    /// The leading terrain test in ContraptionCollider.collideBlocks floors
    /// the entity's translated origin, then advances only positive world axes.
    pub fn collision_anchor(&self, offset: f32, movement: Direction) -> Result<Pos, CaptureError> {
        let origin = self.origin(offset).map(f64::floor);
        let delta = movement.vector().map(|value| value.max(0));
        let [x, y, z] = std::array::from_fn(|i| {
            let coord = origin[i] + f64::from(delta[i]);
            (f64::from(i32::MIN)..=f64::from(i32::MAX))
                .contains(&coord)
                .then_some(coord as i32)
        });
        Ok([
            x.ok_or(CaptureError::CoordinateOverflow)?,
            y.ok_or(CaptureError::CoordinateOverflow)?,
            z.ok_or(CaptureError::CoordinateOverflow)?,
        ])
    }

    pub fn parts_at(&self, grid_offset: u32) -> Result<Vec<Placement>, CaptureError> {
        self.parts
            .iter()
            .map(|entry| {
                let pos = self.world_cell(entry.local, grid_offset)?;
                Ok(if pos == self.base {
                    Placement::Base {
                        retracted: matches!(entry.part, Part::Head { .. }),
                    }
                } else {
                    Placement::World {
                        pos,
                        part: entry.part,
                    }
                })
            })
            .collect()
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LineCell {
    Base(Direction),
    Pole(Axis),
    Head(Direction),
    Other,
}

#[derive(Default, Debug, PartialEq, Eq)]
pub struct PartBreak {
    pub remove: Vec<Pos>,
    pub retract: Option<Pos>,
    pub reset_offset: bool,
}

/// Physical parts broken by a player outside a moving stroke. The broken
/// block itself is left to the normal player mining path.
pub fn break_parts(broken: Pos, max_poles: u32, cell: impl Fn(Pos) -> LineCell) -> PartBreak {
    let scan = |direction: Direction| {
        let mut poles = Vec::new();
        for offset in 1..max_poles {
            let Ok(at) = advance(broken, direction, i64::from(offset)) else {
                break;
            };
            let found = cell(at);
            if found == LineCell::Pole(direction.axis()) {
                poles.push(at);
            } else {
                return (poles, Some((at, found)));
            }
        }
        (poles, None)
    };
    match cell(broken) {
        LineCell::Base(facing) => {
            let (mut front, end) = scan(facing);
            if let Some((head, LineCell::Head(direction))) = end
                && direction == facing
            {
                front.push(head);
                front.sort_unstable();
            } else {
                front.clear();
            }
            front.extend(scan(facing.opposite()).0);
            PartBreak {
                remove: front,
                ..PartBreak::default()
            }
        }
        LineCell::Head(facing) => {
            let (mut remove, end) = scan(facing.opposite());
            if let Some((base, LineCell::Base(direction))) = end
                && direction == facing
            {
                remove.sort_unstable();
                PartBreak {
                    remove,
                    retract: Some(base),
                    reset_offset: false,
                }
            } else {
                PartBreak::default()
            }
        }
        LineCell::Pole(axis) => {
            let direction = match axis {
                Axis::X => Direction::East,
                Axis::Y => Direction::Up,
                Axis::Z => Direction::South,
            };
            let (mut positive, pos) = scan(direction);
            let (negative, neg) = scan(direction.opposite());
            let (base, head) = match (pos, neg) {
                (Some((base, LineCell::Base(facing))), Some((head, LineCell::Head(heading))))
                | (Some((head, LineCell::Head(heading))), Some((base, LineCell::Base(facing))))
                    if facing == heading =>
                {
                    (base, head)
                }
                _ => return PartBreak::default(),
            };
            positive.extend(negative);
            positive.push(head);
            positive.sort_unstable();
            PartBreak {
                remove: positive,
                retract: Some(base),
                reset_offset: true,
            }
        }
        LineCell::Other => PartBreak::default(),
    }
}

/// MechanicalPistonBlockEntity.getMovementSpeed before stroke/sequence clamps.
pub fn directional_speed(rpm: f32, facing: Direction) -> f32 {
    let sign = facing.vector().into_iter().sum::<i32>() as f32;
    let axis_sign = if facing.axis() == Axis::Z { -1.0 } else { 1.0 };
    (rpm / 512.0).clamp(-0.49, 0.49) * -sign * axis_sign
}

fn extension(
    cell: Cell,
    pos: Pos,
    facing: Direction,
    accept_head: bool,
) -> Result<Option<Part>, CaptureError> {
    match cell {
        Cell::Unloaded => Err(CaptureError::Unloaded(pos)),
        Cell::Extension {
            facing: direction,
            part: part @ Part::Pole { .. },
        } if direction.axis() == facing.axis() => Ok(Some(part)),
        Cell::Extension {
            facing: direction,
            part: part @ Part::Head { .. },
        } if accept_head && direction == facing => Ok(Some(part)),
        _ => Ok(None),
    }
}

fn advance(pos: Pos, direction: Direction, distance: i64) -> Result<Pos, CaptureError> {
    let delta = direction.vector();
    let [x, y, z] = std::array::from_fn(|i| {
        i32::try_from(i64::from(pos[i]) + i64::from(delta[i]) * distance)
            .map_err(|_| CaptureError::CoordinateOverflow)
    });
    Ok([x?, y?, z?])
}

#[cfg(test)]
mod tests {
    use super::{Cell, Layout, Part, Placement, PlanError, directional_speed};
    use crate::contraption::{BlockRules, CaptureError};
    use crate::placement::Direction::{Down, East, North, South, Up, West};

    const POLE: Part = Part::Pole { waterlogged: true };
    const HEAD: Part = Part::Head {
        sticky: true,
        waterlogged: false,
    };

    fn block(rules: BlockRules) -> Cell {
        Cell::Block {
            rules,
            wool_carpet: false,
        }
    }

    #[test]
    fn breaking_the_train_only_removes_the_associated_parts() {
        use super::{LineCell, PartBreak, break_parts};
        use crate::kinetics::Axis;
        let base = [0, 4, 0];
        let front = [1, 4, 0];
        let head = [2, 4, 0];
        let rear = [-1, 4, 0];
        let read = |at| match at {
            p if p == base => LineCell::Base(East),
            p if p == head => LineCell::Head(East),
            p if p == front || p == rear => LineCell::Pole(Axis::X),
            _ => LineCell::Other,
        };
        assert_eq!(break_parts(base, 64, read).remove, [front, head, rear]);
        assert_eq!(
            break_parts(front, 64, read),
            PartBreak {
                remove: vec![head],
                retract: Some(base),
                reset_offset: true,
            }
        );
        assert_eq!(
            break_parts(head, 64, read),
            PartBreak {
                remove: vec![front],
                retract: Some(base),
                reset_offset: false,
            }
        );
        assert_eq!(break_parts(rear, 64, read), PartBreak::default());
    }

    #[test]
    fn rear_poles_provide_the_stroke_and_the_head_replaces_no_base() {
        let plan = Layout::scan([0; 3], East, true, false, 64, |[x, _, _]| match x {
            -2 | -1 => Cell::Extension {
                facing: West,
                part: POLE,
            },
            _ => Cell::Empty,
        })
        .unwrap();
        assert_eq!(
            (plan.anchor, plan.initial_offset, plan.extension_length),
            ([1, 0, 0], 0, 2)
        );
        assert!(plan.can_start(0.125));
        assert!(!plan.can_start(-0.125));
        assert_eq!(
            plan.parts_at(0).unwrap(),
            vec![
                Placement::Base { retracted: true },
                Placement::World {
                    pos: [-1, 0, 0],
                    part: POLE
                },
                Placement::World {
                    pos: [-2, 0, 0],
                    part: POLE
                },
            ]
        );
        assert_eq!(
            plan.parts_at(2).unwrap(),
            vec![
                Placement::World {
                    pos: [2, 0, 0],
                    part: HEAD
                },
                Placement::World {
                    pos: [1, 0, 0],
                    part: POLE
                },
                Placement::Base { retracted: false },
            ]
        );
        assert!(plan.anchors([-2, 0, 0]));
        assert!(!plan.anchors([-2, 1, 0]));
        assert!(!plan.anchors([1, 0, 0]));
    }

    #[test]
    fn front_head_counts_and_sticky_retraction_only_seeds_the_first_block() {
        let train = |[x, _, _]: [i32; 3]| match x {
            1 => Cell::Extension {
                facing: West,
                part: POLE,
            },
            2 => Cell::Extension {
                facing: East,
                part: HEAD,
            },
            -1 => Cell::Extension {
                facing: East,
                part: POLE,
            },
            _ => Cell::Empty,
        };
        let sticky = Layout::scan([0; 3], East, true, true, 64, train).unwrap();
        let plain = Layout::scan([0; 3], East, false, true, 64, train).unwrap();
        assert_eq!((sticky.initial_offset, sticky.extension_length), (2, 3));
        assert_eq!(
            sticky
                .payload_frontier(true, 16, |_| block(BlockRules::default()))
                .unwrap(),
            vec![[3, 0, 0]]
        );
        assert!(
            plain
                .payload_frontier(true, 16, |_| panic!(
                    "ordinary retraction has no payload query"
                ))
                .unwrap()
                .is_empty()
        );
        let push_only = BlockRules {
            push_only: true,
            ..BlockRules::default()
        };
        assert!(
            sticky
                .payload_frontier(true, 16, |_| block(push_only))
                .unwrap()
                .is_empty()
        );
        assert_eq!(sticky.payload_local([3, 0, 0]).unwrap(), [0; 3]);
        assert_eq!(sticky.world_cell([0; 3], 0).unwrap(), [1, 0, 0]);
    }

    #[test]
    fn assembly_respects_alignment_and_reports_loaded_limits() {
        let scan = |cell| Layout::scan([0; 3], Up, false, false, 1, cell);
        assert_eq!(
            scan(|_| Cell::Extension {
                facing: West,
                part: POLE
            }),
            Err(PlanError::NoPoles)
        );
        assert_eq!(
            Layout::scan([0; 3], Up, false, false, 1, |_| Cell::Extension {
                facing: Down,
                part: POLE
            }),
            Err(PlanError::TooManyPoles)
        );
        assert_eq!(
            Layout::scan([0; 3], Up, false, false, 1, |_| Cell::Unloaded),
            Err(PlanError::Capture(CaptureError::Unloaded([0, -1, 0])))
        );
    }

    #[test]
    fn push_frontier_stops_after_an_unsupportive_cell() {
        let plan = Layout::scan([0; 3], East, false, false, 64, |[x, _, _]| {
            if x == -1 {
                Cell::Extension {
                    facing: East,
                    part: POLE,
                }
            } else {
                Cell::Empty
            }
        })
        .unwrap();
        let mut wall = BlockRules::default();
        wall.unsupported_faces[East as usize] = true;
        assert_eq!(
            plan.payload_frontier(false, 16, |[x, _, _]| {
                match x {
                    1 => block(BlockRules::default()),
                    2 => block(wall),
                    _ => panic!("must not seed beyond the unsupported face"),
                }
            })
            .unwrap(),
            vec![[1, 0, 0], [2, 0, 0]]
        );
    }

    #[test]
    fn source_rpm_sign_is_inverted_only_on_x_and_y_axes() {
        for facing in [West, Down, South] {
            assert_eq!(directional_speed(64.0, facing), 0.125);
            assert_eq!(directional_speed(-256.0, facing), -0.49);
        }
        for facing in [East, Up, North] {
            assert_eq!(directional_speed(64.0, facing), -0.125);
            assert_eq!(directional_speed(-256.0, facing), 0.49);
        }
        let plan = Layout::scan([2, 0, 0], West, false, false, 64, |[x, _, _]| {
            if x == 3 {
                Cell::Extension {
                    facing: West,
                    part: POLE,
                }
            } else {
                Cell::Empty
            }
        })
        .unwrap();
        assert_eq!(plan.collision_anchor(0.125, West).unwrap(), [0, 0, 0]);
        assert_eq!(plan.collision_anchor(0.875, East).unwrap(), [1, 0, 0]);
    }
}
