// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! Dry vertical transit and the ordinary Chute's `ItemHelper.extract(UPTO)`.

pub const ENTRY: f32 = 1.0;
const GRAVITY: f32 = -0.2;
const WAIT: f32 = 0.5;
const PULL_LIMIT: u32 = 16;

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Step {
    Position(f32),
    Output,
}

pub fn step(position: f32, can_output: impl FnOnce() -> bool) -> Step {
    let next = position + GRAVITY;
    if next >= WAIT {
        return Step::Position(next);
    }
    if !can_output() {
        return Step::Position(WAIT);
    }
    if next < 0.0 {
        Step::Output
    } else {
        Step::Position(next)
    }
}

pub struct Source<'a, T> {
    pub slot: usize,
    pub stack: &'a T,
    pub count: u32,
    pub maximum: u32,
}

/// Preserve source order. The first accessible stack chooses the identity;
/// later candidates of that identity are skipped when they would exceed its
/// stack maximum, as in ItemHelper.canItemStackAmountsStack.
pub fn pull_plan<'a, T: 'a>(
    slots: impl IntoIterator<Item = Source<'a, T>>,
    same: impl Fn(&T, &T) -> bool,
) -> Vec<(usize, u32)> {
    let mut result = Vec::new();
    let mut identity = None;
    let mut total = 0;
    for slot in slots {
        let count = slot.count.min(slot.maximum).min(PULL_LIMIT - total);
        if count == 0
            || identity
                .is_some_and(|first| !same(first, slot.stack) || total + count > slot.maximum)
        {
            continue;
        }
        identity = Some(slot.stack);
        result.push((slot.slot, count));
        total += count;
        if total == PULL_LIMIT {
            break;
        }
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn gravity_uses_the_java_f32_threshold_and_waits_at_the_midpoint() {
        let mut pos = ENTRY;
        for expected in [0.8, 0.6, 0.40000004, 0.20000003, 2.9802322e-8] {
            assert_eq!(step(pos, || true), Step::Position(expected));
            pos = expected;
        }
        assert_eq!(step(pos, || true), Step::Output);
        assert_eq!(step(0.6, || false), Step::Position(0.5));
        assert_eq!(step(0.5, || false), Step::Position(0.5));
        assert_eq!(step(0.5, || true), Step::Position(0.3));
        assert_eq!(step(0.10000001, || true), Step::Output);
        assert_eq!(step(0.8, || panic!("above midpoint")), Step::Position(0.6));
    }

    #[test]
    fn slot_order_and_component_identity_match_the_java_pull() {
        let rows = [
            (0, "wheat", 10, 64),
            (1, "plank", 5, 64),
            (4, "tagged wheat", 7, 64),
            (5, "wheat", 12, 64),
        ];
        let slots = rows.iter().map(|(slot, stack, count, maximum)| Source {
            slot: *slot,
            stack,
            count: *count,
            maximum: *maximum,
        });
        assert_eq!(pull_plan(slots, |a, b| a == b), [(0, 10), (5, 6)]);
        let rows = [(0, "small", 6, 8), (1, "small", 4, 8), (2, "small", 2, 8)];
        let slots = rows.iter().map(|(slot, stack, count, maximum)| Source {
            slot: *slot,
            stack,
            count: *count,
            maximum: *maximum,
        });
        assert_eq!(pull_plan(slots, |a, b| a == b), [(0, 6), (2, 2)]);
    }
}
