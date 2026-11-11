// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! Java `SawMovementBehaviour` and `SawBlockEntity.isSawable`.

use super::length;
use crate::kinetics::Pos;

mod tree;

pub use tree::{SearchError, Tree, TreeBlock, TreePart, TreeStem, find_tree};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Material {
    Other,
    LogOrRoot,
    Leaves,
    VerticalPlant,
    PumpkinOrMelon,
    ChorusPlant,
    DynamicBranch,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Target {
    pub material: Material,
    pub hardness: f32,
    /// Air, liquid, saplings, or `create:non_breakable`.
    pub excluded: bool,
}

impl Target {
    pub fn is_sawable(self) -> bool {
        !self.excluded && self.hardness != -1.0 && self.material != Material::Other
    }

    pub fn breaking_target(self) -> super::breaking::Target {
        super::breaking::Target {
            hardness: self.hardness,
            breakable: self.is_sawable(),
        }
    }
}

pub fn vertical(facing: [f64; 3]) -> bool {
    let [x, y, z] = facing.map(|component| (component as f32).abs());
    // Java Direction.getNearest checks Down and Up before horizontal directions.
    y > 0.0 && y >= x && y >= z
}

/// Overflow from felling a tree spawns at each broken block and always tries
/// mounted storage first. This differs from the ordinary actor drop path.
pub fn tree_drop_velocity(
    relative_motion: [f64; 3],
    position: Pos,
    active_point: Option<[f64; 3]>,
) -> [f64; 3] {
    let distance = active_point.map_or(1.0, |point| {
        length(std::array::from_fn(|i| {
            f64::from(position[i]) + 0.5 - point[i]
        })) as f32
    });
    relative_motion.map(|component| component * f64::from(distance / 20.0))
}

#[cfg(test)]
mod tests {
    use super::*;

    use super::super::breaking::{Breaker, ContraptionKind, Step, breaking_speed};
    fn visit(saw: &mut Breaker, position: Pos, facing: [f64; 3], target: Target) {
        saw.visit(position, target.breaking_target());
        if vertical(facing) {
            saw.forget_target();
        }
    }

    const LOG: Target = Target {
        material: Material::LogOrRoot,
        hardness: 2.0,
        excluded: false,
    };
    const POSITION: Pos = [0, 1, 2];
    const EAST: [f64; 3] = [1.0, 0.0, 0.0];
    const MOTION: [f64; 3] = [0.2, 0.0, 0.0];

    #[test]
    fn slow_saw_stalls_then_progresses_on_java_cooldown_ticks() {
        let mut saw = Breaker::default();
        visit(&mut saw, POSITION, EAST, LOG);
        assert!(saw.stalled());
        let mut strikes = Vec::new();
        for tick in 0..40 {
            let step = saw.tick(MOTION, MOTION, ContraptionKind::Other, |_| {
                LOG.breaking_target()
            });
            if step != Step::Idle {
                strikes.push((tick, step));
            }
        }
        assert_eq!(strikes.len(), 10);
        for (index, (tick, step)) in strikes.iter().enumerate() {
            assert_eq!(*tick, index * 4);
            if index == 9 {
                assert_eq!(*step, Step::Finish { position: POSITION });
            } else {
                assert_eq!(
                    *step,
                    Step::Hit {
                        position: POSITION,
                        progress: index as u8 + 1
                    }
                );
            }
        }
        assert!(!saw.stalled());
    }

    #[test]
    fn motion_quantization_and_transport_minima_match_java() {
        assert_eq!(
            breaking_speed([0.001, 0.0, 0.0], ContraptionKind::Other),
            1.0 / 128.0
        );
        assert_eq!(
            breaking_speed([0.002, 0.0, 0.0], ContraptionKind::Other),
            0.2
        );
        assert_eq!(breaking_speed(MOTION, ContraptionKind::Other), 0.6);
        assert_eq!(breaking_speed(MOTION, ContraptionKind::Minecart), 1.0);
        assert_eq!(breaking_speed(MOTION, ContraptionKind::Train), 2.0);
        assert_eq!(
            breaking_speed([100.0, 0.0, 0.0], ContraptionKind::Other),
            16.0
        );
    }

    #[test]
    fn vertical_saw_and_excluded_states_do_not_stall() {
        let mut saw = Breaker::default();
        visit(&mut saw, POSITION, [1.0, -1.0, 0.0], LOG);
        assert!(!saw.stalled());
        visit(
            &mut saw,
            POSITION,
            EAST,
            Target {
                excluded: true,
                ..LOG
            },
        );
        visit(
            &mut saw,
            POSITION,
            EAST,
            Target {
                hardness: -1.0,
                ..LOG
            },
        );
        visit(
            &mut saw,
            POSITION,
            EAST,
            Target {
                material: Material::Other,
                ..LOG
            },
        );
        assert_eq!(
            saw.tick(MOTION, MOTION, ContraptionKind::Other, |_| unreachable!()),
            Step::Idle
        );
        assert!(!saw.stalled());
    }

    #[test]
    fn a_removed_target_clears_cracks_and_releases_the_driver() {
        let mut saw = Breaker::default();
        visit(&mut saw, POSITION, EAST, LOG);
        saw.tick(MOTION, MOTION, ContraptionKind::Other, |_| {
            LOG.breaking_target()
        });
        for _ in 0..3 {
            assert_eq!(
                saw.tick(MOTION, MOTION, ContraptionKind::Other, |_| unreachable!()),
                Step::Idle
            );
        }
        assert_eq!(
            saw.tick(MOTION, MOTION, ContraptionKind::Other, |_| Target {
                excluded: true,
                ..LOG
            }
            .breaking_target()),
            Step::Clear { position: POSITION }
        );
        assert!(!saw.stalled());
    }
}
