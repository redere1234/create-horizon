// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! SailBlock interaction geometry and the bounded canvas repaint traversal.

use crate::{kinetics::Pos, placement::Direction};
use std::collections::{HashSet, VecDeque};

pub const FRAME: &str = "create:sail_frame";
pub const WHITE: &str = "create:white_sail";
pub const WINDMILL_TAG: &str = "create:windmill_sails";

const CANVAS: [&str; 16] = [
    WHITE,
    "create:orange_sail",
    "create:magenta_sail",
    "create:light_blue_sail",
    "create:yellow_sail",
    "create:lime_sail",
    "create:pink_sail",
    "create:gray_sail",
    "create:light_gray_sail",
    "create:cyan_sail",
    "create:purple_sail",
    "create:blue_sail",
    "create:brown_sail",
    "create:green_sail",
    "create:red_sail",
    "create:black_sail",
];

pub fn material(block: &str) -> Option<&'static str> {
    if block == FRAME {
        return Some(FRAME);
    }
    CANVAS.into_iter().find(|&id| block == id)
}

pub fn canvas_for_dye(item: &str) -> Option<&'static str> {
    let dye = item.strip_prefix("minecraft:")?.strip_suffix("_dye")?;
    CANVAS.into_iter().find(|id| {
        id.strip_prefix("create:")
            .and_then(|id| id.strip_suffix("_sail"))
            == Some(dye)
    })
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Sail {
    pub material: &'static str,
    pub facing: Direction,
}

impl Sail {
    /// BlockMovementChecksImpl attaches sails along their plane. Their axial
    /// faces also prevent an adjacent sticky block from pulling them in.
    pub fn attaches(self, side: Direction) -> bool {
        side.axis() != self.facing.axis()
    }

    pub fn adjacent(self, pos: Pos, hit: [f64; 3]) -> impl Iterator<Item = Pos> {
        let mut directions = Direction::ALL;
        directions.sort_by(|a, b| distance(*a, pos, hit).total_cmp(&distance(*b, pos, hit)));
        directions
            .into_iter()
            .filter(move |&direction| self.attaches(direction))
            .map(move |direction| offset(pos, direction))
    }
}

fn distance(direction: Direction, pos: Pos, hit: [f64; 3]) -> f64 {
    let vector = direction.vector();
    let [x, y, z] =
        std::array::from_fn(|i| f64::from(vector[i]) - (hit[i] - (f64::from(pos[i]) + 0.5)));
    (x * x + y * y + z * z).sqrt()
}

fn offset(pos: Pos, direction: Direction) -> Pos {
    let vector = direction.vector();
    std::array::from_fn(|i| pos[i] + vector[i])
}

/// First repaint the target, then one differing neighbor by hit distance,
/// and only then flood the coplanar group. Java allows 101 frontier pops.
pub fn repaint(
    sail: Sail,
    target: &'static str,
    start: Pos,
    hit: [f64; 3],
    mut sail_at: impl FnMut(Pos) -> Option<Sail>,
) -> Vec<Pos> {
    if sail.material == FRAME && target != FRAME {
        return Vec::new();
    }
    if sail.material != target {
        return vec![start];
    }
    let same_plane = |neighbor: Sail| neighbor.facing == sail.facing;
    if let Some(neighbor) = sail.adjacent(start, hit).find(|&p| {
        sail_at(p).is_some_and(|s| same_plane(s) && s.material != FRAME && s.material != target)
    }) {
        return vec![neighbor];
    }

    let mut visited = HashSet::from([start]);
    let mut queue = VecDeque::from([start]);
    let mut changed = Vec::new();
    for _ in 0..=100 {
        let Some(pos) = queue.pop_front() else {
            break;
        };
        for direction in Direction::ALL.into_iter().filter(|&d| sail.attaches(d)) {
            let neighbor = offset(pos, direction);
            if visited.contains(&neighbor) {
                continue;
            }
            let Some(s) = sail_at(neighbor).filter(|&s| same_plane(s)) else {
                continue;
            };
            if s.material == FRAME && target != FRAME {
                continue;
            }
            if s.material != target {
                changed.push(neighbor);
            }
            visited.insert(neighbor);
            queue.push_back(neighbor);
        }
    }
    changed
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sail(material: &'static str) -> Sail {
        Sail {
            material,
            facing: Direction::South,
        }
    }

    #[test]
    fn repaint_preserves_full_facing_and_prioritizes_the_clicked_edge() {
        let red = canvas_for_dye("minecraft:red_dye").unwrap();
        let start = [0, 0, 0];
        let right = [1, 0, 0];
        let up = [0, 1, 0];
        let hit = [0.9, 0.6, 0.5];
        let world = |p| (p == right || p == up).then(|| sail(WHITE));
        assert_eq!(repaint(sail(WHITE), red, start, hit, world), [start]);
        assert_eq!(repaint(sail(red), red, start, hit, world), [right]);
        assert_eq!(repaint(sail(red), FRAME, start, hit, world), [start]);
        assert!(repaint(sail(FRAME), red, start, hit, world).is_empty());
        assert!(!sail(red).attaches(Direction::North));
        assert!(sail(red).attaches(Direction::Up));
    }

    #[test]
    fn flood_stops_at_axial_faces_flipped_sails_and_frames() {
        let red = canvas_for_dye("minecraft:red_dye").unwrap();
        let start = [0, 0, 0];
        let world = |p: Pos| match p {
            [1, 0, 0] => Some(sail(red)),
            [2, 0, 0] => Some(sail(WHITE)),
            [0, 1, 0] => Some(sail(FRAME)),
            [0, 2, 0] | [0, 0, 1] => Some(sail(WHITE)),
            [-1, 0, 0] => Some(Sail {
                material: WHITE,
                facing: Direction::North,
            }),
            _ => None,
        };
        assert_eq!(repaint(sail(red), red, start, [0.5; 3], world), [[2, 0, 0]]);
    }
}
