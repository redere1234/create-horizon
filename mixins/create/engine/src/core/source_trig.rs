// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! Trigonometry used by the pinned Create 6.0.10 and Catnip source.
use crate::kinetics::Axis;
use std::sync::OnceLock;

fn sine_table() -> &'static [f32] {
    static TABLE: OnceLock<Box<[f32]>> = OnceLock::new();
    TABLE.get_or_init(|| {
        (0..65536)
            .map(|i| ((f64::from(i) * std::f64::consts::PI * 2.0 / 65536.0).sin()) as f32)
            .collect()
    })
}
/// Pinned Minecraft 1.21.1 `Mth.sin(float)`. Its float index multiplication is
/// different from the newer platform's double-index sine helper.
pub fn sin(angle: f32) -> f32 {
    sine_table()[((angle * 10430.378) as i32 & 65535) as usize]
}
/// Pinned Minecraft 1.21.1 `Mth.cos(float)` uses a float quarter-turn shift
/// before truncating its table index.
pub fn cos(angle: f32) -> f32 {
    sine_table()[((angle * 10430.378 + 16384.0) as i32 & 65535) as usize]
}
pub fn rotate(offset: [f64; 3], degrees: f32, axis: Axis) -> [f64; 3] {
    if degrees == 0.0 {
        return offset;
    }
    // Catnip VecHelper.rotate delegates to the original Mth lookup table.
    let radians = (f64::from(degrees) / 180.0 * std::f64::consts::PI) as f32;
    let sin = f64::from(sin(radians));
    let cos = f64::from(cos(radians));
    let [x, y, z] = offset;
    match axis {
        Axis::X => [x, y * cos - z * sin, z * cos + y * sin],
        Axis::Y => [x * cos + z * sin, y, z * cos - x * sin],
        Axis::Z => [x * cos - y * sin, y * cos + x * sin, z],
    }
}
