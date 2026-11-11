// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! ChassisBlockEntity group and payload queries. The host supplies Create's
//! movement classification and owns capture, block entities and interactions.

use super::{BlockRules, CaptureError, Cell, QuarterTurn};
use crate::{
    kinetics::{Axis, Pos},
    placement::Direction,
};
use std::collections::{HashSet, VecDeque};

pub const DEFAULT_RANGE: u8 = 8;
pub const MAX_RANGE: u8 = 16;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    Linear,
    Secondary,
    Radial,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Chassis {
    pub kind: Kind,
    pub axis: Axis,
    range: u8,
    sticky: [bool; 6],
}

impl Chassis {
    pub fn new(kind: Kind, axis: Axis, range: u8) -> Option<Self> {
        (1..=MAX_RANGE).contains(&range).then_some(Self {
            kind,
            axis,
            range,
            sticky: [false; 6],
        })
    }

    pub fn range(self) -> u8 {
        self.range
    }

    pub fn sticky(self, face: Direction) -> bool {
        self.sticky[face as usize]
    }

    /// The canonical state property belongs to a face in the chassis's
    /// reference orientation, which may differ from its world direction.
    pub fn sticky_property(self, face: Direction) -> Option<&'static str> {
        use Direction::{Down, East, North, South, Up, West};
        if self.kind != Kind::Radial {
            return (face.axis() == self.axis).then_some(match face {
                Up | South | East => "sticky_top",
                Down | North | West => "sticky_bottom",
            });
        }
        match (self.axis, face) {
            (Axis::X, Up) | (Axis::Y, North) | (Axis::Z, Up) => Some("sticky_north"),
            (Axis::X, Down) | (Axis::Y, South) | (Axis::Z, Down) => Some("sticky_south"),
            (Axis::X, South) | (Axis::Y | Axis::Z, East) => Some("sticky_east"),
            (Axis::X, North) | (Axis::Y | Axis::Z, West) => Some("sticky_west"),
            _ => None,
        }
    }

    pub fn with_sticky(mut self, face: Direction, sticky: bool) -> Option<Self> {
        self.sticky_property(face)?;
        self.sticky[face as usize] = sticky;
        Some(self)
    }

    /// Linear groups accept every adjacent face but do not cross the two
    /// chassis variants. Radial groups connect only along their common axis.
    pub fn joins(self, other: Self, face: Direction) -> bool {
        self.kind == other.kind
            && self.axis == other.axis
            && (self.kind != Kind::Radial || self.axis == face.axis())
    }

    pub fn rotated(self, turn: QuarterTurn) -> Self {
        let mut rotated = Self {
            axis: turn.axis(self.axis),
            sticky: [false; 6],
            ..self
        };
        for face in Direction::ALL {
            rotated.sticky[turn.facing(face) as usize] = self.sticky(face);
        }
        rotated
    }

    /// The selected payload precedes the ordinary attached/glued expansion.
    /// A radial face has its own flood, so overlapping faces can repeat a cell
    /// in this list. The assembly frontier deduplicates those positions.
    pub fn included(
        self,
        origin: Pos,
        forced: Option<Direction>,
        mut inspect: impl FnMut(Pos) -> Cell,
    ) -> Result<Vec<Pos>, CaptureError> {
        let mut positions = Vec::new();
        if self.kind != Kind::Radial {
            let positive = match self.axis {
                Axis::X => Direction::East,
                Axis::Y => Direction::Up,
                Axis::Z => Direction::South,
            };
            for face in [positive, positive.opposite()] {
                if forced != Some(face) && !self.sticky(face) {
                    continue;
                }
                for distance in 1..=self.range {
                    let pos = offset(origin, face, distance)?;
                    let Some(rules) = payload(pos, &mut inspect)? else {
                        break;
                    };
                    positions.push(pos);
                    if rules.unsupported_faces[face as usize] {
                        break;
                    }
                }
            }
            return Ok(positions);
        }

        let in_plane = Direction::ALL
            .into_iter()
            .filter(|face| face.axis() != self.axis);
        for face in in_plane.clone().filter(|&face| self.sticky(face)) {
            let mut frontier = VecDeque::from([offset(origin, face, 1)?]);
            let mut visited = HashSet::new();
            while let Some(pos) = frontier.pop_front() {
                if visited.contains(&pos) || !in_radius(origin, pos, self.range) {
                    continue;
                }
                let Some(rules) = payload(pos, &mut inspect)? else {
                    continue;
                };
                visited.insert(pos);
                if pos != origin {
                    positions.push(pos);
                }
                for direction in in_plane.clone() {
                    if (pos != origin || direction == face)
                        && !rules.unsupported_faces[direction as usize]
                    {
                        frontier.push_back(offset(pos, direction, 1)?);
                    }
                }
            }
        }
        Ok(positions)
    }
}

fn offset(pos: Pos, face: Direction, distance: u8) -> Result<Pos, CaptureError> {
    let vector = face.vector();
    let add = |axis: usize| {
        pos[axis]
            .checked_add(vector[axis] * i32::from(distance))
            .ok_or(CaptureError::CoordinateOverflow)
    };
    Ok([add(0)?, add(1)?, add(2)?])
}

fn payload(
    pos: Pos,
    inspect: &mut impl FnMut(Pos) -> Cell,
) -> Result<Option<BlockRules>, CaptureError> {
    match inspect(pos) {
        Cell::Block(rules) if !rules.brittle => Ok(Some(rules)),
        Cell::Unloaded => Err(CaptureError::Unloaded(pos)),
        _ => Ok(None),
    }
}

fn in_radius(origin: Pos, pos: Pos, range: u8) -> bool {
    let distance_squared: i64 = origin
        .into_iter()
        .zip(pos)
        .map(|(a, b)| i64::from(a) - i64::from(b))
        .map(|delta| delta * delta)
        .sum();
    // Java BlockPos.closerThan checks strictly less than (range + 0.5)^2.
    let doubled_radius = 2 * i64::from(range) + 1;
    4 * distance_squared < doubled_radius * doubled_radius
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contraption::Rotation;
    use Direction::*;

    fn chassis(kind: Kind, axis: Axis, range: u8) -> Chassis {
        Chassis::new(kind, axis, range).unwrap()
    }

    fn block() -> Cell {
        Cell::Block(BlockRules::default())
    }

    #[test]
    fn variant_and_axis_define_the_group() {
        let primary = chassis(Kind::Linear, Axis::Y, DEFAULT_RANGE);
        let secondary = chassis(Kind::Secondary, Axis::Y, 2);
        let radial = chassis(Kind::Radial, Axis::Y, 16);
        assert!(primary.joins(primary, East));
        assert!(!primary.joins(secondary, East));
        assert!(!primary.joins(chassis(Kind::Linear, Axis::Z, 2), Up));
        assert!(radial.joins(radial, Up));
        assert!(!radial.joins(radial, East));
        assert_eq!(primary.range(), 8);
        assert!(Chassis::new(Kind::Radial, Axis::Y, 0).is_none());
        assert!(Chassis::new(Kind::Radial, Axis::Y, 17).is_none());
    }

    #[test]
    fn rotation_preserves_the_world_face_and_reassigns_its_property() {
        let radial = chassis(Kind::Radial, Axis::Y, 8)
            .with_sticky(North, true)
            .unwrap();
        let turn = Rotation::new([0; 3], Axis::Z, 90.0).unwrap().snapped();
        let rotated = radial.rotated(turn);
        assert_eq!(rotated.axis, Axis::X);
        assert!(rotated.sticky(North));
        assert_eq!(rotated.sticky_property(North), Some("sticky_west"));
        assert_eq!(rotated.sticky_property(Up), Some("sticky_north"));
        assert_eq!(rotated.sticky_property(East), None);
        assert!(radial.with_sticky(Up, true).is_none());
        let linear = chassis(Kind::Secondary, Axis::X, 3)
            .with_sticky(East, true)
            .unwrap();
        let turn = Rotation::new([0; 3], Axis::Y, 180.0).unwrap().snapped();
        let rotated = linear.rotated(turn);
        assert!(rotated.sticky(West));
        assert_eq!(rotated.sticky_property(West), Some("sticky_bottom"));
    }

    #[test]
    fn linear_can_push_unstuck_front_but_stops_at_brittle_or_unsupported_blocks() {
        let state = chassis(Kind::Linear, Axis::X, 4)
            .with_sticky(West, true)
            .unwrap();
        let inspect = |[x, _, _]: Pos| match x {
            1 | -1 | 3 | -3 => block(),
            2 => {
                let mut rules = BlockRules::default();
                rules.unsupported_faces[East as usize] = true;
                Cell::Block(rules)
            }
            -2 => Cell::Block(BlockRules {
                brittle: true,
                ..BlockRules::default()
            }),
            _ => Cell::Empty,
        };
        assert_eq!(
            state.included([0; 3], None, inspect).unwrap(),
            vec![[-1, 0, 0]]
        );
        assert_eq!(
            state.included([0; 3], Some(East), inspect).unwrap(),
            vec![[1, 0, 0], [2, 0, 0], [-1, 0, 0]]
        );
    }

    #[test]
    fn radial_follows_a_connected_path_with_a_strict_radius_in_its_plane() {
        let state = chassis(Kind::Radial, Axis::Y, 2)
            .with_sticky(East, true)
            .unwrap();
        let inspect = |pos: Pos| match pos {
            [0, 0, 0] | [1, 0, 0] | [2, 0, 0] | [2, 0, 1] | [2, 0, 2] | [1, 1, 0] | [-1, 0, 0] => {
                block()
            }
            _ => Cell::Empty,
        };
        assert_eq!(
            state.included([0; 3], Some(West), inspect).unwrap(),
            vec![[1, 0, 0], [2, 0, 0], [2, 0, 1]]
        );
    }

    #[test]
    fn unavailable_payload_cells_fail_closed() {
        let state = chassis(Kind::Linear, Axis::Y, 1)
            .with_sticky(Up, true)
            .unwrap();
        assert_eq!(
            state.included([0; 3], None, |_| Cell::Unloaded),
            Err(CaptureError::Unloaded([0, 1, 0]))
        );
        assert_eq!(
            state.included([0, i32::MAX, 0], None, |_| block()),
            Err(CaptureError::CoordinateOverflow)
        );
    }
}
