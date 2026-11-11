// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! Read-only structure capture, local coordinates and driver rules.
//! The host owns block writes, saved data, entities, collision and rendering.
pub mod actors;
mod assembly;
pub mod bearing;
pub mod cart_assembler;
pub mod cart_coupling;
pub mod chassis;
pub mod clockwork;
pub mod contact;
pub mod gantry;
pub mod glue;
pub mod linear;
pub mod piston;
pub mod portable_storage;

pub mod pulley;
pub mod rotary_contact;
pub mod sticker;
mod transform;
pub mod windmill;

pub use assembly::*;
pub use transform::*;

#[cfg(test)]
mod tests;
