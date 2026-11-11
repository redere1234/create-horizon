// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! GantryShaftBlock, GantryCarriageBlock and GantryContraptionEntity movement rules.

use crate::{
    kinetics::{Axis, Pos},
    placement::Direction,
};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Part {
    Start,
    Middle,
    End,
    Single,
}

impl Part {
    /// Update the one connection affected by `GantryShaftBlock.updateShape`.
    pub fn neighbor_changed(
        self,
        facing: Direction,
        neighbor: Direction,
        neighbor_shaft: Option<Direction>,
    ) -> Self {
        let mut front = matches!(self, Self::Start | Self::Middle);
        let mut back = matches!(self, Self::End | Self::Middle);
        let connected = neighbor_shaft == Some(facing);
        if neighbor == facing {
            front = connected;
        } else if neighbor == facing.opposite() {
            back = connected;
        }
        match (front, back) {
            (true, true) => Self::Middle,
            (true, false) => Self::Start,
            (false, true) => Self::End,
            (false, false) => Self::Single,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Shaft {
    pub facing: Direction,
    pub part: Part,
    pub powered: bool,
    pub rpm: f32,
}

impl Shaft {
    pub fn pinion_speed(self) -> f32 {
        if !self.rpm.is_finite() {
            return 0.0;
        }
        (-self.rpm / 512.0).clamp(-0.49, 0.49)
    }

    pub fn can_assemble(self) -> bool {
        !self.powered
            && match self.part {
                Part::Start => self.pinion_speed() > 0.0,
                Part::Middle => self.pinion_speed() != 0.0,
                Part::End => self.pinion_speed() < 0.0,
                Part::Single => false,
            }
    }

    pub fn assembly_direction(self, carriage_facing: Direction) -> Option<Direction> {
        pinion_axis(carriage_facing, self.facing)?;
        self.can_assemble().then(|| {
            if self.pinion_speed() < 0.0 {
                self.facing.opposite()
            } else {
                self.facing
            }
        })
    }

    /// A powered shaft transfers rotation through its carriage instead of
    /// assembling it. The reciprocal ratio has the same sign and magnitude.
    pub fn powered_pinion_ratio(self, carriage_facing: Direction) -> Option<f32> {
        if self.powered {
            pinion_ratio(self.facing, carriage_facing)
        } else {
            None
        }
    }
}

pub(crate) fn pinion_ratio(shaft: Direction, carriage: Direction) -> Option<f32> {
    pinion_axis(carriage, shaft)?;
    let axis = shaft.axis();
    let sign = shaft.vector()[axis.index()] as f32;
    let invert = matches!(
        (axis, carriage),
        (Axis::X, Direction::Down | Direction::South)
            | (Axis::Y, Direction::North | Direction::East)
            | (Axis::Z, Direction::Up | Direction::West)
    );
    Some(if invert { -sign } else { sign })
}

/// The carriage's output axis is perpendicular to its mounting face and rail.
pub fn pinion_axis(carriage_facing: Direction, shaft_facing: Direction) -> Option<Axis> {
    let facing = carriage_facing.axis();
    let rail = shaft_facing.axis();
    if facing == rail {
        return None;
    }
    [Axis::X, Axis::Y, Axis::Z]
        .into_iter()
        .find(|&axis| axis != facing && axis != rail)
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Action {
    Active {
        movement: [f64; 3],
        stop_actors: bool,
    },
    Place {
        anchor: Pos,
    },
}

/// Authoritative moving carriage. `axis_motion` is signed relative to the
/// current shaft's facing, and `anchor` is the lower corner of the carriage.
#[derive(Clone, Debug, PartialEq)]
pub struct GantryMotion {
    carriage_facing: Direction,
    anchor: [f64; 3],
    axis_motion: f32,
    sequence_left: Option<f64>,
}

impl GantryMotion {
    pub fn resume(
        carriage_facing: Direction,
        anchor: [f64; 3],
        axis_motion: f32,
        sequence_left: Option<f64>,
    ) -> Option<Self> {
        if anchor
            .iter()
            .any(|&value| !(f64::from(i32::MIN)..f64::from(i32::MAX)).contains(&(value + 0.5)))
            || !axis_motion.is_finite()
            || sequence_left.is_some_and(|left| !left.is_finite() || left < 0.0)
        {
            return None;
        }
        Some(Self {
            carriage_facing,
            anchor,
            axis_motion,
            sequence_left,
        })
    }

    pub fn anchor(&self) -> [f64; 3] {
        self.anchor
    }

    pub fn axis_motion(&self) -> f32 {
        self.axis_motion
    }

    pub fn sequence_left(&self) -> Option<f64> {
        self.sequence_left
    }

    /// Select the present rail using the centered carriage cell. An occupied
    /// terrain sweep requests placement at that cell without mutating the
    /// motion state, so the host can retry if placement cannot commit yet.
    pub fn tick(
        &mut self,
        entity_age: u32,
        stalled: bool,
        shaft_at: impl FnOnce(Pos) -> Option<Shaft>,
        collides: impl FnOnce([f64; 3], [f64; 3]) -> bool,
    ) -> Action {
        let center = self.anchor.map(|coordinate| coordinate + 0.5);
        let cell = center.map(|coordinate| coordinate.floor() as i32);
        let place = Action::Place { anchor: cell };
        let support_axis = self.carriage_facing.axis().index();
        let mut shaft_pos = cell;
        let Some(support) =
            cell[support_axis].checked_sub(self.carriage_facing.vector()[support_axis])
        else {
            return place;
        };
        shaft_pos[support_axis] = support;
        let Some(shaft) = shaft_at(shaft_pos) else {
            return place;
        };
        let speed = shaft.pinion_speed();
        if shaft.powered || speed == 0.0 {
            return place;
        }
        let speed = self
            .sequence_left
            .map_or(speed, |left| f64::from(speed).clamp(-left, left) as f32);
        let normal = shaft.facing.vector();
        let axis = shaft.facing.axis().index();
        let movement = normal.map(|component| f64::from(component) * f64::from(speed));
        let next = center[axis] + movement[axis];
        let positive_side = center[axis].floor() + 0.5 < next;
        let negative_movement = movement[axis] < 0.0;
        if positive_side != negative_movement && !shaft.can_assemble() {
            return place;
        }
        if speed != 0.0 && collides(self.anchor, movement) {
            return place;
        }
        let stop_actors = self.axis_motion != 0.0
            && (speed == 0.0 || self.axis_motion.is_sign_negative() != speed.is_sign_negative());
        self.axis_motion = speed;
        let applied = if stalled || entity_age <= 2 {
            [0.0; 3]
        } else {
            for (coordinate, delta) in self.anchor.iter_mut().zip(movement) {
                *coordinate += delta;
            }
            if let Some(left) = &mut self.sequence_left {
                *left = (*left - movement[axis].abs()).max(0.0);
            }
            movement
        };
        Action::Active {
            movement: applied,
            stop_actors,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use Direction::*;

    fn shaft(facing: Direction, part: Part, rpm: f32) -> Shaft {
        Shaft {
            facing,
            part,
            powered: false,
            rpm,
        }
    }

    fn motion(x: f64, sequence_left: Option<f64>) -> GantryMotion {
        GantryMotion::resume(Up, [x, 8.0, -4.0], 0.0, sequence_left).unwrap()
    }

    fn tick(carriage: &mut GantryMotion, rail: Shaft) -> Action {
        carriage.tick(3, false, |_| Some(rail), |_, _| false)
    }

    #[test]
    fn aligned_shaft_neighbors_build_and_remove_each_end() {
        let start = Part::Single.neighbor_changed(East, East, Some(East));
        assert_eq!(start, Part::Start);
        assert_eq!(start.neighbor_changed(East, West, Some(West)), Part::Start);
        assert_eq!(start.neighbor_changed(East, Up, Some(East)), Part::Start);
        let middle = start.neighbor_changed(East, West, Some(East));
        assert_eq!(middle, Part::Middle);
        assert_eq!(middle.neighbor_changed(East, West, None), Part::Start);
        let end = middle.neighbor_changed(East, East, None);
        assert_eq!(end, Part::End);
        assert_eq!(end.neighbor_changed(East, West, None), Part::Single);
    }

    #[test]
    fn speed_and_power_select_assembly_or_pinion_rotation() {
        let start = shaft(East, Part::Start, -256.0);
        assert_eq!(start.pinion_speed(), 0.49);
        assert_eq!(start.assembly_direction(Up), Some(East));
        assert_eq!(start.assembly_direction(West), None);
        assert_eq!(shaft(East, Part::Start, 8.0).assembly_direction(Up), None);
        assert_eq!(
            shaft(East, Part::End, 8.0).assembly_direction(Up),
            Some(West)
        );
        assert_eq!(shaft(East, Part::Single, -8.0).assembly_direction(Up), None);
        assert_eq!(shaft(East, Part::Middle, 0.0).assembly_direction(Up), None);
        assert_eq!(pinion_axis(Up, East), Some(Axis::Z));
        assert_eq!(start.powered_pinion_ratio(Up), None);
        for (facing, carriage, ratio) in [(East, Down, -1.0), (Up, West, 1.0), (North, Up, 1.0)] {
            let rail = Shaft {
                facing,
                powered: true,
                ..start
            };
            assert_eq!(rail.assembly_direction(carriage), None);
            assert_eq!(rail.powered_pinion_ratio(carriage), Some(ratio));
            assert_eq!(
                Shaft {
                    facing: facing.opposite(),
                    ..rail
                }
                .powered_pinion_ratio(carriage),
                Some(-ratio)
            );
        }
    }

    #[test]
    fn powered_pinion_connects_the_rail_to_its_normal_shaft_port() {
        use crate::kinetics::{Kind, Node, ratio, solve};
        let rail = |powered| Node {
            pos: [0, 0, 0],
            axis: Axis::X,
            kind: Kind::GantryShaft {
                facing: East,
                powered,
            },
        };
        let carriage = Node {
            pos: [0, 1, 0],
            axis: Axis::Z,
            kind: Kind::GantryCarriage { facing: Up },
        };
        let output = Node {
            pos: [0, 1, 1],
            axis: Axis::Z,
            kind: Kind::Shaft,
        };
        let source = Node {
            pos: [-1, 0, 0],
            axis: Axis::X,
            kind: Kind::Motor {
                facing: [1, 0, 0],
                rpm: -128.0,
                capacity: 16384.0,
            },
        };
        assert_eq!(ratio(rail(false), carriage), None);
        assert_eq!(ratio(carriage, rail(false)), None);
        assert_eq!(ratio(rail(true), carriage), Some(1.0));
        let track = [rail(true), carriage, output, source];
        let network = solve(source, |position| {
            track.iter().find(|node| node.pos == position).copied()
        });
        assert_eq!(network.speed(output.pos), -128.0);
    }

    #[test]
    fn rail_end_has_the_java_midpoint_asymmetry() {
        let mut eastbound = motion(0.875, None);
        let east_end = shaft(East, Part::End, -64.0);
        assert_eq!(
            tick(&mut eastbound, east_end),
            Action::Active {
                movement: [0.125, 0.0, 0.0],
                stop_actors: false
            }
        );
        assert_eq!(eastbound.anchor(), [1.0, 8.0, -4.0]);
        assert_eq!(
            tick(&mut eastbound, east_end),
            Action::Place { anchor: [1, 8, -4] }
        );

        let mut westbound = motion(0.125, None);
        let west_end = shaft(East, Part::Start, 64.0);
        assert_eq!(
            tick(&mut westbound, west_end),
            Action::Place { anchor: [0, 8, -4] }
        );
        assert_eq!(westbound.anchor(), [0.125, 8.0, -4.0]);
    }

    #[test]
    fn centered_anchor_selects_the_current_rail_and_placement_cell() {
        let mut carriage = motion(-0.6, None);
        let rail = shaft(East, Part::Middle, -128.0);
        assert_eq!(
            carriage.tick(
                3,
                false,
                |pos| {
                    assert_eq!(pos, [-1, 7, -4]);
                    Some(rail)
                },
                |_, _| false
            ),
            Action::Active {
                movement: [0.25, 0.0, 0.0],
                stop_actors: false
            }
        );
        assert_eq!(
            carriage.tick(
                4,
                false,
                |pos| {
                    assert_eq!(pos, [0, 7, -4]);
                    None
                },
                |_, _| false
            ),
            Action::Place { anchor: [0, 8, -4] }
        );
        assert_eq!(
            tick(
                &mut carriage,
                Shaft {
                    powered: true,
                    ..rail
                }
            ),
            Action::Place { anchor: [0, 8, -4] }
        );
        assert_eq!(
            tick(&mut carriage, Shaft { rpm: 0.0, ..rail }),
            Action::Place { anchor: [0, 8, -4] }
        );
    }

    #[test]
    fn terrain_probe_still_runs_during_startup_and_stall() {
        let rail = shaft(East, Part::Middle, -64.0);
        let mut carriage = motion(0.0, None);
        assert_eq!(
            carriage.tick(
                2,
                false,
                |_| Some(rail),
                |at, movement| {
                    assert_eq!(at, [0.0, 8.0, -4.0]);
                    assert_eq!(movement, [0.125, 0.0, 0.0]);
                    false
                }
            ),
            Action::Active {
                movement: [0.0; 3],
                stop_actors: false
            }
        );
        assert_eq!(
            carriage.tick(3, true, |_| Some(rail), |_, _| true),
            Action::Place { anchor: [0, 8, -4] }
        );
        assert_eq!(carriage.anchor(), [0.0, 8.0, -4.0]);
        assert_eq!(carriage.axis_motion(), 0.125);
    }

    #[test]
    fn sequence_limit_consumes_applied_distance_and_stops_actors() {
        let mut carriage = motion(0.0, Some(0.375));
        let east = shaft(East, Part::Middle, -128.0);
        let west = shaft(East, Part::Middle, 128.0);
        assert_eq!(
            tick(&mut carriage, east),
            Action::Active {
                movement: [0.25, 0.0, 0.0],
                stop_actors: false
            }
        );
        assert_eq!(carriage.sequence_left(), Some(0.125));
        assert_eq!(
            tick(&mut carriage, west),
            Action::Active {
                movement: [-0.125, 0.0, 0.0],
                stop_actors: true
            }
        );
        assert_eq!(carriage.sequence_left(), Some(0.0));
        assert_eq!(
            tick(&mut carriage, west),
            Action::Active {
                movement: [0.0; 3],
                stop_actors: true
            }
        );
        assert_eq!(carriage.anchor(), [0.125, 8.0, -4.0]);
    }

    #[test]
    fn motion_matches_the_pinned_java_three_shaft_fixture() {
        // Create 6.0.10, observed after each server tick by gantry_reference_checks.py.
        struct Case {
            rpm: f32,
            initial: f64,
            powered_at: Option<u32>,
            expected: &'static [f64],
            landed: i32,
        }
        let cases = [
            Case {
                rpm: -128.0,
                initial: 948.0,
                powered_at: None,
                expected: &[
                    948.0, 948.0, 948.0, 948.25, 948.5, 948.75, 949.0, 949.25, 949.5, 949.75, 950.0,
                ],
                landed: 950,
            },
            Case {
                rpm: 128.0,
                initial: 950.0,
                powered_at: None,
                expected: &[
                    950.0, 950.0, 950.0, 949.75, 949.5, 949.25, 949.0, 948.75, 948.5, 948.25,
                ],
                landed: 948,
            },
            Case {
                rpm: -128.0,
                initial: 948.0,
                powered_at: Some(5),
                expected: &[948.0, 948.0, 948.0, 948.25, 948.5],
                landed: 949,
            },
        ];
        for Case {
            rpm,
            initial,
            powered_at,
            expected,
            landed,
        } in cases
        {
            let mut carriage = motion(initial, None);
            let mut actual = vec![initial];
            let mut placed = None;
            for age in 1..=12 {
                match carriage.tick(
                    age,
                    false,
                    |[x, _, _]| {
                        let part = match x {
                            948 => Part::Start,
                            949 => Part::Middle,
                            950 => Part::End,
                            _ => return None,
                        };
                        Some(Shaft {
                            facing: East,
                            part,
                            powered: powered_at.is_some_and(|tick| age >= tick),
                            rpm,
                        })
                    },
                    |_, _| false,
                ) {
                    Action::Active { .. } => actual.push(carriage.anchor()[0]),
                    Action::Place { anchor } => {
                        placed = Some(anchor[0]);
                        break;
                    }
                }
            }
            assert_eq!(actual, expected);
            assert_eq!(placed, Some(landed));
        }
    }
}
