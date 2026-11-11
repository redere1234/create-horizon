// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT
// BeltPressingCallbacks + DepotBehaviour: the unprocessed remainder stays held;
// processed items enter the eight-slot output buffer until the last input.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct PressResult {
    pub input_left: u32,
    pub processed: u32,
    pub output_held: bool,
}

pub fn press(count: u32, bulk: bool) -> Option<PressResult> {
    if count == 0 {
        return None;
    }
    let processed = if bulk { count } else { 1 };
    Some(PressResult {
        input_left: count - processed,
        processed,
        output_held: count == processed,
    })
}

/// DepotBehaviour.tick slides the transported item toward the centre.
pub fn slide(position: f32, angle: i32, upright: bool) -> (f32, i32, bool) {
    let distance = 0.5 - position;
    let next_position = if distance > 1.0 / 512.0 {
        position + distance / 4.0
    } else {
        position
    };
    let next_angle = angle.wrapping_add(i32::from(distance > 1.0 / 32.0 && !upright));
    (next_position, next_angle, distance < 1.0 / 16.0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn depot_releases_processing_using_the_position_at_the_start_of_its_tick() {
        let (mut pos, mut angle) = (0.0, 180);
        for _ in 0..8 {
            let (next, rotated, ready) = slide(pos, angle, false);
            assert!(!ready);
            (pos, angle) = (next, rotated);
        }
        let (next, rotated, ready) = slide(pos, angle, false);
        assert!(ready && next > pos);
        assert_eq!(rotated, 189);
        assert_eq!(slide(pos, angle, true).1, angle);
        assert_eq!(slide(0.5, 180, false), (0.5, 180, true));
    }

    #[test]
    fn default_pressing_preserves_input_and_buffers_each_result_until_the_last() {
        for count in 1..=64 {
            let mut held = count;
            let mut buffered = 0;
            let mut strikes = 0;
            while held > 0 {
                let r = press(held, false).unwrap();
                strikes += 1;
                assert_eq!(r.input_left + r.processed, held);
                if r.output_held {
                    assert_eq!(held, 1);
                } else {
                    buffered += r.processed;
                }
                held = r.input_left;
            }
            assert_eq!(strikes, count);
            assert_eq!(buffered + 1, count);
        }
    }

    #[test]
    fn bulk_is_an_explicit_option_and_empty_input_never_produces_output() {
        assert_eq!(press(0, false), None);
        for count in 1..=64 {
            assert_eq!(
                press(count, true),
                Some(PressResult {
                    input_left: 0,
                    processed: count,
                    output_held: true,
                })
            );
        }
    }
}
