// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! Vanilla and data-tagged tree traversal from Java `TreeCutter`.

use crate::{kinetics::Pos, placement::Direction};
use std::collections::{HashMap, HashSet, VecDeque};

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum TreeStem {
    #[default]
    None,
    /// `minecraft:logs`, slimy logs, and mushroom stems.
    Log,
    /// `create:roots`.
    Root,
    /// Bamboo stalk, sugar cane, cactus, and either kelp block.
    VerticalPlant,
    /// Both chorus plant and chorus flower are traversed.
    Chorus,
}

impl TreeStem {
    fn wood(self) -> bool {
        matches!(self, Self::Log | Self::Root)
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct TreeBlock {
    pub stem: TreeStem,
    /// The integer `distance` property, except Minecraft's scaffolding stability distance.
    pub leaf_distance: Option<u32>,
    /// Two for red mushroom caps, three for brown caps, wart blocks and weeping vines.
    pub nondecaying_leaf_radius: Option<u32>,
    /// `create:tree_attachments`.
    pub attachment: bool,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Tree {
    pub logs: Vec<Pos>,
    pub leaves: Vec<Pos>,
    pub attachments: Vec<Pos>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TreePart {
    Attachment,
    Log,
    Leaf,
}

impl TreePart {
    pub fn particles_chance(self) -> f32 {
        match self {
            Self::Attachment => 1.0 / 32.0,
            Self::Log => 0.5,
            Self::Leaf => 0.125,
        }
    }
}

impl Tree {
    /// Java breaks attachments first, then logs, then leaves.
    pub fn actions(&self) -> impl Iterator<Item = (TreePart, Pos)> + '_ {
        [
            (TreePart::Attachment, &self.attachments),
            (TreePart::Log, &self.logs),
            (TreePart::Leaf, &self.leaves),
        ]
        .into_iter()
        .flat_map(|(part, positions)| positions.iter().copied().map(move |pos| (part, pos)))
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SearchError {
    /// The adapter did not provide a snapshot for a queried cell.
    Unavailable(Pos),
    /// A host-defined safety bound for both unique world reads and queue length.
    Limit,
}

/// Call after the start block has been broken, with its former stem kind.
/// Read ordinary air as `Some(TreeBlock::default())`, including out-of-height
/// cells. An unavailable read or exhausted budget discards the entire tree plan.
pub fn find_tree(
    origin: Pos,
    broken: TreeBlock,
    world_height: u32,
    limit: usize,
    read: impl FnMut(Pos) -> Option<TreeBlock>,
) -> Result<Tree, SearchError> {
    let mut search = Search {
        read,
        cache: HashMap::new(),
        limit,
    };
    let Some(above) = shift(origin, [0, 1, 0]) else {
        return Ok(Tree::default());
    };
    let above_state = search.block(above)?;
    match broken.stem {
        TreeStem::VerticalPlant | TreeStem::Chorus if above_state.stem != broken.stem => {
            Ok(Tree::default())
        }
        TreeStem::VerticalPlant => search.vertical(origin, above, world_height),
        TreeStem::Chorus => search.chorus(above),
        _ if search.valid_cut(origin, above)? => search.tree(origin),
        _ => Ok(Tree::default()),
    }
}

struct Search<F> {
    read: F,
    cache: HashMap<Pos, TreeBlock>,
    limit: usize,
}

impl<F: FnMut(Pos) -> Option<TreeBlock>> Search<F> {
    fn block(&mut self, position: Pos) -> Result<TreeBlock, SearchError> {
        if let Some(block) = self.cache.get(&position) {
            return Ok(*block);
        }
        if self.cache.len() >= self.limit {
            return Err(SearchError::Limit);
        }
        let block = (self.read)(position).ok_or(SearchError::Unavailable(position))?;
        self.cache.insert(position, block);
        Ok(block)
    }

    fn vertical(
        &mut self,
        origin: Pos,
        above: Pos,
        world_height: u32,
    ) -> Result<Tree, SearchError> {
        // Create queues the first block above the cut before a scan which starts there again.
        let mut logs = vec![above];
        for offset in 1..world_height {
            let Some(position) = i32::try_from(offset)
                .ok()
                .and_then(|dy| shift(origin, [0, dy, 0]))
            else {
                break;
            };
            if self.block(position)?.stem != TreeStem::VerticalPlant {
                break;
            }
            if logs.len() >= self.limit {
                return Err(SearchError::Limit);
            }
            logs.push(position);
        }
        logs.reverse();
        Ok(Tree {
            logs,
            ..Tree::default()
        })
    }

    fn chorus(&mut self, above: Pos) -> Result<Tree, SearchError> {
        let mut logs = Vec::new();
        let mut visited = HashSet::new();
        let mut frontier = VecDeque::from([above]);
        while let Some(position) = frontier.pop_front() {
            visited.insert(position);
            logs.push(position);
            for next in adjacent(position).filter(|next| !visited.contains(next)) {
                if self.block(next)?.stem != TreeStem::Chorus {
                    continue;
                }
                // Preserve Java's traversal order even where several branches
                // queue the same cell, while bounding dense player-built loops.
                if logs.len() + frontier.len() >= self.limit {
                    return Err(SearchError::Limit);
                }
                frontier.push_back(next);
            }
        }
        logs.reverse();
        Ok(Tree {
            logs,
            ..Tree::default()
        })
    }

    fn valid_cut(&mut self, origin: Pos, above: Pos) -> Result<bool, SearchError> {
        let mut visited = HashSet::from([origin, above]);
        let mut frontier = VecDeque::from([origin, above]);
        while let Some(position) = frontier.pop_front() {
            let stem = self.block(position)?.stem;
            let below = shift(position, [0, -1, 0]);
            let supported = match below {
                Some(below) => self.block(below)?.stem.wood() && below != origin,
                None => false,
            };
            if !stem.wood() {
                continue;
            }
            let lower_layer = position[1] == origin[1];
            if !lower_layer && supported {
                return Ok(false);
            }
            for next in adjacent(position)
                .filter(|next| next[1] >= position[1] && (lower_layer || next[1] == position[1]))
            {
                if visited.insert(next) {
                    frontier.push_back(next);
                }
            }
        }
        Ok(true)
    }

    fn tree(&mut self, origin: Pos) -> Result<Tree, SearchError> {
        let mut tree = Tree::default();
        let mut visited = HashSet::from([origin]);
        let mut frontier = VecDeque::new();
        enqueue(&mut visited, &mut frontier, neighbors(origin, 0, 1));
        let mut has_roots = false;
        while let Some(position) = frontier.pop_front() {
            let stem = self.block(position)?.stem;
            if !stem.wood() {
                continue;
            }
            has_roots |= stem == TreeStem::Root;
            tree.logs.push(position);
            enqueue(&mut visited, &mut frontier, neighbors(position, 0, 1));
        }

        visited.clear();
        enqueue(&mut visited, &mut frontier, tree.logs.iter().copied());
        if has_roots {
            // The original starts downward exploration only from the roots it
            // found in the upward pass and appends newly discovered roots.
            let initial: HashSet<_> = visited.clone();
            while let Some(position) = frontier.pop_front() {
                if self.block(position)?.stem != TreeStem::Root {
                    continue;
                }
                if !initial.contains(&position) {
                    tree.logs.push(position);
                }
                enqueue(&mut visited, &mut frontier, neighbors(position, -1, 0));
            }
            visited.clear();
            enqueue(&mut visited, &mut frontier, tree.logs.iter().copied());
        }

        while let Some(position) = frontier.pop_front() {
            let previous_distance = self.block(position)?.leaf_distance.unwrap_or(0);
            for next in neighbors(position, -1, 1) {
                if visited.contains(&next) {
                    continue;
                }
                let block = self.block(next)?;
                if block.attachment {
                    visited.insert(next);
                    tree.attachments.push(next);
                    continue;
                }
                let radius = next[0].abs_diff(origin[0]).max(next[2].abs_diff(origin[2]));
                if block
                    .nondecaying_leaf_radius
                    .is_some_and(|limit| radius <= limit)
                    || block
                        .leaf_distance
                        .is_some_and(|distance| distance > previous_distance)
                {
                    visited.insert(next);
                    tree.leaves.push(next);
                    frontier.push_back(next);
                }
            }
        }
        Ok(tree)
    }
}

fn enqueue(
    visited: &mut HashSet<Pos>,
    frontier: &mut VecDeque<Pos>,
    next: impl Iterator<Item = Pos>,
) {
    frontier.extend(next.filter(|position| visited.insert(*position)));
}

fn shift(position: Pos, offset: Pos) -> Option<Pos> {
    Some([
        position[0].checked_add(offset[0])?,
        position[1].checked_add(offset[1])?,
        position[2].checked_add(offset[2])?,
    ])
}

fn adjacent(position: Pos) -> impl Iterator<Item = Pos> {
    Direction::ALL
        .into_iter()
        .filter_map(move |dir| shift(position, dir.vector()))
}

fn neighbors(position: Pos, min_y: i32, max_y: i32) -> impl Iterator<Item = Pos> {
    // BlockPos.betweenClosedStream advances X first, then Y, then Z.
    (-1..=1).flat_map(move |z| {
        (min_y..=max_y).flat_map(move |y| (-1..=1).filter_map(move |x| shift(position, [x, y, z])))
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    const ORIGIN: Pos = [0, 0, 0];

    fn block(stem: TreeStem) -> TreeBlock {
        TreeBlock {
            stem,
            ..TreeBlock::default()
        }
    }

    fn leaves(distance: u32) -> TreeBlock {
        TreeBlock {
            leaf_distance: Some(distance),
            ..TreeBlock::default()
        }
    }

    fn plan(broken: TreeStem, blocks: &[(Pos, TreeBlock)]) -> Tree {
        let blocks: HashMap<_, _> = blocks.iter().copied().collect();
        find_tree(ORIGIN, block(broken), 384, 4096, |pos| {
            Some(blocks.get(&pos).copied().unwrap_or_default())
        })
        .unwrap()
    }

    #[test]
    fn saw_only_fells_a_tree_after_the_remaining_trunk_is_unsupported() {
        let log = block(TreeStem::Log);
        let blocks = [
            ([0, 1, 0], log),
            ([1, 1, 0], log),
            ([1, 0, 0], log),
            ([0, 2, 0], log),
        ];
        assert_eq!(plan(TreeStem::Log, &blocks), Tree::default());
        assert_eq!(
            plan(TreeStem::Log, &blocks[..2]).logs,
            [[0, 1, 0], [1, 1, 0]]
        );
    }

    #[test]
    fn distance_gradient_isolates_neighbor_canopies_and_orders_attachments_first() {
        let tree = plan(
            TreeStem::Log,
            &[
                ([0, 1, 0], block(TreeStem::Log)),
                ([1, 1, 0], leaves(1)),
                ([2, 1, 0], leaves(2)),
                ([3, 1, 0], leaves(1)),
                (
                    [0, 2, 0],
                    TreeBlock {
                        attachment: true,
                        ..TreeBlock::default()
                    },
                ),
            ],
        );
        assert_eq!(
            tree.actions().collect::<Vec<_>>(),
            [
                (TreePart::Attachment, [0, 2, 0]),
                (TreePart::Log, [0, 1, 0]),
                (TreePart::Leaf, [1, 1, 0]),
                (TreePart::Leaf, [2, 1, 0]),
            ]
        );
        assert_eq!(TreePart::Attachment.particles_chance(), 1.0 / 32.0);
        assert_eq!(TreePart::Log.particles_chance(), 0.5);
        assert_eq!(TreePart::Leaf.particles_chance(), 0.125);
    }

    #[test]
    fn roots_expand_downwards_but_do_not_pull_in_logs_below_the_cut() {
        let root = block(TreeStem::Root);
        let log = block(TreeStem::Log);
        let tree = plan(
            TreeStem::Log,
            &[
                ([1, 0, 0], root),
                ([2, -1, 0], root),
                ([3, -2, 0], root),
                ([0, 1, 0], log),
                ([1, -1, 0], log),
            ],
        );
        assert_eq!(tree.logs, [[1, 0, 0], [0, 1, 0], [2, -1, 0], [3, -2, 0]]);
    }

    #[test]
    fn vertical_plants_and_chorus_use_top_first_traversals() {
        let stalk = block(TreeStem::VerticalPlant);
        assert_eq!(
            plan(
                TreeStem::VerticalPlant,
                &[([0, 1, 0], stalk), ([0, 2, 0], stalk), ([1, 2, 0], stalk)]
            )
            .logs,
            [[0, 2, 0], [0, 1, 0], [0, 1, 0]]
        );
        let chorus = block(TreeStem::Chorus);
        assert_eq!(
            plan(
                TreeStem::Chorus,
                &[
                    ([0, 1, 0], chorus),
                    ([0, 2, 0], chorus),
                    ([1, 2, 0], chorus)
                ]
            )
            .logs,
            [[1, 2, 0], [0, 2, 0], [0, 1, 0]]
        );
    }

    #[test]
    fn planning_fails_cleanly_at_unloaded_cells_and_on_a_small_budget() {
        let log = block(TreeStem::Log);
        assert_eq!(
            find_tree(ORIGIN, log, 384, 4096, |_| None),
            Err(SearchError::Unavailable([0, 1, 0]))
        );
        assert_eq!(
            find_tree(ORIGIN, log, 384, 1, |_| Some(log)),
            Err(SearchError::Limit)
        );
    }
}
