// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use crate::placement::Direction;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct State {
    pub facing: Direction,
    pub powered: bool,
    pub extended: bool,
}

impl State {
    /// `StickerBlock.neighborChanged` latches on each rising edge.
    pub fn with_signal(self, powered: bool) -> Self {
        Self {
            powered,
            extended: self.extended ^ (powered && !self.powered),
            ..self
        }
    }

    pub fn supported_face(self, side: Direction) -> bool {
        self.extended || side != self.facing
    }

    /// `Contraption.moveBlock` only follows the outgoing front of the latch.
    pub fn attachment(self) -> Option<Direction> {
        self.extended.then_some(self.facing)
    }
}

/// The client StickerBlockEntity advances its linear chaser before applying
/// the most recent block update. Settled contraptions need no chaser.
#[derive(Clone, Copy, Debug)]
pub struct Head {
    previous: f32,
    current: f32,
    target: f32,
}

impl Head {
    pub fn settled(extended: bool) -> Self {
        let value = if extended { 1.0 } else { 0.0 };
        Self {
            previous: value,
            current: value,
            target: value,
        }
    }

    /// Returns whether the head reached the support or started withdrawing.
    pub fn tick(&mut self, update: Option<bool>) -> (bool, bool) {
        self.previous = self.current;
        let current = f64::from(self.current);
        let delta = f64::from(self.target) - current;
        let speed = f64::from(0.4_f32);
        self.current = if delta.abs() < 1.0e-5 {
            self.target
        } else {
            (current + delta.clamp(-speed, speed)) as f32
        };
        let attached = self.current == 1.0 && self.previous != self.current;
        let detached = update == Some(false) && self.target == 1.0;
        if let Some(extended) = update {
            self.target = if extended { 1.0 } else { 0.0 };
        }
        (attached, detached)
    }

    pub fn idle(self) -> bool {
        self.previous == self.current && self.current == self.target
    }

    pub fn offset(self, partial: f32) -> f32 {
        let previous = f64::from(self.previous);
        let extension =
            (previous + f64::from(partial) * (f64::from(self.current) - previous)) as f32;
        extension * extension * 0.25
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sticker_head_ticks_before_accepting_the_new_target() {
        let mut head = Head::settled(false);
        assert_eq!(head.tick(Some(true)), (false, false));
        assert_eq!(head.offset(1.0), 0.0);
        assert_eq!(head.tick(None), (false, false));
        assert!((head.offset(0.5) - 0.01).abs() < 1e-6);
        assert_eq!(head.tick(None), (false, false));
        assert_eq!(head.tick(Some(false)), (true, true));
        assert_eq!(head.offset(1.0), 0.25);
        assert!(!head.idle());
        assert_eq!(head.tick(None), (false, false));
        assert!((head.offset(1.0) - 0.09).abs() < 1e-6);
        for _ in 0..3 {
            assert_eq!(head.tick(None), (false, false));
        }
        assert!(head.idle());
    }

    #[test]
    fn initial_power_is_not_an_edge_and_only_rising_edges_toggle() {
        let mut state = State {
            facing: Direction::Down,
            powered: true,
            extended: false,
        };
        for (signal, extended) in [
            (true, false),
            (false, false),
            (true, true),
            (true, true),
            (false, true),
            (true, false),
        ] {
            state = state.with_signal(signal);
            assert_eq!((state.powered, state.extended), (signal, extended));
        }
    }

    #[test]
    fn only_the_extended_head_is_adhesive_and_the_closed_face_is_unsupported() {
        for facing in Direction::ALL {
            for extended in [false, true] {
                let state = State {
                    facing,
                    powered: false,
                    extended,
                };
                assert_eq!(state.attachment(), extended.then_some(facing));
                for side in Direction::ALL {
                    assert_eq!(state.supported_face(side), side != facing || extended);
                }
            }
        }
    }
}
