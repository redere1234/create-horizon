// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! Game-independent parts, also compiled as the native bundle's engine crate.
#[path = "core/chain_drive.rs"]
pub mod chain_drive;
#[path = "core/kinetics.rs"]
pub mod kinetics;
#[path = "core/placement.rs"]
pub mod placement;
#[path = "core/pressing.rs"]
pub mod pressing;

#[path = "core/depot.rs"]
pub mod depot;

#[path = "core/deployer.rs"]
pub mod deployer;
#[path = "core/sail.rs"]
pub mod sail;

#[path = "core/controls.rs"]
pub mod controls;

#[path = "core/visual.rs"]
pub mod visual;

#[path = "core/waterwheel.rs"]
pub mod waterwheel;

#[path = "core/milling.rs"]
pub mod milling;

#[path = "core/crushing.rs"]
pub mod crushing;

#[path = "core/crafter.rs"]
pub mod crafter;

#[path = "core/fan.rs"]
pub mod fan;

#[path = "core/fan_entities.rs"]
pub mod fan_entities;

#[path = "core/particles.rs"]
pub mod particles;

#[path = "core/source_trig.rs"]
pub mod source_trig;

#[path = "core/transport.rs"]
pub mod transport;

#[path = "core/chute.rs"]
pub mod chute;

#[path = "core/drilling.rs"]
pub mod drilling;
#[path = "core/saw_processing.rs"]
pub mod saw_processing;

#[path = "core/sequenced.rs"]
pub mod sequenced;

#[path = "core/audio.rs"]
pub mod audio;

#[path = "core/basin.rs"]
pub mod basin;

#[path = "core/fluid_transport.rs"]
pub mod fluid_transport;

#[path = "core/burner.rs"]
pub mod burner;

#[path = "core/burner_visual.rs"]
pub mod burner_visual;

#[path = "core/contraption/mod.rs"]
pub mod contraption;
