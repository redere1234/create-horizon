// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! Crop and cut decisions from Java `HarvesterMovementBehaviour`.

use super::Spin;

/// The Flywheel HarvesterActorVisual accumulates rotation from distance.
/// A stall or backwards movement leaves the blade at its current phase.
#[derive(Clone, Copy, Debug, Default)]
pub struct Blade(Spin);

impl Blade {
    pub fn tick(&mut self, distance: f64, active: bool) {
        let degrees = if active {
            let radians = distance * 16.0 / 6.5;
            let degrees = (radians * 180.0 / std::f64::consts::PI) as f32;
            // The division in HarvesterActorVisual is between two Java ints.
            let degrees = (degrees * 3000.0) as i32 / 3000;
            degrees as f32 * 1.25
        } else {
            0.0
        };
        self.0.advance(degrees);
    }

    pub fn angle(self, partial: f32) -> f32 {
        self.0.angle(partial)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Rules {
    pub harvest_partial: bool,
    pub replant: bool,
}

impl Default for Rules {
    fn default() -> Self {
        Self {
            harvest_partial: false,
            replant: true,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Age {
    pub value: u32,
    /// For `age` on generic blocks Java compares to the property's value count minus one.
    pub mature_value: u32,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Plant {
    #[default]
    Other,
    Crop {
        age: Age,
        /// Java compares the whole state with `crop.getStateForAge(0)`.
        matches_default_zero_state: bool,
    },
    Cocoa,
    SweetBerryBush,
    SugarCane,
    GrowingPlant,
    BushOrSpecialPlantable,
    /// An installed Farmer's Delight adapter decides whether its mushroom can be cut.
    CompatMushroom {
        can_cut: bool,
    },
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Block {
    pub plant: Plant,
    /// Any integer property literally named `age`, as opposed to the crop's own age property.
    pub generic_age: Option<Age>,
    pub collision_empty: bool,
    pub leaves: bool,
    /// Air or the `create:non_harvestable` block tag.
    pub excluded: bool,
    pub sugar_cane_variant: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LootTool {
    EmptyHand,
    Shears,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Replacement {
    /// Restore the old fluid's legacy block, or air if the fluid was empty.
    FluidOrAir,
    /// Use `getStateForAge(0)` if it changes block type. Otherwise preserve
    /// every original property except the crop-specific age property.
    ResetCropAge,
    SetGenericAge(u32),
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Harvest {
    pub loot_tool: LootTool,
    pub particles_chance: f32,
    pub replacement: Replacement,
    /// One item is withheld from the first loot stack matching the broken block's item.
    pub reserve_seed: bool,
}

/// Generate loot from the original state before applying the replacement. The
/// adapter checks the replacement's survival after destruction and sets air if
/// the replacement cannot survive. Replanting does not require a matching drop.
pub fn plan(block: Block, rules: Rules) -> Option<Harvest> {
    if block.excluded {
        return None;
    }
    let Plant::Crop {
        age,
        matches_default_zero_state,
    } = block.plant
    else {
        return plan_other(block, rules);
    };
    let mature = if rules.harvest_partial {
        !matches_default_zero_state || !rules.replant
    } else {
        age.value == age.mature_value
    };
    mature.then(|| harvest(block, rules, true, Replacement::ResetCropAge))
}

fn plan_other(block: Block, rules: Rules) -> Option<Harvest> {
    let age_matters = block.collision_empty || block.plant == Plant::Cocoa;
    let crop = age_matters
        && block.generic_age.is_some_and(|age| {
            let uncut_age = u32::from(block.plant == Plant::SweetBerryBush);
            (!rules.replant || age.value > uncut_age)
                && (rules.harvest_partial || age.value == age.mature_value)
        });
    let other = match block.plant {
        Plant::SugarCane => true,
        _ if block.leaves => true,
        Plant::Cocoa => block.generic_age.is_some_and(|age| age.value == 2),
        _ if !block.collision_empty => false,
        Plant::GrowingPlant => true,
        _ if block.generic_age.is_some() => false,
        Plant::BushOrSpecialPlantable => true,
        Plant::CompatMushroom { can_cut } => can_cut,
        _ => false,
    };
    let replacement = match block.plant {
        Plant::SweetBerryBush => Replacement::SetGenericAge(1),
        Plant::GrowingPlant => Replacement::FluidOrAir,
        _ if block.sugar_cane_variant => Replacement::FluidOrAir,
        _ if age_matters && block.generic_age.is_some() => Replacement::SetGenericAge(0),
        _ => Replacement::FluidOrAir,
    };
    (crop || other).then(|| harvest(block, rules, crop, replacement))
}

fn harvest(block: Block, rules: Rules, crop: bool, replacement: Replacement) -> Harvest {
    Harvest {
        loot_tool: if block.leaves {
            LootTool::Shears
        } else {
            LootTool::EmptyHand
        },
        particles_chance: if block.leaves { 0.45 } else { 1.0 },
        replacement: if rules.replant {
            replacement
        } else {
            Replacement::FluidOrAir
        },
        reserve_seed: crop && rules.replant,
    }
}

impl Harvest {
    /// Pass the host's exact matching rule (`ItemHelper.sameItem` compares item
    /// identity). Invoke in loot order and preserve all other stack data.
    pub fn accept_drop(&mut self, matches_block_item: bool, count: u32) -> u32 {
        if self.reserve_seed && matches_block_item && count > 0 {
            self.reserve_seed = false;
            count - 1
        } else {
            count
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn blade_rolls_from_distance_and_keeps_its_phase_when_stopped() {
        let mut blade = Blade::default();
        blade.tick(0.25, true);
        assert_eq!(blade.angle(0.5), 21.875);
        blade.tick(0.25, false);
        assert_eq!(blade.angle(0.5), 43.75);
        for _ in 0..7 {
            blade.tick(0.25, true);
        }
        blade.tick(0.25, true);
        assert_eq!(blade.angle(0.5), 371.875);
        assert_eq!(blade.angle(1.0) % 360.0, 33.75);
    }

    fn crop(value: u32) -> Block {
        Block {
            plant: Plant::Crop {
                age: Age {
                    value,
                    mature_value: 7,
                },
                matches_default_zero_state: value == 0,
            },
            collision_empty: true,
            ..Block::default()
        }
    }

    #[test]
    fn crop_maturity_replant_and_seed_reservation() {
        let rules = Rules::default();
        assert!(plan(crop(6), rules).is_none());
        let mut wheat = plan(crop(7), rules).unwrap();
        assert_eq!(wheat.replacement, Replacement::ResetCropAge);
        assert_eq!(wheat.loot_tool, LootTool::EmptyHand);
        assert_eq!(wheat.accept_drop(false, 1), 1);
        assert_eq!(wheat.accept_drop(true, 3), 2);
        assert_eq!(wheat.accept_drop(true, 2), 2);

        let no_replant = Rules {
            replant: false,
            ..rules
        };
        let mut potatoes = plan(crop(7), no_replant).unwrap();
        assert_eq!(potatoes.replacement, Replacement::FluidOrAir);
        assert_eq!(potatoes.accept_drop(true, 3), 3);
    }

    #[test]
    fn partial_harvest_excludes_only_the_unmodified_youngest_crop_when_replanting() {
        let rules = Rules {
            harvest_partial: true,
            ..Rules::default()
        };
        assert!(plan(crop(1), rules).is_some());
        assert!(plan(crop(0), rules).is_none());
        let different_state = Block {
            plant: Plant::Crop {
                age: Age {
                    value: 0,
                    mature_value: 7,
                },
                matches_default_zero_state: false,
            },
            ..crop(0)
        };
        assert!(plan(different_state, rules).is_some());
        assert!(
            plan(
                crop(0),
                Rules {
                    replant: false,
                    ..rules
                }
            )
            .is_some()
        );
    }

    #[test]
    fn cocoa_berries_cane_and_leaves_follow_distinct_paths() {
        let rules = Rules::default();
        let cocoa = Block {
            plant: Plant::Cocoa,
            generic_age: Some(Age {
                value: 2,
                mature_value: 2,
            }),
            ..Block::default()
        };
        assert_eq!(
            plan(cocoa, rules).unwrap().replacement,
            Replacement::SetGenericAge(0)
        );
        let berries = Block {
            plant: Plant::SweetBerryBush,
            collision_empty: true,
            generic_age: Some(Age {
                value: 3,
                mature_value: 3,
            }),
            ..Block::default()
        };
        assert_eq!(
            plan(berries, rules).unwrap().replacement,
            Replacement::SetGenericAge(1)
        );
        let young_berries = Block {
            generic_age: Some(Age {
                value: 1,
                mature_value: 3,
            }),
            ..berries
        };
        assert!(
            plan(
                young_berries,
                Rules {
                    harvest_partial: true,
                    ..rules
                }
            )
            .is_none()
        );
        let cane = Block {
            plant: Plant::SugarCane,
            sugar_cane_variant: true,
            ..Block::default()
        };
        let mut cane_cut = plan(cane, rules).unwrap();
        assert_eq!(cane_cut.replacement, Replacement::FluidOrAir);
        assert_eq!(cane_cut.accept_drop(true, 3), 3);
        let leaves = Block {
            leaves: true,
            ..Block::default()
        };
        let sheared = plan(leaves, rules).unwrap();
        assert_eq!(sheared.loot_tool, LootTool::Shears);
        assert_eq!(sheared.particles_chance, 0.45);
        assert!(
            plan(
                Block {
                    excluded: true,
                    ..leaves
                },
                rules
            )
            .is_none()
        );
    }

    #[test]
    fn only_growing_plants_or_recognized_bushes_are_cut_as_non_crops() {
        let rules = Rules::default();
        let empty = Block {
            collision_empty: true,
            ..Block::default()
        };
        assert!(plan(empty, rules).is_none());
        let bush = Block {
            plant: Plant::BushOrSpecialPlantable,
            ..empty
        };
        assert!(plan(bush, rules).is_some());
        assert!(
            plan(
                Block {
                    generic_age: Some(Age {
                        value: 0,
                        mature_value: 3
                    }),
                    ..bush
                },
                rules
            )
            .is_none()
        );
        let growing = Block {
            plant: Plant::GrowingPlant,
            generic_age: Some(Age {
                value: 0,
                mature_value: 25,
            }),
            ..empty
        };
        assert_eq!(
            plan(growing, rules).unwrap().replacement,
            Replacement::FluidOrAir
        );
    }
}
