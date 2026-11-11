// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! Super Glue block-volume geometry and read-only selection planning.
//! The host supplies movement-necessary cells and special sticky faces.

use std::collections::{HashSet, VecDeque};

use crate::{kinetics::Pos, placement::Direction};

use super::{Adhesion, BlockRules, CaptureView, Cell, QuarterTurn};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Volume {
    min: Pos,
    max: Pos,
}

impl Volume {
    /// Both endpoints are inclusive, equivalent to the Java AABB after
    /// expanding its upper corner by one and testing block centers.
    pub fn span(from: Pos, to: Pos) -> Self {
        Self {
            min: std::array::from_fn(|axis| from[axis].min(to[axis])),
            max: std::array::from_fn(|axis| from[axis].max(to[axis])),
        }
    }

    pub fn corners(self) -> [Pos; 2] {
        [self.min, self.max]
    }

    pub fn is_single_block(self) -> bool {
        self.min == self.max
    }

    pub fn contains(self, pos: Pos) -> bool {
        (0..3).all(|axis| (self.min[axis]..=self.max[axis]).contains(&pos[axis]))
    }

    /// A face is glued only when this volume contains both of its blocks.
    pub fn glues(self, pos: Pos, face: Direction) -> bool {
        self.contains(pos) && adjacent(pos, face).is_some_and(|target| self.contains(target))
    }

    /// Crop for transfer with a structure. A one-block intersection joins
    /// no faces and is discarded by Create.
    pub fn crop(self, bounds: Self) -> Option<Self> {
        let min = std::array::from_fn(|axis| self.min[axis].max(bounds.min[axis]));
        let max = std::array::from_fn(|axis| self.max[axis].min(bounds.max[axis]));
        (min != max && (0..3).all(|axis| min[axis] <= max[axis])).then_some(Self { min, max })
    }

    /// Minimize a glue entity to the captured blocks inside its original box
    /// before transferring it to a contraption.
    pub fn fit_to(self, blocks: impl IntoIterator<Item = Pos>) -> Option<Self> {
        let mut inside = blocks.into_iter().filter(|&pos| self.contains(pos));
        let first = inside.next()?;
        let fitted = inside.fold(Self::span(first, first), |mut fitted, pos| {
            for (axis, value) in pos.into_iter().enumerate() {
                fitted.min[axis] = fitted.min[axis].min(value);
                fitted.max[axis] = fitted.max[axis].max(value);
            }
            fitted
        });
        (fitted.min != fitted.max).then_some(fitted)
    }

    pub fn relative_to(self, anchor: Pos) -> Option<Self> {
        let local = |pos: Pos| {
            Some([
                pos[0].checked_sub(anchor[0])?,
                pos[1].checked_sub(anchor[1])?,
                pos[2].checked_sub(anchor[2])?,
            ])
        };
        Some(Self {
            min: local(self.min)?,
            max: local(self.max)?,
        })
    }

    /// Transform the integer block-center envelope at the same quarter turn
    /// used for block landing. Axis permutations preserve an axis-aligned box.
    pub fn place(self, anchor: Pos, turn: QuarterTurn) -> Option<Self> {
        Some(Self::span(
            turn.place(anchor, self.min)?,
            turn.place(anchor, self.max)?,
        ))
    }
}

fn adjacent(pos: Pos, face: Direction) -> Option<Pos> {
    let axis = face.axis().index();
    let mut next = pos;
    next[axis] = next[axis].checked_add(face.vector()[axis])?;
    Some(next)
}

fn valid_face(rules: BlockRules, face: Direction) -> bool {
    rules.attached[face as usize] || !rules.unsupported_faces[face as usize]
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Search {
    Preview,
    Commit,
}

impl Search {
    fn reaches(self, from: Pos, to: Pos) -> bool {
        let limit = match self {
            Self::Preview => 24,
            Self::Commit => 25,
        };
        let distance = (0..3)
            .map(|axis| (i128::from(from[axis]) - i128::from(to[axis])).pow(2))
            .sum::<i128>();
        distance < limit * limit
    }
}

#[derive(Debug, PartialEq, Eq)]
pub struct Selection {
    pub volume: Volume,
    pub attached: HashSet<Pos>,
    end: Pos,
}

impl Selection {
    pub fn can_commit(&self) -> bool {
        self.attached.len() >= 2 && self.attached.contains(&self.end)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SelectionError {
    TooFar,
    Unloaded(Pos),
    TooLarge { limit: usize },
}

/// Find the cluster reached from `from` through valid opposing faces. A
/// disconnected cluster is still returned for the preview; check can_commit
/// before spending any glue. Empty or replaceable cells must be classified as
/// empty by the host. Special sticky faces cover bearings, chassis and similar
/// blocks; slime and honey are handled from the shared adhesion rule.
pub fn selection<W: CaptureView>(
    world: &W,
    from: Pos,
    to: Pos,
    search: Search,
    max_blocks: usize,
    special_sticky: impl Fn(Pos, Direction) -> bool,
) -> Result<Selection, SelectionError> {
    if !search.reaches(from, to) {
        return Err(SelectionError::TooFar);
    }
    let volume = Volume::span(from, to);
    let mut attached = HashSet::new();
    let mut frontier = VecDeque::new();
    match world.inspect(from) {
        Cell::Block(rules) => {
            attached.insert(from);
            frontier.push_back((from, rules));
        }
        Cell::Unloaded => return Err(SelectionError::Unloaded(from)),
        Cell::Empty | Cell::OutsideWorld => {}
    }
    let sticky = |pos, face, rules: BlockRules| {
        rules.adhesion != Adhesion::None || special_sticky(pos, face)
    };
    while let Some((pos, current)) = frontier.pop_front() {
        if attached.len() > max_blocks {
            return Err(SelectionError::TooLarge { limit: max_blocks });
        }
        for face in Direction::ALL {
            let Some(next) = adjacent(pos, face) else {
                continue;
            };
            if attached.contains(&next) || !valid_face(current, face) {
                continue;
            }
            let in_range = volume.contains(next)
                || search == Search::Preview
                    && (world.glued(pos, face) || sticky(pos, face, current));
            let target = match world.inspect(next) {
                Cell::Block(rules) => rules,
                Cell::Unloaded if in_range => return Err(SelectionError::Unloaded(next)),
                _ => continue,
            };
            let opposite = face.opposite();
            // The original server ignores previous glue and the current
            // block's sticky face. The destination's sticky face still counts.
            if (in_range || sticky(next, opposite, target)) && valid_face(target, opposite) {
                attached.insert(next);
                frontier.push_back((next, target));
            }
        }
    }
    Ok(Selection {
        volume,
        attached,
        end: to,
    })
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OffhandPlacement {
    Unchanged,
    CancelPlacement,
    Apply(Volume),
}

/// Called after checking the actual offhand item and the player's reach.
/// The hit must be traced with the just-placed block omitted.
pub fn offhand_placement(
    world: &impl CaptureView,
    placed: Pos,
    hit: Option<(Pos, Direction)>,
) -> OffhandPlacement {
    let Some((against, face)) = hit else {
        return OffhandPlacement::Unchanged;
    };
    if adjacent(against, face) != Some(placed) {
        return OffhandPlacement::CancelPlacement;
    }
    if world.glued(against, face) {
        return OffhandPlacement::Unchanged;
    }
    match world.inspect(against) {
        Cell::Block(rules) if valid_face(rules, face) => {
            OffhandPlacement::Apply(Volume::span(against, placed))
        }
        _ => OffhandPlacement::Unchanged,
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use super::*;

    #[derive(Default)]
    struct World {
        blocks: HashMap<Pos, Cell>,
        volumes: Vec<Volume>,
    }

    impl World {
        fn with_blocks(positions: impl IntoIterator<Item = Pos>) -> Self {
            Self {
                blocks: positions
                    .into_iter()
                    .map(|pos| (pos, Cell::Block(BlockRules::default())))
                    .collect(),
                ..Self::default()
            }
        }
    }

    impl CaptureView for World {
        type Block = ();

        fn inspect(&self, pos: Pos) -> Cell {
            self.blocks.get(&pos).copied().unwrap_or(Cell::Empty)
        }

        fn snapshot(&self, _: Pos) -> Option<Self::Block> {
            Some(())
        }

        fn glued(&self, pos: Pos, face: Direction) -> bool {
            self.volumes.iter().any(|volume| volume.glues(pos, face))
        }
    }

    #[test]
    fn inclusive_volume_glues_both_directions_and_drops_single_block_crops() {
        let volume = Volume::span([3, 1, -1], [1, 1, -2]);
        assert_eq!(volume.corners(), [[1, 1, -2], [3, 1, -1]]);
        assert!(volume.glues([1, 1, -2], Direction::East));
        assert!(volume.glues([2, 1, -2], Direction::West));
        assert!(!volume.glues([3, 1, -2], Direction::East));
        assert_eq!(
            volume.crop(Volume::span([2, 1, -2], [4, 2, -2])),
            Some(Volume::span([2, 1, -2], [3, 1, -2]))
        );
        assert_eq!(volume.crop(Volume::span([3, 1, -2], [4, 1, -2])), None);
    }

    #[test]
    fn transferred_glue_is_fit_to_captured_blocks_inside_the_volume() {
        let volume = Volume::span([0, 0, 0], [4, 4, 4]);
        let blocks = [[1, 1, 2], [1, 2, 2], [8, 0, 1], [8, 4, 4]];
        assert_eq!(
            volume.fit_to(blocks),
            Some(Volume::span([1, 1, 2], [1, 2, 2]))
        );
        assert_eq!(volume.fit_to([[1, 1, 2], [8, 4, 4]]), None);
    }

    #[test]
    fn transfer_rotates_the_minimized_volume_with_its_captured_blocks() {
        use crate::contraption::Rotation;
        use crate::kinetics::Axis;

        let anchor = [100, 64, 100];
        let volume = Volume::span([98, 63, 99], [104, 67, 106]);
        let inside = [[101, 65, 100], [102, 66, 101]];
        let outside = [[105, 64, 100], [100, 68, 100]];
        let fitted = volume.fit_to(inside.into_iter().chain(outside)).unwrap();
        let local = fitted.relative_to(anchor).unwrap();
        assert_eq!(local.corners(), [[1, 1, 0], [2, 2, 1]]);

        let next_anchor = [120, 70, -30];
        let turn = Rotation::new(next_anchor, Axis::Y, 90.0).unwrap().snapped();
        let landed = local.place(next_anchor, turn).unwrap();
        assert_eq!(landed.corners(), [[120, 71, -32], [121, 72, -31]]);
        for pos in inside {
            let world = turn
                .place(
                    next_anchor,
                    std::array::from_fn(|axis| pos[axis] - anchor[axis]),
                )
                .unwrap();
            assert!(landed.contains(world));
        }
        assert!(!landed.contains(next_anchor));
    }

    #[test]
    fn volume_transform_rejects_overflow_before_world_changes() {
        use crate::contraption::Rotation;
        use crate::kinetics::Axis;

        let bound = Volume::span([i32::MIN, 0, 0], [i32::MIN + 1, 0, 0]);
        assert_eq!(bound.relative_to([1, 0, 0]), None);
        let local = Volume::span([1, 0, 0], [2, 0, 0]);
        let edge = [i32::MAX, 0, 0];
        let turn = Rotation::new(edge, Axis::Y, 0.0).unwrap().snapped();
        assert_eq!(local.place(edge, turn), None);
    }

    #[test]
    fn range_is_strict_euclidean_and_server_allows_one_extra_block() {
        assert!(Search::Preview.reaches([0; 3], [14, 14, 13]));
        assert!(!Search::Preview.reaches([0; 3], [14, 14, 14]));
        assert!(!Search::Preview.reaches([0; 3], [24, 0, 0]));
        assert!(Search::Commit.reaches([0; 3], [24, 0, 0]));
        assert!(!Search::Commit.reaches([0; 3], [25, 0, 0]));
        assert!(!Search::Commit.reaches([i32::MIN; 3], [i32::MAX; 3]));
    }

    #[test]
    fn an_existing_glue_bridge_only_counts_in_the_preview() {
        let start = [0, 0, 0];
        let end = [2, 0, 0];
        let path = [start, [0, 1, 0], [1, 1, 0], [2, 1, 0], end];
        let mut world = World::with_blocks(path);
        world.volumes.push(Volume::span(start, [2, 1, 0]));
        let preview = selection(&world, start, end, Search::Preview, 16, |_, _| false).unwrap();
        assert!(preview.can_commit());
        assert_eq!(preview.attached.len(), 5);
        let server = selection(&world, start, end, Search::Commit, 16, |_, _| false).unwrap();
        assert!(!server.can_commit());
        assert_eq!(server.attached, HashSet::from([start]));
    }

    #[test]
    fn a_sticky_destination_can_expand_the_server_cluster_but_a_sticky_source_cannot() {
        let start = [0, 0, 0];
        let end = [1, 0, 0];
        let outside = [0, 1, 0];
        let world = World::with_blocks([start, end, outside]);
        let from_sticky = |pos, face| pos == start && face == Direction::Up;
        let to_sticky = |pos, face| pos == outside && face == Direction::Down;
        let from = selection(&world, start, end, Search::Commit, 16, from_sticky).unwrap();
        let to = selection(&world, start, end, Search::Commit, 16, to_sticky).unwrap();
        assert!(!from.attached.contains(&outside));
        assert!(to.attached.contains(&outside));
        assert!(to.can_commit());
    }

    #[test]
    fn attached_blocks_can_override_an_unsupported_face_and_world_load_is_bounded() {
        let start = [0, 0, 0];
        let end = [1, 0, 0];
        let mut world = World::with_blocks([start, end]);
        let mut rules = BlockRules::default();
        rules.unsupported_faces[Direction::East as usize] = true;
        world.blocks.insert(start, Cell::Block(rules));
        let run = |world: &World, limit| {
            selection(world, start, end, Search::Commit, limit, |_, _| false)
        };
        assert!(!run(&world, 2).unwrap().can_commit());
        rules.attached[Direction::East as usize] = true;
        world.blocks.insert(start, Cell::Block(rules));
        assert!(run(&world, 2).unwrap().can_commit());
        assert_eq!(run(&world, 1), Err(SelectionError::TooLarge { limit: 1 }));
        world.blocks.insert(end, Cell::Unloaded);
        assert_eq!(run(&world, 2), Err(SelectionError::Unloaded(end)));
    }

    #[test]
    fn offhand_glue_requires_the_actual_support_face_and_skips_existing_glue() {
        let start = [0, 0, 0];
        let end = [1, 0, 0];
        let mut world = World::with_blocks([start, end]);
        assert_eq!(
            offhand_placement(&world, end, Some((start, Direction::West))),
            OffhandPlacement::CancelPlacement
        );
        let hit = Some((start, Direction::East));
        let volume = Volume::span(start, end);
        assert_eq!(
            offhand_placement(&world, end, hit),
            OffhandPlacement::Apply(volume)
        );
        let mut rules = BlockRules::default();
        rules.unsupported_faces[Direction::East as usize] = true;
        world.blocks.insert(start, Cell::Block(rules));
        assert_eq!(
            offhand_placement(&world, end, hit),
            OffhandPlacement::Unchanged
        );
        rules.attached[Direction::East as usize] = true;
        world.blocks.insert(start, Cell::Block(rules));
        assert_eq!(
            offhand_placement(&world, end, hit),
            OffhandPlacement::Apply(volume)
        );
        world.volumes.push(volume);
        assert_eq!(
            offhand_placement(&world, end, hit),
            OffhandPlacement::Unchanged
        );
        assert_eq!(
            offhand_placement(&world, end, None),
            OffhandPlacement::Unchanged
        );
    }
}
