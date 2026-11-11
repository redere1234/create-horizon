// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

// There is no gameplay wheel-to-RPM interaction in pinned Create 6.0.10.
// Wheel input belongs to ValueSettingsScreen while its board is open.
fn motor_wheel(_game: &mut crate::game::Game<'_>, _steps: f32, _claimed: &mut bool) {}
