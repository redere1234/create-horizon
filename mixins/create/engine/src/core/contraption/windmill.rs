// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! BearingContraption sail checks and WindmillBearingBlockEntity motion.
//! The host supplies sail-tag matches from the captured assembly and owns its
//! kinetic network, block writes and persistence.
use std::num::NonZeroUsize;

use super::transform::java_round;

pub const CAPACITY_PER_RPM: f32 = 512.0;
pub const RESTORE_ANGLE: f32 = 0.0;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum RotationDirection {
    #[default]
    Clockwise,
    CounterClockwise,
}

impl RotationDirection {
    pub fn from_scroll_value(value: i32) -> Option<Self> {
        match value {
            0 => Some(Self::Clockwise),
            1 => Some(Self::CounterClockwise),
            _ => None,
        }
    }

    fn sign(self) -> f32 {
        match self {
            Self::Clockwise => 1.0,
            Self::CounterClockwise => -1.0,
        }
    }
}

#[derive(Clone, Copy, Debug)]
pub struct Config {
    pub minimum_sails: usize,
    pub sails_per_rpm: NonZeroUsize,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            minimum_sails: 8,
            sails_per_rpm: NonZeroUsize::new(8).unwrap(),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct InsufficientSails {
    pub found: usize,
    pub required: usize,
}

impl Config {
    /// Run this check before taking ownership of the captured blocks.
    pub fn check_sails(self, sails: usize) -> Result<(), InsufficientSails> {
        if sails < self.minimum_sails {
            return Err(InsufficientSails {
                found: sails,
                required: self.minimum_sails,
            });
        }
        Ok(())
    }

    pub fn rpm(self, sails: usize, direction: RotationDirection) -> f32 {
        (sails / self.sails_per_rpm).clamp(1, 16) as f32 * direction.sign()
    }
}

#[derive(Debug, Default)]
pub struct Windmill {
    running: bool,
    angle: f32,
    assembly_requested: bool,
    queued_reassembly: bool,
    last_generated_rpm: f32,
}

impl Windmill {
    pub fn restored(
        running: bool,
        angle: f32,
        last_generated_rpm: f32,
        queued_reassembly: bool,
    ) -> Self {
        Self {
            running,
            angle,
            last_generated_rpm,
            queued_reassembly,
            ..Self::default()
        }
    }

    pub fn running(&self) -> bool {
        self.running
    }

    pub fn angle(&self) -> f32 {
        self.angle
    }

    pub fn last_generated_rpm(&self) -> f32 {
        self.last_generated_rpm
    }

    pub fn queued_reassembly(&self) -> bool {
        self.queued_reassembly
    }

    /// Returns true when a manual use requests immediate disassembly.
    pub fn toggle(&mut self) -> bool {
        if self.running {
            return true;
        }
        self.assembly_requested = true;
        false
    }

    /// Consume this at the start of the bearing turn. No input RPM is needed.
    pub fn take_assembly_request(&mut self) -> bool {
        std::mem::take(&mut self.assembly_requested) && !self.running
    }

    /// After committing a validated capture, publish the returned RPM before
    /// advancing the angle on this same turn.
    pub fn assembled(&mut self, sails: usize, config: Config, direction: RotationDirection) -> f32 {
        self.running = true;
        self.angle = RESTORE_ANGLE;
        self.publish_generation(Some(sails), config, direction)
    }

    pub fn generated_rpm(
        &self,
        captured_sails: Option<usize>,
        config: Config,
        direction: RotationDirection,
    ) -> f32 {
        if !self.running {
            return 0.0;
        }
        captured_sails.map_or(self.last_generated_rpm, |sails| {
            config.rpm(sails, direction)
        })
    }

    /// Java's generator update caches LastGenerated and cancels QueueAssembly.
    pub fn publish_generation(
        &mut self,
        captured_sails: Option<usize>,
        config: Config,
        direction: RotationDirection,
    ) -> f32 {
        self.last_generated_rpm = self.generated_rpm(captured_sails, config, direction);
        self.queued_reassembly = false;
        self.last_generated_rpm
    }

    /// The generating bearing rounds and stops actors on a kinetic sign
    /// change, but does not request assembly due to changes in the network.
    pub fn speed_changed(&mut self, previous_rpm: f32, effective_rpm: f32, stalled: bool) -> bool {
        let sign = |rpm: f32| i8::from(rpm > 0.0) - i8::from(rpm < 0.0);
        let stop_actors =
            self.running && previous_rpm != 0.0 && sign(previous_rpm) != sign(effective_rpm);
        if stop_actors && !stalled {
            self.angle = java_round(self.angle) as f32;
        }
        stop_actors
    }

    /// Advance using generated RPM while the kinetic network can turn.
    /// A moved bearing queues assembly for the following turn.
    pub fn finish_tick(&mut self, generated_rpm: f32, effective_network_rpm: f32, stalled: bool) {
        if self.running && !stalled {
            let step = if effective_network_rpm == 0.0 {
                0.0
            } else {
                generated_rpm * 360.0 / 60.0 / 20.0
            };
            self.angle = (self.angle + step) % 360.0;
        }

        if std::mem::take(&mut self.queued_reassembly) && !self.running {
            self.assembly_requested = true;
        }
    }

    /// Acknowledge a successful restoration at RESTORE_ANGLE. Returning zero
    /// tells the host to remove this bearing's generation from the network.
    pub fn disassembled(&mut self, for_movement: bool) -> f32 {
        *self = Self {
            queued_reassembly: self.running && for_movement,
            ..Self::default()
        };
        0.0
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sail_threshold_and_integer_generation_match_create_defaults() {
        let config = Config::default();
        assert_eq!(
            config.check_sails(7),
            Err(InsufficientSails {
                found: 7,
                required: 8
            })
        );
        for (sails, rpm) in [
            (8, 1.0),
            (15, 1.0),
            (16, 2.0),
            (127, 15.0),
            (128, 16.0),
            (2048, 16.0),
        ] {
            assert_eq!(config.check_sails(sails), Ok(()));
            assert_eq!(config.rpm(sails, RotationDirection::Clockwise), rpm);
            assert_eq!(config.rpm(sails, RotationDirection::CounterClockwise), -rpm);
        }
    }

    #[test]
    fn use_assembles_without_input_and_overstress_does_not_disassemble() {
        let mut windmill = Windmill::default();
        let config = Config::default();
        assert!(!windmill.speed_changed(0.0, 32.0, false));
        assert!(!windmill.take_assembly_request());
        assert!(!windmill.toggle());
        assert!(windmill.take_assembly_request());

        let rpm = windmill.assembled(32, config, RotationDirection::Clockwise);
        windmill.finish_tick(rpm, rpm, false);
        assert_eq!(windmill.angle(), 1.2);
        assert!(windmill.speed_changed(rpm, 0.0, false));
        windmill.finish_tick(rpm, 0.0, false);
        assert_eq!(windmill.angle(), 1.0);
        assert!(windmill.running());
        assert!(!windmill.take_assembly_request());

        assert!(windmill.toggle());
        assert_eq!(RESTORE_ANGLE, 0.0);
        assert_eq!(windmill.disassembled(false), 0.0);
        assert!(!windmill.running());
    }

    #[test]
    fn saved_generation_and_deferred_reassembly_survive_restore() {
        let direction = RotationDirection::CounterClockwise;
        let config = Config::default();
        let mut windmill = Windmill::restored(true, -30.0, -4.0, false);
        assert_eq!(windmill.generated_rpm(None, config, direction), -4.0);
        assert_eq!(windmill.last_generated_rpm(), -4.0);
        assert_eq!(windmill.generated_rpm(Some(48), config, direction), -6.0);

        windmill.finish_tick(-4.0, -8.0, true);
        assert_eq!(windmill.angle(), -30.0);
        windmill.finish_tick(-4.0, -8.0, false);
        assert_eq!(windmill.angle(), -31.2);

        windmill.disassembled(true);
        assert!(windmill.queued_reassembly());
        assert!(!windmill.take_assembly_request());
        windmill.finish_tick(0.0, 0.0, false);
        assert!(windmill.take_assembly_request());
        assert!(!windmill.take_assembly_request());
    }

    #[test]
    fn a_stopped_network_wraps_the_angle_after_rounding_at_one_revolution() {
        let mut windmill = Windmill::restored(true, 359.9, 2.0, false);
        assert!(windmill.speed_changed(2.0, 0.0, false));
        assert_eq!(windmill.angle(), 360.0);
        windmill.finish_tick(2.0, 0.0, false);
        assert_eq!(windmill.angle(), 0.0);
    }
}
