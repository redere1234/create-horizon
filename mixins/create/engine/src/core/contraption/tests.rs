// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use std::collections::HashMap;

use super::{
    bearing::{Bearing, Mode, TickAction},
    *,
};
use crate::{
    kinetics::{Axis, Pos},
    placement::Direction,
};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Block {
    Slime,
    Honey,
    Plain,
    Log(Axis),
    Inventory(u8),
}

#[derive(Default)]
struct Scene {
    cells: HashMap<Pos, (BlockRules, Option<Block>)>,
    glue: Vec<(Pos, Direction)>,
    unloaded: Option<Pos>,
}

impl Scene {
    fn insert(&mut self, pos: Pos, block: Block) {
        let rules = BlockRules {
            adhesion: match block {
                Block::Slime => Adhesion::Slime,
                Block::Honey => Adhesion::Honey,
                _ => Adhesion::None,
            },
            ..BlockRules::default()
        };
        self.cells.insert(pos, (rules, Some(block)));
    }
}

impl CaptureView for Scene {
    type Block = Block;

    fn inspect(&self, pos: Pos) -> Cell {
        if Some(pos) == self.unloaded {
            return Cell::Unloaded;
        }
        self.cells
            .get(&pos)
            .map_or(Cell::Empty, |(rules, _)| Cell::Block(*rules))
    }

    fn snapshot(&self, pos: Pos) -> Option<Block> {
        self.cells.get(&pos).and_then(|(_, block)| *block)
    }

    fn glued(&self, pos: Pos, face: Direction) -> bool {
        let delta = face.vector();
        let adjacent = std::array::from_fn(|i| pos[i] + delta[i]);
        self.glue.contains(&(pos, face)) || self.glue.contains(&(adjacent, face.opposite()))
    }
}

const ROOT: Pos = [0; 3];
const EAST: Pos = [1, 0, 0];

#[test]
fn adhesion_and_explicit_attachments_capture_only_connected_blocks() {
    let mut scene = Scene::default();
    scene.insert(ROOT, Block::Slime);
    scene.insert(EAST, Block::Plain);
    scene.insert([-1, 0, 0], Block::Honey);
    scene.insert([0, -1, 0], Block::Plain);
    scene.insert([1, 0, 1], Block::Inventory(7));
    scene.insert([0, 0, 1], Block::Plain);
    scene.cells.get_mut(&[0, 0, 1]).unwrap().0.push_only = true;
    scene.insert([1, 1, 0], Block::Plain);
    let fixture = &mut scene.cells.get_mut(&[1, 1, 0]).unwrap().0;
    fixture.brittle = true;
    fixture.attached[Direction::Down as usize] = true;
    scene.glue.push((EAST, Direction::South));

    let assembled = Assembly::capture(&scene, ROOT, Some([0, -1, 0]), None, 8).unwrap();
    assert_eq!(
        assembled.blocks(),
        &[
            (ROOT, Block::Slime),
            (EAST, Block::Plain),
            ([1, 1, 0], Block::Plain),
            ([1, 0, 1], Block::Inventory(7)),
        ]
    );
}

#[test]
fn forced_push_and_snapshot_limits_report_the_block_that_prevents_capture() {
    let mut scene = Scene::default();
    scene.insert(ROOT, Block::Plain);
    scene.insert(EAST, Block::Inventory(5));
    let capture =
        |scene: &Scene, limit| Assembly::capture(scene, ROOT, None, Some(Direction::East), limit);
    assert_eq!(capture(&scene, 1), Err(CaptureError::TooLarge { limit: 1 }));
    scene.cells.get_mut(&EAST).unwrap().1 = None;
    assert_eq!(capture(&scene, 4), Err(CaptureError::Unsupported(EAST)));
    scene.cells.get_mut(&EAST).unwrap().0.movable = false;
    assert_eq!(capture(&scene, 4), Err(CaptureError::Immovable(EAST)));
    scene.unloaded = Some(EAST);
    assert_eq!(capture(&scene, 4), Err(CaptureError::Unloaded(EAST)));
}

#[test]
fn obstructed_or_unsupported_landing_keeps_the_complete_snapshot_for_retry() {
    let mut scene = Scene::default();
    scene.insert(ROOT, Block::Slime);
    scene.insert(EAST, Block::Inventory(5));
    let shape = Assembly::capture(&scene, ROOT, None, None, 2).unwrap();
    let turn = Rotation::new(ROOT, Axis::Y, 90.0).unwrap().snapped();
    let north = [0, 0, -1];
    assert_eq!(
        shape.landing(ROOT, turn, |block, _| Some(*block), |pos, _| pos != north),
        Err(LandingError::Obstructed(north))
    );
    assert_eq!(
        shape.landing(
            ROOT,
            turn,
            |block, _| (*block == Block::Slime).then_some(*block),
            |_, _| true
        ),
        Err(LandingError::Unsupported(north))
    );
    assert_eq!(
        shape
            .landing(ROOT, turn, |block, _| Some(*block), |_, _| true)
            .unwrap(),
        vec![(ROOT, Block::Slime), (north, Block::Inventory(5))]
    );
}

#[test]
fn transforms_share_the_anchor_and_java_rounding() {
    let anchor = [-17, 128, 10];
    let a = Rotation::new(anchor, Axis::Y, 127.0).unwrap();
    let point = [1.125, -3.375, 4.75];
    for (expected, actual) in point.into_iter().zip(a.to_local(a.to_world(point))) {
        assert!((expected - actual).abs() < 1.0e-12);
    }
    assert_eq!(a.to_world([0.5; 3]), [-16.5, 128.5, 10.5]);
    for (angle, expected) in [
        (44.999_996, EAST),
        (45.0, [0, 0, -1]),
        (-45.0, EAST),
        (-45.000_004, [0, 0, 1]),
        (-135.0, [0, 0, 1]),
        (360.0, EAST),
    ] {
        assert_eq!(
            Rotation::new(ROOT, Axis::Y, angle)
                .unwrap()
                .snapped()
                .place(ROOT, EAST),
            Some(expected)
        );
    }
    assert_eq!(
        Rotation::new(ROOT, Axis::Y, 0.0)
            .unwrap()
            .snapped()
            .place([i32::MAX, 0, 0], EAST),
        None
    );
    assert!(Rotation::new(ROOT, Axis::Y, f32::NAN).is_none());
}

#[test]
fn bearing_matches_the_create_6_0_10_trace_and_log_restoration_on_all_axes() {
    // Recorded from the real Java client with tools/bearing_reference_checks.py.
    let angles = [
        9.6, 19.2, 28.800_001, 38.4, 48.0, 57.6, 67.2, 76.799_995, 86.399_994,
    ];
    for (axis, log, log_axis, target, target_axis) in [
        (Axis::X, [0, 0, 1], Axis::Z, [0, -1, 0], Axis::Y),
        (Axis::Y, [0, 0, 1], Axis::Z, EAST, Axis::X),
        (Axis::Z, EAST, Axis::X, [0, 1, 0], Axis::Y),
    ] {
        let mut scene = Scene::default();
        scene.insert(ROOT, Block::Slime);
        scene.insert(log, Block::Log(log_axis));
        let shape = Assembly::capture(&scene, ROOT, None, None, DEFAULT_MAX_BLOCKS).unwrap();
        let mut bearing = Bearing::default();
        assert!(!bearing.speed_changed(0.0, 32.0, false, None));
        for (tick, angle) in angles.into_iter().enumerate() {
            let action = bearing.tick(32.0, 32.0, Mode::Place, false, || true);
            assert_eq!(
                action,
                if tick == 0 {
                    TickAction::Assembled
                } else {
                    TickAction::None
                }
            );
            assert_eq!(bearing.angle(), angle);
        }
        assert!(bearing.speed_changed(32.0, 0.0, false, None));
        assert_eq!(
            bearing.tick(0.0, 0.0, Mode::Place, false, || unreachable!()),
            TickAction::Disassemble
        );
        let turn = Rotation::new(ROOT, axis, bearing.angle())
            .unwrap()
            .snapped();
        let landing = shape
            .landing(
                ROOT,
                turn,
                |block, turn| {
                    Some(match block {
                        Block::Log(axis) => Block::Log(turn.axis(*axis)),
                        other => *other,
                    })
                },
                |_, _| true,
            )
            .unwrap();
        assert_eq!(
            landing,
            vec![(ROOT, Block::Slime), (target, Block::Log(target_axis))]
        );
        assert!(bearing.running());
        bearing.disassembled();
        assert_eq!(bearing.angle(), 0.0);
        assert!(!bearing.running());
    }
}

#[test]
fn bearing_respects_stall_sequence_limit_and_manual_disassembly() {
    let mut bearing = Bearing::default();
    assert!(!bearing.toggle());
    assert_eq!(
        bearing.tick(0.0, 0.0, Mode::NeverPlace, false, || unreachable!()),
        TickAction::None
    );
    bearing.speed_changed(0.0, 32.0, false, Some(14.0));
    bearing.tick(32.0, 32.0, Mode::NeverPlace, true, || true);
    assert_eq!(bearing.angle(), 0.0);
    for _ in 0..3 {
        bearing.tick(32.0, 32.0, Mode::NeverPlace, false, || unreachable!());
    }
    assert_eq!(bearing.angle(), 14.0);
    assert!(bearing.speed_changed(32.0, -32.0, false, None));
    bearing.tick(-32.0, -32.0, Mode::NeverPlace, false, || unreachable!());
    assert!((bearing.angle() - 4.4).abs() < 1.0e-6);
    bearing.speed_changed(-32.0, 0.0, false, None);
    assert_eq!(
        bearing.tick(0.0, 0.0, Mode::NeverPlace, false, || unreachable!()),
        TickAction::None
    );
    assert!(bearing.toggle());
    assert!(bearing.running());
    bearing.disassembled();
    assert!(!bearing.running());
}
