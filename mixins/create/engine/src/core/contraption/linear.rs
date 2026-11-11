// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! Server-side offset and stop rules from LinearActuatorBlockEntity.
//! The host owns the assembly until it has committed a requested placement.

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Mode {
    #[default]
    Place,
    PlaceReturned,
    NeverPlace,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Action {
    Hold,
    Move {
        crossed_cell: bool,
        sequence_locked: bool,
    },
    Place {
        grid_offset: u32,
        retry_extension: bool,
    },
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Motion {
    pub from: f32,
    pub to: f32,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum Track {
    Piston,
    Pulley,
}

pub(super) struct Tick {
    pub rpm: f32,
    pub directional_speed: f32,
    pub mode: Mode,
    pub stalled: bool,
    pub track: Track,
}

/// Active actuator. The offset is a distance from the fully retracted
/// position, even for an assembly started with its head already extended.
#[derive(Clone, Debug)]
pub struct LinearActuator {
    initial: u32,
    limit: u32,
    offset: f32,
    waiting: bool,
    refresh: bool,
    sequence_left: Option<f64>,
}

impl LinearActuator {
    pub fn start(initial: u32, limit: u32) -> Option<Self> {
        Self::resume(initial, limit, initial as f32, false, None)
    }

    pub fn resume(
        initial: u32,
        limit: u32,
        offset: f32,
        waiting: bool,
        sequence_left: Option<f64>,
    ) -> Option<Self> {
        if limit == 0
            || initial > limit
            || !(0.0..=limit as f32).contains(&offset)
            || sequence_left.is_some_and(|distance| !distance.is_finite() || distance < 0.0)
        {
            return None;
        }
        Some(Self {
            initial,
            limit,
            offset,
            waiting,
            refresh: false,
            sequence_left,
        })
    }

    pub fn offset(&self) -> f32 {
        self.offset
    }

    pub fn waiting(&self) -> bool {
        self.waiting
    }

    pub fn sequence_left(&self) -> Option<f64> {
        self.sequence_left
    }

    pub fn grid_offset(&self) -> u32 {
        ((self.offset + 0.5) as u32).min(self.limit)
    }

    pub fn request_refresh(&mut self) {
        self.refresh = true;
    }

    pub fn mode_changed(&mut self) {
        self.waiting = false;
    }

    /// Reports whether a sign change must stop the moving block actors.
    pub fn speed_changed(
        &mut self,
        previous_rpm: f32,
        rpm: f32,
        stalled: bool,
        sequence_distance: Option<f64>,
    ) -> bool {
        self.refresh = true;
        self.waiting = false;
        self.sequence_left =
            sequence_distance.filter(|distance| distance.is_finite() && *distance >= 0.0);
        let sign = |value: f32| i8::from(value > 0.0) - i8::from(value < 0.0);
        let stop_actors = previous_rpm != 0.0 && sign(previous_rpm) != sign(rpm);
        if stop_actors && !stalled {
            // Java divides the two integers after Math.round(offset * 16).
            self.offset = (((self.offset * 16.0 + 0.5) as u32) / 16) as f32;
        }
        stop_actors
    }

    fn movement_speed(&self, directional_speed: f32, track: Track) -> f32 {
        let speed = match track {
            Track::Piston => directional_speed.clamp(-self.offset, self.limit as f32 - self.offset),
            Track::Pulley => directional_speed,
        };
        self.sequence_left
            .map_or(speed, |left| f64::from(speed).clamp(-left, left) as f32)
    }

    fn try_place(&mut self, mode: Mode, retry_extension: bool) -> Action {
        let grid_offset = self.grid_offset();
        if mode == Mode::NeverPlace || (mode == Mode::PlaceReturned && grid_offset != self.initial)
        {
            self.waiting = true;
            return Action::Hold;
        }
        Action::Place {
            grid_offset,
            retry_extension,
        }
    }

    /// Run a server tick with the driver's signed movement speed in blocks per
    /// tick. The terrain probe receives the attempted continuous move, after
    /// end stops and the current sequencer allowance have been applied.
    pub fn tick(
        &mut self,
        rpm: f32,
        directional_speed: f32,
        mode: Mode,
        stalled: bool,
        collides: impl FnOnce(Motion) -> bool,
    ) -> Action {
        self.tick_track(
            Tick {
                rpm,
                directional_speed,
                mode,
                stalled,
                track: Track::Piston,
            },
            collides,
            |_| false,
        )
    }

    pub(super) fn tick_track(
        &mut self,
        tick: Tick,
        collides: impl FnOnce(Motion) -> bool,
        catch_payload: impl FnOnce(f32) -> bool,
    ) -> Action {
        let Tick {
            rpm,
            directional_speed,
            mode,
            stalled,
            track,
        } = tick;
        if self.waiting {
            return Action::Hold;
        }
        if std::mem::take(&mut self.refresh) {
            return if rpm == 0.0 {
                self.try_place(mode, false)
            } else {
                Action::Hold
            };
        }

        let movement = self.movement_speed(directional_speed, track);
        let next = self.offset + movement;
        let crossed_cell = next as i32 != self.offset as i32;
        let mut sequence_locked = false;
        if let Some(left) = self.sequence_left.as_mut().filter(|left| **left > 0.0) {
            *left = (*left - f64::from(movement.abs())).max(0.0);
            sequence_locked = *left == 0.0;
        }
        let probe = self.movement_speed(directional_speed, track);
        if crossed_cell && catch_payload(self.offset + probe) {
            // A rope-only pulley lands its physical line before it assembles
            // the block it has reached, independent of the chosen stop mode.
            return self.try_place(Mode::Place, true);
        }

        if stalled {
            return if self.offset == 0.0 || self.offset == self.limit as f32 {
                self.try_place(mode, false)
            } else {
                Action::Hold
            };
        }
        // Java consumes the sequencer allowance before asking for the terrain
        // motion vector again, so the collision probe can differ from newOffset.
        if probe != 0.0
            && collides(Motion {
                from: self.offset,
                to: self.offset + probe,
            })
        {
            self.offset = self.grid_offset() as f32;
            return self.try_place(mode, track == Track::Piston && directional_speed > 0.0);
        }

        self.offset = next;
        if self.offset <= 0.0 || self.offset >= self.limit as f32 {
            self.offset = self.offset.clamp(0.0, self.limit as f32);
            return self.try_place(mode, false);
        }
        if movement == 0.0 && !sequence_locked {
            return Action::Hold;
        }
        Action::Move {
            crossed_cell,
            sequence_locked,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{Action, LinearActuator, Mode};

    #[test]
    fn a_stalled_actuator_at_the_end_still_applies_its_stop_mode() {
        let mut actuator = LinearActuator::resume(0, 4, 4.0, false, None).unwrap();
        assert_eq!(
            actuator.tick(128.0, -0.25, Mode::Place, true, |_| unreachable!()),
            Action::Place {
                grid_offset: 4,
                retry_extension: false
            },
        );
        assert_eq!(
            actuator.tick(128.0, -0.25, Mode::PlaceReturned, true, |_| unreachable!()),
            Action::Hold,
        );
        assert!(actuator.waiting());
    }

    #[test]
    fn end_stops_clamp_and_snap_the_placement_offset() {
        let mut actuator = LinearActuator::start(0, 1).unwrap();
        for _ in 0..3 {
            assert_eq!(
                actuator.tick(128.0, 0.25, Mode::Place, false, |_| false),
                Action::Move {
                    crossed_cell: false,
                    sequence_locked: false,
                }
            );
        }
        assert_eq!(
            actuator.tick(256.0, 0.49, Mode::Place, false, |probe| {
                assert_eq!((probe.from, probe.to), (0.75, 1.0));
                false
            }),
            Action::Place {
                grid_offset: 1,
                retry_extension: false
            }
        );
    }

    #[test]
    fn reversing_rounds_to_the_original_integer_grid_and_pauses_for_one_tick() {
        let mut actuator = LinearActuator::resume(0, 4, 2.93, false, None).unwrap();
        assert!(actuator.speed_changed(64.0, -64.0, false, None));
        assert_eq!(actuator.offset(), 2.0);
        assert_eq!(
            actuator.tick(-64.0, -0.125, Mode::Place, false, |_| panic!(
                "refresh tick does not move"
            )),
            Action::Hold
        );
        assert_eq!(actuator.offset(), 2.0);
        actuator.tick(-64.0, -0.125, Mode::Place, false, |_| false);
        assert_eq!(actuator.offset(), 1.875);
    }

    #[test]
    fn returned_mode_waits_until_the_rounded_start_position() {
        let mut actuator = LinearActuator::resume(2, 4, 0.25, false, None).unwrap();
        assert_eq!(
            actuator.tick(-64.0, -0.25, Mode::PlaceReturned, false, |_| false),
            Action::Hold
        );
        assert!(actuator.waiting());
        actuator.speed_changed(-64.0, 64.0, false, None);
        actuator.tick(64.0, 0.25, Mode::PlaceReturned, false, |_| false);
        for _ in 0..8 {
            actuator.tick(64.0, 0.25, Mode::PlaceReturned, false, |_| false);
        }
        assert_eq!(actuator.grid_offset(), 2);
        actuator.speed_changed(64.0, 0.0, false, None);
        assert_eq!(
            actuator.tick(0.0, 0.0, Mode::PlaceReturned, false, |_| false),
            Action::Place {
                grid_offset: 2,
                retry_extension: false
            }
        );
    }

    #[test]
    fn terrain_collision_rewinds_and_requests_extension_retry() {
        let mut actuator = LinearActuator::resume(0, 4, 1.5, false, None).unwrap();
        assert_eq!(
            actuator.tick(64.0, 0.125, Mode::Place, false, |probe| {
                assert_eq!((probe.from, probe.to), (1.5, 1.625));
                true
            }),
            Action::Place {
                grid_offset: 2,
                retry_extension: true
            }
        );
        assert_eq!(actuator.offset(), 2.0);
    }

    #[test]
    fn a_distance_sequence_consumes_its_last_step_before_the_collision_probe() {
        let mut actuator = LinearActuator::resume(0, 4, 1.5, false, Some(0.0625)).unwrap();
        assert_eq!(
            actuator.tick(64.0, 0.125, Mode::Place, false, |_| panic!(
                "last step uses zero probe motion"
            )),
            Action::Move {
                crossed_cell: false,
                sequence_locked: true
            }
        );
        assert_eq!(actuator.offset(), 1.5625);
        assert_eq!(actuator.sequence_left(), Some(0.0));
    }
}
