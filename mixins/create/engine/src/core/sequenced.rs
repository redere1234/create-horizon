// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT
//! The saved step and weighted result rules from SequencedAssemblyRecipe.

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Progress {
    pub step: i32,
    pub fraction: f32,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Step {
    pub recipe_index: usize,
    pub next: Option<Progress>,
}

/// Step zero starts a new recipe. The last step rolls the output instead of
/// creating a completed intermediate item.
pub fn step(sequence_len: usize, loops: u32, step: i32) -> Option<Step> {
    let length = i32::try_from(sequence_len).ok()?;
    let loops = i32::try_from(loops).ok()?;
    let total = length.checked_mul(loops)?;
    if !(0..total).contains(&step) {
        return None;
    }
    let next = step + 1;
    Some(Step {
        recipe_index: (step % length) as usize,
        next: (next < total).then(|| Progress {
            step: next,
            fraction: next as f32 / total as f32,
        }),
    })
}

pub fn roll_result(weights: &[f32], roll: f32) -> Option<usize> {
    if !(0.0..1.0).contains(&roll)
        || weights
            .iter()
            .any(|weight| !weight.is_finite() || *weight < 0.0)
    {
        return None;
    }
    let total: f32 = weights.iter().sum();
    if !total.is_finite() || total <= 0.0 {
        return None;
    }
    let mut remaining = roll * total;
    weights.iter().position(|weight| {
        remaining -= weight;
        remaining < 0.0
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn precision_mechanism_has_fifteen_steps_with_no_final_intermediate() {
        for index in 0..15 {
            assert_eq!(
                step(3, 5, index),
                Some(Step {
                    recipe_index: index as usize % 3,
                    next: (index < 14).then(|| Progress {
                        step: index + 1,
                        fraction: (index + 1) as f32 / 15.0,
                    }),
                }),
            );
        }
        assert_eq!(step(3, 5, -1), None);
        assert_eq!(step(3, 5, 15), None);
        assert_eq!(step(0, 5, 0), None);
        assert_eq!(step(3, 0, 0), None);
        assert_eq!(step(i32::MAX as usize, 2, 0), None);
    }

    #[test]
    fn weighted_result_matches_source_pool_order_and_strict_boundary() {
        let weights = [120.0, 8.0, 8.0, 5.0, 3.0, 2.0, 2.0, 1.0, 1.0];
        let mut offset = 0.0;
        for (index, weight) in weights.iter().enumerate() {
            assert_eq!(
                roll_result(&weights, (offset + weight / 2.0) / 150.0),
                Some(index)
            );
            offset += weight;
        }
        assert_eq!(roll_result(&[3.0, 1.0], 0.75), Some(1));
        assert_eq!(roll_result(&[0.0, 1.0], 0.0), Some(1));
        assert_eq!(roll_result(&[0.0, 0.0], 0.0), None);
        assert_eq!(roll_result(&[1.0, f32::NAN], 0.0), None);
        assert_eq!(roll_result(&[1.0, -1.0], 0.0), None);
    }
}
