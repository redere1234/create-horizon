// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! The directed grid and per-crafter timing of Create's Mechanical Crafter.
use crate::{
    kinetics::{Axis, Pos},
    placement::Direction,
};
use std::collections::{BTreeMap, BTreeSet, VecDeque};

const MAX_CHAIN: usize = 4096;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Pointing {
    Up,
    Left,
    Down,
    Right,
}

impl Pointing {
    pub fn name(self) -> &'static str {
        match self {
            Self::Up => "up",
            Self::Left => "left",
            Self::Down => "down",
            Self::Right => "right",
        }
    }

    pub fn from_name(value: &str) -> Option<Self> {
        match value {
            "up" => Some(Self::Up),
            "left" => Some(Self::Left),
            "down" => Some(Self::Down),
            "right" => Some(Self::Right),
            _ => None,
        }
    }

    pub fn next(self) -> Self {
        match self {
            Self::Up => Self::Left,
            Self::Left => Self::Down,
            Self::Down => Self::Right,
            Self::Right => Self::Up,
        }
    }

    pub fn direction(self, facing: Direction) -> Direction {
        match self {
            Self::Up => Direction::Up,
            Self::Left => facing.clockwise(Axis::Y),
            Self::Down => Direction::Down,
            Self::Right => facing.clockwise(Axis::Y).opposite(),
        }
    }

    /// On the crafter plane the arrow leads back to the clicked support.
    /// Preserve Java's perpendicular arrow on a click along the facing axis.
    pub fn from_clicked_face(face: Direction, facing: Direction) -> Self {
        let positive = matches!(facing, Direction::South | Direction::East);
        match face {
            Direction::Down => Self::Up,
            Direction::Up => Self::Down,
            Direction::East | Direction::North if positive => Self::Left,
            Direction::West | Direction::South if !positive => Self::Left,
            _ => Self::Right,
        }
    }

    fn grid_offset(self) -> (i32, i32) {
        match self {
            Self::Up => (0, -1),
            Self::Left => (1, 0),
            Self::Down => (0, 1),
            Self::Right => (-1, 0),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Layout {
    pub facing: Direction,
    pub pointing: Pointing,
}

impl Layout {
    pub fn target_direction(self) -> Direction {
        self.pointing.direction(self.facing)
    }

    pub fn target_position(self, pos: Pos) -> Pos {
        offset(pos, self.target_direction())
    }
}

fn offset(pos: Pos, direction: Direction) -> Pos {
    let delta = direction.vector();
    std::array::from_fn(|axis| pos[axis] + delta[axis])
}

pub fn target(
    pos: Pos,
    layout: Layout,
    read: &mut impl FnMut(Pos) -> Option<Layout>,
) -> Option<Pos> {
    let next = layout.target_position(pos);
    read(next).filter(|other| other.facing == layout.facing)?;
    Some(next)
}

pub fn preceding(
    pos: Pos,
    layout: Layout,
    read: &mut impl FnMut(Pos) -> Option<Layout>,
) -> Vec<Pos> {
    let outgoing = layout.target_direction();
    Direction::ALL
        .into_iter()
        .filter(|&side| side.axis() != layout.facing.axis() && side != outgoing)
        .filter_map(|side| {
            let next = offset(pos, side);
            let other = read(next)?;
            (other.facing == layout.facing && other.target_direction() == side.opposite())
                .then_some(next)
        })
        .collect()
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ChainError {
    Missing,
    Cycle,
    TooLarge,
}

/// RecipeGridHandler's target-first traversal with incoming directions in
/// Minecraft enum order. A reciprocal pair has no output and is also
/// rejected; Java's predecessor search skips their shared outgoing edge.
pub fn chain(
    start: Pos,
    mut read: impl FnMut(Pos) -> Option<Layout>,
) -> Result<Vec<Pos>, ChainError> {
    let mut frontier = VecDeque::from([(start, None)]);
    let mut visited = BTreeSet::new();
    let mut result = Vec::new();
    let mut has_output = false;
    while let Some((pos, previous)) = frontier.pop_front() {
        if !visited.insert(pos) {
            return Err(ChainError::Cycle);
        }
        if visited.len() > MAX_CHAIN {
            return Err(ChainError::TooLarge);
        }
        let layout = read(pos).ok_or(ChainError::Missing)?;
        result.push(pos);
        if let Some(next) = target(pos, layout, &mut read) {
            if Some(next) != previous {
                frontier.push_back((next, Some(pos)));
            }
        } else {
            has_output = true;
        }
        for next in preceding(pos, layout, &mut read) {
            if Some(next) != previous {
                frontier.push_back((next, Some(pos)));
            }
        }
    }
    if has_output {
        Ok(result)
    } else {
        Err(ChainError::Cycle)
    }
}

/// Java's persisted coordinates are relative to the current crafter, with
/// positive X to the right and positive Y up. Blanks remain in the live grid.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct GroupedItems<T> {
    pub grid: BTreeMap<(i32, i32), Option<T>>,
}

impl<T> Default for GroupedItems<T> {
    fn default() -> Self {
        Self {
            grid: BTreeMap::new(),
        }
    }
}

impl<T> GroupedItems<T> {
    pub fn single(item: Option<T>) -> Self {
        Self {
            grid: BTreeMap::from([((0, 0), item)]),
        }
    }

    pub fn only_empty(&self) -> bool {
        self.grid.values().all(Option::is_none)
    }

    /// Refuse overflowing or overlapping coordinates before moving anything.
    /// Separate branches in a valid physical tree never overlap.
    pub fn merge_onto(&mut self, target: &mut Self, pointing: Pointing) -> bool {
        let (dx, dy) = pointing.grid_offset();
        for &(x, y) in self.grid.keys() {
            let Some(pos) = x.checked_add(dx).zip(y.checked_add(dy)) else {
                return false;
            };
            if target.grid.contains_key(&pos) {
                return false;
            }
        }
        target.grid.extend(
            std::mem::take(&mut self.grid)
                .into_iter()
                .map(|((x, y), stack)| ((x + dx, y + dy), stack)),
        );
        true
    }

    /// MechanicalCraftingInput crops by occupied cells, then reads top-down
    /// even though GroupedItems uses bottom-up coordinates.
    pub fn recipe_grid(&self) -> Option<RecipeGrid<'_, T>> {
        let mut occupied = self
            .grid
            .iter()
            .filter_map(|(&pos, item)| item.as_ref().map(|_| pos));
        let (mut min_x, mut max_y) = occupied.next()?;
        let (mut max_x, mut min_y) = (min_x, max_y);
        for (x, y) in occupied {
            min_x = min_x.min(x);
            max_x = max_x.max(x);
            min_y = min_y.min(y);
            max_y = max_y.max(y);
        }
        Some(RecipeGrid {
            items: &self.grid,
            min_x,
            max_y,
            width: (i64::from(max_x) - i64::from(min_x) + 1).try_into().ok()?,
            height: (i64::from(max_y) - i64::from(min_y) + 1).try_into().ok()?,
        })
    }
}

pub struct RecipeGrid<'a, T> {
    items: &'a BTreeMap<(i32, i32), Option<T>>,
    min_x: i32,
    max_y: i32,
    pub width: usize,
    pub height: usize,
}

impl<T> RecipeGrid<'_, T> {
    pub fn get(&self, x: usize, y: usize) -> Option<&T> {
        if x >= self.width || y >= self.height {
            return None;
        }
        let px = i32::try_from(i64::from(self.min_x) + x as i64).ok()?;
        let py = i32::try_from(i64::from(self.max_y) - y as i64).ok()?;
        self.items.get(&(px, py))?.as_ref()
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Phase {
    #[default]
    Idle,
    Accepting,
    Assembling,
    Exporting,
    Waiting,
    Crafting,
    Inserting,
}

impl Phase {
    pub fn name(self) -> &'static str {
        match self {
            Self::Idle => "IDLE",
            Self::Accepting => "ACCEPTING",
            Self::Assembling => "ASSEMBLING",
            Self::Exporting => "EXPORTING",
            Self::Waiting => "WAITING",
            Self::Crafting => "CRAFTING",
            Self::Inserting => "INSERTING",
        }
    }

    pub fn from_name(value: &str) -> Option<Self> {
        match value {
            "IDLE" => Some(Self::Idle),
            "ACCEPTING" => Some(Self::Accepting),
            "ASSEMBLING" => Some(Self::Assembling),
            "EXPORTING" => Some(Self::Exporting),
            "WAITING" => Some(Self::Waiting),
            "CRAFTING" => Some(Self::Crafting),
            "INSERTING" => Some(Self::Inserting),
            _ => None,
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Cycle {
    pub phase: Phase,
    pub countdown: i32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Tick {
    None,
    AssemblyComplete,
    ExportComplete,
    CraftMiddle,
    CraftComplete,
}

pub fn countdown_speed(rpm: f32) -> i32 {
    if rpm == 0.0 || !rpm.is_finite() {
        return 0;
    }
    (rpm.abs() as i32).clamp(4, 250)
}

impl Cycle {
    pub fn begin(self, has_preceding: bool) -> Self {
        if has_preceding {
            Self {
                phase: Phase::Accepting,
                ..self
            }
        } else {
            Self::assembling()
        }
    }

    pub fn assembling() -> Self {
        Self {
            phase: Phase::Assembling,
            countdown: 1,
        }
    }

    pub fn exporting(only_empty: bool) -> Self {
        Self {
            phase: Phase::Exporting,
            countdown: if only_empty { 0 } else { 1000 },
        }
    }

    pub fn crafting() -> Self {
        Self {
            phase: Phase::Crafting,
            countdown: 2000,
        }
    }

    /// The host commits each transition before the next crafter's tick.
    /// A countdown equal to zero still waits for one nonzero-speed tick.
    pub fn tick(&mut self, rpm: f32) -> Tick {
        let complete = match self.phase {
            Phase::Assembling => Tick::AssemblyComplete,
            Phase::Exporting => Tick::ExportComplete,
            Phase::Crafting => Tick::CraftComplete,
            _ => return Tick::None,
        };
        let previous = self.countdown;
        let remaining = previous.saturating_sub(countdown_speed(rpm));
        self.countdown = remaining.max(0);
        if remaining < 0 {
            complete
        } else if self.phase == Phase::Crafting && remaining < 1000 && previous >= 1000 {
            Tick::CraftMiddle
        } else {
            Tick::None
        }
    }
}

/// MechanicalCrafterRenderer's two overlapping half-cycle poses.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct CraftPose {
    pub input_scale: f32,
    pub center: f32,
    pub spacing: f32,
    pub result_scale: f32,
    pub result_angle: f32,
}

pub fn craft_pose(remaining: f32) -> CraftPose {
    let input_progress = ((2000.0 - remaining) / 1000.0).clamp(0.0, 1.0);
    let result_progress = ((1000.0 - remaining) / 1000.0).clamp(0.0, 1.0);
    let early = |progress: f32| (progress * 2.0).clamp(0.0, 1.0);
    let late = |progress: f32| (progress * 2.0 - 1.0).clamp(0.0, 1.0);
    CraftPose {
        input_scale: 1.0 - late(input_progress),
        center: early(input_progress),
        spacing: 0.5 + (-4.0 * (input_progress - 0.5).powi(2) + 1.0) * 0.25,
        result_scale: early(result_progress)
            * 1.125
            * (1.0 + (1.0 - late(result_progress)) * 0.125),
        result_angle: early(result_progress) * 720.0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cmp::Reverse;

    fn south(pointing: Pointing) -> Layout {
        Layout {
            facing: Direction::South,
            pointing,
        }
    }

    #[test]
    fn craft_pose_centers_and_shrinks_the_input_then_spins_and_grows_the_result() {
        assert_eq!(
            [2000., 1750., 1500., 1250., 1000., 750., 500., 250., 0.].map(|remaining| {
                let pose = craft_pose(remaining);
                [
                    pose.input_scale,
                    pose.center,
                    pose.spacing,
                    pose.result_scale,
                    pose.result_angle,
                ]
            }),
            [
                [1., 0., 0.5, 0., 0.],
                [1., 0.5, 0.6875, 0., 0.],
                [1., 1., 0.75, 0., 0.],
                [0.5, 1., 0.6875, 0., 0.],
                [0., 1., 0.5, 0., 0.],
                [0., 1., 0.5, 0.6328125, 360.],
                [0., 1., 0.5, 1.265625, 720.],
                [0., 1., 0.5, 1.1953125, 720.],
                [0., 1., 0.5, 1.125, 720.],
            ],
        );
    }

    #[test]
    fn front_wrench_and_support_directions_follow_java_pointing() {
        for facing in [
            Direction::South,
            Direction::West,
            Direction::North,
            Direction::East,
        ] {
            let mut pointing = Pointing::Up;
            for _ in 0..4 {
                let clicked = pointing.direction(facing).opposite();
                assert_eq!(Pointing::from_clicked_face(clicked, facing), pointing);
                assert_eq!(Pointing::from_name(pointing.name()), Some(pointing));
                pointing = pointing.next();
            }
            assert_eq!(pointing, Pointing::Up);
        }
        assert_eq!(Pointing::Left.direction(Direction::South), Direction::West);
        assert_eq!(Pointing::Left.direction(Direction::East), Direction::South);
        assert_eq!(
            Pointing::from_clicked_face(Direction::North, Direction::South),
            Pointing::Left
        );
    }

    #[test]
    fn branches_merge_to_the_original_twenty_one_cell_recipe() {
        let pattern = [b" AAA ", b"AAPAA", b"APSPA", b"AAPAA", b" AAA "];
        let mut layout = BTreeMap::new();
        let mut grouped = BTreeMap::new();
        for (row, cells) in pattern.into_iter().enumerate() {
            for (col, &item) in cells.iter().enumerate() {
                if item == b' ' {
                    continue;
                }
                let x = col as i32 - 2;
                let pos = [x, 4 - row as i32, 0];
                let pointing = match x.cmp(&0) {
                    std::cmp::Ordering::Less => Pointing::Right,
                    std::cmp::Ordering::Equal => Pointing::Down,
                    std::cmp::Ordering::Greater => Pointing::Left,
                };
                layout.insert(pos, south(pointing));
                grouped.insert(pos, GroupedItems::single(Some(item)));
            }
        }
        let sink = [0, 0, 0];
        let mut read = |pos| layout.get(&pos).copied();
        let mut order = chain([-1, 4, 0], &mut read).unwrap();
        assert_eq!(order.len(), 21);
        order.sort_by_key(|&[x, y, _]| Reverse(x.abs() + y));
        for pos in order.into_iter().filter(|&pos| pos != sink) {
            let destination = target(pos, layout[&pos], &mut read).unwrap();
            let mut incoming = grouped.remove(&pos).unwrap();
            assert!(incoming.merge_onto(
                grouped.get_mut(&destination).unwrap(),
                layout[&pos].pointing
            ));
            assert!(incoming.grid.is_empty());
        }
        let mut result = grouped.remove(&sink).unwrap();
        assert_eq!(result.grid[&(0, 2)], Some(b'S'));
        assert_eq!(result.grid[&(-1, 4)], Some(b'A'));
        result.grid.insert((10, -10), None);
        let grid = result.recipe_grid().unwrap();
        assert_eq!((grid.width, grid.height), (5, 5));
        for (y, row) in pattern.into_iter().enumerate() {
            for (x, &item) in row.iter().enumerate() {
                assert_eq!(grid.get(x, y).copied().unwrap_or(b' '), item);
            }
        }
    }

    #[test]
    fn cyclic_or_corrupt_input_never_overwrites_items() {
        let reciprocal = |pos: Pos| match pos {
            [0, 0, 0] => Some(south(Pointing::Right)),
            [1, 0, 0] => Some(south(Pointing::Left)),
            _ => None,
        };
        assert_eq!(chain([0, 0, 0], reciprocal), Err(ChainError::Cycle));
        let cycle = |pos: Pos| match pos {
            [0, 0, 0] => Some(south(Pointing::Right)),
            [1, 0, 0] => Some(south(Pointing::Up)),
            [1, 1, 0] => Some(south(Pointing::Left)),
            [0, 1, 0] => Some(south(Pointing::Down)),
            _ => None,
        };
        assert_eq!(chain([0, 0, 0], cycle), Err(ChainError::Cycle));
        let too_large = |[x, _, _]: Pos| (x <= MAX_CHAIN as i32).then_some(south(Pointing::Right));
        assert_eq!(chain([0, 0, 0], too_large), Err(ChainError::TooLarge));
        let mut incoming = GroupedItems::single(Some("alloy"));
        let mut existing = GroupedItems::default();
        existing.grid.insert((1, 0), Some("stone"));
        assert!(!incoming.merge_onto(&mut existing, Pointing::Left));
        assert_eq!(incoming.grid[&(0, 0)], Some("alloy"));
        assert_eq!(existing.grid[&(1, 0)], Some("stone"));
    }

    #[test]
    fn countdown_waits_at_zero_and_tracks_the_crafting_midpoint() {
        assert_eq!(countdown_speed(-3.9), 4);
        assert_eq!(countdown_speed(-16.9), 16);
        assert_eq!(countdown_speed(256.0), 250);
        let mut cycle = Cycle::default().begin(false);
        assert_eq!(cycle.tick(0.0), Tick::None);
        assert_eq!(cycle.countdown, 1);
        assert_eq!(cycle.tick(128.0), Tick::AssemblyComplete);
        cycle = Cycle::exporting(false);
        for _ in 0..4 {
            assert_eq!(cycle.tick(250.0), Tick::None);
        }
        assert_eq!(cycle.countdown, 0);
        assert_eq!(cycle.tick(0.0), Tick::None);
        assert_eq!(cycle.tick(-250.0), Tick::ExportComplete);
        let mut blank = Cycle::exporting(true);
        assert_eq!(blank.tick(0.0), Tick::None);
        assert_eq!(blank.tick(1.0), Tick::ExportComplete);
        let mut craft = Cycle::crafting();
        for _ in 0..4 {
            assert_eq!(craft.tick(250.0), Tick::None);
        }
        assert_eq!(craft.countdown, 1000);
        assert_eq!(craft.tick(250.0), Tick::CraftMiddle);
        for _ in 0..3 {
            assert_eq!(craft.tick(250.0), Tick::None);
        }
        assert_eq!(craft.countdown, 0);
        assert_eq!(craft.tick(250.0), Tick::CraftComplete);
    }
}
