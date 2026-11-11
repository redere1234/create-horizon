// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT
//! Straight-line subset of Create 6.0.10 PipeConnection and FluidNetwork.
//! The caller supplies per-block ticking order and endpoint storage.

/// A pump's default range includes its endpoint, so each half can contain
/// at most this many ordinary pipes.
pub const MAX_PIPES_PER_SIDE: i32 = 15;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Fluid {
    Water,
    Lava,
}

impl Fluid {
    pub fn from_id(id: &str) -> Option<Self> {
        match id {
            "minecraft:water" => Some(Self::Water),
            "minecraft:lava" => Some(Self::Lava),
            _ => None,
        }
    }

    pub fn id(self) -> &'static str {
        match self {
            Self::Water => "minecraft:water",
            Self::Lava => "minecraft:lava",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Flow {
    pub fluid: Fluid,
    pub progress: f32,
}

impl Flow {
    pub fn complete(self) -> Option<Fluid> {
        (self.progress == 1.0).then_some(self.fluid)
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Faces {
    pub inlet: Option<Flow>,
    pub outlet: Option<Flow>,
}

impl Faces {
    pub fn complete(self, fluid: Fluid) -> bool {
        self.inlet.and_then(Flow::complete) == Some(fluid)
            && self.outlet.and_then(Flow::complete) == Some(fluid)
    }

    /// A complete flow can turn around; an incomplete one is cleared on a
    /// single-pressure reversal (`flipFlowsIfPressureReversed`).
    pub fn reversed(self) -> Self {
        Self {
            inlet: self.outlet.filter(|flow| flow.complete().is_some()),
            outlet: self.inlet.filter(|flow| flow.complete().is_some()),
        }
    }

    pub fn tick(&mut self, input: Option<Fluid>, pressure: f32) {
        let internal = self.inlet.and_then(Flow::complete);
        let speed = progress_step(pressure);
        self.inlet = advance(self.inlet, input, speed);
        self.outlet = advance(self.outlet, internal, speed);
    }
}

fn advance(before: Option<Flow>, input: Option<Fluid>, speed: f32) -> Option<Flow> {
    let input = input?;
    let progress = match before {
        Some(flow) if flow.fluid == input => flow.progress,
        Some(_) => return None,
        None => 0.0,
    };
    Some(Flow {
        fluid: input,
        progress: (progress + speed).min(1.0),
    })
}

fn progress_step(pressure: f32) -> f32 {
    1.0 / 32.0 + (pressure / 128.0).clamp(0.0, 1.0) * 31.0 / 32.0
}

pub fn transfer_rate(pressure: f32) -> i32 {
    (pressure / 2.0).max(1.0) as i32
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn six_java_startups_follow_device_registration_order() {
        for (length, pressure, reverse, first, rate) in [
            (1, 32.0, false, 9, 16),
            (3, 32.0, false, 23, 16),
            (5, 32.0, false, 37, 16),
            (3, 32.0, true, 24, 16),
            (3, 4.0, false, 101, 2),
            (3, 64.0, false, 11, 32),
        ] {
            let mut faces = vec![Faces::default(); length];
            let mut first_transfer = None;
            for tick in 1..=115 {
                for i in 0..length {
                    let index = if reverse { length - 1 - i } else { i };
                    let fluid = Fluid::Water;
                    if index == 0 && tick >= 4 && faces.iter().all(|f| f.complete(fluid)) {
                        first_transfer.get_or_insert(tick);
                    }
                    let inlet = if index == 0 {
                        Some(fluid)
                    } else {
                        faces[index - 1].outlet.and_then(Flow::complete)
                    };
                    faces[index].tick(inlet, pressure);
                }
            }
            assert_eq!(first_transfer, Some(first));
            assert_eq!(transfer_rate(pressure), rate);
        }
    }

    #[test]
    fn fluid_switch_clears_the_face_before_restarting() {
        let mut faces = Faces::default();
        faces.tick(Some(Fluid::Water), 128.0);
        faces.tick(Some(Fluid::Lava), 128.0);
        assert_eq!(faces.inlet, None);
        assert_eq!(faces.outlet.and_then(Flow::complete), Some(Fluid::Water));
        faces.tick(Some(Fluid::Lava), 128.0);
        assert_eq!(faces.inlet.and_then(Flow::complete), Some(Fluid::Lava));
        assert_eq!(faces.outlet, None);
    }

    #[test]
    fn reversal_keeps_only_complete_connections() {
        let faces = Faces {
            inlet: Some(Flow {
                fluid: Fluid::Water,
                progress: 1.0,
            }),
            outlet: Some(Flow {
                fluid: Fluid::Water,
                progress: 0.25,
            }),
        };
        assert_eq!(
            faces.reversed(),
            Faces {
                inlet: None,
                outlet: faces.inlet
            }
        );
    }
}
