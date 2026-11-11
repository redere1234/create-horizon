// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT
// Create 6.0.10 BeltConnectorItem/BeltBlock/BeltBlockEntity/BeltInventory adapter.
// The portable transport module owns geometry and movement. This adapter owns
// normal world writes, component-preserving NBT, controller lifetime and drawing.
// Processor callbacks use the portable transport result/queue contract.
use super::create_port_block_entity_revision::EntityRevision as _;
use super::{Game, create_port_basin_recipes::item_drain, native_block_entity_draw::BlockEntityDraw};
use crate::{
    containers::{BlockEntity, ModBlockEntity, ModRevision},
    items::ItemStack,
    mod_api::{NativeModelMaterial, NativeModelRenderOptions},
    particles::{ParticleOptions, ParticleType},
};
use create_engine::{
    fan::{Processing, ProcessingType},
    kinetics::{Axis, Pos},
    placement::Direction,
    transport::{
        self, Belt, Chain, Ending, Hooks, Inventory, Part, Pulley, Slope, Space, Stack, Transported,
    },
};
use horizon_assets::item_model::DisplayContext;
use horizon_client::motion::MotionWorld;
use horizon_core::{
    geometry::{Direction as WorldDirection, Vec3},
    position::BlockPos,
    random::{LegacyRandom, RandomSource},
};
use horizon_world::{
    entity_move::EntityMoveWorld,
    level::{LevelAccess, LevelEvent},
    nbt::{Compound, Tag},
    registry::BlockStateId,
};
use std::{cell::RefCell, collections::BTreeMap};

const ID: &str = "create:belt";
const CONNECTOR: &str = "create:belt_connector";
pub(super) const FIRST: &str = "create:belt_first_shaft";
type Moving = Transported<ItemStack>;
type Contents = Inventory<ItemStack>;

#[derive(Clone)]
struct KnownChain {
    chain: Chain,
    owners: Vec<ModRevision>,
    inventory: Contents,
    rpm: f32,
}

impl KnownChain {
    fn owns_segment(&self, game: &Game<'_>, index: usize) -> bool {
        let segment = &self.chain.segments[index];
        let pos = segment.pos;
        belt_revision(game, pos).is_some_and(|live| self.owners[index].is_same_create_entity(live))
            && facing(game, pos) == self.chain.facing
            && slope(game, pos) == self.chain.slope
            && part(game, pos) == segment.part
    }
}

fn belt_revision(game: &Game<'_>, pos: Pos) -> Option<ModRevision> {
    match game.world.block_entities.get(&(pos[0], pos[1], pos[2])) {
        Some(BlockEntity::Mod(entity)) if entity.id == ID => Some(entity.revision()),
        _ => None,
    }
}
#[derive(Clone)]
struct ProcessingOwner {
    // Source live records keep toRemove identities and toInsert outputs apart
    // until the controller ticks or its serialization boundary is reached.
    inventory: Contents,
    committed: Option<Tag>,
}
#[derive(Default)]
struct State {
    checked: Option<i64>,
    chains: BTreeMap<Pos, KnownChain>,
    processing: BTreeMap<Pos, ProcessingOwner>,
}
thread_local! { static STATE: RefCell<transport::SessionCache<State>> = RefCell::new(Default::default()); }
// TransportedItemStack owns a private java.util.Random, independent of level
// randomness. Keep that separation so item orientation never consumes world RNG.
thread_local! {
    static ITEM_RANDOM: RefCell<LegacyRandom> = RefCell::new(LegacyRandom::new(
        std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |time| time.as_nanos() as i64)
    ));
}
fn simulates(game: &Game<'_>) -> bool {
    game.serving.is_some() || game.options.dedicated.is_some()
}

fn passenger_motion(game: &Game<'_>) -> Option<Vec3> {
    let player = game.player.as_ref()?;
    if !player.ground.on_ground
        || player.shift_key_down
        || player.flying
        || player.spectator
        || player.health.health() <= 0.0
        || game.riding.is_some()
        || game.sleeping.is_some()
    {
        return None;
    }
    let support = player.ground.supporting_block?;
    let pos = [support.x, support.y, support.z];
    let is_dry_horizontal = |pos| {
        game.native_block(pos) == ID
            && slope(game, pos) == Slope::Horizontal
            && game.native_block_property(pos, "waterlogged").as_deref() == Some("false")
    };
    if player.position.y - 0.25 < f64::from(support.y) || !is_dry_horizontal(pos) {
        return None;
    }
    let (controller, index) = node_data(game, pos)?;
    let Some(BlockEntity::Mod(owner)) = game.world.block_entities.get(&(controller[0], controller[1], controller[2])) else {
        return None;
    };
    let length = int(&owner.nbt, "Length");
    let direction = facing(game, pos);
    if owner.id != ID
        || !boolean(&owner.nbt, "IsController")
        || !(2..=1000).contains(&length)
        || !(0..length).contains(&index)
        || !is_dry_horizontal(controller)
        || facing(game, controller) != direction
        || at(controller, direction, Slope::Horizontal, index) != pos
    {
        return None;
    }
    let rpm = super::create_port::running_speed(game, &owner.nbt);
    if !rpm.is_finite() || rpm.abs() < 1.0 {
        return None;
    }
    let speed = transport::movement_speed(rpm);
    let along_x = direction.axis() == Axis::X;
    let cross = if along_x { f64::from(support.z) + 0.5 - player.position.z }
                else { f64::from(support.x) + 0.5 - player.position.x };
    if cross.abs() > 0.75 {
        return None;
    }
    // BeltMovementHandler centers an idle rider only. RPM is signed in
    // world axes, independently of which endpoint was connected first.
    let centering = if player.applied_input == [0.0; 2] {
        cross * f64::from(speed.abs().min(0.1)) * 4.0
    } else {
        0.0
    };
    let speed = f64::from(speed);
    Some(if along_x { Vec3::new(-speed, 0.0, centering) }
         else { Vec3::new(centering, 0.0, speed) })
}

pub(super) fn passenger_tick(game: &mut Game<'_>) {
    let Some(movement) = passenger_motion(game) else { return };
    let entities = game.player_entity_collisions();
    let Some(player) = game.player.as_mut() else { return };
    player.fall_distance = 0.0;
    let mut world = MotionWorld {
        entities: &entities,
        player,
        scene: &mut game.world,
        assets: &game.pack.assets,
        collision_binding: game.collision,
        resources: game.motion,
        health: &game.health_resources,
    };
    if world.move_self(movement).is_ok() {
        // Java's Entity.move(SELF) is followed by setOnGround(true).
        let horizontal = world.player.ground.horizontal_collision;
        let _ = world.set_on_ground_with_movement(true, horizontal, Vec3::ZERO);
    }
}

fn with_state<R>(game: &Game<'_>, f: impl FnOnce(&mut State) -> R) -> R {
    STATE.with(|cell| {
        let mut cache = cell.borrow_mut();
        // swap_level exchanges dimension contents in place. The address alone
        // identifies this Game's session, reset(false) ends it explicitly.
        let state = cache.dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id());
        f(state)
    })
}
pub(super) fn reset(reload: bool) {
    if !reload {
        STATE.with(|s| s.borrow_mut().clear());
    }
}
fn int(nbt: &Compound, key: &str) -> i32 {
    super::create_port::integer(nbt, key)
}
fn number(nbt: &Compound, key: &str) -> f32 {
    super::create_port::number(nbt, key)
}
fn boolean(nbt: &Compound, key: &str) -> bool {
    int(nbt, key) != 0
}
fn dye_name(nbt: &Compound) -> Option<&'static str> {
    let Tag::String(value) = nbt.get(&"Dye".into())? else {
        return None;
    };
    create_assets::BELT_DYES.iter().copied().find(|dye| {
        dye.bytes()
            .map(|byte| u16::from(byte.to_ascii_uppercase()))
            .eq(value.0.iter().copied())
    })
}

pub(super) fn dye_update(entity: &ModBlockEntity, tag: &mut Compound) {
    if entity.id == ID {
        // The client merges partial tags. An explicit non-colour clears old
        // rendering while the source saved form has no Dye tag at all.
        tag.entry("Dye".into()).or_insert(Tag::Byte(0));
    }
}

fn washes_belt(game: &Game<'_>, stack: &ItemStack) -> bool {
    game.native_item_fluid(stack)
        .is_some_and(|item| item.amount > 0 && item.fluid.as_deref() == Some("minecraft:water"))
        || (stack.item.as_ref() == "minecraft:potion"
            && stack.potion() == Some("minecraft:water")
            && stack.custom_potion_effects().is_empty())
}

// Some(None) is a valid wash. None lets the normal item-use path continue.
fn dye_change(game: &Game<'_>, pos: Pos, stack: &ItemStack) -> Option<Option<&'static str>> {
    if stack.count == 0 || !game.may_build() || game.native_sneaking() {
        return None;
    }
    let Some(BlockEntity::Mod(clicked)) = game.world.block_entities.get(&(pos[0], pos[1], pos[2]))
    else {
        return None;
    };
    if clicked.id != ID {
        return None;
    }
    let dye = stack.item.strip_prefix("minecraft:")
        .and_then(|item| item.strip_suffix("_dye"))
        .and_then(|name| create_assets::BELT_DYES.iter().copied().find(|&dye| dye == name));
    (dye_name(&clicked.nbt) != dye && (dye.is_some() || washes_belt(game, stack))).then_some(dye)
}

pub(super) fn predicts_dye(game: &Game<'_>, pos: Pos) -> bool {
    game.native_on("create") && game.held().is_some_and(|stack| dye_change(game, pos, stack).is_some())
}

fn dye_belt(game: &mut Game<'_>, pos: Pos, dye: Option<&'static str>) -> bool {
    let Some((_, chain)) = restored_chain(game, pos) else {
        return false;
    };
    let value = dye.map(|dye| Tag::String(dye.to_ascii_uppercase().as_str().into()));
    for segment in chain.chain.segments {
        game.native_with_mod_block_entity(segment.pos, |entity| {
            if let Some(value) = &value {
                entity.nbt.insert("Dye".into(), value.clone());
            } else {
                entity.nbt.remove(&"Dye".into());
            }
        });
        game.native_block_entity_sync(segment.pos);
    }
    true
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Casing {
    None,
    Andesite,
    Brass,
}

impl Casing {
    fn read(nbt: &Compound) -> Self {
        match nbt.get(&"Casing".into()) {
            Some(Tag::String(value)) if value == &"ANDESITE".into() => Self::Andesite,
            Some(Tag::String(value)) if value == &"BRASS".into() => Self::Brass,
            _ => Self::None,
        }
    }

    fn tag(self) -> Tag {
        Tag::String(match self {
            Self::None => "NONE",
            Self::Andesite => "ANDESITE",
            Self::Brass => "BRASS",
        }.into())
    }

    fn material(self) -> Option<&'static str> {
        match self {
            Self::None => None,
            Self::Andesite => Some("andesite"),
            Self::Brass => Some("brass"),
        }
    }
}

fn cased(game: &Game<'_>, pos: Pos) -> bool {
    game.native_block_property(pos, "casing").as_deref() == Some("true")
}

fn casing_interaction(game: &Game<'_>, pos: Pos, face: Pos, stack: &ItemStack) -> Option<Casing> {
    if game.native_block(pos) != ID || !game.may_build() || game.native_sneaking() {
        return None;
    }
    match stack.item.as_ref() {
        "create:andesite_casing" => Some(Casing::Andesite),
        "create:brass_casing" => Some(Casing::Brass),
        // Top clicks go through BeltSlicer, which is a separate operation.
        "create:wrench" if face[1] != 1 && cased(game, pos) => Some(Casing::None),
        _ => None,
    }
}

pub(super) fn predicts_casing(game: &Game<'_>, pos: Pos, face: Pos) -> bool {
    game.native_on("create") && game.held().is_some_and(|stack| {
        casing_interaction(game, pos, face, stack).is_some()
    })
}

fn covered(game: &Game<'_>, pos: Pos) -> bool {
    let above = [pos[0], pos[1] + 1, pos[2]];
    match game.native_block(above).as_str() {
        "create:crushing_wheel_controller" | "create:andesite_belt_tunnel" | "create:brass_belt_tunnel"
        | "create:andesite_belt_funnel" | "create:brass_belt_funnel" => return false,
        "create:andesite_funnel" | "create:brass_funnel"
            if game.native_block_property(above, "facing").as_deref() != Some("up") => return false,
        _ => {}
    }
    let mut bounds = [f64::INFINITY, f64::INFINITY, f64::INFINITY, f64::NEG_INFINITY,
                      f64::NEG_INFINITY, f64::NEG_INFINITY];
    for box_ in game.native_block_collision(above) {
        for i in 0..3 {
            bounds[i] = bounds[i].min(box_[i]);
            bounds[i + 3] = bounds[i + 3].max(box_[i + 3]);
        }
    }
    bounds[1] <= 0.0 && bounds[3] - bounds[0] >= 0.5 && bounds[5] - bounds[2] >= 0.5
}

fn update_cover(entity: &mut ModBlockEntity, cover: bool) -> bool {
    if boolean(&entity.nbt, "Covered") == cover {
        return false;
    }
    entity.nbt.insert("Covered".into(), Tag::Byte(i8::from(cover)));
    true
}

fn change_casing(game: &mut Game<'_>, pos: Pos, next: Casing) -> bool {
    let Some(BlockEntity::Mod(entity)) = game.world.block_entities.get(&(pos[0], pos[1], pos[2])) else {
        return false;
    };
    if entity.id != ID {
        return false;
    }
    if !simulates(game) {
        return true;
    }
    let previous = Casing::read(&entity.nbt);
    let has_casing = next != Casing::None;
    if has_casing != cased(game, pos)
        && !game.native_set_block_property(pos, "casing", if has_casing { "true" } else { "false" })
    {
        return false;
    }
    let cover = (has_casing && slope(game, pos) == Slope::Horizontal).then(|| covered(game, pos));
    if game.native_with_mod_block_entity(pos, |entity| {
        entity.nbt.insert("Casing".into(), next.tag());
        if let Some(cover) = cover {
            update_cover(entity, cover);
        }
    }).is_none() {
        return false;
    }
    if previous != next
        && let Some(material) = previous.material()
        && let Some(state) = game.pack.assets.registry.default_state(&format!("create:{material}_casing"))
    {
        game.with_level(|_, level, _| {
            level.emit(LevelEvent::LevelEvent {
                id: 2001,
                pos: BlockPos::new(pos[0], pos[1], pos[2]),
                data: state.0 as i32,
            });
        });
    }
    if has_casing {
        let center = pos.map(|coordinate| f64::from(coordinate) + 0.5);
        game.with_level(|_, level, _| {
            level.native_play_sound("minecraft:block.wood.place", center, 4, 1.0, 0.8);
        });
    }
    game.native_block_entity_sync(pos);
    true
}

fn pos_tag(nbt: &Compound, key: &str) -> Option<Pos> {
    match nbt.get(&key.into()) {
        Some(Tag::IntArray(v)) if v.len() == 3 => Some([v[0], v[1], v[2]]),
        _ => None,
    }
}
fn direction(name: &str) -> Direction {
    Direction::ALL
        .into_iter()
        .find(|d| d.name() == name)
        .unwrap_or(Direction::North)
}
fn facing(game: &Game<'_>, pos: Pos) -> Direction {
    direction(
        game.native_block_property(pos, "facing")
            .as_deref()
            .unwrap_or("north"),
    )
}
fn slope_name(slope: Slope) -> &'static str {
    match slope {
        Slope::Horizontal => "horizontal",
        Slope::Upward => "upward",
        Slope::Downward => "downward",
        Slope::Vertical => "vertical",
        Slope::Sideways => "sideways",
    }
}
fn slope(game: &Game<'_>, pos: Pos) -> Slope {
    match game.native_block_property(pos, "slope").as_deref() {
        Some("upward") => Slope::Upward,
        Some("downward") => Slope::Downward,
        Some("vertical") => Slope::Vertical,
        Some("sideways") => Slope::Sideways,
        _ => Slope::Horizontal,
    }
}
fn part_name(part: Part) -> &'static str {
    match part {
        Part::Start => "start",
        Part::Middle => "middle",
        Part::End => "end",
        Part::Pulley => "pulley",
    }
}
fn part(game: &Game<'_>, pos: Pos) -> Part {
    match game.native_block_property(pos, "part").as_deref() {
        Some("start") => Part::Start,
        Some("end") => Part::End,
        Some("pulley") => Part::Pulley,
        _ => Part::Middle,
    }
}
fn axis(game: &Game<'_>, pos: Pos) -> Axis {
    if game.native_block(pos) == ID {
        if slope(game, pos) == Slope::Sideways {
            Axis::Y
        } else if facing(game, pos).axis() == Axis::X {
            Axis::Z
        } else {
            Axis::X
        }
    } else {
        match game.native_block_property(pos, "axis").as_deref() {
            Some("x") => Axis::X,
            Some("z") => Axis::Z,
            _ => Axis::Y,
        }
    }
}
pub(super) fn world_direction(d: Direction) -> WorldDirection {
    match d {
        Direction::Down => WorldDirection::Down,
        Direction::Up => WorldDirection::Up,
        Direction::North => WorldDirection::North,
        Direction::South => WorldDirection::South,
        Direction::West => WorldDirection::West,
        Direction::East => WorldDirection::East,
    }
}
fn at(origin: Pos, facing: Direction, slope: Slope, index: i32) -> Pos {
    let v = if slope == Slope::Vertical {
        [
            0,
            if facing.vector().iter().any(|v| *v < 0) {
                -1
            } else {
                1
            },
            0,
        ]
    } else {
        let mut v = facing.vector();
        v[1] = match slope {
            Slope::Upward => 1,
            Slope::Downward => -1,
            _ => 0,
        };
        v
    };
    std::array::from_fn(|i| origin[i] + v[i] * index)
}
fn next(game: &Game<'_>, pos: Pos, forward: bool) -> Option<Pos> {
    if matches!(
        (part(game, pos), forward),
        (Part::Start, false) | (Part::End, true)
    ) {
        return None;
    }
    Some(at(
        pos,
        facing(game, pos),
        slope(game, pos),
        if forward { 1 } else { -1 },
    ))
}
fn metadata(e: &mut ModBlockEntity, controller: Pos, length: usize, index: usize) {
    e.nbt
        .insert("Controller".into(), Tag::IntArray(controller.to_vec()));
    e.nbt
        .insert("IsController".into(), Tag::Byte(i8::from(index == 0)));
    e.nbt.insert("Length".into(), Tag::Int(length as i32));
    e.nbt.insert("Index".into(), Tag::Int(index as i32));
    e.nbt
        .entry("Casing".into())
        .or_insert(Tag::String("NONE".into()));
    e.nbt.entry("Covered".into()).or_insert(Tag::Byte(0));
}
pub(super) fn node_data(game: &Game<'_>, pos: Pos) -> Option<(Pos, i32)> {
    // The ticker leaves an empty placeholder at its own position. Use the
    // initialized chain instead of treating that placeholder as a controller.
    if let Some(BlockEntity::Mod(e)) = game.world.block_entities.get(&(pos[0], pos[1], pos[2]))
        && e.id == ID
    {
        return Some((
            pos_tag(&e.nbt, "Controller").unwrap_or(pos),
            int(&e.nbt, "Index"),
        ));
    }
    with_state(game, |s| {
        s.chains.iter().find_map(|(controller, known)| {
            known
                .chain
                .segments
                .iter()
                .position(|p| p.pos == pos)
                .map(|i| (*controller, i as i32))
        })
    })
}
fn belt(game: &Game<'_>, pos: Pos, e: &ModBlockEntity, rpm: f32) -> Belt {
    Belt {
        rpm,
        facing: facing(game, pos),
        slope: slope(game, pos),
        length: int(&e.nbt, "Length"),
    }
}
pub(super) fn game_stack(stack: &Stack<ItemStack>) -> ItemStack {
    ItemStack {
        count: stack.count,
        ..stack.payload.clone()
    }
}
pub(super) fn core_stack(game: &Game<'_>, stack: ItemStack) -> Stack<ItemStack> {
    let maximum = super::create_port::stack_maximum(game, &stack);
    Stack {
        count: stack.count,
        maximum,
        payload: ItemStack { count: 1, ..stack },
    }
}
fn return_to_player(game: &mut Game<'_>, pos: Pos, stack: ItemStack) {
    let player = game.native_acting_id();
    if let Some(rest) = game.native_give_stack(player, stack) {
        // Inventory.placeItemBackInInventory -> Player.drop(stack, false).
        if let Some(eye) = game.eye_position() {
            game.throw_from_eyes(rest, eye, false);
        } else {
            game.spawn_item(rest, pos.map(|v| f64::from(v) + 0.5), [0.0, 0.2, 0.0], 10);
        }
    }
}
pub(super) fn read_item(game: &Game<'_>, tag: &Tag) -> Option<Moving> {
    let Tag::Compound(nbt) = tag else { return None };
    let stack = horizon_items::item_nbt::item_from_nbt(nbt.get(&"Item".into())?)?;
    let mut item = Moving::new(core_stack(game, stack), int(nbt, "Angle"));
    item.position = number(nbt, "Pos");
    item.previous_position = number(nbt, "PrevPos");
    item.side_offset = number(nbt, "Offset");
    item.previous_side_offset = number(nbt, "PrevOffset");
    item.inserted_at = int(nbt, "InSegment");
    item.inserted_from = Direction::ALL[int(nbt, "InDirection").rem_euclid(6) as usize];
    item.locked = boolean(nbt, "Locked");
    item.externally_locked = boolean(nbt, "LockedExternally");
    item.fan = Processing {
        kind: match nbt.get(&"FanProcessingType".into()) {
            Some(Tag::String(s)) => ProcessingType::parse(&s.to_string_lossy()),
            _ => None,
        },
        time: int(nbt, "FanProcessingTime"),
    };
    (item.position.is_finite()
        && item.previous_position.is_finite()
        && item.side_offset.is_finite()
        && item.previous_side_offset.is_finite())
    .then_some(item)
}
pub(super) fn write_item(item: &Moving) -> Tag {
    let mut nbt = Compound::from([
        (
            "Item".into(),
            horizon_items::item_nbt::item_to_nbt(&game_stack(&item.stack)),
        ),
        ("Pos".into(), Tag::Float(item.position.to_bits())),
        (
            "PrevPos".into(),
            Tag::Float(item.previous_position.to_bits()),
        ),
        ("Offset".into(), Tag::Float(item.side_offset.to_bits())),
        (
            "PrevOffset".into(),
            Tag::Float(item.previous_side_offset.to_bits()),
        ),
        ("InSegment".into(), Tag::Int(item.inserted_at)),
        ("Angle".into(), Tag::Int(item.angle)),
        (
            "InDirection".into(),
            Tag::Int(
                Direction::ALL
                    .iter()
                    .position(|d| *d == item.inserted_from)
                    .unwrap_or(1) as i32,
            ),
        ),
    ]);
    if let Some(kind) = item.fan.kind {
        nbt.insert("FanProcessingType".into(), Tag::String(kind.id().into()));
        nbt.insert("FanProcessingTime".into(), Tag::Int(item.fan.time));
    }
    if item.locked {
        nbt.insert("Locked".into(), Tag::Byte(1));
    }
    if item.externally_locked {
        nbt.insert("LockedExternally".into(), Tag::Byte(1));
    }
    Tag::Compound(nbt)
}
pub(super) fn depot_item(
    game: &Game<'_>,
    stack: &ItemStack,
    position: f32,
    from: Direction,
) -> Tag {
    let mut item = Moving::new(core_stack(game, stack.clone()), angle(game, stack));
    item.position = position;
    item.previous_position = position;
    item.inserted_from = from;
    write_item(&item)
}

fn depot_accepts_inventory_stack(entity: &ModBlockEntity) -> bool {
    entity.id == "create:depot"
        && super::create_port::inventory_supported(entity)
        && !entity.items.is_empty()
        && entity.items.iter().all(Option::is_none)
}

/// Chutes use DepotItemHandler, whose uncentered stack starts at position 0
/// and slides toward the center. Direct belt input has a different pose.
pub(super) fn insert_depot_from_chute(
    game: &mut Game<'_>,
    [x, y, z]: Pos,
    stack: &ItemStack,
    simulate: bool,
) -> u32 {
    let Some(BlockEntity::Mod(entity)) = game.world.block_entities.get(&(x, y, z)) else {
        return 0;
    };
    if !depot_accepts_inventory_stack(entity) {
        return 0;
    }
    let count = stack
        .count
        .min(super::create_port::stack_maximum(game, stack));
    if count == 0 || simulate {
        return count;
    }
    let inserted = ItemStack {
        count,
        ..stack.clone()
    };
    let record = depot_item(game, &inserted, 0.0, Direction::Up);
    let target = [x, y, z];
    if game
        .native_with_mod_block_entity(target, |entity| {
            entity.items[0] = Some(inserted);
            entity.nbt.insert("HeldItem".into(), record);
        })
        .is_none()
    {
        return 0;
    }
    super::create_port_sounds::land(game, target);
    game.native_block_entity_sync(target);
    count
}

/// DepotBehaviour's direct input refuses a held stack or an occupied output
/// buffer. It takes at most one stack and keeps the transported record.
pub(super) fn insert_depot_from_side(
    game: &mut Game<'_>,
    target: Pos,
    item: &Transported<ItemStack>,
    from: Direction,
) -> u32 {
    let mut inserted = item.source_copy();
    inserted.position = if from.axis() == Axis::Y { 0.5 } else { 0.0 };
    inserted.previous_position = inserted.position;
    inserted.previous_side_offset = inserted.side_offset;
    inserted.inserted_from = from;
    inserted.stack.count = inserted.stack.count.min(inserted.stack.maximum);
    if inserted.stack.count == 0 {
        return 0;
    }
    let moved = game
        .native_with_mod_block_entity(target, |e| {
            if !depot_accepts_inventory_stack(e) {
                return false;
            }
            e.items[0] = Some(game_stack(&inserted.stack));
            e.nbt.insert("HeldItem".into(), write_item(&inserted));
            true
        })
        .unwrap_or(false);
    if moved {
        if from.axis() == Axis::Y {
            super::create_port_sounds::land(game, target);
        } else {
            super::create_port_sounds::depot(game, target);
        }
        game.native_block_entity_sync(target);
        inserted.stack.count
    } else {
        0
    }
}

fn read_inventory(game: &Game<'_>, e: &ModBlockEntity) -> Contents {
    let Some(Tag::Compound(nbt)) = e.nbt.get(&"Inventory".into()) else {
        return Contents::default();
    };
    let items = match nbt.get(&"Items".into()) {
        Some(Tag::List(items)) => items.iter().filter_map(|i| read_item(game, i)).collect(),
        _ => Vec::new(),
    };
    Contents {
        items,
        pending: Vec::new(),
        positive: boolean(nbt, "PositiveOrder"),
    }
}
fn write_inventory(e: &mut ModBlockEntity, inventory: &mut Contents) {
    // BeltInventory.write flushes insertion/removal queues before serialization.
    inventory.flush();
    let tag = Tag::Compound(Compound::from([
        (
            "Items".into(),
            Tag::List(inventory.items.iter().map(write_item).collect()),
        ),
        (
            "PositiveOrder".into(),
            Tag::Byte(i8::from(inventory.positive)),
        ),
    ]));
    if e.nbt.get(&"Inventory".into()) != Some(&tag) {
        e.nbt.insert("Inventory".into(), tag);
    }
}
fn remember(
    game: &Game<'_>,
    chain: Chain,
    inventory: Contents,
    rpm: f32,
    ticking: Option<(Pos, ModRevision)>,
) {
    let Some(first) = chain.segments.first() else {
        return;
    };
    let owners = chain.segments.iter().map(|segment| {
        // The native ticker temporarily holds this entity outside the world map.
        ticking.filter(|(pos, _)| *pos == segment.pos).map(|(_, owner)| owner)
            .or_else(|| belt_revision(game, segment.pos))
    }).collect::<Option<Vec<_>>>();
    let Some(owners) = owners else {
        return;
    };
    let controller = first.pos;
    with_state(game, |s| {
        s.chains.insert(controller, KnownChain { chain, owners, inventory, rpm });
    });
}
fn initialize(game: &mut Game<'_>, pos: Pos, entity: &mut ModBlockEntity) -> bool {
    let mut controller = pos;
    for _ in 0..1000 {
        if game.native_block(controller) != ID {
            return false;
        }
        let Some(previous) = next(game, controller, false) else {
            break;
        };
        if !game.world.loaded(previous[0], previous[2]) {
            return false;
        }
        controller = previous;
    }
    let mut chain = Chain {
        facing: facing(game, controller),
        slope: slope(game, controller),
        segments: Vec::new(),
    };
    let mut current = controller;
    for _ in 0..1000 {
        if !game.world.loaded(current[0], current[2]) || game.native_block(current) != ID {
            return false;
        }
        chain.segments.push(transport::Segment {
            pos: current,
            part: part(game, current),
        });
        let Some(n) = next(game, current, true) else {
            break;
        };
        current = n;
    }
    if chain.segments.len() < 2 || chain.segments.last().is_none_or(|s| s.part != Part::End) {
        return false;
    }
    for (i, segment) in chain.segments.iter().enumerate() {
        if segment.pos == pos {
            metadata(entity, controller, chain.segments.len(), i);
        } else {
            game.native_with_mod_block_entity(segment.pos, |e| {
                metadata(e, controller, chain.segments.len(), i)
            });
        }
        game.native_block_entity_sync(segment.pos);
    }
    let inventory = if pos == controller {
        authoritative_inventory(game, controller, entity)
    } else {
        match game
            .world
            .block_entities
            .get(&(controller[0], controller[1], controller[2]))
        {
            Some(BlockEntity::Mod(e)) => authoritative_inventory(game, controller, e),
            _ => Contents::default(),
        }
    };
    remember(game, chain, inventory, 0.0, Some((pos, entity.revision())));
    super::create_port_kinetic_runtime::invalidate();
    true
}
/// Called before the ordinary kinetic solve, while this entity is in hand.
pub(super) fn prepare(game: &mut Game<'_>, pos: Pos, entity: &mut ModBlockEntity) -> bool {
    if entity.id != ID {
        return false;
    }
    let controller = pos_tag(&entity.nbt, "Controller").unwrap_or(pos);
    if int(&entity.nbt, "Length") == 0 || !with_state(game, |s| s.chains.contains_key(&controller))
    {
        initialize(game, pos, entity);
    }
    true
}
fn state(game: &Game<'_>, block: &str, properties: &[(&str, &str)]) -> Option<BlockStateId> {
    let registry = game.pack.assets.registry;
    let default = registry.default_state(block)?;
    let mut descriptor = registry.state(default)?.clone();
    for (key, value) in properties {
        descriptor
            .properties
            .insert((*key).to_owned(), (*value).to_owned());
    }
    registry.id(&descriptor)
}
fn pulley(game: &Game<'_>, pos: Pos) -> Pulley {
    let entity = match game.world.block_entities.get(&(pos[0], pos[1], pos[2])) {
        Some(BlockEntity::Mod(entity)) => Some(entity.as_ref()),
        _ => None,
    };
    Pulley {
        pos,
        axis: axis(game, pos),
        rpm: entity.map_or(0.0, super::create_port_kinetic_runtime::theoretical),
        loaded: game.world.loaded(pos[0], pos[2]),
        shaft: entity.is_some() && game.native_block(pos) == "create:shaft",
    }
}

fn connector_first(stack: &ItemStack) -> Option<Pos> {
    if stack.item.as_ref() != CONNECTOR {
        return None;
    }
    match stack.data()?.other(FIRST)? {
        Tag::IntArray(p) if p.len() == 3 => Some([p[0], p[1], p[2]]),
        _ => None,
    }
}

fn replaceable(game: &Game<'_>, pos: Pos) -> bool {
    game.res
        .behaviours()
        .is_replaceable(game.world.block(pos[0], pos[1], pos[2]))
}

fn connect(game: &Game<'_>, first: Pos, pos: Pos) -> Result<Chain, transport::ConnectionError> {
    transport::connect(pulley(game, first), pulley(game, pos), transport::DEFAULT_MAX_LENGTH, |p| {
        if game.native_block(p) == "create:shaft" {
            Space::Shaft(axis(game, p))
        } else if replaceable(game, p) {
            Space::Replaceable
        } else {
            Space::Blocked
        }
    })
}

pub(super) fn connector_preview(game: &mut Game<'_>) {
    if !game.native_window() || game.remote.is_none() || !game.native_on("create")
        || !game.native_playing() || game.screen_over_playing() || game.native_mod_screen().is_some()
    {
        return;
    }
    let first = game.inventory.get(game.selected).and_then(Option::as_ref)
        .into_iter().chain(game.offhand.as_ref()).filter_map(connector_first)
        .find(|p| game.native_block_property(*p, "axis").is_some());
    let Some(first) = first else { return };
    let mut dust = ParticleOptions::simple(ParticleType::Dust);
    dust.color = [0.3, 0.9, 0.5, 1.0];
    let center = first.map(|v| f64::from(v) + 0.5);
    if game.pick_entity_hit().is_some() {
        if game.world.random.next_int_bound(50) == Ok(0) {
            let position = center.map(|v| v + f64::from((game.world.random.next_float() - 0.5) * 0.5));
            game.particles.add(&dust, position, [0.0; 3]);
        }
        return;
    }
    let Some(hit) = game.pick() else { return };
    if replaceable(game, hit.pos) {
        return;
    }
    let selected = if game.native_block(hit.pos) == "create:shaft" { hit.pos } else { hit.beside() };
    let Some((step, samples)) = transport::preview_line(first, selected, axis(game, first)) else { return };
    let valid = connect(game, first, selected).is_ok();
    if !valid {
        dust.color = [0.9, 0.3, 0.5, 1.0];
    }
    let mut spawned = 0;
    for sample in 0..samples {
        if game.world.random.next_int_bound(10) == Ok(0) {
            let position = std::array::from_fn(|i| center[i] + f64::from(step[i]) * f64::from(sample) / 16.0);
            game.particles.add(&dust, position, [0.0; 3]);
            spawned += 1;
        }
    }
    if std::env::var_os("CREATE_HORIZON_PARTICLE_TRACE").is_some() && spawned > 0 {
        log::info!("Create belt preview: first={first:?} selected={selected:?} step={step:?} samples={samples} valid={valid} spawned={spawned}");
    }
}

fn change_pulley(game: &mut Game<'_>, pos: Pos, previous: Part, next: Part) -> bool {
    let Some((controller, index)) = node_data(game, pos) else {
        return false;
    };
    let (Ok(index), Some(owner)) = (usize::try_from(index), belt_revision(game, pos)) else {
        return false;
    };
    if !game.native_set_block_property(pos, "part", part_name(next)) {
        return false;
    }
    // Middle and pulley are two states of the same belt entity. Update only
    // its matching chain entry so maintenance sees the in-place change.
    if belt_revision(game, pos).is_some_and(|live| owner.is_same_create_entity(live)) {
        with_state(game, |state| {
            if let Some(chain) = state.chains.get_mut(&controller)
                && chain.owners.get(index).is_some_and(|old| old.is_same_create_entity(owner))
                && let Some(segment) = chain.chain.segments.get_mut(index)
                && segment.pos == pos && segment.part == previous
            {
                segment.part = next;
            }
        });
    }
    super::create_port_kinetic_runtime::invalidate();
    true
}

pub(super) fn right_click(game: &mut Game<'_>, pos: Pos, face: Pos) -> bool {
    if !game.native_on("create") {
        return false;
    }
    let held = game.held().cloned();
    let sneaking = game.keys.contains(&winit::keyboard::KeyCode::ShiftLeft);
    if held.as_ref().is_some_and(|s| s.item.as_ref() == CONNECTOR) {
        if !simulates(game) {
            return true;
        }
        if sneaking {
            if let Some(s) = game.held_mut().as_mut() {
                s.data_mut().set_other(FIRST, None);
            }
            return true;
        }
        if game.native_block(pos) != "create:shaft" {
            return true;
        }
        let first = held.as_ref().and_then(connector_first);
        let first = first.filter(|p| {
            game.native_block(*p) == "create:shaft"
                && p.iter()
                    .zip(pos)
                    .map(|(a, b)| f64::from(*a - b).powi(2))
                    .sum::<f64>()
                    < 1600.0
        });
        if let Some(first) = first {
            let chain = connect(game, first, pos);
            let Ok(chain) = chain else { return true };
            let plans = chain
                .segments
                .iter()
                .map(|segment| {
                    let wet = game
                        .native_block_property(segment.pos, "waterlogged")
                        .as_deref()
                        == Some("true")
                        || game.native_block(segment.pos) == "minecraft:water";
                    state(
                        game,
                        ID,
                        &[
                            ("facing", chain.facing.name()),
                            ("slope", slope_name(chain.slope)),
                            ("part", part_name(segment.part)),
                            ("casing", "false"),
                            ("waterlogged", if wet { "true" } else { "false" }),
                        ],
                    )
                    .map(|s| (segment.pos, s))
                })
                .collect::<Option<Vec<_>>>();
            let Some(plans) = plans else { return true };
            let dim = game.dim.id().to_owned();
            for (p, s) in plans {
                if !game.native_set_block(&dim, p, s, 3) {
                    return true;
                }
            }
            for (i, segment) in chain.segments.iter().enumerate() {
                game.native_with_mod_block_entity(segment.pos, |e| {
                    metadata(e, first, chain.segments.len(), i)
                });
                game.native_block_entity_sync(segment.pos);
            }
            let midpoint =
                std::array::from_fn(|i| (f64::from(first[i]) + f64::from(pos[i])) * 0.5 + 0.5);
            game.with_level(|_, level, _| {
                level.native_play_sound("minecraft:block.wool.place", midpoint, 4, 0.5, 1.0)
            });
            remember(game, chain, Contents::default(), 0.0, None);
            super::create_port_kinetic_runtime::invalidate();
            let creative = game.creative;
            if let Some(s) = game.held_mut().as_mut() {
                s.data_mut().set_other(FIRST, None);
                if !creative {
                    s.count = s.count.saturating_sub(1);
                }
            }
            if game.held().is_some_and(|s| s.count == 0) {
                game.held_mut().take();
            }
        } else if let Some(s) = game.held_mut().as_mut() {
            s.data_mut()
                .set_other(FIRST, Some(Tag::IntArray(pos.to_vec())));
        }
        game.add_cooldown(CONNECTOR.into(), 5);
        return true;
    }
    if game.native_block(pos) != ID || sneaking {
        return false;
    }
    if let Some(dye) = held.as_ref().and_then(|stack| dye_change(game, pos, stack)) {
        return dye_belt(game, pos, dye);
    }
    if let Some(casing) = held.as_ref().and_then(|stack| casing_interaction(game, pos, face, stack)) {
        return change_casing(game, pos, casing);
    }
    if held.is_none() && game.hand == crate::game::Hand::Main {
        let Some((controller, index)) = node_data(game, pos) else {
            return true;
        };
        let Some(mut inventory) = controller_inventory(game, controller) else {
            return true;
        };
        let mut taken = Vec::new();
        inventory.items.retain(|i| {
            if (index as f32 + 0.5 - i.position).abs() < 0.55 {
                taken.push(game_stack(&i.stack));
                false
            } else {
                true
            }
        });
        save_controller(game, controller, &mut inventory);
        if !taken.is_empty() {
            super::create_port_sounds::pickup(game, pos);
        }
        for stack in taken {
            return_to_player(game, pos, stack);
        }
        return true;
    }
    if held
        .as_ref()
        .is_some_and(|s| s.item.as_ref() == "create:shaft")
        && part(game, pos) == Part::Middle
    {
        if change_pulley(game, pos, Part::Middle, Part::Pulley)
            && !game.creative
            && let Some(s) = game.held_mut().as_mut()
        {
            s.count = s.count.saturating_sub(1);
        }
        return true;
    }
    if held
        .as_ref()
        .is_some_and(|s| s.item.as_ref() == "create:wrench")
    {
        if !cased(game, pos)
            && part(game, pos) == Part::Pulley
            && change_pulley(game, pos, Part::Pulley, Part::Middle)
            && !game.creative
        {
            return_to_player(game, pos, ItemStack::new("create:shaft", 1));
        }
        return true;
    }
    false
}
fn controller_inventory(game: &Game<'_>, controller: Pos) -> Option<Contents> {
    match game
        .world
        .block_entities
        .get(&(controller[0], controller[1], controller[2]))
    {
        Some(BlockEntity::Mod(e)) if e.id == ID => {
            Some(authoritative_inventory(game, controller, e))
        }
        _ => None,
    }
}
fn authoritative_inventory(game: &Game<'_>, controller: Pos, entity: &ModBlockEntity) -> Contents {
    let live = with_state(game, |s| {
        if let Some(owner) = s.processing.get(&controller)
            && owner.committed.as_ref() == entity.nbt.get(&"Inventory".into())
        {
            return Some(owner.inventory.clone());
        }
        // Ordinary data merge/replacement is authoritative over stale cache.
        s.processing.remove(&controller);
        None
    });
    live.unwrap_or_else(|| read_inventory(game, entity))
}
fn save_controller(game: &mut Game<'_>, controller: Pos, inventory: &mut Contents) {
    game.native_with_mod_block_entity(controller, |e| write_inventory(e, inventory));
    with_state(game, |s| {
        s.processing.remove(&controller);
        if let Some(c) = s.chains.get_mut(&controller) {
            c.inventory = inventory.clone();
        }
    });
    game.native_block_entity_sync(controller);
}

pub(super) fn insert_belt_from_side(
    game: &mut Game<'_>,
    target: Pos,
    item: &Moving,
    from: Direction,
    from_previous_belt: bool,
) -> bool {
    let Some((controller, index)) = node_data(game, target) else {
        return false;
    };
    let Some(mut contents) = controller_inventory(game, controller) else {
        return false;
    };
    let [x, y, z] = controller;
    let Some(BlockEntity::Mod(entity)) = game.world.block_entities.get(&(x, y, z)) else {
        return false;
    };
    let target_belt = belt(game, controller, entity, number(&entity.nbt, "Speed"));
    if !contents.insert_direct(target_belt, index, item, from, from_previous_belt, false) {
        return false;
    }
    save_controller(game, controller, &mut contents);
    true
}

pub(super) fn insert_from_container(
    game: &mut Game<'_>,
    target: Pos,
    stack: &ItemStack,
    simulate: bool,
) -> u32 {
    // A lone or truncated Belt has no receiving inventory, even if a saved
    // member points at itself. Confirm ownership before moving the stack.
    let Some((controller, known)) = restored_chain(game, target) else {
        return 0;
    };
    let Some(index) = known
        .chain
        .segments
        .iter()
        .position(|segment| segment.pos == target)
    else {
        return 0;
    };
    let target_belt = Belt {
        rpm: known.rpm,
        facing: known.chain.facing,
        slope: known.chain.slope,
        length: known.chain.segments.len() as i32,
    };
    let mut contents = known.inventory;
    let input = core_stack(game, stack.clone());
    // Insertion preview must neither draw a random display angle nor publish.
    let angle = if simulate { 0 } else { angle(game, stack) };
    let remainder = contents.insert_automation(target_belt, index as i32, input, angle, simulate);
    let moved = stack.count - remainder.count;
    if moved > 0 && !simulate {
        save_controller(game, controller, &mut contents);
    }
    moved
}

fn stage_processing(game: &mut Game<'_>, controller: Pos, inventory: Contents) {
    // Canonical NBT is always save-safe. Its flushed clone is also what an
    // outbound tag must show, without exposing queued outputs to another
    // handler in this simulation pass.
    let mut saved = inventory.clone();
    let committed = game
        .native_with_mod_block_entity(controller, |entity| {
            if entity.id != ID {
                return None;
            }
            write_inventory(entity, &mut saved);
            Some(entity.nbt.get(&"Inventory".into()).cloned())
        })
        .flatten();
    let Some(committed) = committed else { return };
    with_state(game, |s| {
        if let Some(chain) = s.chains.get_mut(&controller) {
            chain.inventory = inventory.clone();
        }
        s.processing.insert(
            controller,
            ProcessingOwner {
                inventory,
                committed,
            },
        );
    });
}
/// The pinned tick_lan HEAD hook calls this before outgoing block-entity tags.
/// LevelTickPost runs after networking and would expose a stale frame instead.
pub(super) fn flush_processing(game: &mut Game<'_>) {
    if !simulates(game) {
        return;
    }
    let pending = with_state(game, |s| std::mem::take(&mut s.processing));
    for (controller, mut owner) in pending {
        if game.native_block(controller) != ID {
            continue;
        }
        let committed = game
            .native_with_mod_block_entity(controller, |entity| {
                if entity.id != ID {
                    return None;
                }
                if owner.committed.as_ref() == entity.nbt.get(&"Inventory".into()) {
                    write_inventory(entity, &mut owner.inventory);
                    Some(true)
                } else {
                    Some(false)
                }
            })
            .flatten();
        let current = match committed {
            Some(true) => Some(owner.inventory),
            Some(false) => controller_inventory(game, controller),
            None => None,
        };
        if let Some(current) = current {
            with_state(game, |s| {
                if let Some(chain) = s.chains.get_mut(&controller) {
                    chain.inventory = current;
                }
            });
        }
    }
}
/// TransportedItemStackHandlerBehaviour.applyToAllItems boundary for fan or
/// other machine adapters. Source results queue conversions/removals; equal
/// output stacks alone do not replace a transported record or its animation.
pub(super) fn apply_to_each_within(
    game: &mut Game<'_>,
    pos: Pos,
    maximum_distance: f32,
    mut apply: impl FnMut(
        &mut Game<'_>,
        &mut Transported<ItemStack>,
    ) -> Option<transport::TransportedResult<ItemStack>>,
) -> usize {
    if game.native_block(pos) != ID || !maximum_distance.is_finite() || maximum_distance <= 0.0 {
        return 0;
    }
    let Some((controller, index)) = node_data(game, pos) else {
        return 0;
    };
    let Some(mut inventory) = controller_inventory(game, controller) else {
        return 0;
    };
    let mut metadata_changed = false;
    let changed = inventory.apply_to_each_within(index as f32 + 0.5, maximum_distance, |item| {
        let before = item.clone();
        let result = apply(game, item);
        metadata_changed |= *item != before;
        result
    });
    if metadata_changed || changed > 0 {
        stage_processing(game, controller, inventory);
    }
    if changed > 0 {
        game.native_block_entity_sync(controller);
    }
    changed
}
pub(super) fn processing_positions(
    game: &Game<'_>,
    pos: Pos,
    maximum_distance: f32,
) -> Vec<[f64; 3]> {
    if game.native_block(pos) != ID || !maximum_distance.is_finite() || maximum_distance <= 0.0 {
        return Vec::new();
    }
    let Some((controller, index)) = node_data(game, pos) else {
        return Vec::new();
    };
    let Some(inventory) = controller_inventory(game, controller) else {
        return Vec::new();
    };
    let Some(BlockEntity::Mod(entity)) =
        game.world
            .block_entities
            .get(&(controller[0], controller[1], controller[2]))
    else {
        return Vec::new();
    };
    let shape = belt(game, controller, entity, 0.0);
    inventory
        .items
        .iter()
        .filter(|item| {
            !item.scheduled_removal
                && ((index as f32 + 0.5) - item.position).abs() < maximum_distance
        })
        .map(|item| shape.world_position(controller, item.position))
        .collect()
}
fn eject(game: &mut Game<'_>, controller: Pos, belt: Belt, item: Moving) {
    let mut at = belt.world_position(controller, item.position);
    let motion = belt.ejection_velocity();
    let length = motion.iter().map(|x| x * x).sum::<f64>().sqrt();
    if length > 0.0 {
        for i in 0..3 {
            at[i] += motion[i] / length * 0.001;
        }
    }
    at[1] += 6.0 / 16.0;
    game.spawn_item(game_stack(&item.stack), at, motion, 10);
}
fn dismantle(game: &mut Game<'_>, controller: Pos, mut known: KnownChain, removed: Option<Pos>) {
    let b = Belt {
        rpm: known.rpm,
        facing: known.chain.facing,
        slope: known.chain.slope,
        length: known.chain.segments.len() as i32,
    };
    let mut inventory = if known.owns_segment(game, 0) {
        let live = controller_inventory(game, controller);
        game.native_with_mod_block_entity(controller, |e| {
            e.nbt.remove(&"Inventory".into());
        });
        live.unwrap_or_else(|| std::mem::take(&mut known.inventory))
    } else {
        std::mem::take(&mut known.inventory)
    };
    inventory.flush();
    for item in inventory.items {
        eject(game, controller, b, item);
    }
    let dim = game.dim.id().to_owned();
    for (index, segment) in known.chain.segments.iter().enumerate() {
        if Some(segment.pos) == removed || !known.owns_segment(game, index) {
            continue;
        }
        let axis = axis(game, segment.pos);
        let wet = game
            .native_block_property(segment.pos, "waterlogged")
            .as_deref()
            == Some("true");
        let replacement = if part(game, segment.pos) == Part::Middle {
            state(
                game,
                if wet {
                    "minecraft:water"
                } else {
                    "minecraft:air"
                },
                &[],
            )
        } else {
            state(
                game,
                "create:shaft",
                &[
                    (
                        "axis",
                        match axis {
                            Axis::X => "x",
                            Axis::Y => "y",
                            Axis::Z => "z",
                        },
                    ),
                    ("waterlogged", if wet { "true" } else { "false" }),
                ],
            )
        };
        if let Some(replacement) = replacement {
            game.native_set_block(&dim, segment.pos, replacement, 3);
        }
    }
    super::create_port_kinetic_runtime::invalidate();
}
/// Rebuild ownership from saved entities when no tick has populated the cache
/// (a chunk reload, or destruction before that dimension's first belt tick).
/// Do not follow guessed metadata into unloaded chunks or a crossing chain.
fn restored_chain(game: &Game<'_>, pos: Pos) -> Option<(Pos, KnownChain)> {
    let expected_facing = facing(game, pos);
    let expected_slope = slope(game, pos);
    let valid = |p: Pos| {
        game.world.loaded(p[0], p[2])
            && game.native_block(p) == ID
            && facing(game, p) == expected_facing
            && slope(game, p) == expected_slope
    };
    let mut controller = pos;
    let mut start_found = false;
    for _ in 0..1000 {
        if !valid(controller) {
            return None;
        }
        if part(game, controller) == Part::Start {
            start_found = true;
            break;
        }
        controller = at(controller, expected_facing, expected_slope, -1);
    }
    if !start_found {
        return None;
    }
    let mut chain = Chain {
        facing: expected_facing,
        slope: expected_slope,
        segments: Vec::new(),
    };
    for index in 0..1000 {
        let current = at(controller, expected_facing, expected_slope, index);
        if !valid(current) {
            return None;
        }
        let current_part = part(game, current);
        if (index == 0 && current_part != Part::Start)
            || (index != 0 && current_part == Part::Start)
        {
            return None;
        }
        chain.segments.push(transport::Segment {
            pos: current,
            part: current_part,
        });
        if current_part == Part::End {
            break;
        }
    }
    if chain.segments.len() < 2 || chain.segments.last()?.part != Part::End {
        return None;
    }
    let mut owners = Vec::with_capacity(chain.segments.len());
    for (index, segment) in chain.segments.iter().enumerate() {
        let Some(BlockEntity::Mod(entity)) =
            game.world
                .block_entities
                .get(&(segment.pos[0], segment.pos[1], segment.pos[2]))
        else {
            return None;
        };
        if entity.id != ID {
            return None;
        }
        owners.push(entity.revision());
        if int(&entity.nbt, "Length") != 0
            && (int(&entity.nbt, "Length") != chain.segments.len() as i32
                || int(&entity.nbt, "Index") != index as i32
                || pos_tag(&entity.nbt, "Controller") != Some(controller))
        {
            return None;
        }
    }
    let Some(BlockEntity::Mod(entity)) =
        game.world
            .block_entities
            .get(&(controller[0], controller[1], controller[2]))
    else {
        return None;
    };
    Some((
        controller,
        KnownChain {
            owners,
            inventory: authoritative_inventory(game, controller, entity),
            rpm: number(&entity.nbt, "Speed"),
            chain,
        },
    ))
}
fn eject_controller_without_chain(game: &mut Game<'_>, pos: Pos) {
    let Some(BlockEntity::Mod(entity)) = game.world.block_entities.get(&(pos[0], pos[1], pos[2]))
    else {
        return;
    };
    if entity.id != ID
        || (!boolean(&entity.nbt, "IsController")
            && pos_tag(&entity.nbt, "Controller") != Some(pos))
    {
        return;
    }
    let mut inventory = authoritative_inventory(game, pos, entity);
    let b = belt(game, pos, entity, number(&entity.nbt, "Speed"));
    inventory.flush();
    game.native_with_mod_block_entity(pos, |entity| {
        entity.nbt.remove(&"Inventory".into());
    });
    // BeltBlockEntity.destroy ejects its OWN inventory even when neighbours
    // cannot be resolved. Never make item conservation depend on a cache hit
    // or on a different chunk being loaded.
    for item in inventory.items {
        eject(game, pos, b, item);
    }
}
/// Before ordinary player destruction: retain normal clicked-block loot, restore
/// the other pulleys and eject the controller's actual inventory exactly once.
pub(super) fn destroy(game: &mut Game<'_>, pos: Pos) {
    if game.native_block(pos) != ID {
        return;
    }
    let found = with_state(game, |s| {
        let controller = s
            .chains
            .iter()
            .find(|(_, v)| v.chain.segments.iter().any(|s| s.pos == pos))
            .map(|(p, _)| *p)?;
        s.chains.remove(&controller).map(|v| (controller, v))
    })
    .or_else(|| restored_chain(game, pos));
    if let Some((controller, known)) = found {
        dismantle(game, controller, known, Some(pos));
    } else {
        eject_controller_without_chain(game, pos);
    }
}
/// Catch non-player removal through normal world changes; never ticket chunks.
pub(super) fn maintenance(game: &mut Game<'_>) {
    if !simulates(game) {
        return;
    }
    let broken = with_state(game, |s| {
        if s.checked == Some(game.world.game_time) {
            return Vec::new();
        }
        s.checked = Some(game.world.game_time);
        s.processing.retain(|controller, _| {
            game.world.loaded(controller[0], controller[2]) && game.native_block(*controller) == ID
        });
        s.chains.retain(|_, c| {
            c.chain
                .segments
                .iter()
                .all(|p| game.world.loaded(p.pos[0], p.pos[2]))
        });
        let broken = s
            .chains
            .iter()
            .filter(|(_, c)| {
                c.chain
                    .segments
                    .iter()
                    .all(|p| game.world.loaded(p.pos[0], p.pos[2]))
                    && c.chain
                        .segments
                        .iter()
                        .enumerate()
                        .any(|(index, _)| !c.owns_segment(game, index))
            })
            .map(|(p, _)| *p)
            .collect::<Vec<_>>();
        broken
            .into_iter()
            .filter_map(|p| s.chains.remove(&p).map(|c| (p, c)))
            .collect::<Vec<_>>()
    });
    for (controller, known) in broken {
        dismantle(game, controller, known, None);
    }
}

#[derive(Clone, Copy)]
pub(super) enum Processor {
    Press,
    Deployer,
}

impl Processor {
    pub(super) fn at(game: &Game<'_>, pos: Pos) -> Option<Self> {
        if super::create_port_belt_press::available(game, pos) {
            Some(Self::Press)
        } else if super::create_port_deployer::transports(game, pos) {
            Some(Self::Deployer)
        } else {
            None
        }
    }

    pub(super) fn process(
        self,
        game: &mut Game<'_>,
        pos: Pos,
        item: &mut Moving,
        held: bool,
    ) -> transport::ProcessingUpdate<ItemStack> {
        match self {
            Self::Press if held => super::create_port_belt_press::held(game, pos, item),
            Self::Press => super::create_port_belt_press::received(game, pos, item),
            Self::Deployer => super::create_port_deployer::process_transport(game, pos, item, held),
        }
    }
}

struct WorldHooks<'a, 'g> {
    game: &'a mut Game<'g>,
    origin: Pos,
    belt: Belt,
}
impl WorldHooks<'_, '_> {
    fn target(&self) -> Pos {
        let offset = if self.belt.speed() > 0.0 {
            self.belt.length
        } else {
            -1
        };
        let d = self.belt.facing.vector();
        let y = match self.belt.slope {
            Slope::Upward => 1,
            Slope::Downward => -1,
            _ => 0,
        };
        [
            self.origin[0] + d[0] * offset,
            self.origin[1] + offset.clamp(0, self.belt.length - 1) * y,
            self.origin[2] + d[2] * offset,
        ]
    }
}
impl Hooks<ItemStack> for WorldHooks<'_, '_> {
    fn processor(&mut self, segment: i32) -> Option<bool> {
        let p = at(self.origin, self.belt.facing, self.belt.slope, segment);
        Some(Processor::at(self.game, [p[0], p[1] + 2, p[2]]).is_some())
    }
    fn processing_blocked(&mut self, segment: i32) -> bool {
        let p = at(self.origin, self.belt.facing, self.belt.slope, segment);
        !self
            .game
            .native_block_collision([p[0], p[1] + 1, p[2]])
            .is_empty()
    }
    fn received_update(
        &mut self,
        item: &mut Moving,
        segment: i32,
    ) -> transport::ProcessingUpdate<ItemStack> {
        let p = at(self.origin, self.belt.facing, self.belt.slope, segment);
        let pos = [p[0], p[1] + 2, p[2]];
        Processor::at(self.game, pos)
            .map_or_else(|| transport::ProcessingResult::Pass.into(),
                         |processor| processor.process(self.game, pos, item, false))
    }
    fn held_update(
        &mut self,
        item: &mut Moving,
        segment: i32,
    ) -> transport::ProcessingUpdate<ItemStack> {
        let p = at(self.origin, self.belt.facing, self.belt.slope, segment);
        let pos = [p[0], p[1] + 2, p[2]];
        Processor::at(self.game, pos)
            .map_or_else(|| transport::ProcessingResult::Pass.into(),
                         |processor| processor.process(self.game, pos, item, true))
    }
    fn ending(&mut self, _positive: bool) -> Ending {
        let target = self.target();
        let target_block = self.game.native_block(target);
        if matches!(
            target_block.as_str(),
            ID | "create:depot" | "create:millstone" | item_drain::BLOCK | super::create_port_drill::SAW
        ) || super::create_port_chute::is_chute(&target_block)
        {
            return Ending::Insert;
        }
        let state = self.game.world.block(target[0], target[1], target[2]);
        if self
            .game
            .res
            .behaviours()
            .is_face_sturdy(state, world_direction(self.belt.direction().opposite()))
        {
            Ending::Blocked
        } else {
            Ending::Eject
        }
    }
    fn insert_transported_end(&mut self, item: &Moving, from: Direction) -> Stack<ItemStack> {
        use super::create_port_chute as chute;

        let stack = &item.stack;
        let target = self.target();
        let count = match self.game.native_block(target).as_str() {
            ID => {
                if insert_belt_from_side(self.game, target, item, from, true) {
                    0
                } else {
                    stack.count
                }
            }
            "create:depot" => stack.count - insert_depot_from_side(self.game, target, item, from),
            item_drain::BLOCK => stack.count - item_drain::insert(self.game, target, item, from),
            chute::BLOCK | chute::SMART => {
                stack.count - chute::insert_from_transport(self.game, target, &game_stack(stack))
            }
            super::create_port_drill::SAW => {
                stack.count - super::create_port_saw_processing::insert_from_transport(
                    self.game, target, &game_stack(stack), false,
                )
            }
            _ => {
                // MillstoneBlockEntity has the default DirectBeltInputBehaviour.
                let remaining = self
                    .game
                    .native_insert_item(target, world_direction(from), game_stack(stack))
                    .map_or(0, |s| s.count);
                if remaining < stack.count {
                    super::create_port_millstone::publish_inventory(self.game, target);
                }
                remaining
            }
        };
        Stack {
            count,
            ..stack.clone()
        }
    }
}
pub(super) fn upright(game: &Game<'_>, stack: &ItemStack) -> bool {
    let tags = &game.res.items().item_tags;
    let in_tag = |tag: &str| {
        tags.get(tag)
            .is_some_and(|v| v.contains(stack.item.as_ref()))
    };
    (game.native_item_fluid(stack).is_some() || in_tag("create:upright_on_belt"))
        && !in_tag("create:not_upright_on_belt")
}
pub(super) fn angle(game: &Game<'_>, stack: &ItemStack) -> i32 {
    if upright(game, stack) {
        180
    } else {
        ITEM_RANDOM.with(|random| random.borrow_mut().next_int_bound(360).unwrap_or(0))
    }
}
fn capture(game: &mut Game<'_>, origin: Pos, belt: Belt, contents: &mut Contents) {
    if !belt.slope.transports() {
        return;
    }
    let dim = game.dim.id().to_owned();
    for index in 0..belt.length {
        let p = at(origin, belt.facing, belt.slope, index);
        let min = [f64::from(p[0]), f64::from(p[1]) + 0.5, f64::from(p[2])];
        let max = [min[0] + 1.0, f64::from(p[1]) + 1.25, min[2] + 1.0];
        for dropped in game.native_item_entities(&dim, min, max) {
            let falling = game
                .dropped
                .iter()
                .any(|e| e.id == dropped.id && e.velocity.y <= 0.0);
            if !falling || dropped.position[1] < min[1] {
                continue;
            }
            let input = core_stack(game, dropped.stack.clone());
            let remainder = contents.insert_automation(belt, index, input, 0, true);
            if remainder.count == dropped.stack.count {
                continue;
            }
            let rest = ItemStack {
                count: remainder.count,
                ..dropped.stack.clone()
            };
            if game.native_set_item_entity(&dim, dropped.id, rest) {
                contents.insert_automation(
                    belt,
                    index,
                    core_stack(game, dropped.stack.clone()),
                    angle(game, &dropped.stack),
                    false,
                );
            }
        }
    }
}
/// Called after effective RPM is written, including overstress.
pub(super) fn tick(game: &mut Game<'_>, pos: Pos, entity: &mut ModBlockEntity, rpm: f32) -> bool {
    if entity.id != ID {
        return false;
    }
    let cover_changed = cased(game, pos) && slope(game, pos) == Slope::Horizontal
        && update_cover(entity, covered(game, pos));
    if !boolean(&entity.nbt, "IsController") || int(&entity.nbt, "Length") < 2 {
        return cover_changed;
    }
    let old_inventory = entity.nbt.get(&"Inventory".into()).cloned();
    let belt = belt(game, pos, entity, rpm);
    let mut contents = authoritative_inventory(game, pos, entity);
    with_state(game, |s| {
        s.processing.remove(&pos);
    });
    if !belt.slope.transports() {
        for item in contents.items.drain(..) {
            eject(game, pos, belt, item);
        }
    } else {
        capture(game, pos, belt, &mut contents);
        let result = contents.tick(
            belt,
            &mut WorldHooks {
                game,
                origin: pos,
                belt,
            },
        );
        for item in result.ejected {
            eject(game, pos, belt, item);
        }
    }
    write_inventory(entity, &mut contents);
    with_state(game, |s| {
        if let Some(c) = s.chains.get_mut(&pos) {
            c.inventory = contents;
            c.rpm = rpm;
        }
    });
    // Controller inventory is not a generic container; send its full source NBT.
    // Client prediction is deliberately separate from server authority.
    let changed = entity.nbt.get(&"Inventory".into()) != old_inventory.as_ref();
    if changed {
        game.native_block_entity_sync(pos);
    }
    changed || cover_changed
}

pub(super) fn models(models: &mut Vec<String>) {
    for part in [
        "belt_pulley",
        "belt/start",
        "belt/middle",
        "belt/end",
        "belt/start_bottom",
        "belt/middle_bottom",
        "belt/end_bottom",
        "belt/diagonal_start",
        "belt/diagonal_middle",
        "belt/diagonal_end",
    ] {
        models.push(format!("create:block/{part}"));
    }
    for shape in ["horizontal", "diagonal", "sideways"] {
        for part in ["start", "middle", "end", "pulley"] {
            for prefix in ["", "andesite_"] {
                models.push(format!("create:block/belt_casing/{prefix}{shape}_{part}"));
            }
        }
    }
    for material in ["andesite", "brass"] {
        for axis in ["x", "z"] {
            models.push(format!("create:block/belt_cover/{material}_belt_cover_{axis}"));
        }
    }
}
/// A rotated cuboid face remains a rectangle in UV space. Reorder its corners
/// cyclically so native_draw_quad can draw exactly the source 0/90/180/270 UVs.
fn rectangle(positions: [[f32; 3]; 4], uv: [[f32; 2]; 4]) -> Option<([[f32; 3]; 4], [f32; 4])> {
    for i in 0..4 {
        let p = [
            positions[i],
            positions[(i + 1) % 4],
            positions[(i + 2) % 4],
            positions[(i + 3) % 4],
        ];
        let t = [uv[i], uv[(i + 1) % 4], uv[(i + 2) % 4], uv[(i + 3) % 4]];
        if (t[0][0] - t[1][0]).abs() < 0.00001
            && (t[1][1] - t[2][1]).abs() < 0.00001
            && (t[2][0] - t[3][0]).abs() < 0.00001
            && (t[3][1] - t[0][1]).abs() < 0.00001
        {
            return Some((
                p,
                [
                    t[0][0] * 16.0,
                    t[0][1] * 16.0,
                    t[2][0] * 16.0,
                    t[2][1] * 16.0,
                ],
            ));
        }
    }
    None
}
fn moving_model(
    game: &Game<'_>,
    draw: &mut BlockEntityDraw,
    model: &str,
    scroll: f32,
    diagonal: bool,
    dye: Option<&str>,
) {
    let original = super::create_port::original_assets();
    if dye.is_none() && !original {
        game.native_draw_model(draw, model, 0xFFFFFF);
        return;
    }
    let Some(baked) = game.pack.render.model_catalog.standalone(model) else {
        return;
    };
    let variant;
    let (target, tint) = if original {
        let target = match (dye, diagonal) {
            (Some(dye), _) => {
                let suffix = if diagonal { "diagonal_scroll" } else { "scroll" };
                variant = format!("create:gui/scrolling/belt/{dye}_{suffix}");
                variant.as_str()
            }
            (None, true) => "create:gui/scrolling/belt_diagonal_scroll",
            (None, false) => "create:gui/scrolling/belt_scroll",
        };
        (target, 0xFFFFFF)
    } else {
        use horizon_client::mobs::render::{DYE, DYE_NAMES};
        let tint = dye.and_then(|name| DYE_NAMES.iter().position(|&dye| dye == name))
            .map_or(0xFFFFFF, |index| DYE[index]);
        // The fallback belt's ordinary black wool is too dark to dye directly.
        ("block/white_wool", tint)
    };
    if !game.gui.atlas.sprites.contains_key(target) {
        game.native_draw_model(draw, model, tint);
        return;
    }
    for face in &baked.faces {
        let mut uv = face.quad.uv;
        if original {
            uv = uv.map(|[u, v]| [u, v * 0.5 + scroll]);
        }
        if let Some((corners, uv)) = rectangle(face.quad.positions, uv) {
            game.native_draw_quad(draw, target, corners, uv, tint);
        }
    }
}
pub(super) fn render_bounds(
    game: &Game<'_>,
    pos: Pos,
    entity: &ModBlockEntity,
    bounds: &mut [f32; 6],
) {
    if entity.id == super::create_port::FLYWHEEL {
        // FlywheelBlockEntity inflates its ordinary block bounds by two.
        *bounds = [-2.0, -2.0, -2.0, 3.0, 3.0, 3.0];
        return;
    }
    if entity.id != ID || !boolean(&entity.nbt, "IsController") {
        return;
    }
    let end = at(
        pos,
        facing(game, pos),
        slope(game, pos),
        int(&entity.nbt, "Length").saturating_sub(1),
    );
    for i in 0..3 {
        bounds[i] = ((end[i] - pos[i]).min(0) - 1) as f32;
        bounds[i + 3] = ((end[i] - pos[i]).max(0) + 2) as f32;
    }
}

// BeltVisual combines the vanilla yaw with its own XYZ rotations.
fn render_yaw(facing: Direction) -> f32 {
    match facing {
        Direction::South => 0.0,
        Direction::West => 90.0,
        Direction::North => 180.0,
        Direction::East => 270.0,
        _ => 0.0,
    }
}

fn draw_casing(
    game: &Game<'_>,
    draw: &mut BlockEntityDraw,
    entity: &ModBlockEntity,
    facing: Direction,
    slope: Slope,
    mut part: Part,
) {
    let casing = Casing::read(&entity.nbt);
    let Some(material) = casing.material() else { return };
    let negative = matches!(facing, Direction::North | Direction::West);
    if slope == Slope::Downward || matches!(slope, Slope::Vertical | Slope::Sideways) && negative {
        part = match part {
            Part::Start => Part::End,
            Part::End => Part::Start,
            _ => part,
        };
    }
    let shape = match slope {
        Slope::Horizontal => "horizontal",
        Slope::Upward | Slope::Downward => "diagonal",
        Slope::Vertical | Slope::Sideways => "sideways",
    };
    let yaw = match slope {
        Slope::Upward => -180.0,
        Slope::Vertical => -90.0,
        _ => 0.0,
    };
    let pitch = match slope {
        Slope::Vertical => -90.0,
        Slope::Sideways if negative => -180.0,
        _ => 0.0,
    };
    draw.push();
    // BeltGenerator's block-state model rotations apply X, then Y.
    let vanilla_yaw = match facing {
        Direction::West => -90.0,
        Direction::East => -270.0,
        Direction::North => -180.0,
        _ => 0.0,
    };
    draw.rotate_about([0.0, 1.0, 0.0], vanilla_yaw + yaw, [0.5; 3]);
    if pitch != 0.0 {
        draw.rotate_about([1.0, 0.0, 0.0], pitch, [0.5; 3]);
    }
    let prefix = if casing == Casing::Andesite { "andesite_" } else { "" };
    game.native_draw_terrain_model(
        draw,
        &format!("create:block/belt_casing/{prefix}{shape}_{}", part_name(part)),
        NativeModelRenderOptions {
            material: NativeModelMaterial::CutoutMipped,
            ..Default::default()
        },
    );
    draw.pop();
    if boolean(&entity.nbt, "Covered") {
        let axis = if facing.axis() == Axis::X { "x" } else { "z" };
        game.native_draw_terrain_model(
            draw,
            &format!("create:block/belt_cover/{material}_belt_cover_{axis}"),
            NativeModelRenderOptions {
                material: NativeModelMaterial::CutoutMipped,
                ..Default::default()
            },
        );
    }
}

pub(super) fn draw(
    game: &Game<'_>,
    pos: Pos,
    entity: &ModBlockEntity,
    draw: &mut BlockEntityDraw,
) -> bool {
    if entity.id != ID {
        return false;
    }
    let slope = slope(game, pos);
    let facing = facing(game, pos);
    let part = part(game, pos);
    if cased(game, pos) {
        draw_casing(game, draw, entity, facing, slope, part);
    }
    let diagonal = matches!(slope, Slope::Upward | Slope::Downward);
    let downward = slope == Slope::Downward;
    let upward = slope == Slope::Upward;
    let sideways = slope == Slope::Sideways;
    let vertical = slope == Slope::Vertical;
    let along_x = facing.axis() == Axis::X;
    let along_z = facing.axis() == Axis::Z;
    let negative = facing.vector().iter().any(|v| *v < 0);
    let start = part == Part::Start;
    let end = part == Part::End;
    let rpm = number(&entity.nbt, "Speed");
    let dye = dye_name(&entity.nbt);
    let time = draw.game_time as f32 + draw.partial;
    let belt_time = game.visual_ticks() as f32 + draw.partial;
    let mut speed = rpm;
    if (negative ^ upward) ^ ((along_x && !diagonal) || (along_z && diagonal)) {
        speed = -speed;
    }
    if (sideways && matches!(facing, Direction::South | Direction::West))
        || (vertical && facing == Direction::East)
    {
        speed = -speed;
    }
    let scroll_speed = speed * (1.0 / (31.5 * 16.0));
    let scroll_scale = if diagonal { 3.0 / 8.0 } else { 0.5 };
    let rot_x = if !diagonal && slope != Slope::Horizontal { 90.0 } else { 0.0 }
        + if downward { 180.0 } else { 0.0 }
        + if sideways { 90.0 } else { 0.0 }
        + if vertical && along_z { 180.0 } else { 0.0 };
    let rot_y = render_yaw(facing)
        + if (diagonal ^ along_x) && !downward { 180.0 } else { 0.0 }
        + if sideways && along_z { 180.0 } else { 0.0 }
        + if vertical && along_x { 90.0 } else { 0.0 };
    let rot_z = if sideways { 90.0 } else { 0.0 }
        + if vertical && along_x { 90.0 } else { 0.0 };
    draw.push();
    draw.rotate_about([1.0, 0.0, 0.0], rot_x, [0.5; 3]);
    draw.rotate_about([0.0, 1.0, 0.0], rot_y, [0.5; 3]);
    draw.rotate_about([0.0, 0.0, 1.0], rot_z, [0.5; 3]);
    for bottom in [true, false] {
        let model = if diagonal {
            if start {
                "diagonal_start"
            } else if end {
                "diagonal_end"
            } else {
                "diagonal_middle"
            }
        } else if bottom {
            if start {
                "start_bottom"
            } else if end {
                "end_bottom"
            } else {
                "middle_bottom"
            }
        } else if start {
            "start"
        } else if end {
            "end"
        } else {
            "middle"
        };
        // The Flywheel shader samples the scrolling strip even at zero speed.
        let scroll = scroll_speed * belt_time + if bottom { 0.5 } else { 0.0 };
        let scroll = (scroll - scroll.floor()) * scroll_scale;
        moving_model(
            game,
            draw,
            &format!("create:block/belt/{model}"),
            scroll,
            diagonal,
            dye,
        );
        if diagonal {
            break;
        }
    }
    draw.pop();
    if part != Part::Middle {
        let axis = axis(game, pos);
        draw.push();
        let rotation = create_engine::visual::angle(
            f64::from(time),
            rpm,
            create_engine::visual::rotation_offset(pos, axis, false),
        );
        draw.rotate_about(
            create_engine::visual::positive_axis(axis),
            rotation,
            [0.5; 3],
        );
        if axis == Axis::X {
            draw.rotate_about([0.0, 1.0, 0.0], 90.0, [0.5; 3]);
        }
        if axis == Axis::Y {
            draw.rotate_about([1.0, 0.0, 0.0], 90.0, [0.5; 3]);
        }
        draw.rotate_about([1.0, 0.0, 0.0], 90.0, [0.5; 3]);
        game.native_draw_model(draw, "create:block/belt_pulley", 0xFFFFFF);
        draw.pop();
    }
    if boolean(&entity.nbt, "IsController") && int(&entity.nbt, "Length") > 0 {
        let b = belt(game, pos, entity, rpm);
        let contents = read_inventory(game, entity);
        for item in &contents.items {
            draw_item(game, draw, pos, b, item);
        }
    }
    true
}
fn draw_item(game: &Game<'_>, draw: &mut BlockEntityDraw, origin: Pos, belt: Belt, item: &Moving) {
    let partial = if belt.rpm == 0.0 { 1.0 } else { draw.partial };
    let offset = item.previous_position + (item.position - item.previous_position) * partial;
    let mut side =
        item.previous_side_offset + (item.side_offset - item.previous_side_offset) * partial;
    let old_light = draw.light;
    let segment = offset.floor() as i32;
    let light_pos = at(origin, belt.facing, belt.slope, segment);
    let at = belt.world_position(origin, offset);
    let (block_light, sky_light) = game.native_light(light_pos);
    draw.light = horizon_client::block_entity_render::vertex_light((sky_light << 4) | block_light);
    let stack = game_stack(&item.stack);
    let upright = upright(game, &stack);
    // Legacy source gui3d is not a data property in modern item model format.
    // This block-registry classification covers the supported original fixtures;
    // custom item models need an explicit isGui3d compatibility contract.
    let block_item = game
        .pack
        .assets
        .registry
        .default_state(&stack.item)
        .is_some();
    let on_slope =
        belt.slope != Slope::Horizontal && offset >= 0.5 && offset <= belt.length as f32 - 0.5;
    let tilt = ((belt.slope == Slope::Downward) ^ belt.facing.vector().iter().any(|v| *v > 0))
        == (belt.facing.axis() == Axis::Z);
    let slope_angle = if on_slope {
        if tilt { -45.0 } else { 45.0 }
    } else {
        0.0
    };
    let axis = if belt.facing.axis() == Axis::X {
        [0.0, 0.0, 1.0]
    } else {
        [1.0, 0.0, 0.0]
    };
    draw.push();
    draw.translate(std::array::from_fn(|i| {
        (at[i] - f64::from(origin[i])) as f32 + if i == 1 { 7.0 / 16.0 } else { 0.0 }
    }));
    if belt.facing.axis() == Axis::X {
        side *= -1.0;
        draw.translate([0.0, 0.0, side]);
    } else {
        draw.translate([side, 0.0, 0.0]);
    }
    if !upright {
        draw.rotate_about(axis, slope_angle, [0.0; 3]);
    }
    if on_slope {
        draw.translate([0.0, 0.125, 0.0]);
    }
    if upright {
        if let Some(camera) = game.native_camera() {
            let yaw = ((at[0] - camera.position[0]).atan2(at[2] - camera.position[2])
                + std::f64::consts::PI)
                .to_degrees() as f32;
            draw.rotate_about([0.0, 1.0, 0.0], yaw, [0.0; 3]);
        }
        draw.translate([0.0, 3.0 / 32.0, 1.0 / 16.0]);
    }
    let near = game.native_player().is_some_and(|p| {
        (p.x - at[0]).powi(2) + (p.y - at[1]).powi(2) + (p.z - at[2]).powi(2) < 256.0
    });
    let count = if near {
        (31 - item.stack.count.max(1).leading_zeros()) / 2
    } else {
        0
    };
    let mut random = LegacyRandom::new(i64::from(item.angle));
    for i in 0..=count {
        draw.push();
        draw.rotate_about([0.0, 1.0, 0.0], item.angle as f32, [0.0; 3]);
        if !block_item && !upright {
            draw.translate([0.0, -0.09375, 0.0]);
            draw.rotate_about([1.0, 0.0, 0.0], 90.0, [0.0; 3]);
        }
        if block_item {
            draw.translate([
                random.next_float() * 0.0625 * i as f32,
                0.0,
                random.next_float() * 0.0625 * i as f32,
            ]);
        }
        draw.scale([0.5; 3]);
        game.native_draw_item(draw, &stack, DisplayContext::Fixed, None, item.angle);
        draw.pop();
        if !upright {
            if !block_item {
                draw.rotate_about([0.0, 1.0, 0.0], 10.0, [0.0; 3]);
            }
            draw.translate([0.0, if block_item { 1.0 / 64.0 } else { 1.0 / 16.0 }, 0.0]);
        } else {
            draw.translate([0.0, 0.0, -1.0 / 16.0]);
        }
    }
    draw.pop();
    draw.light = old_light;
}
