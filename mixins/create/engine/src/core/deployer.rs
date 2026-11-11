// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! Deployer timing, hand pose, target geometry and inventory policy from
//! Create 6.0.10. The host supplies world rays and performs item/player actions.

use std::f64::consts::PI;

use crate::{
    contraption::actors::{MotionTracker, Movement, Sample},
    kinetics::Pos,
    placement::Direction,
    source_trig::sin,
};

const STROKE: i32 = 1000;
const REST: i32 = 500;
const IDLE_RETRY_TICKS: i32 = 10;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Mode {
    Punch,
    #[default]
    Use,
}

impl Mode {
    /// New blocks start in Use. The Java NBT reader uses the first enum
    /// constant for an absent or unknown value.
    pub fn from_saved(value: &str) -> Self {
        if value == "USE" {
            Self::Use
        } else {
            Self::Punch
        }
    }

    pub fn saved_name(self) -> &'static str {
        match self {
            Self::Use => "USE",
            Self::Punch => "PUNCH",
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Phase {
    #[default]
    Waiting,
    Expanding,
    Retracting,
    Dumping,
}

impl Phase {
    pub fn from_saved(value: &str) -> Self {
        match value {
            "EXPANDING" => Self::Expanding,
            "RETRACTING" => Self::Retracting,
            "DUMPING" => Self::Dumping,
            _ => Self::Waiting,
        }
    }

    pub fn saved_name(self) -> &'static str {
        match self {
            Self::Waiting => "WAITING",
            Self::Expanding => "EXPANDING",
            Self::Retracting => "RETRACTING",
            Self::Dumping => "DUMPING",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HandPose {
    Pointing,
    Holding,
    Punching,
}

pub fn hand_pose(mode: Mode, has_item: bool) -> HandPose {
    match (mode, has_item) {
        (Mode::Punch, _) => HandPose::Punching,
        (Mode::Use, true) => HandPose::Holding,
        (Mode::Use, false) => HandPose::Pointing,
    }
}

pub fn timer_speed(rpm: f32) -> i32 {
    if rpm == 0.0 {
        0
    } else {
        (rpm * 2.0).abs().clamp(8.0, 512.0) as i32
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Waiting {
    /// The source uses the same backoff for overflow and unnecessary uses.
    Retry,
    Locked,
    Start {
        reach: f32,
    },
    FistBump {
        reach: f32,
    },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TickAction {
    None,
    Started,
    Activate { try_fist_bump: bool },
    Returned,
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Stationary {
    pub phase: Phase,
    pub mode: Mode,
    pub timer: i32,
    /// Reach and fist bump are client update fields in the Java block entity.
    pub reach: f32,
    pub fist_bump: bool,
}

impl Stationary {
    pub fn tick(&mut self, rpm: f32, waiting: impl FnOnce(Mode) -> Waiting) -> TickAction {
        if rpm == 0.0 {
            return TickAction::None;
        }
        let speed = timer_speed(rpm);
        if self.timer > 0 {
            self.timer -= speed;
            return TickAction::None;
        }

        match self.phase {
            Phase::Waiting => match waiting(self.mode) {
                Waiting::Retry => {
                    self.timer = speed * IDLE_RETRY_TICKS;
                    TickAction::None
                }
                Waiting::Locked => TickAction::None,
                decision @ (Waiting::Start { reach } | Waiting::FistBump { reach }) => {
                    self.fist_bump |= matches!(decision, Waiting::FistBump { .. });
                    self.start(reach);
                    TickAction::Started
                }
            },
            Phase::Expanding => {
                self.phase = Phase::Retracting;
                self.timer = STROKE;
                TickAction::Activate {
                    try_fist_bump: self.fist_bump,
                }
            }
            Phase::Retracting => {
                self.phase = Phase::Waiting;
                self.timer = REST;
                TickAction::Returned
            }
            Phase::Dumping => TickAction::None,
        }
    }

    /// Belt processing and a fist-bump partner can also begin the stroke.
    pub fn start(&mut self, reach: f32) {
        self.phase = Phase::Expanding;
        self.timer = STROKE;
        self.reach = reach;
    }

    pub fn hand_extension(self, rpm: f32, partial_tick: f32, has_item: bool) -> f32 {
        let remaining = self.timer as f32 - partial_tick * timer_speed(rpm) as f32;
        let progress = match self.phase {
            Phase::Expanding => {
                let progress = 1.0 - remaining / STROKE as f32;
                if self.fist_bump {
                    progress * progress
                } else {
                    progress
                }
            }
            Phase::Retracting => remaining / STROKE as f32,
            Phase::Waiting | Phase::Dumping => 0.0,
        };
        let hand_length = match hand_pose(self.mode, has_item) {
            HandPose::Pointing => 0.0,
            HandPose::Holding => 4.0 / 16.0,
            HandPose::Punching => 3.0 / 16.0,
        };
        (progress.clamp(0.0, 1.0) * (self.reach + hand_length)).min(21.0 / 16.0)
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Segment {
    pub start: [f64; 3],
    pub end: [f64; 3],
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Aim {
    pub clicked: Pos,
    pub yaw: f32,
    pub pitch: f32,
    body: [f64; 3],
    forward: [f64; 3],
}

impl Aim {
    fn segment(self, start: f64, end: f64) -> Segment {
        let point = |distance| std::array::from_fn(|i| self.body[i] + self.forward[i] * distance);
        Segment {
            start: point(start),
            end: point(end),
        }
    }

    pub fn reach_probe(self) -> Segment {
        self.segment(1.5, 2.5)
    }

    pub fn action_ray(self) -> Segment {
        self.segment(1.5 + 1.0 / 64.0, 2.5 - 1.0 / 64.0)
    }

    /// The reach ray measures the stroke even on a miss, where vanilla
    /// reports the end of the segment. The use ray keeps the prescribed cell.
    pub fn reach(self, hit: [f64; 3]) -> f32 {
        (0.5 + distance(self.reach_probe().start, hit).min(0.75)) as f32
    }
}

fn distance(a: [f64; 3], b: [f64; 3]) -> f64 {
    let [x, y, z] = std::array::from_fn(|i| a[i] - b[i]);
    (x * x + y * y + z * z).sqrt()
}

pub fn stationary_aim(pos: Pos, facing: Direction) -> Option<Aim> {
    let [x, y, z] = facing.vector();
    Some(Aim {
        clicked: [
            pos[0].checked_add(x * 2)?,
            pos[1].checked_add(y * 2)?,
            pos[2].checked_add(z * 2)?,
        ],
        yaw: match facing {
            Direction::South => 0.0,
            Direction::West => 90.0,
            Direction::North => 180.0,
            Direction::East | Direction::Up | Direction::Down => 270.0,
        },
        pitch: (y * -90) as f32,
        body: pos.map(|coordinate| f64::from(coordinate) + 0.5),
        forward: [x, y, z].map(f64::from),
    })
}

pub fn active_point(local_pos: Pos, facing: Direction) -> [f64; 3] {
    let normal = facing.vector();
    std::array::from_fn(|i| f64::from(local_pos[i]) + 0.5 + f64::from(normal[i]) * 2.0)
}

/// DeployerMovementBehaviour uses the base activity rule even on a reverse
/// pass. The caller transforms the active point and supplies carriage motion.
pub fn track_actor(
    tracker: &mut MotionTracker,
    sample: Sample,
    effective_motion: impl FnOnce([f64; 3]) -> [f64; 3],
    inverse_rotation: impl FnOnce([f64; 3]) -> [f64; 3],
) -> Movement {
    tracker.sample_with_activation(sample, effective_motion, inverse_rotation, |_, _| true)
}

/// The caller provides the transformed forward vector and the transformed
/// vertical yaw reference (including initial cart yaw or the train's 90°).
pub fn moving_aim(
    clicked: Pos,
    active_point: [f64; 3],
    forward: [f64; 3],
    vertical_reference: [f64; 3],
) -> Aim {
    let pitch = (forward[1].acos() / PI * 180.0) as f32 - 90.0;
    let ray_direction = if pitch.abs() > 89.0 {
        vertical_reference
    } else {
        forward
    };
    let yaw = ((3.0 * PI / 2.0 + ray_direction[2].atan2(ray_direction[0])) / PI * 180.0) as f32;
    Aim {
        clicked,
        yaw,
        pitch,
        body: std::array::from_fn(|i| active_point[i] - forward[i] * 2.0),
        forward: ray_direction,
    }
}

pub fn moving_extension(
    position: Option<[f64; 3]>,
    motion: [f64; 3],
    stalled_or_stationary_timer: bool,
    disabled: bool,
    render_time: f32,
    partial_tick: f32,
) -> f32 {
    if disabled {
        return 0.0;
    }
    let Some(pos) = position.filter(|_| !stalled_or_stationary_timer) else {
        return sin(render_time * 0.5) * 0.25 + 0.25;
    };
    let center = pos.map(|coordinate| coordinate.floor() + 0.5);
    let before = distance(pos, center);
    let next = distance(std::array::from_fn(|i| pos[i] + motion[i]), center);
    (0.5 - (before + f64::from(partial_tick) * (next - before)).clamp(0.0, 1.0)) as f32
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Held<'a> {
    Empty,
    Block(&'a str),
    FilledBucket(&'a str),
    Other,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Target<'a> {
    pub block: &'a str,
    pub fluid: Option<&'a str>,
    pub transports_items: bool,
}

pub fn should_use(
    held: Held<'_>,
    target: Target<'_>,
    stationary_facing: Option<Direction>,
) -> bool {
    if matches!(held, Held::Block(block) if block == target.block)
        || matches!(held, Held::FilledBucket(fluid) if Some(fluid) == target.fluid)
    {
        return false;
    }
    held == Held::Empty || stationary_facing != Some(Direction::Down) || !target.transports_items
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BeltAction {
    Pass,
    Hold,
    Start,
    Apply,
}

/// BeltDeployerCallbacks. The entrance and already-held callback test power
/// and the availability of a recipe at different points in the stroke.
pub fn belt_action(
    state: Stationary,
    held: bool,
    powered: bool,
    hand_has_item: bool,
    matches_recipe: bool,
) -> BeltAction {
    if !held {
        if state.phase != Phase::Waiting {
            return BeltAction::Hold;
        }
        if powered {
            return BeltAction::Pass;
        }
    }
    if !hand_has_item {
        return BeltAction::Hold;
    }
    if !matches_recipe {
        return BeltAction::Pass;
    }
    if held && state.phase == Phase::Retracting && state.timer == STROKE {
        return BeltAction::Apply;
    }
    if state.phase == Phase::Waiting {
        if powered {
            BeltAction::Pass
        } else {
            BeltAction::Start
        }
    } else {
        BeltAction::Hold
    }
}

/// A downward stationary Deployer delegates item activation to the belt
/// behaviour even if a stroke began with an empty hand.
pub fn station_uses_world(facing: Direction, target: Target<'_>) -> bool {
    facing != Direction::Down || !target.transports_items
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MovingAction {
    Skip,
    World(Mode),
    PrintSchematic,
}

/// The caller attempts the one-item mounted-storage grab before this check.
pub fn moving_action(
    mode: Mode,
    held: Held<'_>,
    target: Target<'_>,
    schematic_filter: bool,
) -> MovingAction {
    if mode == Mode::Use && !should_use(held, target, None) {
        return MovingAction::Skip;
    }
    if schematic_filter {
        MovingAction::PrintSchematic
    } else {
        MovingAction::World(mode)
    }
}

pub fn grabs_from_storage(held_empty: bool, schematic_filter: bool) -> bool {
    held_empty && !schematic_filter
}

/// Move excess stacks in Java inventory order. WAITING handles an existing
/// overflow queue first, so a new drain only starts with an empty queue.
pub fn drain_stationary<T>(
    inventory: &mut [Option<T>],
    selected: usize,
    overflow: &mut Vec<T>,
    matches_filter: impl Fn(&T) -> bool,
) -> bool {
    if !overflow.is_empty() {
        return false;
    }
    for (slot, stack) in inventory.iter_mut().enumerate() {
        if overflow.len() > 10 {
            break;
        }
        if let Some(stack) = stack.take_if(|stack| slot != selected || !matches_filter(stack)) {
            overflow.push(stack);
        }
    }
    !overflow.is_empty()
}

/// Dispose of armor first, then offhand, then ordinary items in slot order.
/// The selected stack stays only while it passes the original filter.
pub fn drain_moving<T>(
    armor: &mut [Option<T>],
    offhand: &mut [Option<T>],
    items: &mut [Option<T>],
    selected: usize,
    matches_filter: impl Fn(&T) -> bool,
    mut dispose: impl FnMut(T),
) {
    for stack in armor.iter_mut().chain(offhand) {
        if let Some(stack) = stack.take() {
            dispose(stack);
        }
    }
    for (index, stack) in items.iter_mut().enumerate() {
        if let Some(stack) = stack.take_if(|stack| index != selected || !matches_filter(stack)) {
            dispose(stack);
        }
    }
}

pub fn insert_count(
    slot: usize,
    overflow_count: usize,
    incoming: u32,
    held: u32,
    stack_limit: u32,
    matches_filter: bool,
    same_item_and_components: bool,
) -> u32 {
    if slot < overflow_count || !matches_filter || held != 0 && !same_item_and_components {
        0
    } else {
        incoming.min(stack_limit.saturating_sub(held))
    }
}

pub fn extract_count(
    slot: usize,
    overflow_count: usize,
    available: u32,
    requested: u32,
    active_filter_matches: bool,
) -> u32 {
    if slot >= overflow_count && active_filter_matches {
        0
    } else {
        requested.min(available)
    }
}

/// The moving actor retries a pending block break after twenty wait turns.
/// The saved timer remains untouched when the underlying break is cancelled.
pub fn stalled_retry(timer: &mut Option<i32>, breaking: Option<Pos>) -> Option<Pos> {
    let target = breaking?;
    let elapsed = timer.get_or_insert(0);
    if *elapsed < 20 {
        *elapsed += 1;
        None
    } else {
        *timer = None;
        Some(target)
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum PunchProgress {
    Clear,
    Continue {
        progress: f32,
        crack_stage: Option<i32>,
    },
    Harvest,
}

pub fn punch_progress(before: f32, destroy_progress: f32) -> PunchProgress {
    let progress = destroy_progress * 16.0 + before;
    if progress >= 1.0 {
        PunchProgress::Harvest
    } else if progress <= 0.0 {
        PunchProgress::Clear
    } else {
        let stage = (progress * 10.0) as i32;
        PunchProgress::Continue {
            progress,
            crack_stage: (stage != (before * 10.0) as i32).then_some(stage),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn belt_entrance_and_held_items_follow_source_state_and_power_order() {
        let waiting = Stationary::default();
        let expanding = Stationary {
            phase: Phase::Expanding,
            ..waiting
        };
        let at_apply = Stationary {
            phase: Phase::Retracting,
            timer: STROKE,
            ..waiting
        };
        let after_apply = Stationary {
            timer: STROKE - 1,
            ..at_apply
        };
        assert_eq!(
            belt_action(waiting, false, true, false, false),
            BeltAction::Pass
        );
        assert_eq!(
            belt_action(waiting, false, false, false, false),
            BeltAction::Hold
        );
        assert_eq!(
            belt_action(waiting, false, false, true, false),
            BeltAction::Pass
        );
        assert_eq!(
            belt_action(waiting, false, false, true, true),
            BeltAction::Start
        );
        assert_eq!(
            belt_action(expanding, false, true, true, false),
            BeltAction::Hold
        );
        assert_eq!(
            belt_action(waiting, true, true, false, false),
            BeltAction::Hold
        );
        assert_eq!(
            belt_action(at_apply, true, true, true, true),
            BeltAction::Apply
        );
        assert_eq!(
            belt_action(after_apply, true, true, true, true),
            BeltAction::Hold
        );
        assert_eq!(
            belt_action(at_apply, true, false, true, false),
            BeltAction::Pass
        );
    }

    #[test]
    fn stationary_planting_matches_the_observed_java_timer_trace() {
        let mut driver = Stationary::default();
        let mut saplings = 3;
        let mut planted = false;
        let mut trace = Vec::new();
        // In the original fixture the motor's own first turn establishes
        // speed. The Deployer begins its stroke on the following server turn.
        for tick in 2..=64 {
            let action = driver.tick(32.0, |_| {
                if planted {
                    Waiting::Retry
                } else {
                    Waiting::Start { reach: 1.25 }
                }
            });
            if matches!(action, TickAction::Activate { .. }) {
                planted = true;
                saplings -= 1;
            }
            trace.push((tick, driver.phase, driver.timer, planted));
        }
        let expanding = trace
            .iter()
            .filter(|row| row.1 == Phase::Expanding)
            .map(|row| row.2)
            .collect::<Vec<_>>();
        assert_eq!(
            expanding,
            (0..=16).map(|tick| 1000 - 64 * tick).collect::<Vec<_>>()
        );
        for (tick, phase, timer, target) in [
            (2, Phase::Expanding, 1000, false),
            (19, Phase::Retracting, 1000, true),
            (36, Phase::Waiting, 500, true),
            (45, Phase::Waiting, 640, true),
            (55, Phase::Waiting, 0, true),
            (56, Phase::Waiting, 640, true),
        ] {
            assert_eq!(trace[tick - 2], (tick, phase, timer, target));
        }
        assert_eq!(saplings, 2);
    }

    #[test]
    fn stationary_wait_polls_only_when_ready_and_reversing_rpm_preserves_cadence() {
        let mut driver = Stationary::default();
        assert_eq!(timer_speed(0.0), 0);
        assert_eq!(timer_speed(1.0), 8);
        assert_eq!(timer_speed(-13.8), 27);
        assert_eq!(timer_speed(300.0), 512);
        assert_eq!(driver.tick(0.0, |_| unreachable!()), TickAction::None);
        assert_eq!(driver.tick(-4.0, |_| Waiting::Locked), TickAction::None);
        assert_eq!(driver.timer, 0);
        assert_eq!(driver.tick(-4.0, |_| Waiting::Retry), TickAction::None);
        assert_eq!(driver.timer, 80);
        assert_eq!(driver.tick(0.0, |_| unreachable!()), TickAction::None);
        assert_eq!(driver.timer, 80);
        for _ in 0..10 {
            assert_eq!(driver.tick(-4.0, |_| unreachable!()), TickAction::None);
        }
        assert_eq!(driver.timer, 0);
    }

    #[test]
    fn stationary_pose_distinguishes_hand_models_and_fist_bump_easing() {
        let mut driver = Stationary::default();
        driver.start(1.25);
        driver.timer = 500;
        assert_eq!(driver.hand_extension(32.0, 0.0, false), 0.625);
        assert_eq!(driver.hand_extension(32.0, 0.0, true), 0.75);
        driver.mode = Mode::Punch;
        driver.fist_bump = true;
        assert_eq!(driver.hand_extension(32.0, 0.0, true), 0.359375);
        driver.phase = Phase::Retracting;
        driver.timer = 1000;
        assert_eq!(driver.hand_extension(32.0, 0.0, true), 21.0 / 16.0);
    }

    #[test]
    fn saves_use_java_enum_names_and_fall_back_to_first_constants() {
        assert_eq!(Mode::default(), Mode::Use);
        assert_eq!(Mode::from_saved(""), Mode::Punch);
        assert_eq!(Mode::from_saved(Mode::Use.saved_name()), Mode::Use);
        assert_eq!(Phase::from_saved("unknown"), Phase::Waiting);
        assert_eq!(
            Phase::from_saved(Phase::Dumping.saved_name()),
            Phase::Dumping
        );
    }

    #[test]
    fn rays_use_the_source_offsets_and_preserve_the_vertical_moving_target() {
        let aim = stationary_aim([1062, 100, 55], Direction::East).unwrap();
        assert_eq!(aim.clicked, [1064, 100, 55]);
        assert_eq!((aim.yaw, aim.pitch), (270.0, 0.0));
        assert_eq!(aim.reach_probe().start, [1064.0, 100.5, 55.5]);
        assert_eq!(aim.reach_probe().end, [1065.0, 100.5, 55.5]);
        assert_eq!(aim.action_ray().start, [1064.015625, 100.5, 55.5]);
        assert_eq!(aim.action_ray().end, [1064.984375, 100.5, 55.5]);
        assert_eq!(aim.reach(aim.reach_probe().end), 1.25);
        assert_eq!(aim.reach([1064.25, 100.5, 55.5]), 0.75);
        assert!(stationary_aim([i32::MAX, 0, 0], Direction::East).is_none());

        let local = active_point([1045, 104, 55], Direction::Down);
        assert_eq!(local, [1045.5, 102.5, 55.5]);
        let actor = moving_aim([1045, 102, 55], local, [0.0, -1.0, 0.0], [0.0, 0.0, 1.0]);
        assert_eq!(actor.clicked, [1045, 102, 55]);
        assert_eq!((actor.yaw, actor.pitch), (360.0, 90.0));
        assert_eq!(actor.action_ray().start, [1045.5, 104.5, 57.015625]);
    }

    #[test]
    fn moving_actor_visits_while_moving_backward_and_preserves_disabled_first_visit() {
        let mut tracker = MotionTracker::default();
        let mut step = |x, disabled, stalled| {
            track_actor(
                &mut tracker,
                Sample {
                    position: [x, 102.5, 55.5],
                    facing: Direction::East,
                    stalled,
                    disabled,
                    allow_stationary_first_visit: false,
                },
                |motion| motion,
                |motion| motion,
            )
        };
        assert_eq!(step(1048.75, false, false).visit, None);
        assert_eq!(step(1048.5, true, false).visit, None);
        assert_eq!(step(1048.25, false, false).visit, Some([1048, 102, 55]));
        assert_eq!(step(1048.0, false, false).visit, None);
        assert_eq!(step(1047.75, false, false).visit, Some([1047, 102, 55]));
        assert_eq!(step(1046.75, false, true).visit, None);
    }

    #[test]
    fn moving_actor_visits_the_four_planting_cells_seen_in_java() {
        let mut tracker = MotionTracker::default();
        let mut visits = Vec::new();
        for tick in 3..=13 {
            // The actor has the previous piston pose when it takes its turn.
            let mut position = active_point([1045, 104, 55], Direction::Down);
            position[0] += f64::from(tick - 3) * 0.25;
            let movement = track_actor(
                &mut tracker,
                Sample {
                    position,
                    facing: Direction::Down,
                    stalled: false,
                    disabled: false,
                    allow_stationary_first_visit: false,
                },
                |motion| motion,
                |motion| motion,
            );
            if let Some(target) = movement.visit {
                visits.push((tick, target));
            }
        }
        assert_eq!(
            visits,
            [
                (4, [1045, 102, 55]),
                (5, [1046, 102, 55]),
                (9, [1047, 102, 55]),
                (13, [1048, 102, 55]),
            ]
        );
    }

    #[test]
    fn moving_pose_uses_cell_center_and_the_original_stall_wave() {
        assert_eq!(
            moving_extension(
                Some([3.5, 4.5, 5.5]),
                [0.5, 0.0, 0.0],
                false,
                false,
                0.0,
                0.5
            ),
            0.25
        );
        assert_eq!(
            moving_extension(None, [0.0; 3], false, false, 0.0, 0.5),
            0.25
        );
        assert_eq!(moving_extension(None, [0.0; 3], true, true, 0.0, 0.5), 0.0);
    }

    #[test]
    fn block_and_bucket_duplicates_skip_without_treating_moving_belts_as_stationary() {
        let target = Target {
            block: "minecraft:oak_sapling",
            fluid: Some("minecraft:water"),
            transports_items: true,
        };
        assert!(!should_use(Held::Block(target.block), target, None));
        assert!(!should_use(
            Held::FilledBucket("minecraft:water"),
            target,
            None
        ));
        assert!(should_use(Held::Empty, target, Some(Direction::Down)));
        assert!(!should_use(Held::Other, target, Some(Direction::Down)));
        assert!(!station_uses_world(Direction::Down, target));
        assert_eq!(
            moving_action(Mode::Use, Held::Other, target, false),
            MovingAction::World(Mode::Use)
        );
        assert_eq!(
            moving_action(Mode::Punch, Held::Block(target.block), target, true),
            MovingAction::PrintSchematic
        );
        assert!(grabs_from_storage(true, false));
        assert!(!grabs_from_storage(true, true));
    }

    #[test]
    fn filtered_inventory_keeps_matching_hand_items_and_ordered_overflow() {
        let mut inventory = (0..14).map(Some).collect::<Vec<_>>();
        let mut overflow = Vec::new();
        assert!(drain_stationary(
            &mut inventory,
            2,
            &mut overflow,
            |&item| item == 2
        ));
        assert_eq!(inventory[2], Some(2));
        assert_eq!(overflow, [0, 1, 3, 4, 5, 6, 7, 8, 9, 10, 11]);
        assert!(!drain_stationary(&mut inventory, 2, &mut overflow, |_| {
            false
        }));
        assert_eq!(insert_count(0, 2, 3, 0, 64, true, true), 0);
        assert_eq!(insert_count(2, 2, 8, 60, 64, true, true), 4);
        assert_eq!(insert_count(2, 2, 8, 60, 64, true, false), 0);
        assert_eq!(extract_count(0, 2, 3, 10, true), 3);
        assert_eq!(extract_count(2, 2, 3, 10, true), 0);

        let mut armor = [Some(11), None];
        let mut offhand = [Some(12)];
        let mut items = [Some(13), Some(2), Some(14)];
        let mut disposed = Vec::new();
        drain_moving(
            &mut armor,
            &mut offhand,
            &mut items,
            1,
            |&item| item == 2,
            |item| disposed.push(item),
        );
        assert_eq!(disposed, [11, 12, 13, 14]);
        assert_eq!(items, [None, Some(2), None]);
    }

    #[test]
    fn moving_punch_retries_on_the_twenty_first_stalled_turn() {
        let target = Some([1, 2, 3]);
        let mut timer = None;
        for _ in 0..20 {
            assert_eq!(stalled_retry(&mut timer, target), None);
        }
        assert_eq!(timer, Some(20));
        assert_eq!(stalled_retry(&mut timer, None), None);
        assert_eq!(timer, Some(20));
        assert_eq!(stalled_retry(&mut timer, target), target);
        assert_eq!(timer, None);
        assert_eq!(punch_progress(0.0, 0.0), PunchProgress::Clear);
        assert_eq!(punch_progress(0.0, 0.0625), PunchProgress::Harvest);
        assert!(matches!(
            punch_progress(0.1, 0.001),
            PunchProgress::Continue {
                crack_stage: None,
                ..
            }
        ));
    }
}
