// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! Item cutting in an upward-facing stationary Mechanical Saw.

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct CuttingCycle {
    pub remaining: f32,
    pub duration: f32,
    pub applied: bool,
    pub recipe_index: usize,
}

impl Default for CuttingCycle {
    fn default() -> Self {
        Self {
            remaining: -1.0,
            duration: 0.0,
            applied: false,
            recipe_index: 0,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Action {
    Idle,
    Start,
    Advance,
    Apply,
    Export,
}

impl CuttingCycle {
    /// Duration for each eligible recipe in the world recipe order. Vanilla
    /// stonecutting uses 50, while Create cutting uses its declared duration.
    pub fn start(&mut self, input_count: u32, recipe_durations: &[u32]) {
        let duration = if recipe_durations.is_empty() {
            10
        } else {
            self.recipe_index = if self.recipe_index >= recipe_durations.len() - 1 {
                0
            } else {
                self.recipe_index + 1
            };
            recipe_durations[self.recipe_index].saturating_mul((input_count / 5).max(1))
        };
        self.duration = duration as f32;
        self.remaining = self.duration;
        self.applied = false;
    }

    /// The recipe list can change between insertion and the application tick.
    pub fn select_current(&mut self, candidates: usize) -> Option<usize> {
        if candidates == 0 {
            return None;
        }
        if self.recipe_index >= candidates {
            self.recipe_index = 0;
        }
        Some(self.recipe_index)
    }

    pub fn tick(&mut self, rpm: f32, has_input: bool) -> Action {
        if rpm == 0.0 || !rpm.is_finite() {
            return Action::Idle;
        }
        if self.remaining == -1.0 {
            return if has_input && !self.applied {
                Action::Start
            } else {
                Action::Idle
            };
        }
        self.remaining -= (rpm.abs() / 24.0).clamp(1.0, 128.0);
        if self.remaining < 5.0 && !self.applied {
            return Action::Apply;
        }
        if self.remaining > 0.0 {
            return Action::Advance;
        }
        self.remaining = 0.0;
        Action::Export
    }

    /// Call after the host commits recipe results. An unmatched stack is
    /// carried through the same output delay and then ejected unchanged.
    pub fn finish_application(&mut self) {
        self.applied = true;
        self.duration = 20.0;
        self.remaining = self.duration;
    }

    pub fn finish_export(&mut self) {
        *self = Self {
            recipe_index: self.recipe_index,
            ..Self::default()
        };
    }
}

/// The pinned 1.21.1 loader inserts recipe IDs in ResourceLocation order
/// into its 8,192-bucket HashMap before building the recipe manager's ordered
/// map. RecipeFinder reads those values, so a lexical name sort changes
/// the output selected by a freshly placed Saw. Other pack sets can differ.
pub fn source_recipe_order(id: &str) -> (u32, &str, &str) {
    fn java_hash(value: &str) -> u32 {
        value.encode_utf16().fold(0u32, |hash, unit| {
            hash.wrapping_mul(31).wrapping_add(u32::from(unit))
        })
    }
    let (namespace, path) = id.split_once(':').unwrap_or(("minecraft", id));
    let hash = java_hash(namespace)
        .wrapping_mul(31)
        .wrapping_add(java_hash(path));
    ((hash ^ (hash >> 16)) & 8191, path, namespace)
}

pub fn automated_recipe(id: &str) -> bool {
    !id.ends_with("_manual_only")
}

/// The native station's matching ingredient and result still come from
/// Horizon. Only the eleven renamed built-in IDs need the 1.21.1 sort key.
/// The four new outputs for ordinary stone were absent from that version.
pub fn stonecutting_source_id(id: &str) -> Option<&str> {
    Some(match id {
        "minecraft:cobblestone_from_stone_stonecutting"
        | "minecraft:cobblestone_slab_from_stone_stonecutting"
        | "minecraft:cobblestone_stairs_from_stone_stonecutting"
        | "minecraft:cobblestone_wall_from_stone_stonecutting" => return None,
        "minecraft:end_stone_brick_slab_from_end_stone_bricks_stonecutting" => {
            "minecraft:end_stone_brick_slab_from_end_stone_brick_stonecutting"
        }
        "minecraft:end_stone_brick_stairs_from_end_stone_bricks_stonecutting" => {
            "minecraft:end_stone_brick_stairs_from_end_stone_brick_stonecutting"
        }
        "minecraft:end_stone_brick_wall_from_end_stone_bricks_stonecutting" => {
            "minecraft:end_stone_brick_wall_from_end_stone_brick_stonecutting"
        }
        "minecraft:mossy_stone_brick_slab_from_mossy_stone_bricks_stonecutting" => {
            "minecraft:mossy_stone_brick_slab_from_mossy_stone_brick_stonecutting"
        }
        "minecraft:mossy_stone_brick_stairs_from_mossy_stone_bricks_stonecutting" => {
            "minecraft:mossy_stone_brick_stairs_from_mossy_stone_brick_stonecutting"
        }
        "minecraft:mossy_stone_brick_wall_from_mossy_stone_bricks_stonecutting" => {
            "minecraft:mossy_stone_brick_wall_from_mossy_stone_brick_stonecutting"
        }
        "minecraft:prismarine_brick_slab_from_prismarine_bricks_stonecutting" => {
            "minecraft:prismarine_brick_slab_from_prismarine_stonecutting"
        }
        "minecraft:prismarine_brick_stairs_from_prismarine_bricks_stonecutting" => {
            "minecraft:prismarine_brick_stairs_from_prismarine_stonecutting"
        }
        "minecraft:quartz_slab_from_quartz_block_stonecutting" => {
            "minecraft:quartz_slab_from_stonecutting"
        }
        "minecraft:chiseled_stone_bricks_from_stone_stonecutting" => {
            "minecraft:chiseled_stone_bricks_stone_from_stonecutting"
        }
        "minecraft:stone_brick_wall_from_stone_stonecutting" => {
            "minecraft:stone_brick_walls_from_stone_stonecutting"
        }
        _ => id,
    })
}

/// Unit vector toward the output edge from SawBlockEntity.getItemMovementVec.
pub fn item_motion(axis_along_first: bool, rpm: f32) -> [i32; 3] {
    let sign = if rpm < 0.0 { -1 } else { 1 };
    if axis_along_first {
        [0, 0, -sign]
    } else {
        [sign, 0, 0]
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn java_oak_log_and_unmatched_item_boundaries_at_128_rpm() {
        for (durations, apply_tick, export_tick) in [(&[50][..], 9, 13), (&[][..], 1, 5)] {
            let mut cycle = CuttingCycle::default();
            assert_eq!(cycle.tick(128.0, true), Action::Start);
            cycle.start(1, durations);
            for tick in 1..=export_tick {
                let action = cycle.tick(128.0, true);
                match tick {
                    tick if tick == apply_tick => {
                        assert_eq!(action, Action::Apply);
                        cycle.finish_application();
                        assert_eq!(cycle.remaining, 20.0);
                    }
                    tick if tick == export_tick => {
                        assert_eq!(action, Action::Export);
                        cycle.finish_export();
                        assert_eq!(cycle.remaining, -1.0);
                    }
                    _ => assert_eq!(action, Action::Advance),
                }
            }
        }
    }

    #[test]
    fn cycles_candidates_rechecks_changed_recipes_and_scales_bulk() {
        let mut cycle = CuttingCycle::default();
        cycle.start(16, &[200, 50, 10]);
        assert_eq!(cycle.select_current(3), Some(1));
        assert_eq!(cycle.duration, 150.0);
        cycle.start(1, &[200, 50, 10]);
        assert_eq!(cycle.select_current(1), Some(0));
        assert_eq!(cycle.duration, 10.0);
        let before = cycle;
        assert_eq!(cycle.tick(0.0, true), Action::Idle);
        assert_eq!(cycle, before);
    }

    #[test]
    fn pinned_order_combines_runtime_and_shipped_bamboo_recipes() {
        let mut recipes = [
            "create:cutting/bamboo_planks",
            "create:cutting/runtime_generated/compat/minecraft/bamboo_planks_to_bamboo_slab",
            "create:cutting/runtime_generated/compat/minecraft/bamboo_planks_to_bamboo_fence_gate",
            "create:cutting/runtime_generated/compat/minecraft/bamboo_planks_to_bamboo_sign",
        ];
        recipes.sort_by_key(|recipe| source_recipe_order(recipe));
        assert!(recipes[0].ends_with("_sign"));
        assert!(recipes[1].ends_with("_fence_gate"));
        assert!(recipes[2].ends_with("/bamboo_planks"));
        assert!(recipes[3].ends_with("_slab"));
        assert!(!automated_recipe("other:result_manual_only"));
        assert!(automated_recipe("other:manual_only/result"));
    }

    #[test]
    fn pinned_stone_cycle_ignores_the_four_new_native_outputs() {
        let mut ids: Vec<_> = [
            "minecraft:chiseled_stone_bricks_from_stone_stonecutting",
            "minecraft:cobblestone_from_stone_stonecutting",
            "minecraft:cobblestone_slab_from_stone_stonecutting",
            "minecraft:cobblestone_stairs_from_stone_stonecutting",
            "minecraft:cobblestone_wall_from_stone_stonecutting",
            "minecraft:stone_bricks_from_stone_stonecutting",
            "minecraft:stone_brick_slab_from_stone_stonecutting",
            "minecraft:stone_brick_stairs_from_stone_stonecutting",
            "minecraft:stone_brick_wall_from_stone_stonecutting",
            "minecraft:stone_slab_from_stone_stonecutting",
            "minecraft:stone_stairs_from_stone_stonecutting",
        ]
        .into_iter()
        .filter_map(stonecutting_source_id)
        .collect();
        ids.sort_by_key(|id| source_recipe_order(id));
        assert_eq!(
            ids,
            [
                "minecraft:chiseled_stone_bricks_stone_from_stonecutting",
                "minecraft:stone_bricks_from_stone_stonecutting",
                "minecraft:stone_stairs_from_stone_stonecutting",
                "minecraft:stone_slab_from_stone_stonecutting",
                "minecraft:stone_brick_slab_from_stone_stonecutting",
                "minecraft:stone_brick_stairs_from_stone_stonecutting",
                "minecraft:stone_brick_walls_from_stone_stonecutting",
            ]
        );
    }

    #[test]
    fn output_direction_reverses_on_both_axes() {
        assert_eq!(item_motion(false, 128.0), [1, 0, 0]);
        assert_eq!(item_motion(false, -128.0), [-1, 0, 0]);
        assert_eq!(item_motion(true, 128.0), [0, 0, -1]);
        assert_eq!(item_motion(true, -128.0), [0, 0, 1]);
    }
}
