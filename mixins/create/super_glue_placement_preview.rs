// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use super::{DryLevel, Game};
use horizon_world::level::{PlaceContext, PlaceOutcome, Ticks};

impl Game<'_> {
    /// Run BlockItem.place on Horizon's disposable level.
    pub(in crate::game) fn create_glue_preview_placement(
        &mut self,
        context: &PlaceContext,
    ) -> Option<[i32; 3]> {
        self.with_level(|behaviours, level, _| {
            match behaviours.place_block(&mut DryLevel::new(level), &mut Ticks::default(), context)
            {
                PlaceOutcome::Placed { pos, .. } => Some([pos.x, pos.y, pos.z]),
                PlaceOutcome::Failed => None,
            }
        })
    }
}
