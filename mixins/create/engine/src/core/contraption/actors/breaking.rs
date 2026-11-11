// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! Shared Java BlockBreakingMovementBehaviour tick and contact rules.

use super::length;
use crate::kinetics::Pos;

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Target {
    pub hardness: f32,
    pub breakable: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ContraptionKind {
    Other,
    Minecart,
    Train,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Step {
    Idle,
    /// Play the hit sound and send the target's crack stage.
    Hit {
        position: Pos,
        progress: u8,
    },
    /// Play the last hit sound, clear cracks and destroy the target. Java
    /// searches upward through any FallingBlock column before destroying a
    /// start block. Dynamic Trees must dispatch their own queue instead.
    Finish {
        position: Pos,
    },
    /// Clear an existing crack overlay on an invalidated or canceled target.
    Clear {
        position: Pos,
    },
}

/// Retain with the actor while it is moving. `stalled` feeds the shared
/// controller and the motion tracker, preserving speed across break ticks.
#[derive(Clone, Copy, Debug, Default)]
pub struct Breaker {
    target: Option<Pos>,
    progress: u8,
    ticks_until_progress: i32,
    stalled: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct BreakState {
    pub target: Option<Pos>,
    pub progress: u8,
    pub ticks_until_progress: i32,
    pub stalled: bool,
}

impl Breaker {
    pub fn state(self) -> BreakState {
        BreakState {
            target: self.target,
            progress: self.progress,
            ticks_until_progress: self.ticks_until_progress,
            stalled: self.stalled,
        }
    }

    pub fn restore(state: BreakState) -> Option<Self> {
        (state.progress < 10
            && state.ticks_until_progress >= 0
            && (!state.stalled || state.target.is_some()))
        .then_some(Self {
            target: state.target,
            progress: state.progress,
            ticks_until_progress: state.ticks_until_progress,
            stalled: state.stalled,
        })
    }

    pub fn stalled(&self) -> bool {
        self.stalled
    }

    /// Call when an active tool first visits a world cell.
    pub fn visit(&mut self, position: Pos, block: Target) {
        if block.breakable {
            self.target = Some(position);
            self.stalled = true;
        }
    }

    /// A Saw looking up or down removes the target set by the common visit.
    pub fn forget_target(&mut self) {
        if self.target.take().is_some() {
            self.stalled = false;
        }
    }

    /// The host updates block identity and hardness at each progress tick.
    pub fn tick(
        &mut self,
        relative_motion: [f64; 3],
        motion: [f64; 3],
        kind: ContraptionKind,
        read_target: impl FnOnce(Pos) -> Target,
    ) -> Step {
        let Some(position) = self.target else {
            self.stalled = false;
            return Step::Idle;
        };
        if relative_motion == [0.0; 3] {
            self.stalled = false;
            return Step::Idle;
        }
        if self.ticks_until_progress > 0 {
            self.ticks_until_progress -= 1;
            return Step::Idle;
        }
        let block = read_target(position);
        if !block.breakable {
            self.stalled = false;
            return if self.progress == 0 {
                Step::Idle
            } else {
                self.cancel()
            };
        }

        let speed = breaking_speed(motion, kind);
        let step = ((speed / block.hardness) as i32).clamp(1, i32::from(10 - self.progress));
        self.progress += step as u8;
        if self.progress == 10 {
            *self = Self::default();
            Step::Finish { position }
        } else {
            self.ticks_until_progress = (block.hardness / speed) as i32;
            Step::Hit {
                position,
                progress: self.progress,
            }
        }
    }

    pub fn cancel(&mut self) -> Step {
        let Some(position) = self.target else {
            return Step::Idle;
        };
        *self = Self::default();
        Step::Clear { position }
    }
}

pub(super) fn breaking_speed(motion: [f64; 3], kind: ContraptionKind) -> f32 {
    let speed = length(motion);
    let animation_speed = if speed < 1.0 / 512.0 {
        0.0
    } else {
        let hundred_rpm_steps = ((speed * 1000.0 + 100.0) as i32) / 100;
        (hundred_rpm_steps * 100) as f32
    };
    let minimum = match kind {
        ContraptionKind::Other => 1.0 / 128.0,
        ContraptionKind::Minecart => 1.0,
        ContraptionKind::Train => 2.0,
    };
    (animation_speed / 500.0).clamp(minimum, 16.0)
}

/// A contact visit through a non-conducting block damages only eligible
/// entities. Filter vehicles, passengers, items and recently placed oriented
/// contraptions in the host before dispatching this result.
pub fn contact_damage(relative_motion: [f64; 3]) -> f32 {
    (6.0 * length(relative_motion).powf(0.4) + 1.0).clamp(2.0, 10.0) as f32
}

pub fn contact_boost(mut motion: [f64; 3]) -> [f64; 3] {
    motion[1] += length(motion) / 4.0;
    let magnitude = length(motion);
    if magnitude <= 4.0 {
        return motion;
    }
    motion.map(|component| component - component / magnitude * (magnitude - 4.0))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn restored_cut_keeps_progress_and_cooldown() {
        let position = [4, 65, 3];
        let target = Target {
            hardness: 2.0,
            breakable: true,
        };
        let motion = [0.4, 0.0, 0.0];
        let advance =
            |cut: &mut Breaker| cut.tick(motion, motion, ContraptionKind::Other, |_| target);
        let mut original = Breaker::default();
        original.visit(position, target);
        assert_eq!(
            advance(&mut original),
            Step::Hit {
                position,
                progress: 1
            }
        );
        let state = original.state();
        let mut restored = Breaker::restore(state).unwrap();
        assert!(restored.stalled());
        for _ in 0..32 {
            assert_eq!(advance(&mut restored), advance(&mut original));
        }
        assert!(!restored.stalled());
        assert!(
            Breaker::restore(BreakState {
                progress: 10,
                ..state
            })
            .is_none()
        );
        assert!(
            Breaker::restore(BreakState {
                target: None,
                ..state
            })
            .is_none()
        );
    }
}
