// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

//! CartAssemblerBlock, CartAssemblerBlockEntity and MountedContraption rules.

use super::cart_coupling::{dot, norm, normalize};
use crate::{
    kinetics::{Axis, Pos},
    placement::Direction,
};

pub const PASS_COOLDOWN: u8 = 8;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RailKind {
    Regular,
    Powered,
    Detector,
    Activator,
    Controller,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Track {
    EastWest,
    NorthSouth,
}

impl Track {
    pub fn axis(self) -> Axis {
        match self {
            Self::EastWest => Axis::X,
            Self::NorthSouth => Axis::Z,
        }
    }

    fn negative(self) -> Direction {
        match self {
            Self::EastWest => Direction::West,
            Self::NorthSouth => Direction::North,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Rail {
    pub kind: RailKind,
    pub track: Track,
    pub powered: bool,
    pub backwards: bool,
    pub waterlogged: bool,
}

impl Rail {
    /// Wrapping an existing rail requires one of the two flat straight shapes.
    /// The controller rail contributes its stored direction. The assembler's
    /// water and power state begin at the block defaults.
    pub fn wrap(
        kind: RailKind,
        track: Option<Track>,
        controller_backwards: bool,
        player_direction: Direction,
    ) -> Option<Self> {
        let backwards = if kind == RailKind::Controller {
            controller_backwards
        } else {
            player_direction.vector()[player_direction.axis().index()] > 0
        };
        Some(Self {
            kind,
            track: track?,
            powered: false,
            backwards,
            waterlogged: false,
        })
    }

    /// Unwrapping preserves the underlying type, shape and controller direction.
    pub fn unwrap(self) -> Self {
        Self {
            powered: false,
            backwards: self.kind == RailKind::Controller && self.backwards,
            waterlogged: false,
            ..self
        }
    }

    /// The host owns the inventory exchange. Creative players change the rail
    /// without consuming the held rail or getting the original rail back.
    pub fn swap(&mut self, new_kind: RailKind, creative: bool) -> RailSwap {
        if self.kind == new_kind {
            return RailSwap::Unchanged;
        }
        let old = std::mem::replace(&mut self.kind, new_kind);
        if creative {
            RailSwap::Creative
        } else {
            RailSwap::Exchange(old)
        }
    }

    pub fn direction(self) -> Direction {
        let direction = self.track.negative();
        if self.backwards {
            direction.opposite()
        } else {
            direction
        }
    }

    pub fn rotate(self, clockwise_quarters: u8) -> Self {
        let direction = (0..clockwise_quarters % 4).fold(self.direction(), |direction, _| {
            direction.clockwise(Axis::Y)
        });
        let track = if direction.axis() == Axis::X {
            Track::EastWest
        } else {
            Track::NorthSouth
        };
        Self {
            track,
            backwards: direction != track.negative(),
            ..self
        }
    }

    pub fn mirror(self, flipped_axis: Axis) -> Self {
        Self {
            backwards: self.backwards ^ (flipped_axis == self.track.axis()),
            ..self
        }
    }

    pub fn action(self, passenger: Passenger) -> RailAction {
        match (self.kind, self.powered, passenger) {
            (RailKind::Activator, false, _) => RailAction::Pass,
            (RailKind::Regular, false, _) | (RailKind::Activator, true, _) => {
                RailAction::Disassemble
            }
            (RailKind::Regular, true, _) => RailAction::Assemble,
            (RailKind::Controller, true, _) => RailAction::AssembleDirectional,
            (RailKind::Controller | RailKind::Powered, false, _) => RailAction::DisassembleBrake,
            (RailKind::Powered, true, _) | (RailKind::Detector, _, Passenger::Empty) => {
                RailAction::AssembleAccelerate
            }
            (RailKind::Detector, _, _) => RailAction::Disassemble,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RailSwap {
    Unchanged,
    Creative,
    Exchange(RailKind),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CartKind {
    Rideable,
    Furnace,
    Chest,
    Other,
}

impl CartKind {
    pub fn eligible(self) -> bool {
        matches!(self, Self::Rideable | Self::Furnace | Self::Chest)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Passenger {
    Empty,
    Other,
    Mounted,
    CoupledContraption,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RailAction {
    Pass,
    Assemble,
    Disassemble,
    AssembleAccelerate,
    DisassembleBrake,
    AssembleDirectional,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Operation {
    Assemble,
    Disassemble,
}

impl RailAction {
    pub fn operation(self) -> Option<Operation> {
        match self {
            Self::Assemble | Self::AssembleAccelerate | Self::AssembleDirectional => {
                Some(Operation::Assemble)
            }
            Self::Disassemble | Self::DisassembleBrake => Some(Operation::Disassemble),
            Self::Pass => None,
        }
    }

    /// Apply this after the assembly/disassembly attempt, using the cart's
    /// resulting position and motion even when the attempt did not succeed.
    /// `conductors` lists the positive and negative ends of the rail axis.
    pub fn motion_after(
        self,
        rail: Rail,
        assembler: Pos,
        cart: CartMotion,
        [positive, negative]: [bool; 2],
    ) -> Option<[f64; 3]> {
        let speed = f64::from(cart.rail_max_speed);
        let toward = |direction: Direction| direction.vector().map(|step| f64::from(step) * speed);
        match self {
            Self::AssembleAccelerate => {
                if cart.velocity.iter().map(|v| v * v).sum::<f64>() <= (1.0_f64 / 128.0).powi(2) {
                    return None;
                }
                // Catnip visits the positive side first and the negative last.
                let direction = if negative {
                    rail.track.negative().opposite()
                } else if positive {
                    rail.track.negative()
                } else {
                    cart.motion_direction
                };
                Some(toward(direction))
            }
            Self::AssembleDirectional => Some(toward(rail.direction())),
            Self::DisassembleBrake => Some([
                (f64::from(assembler[0]) + 0.5 - cart.position[0]) / 16.0,
                0.0,
                (f64::from(assembler[2]) + 0.5 - cart.position[2]) / 16.0,
            ]),
            _ => None,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct CartMotion {
    pub position: [f64; 3],
    pub velocity: [f64; 3],
    pub motion_direction: Direction,
    pub rail_max_speed: f32,
}

/// Minecart pass callbacks preserve only the first eligible cart. Every
/// block entity tick consumes the queued pass, including a cooldown rejection.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PassQueue<T> {
    cart: Option<T>,
    elapsed: u8,
}

impl<T> Default for PassQueue<T> {
    fn default() -> Self {
        Self {
            cart: None,
            elapsed: PASS_COOLDOWN,
        }
    }
}

impl<T> PassQueue<T> {
    pub fn observe(&mut self, cart: T, kind: CartKind) {
        if kind.eligible() && self.cart.is_none() {
            self.cart = Some(cart);
        }
    }

    /// The host reads the current rail and cart state only after this succeeds.
    /// A pass spends cooldown even if the rail was removed or selects `Pass`.
    pub fn tick(&mut self) -> Option<T> {
        self.elapsed = (self.elapsed + 1).min(PASS_COOLDOWN);
        let cart = self.cart.take()?;
        if self.elapsed != PASS_COOLDOWN {
            return None;
        }
        self.elapsed = 0;
        Some(cart)
    }
}

pub fn assembly_seed(assembler: Pos) -> Option<Pos> {
    Some([assembler[0], assembler[1].checked_add(1)?, assembler[2]])
}

/// The payload count excludes the synthetic minecart anchor. A secondary
/// assembler is represented by an anchor as well, with its rail left in place.
pub fn can_assemble(
    passenger: Passenger,
    coupled_through_contraption: bool,
    payload: usize,
) -> bool {
    passenger == Passenger::Empty && !coupled_through_contraption && payload != 0
}

/// The first aligned secondary assembler in capture order may supply a cart.
/// Iterate its entity query in order. An ineligible cart terminates the scan;
/// Create centers each eligible cart and keeps the last of that prefix.
pub fn secondary_carts<T>(
    primary: Pos,
    secondary: Pos,
    carts: &[(T, CartKind)],
) -> &[(T, CartKind)] {
    if coupled_initial_direction(primary, secondary).is_none() {
        return &[];
    }
    let count = carts.iter().take_while(|(_, kind)| kind.eligible()).count();
    &carts[..count]
}

/// Java maps atan2(secondary Z, secondary X) onto its horizontal yaw basis.
/// Both cart positions have been centered on aligned assembler blocks.
pub fn coupled_initial_direction(primary: Pos, secondary: Pos) -> Option<Direction> {
    use std::cmp::Ordering::*;
    if primary[1] != secondary[1] {
        return None;
    }
    match (secondary[0].cmp(&primary[0]), secondary[2].cmp(&primary[2])) {
        (Greater, Equal) => Some(Direction::South),
        (Less, Equal) => Some(Direction::North),
        (Equal, Greater) => Some(Direction::West),
        (Equal, Less) => Some(Direction::East),
        _ => None,
    }
}

/// The coupled transform uses both cart positions before applying the
/// single-cart rotation mode. Returns yaw and pitch in degrees.
pub fn coupled_angles(leading: [f64; 3], trailing: [f64; 3], rides_leading: bool) -> [f32; 2] {
    let [x, y, z] = std::array::from_fn(|i| leading[i] - trailing[i]);
    let yaw = z.atan2(x).to_degrees() as f32;
    let pitch = y.atan2((x * x + z * z).sqrt()).to_degrees() as f32;
    if rides_leading {
        [yaw + 180.0, -pitch]
    } else {
        [yaw, pitch]
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct CouplingLinks<T> {
    pub leading: Option<T>,
    pub trailing: Option<T>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct CouplingPlan {
    pub length: u32,
    pub reverse_primary_chain: bool,
    pub reverse_secondary_chain: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CouplingError {
    Distance,
    Unloaded,
    Full,
    AlreadyConnected,
    Loop,
}

/// Validate `CouplingHandler.tryToCoupleCarts` for a contraption coupling.
/// Distance is measured after the host centers both carts on their assemblers.
pub fn coupling<T: Copy + Eq>(
    primary: T,
    secondary: T,
    distance: f64,
    max_length: u32,
    read: impl Fn(T) -> Option<CouplingLinks<T>>,
) -> Result<CouplingPlan, CouplingError> {
    if !distance.is_finite() || distance < 2.0 || distance.floor() > f64::from(max_length) {
        return Err(CouplingError::Distance);
    }
    let first = read(primary).ok_or(CouplingError::Unloaded)?;
    let second = read(secondary).ok_or(CouplingError::Unloaded)?;
    if [first, second]
        .into_iter()
        .any(|links| links.leading.is_some() && links.trailing.is_some())
    {
        return Err(CouplingError::Full);
    }
    if first.leading == Some(secondary) || second.leading == Some(primary) {
        return Err(CouplingError::AlreadyConnected);
    }
    for mut current in [first, second] {
        let follow_leading = current.leading.is_some();
        let mut safety = 1000;
        loop {
            if safety == 0 {
                return Err(CouplingError::Loop);
            }
            safety -= 1;
            let link = if follow_leading {
                current.leading
            } else {
                current.trailing
            };
            let Some(id) = link else { break };
            current = read(id).ok_or(CouplingError::Unloaded)?;
            if id == secondary {
                return Err(CouplingError::Loop);
            }
        }
    }
    Ok(CouplingPlan {
        length: distance as u32,
        reverse_primary_chain: first.leading.is_some(),
        reverse_secondary_chain: second.trailing.is_some(),
    })
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Disassembly {
    Single { facing: Direction },
    Coupled,
}

/// Coupled carts can release only when the other loaded cart is also above an
/// assembler that calls for disassembly. The host removes both connections.
pub fn disassembly(
    rail: Rail,
    passenger: Passenger,
    other: Option<(Rail, Passenger)>,
) -> Option<Disassembly> {
    if rail.action(passenger).operation() != Some(Operation::Disassemble) {
        return None;
    }
    match passenger {
        Passenger::Mounted => Some(Disassembly::Single {
            facing: rail.direction(),
        }),
        Passenger::CoupledContraption => {
            let (rail, passenger) = other?;
            (rail.action(passenger).operation() == Some(Operation::Disassemble))
                .then_some(Disassembly::Coupled)
        }
        _ => None,
    }
}

/// Furnace minecart push is cleared on assembly. On ejection Create stores
/// velocity Z in PushX and velocity X in PushZ, before any rail braking.
pub fn furnace_push(kind: CartKind, operation: Operation, velocity: [f64; 3]) -> Option<[f64; 2]> {
    (kind == CartKind::Furnace).then_some(match operation {
        Operation::Assemble => [0.0; 2],
        Operation::Disassemble => [velocity[2], velocity[0]],
    })
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum MovementMode {
    #[default]
    Rotate,
    RotatePaused,
    RotationLocked,
}

impl MovementMode {
    pub fn tick_actors(self, rotating: bool) -> bool {
        self != Self::RotatePaused || !rotating
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct MountedYaw {
    pub previous: f32,
    pub current: f32,
    pub target: f32,
}

impl MountedYaw {
    pub fn new(yaw: f32) -> Self {
        Self {
            previous: yaw,
            current: yaw,
            target: yaw,
        }
    }

    /// The single-cart orientation step from `OrientedContraptionEntity`.
    /// The rail vector is the host's `MinecartSim2020.getRailVec` equivalent.
    /// Returns whether the structure is still turning after this tick.
    pub fn tick(
        &mut self,
        mode: MovementMode,
        was_stalled: bool,
        velocity: [f64; 3],
        displacement: [f64; 3],
        rail_vector: Option<[f64; 3]>,
        width: f64,
    ) -> bool {
        self.previous = self.current;
        if was_stalled || mode == MovementMode::RotationLocked {
            return false;
        }

        let mut motion = normalize(velocity);
        if let Some(rail) = rail_vector {
            let squared = dot(rail, rail);
            motion = if squared == 0.0 {
                [0.0; 3]
            } else {
                let scale = dot(motion, rail) / squared;
                rail.map(|component| component * scale)
            };
        }

        let length = norm(motion);
        if length > 0.0 {
            self.target = yaw_from_vector(motion);
            if self.target < 0.0 {
                self.target += 360.0;
            }
            if self.current < 0.0 {
                self.current += 360.0;
            }
        }
        self.previous = self.current;
        let max_step = (length * 12.0 / (width / 6.0).max(1.0)) as f32;
        let hint = shortest_turn(self.current, yaw_from_vector(displacement));
        let mut turn = shortest_turn(self.current, self.target);
        if turn == -180.0 && hint > 0.0 {
            turn = 180.0;
        }
        self.current += turn.clamp(-max_step, max_step);
        if shortest_turn(self.current, self.target).abs() < 1.0 {
            self.current = self.target;
            return false;
        }
        true
    }
}

fn yaw_from_vector([x, _, z]: [f64; 3]) -> f32 {
    use std::f64::consts::{FRAC_PI_2, PI};
    ((3.0 * FRAC_PI_2 + z.atan2(x)) / PI * 180.0) as f32
}

fn shortest_turn(from: f32, to: f32) -> f32 {
    let from = f64::from(from) % 360.0;
    let to = f64::from(to) % 360.0;
    (((to - from) % 360.0 + 540.0) % 360.0 - 180.0) as f32
}

#[cfg(test)]
mod tests {
    use super::*;
    use Direction::*;
    use Passenger::{Empty, Mounted};
    use RailAction::*;
    use RailKind::*;

    fn rail(kind: RailKind, powered: bool) -> Rail {
        Rail {
            kind,
            track: Track::EastWest,
            powered,
            backwards: false,
            waterlogged: false,
        }
    }

    #[test]
    fn wraps_straight_rails_and_preserves_the_controller_direction() {
        assert!(Rail::wrap(Regular, None, false, East).is_none());
        let ordinary = Rail::wrap(Regular, Some(Track::EastWest), false, East).unwrap();
        assert_eq!(ordinary.direction(), East);
        let mut directed = Rail::wrap(Controller, Some(Track::NorthSouth), false, East).unwrap();
        assert_eq!(directed.direction(), North);
        assert_eq!(directed.rotate(1).direction(), East);
        assert_eq!(directed.rotate(2).direction(), South);
        assert_eq!(directed.mirror(Axis::X), directed);
        assert_eq!(directed.mirror(Axis::Z).direction(), South);
        assert_eq!(directed.swap(Controller, false), RailSwap::Unchanged);
        assert_eq!(
            directed.swap(Detector, false),
            RailSwap::Exchange(Controller)
        );
        assert_eq!(directed.swap(Powered, true), RailSwap::Creative);
        let wrapped = Rail {
            powered: true,
            backwards: true,
            waterlogged: true,
            ..rail(Controller, false)
        };
        assert_eq!(
            wrapped.unwrap(),
            Rail {
                backwards: true,
                ..rail(Controller, false)
            }
        );
    }

    #[test]
    fn each_rail_selects_the_source_action_for_power_and_passengers() {
        let rows = [
            (Regular, [Disassemble, Assemble, Disassemble, Assemble]),
            (
                Powered,
                [
                    DisassembleBrake,
                    AssembleAccelerate,
                    DisassembleBrake,
                    AssembleAccelerate,
                ],
            ),
            (
                Detector,
                [
                    AssembleAccelerate,
                    AssembleAccelerate,
                    Disassemble,
                    Disassemble,
                ],
            ),
            (Activator, [Pass, Disassemble, Pass, Disassemble]),
            (
                Controller,
                [
                    DisassembleBrake,
                    AssembleDirectional,
                    DisassembleBrake,
                    AssembleDirectional,
                ],
            ),
        ];
        for (kind, expected) in rows {
            let actual = [
                (false, Empty),
                (true, Empty),
                (false, Mounted),
                (true, Mounted),
            ]
            .map(|(powered, passenger)| rail(kind, powered).action(passenger));
            assert_eq!(actual, expected);
        }
    }

    #[test]
    fn first_supported_pass_wins_and_a_cooldown_rejection_is_discarded() {
        let mut queue = PassQueue::default();
        queue.observe(0, CartKind::Other);
        queue.observe(1, CartKind::Chest);
        queue.observe(2, CartKind::Rideable);
        assert_eq!(queue.tick(), Some(1));
        for _ in 1..PASS_COOLDOWN {
            queue.observe(3, CartKind::Rideable);
            assert_eq!(queue.tick(), None);
        }
        assert_eq!(queue.tick(), None);
        queue.observe(4, CartKind::Furnace);
        assert_eq!(queue.tick(), Some(4));
    }

    #[test]
    fn single_cart_yaw_follows_rail_projection_width_and_stall() {
        let velocity = [0.2, 0.0, 0.2];
        let displacement = [0.05, 0.0, 0.01];
        let rail = Some([1.0, 0.0, 0.0]);
        let mut yaw = MountedYaw::new(90.0);
        assert!(yaw.tick(
            MovementMode::RotatePaused,
            false,
            velocity,
            displacement,
            rail,
            12.0
        ));
        assert_eq!(yaw.previous, 90.0);
        assert_eq!(yaw.target, 270.0);
        assert!((yaw.current - (90.0 - 6.0 / 2.0_f32.sqrt())).abs() < 1.0e-5);
        assert!(!MovementMode::RotatePaused.tick_actors(true));
        let before_stall = yaw.current;
        assert!(!yaw.tick(
            MovementMode::RotatePaused,
            true,
            velocity,
            displacement,
            rail,
            12.0
        ));
        assert_eq!(yaw.current, before_stall);
        assert_eq!(yaw.previous, before_stall);
        assert!(!yaw.tick(
            MovementMode::RotationLocked,
            false,
            velocity,
            displacement,
            rail,
            12.0
        ));
        assert_eq!(yaw.current, before_stall);

        let mut reverse_hint = MountedYaw::new(90.0);
        assert!(reverse_hint.tick(
            MovementMode::Rotate,
            false,
            velocity,
            [0.05, 0.0, -0.01],
            rail,
            12.0,
        ));
        assert!((reverse_hint.current - (90.0 + 6.0 / 2.0_f32.sqrt())).abs() < 1.0e-5);

        let mut snap = MountedYaw::new(257.5);
        assert!(!snap.tick(
            MovementMode::Rotate,
            false,
            [1.0, 0.0, 0.0],
            displacement,
            rail,
            6.0
        ));
        assert_eq!(snap.current, 270.0);
    }

    #[test]
    fn acceleration_and_brake_run_after_the_attempt() {
        let cart = CartMotion {
            position: [10.75, 23.0, -2.75],
            velocity: [0.125, 0.0, 0.0],
            motion_direction: East,
            rail_max_speed: 0.4,
        };
        let position = [10, 23, -3];
        let acceleration = rail(Powered, true);
        let action = acceleration.action(Passenger::Other);
        assert_eq!(action.operation(), Some(Operation::Assemble));
        assert!(!can_assemble(Passenger::Other, false, 1));
        let speed = f64::from(0.4_f32);
        assert_eq!(
            action.motion_after(acceleration, position, cart, [true, false]),
            Some([-speed, 0.0, 0.0])
        );
        assert_eq!(
            action.motion_after(acceleration, position, cart, [true, true]),
            Some([speed, 0.0, 0.0])
        );
        let slow = CartMotion {
            velocity: [1.0 / 128.0, 0.0, 0.0],
            ..cart
        };
        assert_eq!(
            action.motion_after(acceleration, position, slow, [false; 2]),
            None
        );
        let directional = Rail {
            backwards: true,
            ..rail(Controller, true)
        };
        let rest = CartMotion {
            velocity: [0.0; 3],
            ..cart
        };
        assert_eq!(
            directional
                .action(Empty)
                .motion_after(directional, position, rest, [false; 2]),
            Some([speed, 0.0, 0.0])
        );
        assert_eq!(
            DisassembleBrake.motion_after(rail(Powered, false), position, cart, [false; 2]),
            Some([-1.0 / 64.0, 0.0, 1.0 / 64.0])
        );
        assert_eq!(
            furnace_push(CartKind::Furnace, Operation::Assemble, cart.velocity),
            Some([0.0; 2])
        );
        assert_eq!(
            furnace_push(CartKind::Furnace, Operation::Disassemble, cart.velocity),
            Some([0.0, 0.125])
        );
    }

    #[test]
    fn secondary_cart_search_keeps_the_last_eligible_prefix_member() {
        let carts = [
            (1, CartKind::Chest),
            (2, CartKind::Rideable),
            (3, CartKind::Other),
            (4, CartKind::Furnace),
        ];
        assert_eq!(secondary_carts([0; 3], [5, 0, 0], &carts), &carts[..2]);
        assert!(secondary_carts([0; 3], [5, 1, 0], &carts).is_empty());
        assert!(secondary_carts([0; 3], [5, 0, 1], &carts).is_empty());
        assert!(secondary_carts([0; 3], [5, 0, 0], &carts[2..]).is_empty());
        assert_eq!(coupled_initial_direction([0; 3], [5, 0, 0]), Some(South));
        assert_eq!(coupled_initial_direction([0; 3], [0, 0, -5]), Some(East));
        assert_eq!(
            coupled_angles([2.0, 1.0, 0.0], [1.0, 0.0, 0.0], true),
            [180.0, -45.0]
        );
    }

    #[test]
    fn coupling_keeps_integer_distance_and_rejects_missing_or_cyclic_chains() {
        let lone = CouplingLinks {
            leading: None,
            trailing: None,
        };
        let existing = |id| match id {
            1 => Some(CouplingLinks {
                leading: Some(3),
                ..lone
            }),
            2 => Some(CouplingLinks {
                trailing: Some(4),
                ..lone
            }),
            3 | 4 => Some(lone),
            _ => None,
        };
        assert_eq!(
            coupling(1, 2, 1.999, 32, existing),
            Err(CouplingError::Distance)
        );
        assert_eq!(
            coupling(1, 2, 32.9, 32, existing),
            Ok(CouplingPlan {
                length: 32,
                reverse_primary_chain: true,
                reverse_secondary_chain: true,
            })
        );
        assert_eq!(
            coupling(1, 2, 2.0, 32, |id| if id == 4 {
                None
            } else {
                existing(id)
            }),
            Err(CouplingError::Unloaded)
        );
        assert_eq!(
            coupling(1, 2, 2.0, 32, |id| if id == 3 {
                Some(CouplingLinks {
                    leading: Some(2),
                    ..lone
                })
            } else {
                existing(id)
            }),
            Err(CouplingError::Loop)
        );
        assert_eq!(
            coupling(1, 2, 2.0, 32, |id| if id == 1 {
                Some(CouplingLinks {
                    leading: Some(2),
                    ..lone
                })
            } else {
                existing(id)
            }),
            Err(CouplingError::AlreadyConnected)
        );
    }

    #[test]
    fn mounted_capture_and_coupled_release_preserve_both_assembler_rails() {
        assert_eq!(assembly_seed([10, 23, -3]), Some([10, 24, -3]));
        assert!(!can_assemble(Empty, false, 0));
        assert!(!can_assemble(Empty, true, 1));
        assert!(can_assemble(Empty, false, 1));
        let release = rail(Regular, false);
        assert_eq!(
            disassembly(release, Mounted, None),
            Some(Disassembly::Single { facing: West })
        );
        assert_eq!(disassembly(release, Passenger::Other, None), None);
        let coupled = Passenger::CoupledContraption;
        assert_eq!(disassembly(release, coupled, None), None);
        assert_eq!(
            disassembly(release, coupled, Some((rail(Detector, false), Empty))),
            None
        );
        assert_eq!(
            disassembly(release, coupled, Some((rail(Activator, true), Empty))),
            Some(Disassembly::Coupled)
        );
        assert!(!MovementMode::RotatePaused.tick_actors(true));
        assert!(MovementMode::RotatePaused.tick_actors(false));
        assert!(MovementMode::Rotate.tick_actors(true));
    }
}
