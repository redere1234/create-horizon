// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use std::collections::{HashSet, VecDeque};

use super::QuarterTurn;
use crate::{kinetics::Pos, placement::Direction};

pub const DEFAULT_MAX_BLOCKS: usize = 2048;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Adhesion {
    #[default]
    None,
    Slime,
    Honey,
}

impl Adhesion {
    fn sticks_to(self, other: Self) -> bool {
        !matches!(
            (self, other),
            (Self::None, Self::None) | (Self::Slime, Self::Honey) | (Self::Honey, Self::Slime)
        )
    }
}

/// The host classifies block-specific rules without having to copy block data.
/// Face arrays are indexed in Direction::ALL order.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct BlockRules {
    pub movable: bool,
    pub brittle: bool,
    pub push_only: bool,
    pub adhesion: Adhesion,
    pub attached: [bool; 6],
    pub unsupported_faces: [bool; 6],
}

impl Default for BlockRules {
    fn default() -> Self {
        Self {
            movable: true,
            brittle: false,
            push_only: false,
            adhesion: Adhesion::None,
            attached: [false; 6],
            unsupported_faces: [false; 6],
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Cell {
    Empty,
    OutsideWorld,
    Unloaded,
    Block(BlockRules),
}

/// Read-only view. Implementations must not load chunks or change the world.
/// Snapshots include all state and data needed to restore a moved block.
/// A movable block the adapter cannot preserve returns None from snapshot.
pub trait CaptureView {
    type Block;

    fn inspect(&self, pos: Pos) -> Cell;
    fn snapshot(&self, pos: Pos) -> Option<Self::Block>;
    fn glued(&self, pos: Pos, face: Direction) -> bool;
    /// Structured attachments may select more than one adjacent block.
    fn expand(&self, _: Pos, _: Option<Direction>) -> Result<Vec<Pos>, CaptureError> {
        Ok(Vec::new())
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CaptureError {
    CoordinateOverflow,
    Unloaded(Pos),
    Immovable(Pos),
    Unsupported(Pos),
    TooLarge { limit: usize },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LandingError {
    CoordinateOverflow,
    Unsupported(Pos),
    Obstructed(Pos),
}

#[derive(Debug, PartialEq, Eq)]
pub struct Assembly<B> {
    anchor: Pos,
    blocks: Vec<(Pos, B)>,
}

impl<B> Assembly<B> {
    /// Contraption.searchMovedStructure and moveBlock, with host-provided
    /// attachment and movement rules. The controller is excluded even if glued.
    /// Unavailable neighbouring cells are rejected rather than treated as air.
    pub fn capture(
        world: &impl CaptureView<Block = B>,
        anchor: Pos,
        controller: Option<Pos>,
        forced: Option<Direction>,
        max_blocks: usize,
    ) -> Result<Self, CaptureError> {
        Self::capture_from(
            world,
            anchor,
            [anchor],
            |pos| controller == Some(pos),
            forced,
            max_blocks,
        )
    }

    pub fn capture_from(
        world: &impl CaptureView<Block = B>,
        anchor: Pos,
        seeds: impl IntoIterator<Item = Pos>,
        fixed: impl Fn(Pos) -> bool,
        forced: Option<Direction>,
        max_blocks: usize,
    ) -> Result<Self, CaptureError> {
        let mut blocks = Vec::new();
        let mut frontier = VecDeque::new();
        let mut seen = HashSet::new();
        for pos in seeds {
            if fixed(pos) || seen.contains(&pos) {
                continue;
            }
            match world.inspect(pos) {
                Cell::Unloaded => return Err(CaptureError::Unloaded(pos)),
                Cell::Block(rules) if !rules.brittle => {
                    if seen.len() == max_blocks {
                        return Err(CaptureError::TooLarge { limit: max_blocks });
                    }
                    seen.insert(pos);
                    frontier.push_back((pos, rules));
                }
                _ => {}
            }
        }
        while let Some((pos, rules)) = frontier.pop_front() {
            if !rules.movable {
                return Err(CaptureError::Immovable(pos));
            }
            if blocks.len() == max_blocks {
                return Err(CaptureError::TooLarge { limit: max_blocks });
            }
            let local = checked_zip(pos, anchor, i32::checked_sub)
                .ok_or(CaptureError::CoordinateOverflow)?;
            blocks.push((
                local,
                world.snapshot(pos).ok_or(CaptureError::Unsupported(pos))?,
            ));
            for extra in world.expand(pos, forced)? {
                if fixed(extra) || seen.contains(&extra) {
                    continue;
                }
                match world.inspect(extra) {
                    Cell::Unloaded => return Err(CaptureError::Unloaded(extra)),
                    Cell::Block(rules) => {
                        if seen.len() == max_blocks {
                            return Err(CaptureError::TooLarge { limit: max_blocks });
                        }
                        seen.insert(extra);
                        frontier.push_back((extra, rules));
                    }
                    _ => {}
                }
            }
            for face in Direction::ALL {
                let neighbour = checked_zip(pos, face.vector(), i32::checked_add)
                    .ok_or(CaptureError::CoordinateOverflow)?;
                if fixed(neighbour) || seen.contains(&neighbour) {
                    continue;
                }
                let adjacent = match world.inspect(neighbour) {
                    Cell::Unloaded => return Err(CaptureError::Unloaded(neighbour)),
                    Cell::Block(adjacent) => adjacent,
                    _ => continue,
                };
                let force = forced == Some(face);
                if !adjacent.movable {
                    if force {
                        return Err(CaptureError::Immovable(neighbour));
                    }
                    continue;
                }
                let opposite = face.opposite() as usize;
                let supportive = !rules.unsupported_faces[face as usize];
                let sticks = !adjacent.brittle
                    && !rules.push_only
                    && !adjacent.push_only
                    && supportive
                    && !adjacent.unsupported_faces[opposite]
                    && rules.adhesion.sticks_to(adjacent.adhesion);
                if sticks
                    || adjacent.attached[opposite]
                    || world.glued(pos, face)
                    || force && supportive
                {
                    if seen.len() == max_blocks {
                        return Err(CaptureError::TooLarge { limit: max_blocks });
                    }
                    seen.insert(neighbour);
                    frontier.push_back((neighbour, adjacent));
                }
            }
        }
        Ok(Self { anchor, blocks })
    }

    pub fn anchor(&self) -> Pos {
        self.anchor
    }

    /// Local positions, in deterministic discovery order.
    pub fn blocks(&self) -> &[(Pos, B)] {
        &self.blocks
    }

    /// Build the whole restoration plan before any world edit. The host
    /// decides which replacements are legal and how state and data rotate.
    pub fn landing(
        &self,
        anchor: Pos,
        turn: QuarterTurn,
        rotate: impl FnMut(&B, QuarterTurn) -> Option<B>,
        accepts: impl FnMut(Pos, &B) -> bool,
    ) -> Result<Vec<(Pos, B)>, LandingError> {
        plan_landing(&self.blocks, anchor, turn, rotate, accepts)
    }
}

/// Restore a live or deserialized snapshot using the same preflight.
pub fn plan_landing<B>(
    blocks: &[(Pos, B)],
    anchor: Pos,
    turn: QuarterTurn,
    mut rotate: impl FnMut(&B, QuarterTurn) -> Option<B>,
    mut accepts: impl FnMut(Pos, &B) -> bool,
) -> Result<Vec<(Pos, B)>, LandingError> {
    blocks
        .iter()
        .map(|(local, block)| {
            let pos = turn
                .place(anchor, *local)
                .ok_or(LandingError::CoordinateOverflow)?;
            let block = rotate(block, turn).ok_or(LandingError::Unsupported(pos))?;
            if !accepts(pos, &block) {
                return Err(LandingError::Obstructed(pos));
            }
            Ok((pos, block))
        })
        .collect()
}

fn checked_zip(a: Pos, b: Pos, op: fn(i32, i32) -> Option<i32>) -> Option<Pos> {
    Some([op(a[0], b[0])?, op(a[1], b[1])?, op(a[2], b[2])?])
}
