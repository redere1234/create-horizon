// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! PortableStorageInterfaceMovement and PortableStorageInterfaceBlockEntity.
//! The host resolves item endpoints, inventories, notifications and poses.

use crate::{kinetics::Pos, placement::Direction};

pub const ANIMATION: u32 = 4;
pub const DEFAULT_TIMEOUT: u32 = 60;
const ACTIVE_OFFSET: f64 = 1.85_f32 as f64;
const START: u32 = 6 + ANIMATION * 2;
const KEEP_ALIVE: u8 = 2;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Endpoint {
    pub facing: Direction,
    pub powered: bool,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Docking {
    pub position: Pos,
    pub distance: f32,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Probe {
    position: [f64; 3],
    facing: Option<Direction>,
}

impl Probe {
    /// Transform this local point to world space before creating a probe.
    pub fn local_center(local: Pos, facing: Direction) -> [f64; 3] {
        let normal = facing.vector();
        std::array::from_fn(|i| f64::from(local[i]) + 0.5 + f64::from(normal[i]) * ACTIVE_OFFSET)
    }

    pub fn new(position: [f64; 3], rotated_facing: [f64; 3]) -> Option<Self> {
        cell(position)?;
        if !rotated_facing.iter().all(|component| component.is_finite()) {
            return None;
        }
        let dot = |facing: Direction| {
            let unit = facing.vector().map(f64::from);
            (0..3).map(|i| unit[i] * rotated_facing[i]).sum::<f64>()
        };
        let facing = Direction::ALL
            .into_iter()
            .max_by(|&a, &b| dot(a).total_cmp(&dot(b)))?;
        let unit = facing.vector();
        let error = (0..3)
            .map(|i| (rotated_facing[i] - f64::from(unit[i])).powi(2))
            .sum::<f64>();
        Some(Self {
            position,
            facing: (error <= 0.25).then_some(facing),
        })
    }

    pub fn position(self) -> [f64; 3] {
        self.position
    }

    pub fn grid(self) -> Pos {
        // The constructor checks that each axis can be floored to i32.
        self.position.map(|value| value.floor() as i32)
    }

    fn accepts(self, endpoint: Endpoint) -> bool {
        !endpoint.powered
            && self
                .facing
                .is_some_and(|facing| endpoint.facing == facing.opposite())
    }

    /// The endpoint lookup only returns stationary item interfaces. Check the
    /// probe cell first, then the next cell in its snapped facing direction.
    pub fn find(self, mut endpoint: impl FnMut(Pos) -> Option<Endpoint>) -> Option<Docking> {
        let grid = self.grid();
        let facing = self.facing?;
        let normal = facing.vector();
        for i in 0..2 {
            let target = [
                grid[0].checked_add(i * normal[0])?,
                grid[1].checked_add(i * normal[1])?,
                grid[2].checked_add(i * normal[2])?,
            ];
            if endpoint(target).is_some_and(|end| self.accepts(end)) {
                let axis = facing.axis().index();
                let delta = (f64::from(target[axis]) + 0.5 - self.position[axis]).abs();
                let distance = (delta + ACTIVE_OFFSET - 1.0) as f32;
                return Some(Docking {
                    position: target,
                    distance,
                });
            }
        }
        None
    }

    fn moving_away(self, target: Pos, motion: [f64; 3]) -> bool {
        let center = target.map(|value| f64::from(value) + 0.5);
        let current = (0..3)
            .map(|i| (self.position[i] - center[i]).powi(2))
            .sum::<f64>();
        let next = (0..3)
            .map(|i| (self.position[i] + motion[i] - center[i]).powi(2))
            .sum::<f64>();
        // Vec3.closerThan compares a squared distance with the squared
        // argument returned by the following position's distanceTo call.
        current < next.sqrt().powi(2)
    }
}

fn cell(position: [f64; 3]) -> Option<Pos> {
    position
        .iter()
        .all(|v| (f64::from(i32::MIN)..=f64::from(i32::MAX)).contains(&v.floor()))
        .then(|| position.map(|v| v.floor() as i32))
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Actor {
    working: Option<Pos>,
    stalled: bool,
}

impl Actor {
    pub fn working(self) -> Option<Pos> {
        self.working
    }

    pub fn stalled(self) -> bool {
        self.stalled
    }

    pub fn visit(
        &mut self,
        probe: Option<Probe>,
        endpoint: impl FnMut(Pos) -> Option<Endpoint>,
    ) -> Option<Docking> {
        let docking = probe.and_then(|probe| probe.find(endpoint));
        self.working = docking.map(|d| d.position);
        docking
    }

    /// Tick an established target. The host supplies that position's current
    /// endpoint and station, including any power or facing changes. Returns
    /// whether the station bound itself to the owner again.
    pub fn tick(
        &mut self,
        owner: Pos,
        probe: Option<Probe>,
        motion: [f64; 3],
        target: Option<(Endpoint, &mut Station)>,
    ) -> bool {
        let Some(((position, probe), (endpoint, station))) = self.working.zip(probe).zip(target)
        else {
            self.reset();
            return false;
        };
        if !probe.accepts(endpoint) {
            self.reset();
            return false;
        }
        self.stalled = self.stalled || probe.moving_away(position, motion);
        let started = station.owner().is_none() && station.start(owner, station.distance());
        station.keep_alive = KEEP_ALIVE;
        if station.timer() <= ANIMATION {
            self.stalled = false;
        }
        started
    }

    pub fn reset(&mut self) {
        *self = Self::default();
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TickUpdate {
    None,
    Sync,
    Disconnect { sync: bool },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PowerUpdate {
    Unchanged,
    RefreshActors,
    Disconnect,
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Station {
    timer: u32,
    distance: f32,
    powered: bool,
    owner: Option<Pos>,
    keep_alive: u8,
}

impl Station {
    /// A save stores the visual timer, distance and power, while the world
    /// must rediscover the live inventory owner and keepalive.
    pub fn from_saved(timer: u32, distance: f32, powered: bool) -> Option<Self> {
        (0.0..=2.0).contains(&distance).then_some(Self {
            timer,
            distance,
            powered,
            ..Self::default()
        })
    }

    pub fn timer(self) -> u32 {
        self.timer
    }

    pub fn distance(self) -> f32 {
        self.distance
    }

    pub fn owner(self) -> Option<Pos> {
        self.owner
    }

    pub fn powered(self) -> bool {
        self.powered
    }

    pub fn start(&mut self, owner: Pos, distance: f32) -> bool {
        if self.owner == Some(owner) {
            return false;
        }
        self.distance = distance.min(2.0);
        self.owner = Some(owner);
        self.timer = START;
        true
    }

    pub fn disconnect(&mut self) {
        self.owner = None;
    }

    pub fn set_powered(&mut self, powered: bool) -> PowerUpdate {
        if self.powered == powered {
            return PowerUpdate::Unchanged;
        }
        self.powered = powered;
        if powered {
            self.disconnect();
            PowerUpdate::Disconnect
        } else {
            PowerUpdate::RefreshActors
        }
    }

    pub fn tick(&mut self, timeout: u32) -> TickUpdate {
        if self.keep_alive > 0 {
            self.keep_alive -= 1;
            if self.keep_alive == 0 {
                self.disconnect();
                self.timer = ANIMATION - 1;
                return TickUpdate::Disconnect { sync: true };
            }
        }
        self.timer = self
            .timer
            .min(window_end(timeout).saturating_add(ANIMATION));
        if self.timer > ANIMATION || self.timer > 0 && self.keep_alive == 0 {
            self.timer -= 1;
            let sync = self.timer == ANIMATION - 1;
            if self.timer == 0 || self.powered {
                self.disconnect();
                return TickUpdate::Disconnect { sync };
            }
            if sync {
                return TickUpdate::Sync;
            }
        }
        TickUpdate::None
    }

    pub fn connected(self, timeout: u32) -> bool {
        (ANIMATION..=window_end(timeout)).contains(&self.timer)
    }

    pub fn signal(self, timeout: u32) -> u8 {
        if self.connected(timeout) { 15 } else { 0 }
    }

    pub fn can_transfer(self, timeout: u32) -> bool {
        self.owner.is_some() && self.connected(timeout)
    }

    /// A simulation, refused insertion or empty extraction never restarts the
    /// window. The host calls this after the actual inventory commit.
    pub fn transferred(&mut self, timeout: u32, count: u32, simulate: bool) -> bool {
        if simulate || count == 0 || !self.can_transfer(timeout) {
            return false;
        }
        self.timer = window_end(timeout);
        true
    }

    pub fn extension(self, timeout: u32) -> f32 {
        let end = window_end(timeout);
        let progress = if self.connected(timeout) {
            1.0
        } else if self.timer >= end {
            1.0 - (self.timer - end) as f32 / ANIMATION as f32
        } else {
            self.timer as f32 / ANIMATION as f32
        };
        (f64::from(progress).powi(2) * f64::from(self.distance) / 2.0) as f32
    }
}

fn window_end(timeout: u32) -> u32 {
    timeout.max(1).saturating_add(ANIMATION)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{contraption::Rotation, kinetics::Axis};

    fn endpoint(facing: Direction) -> Endpoint {
        Endpoint {
            facing,
            powered: false,
        }
    }

    #[test]
    fn searches_two_forward_cells_with_opposed_unpowered_endpoints() {
        let probe = Probe::new([1.3, 4.5, -1.2], [1.0, 0.0, 0.0]).unwrap();
        let first = [1, 4, -2];
        let second = [2, 4, -2];
        let west = endpoint(Direction::West);
        let dock = probe.find(|_| Some(west)).unwrap();
        assert_eq!(dock.position, first);
        assert!((dock.distance - 1.05).abs() < 1e-5);
        for rejected in [
            endpoint(Direction::East),
            Endpoint {
                powered: true,
                ..west
            },
        ] {
            let dock = probe
                .find(|pos| {
                    if pos == first {
                        Some(rejected)
                    } else {
                        (pos == second).then_some(west)
                    }
                })
                .unwrap();
            assert_eq!(dock.position, second);
            let mut station = Station::default();
            assert!(station.start([0; 3], dock.distance));
            assert_eq!(station.distance(), 2.0);
        }
        assert!(
            probe
                .find(|pos| (pos == [3, 4, -2]).then_some(west))
                .is_none()
        );
        for (degrees, pairs) in [(28.0_f64, true), (30.0_f64, false)] {
            let (sin, cos) = degrees.to_radians().sin_cos();
            let oblique = Probe::new(probe.position(), [cos, 0.0, -sin]).unwrap();
            assert_eq!(oblique.find(|_| Some(west)).is_some(), pairs);
        }
    }

    #[test]
    fn rotates_and_stalls_on_the_measured_java_bearing_pose() {
        let anchor = [1400, 147, 151];
        let owner = [1400, 146, 151];
        let target = [1400, 147, 147];
        let end = endpoint(Direction::South);
        let mut previous: Option<Probe> = None;
        let mut actor = Actor::default();
        let mut station = Station::default();
        let mut angle = 0.0_f32;
        for tick in 0..=9 {
            let rotation = Rotation::new(anchor, Axis::Y, angle).unwrap();
            let local = Probe::local_center([2, 0, 0], Direction::East);
            let probe = Probe::new(
                rotation.to_world(local),
                rotation.rotate_vector([1.0, 0.0, 0.0]),
            )
            .unwrap();
            if let Some(old) = previous {
                if (tick == 1 || old.grid() != probe.grid())
                    && let Some(dock) =
                        actor.visit(Some(probe), |pos| (pos == target).then_some(end))
                {
                    assert!(station.start(owner, dock.distance));
                }
                let motion = std::array::from_fn(|i| probe.position()[i] - old.position()[i]);
                actor.tick(owner, Some(probe), motion, Some((end, &mut station)));
                assert_eq!(actor.stalled(), tick == 9, "{angle}");
            }
            previous = Some(probe);
            angle += 9.6;
        }
        assert_eq!(actor.working(), Some(target));
        assert_eq!(station.owner(), Some(owner));
        assert_eq!(station.timer(), 14);
        assert!((station.distance() - 1.0076).abs() < 1e-4);
        assert!(station.transferred(DEFAULT_TIMEOUT, 1, false));
        assert_eq!(station.timer(), 64);

        let probe = previous.unwrap();
        for remaining in (4..64).rev() {
            assert_eq!(station.tick(DEFAULT_TIMEOUT), TickUpdate::None);
            assert_eq!(station.timer(), remaining);
            actor.tick(owner, Some(probe), [0.0; 3], Some((end, &mut station)));
            assert_eq!(actor.stalled(), remaining > ANIMATION);
            assert_eq!(station.signal(DEFAULT_TIMEOUT), 15);
        }
        assert_eq!(station.tick(DEFAULT_TIMEOUT), TickUpdate::None);
        assert_eq!(station.timer(), 4);
        assert_eq!(
            station.tick(DEFAULT_TIMEOUT),
            TickUpdate::Disconnect { sync: true }
        );
        assert_eq!(station.timer(), 3);
        assert_eq!(station.signal(DEFAULT_TIMEOUT), 0);
        assert!(!station.can_transfer(DEFAULT_TIMEOUT));
    }

    #[test]
    fn failed_transfers_same_owner_visits_and_power_do_not_refresh_the_window() {
        let mut station = Station::default();
        let owner = [7, 2, -1];
        assert!(station.start(owner, 1.5));
        assert!(!station.transferred(DEFAULT_TIMEOUT, 1, true));
        assert!(!station.transferred(DEFAULT_TIMEOUT, 0, false));
        assert_eq!(station.tick(DEFAULT_TIMEOUT), TickUpdate::None);
        assert!(!station.start(owner, 2.0));
        assert_eq!(station.timer(), 13);
        assert_eq!(station.extension(DEFAULT_TIMEOUT), 0.75);
        assert_eq!(station.set_powered(true), PowerUpdate::Disconnect);
        assert!(!station.can_transfer(DEFAULT_TIMEOUT));
        assert!(!station.transferred(DEFAULT_TIMEOUT, 1, false));
        assert_eq!(station.set_powered(false), PowerUpdate::RefreshActors);
        assert_eq!(station.set_powered(false), PowerUpdate::Unchanged);
        assert!(station.start(owner, 2.0));
    }

    #[test]
    fn configured_timeout_limits_the_animation_and_comparator_window() {
        let mut station = Station::default();
        station.start([0; 3], 2.0);
        assert_eq!(station.signal(3), 0);
        assert_eq!(station.tick(3), TickUpdate::None);
        assert_eq!(station.timer(), 10);
        assert_eq!(station.extension(3), 0.0625);
        for _ in 0..3 {
            station.tick(3);
        }
        assert_eq!(station.timer(), 7);
        assert_eq!(station.signal(3), 15);
        assert_eq!(station.extension(3), 1.0);
    }

    #[test]
    fn a_saved_visual_timer_does_not_recreate_an_inventory_capability() {
        let mut station = Station::from_saved(4, 1.0, false).unwrap();
        assert_eq!(station.owner(), None);
        assert_eq!(station.signal(DEFAULT_TIMEOUT), 15);
        assert!(!station.powered());
        assert!(!station.can_transfer(DEFAULT_TIMEOUT));
        assert_eq!(station.tick(DEFAULT_TIMEOUT), TickUpdate::Sync);
        assert_eq!(station.timer(), 3);
        assert_eq!(station.extension(DEFAULT_TIMEOUT), 0.28125);
        assert!(Station::from_saved(0, f32::NAN, false).is_none());
    }
}
