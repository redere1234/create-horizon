// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! MechanicalBearingBlockEntity controller. The assembly is owned by the
//! host, so a requested disassembly cannot discard it on a failed world write.
use super::transform::java_round;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Mode {
    #[default]
    Place,
    PlaceReturned,
    NeverPlace,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TickAction {
    None,
    Assembled,
    Disassemble,
}

#[derive(Debug, Default)]
pub struct Bearing {
    running: bool,
    angle: f32,
    pending: bool,
    sequence_left: Option<f64>,
}

impl Bearing {
    pub fn resume(angle: f32) -> Self {
        Self {
            running: true,
            angle,
            ..Self::default()
        }
    }

    pub fn running(&self) -> bool {
        self.running
    }

    pub fn angle(&self) -> f32 {
        self.angle
    }

    /// An empty-hand click schedules an assembly or requests immediate
    /// disassembly. The caller must commit before calling disassembled.
    pub fn toggle(&mut self) -> bool {
        if self.running {
            return true;
        }
        self.pending = true;
        false
    }

    /// Returns whether the host should stop the contraption's actors.
    pub fn speed_changed(
        &mut self,
        previous_rpm: f32,
        effective_rpm: f32,
        stalled: bool,
        sequence_angle: Option<f64>,
    ) -> bool {
        self.pending = true;
        self.sequence_left = sequence_angle.filter(|value| value.is_finite() && *value >= 0.0);
        let sign = |rpm: f32| i8::from(rpm > 0.0) - i8::from(rpm < 0.0);
        let stop_actors =
            self.running && previous_rpm != 0.0 && sign(previous_rpm) != sign(effective_rpm);
        if stop_actors && !stalled {
            self.angle = java_round(self.angle) as f32;
        }
        stop_actors
    }

    /// The source uses theoretical RPM to start/stop and effective RPM to
    /// move. On the first successful assembly turn it also advances the angle.
    pub fn tick(
        &mut self,
        theoretical_rpm: f32,
        effective_rpm: f32,
        mode: Mode,
        stalled: bool,
        assemble: impl FnOnce() -> bool,
    ) -> TickAction {
        let mut action = TickAction::None;
        if std::mem::take(&mut self.pending) {
            if self.running {
                let near_start = self.angle.abs() < 22.5 || self.angle.abs() > 337.5;
                if theoretical_rpm == 0.0
                    && (mode == Mode::Place || mode == Mode::PlaceReturned && near_start)
                {
                    return TickAction::Disassemble;
                }
            } else if theoretical_rpm != 0.0 && assemble() {
                self.running = true;
                self.angle = 0.0;
                action = TickAction::Assembled;
            }
        }
        if self.running && !stalled {
            let mut step = effective_rpm * 360.0 / 60.0 / 20.0;
            if let Some(left) = &mut self.sequence_left {
                step = f64::from(step).clamp(-*left, *left) as f32;
                *left = (*left - f64::from(step.abs())).max(0.0);
            }
            self.angle = (self.angle + step) % 360.0;
        }
        action
    }

    pub fn disassembled(&mut self) {
        *self = Self::default();
    }
}
