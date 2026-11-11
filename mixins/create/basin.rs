// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT
// Create 6.0.10 BasinBlockEntity/BasinInventory/BasinRenderer adapter.
// Heat-aware downward basin; two canonical water/lava tank halves.
// Unknown tank data, complex filters and side spouts remain opaque.
use super::create_port_block_entity_revision::EntityRevision as _;
use super::{
    Game, GameLevel, create_port_basin_recipes::item_drain, create_port_fluid_codec as fluids,
    native_block_entity_draw::BlockEntityDraw,
};
use crate::{
    containers::{BlockEntity, ModBlockEntity, ModContainer, ModRevision},
    items::ItemStack,
};
use create_engine::{basin as rules, transport::SessionCache};
use horizon_client::mod_api::{
    NativeFluidAction, NativeFluidDrain, NativeFluidRenderOptions, NativeFluidStack,
    NativeFluidTankView,
};
use horizon_core::random::{LegacyRandom, RandomSource};
use horizon_world::nbt::{Compound, Tag};
use std::{cell::RefCell, collections::BTreeMap};

pub(super) const ID: &str = "create:basin";
type Pos = [i32; 3];

#[derive(Clone, Debug)]
pub(super) struct Key(pub ItemStack);
impl PartialEq for Key {
    fn eq(&self, other: &Self) -> bool {
        self.0.same_item_same_components(&other.0)
    }
}
impl Eq for Key {}
pub(super) type Basin = rules::Basin<Key, fluids::Key>;

#[derive(Default)]
struct Motion {
    owner: Option<ModRevision>,
    tick: Option<i64>,
    previous: f32,
    angle: f32,
    speed: f32,
    lazy: i32,
    moving: bool,
    fluid_levels: [rules::FluidLevel; 4],
    received_fluids: [Option<fluids::Level>; 4],
    rendered_fluids: [Option<rules::Fluid<fluids::Key>>; 4],
}
struct Server {
    owner: Option<ModRevision>,
    initialized: bool,
    contents_changed: bool,
    tick: Option<i64>,
    lazy: i32,
    backup: i32,
    heat: rules::HeatCache,
}
impl Default for Server {
    fn default() -> Self {
        Self {
            owner: None,
            initialized: false,
            contents_changed: false,
            tick: None,
            lazy: 10,
            backup: 20,
            heat: rules::HeatCache::default(),
        }
    }
}
impl Server {
    fn bind(&mut self, owner: ModRevision) {
        if self.owner.is_some_and(|old| !old.is_same_create_entity(owner)) {
            *self = Self::default();
        }
        self.owner = Some(owner);
    }
}
thread_local! {
    static MOTION: RefCell<SessionCache<BTreeMap<Pos, Motion>>> = RefCell::new(SessionCache::default());
    static SERVER: RefCell<SessionCache<BTreeMap<Pos, Server>>> = RefCell::new(SessionCache::default());
}

pub(super) fn reset(reload: bool) {
    if !reload {
        MOTION.with(|m| m.borrow_mut().clear());
        SERVER.with(|m| m.borrow_mut().clear());
        tank::reset();
        pump::reset();
    }
}

/// BasinInventory.whenContentsChanged/notifyChangeOfContents only raises a
/// flag. The next ordinary Basin tick schedules its operator checker.
pub(super) fn notify_contents(game: &Game<'_>, pos: Pos) {
    let Some(BlockEntity::Mod(entity)) = game.world.block_entities.get(&(pos[0], pos[1], pos[2]))
    else {
        return;
    };
    if entity.id != ID || !crate::game::create_port::inventory_supported(entity) {
        return;
    }
    SERVER.with(|cache| {
        let mut cache = cache.borrow_mut();
        let server = cache
            .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
            .entry(pos)
            .or_default();
        server.bind(entity.revision());
        server.contents_changed = true;
    });
}

pub(super) fn container(block: &str, container: &mut Option<ModContainer>) {
    if block == ID && container.is_none() {
        *container = Some(ModContainer {
            slots: 18,
            faces: std::array::from_fn(|_| (0..18).collect()),
            inputs: (0..9).collect(),
            // CombinedInvWrapper exposes BOTH input and output to extraction.
            outputs: (0..18).collect(),
            menu: None,
        });
    }
}

fn inventory(slots: &[Option<ItemStack>]) -> Tag {
    Tag::Compound(Compound::from([
        ("Size".into(), Tag::Int(9)),
        (
            "Items".into(),
            Tag::List(
                slots
                    .iter()
                    .enumerate()
                    .filter_map(|(i, s)| {
                        let stack = s.as_ref().filter(|s| s.count > 0)?;
                        let Tag::Compound(mut nbt) = horizon_items::item_nbt::item_to_nbt(stack)
                        else {
                            return None;
                        };
                        nbt.insert("Slot".into(), Tag::Int(i as i32));
                        Some(Tag::Compound(nbt))
                    })
                    .collect(),
            ),
        ),
    ]))
}
fn restore(entity: &mut ModBlockEntity) {
    // Canonical inventory is decoded before publication. Never re-read an old
    // bridge snapshot after ordinary automation has already changed live slots.
    if crate::game::create_port::inventory_supported(entity) {
        entity.items.resize(18, None);
    }
}
pub(super) fn data(entity: &mut ModBlockEntity) -> bool {
    if entity.id != ID || !crate::game::create_port::inventory_supported(entity) {
        return false;
    }
    entity.items.resize(18, None);
    let mut changed = false;
    for (key, range) in [("InputItems", 0..9), ("OutputItems", 9..18)] {
        let Tag::Compound(updated) = inventory(&entity.items[range]) else {
            unreachable!();
        };
        let mut value = match entity.nbt.get(&key.into()) {
            Some(Tag::Compound(existing)) => existing.clone(),
            _ => Compound::new(),
        };
        value.extend(updated);
        let value = Tag::Compound(value);
        changed |= entity.nbt.get(&key.into()) != Some(&value);
        entity.nbt.insert(key.into(), value.clone());
    }
    changed
}
fn empty_tanks() -> Tag {
    let segment = Tag::Compound(Compound::from([
        (
            "Level".into(),
            Tag::Compound(Compound::from([
                ("Force".into(), Tag::Byte(1)),
                ("Speed".into(), Tag::Float(0.25f32.to_bits())),
                ("Target".into(), Tag::Float(0.0f32.to_bits())),
                ("Value".into(), Tag::Float(0.0f32.to_bits())),
            ])),
        ),
        ("TankContent".into(), Tag::Compound(Compound::new())),
    ]));
    Tag::List(vec![segment.clone(), segment])
}
pub(super) fn initialize(entity: &mut ModBlockEntity) {
    if entity.id != ID || !crate::game::create_port::inventory_supported(entity) {
        return;
    }
    restore(entity);
    for key in ["InputTanks", "OutputTanks"] {
        entity.nbt.entry(key.into()).or_insert_with(empty_tanks);
    }
    for key in ["DisabledSpoutput", "Overflow", "FluidOverflow"] {
        entity
            .nbt
            .entry(key.into())
            .or_insert_with(|| Tag::List(Vec::new()));
    }
    entity
        .nbt
        .entry("Filter".into())
        .or_insert_with(|| Tag::Compound(Compound::new()));
    entity
        .nbt
        .entry("FilterAmount".into())
        .or_insert(Tag::Int(64));
    entity.nbt.entry("UpTo".into()).or_insert(Tag::Byte(1));
    data(entity);
}

fn nonempty(tag: Option<&Tag>) -> bool {
    match tag {
        None => false,
        Some(Tag::Compound(c)) => !c.is_empty(),
        Some(Tag::List(l)) => !l.is_empty(),
        _ => true,
    }
}
pub(super) fn unsupported(
    game: &Game<'_>,
    pos: Pos,
    entity: &ModBlockEntity,
) -> Option<&'static str> {
    if !crate::game::create_port::inventory_supported(entity) {
        return Some("basin inventory sizes are not supported");
    }
    if game.native_block_property(pos, "facing").as_deref() != Some("down") {
        return Some("basin side spouts are not implemented");
    }
    if super::create_port_basin_filter::read(game, entity).is_none() {
        return Some("basin recipe filter data is not supported");
    }
    for key in ["InputTanks", "OutputTanks"] {
        if let Err(fluids::Unsupported(reason)) = read_tanks(entity, key) {
            return Some(reason);
        }
    }
    if [
        "Overflow",
        "FluidOverflow",
        "PreferredSpoutput",
        "DisabledSpoutput",
    ]
    .into_iter()
    .any(|key| nonempty(entity.nbt.get(&key.into())))
    {
        return Some("basin spout buffers are not implemented");
    }
    None
}
fn component_maximum(stack: &ItemStack) -> Option<u32> {
    super::create_port::stack_maximum_override(stack)
}
pub(super) fn max_stack(game: &Game<'_>, stack: &ItemStack) -> u32 {
    super::create_port::stack_maximum(game, stack)
}
pub(super) fn has_analog(
    game: &GameLevel<'_>,
    state: horizon_world::registry::BlockStateId,
    output: &mut bool,
) {
    if matches!(game.facts.get(state).name.as_ref(), ID | item_drain::BLOCK | tank::BLOCK) {
        *output = true;
    }
}
pub(super) fn analog(
    game: &GameLevel<'_>,
    pos: horizon_core::position::BlockPos,
    state: horizon_world::registry::BlockStateId,
    output: &mut i32,
) {
    let block = game.facts.get(state).name.as_ref();
    if !matches!(block, ID | item_drain::BLOCK | tank::BLOCK) {
        return;
    }
    *output = 0;
    let Some(BlockEntity::Mod(e)) = game.world.block_entities.get(&(pos.x, pos.y, pos.z)) else {
        return;
    };
    if block == item_drain::BLOCK {
        *output = item_drain::comparator(e);
        return;
    }
    if block == tank::BLOCK {
        *output = tank::comparator_group(game, [pos.x, pos.y, pos.z])
            .unwrap_or_else(|| tank::comparator(e));
        return;
    }
    // Unsupported native-created inventories may not have canonical slots yet.
    // Keep their payload opaque and fail closed before any comparator indexing.
    if !crate::game::create_port::inventory_supported(e) {
        return;
    }
    let mut fullness = 0.0f32;
    let mut occupied = false;
    for stack in e.items.iter().take(9).flatten().filter(|s| s.count > 0) {
        let maximum = component_maximum(stack)
            .unwrap_or_else(|| game.items.get(&stack.item).map_or(64, |i| i.max_stack))
            .min(64);
        fullness += stack.count as f32 / maximum as f32;
        occupied = true;
    }
    *output = (fullness / 9.0 * 14.0).floor() as i32 + i32::from(occupied);
}
pub(super) fn can_survive(
    game: &GameLevel<'_>,
    pos: horizon_core::position::BlockPos,
    state: horizon_world::registry::BlockStateId,
    survives: &mut Option<bool>,
) {
    let block = game.facts.get(state).name.as_ref();
    if block == "create:mechanical_mixer" {
        *survives = Some(
            !matches!(game.world.block_entities.get(&(pos.x,pos.y-1,pos.z)),Some(BlockEntity::Mod(e)) if e.id == ID),
        );
        return;
    }
    if block != ID {
        return;
    }
    *survives = Some(
        !matches!(game.world.block_entities.get(&(pos.x,pos.y+1,pos.z)),Some(BlockEntity::Mod(e)) if matches!(e.id.as_str(),"create:mechanical_mixer"|"create:mechanical_press")),
    );
}
pub(super) fn core_stack(game: &Game<'_>, stack: &ItemStack) -> rules::Item<Key> {
    let mut key = stack.clone();
    key.count = 1;
    rules::Item {
        key: Key(key),
        count: stack.count,
        maximum: max_stack(game, stack),
    }
}
pub(super) fn native_stack(item: &rules::Item<Key>) -> ItemStack {
    ItemStack {
        count: item.count,
        ..item.key.0.clone()
    }
}
pub(super) fn read(game: &Game<'_>, pos: Pos) -> Option<Basin> {
    let BlockEntity::Mod(entity) = game.world.block_entities.get(&(pos[0], pos[1], pos[2]))? else {
        return None;
    };
    if entity.id != ID || unsupported(game, pos, entity).is_some() {
        return None;
    }
    Some(Basin {
        input: std::array::from_fn(|i| {
            entity
                .items
                .get(i)
                .and_then(Option::as_ref)
                .filter(|s| s.count > 0)
                .map(|s| core_stack(game, s))
        }),
        output: std::array::from_fn(|i| {
            entity
                .items
                .get(9 + i)
                .and_then(Option::as_ref)
                .filter(|s| s.count > 0)
                .map(|s| core_stack(game, s))
        }),
        input_fluids: read_tanks(entity, "InputTanks").ok()?,
        output_fluids: read_tanks(entity, "OutputTanks").ok()?,
        ..Basin::default()
    })
}
pub(super) fn heat(game: &Game<'_>, pos: Pos) -> rules::Heat {
    let Some(BlockEntity::Mod(entity)) = game.world.block_entities.get(&(pos[0], pos[1], pos[2]))
    else {
        return rules::Heat::None;
    };
    if entity.id != ID {
        return rules::Heat::None;
    }
    SERVER.with(|cache| {
        let mut cache = cache.borrow_mut();
        let server = cache
            .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
            .entry(pos)
            .or_default();
        server.bind(entity.revision());
        server.heat.get_or_read(|| {
            let state = game.world.block(pos[0], pos[1] - 1, pos[2]);
            let Some(state) = game.pack.assets.registry.state(state) else {
                return Some(rules::Heat::None);
            };
            let blaze = state
                .properties
                .get("blaze")
                .map(|value| match value.as_str() {
                    "smouldering" => rules::Heat::Smouldering,
                    "fading" => rules::Heat::Fading,
                    "kindled" => rules::Heat::Kindled,
                    "seething" => rules::Heat::Seething,
                    _ => rules::Heat::None,
                });
            // Same source priority and short-circuit: a real blaze level
            // wins before passive tags or campfire lit state are tested.
            if let Some(blaze) = blaze {
                return Some(blaze);
            }
            let passive = game
                .native_server_block_in_tag(state, "create:passive_boiler_heaters")
                .unwrap_or(false);
            let campfire = passive
                && game
                    .native_server_block_in_tag(state, "minecraft:campfires")
                    .unwrap_or(false);
            let lit = state.properties.get("lit").map(|v| v == "true");
            Some(rules::heat_for_block(blaze, passive, campfire, lit))
        })
    })
}
pub(super) fn write(game: &mut Game<'_>, pos: Pos, basin: &Basin) -> bool {
    let Some(changed) = game.native_with_mod_block_entity(pos, |entity| {
        if entity.id != ID || !crate::game::create_port::inventory_supported(entity) {
            return false;
        }
        // Preflight both canonical halves before any item/fluid write. Unsupported
        // original data is retained; it cannot become an empty tank by accident.
        let Ok((input, output)) = replacement_tanks(entity, basin) else {
            return false;
        };
        let fluid_changed = set_tanks(entity, input, output);
        entity.items = basin
            .input
            .iter()
            .chain(&basin.output)
            .map(|s| s.as_ref().map(native_stack))
            .collect();
        data(entity) || fluid_changed
    }) else {
        return false;
    };
    if changed {
        game.native_block_entity_sync(pos);
        notify_contents(game, pos);
    }
    changed
}

fn read_tanks(entity: &ModBlockEntity, key: &str) -> Result<fluids::Tanks, fluids::Unsupported> {
    // A fresh factory-created entity has not yet had its first initialization
    // tick. Reading/simulating that default must not write or dirty the entity.
    let empty = empty_tanks();
    fluids::read_half(Some(entity.nbt.get(&key.into()).unwrap_or(&empty)))
}
fn replacement_tanks(
    entity: &ModBlockEntity,
    basin: &Basin,
) -> Result<(Tag, Tag), fluids::Unsupported> {
    let empty = empty_tanks();
    Ok((
        fluids::write_half(
            Some(entity.nbt.get(&"InputTanks".into()).unwrap_or(&empty)),
            &basin.input_fluids,
        )?,
        fluids::write_half(
            Some(entity.nbt.get(&"OutputTanks".into()).unwrap_or(&empty)),
            &basin.output_fluids,
        )?,
    ))
}
fn set_tanks(entity: &mut ModBlockEntity, input: Tag, output: Tag) -> bool {
    let changed = entity.nbt.get(&"InputTanks".into()) != Some(&input)
        || entity.nbt.get(&"OutputTanks".into()) != Some(&output);
    if changed {
        entity.nbt.insert("InputTanks".into(), input);
        entity.nbt.insert("OutputTanks".into(), output);
    }
    changed
}
fn fluid_state(game: &Game<'_>, pos: Pos) -> Option<Basin> {
    if game.options.execution_role.is_client() {
        return None;
    }
    let BlockEntity::Mod(entity) = game.world.block_entities.get(&(pos[0], pos[1], pos[2]))? else {
        return None;
    };
    if entity.id != ID || !crate::game::create_port::inventory_supported(entity) {
        return None;
    }
    Some(Basin {
        input_fluids: read_tanks(entity, "InputTanks").ok()?,
        output_fluids: read_tanks(entity, "OutputTanks").ok()?,
        ..Basin::default()
    })
}
fn commit_fluids(game: &mut Game<'_>, pos: Pos, state: &Basin) {
    let changed = game
        .native_with_mod_block_entity(pos, |entity| {
            if entity.id != ID || !crate::game::create_port::inventory_supported(entity) {
                return false;
            }
            let Ok((input, output)) = replacement_tanks(entity, state) else {
                return false;
            };
            set_tanks(entity, input, output)
        })
        .unwrap_or(false);
    if changed {
        game.native_block_entity_sync(pos);
        notify_contents(game, pos);
    }
}
fn core_fluid(stack: &NativeFluidStack) -> Option<rules::Fluid<fluids::Key>> {
    (stack.amount > 0 && matches!(stack.fluid.as_str(), "minecraft:water" | "minecraft:lava")).then(
        || rules::Fluid {
            key: fluids::Key {
                id: stack.fluid.clone(),
                components: stack.components.clone(),
            },
            amount: stack.amount as u32,
        },
    )
}
fn native_fluid(stack: &rules::Fluid<fluids::Key>) -> NativeFluidStack {
    NativeFluidStack {
        fluid: stack.key.id.clone(),
        amount: stack.amount as i32,
        components: stack.key.components.clone(),
    }
}
/// Use the shared Horizon fluid helpers for sided automation.
pub(super) fn custom_fluids(block: &str, custom: &mut bool) {
    if matches!(block, ID | tank::BLOCK) {
        *custom = true;
    }
}
pub(super) fn fluid_tanks(
    game: &Game<'_>,
    pos: Pos,
    _side: Option<horizon_core::geometry::Direction>,
    out: &mut Option<Vec<NativeFluidTankView>>,
) {
    if game.native_block(pos) == tank::BLOCK {
        *out = tank::view(game, pos);
        return;
    }
    let Some(state) = fluid_state(game, pos) else {
        return;
    };
    *out = Some(
        (0..4)
            .map(|tank| NativeFluidTankView {
                tank,
                content: state.fluid(tank).map(native_fluid),
                capacity: rules::TANK_CAPACITY as i32,
                can_fill: tank >= 2,
                can_drain: true,
            })
            .collect(),
    );
}
pub(super) fn fluid_fill(
    game: &mut Game<'_>,
    pos: Pos,
    _side: Option<horizon_core::geometry::Direction>,
    resource: &NativeFluidStack,
    action: NativeFluidAction,
    out: &mut Option<i32>,
) {
    if game.native_block(pos) == tank::BLOCK {
        *out = tank::fill(game, pos, resource, action);
        return;
    }
    let Some(mut state) = fluid_state(game, pos) else {
        return;
    };
    *out = Some(0);
    let Some(resource) = core_fluid(resource) else {
        return;
    };
    // Injected into the defining crate today; reject future external variants.
    #[allow(unreachable_patterns)]
    let simulate = match action {
        NativeFluidAction::Simulate => true,
        NativeFluidAction::Execute => false,
        _ => return,
    };
    *out = Some(fill_input(game, pos, &mut state, &resource, simulate) as i32);
}
fn fill_input(
    game: &mut Game<'_>,
    pos: Pos,
    state: &mut Basin,
    resource: &rules::Fluid<fluids::Key>,
    simulate: bool,
) -> u32 {
    let amount = state.fill_input_fluid(resource, simulate);
    if !simulate && amount > 0 {
        commit_fluids(game, pos, state);
    }
    amount
}
pub(super) fn fluid_drain(
    game: &mut Game<'_>,
    pos: Pos,
    _side: Option<horizon_core::geometry::Direction>,
    request: &NativeFluidDrain,
    action: NativeFluidAction,
    out: &mut Option<NativeFluidStack>,
) {
    if game.native_block(pos) == tank::BLOCK {
        *out = tank::drain(game, pos, request, action);
        return;
    }
    let Some(mut state) = fluid_state(game, pos) else {
        return;
    };
    let selected;
    let request = match request {
        NativeFluidDrain::Any(maximum) if *maximum > 0 => rules::FluidRequest::Any(*maximum as u32),
        NativeFluidDrain::Exact(stack) => {
            let Some(stack) = core_fluid(stack) else {
                return;
            };
            selected = stack;
            rules::FluidRequest::Exact(&selected)
        }
        _ => return,
    };
    // Injected into the defining crate today; reject future external variants.
    #[allow(unreachable_patterns)]
    let simulate = match action {
        NativeFluidAction::Simulate => true,
        NativeFluidAction::Execute => false,
        _ => return,
    };
    *out = drain(game, pos, &mut state, request, simulate)
        .as_ref()
        .map(native_fluid);
}
fn drain(
    game: &mut Game<'_>,
    pos: Pos,
    state: &mut Basin,
    request: rules::FluidRequest<'_, fluids::Key>,
    simulate: bool,
) -> Option<rules::Fluid<fluids::Key>> {
    let report = state.drain_fluid(request, simulate);
    if !simulate && report.consumed > 0 {
        commit_fluids(game, pos, state);
    }
    report.returned
}
/// `BasinInventory.insertItem`: unique component-bearing stack per half and
/// only its first empty slot. Normal hopper transfers are one item at a time.
pub(super) fn can_place(
    slots: &[Option<ItemStack>],
    local: usize,
    stack: &ItemStack,
    maximum: u32,
) -> bool {
    let maximum = component_maximum(stack).unwrap_or(maximum);
    if local >= 9 || slots.len() < 9 || stack.count == 0 {
        return false;
    }
    let input = &slots[..9];
    if input.iter().enumerate().any(|(i, s)| {
        i != local
            && s.as_ref()
                .is_some_and(|s| s.count > 0 && s.same_item_same_components(stack))
    }) {
        return false;
    }
    match input[local].as_ref().filter(|s| s.count > 0) {
        Some(held) => held.count < maximum.min(64) && held.same_item_same_components(stack),
        None => {
            input
                .iter()
                .position(|s| s.as_ref().is_none_or(|s| s.count == 0))
                == Some(local)
        }
    }
}

pub(super) fn tick(game: &mut Game<'_>, pos: Pos, entity: &mut ModBlockEntity) -> bool {
    if entity.id != ID || !crate::game::create_port::inventory_supported(entity) {
        return false;
    }
    restore(entity);
    let changed = data(entity);
    initialize(entity);
    let owner = entity.revision();
    let already_ticked = SERVER.with(|cache| {
        let mut cache = cache.borrow_mut();
        let server = cache
            .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
            .entry(pos)
            .or_default();
        server.bind(owner);
        server.tick == Some(game.world.game_time)
    });
    if already_ticked {
        return changed;
    }
    SERVER.with(|cache| {
        cache
            .borrow_mut()
            .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
            .entry(pos)
            .or_default()
            .heat
            .reset()
    });
    for key in ["InputTanks", "OutputTanks"] {
        if let Some(tanks) = entity.nbt.get_mut(&key.into()) {
            let _ = fluids::tick_half(tanks);
        }
    }
    let scheduled = SERVER.with(|cache| {
        let mut cache = cache.borrow_mut();
        let s = cache
            .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
            .entry(pos)
            .or_default();
        if s.tick == Some(game.world.game_time) {
            return false;
        }
        if s.tick.is_some_and(|t| t > game.world.game_time) {
            *s = Server {
                owner: Some(owner),
                ..Server::default()
            };
        }
        // The duplicate-tick return above deliberately leaves this flag set.
        let mut scheduled = std::mem::take(&mut s.contents_changed) || !s.initialized;
        if !s.initialized {
            s.initialized = true;
            s.backup -= 1;
        }
        if s.lazy <= 0 {
            s.lazy = 10;
            if s.backup <= 0 {
                s.backup = 20;
                scheduled |= entity.items.iter().flatten().any(|s| s.count > 0)
                    || ["InputTanks", "OutputTanks"].into_iter().any(|key| {
                        read_tanks(entity, key)
                            .is_ok_and(|tanks| tanks.iter().flatten().any(|f| f.amount > 0))
                    });
            } else {
                s.backup -= 1;
            }
        } else {
            s.lazy -= 1;
        }
        s.tick = Some(game.world.game_time);
        scheduled
    });
    // Canonical serialization may normalize a supported loaded inventory's
    // order/numeric tags. Basin.read does not notify contents: only genuine
    // inventory/fluid events, initialization and the lazy backup wake it.
    if scheduled {
        crate::game::create_port_mixer::schedule(game, [pos[0], pos[1] + 2, pos[2]]);
        crate::game::create_port_press_basin::schedule(game, [pos[0], pos[1] + 2, pos[2]]);
    }
    if changed {
        let dim = game.dim.id().to_owned();
        game.native_update_output_neighbors(&dim, pos);
    }
    let reason = unsupported(game, pos, entity);
    match reason {
        Some(reason) => {
            entity.nbt.insert(
                "create_horizon:Unsupported".into(),
                Tag::String(reason.into()),
            );
        }
        None => {
            entity.nbt.remove(&"create_horizon:Unsupported".into());
        }
    }
    // Falling-item intake deliberately waits for the entity-sensitive basin
    // collision API; no guessed contact height or direct teleport is used.
    changed
}
pub(super) fn reacts(game: &Game<'_>, pos: Pos) -> bool {
    game.native_on("create")
        && game.native_block(pos) == ID
        && game.held().is_none_or(|s| {
            s.count == 0
                || matches!(
                    s.item.as_ref(),
                    "minecraft:air"
                        | "minecraft:water_bucket"
                        | "minecraft:lava_bucket"
                        | "minecraft:bucket"
                        | "minecraft:sponge"
                )
        })
}
pub(super) fn give_container(game: &mut Game<'_>, pos: Pos, stack: ItemStack) {
    let player = game.native_acting_id();
    if let Some(rest) = game.native_give_stack(player, stack) {
        if let Some(eye) = game.eye_position() {
            game.throw_from_eyes(rest, eye, false);
        } else {
            game.spawn_item(rest, pos.map(|v| f64::from(v) + 0.5), [0.0, 0.2, 0.0], 10);
        }
    }
}
fn bucket_click(game: &mut Game<'_>, pos: Pos, held: &ItemStack) -> bool {
    match held.item.as_ref() {
        "minecraft:water_bucket" | "minecraft:lava_bucket" => {
            let Some((fluid, amount, remainder)) = game.native_item_fluid_drain(held, 1000) else {
                return true;
            };
            let Some(mut state) = fluid_state(game, pos) else {
                return true;
            };
            let fluid = rules::Fluid {
                key: fluids::Key { id: fluid, components: Compound::new() },
                amount: amount as u32,
            };
            if fill_input(game, pos, &mut state, &fluid, true) != fluid.amount {
                return true;
            }
            fill_input(game, pos, &mut state, &fluid, false);
            if !game.creative {
                if held.count == 1 {
                    *game.held_mut() = Some(remainder);
                } else {
                    if let Some(s) = game.held_mut() {
                        s.count -= 1;
                    }
                    give_container(game, pos, remainder);
                }
            }
            true
        }
        "minecraft:bucket" => {
            let Some(mut state) = fluid_state(game, pos) else {
                return true;
            };
            for tank in 0..4 {
                let Some(mut fluid) = state.fluid(tank).cloned() else {
                    continue;
                };
                // API item containers cannot carry an opaque fluid component
                // patch. Refuse it explicitly rather than flattening it.
                if !fluid.key.components.is_empty() || fluid.amount < 1000 {
                    continue;
                }
                let Some((amount, filled)) = game.native_item_fluid_fill(held, &fluid.key.id, 1000)
                else {
                    continue;
                };
                if amount != 1000 {
                    continue;
                }
                fluid.amount = amount as u32;
                drain(game, pos, &mut state, rules::FluidRequest::Exact(&fluid), false);
                if !game.creative {
                    game.consume_held();
                    give_container(game, pos, filled);
                }
                return true;
            }
            true // GenericItemFilling claims even a refused/insufficient bucket.
        }
        "minecraft:sponge" => fluid_state(game, pos).is_some_and(|mut state| {
            drain(game, pos, &mut state, rules::FluidRequest::Any(i32::MAX as u32), false).is_some()
        }),
        _ => false,
    }
}
pub(super) fn right_click(game: &mut Game<'_>, pos: Pos) -> bool {
    if crate::game::create_port::inventory_blocked(game, pos) {
        return true;
    }
    if !reacts(game, pos) {
        return false;
    }
    if let Some(held) = game
        .held()
        .filter(|s| s.count > 0 && s.item.as_ref() != "minecraft:air")
        .cloned()
    {
        return bucket_click(game, pos, &held);
    }
    let stacks = game
        .native_with_mod_block_entity(pos, |entity| {
            restore(entity);
            let stacks = entity
                .items
                .iter_mut()
                .filter_map(Option::take)
                .collect::<Vec<_>>();
            data(entity);
            stacks
        })
        .unwrap_or_default();
    let player = game.native_acting_id();
    let success = !stacks.is_empty();
    for stack in stacks {
        if let Some(rest) = game.native_give_stack(player, stack) {
            if let Some(eye) = game.eye_position() {
                game.throw_from_eyes(rest, eye, false);
            } else {
                game.spawn_item(rest, pos.map(|v| f64::from(v) + 0.5), [0.0, 0.2, 0.0], 10);
            }
        }
    }
    if success {
        let pitch = 1.0 + game.world.random.next_float();
        game.with_level(|_, level, _| {
            level.native_play_sound(
                "minecraft:entity.item.pickup",
                pos.map(|v| f64::from(v) + 0.5),
                7,
                0.2,
                pitch,
            );
        });
    }
    game.native_block_entity_sync(pos);
    crate::game::create_port_mixer::basin_removed(game, [pos[0], pos[1] + 2, pos[2]]);
    crate::game::create_port_press_basin::basin_removed(game, [pos[0], pos[1] + 2, pos[2]]);
    true
}

/// Ordinary singleton FluidTankBlockEntity. A controller or non-singleton save
/// never falls back to empty storage. Towers, boiler and moving tanks need their
/// own topology adapter.
pub(super) mod tank {
    use super::*;
    use horizon_world::{level::PlacementContext, registry::BlockStateId};

    pub(in crate::game) const BLOCK: &str = "create:fluid_tank";
    const CAPACITY: u32 = 8000;
    const BUCKET: i32 = 1000;
    const TOTAL_HEIGHT: f32 = 7.0 / 16.0;
    type Fluid = rules::Fluid<fluids::Key>;

    #[derive(Default)]
    struct RenderLevel {
        owner: Option<ModRevision>,
        tick: Option<i64>,
        chase: rules::FluidLevel,
    }

    thread_local! {
        static RENDER: RefCell<SessionCache<BTreeMap<Pos, RenderLevel>>> = RefCell::new(SessionCache::default());
    }

    pub(super) fn reset() {
        RENDER.with(|cache| cache.borrow_mut().clear());
    }

    pub(in crate::game) fn default_nbt() -> Compound {
        Compound::from([
            (
                "Boiler".into(),
                Tag::Compound(Compound::from([
                    ("ActiveHeat".into(), Tag::Int(0)),
                    ("Engines".into(), Tag::Int(0)),
                    ("PassiveHeat".into(), Tag::Byte(0)),
                    ("Supply".into(), Tag::Float(0)),
                    ("Update".into(), Tag::Byte(0)),
                    ("Whistles".into(), Tag::Int(0)),
                ])),
            ),
            ("Height".into(), Tag::Int(1)),
            ("Size".into(), Tag::Int(1)),
            ("Luminosity".into(), Tag::Int(0)),
            ("Window".into(), Tag::Byte(1)),
            ("TankContent".into(), Tag::Compound(Compound::new())),
        ])
    }

    fn read(entity: &ModBlockEntity) -> Option<(bool, Option<Fluid>)> {
        let nbt = &entity.nbt;
        if entity.id != BLOCK
            || nbt.contains_key(&"Controller".into())
            || !matches!(nbt.get(&"Size".into()), Some(Tag::Int(1)))
            || !matches!(nbt.get(&"Height".into()), Some(Tag::Int(1)))
        {
            return None;
        }
        let Tag::Compound(boiler) = nbt.get(&"Boiler".into())? else {
            return None;
        };
        if ["Engines", "Whistles"]
            .iter()
            .any(|key| !matches!(boiler.get(&(*key).into()), Some(Tag::Int(0))))
        {
            return None;
        }
        let window = match nbt.get(&"Window".into())? {
            Tag::Byte(value @ (0 | 1)) => *value != 0,
            _ => return None,
        };
        Some((
            window,
            fluids::read_content(nbt.get(&"TankContent".into()), CAPACITY).ok()?,
        ))
    }

    fn entity_at<'a>(game: &'a Game<'_>, [x, y, z]: Pos) -> Option<&'a ModBlockEntity> {
        match game.world.block_entities.get(&(x, y, z))? {
            BlockEntity::Mod(entity) => Some(entity),
            _ => None,
        }
    }

    /// `FluidTankBlockEntity.getMaxWidth` / `getMaxHeight` (server config defaults).
    const MAX_WIDTH: i32 = 3;
    const MAX_HEIGHT: i32 = 32;

    /// One tank multiblock: its north-west bottom corner (the Java controller
    /// position), its width and its height.
    #[derive(Clone, Copy, PartialEq, Eq, Debug)]
    pub(in crate::game) struct Layout {
        pub(in crate::game) origin: Pos,
        pub(in crate::game) width: i32,
        pub(in crate::game) height: i32,
    }

    impl Layout {
        pub(in crate::game) fn members(self) -> Vec<Pos> {
            let mut result = Vec::new();
            for y in 0..self.height {
                for x in 0..self.width {
                    for z in 0..self.width {
                        result.push([self.origin[0] + x, self.origin[1] + y, self.origin[2] + z]);
                    }
                }
            }
            result
        }
    }

    /// Tanks connected to `pos`, at most this many (a larger mass of tanks
    /// falls back to columns).
    const SEARCH_LIMIT: usize = 4096;

    /// How a connected group of tanks splits into multiblocks, following
    /// `ConnectivityHandler.tryToFormNewMulti`: from the lowest, then
    /// north-west-most free tank, take the width (1 to 3) that holds the most
    /// tanks (the wider on a tie) and grow it upward while every layer is
    /// complete, up to 32. A complete box is one tank whatever order it was
    /// built in; leftovers form their own smaller tanks.
    pub(in crate::game) fn partition(is_tank: impl Fn(Pos) -> bool, pos: Pos) -> Vec<Layout> {
        if !is_tank(pos) {
            return Vec::new();
        }
        let mut seen = std::collections::BTreeSet::from([pos]);
        let mut queue = vec![pos];
        let mut overflow = false;
        while let Some(at) = queue.pop() {
            for offset in [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]] {
                let next: Pos = std::array::from_fn(|i| at[i] + offset[i]);
                if seen.contains(&next) || !is_tank(next) {
                    continue;
                }
                if seen.len() >= SEARCH_LIMIT {
                    overflow = true;
                    queue.clear();
                    break;
                }
                seen.insert(next);
                queue.push(next);
            }
        }
        if overflow {
            return vec![column(&is_tank, pos)];
        }
        // Order: y, then x, then z (BTreeSet<[i32; 3]> sorts x first).
        let mut order: Vec<Pos> = seen.iter().copied().collect();
        order.sort_by_key(|p| (p[1], p[0], p[2]));
        let mut free = seen;
        let mut result = Vec::new();
        for origin in order {
            if !free.contains(&origin) {
                continue;
            }
            let mut best = Layout { origin, width: 1, height: 1 };
            let mut best_amount = 0;
            for width in 1..=MAX_WIDTH {
                let mut height = 0;
                while height < MAX_HEIGHT
                    && (0..width).all(|x| {
                        (0..width).all(|z| {
                            free.contains(&[origin[0] + x, origin[1] + height, origin[2] + z])
                        })
                    })
                {
                    height += 1;
                }
                let amount = width * width * height;
                if height > 0 && amount >= best_amount {
                    best = Layout { origin, width, height };
                    best_amount = amount;
                }
            }
            for member in best.members() {
                free.remove(&member);
            }
            result.push(best);
        }
        result
    }

    fn column(is_tank: &impl Fn(Pos) -> bool, pos: Pos) -> Layout {
        let mut bottom = pos[1];
        for _ in 1..MAX_HEIGHT {
            if !is_tank([pos[0], bottom - 1, pos[2]]) {
                break;
            }
            bottom -= 1;
        }
        let mut height = 1;
        while height < MAX_HEIGHT && is_tank([pos[0], bottom + height, pos[2]]) {
            height += 1;
        }
        Layout { origin: [pos[0], bottom, pos[2]], width: 1, height }
    }

    impl Layout {
        fn contains(self, pos: Pos) -> bool {
            (0..3).all(|i| {
                let size = if i == 1 { self.height } else { self.width };
                (self.origin[i]..self.origin[i] + size).contains(&pos[i])
            })
        }
    }

    /// The multiblock `pos` belongs to.
    pub(in crate::game) fn layout(is_tank: impl Fn(Pos) -> bool, pos: Pos) -> Option<Layout> {
        partition(is_tank, pos).into_iter().find(|layout| layout.contains(pos))
    }

    fn is_tank_at(game: &Game<'_>, [x, y, z]: Pos) -> bool {
        game.world.loaded(x, z)
            && game
                .pack
                .assets
                .registry
                .state(game.world.block(x, y, z))
                .is_some_and(|state| state.name == BLOCK)
    }

    thread_local! {
        /// Layouts found this tick, so a group is split once per tick rather
        /// than once per member.
        static LAYOUTS: RefCell<(usize, i64, BTreeMap<Pos, Layout>)> = RefCell::new((0, i64::MIN, BTreeMap::new()));
    }

    pub(in crate::game) fn layout_at(game: &Game<'_>, pos: Pos) -> Option<Layout> {
        if !is_tank_at(game, pos) {
            return None;
        }
        let world = std::ptr::from_ref(&game.world) as usize;
        let time = game.world.game_time;
        LAYOUTS.with(|cache| {
            let mut cache = cache.borrow_mut();
            if cache.0 != world || cache.1 != time {
                *cache = (world, time, BTreeMap::new());
            }
            if let Some(found) = cache.2.get(&pos) {
                return Some(*found);
            }
            let groups = partition(|at| is_tank_at(game, at), pos);
            for group in &groups {
                for member in group.members() {
                    cache.2.insert(member, *group);
                }
            }
            groups.into_iter().find(|group| group.contains(pos))
        })
    }

    fn members(game: &Game<'_>, pos: Pos) -> Vec<Pos> {
        if game.options.execution_role.is_client() || !game.native_on("create") {
            return Vec::new();
        }
        layout_at(game, pos).map_or_else(Vec::new, Layout::members)
    }

    /// `FluidTankBlockEntity.setWindows`: the shape one member shows.
    fn window_shape(window: bool, width: i32, x: i32, z: i32) -> &'static str {
        if !window {
            return "plain";
        }
        match width {
            1 => "window",
            2 => match (x == 0, z == 0) {
                (true, true) => "window_nw",
                (true, false) => "window_sw",
                (false, true) => "window_ne",
                (false, false) => "window_se",
            },
            3 if (x.abs() - z.abs()).abs() == 1 => "window",
            _ => "plain",
        }
    }

    fn property(game: &Game<'_>, [x, y, z]: Pos, key: &str) -> Option<String> {
        game.pack
            .assets
            .registry
            .state(game.world.block(x, y, z))?
            .properties
            .get(key)
            .cloned()
    }

    /// A multiblock shows windows while any member does: a 3×3 keeps its
    /// corners and centre plain even with windows on.
    fn group_window(game: &Game<'_>, layout: Layout) -> bool {
        layout
            .members()
            .into_iter()
            .any(|at| property(game, at, "shape").is_some_and(|shape| shape != "plain"))
    }

    /// `notifyMultiUpdated` + `setWindows` for one member: top, bottom and the
    /// window shape follow the multiblock it now belongs to.
    fn sync_member(game: &mut Game<'_>, pos: Pos, layout: Layout, window: bool) {
        let shape = window_shape(window, layout.width, pos[0] - layout.origin[0], pos[2] - layout.origin[2]);
        let top = if pos[1] == layout.origin[1] + layout.height - 1 { "true" } else { "false" };
        let bottom = if pos[1] == layout.origin[1] { "true" } else { "false" };
        for (key, value) in [("shape", shape), ("top", top), ("bottom", bottom)] {
            if property(game, pos, key).as_deref() != Some(value) {
                game.native_set_block_property_with(
                    pos,
                    key,
                    value,
                    horizon_world::level::flags::UPDATE_CLIENTS,
                );
            }
        }
    }

    fn network(game: &Game<'_>, pos: Pos) -> Option<(Vec<Pos>, bool, Option<Fluid>)> {
        let members = members(game, pos);
        if members.is_empty() {
            return None;
        }
        let mut window = true;
        let mut fluid = None;
        let mut amount = 0;
        for member in &members {
            let (member_window, member_fluid) = read(entity_at(game, *member)?)?;
            window &= member_window;
            if let Some(member_fluid) = member_fluid {
                if fluid
                    .as_ref()
                    .is_some_and(|existing: &Fluid| existing.key != member_fluid.key)
                {
                    return None;
                }
                amount += member_fluid.amount;
                fluid = Some(member_fluid);
            }
        }
        if let Some(fluid) = fluid.as_mut() {
            fluid.amount = amount;
        }
        Some((members, window, fluid))
    }

    fn current(game: &Game<'_>, pos: Pos) -> Option<(bool, Option<Fluid>)> {
        let (_, window, fluid) = network(game, pos)?;
        Some((window, fluid))
    }

    pub(in crate::game) fn shape(
        game: &GameLevel<'_>,
        state: BlockStateId,
        side: create_engine::placement::Direction,
        neighbor: BlockStateId,
        new: &mut Option<BlockStateId>,
    ) {
        let Some(current) = game.registry.state(state) else {
            return;
        };
        if current.name != BLOCK {
            return;
        }
        let neighbor_is_tank = game
            .registry
            .state(neighbor)
            .is_some_and(|state| state.name == BLOCK);
        let property = match side {
            create_engine::placement::Direction::Up => "top",
            create_engine::placement::Direction::Down => "bottom",
            _ => return,
        };
        let desired = if neighbor_is_tank { "false" } else { "true" };
        if current.properties.get(property).map(String::as_str) == Some(desired) {
            return;
        }
        *new = Some(
            game.native_state_with_property(state, property, desired)
                .unwrap_or(state),
        );
    }

    pub(in crate::game) fn placement(game: &GameLevel<'_>, ctx: &PlacementContext) -> bool {
        // Java places a tank anywhere and lets ConnectivityHandler merge it.
        // The neighbours must be loaded so the multiblock can be read.
        let [x, z] = [ctx.pos.x, ctx.pos.z];
        (-MAX_WIDTH..=MAX_WIDTH)
            .all(|dx| (-MAX_WIDTH..=MAX_WIDTH).all(|dz| game.world.loaded(x + dx, z + dz)))
    }

    pub(in crate::game) fn tick(game: &mut Game<'_>, pos: Pos, entity: &mut ModBlockEntity) {
        // Re-read the multiblock every 10 ticks, staggered per position.
        let stagger = i64::from((pos[0] ^ pos[1].wrapping_mul(31) ^ pos[2].wrapping_mul(17)) & 7);
        if !game.options.execution_role.is_client()
            && (game.world.game_time + stagger) % 10 == 0
            && let Some(layout) = layout_at(game, pos)
        {
            let window = group_window(game, layout);
            sync_member(game, pos, layout, window);
            if matches!(entity.nbt.get(&"Window".into()), Some(Tag::Byte(value)) if (*value != 0) != window)
            {
                entity.nbt.insert("Window".into(), Tag::Byte(i8::from(window)));
                game.world.modified.insert((pos[0] >> 4, pos[2] >> 4));
                game.native_block_entity_sync(pos);
            }
        }
        if entity.nbt.contains_key(&"LastKnownPos".into()) || read(entity).is_none() {
            return;
        }
        entity
            .nbt
            .insert("LastKnownPos".into(), Tag::IntArray(pos.to_vec()));
        game.world.modified.insert((pos[0] >> 4, pos[2] >> 4));
    }

    fn fraction(fluid: Option<&Fluid>) -> f32 {
        fluid.map_or(0.0, |fluid| fluid.amount as f32 / CAPACITY as f32)
    }

    pub(super) fn comparator(entity: &ModBlockEntity) -> i32 {
        read(entity).map_or(0, |(_, fluid)| {
            let fraction = f64::from(fraction(fluid.as_ref()));
            (fraction * 14.0 + f64::from(u8::from(fraction > 0.0))).floor() as i32
        })
    }

    /// `FluidTankBlockEntity` comparator output: the fill of the whole
    /// multiblock, read from any member.
    pub(super) fn comparator_group(game: &GameLevel<'_>, pos: Pos) -> Option<i32> {
        let is_tank = |[x, y, z]: Pos| {
            game.world.loaded(x, z) && game.facts.get(game.world.block(x, y, z)).name.as_ref() == BLOCK
        };
        let members = layout(is_tank, pos)?.members();
        let mut amount = 0u64;
        for [x, y, z] in &members {
            let Some(BlockEntity::Mod(entity)) = game.world.block_entities.get(&(*x, *y, *z)) else {
                return None;
            };
            let (_, fluid) = read(entity)?;
            amount += u64::from(fluid.map_or(0, |fluid| fluid.amount));
        }
        let fraction = amount as f64 / (u64::from(CAPACITY) * members.len() as u64) as f64;
        Some((fraction * 14.0 + f64::from(u8::from(fraction > 0.0))).floor() as i32)
    }

    pub(super) fn view(game: &Game<'_>, pos: Pos) -> Option<Vec<NativeFluidTankView>> {
        let (members, _, fluid) = network(game, pos)?;
        Some(vec![NativeFluidTankView {
            tank: 0,
            content: fluid.as_ref().map(native_fluid),
            capacity: (CAPACITY * members.len() as u32) as i32,
            can_fill: true,
            can_drain: true,
        }])
    }

    fn tank_fields(fluid: Option<&Fluid>) -> Option<(Tag, Tag)> {
        let content = fluids::write_content(fluid, CAPACITY).ok()?;
        let luminosity = fluid.map_or(0, |fluid| {
            if fluid.key.id == "minecraft:lava" {
                12
            } else {
                0
            }
        });
        Some((content, Tag::Int(luminosity)))
    }

    fn set_fields(game: &mut Game<'_>, pos: Pos, (content, luminosity): (Tag, Tag)) -> bool {
        game.native_with_mod_block_entity(pos, |entity| {
            entity.nbt.insert("TankContent".into(), content);
            entity.nbt.insert("Luminosity".into(), luminosity);
        })
        .is_some()
    }

    fn notify(game: &mut Game<'_>, pos: Pos) {
        game.native_block_entity_sync(pos);
        game.native_update_output_neighbors(game.dim.id(), pos);
    }

    pub(super) fn endpoint(game: &Game<'_>, pos: Pos) -> bool {
        current(game, pos)
            .is_some_and(|(_, fluid)| fluid.is_none_or(|fluid| fluid.key.components.is_empty()))
    }

    pub(super) fn sample(
        game: &Game<'_>,
        pos: Pos,
    ) -> Option<create_engine::fluid_transport::Fluid> {
        let (_, fluid) = current(game, pos)?;
        let fluid = fluid?;
        if !fluid.key.components.is_empty() {
            return None;
        }
        create_engine::fluid_transport::Fluid::from_id(&fluid.key.id)
    }

    pub(super) fn amount(game: &Game<'_>, pos: Pos) -> Option<u32> {
        let (_, fluid) = current(game, pos)?;
        Some(fluid.map_or(0, |fluid| fluid.amount))
    }

    pub(super) fn transfer_pair(
        game: &mut Game<'_>,
        source: Pos,
        target: Pos,
        kind: create_engine::fluid_transport::Fluid,
        rate: i32,
    ) {
        if source == target || rate <= 0 {
            return;
        }
        let Some((source_members, _, Some(mut from))) = network(game, source) else {
            return;
        };
        let Some((target_members, _, to)) = network(game, target) else {
            return;
        };
        if from.key.id != kind.id()
            || !from.key.components.is_empty()
            || to.as_ref().is_some_and(|fluid| fluid.key != from.key)
        {
            return;
        }
        let received = total_amount(game, &target_members);
        let capacity = CAPACITY * target_members.len() as u32;
        let moved = (rate as u32).min(from.amount).min(capacity.saturating_sub(received));
        if moved == 0 {
            return;
        }
        from.amount -= moved;
        if !write_total(game, &source_members, (from.amount > 0).then_some(&from)) {
            return;
        }
        let into = Fluid {
            key: from.key.clone(),
            amount: received + moved,
        };
        let _ = write_total(game, &target_members, Some(&into));
    }

    fn total_amount(game: &Game<'_>, members: &[Pos]) -> u32 {
        members
            .iter()
            .filter_map(|pos| entity_at(game, *pos))
            .filter_map(|entity| read(entity).and_then(|(_, fluid)| fluid))
            .map(|fluid| fluid.amount)
            .sum()
    }

    fn write_total(game: &mut Game<'_>, members: &[Pos], fluid: Option<&Fluid>) -> bool {
        let Some(fluid) = fluid else {
            for &pos in members {
                let Some(fields) = tank_fields(None) else { return false; };
                if !set_fields(game, pos, fields) {
                    return false;
                }
                notify(game, pos);
            }
            return true;
        };
        // Fill layer by layer from the bottom, sharing each layer evenly, so
        // every member's own content matches the level the multiblock shows.
        let mut remaining = fluid.amount;
        for layer in members.chunk_by(|a, b| a[1] == b[1]) {
            let count = layer.len() as u32;
            let amount = remaining.min(CAPACITY * count);
            remaining -= amount;
            for (index, &pos) in layer.iter().enumerate() {
                let share = amount / count + u32::from((index as u32) < amount % count);
                let Some(fields) = tank_fields((share > 0).then_some(&Fluid {
                    key: fluid.key.clone(),
                    amount: share,
                })) else {
                    return false;
                };
                if !set_fields(game, pos, fields) {
                    return false;
                }
                notify(game, pos);
            }
        }
        remaining == 0
    }

    pub(super) fn fill(
        game: &mut Game<'_>,
        pos: Pos,
        resource: &NativeFluidStack,
        action: NativeFluidAction,
    ) -> Option<i32> {
        let (members, _, current) = network(game, pos)?;
        let Some(mut fluid) = core_fluid(resource) else {
            return Some(0);
        };
        let stored = match current {
            Some(current) if current.key == fluid.key => current.amount,
            Some(_) => return Some(0),
            None => 0,
        };
        let capacity = CAPACITY * members.len() as u32;
        let accepted = fluid.amount.min(capacity.saturating_sub(stored));
        #[allow(unreachable_patterns)]
        match action {
            NativeFluidAction::Simulate => {}
            NativeFluidAction::Execute => {
                fluid.amount = stored + accepted;
                if accepted != 0 && !write_total(game, &members, Some(&fluid)) {
                    return Some(0);
                }
            }
            _ => return Some(0),
        }
        Some(accepted as i32)
    }

    pub(super) fn drain(
        game: &mut Game<'_>,
        pos: Pos,
        request: &NativeFluidDrain,
        action: NativeFluidAction,
    ) -> Option<NativeFluidStack> {
        let (members, _, fluid) = network(game, pos)?;
        let mut fluid = fluid?;
        let maximum = match request {
            NativeFluidDrain::Any(maximum) => *maximum,
            NativeFluidDrain::Exact(wanted)
                if wanted.fluid == fluid.key.id && wanted.components == fluid.key.components =>
            {
                wanted.amount
            }
            _ => return None,
        };
        if maximum <= 0 {
            return None;
        }
        let drained = fluid.amount.min(maximum as u32);
        #[allow(unreachable_patterns)]
        match action {
            NativeFluidAction::Simulate => {}
            NativeFluidAction::Execute => {
                fluid.amount -= drained;
                if !write_total(game, &members, (fluid.amount > 0).then_some(&fluid)) {
                    return None;
                }
            }
            _ => return None,
        }
        fluid.amount = drained;
        Some(native_fluid(&fluid))
    }

    pub(in crate::game) fn predicts_use(game: &Game<'_>, pos: Pos) -> bool {
        game.native_on("create")
            && game.native_block(pos) == BLOCK
            && !game.native_sneaking()
            && game
                .held()
                .filter(|held| held.count > 0)
                .is_some_and(|held| {
                    game.may_build() && crate::game::create_port_chassis::wrench(game, held)
                        || game.creative
                            && matches!(
                                held.item.as_ref(),
                                "minecraft:bucket"
                                    | "minecraft:water_bucket"
                                    | "minecraft:lava_bucket"
                            )
                })
    }

    pub(in crate::game) fn right_click(game: &mut Game<'_>, pos: Pos) -> bool {
        if !predicts_use(game, pos) {
            return false;
        }
        let Some((_, before)) = current(game, pos) else {
            return true;
        };
        let Some(held) = game.held().cloned() else {
            return false;
        };
        if crate::game::create_port_chassis::wrench(game, &held) {
            // FluidTankBlockEntity.toggleWindows: the whole multiblock at once.
            let Some(layout) = layout_at(game, pos) else {
                return true;
            };
            let window = !group_window(game, layout);
            for member in layout.members() {
                sync_member(game, member, layout, window);
                game.native_with_mod_block_entity(member, |entity| {
                    entity.nbt.insert("Window".into(), Tag::Byte(i8::from(window)));
                });
                game.native_block_entity_sync(member);
            }
            return true;
        }
        let (fluid, amount, emptying) = if held.item.as_ref() == "minecraft:bucket" {
            let Some(mut resource) = before
                .as_ref()
                .map(native_fluid)
                .filter(|f| f.components.is_empty())
            else {
                return true;
            };
            if resource.amount < BUCKET
                || game
                    .native_item_fluid_fill(&held, &resource.fluid, BUCKET)
                    .is_none_or(|(amount, _)| amount != BUCKET)
            {
                return true;
            }
            let remaining = resource.amount - BUCKET;
            resource.amount = BUCKET;
            let request = NativeFluidDrain::Exact(resource);
            let mut drained = None;
            game.native_custom_fluid_drain(
                pos,
                None,
                &request,
                NativeFluidAction::Execute,
                &mut drained,
            );
            let Some(drained) = drained else {
                return true;
            };
            (drained.fluid, remaining, false)
        } else {
            let Some((fluid, amount, _)) = game.native_item_fluid_drain(&held, BUCKET) else {
                return true;
            };
            let resource = NativeFluidStack {
                fluid,
                amount,
                components: Compound::new(),
            };
            let mut accepted = None;
            game.native_custom_fluid_fill(
                pos,
                None,
                &resource,
                NativeFluidAction::Simulate,
                &mut accepted,
            );
            if accepted != Some(amount) {
                return true;
            }
            accepted = None;
            game.native_custom_fluid_fill(
                pos,
                None,
                &resource,
                NativeFluidAction::Execute,
                &mut accepted,
            );
            if accepted != Some(amount) {
                return true;
            }
            (
                resource.fluid,
                before.as_ref().map_or(0, |f| f.amount as i32) + amount,
                true,
            )
        };
        play_bucket(game, pos, &fluid, amount, emptying);
        true
    }

    fn play_bucket(game: &mut Game<'_>, pos: Pos, fluid: &str, amount: i32, emptying: bool) {
        let event = match (emptying, fluid) {
            (true, "minecraft:lava") => "minecraft:item.bucket.empty_lava",
            (false, "minecraft:lava") => "minecraft:item.bucket.fill_lava",
            (true, _) => "minecraft:item.bucket.empty",
            (false, _) => "minecraft:item.bucket.fill",
        };
        game.with_level(|_, level, _| {
            let Some(random) = level.native_level_random() else {
                return;
            };
            let pitch = (1.0 - amount as f32 / (CAPACITY as f32 * 16.0)).clamp(0.0, 1.0) / 1.5
                + 0.5
                + (random.next_float() - 0.5) / 4.0;
            level.native_play_sound(
                event,
                pos.map(|coordinate| f64::from(coordinate) + 0.5),
                4,
                0.5,
                pitch,
            );
        });
    }

    pub(super) fn client_tick(
        session: usize,
        dimension: &str,
        time: i64,
        entries: &[(Pos, &ModBlockEntity)],
    ) {
        RENDER.with(|cache| {
            let mut cache = cache.borrow_mut();
            let cache = cache.dimension(session, dimension);
            let mut live = std::collections::BTreeSet::new();
            for &(pos, entity) in entries.iter().filter(|(_, e)| e.id == BLOCK) {
                let Some((_, fluid)) = read(entity) else {
                    continue;
                };
                live.insert(pos);
                let owner = entity.revision();
                let target = fraction(fluid.as_ref());
                let motion = cache.entry(pos).or_default();
                if motion.tick.is_some_and(|old| old > time)
                    || motion
                        .owner
                        .is_none_or(|old| !old.is_same_create_entity(owner))
                {
                    *motion = RenderLevel {
                        owner: Some(owner),
                        tick: None,
                        chase: rules::FluidLevel {
                            previous: target,
                            value: target,
                            target,
                            speed: 0.5,
                        },
                    };
                }
                motion.chase.target = target;
                if motion.tick != Some(time) {
                    motion.chase.tick();
                    motion.tick = Some(time);
                }
            }
            cache.retain(|pos, _| live.contains(pos));
        });
    }

    pub(in crate::game) fn draw(
        game: &Game<'_>,
        pos: Pos,
        entity: &ModBlockEntity,
        draw: &mut BlockEntityDraw,
    ) {
        let Some((true, own)) = read(entity) else {
            return;
        };
        let layout = layout_at(game, pos).unwrap_or(Layout { origin: pos, width: 1, height: 1 });
        if layout.width * layout.width * layout.height > 1 {
            draw_multi(game, pos, layout, draw);
            return;
        }
        let Some(fluid) = own else {
            return;
        };
        let level = RENDER.with(|cache| {
            cache
                .borrow_mut()
                .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
                .get(&pos)
                .filter(|motion| {
                    motion
                        .owner
                        .is_some_and(|old| old.is_same_create_entity(entity.revision()))
                })
                .map_or_else(
                    || fraction(Some(&fluid)),
                    |motion| motion.chase.at(draw.partial),
                )
        });
        if level < 1.0 / (512.0 * TOTAL_HEIGHT) {
            return;
        }
        let hull = 1.0 / 16.0 + 1.0 / 128.0;
        let floor = 5.0 / 16.0;
        let height = (level * TOTAL_HEIGHT).clamp(0.0, TOTAL_HEIGHT);
        game.native_draw_fluid_box(
            draw,
            &native_fluid(&fluid),
            [hull, floor, hull, 1.0 - hull, floor + height, 1.0 - hull],
            NativeFluidRenderOptions {
                argb: None,
                render_bottom: false,
                uv_shrink_ratio: 4.0 / 2048.0,
            },
        );
    }

    /// FluidTankRenderer for a multiblock: one fluid box over the whole tank,
    /// cut into the part inside this member.
    fn draw_multi(game: &Game<'_>, pos: Pos, layout: Layout, draw: &mut BlockEntityDraw) {
        let mut fluid: Option<Fluid> = None;
        let mut amount = 0;
        let members = layout.members();
        for member in &members {
            let Some((_, Some(content))) = entity_at(game, *member).and_then(read) else {
                continue;
            };
            if fluid.as_ref().is_some_and(|f| f.key != content.key) {
                continue;
            }
            amount += content.amount;
            fluid = Some(content);
        }
        let Some(mut fluid) = fluid else {
            return;
        };
        fluid.amount = amount;
        let level = amount as f32 / (CAPACITY * members.len() as u32) as f32;
        let cap = 1.0 / 4.0;
        let puddle = 1.0 / 16.0;
        let total = layout.height as f32 - 2.0 * cap - puddle;
        if level < 1.0 / (512.0 * total) {
            return;
        }
        let hull = 1.0 / 16.0 + 1.0 / 128.0;
        let width = layout.width as f32;
        let floor = cap + puddle;
        let top = floor + (level * total).clamp(0.0, total);
        let offset = [
            (pos[0] - layout.origin[0]) as f32,
            (pos[1] - layout.origin[1]) as f32,
            (pos[2] - layout.origin[2]) as f32,
        ];
        let low = [hull - offset[0], floor - offset[1], hull - offset[2]];
        let high = [width - hull - offset[0], top - offset[1], width - hull - offset[2]];
        let low = low.map(|v| v.max(0.0));
        let high = high.map(|v| v.min(1.0));
        if (0..3).any(|i| high[i] <= low[i]) {
            return;
        }
        game.native_draw_fluid_box(
            draw,
            &native_fluid(&fluid),
            [low[0], low[1], low[2], high[0], high[1], high[2]],
            NativeFluidRenderOptions {
                argb: None,
                render_bottom: false,
                uv_shrink_ratio: 4.0 / 2048.0,
            },
        );
    }
}

pub(super) fn removed(game: &mut Game<'_>, pos: Pos) {
    SERVER.with(|cache| {
        cache
            .borrow_mut()
            .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
            .remove(&pos);
    });
    crate::game::create_port_mixer::basin_removed(game, [pos[0], pos[1] + 2, pos[2]]);
    crate::game::create_port_press_basin::basin_removed(game, [pos[0], pos[1] + 2, pos[2]]);
}
pub(super) fn maintenance(game: &mut Game<'_>) {
    SERVER.with(|cache| {
        cache
            .borrow_mut()
            .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
            .retain(|p, _| game.world.loaded(p[0], p[2]) && game.native_block(*p) == ID);
    });
}
/// FluidTransportBehaviour adapter for one dry, closed, straight line.
pub(super) mod pump {
    use super::*;
    use create_engine::{fluid_transport as flow, placement::Direction};
    use horizon_world::{chunk::BlockState, level::PlacementContext, registry::BlockStateId};
    use std::rc::Rc;

    pub(in crate::game) const PUMP: &str = "create:mechanical_pump";
    pub(in crate::game) const PIPE: &str = "create:fluid_pipe";
    pub(in crate::game) const VALVE: &str = "create:fluid_valve";

    struct Line {
        pump: Pos,
        front: Direction,
        source: Pos,
        target: Pos,
        devices: Vec<Pos>,
        /// For each device, the face fluid enters through and the face it
        /// leaves through, in flow order (bends included).
        sides: Vec<(Direction, Direction)>,
        valve: Option<(Pos, bool)>,
    }

    #[derive(Default)]
    struct TickState {
        owner: Option<ModRevision>,
        line: Option<(Pos, Direction, Pos, Pos)>,
        valve: Option<(Pos, bool)>,
        pressure: f32,
        phase: u8,
        source_ticks: u8,
    }

    #[derive(Default)]
    struct Lines {
        tick: Option<i64>,
        by_device: BTreeMap<Pos, Option<Rc<Line>>>,
        live: BTreeMap<Pos, TickState>,
    }

    thread_local! {
        static NETWORKS: RefCell<SessionCache<Lines>> = RefCell::new(SessionCache::default());
    }

    pub(super) fn reset() {
        NETWORKS.with(|networks| networks.borrow_mut().clear());
    }

    fn relative(pos: Pos, direction: Direction, distance: i32) -> Pos {
        let offset = direction.vector();
        std::array::from_fn(|i| pos[i] + offset[i] * distance)
    }

    fn dry(state: &BlockState) -> bool {
        state
            .properties
            .get("waterlogged")
            .is_some_and(|value| value == "false")
    }

    fn front(state: &BlockState) -> Option<Direction> {
        let name = state.properties.get("facing")?;
        Direction::ALL.into_iter().find(|side| side.name() == name)
    }

    fn axis(state: &BlockState) -> Option<create_engine::kinetics::Axis> {
        let mut sides = Direction::ALL.into_iter().filter(|side| {
            state
                .properties
                .get(side.name())
                .is_some_and(|v| v == "true")
        });
        let first = sides.next()?;
        sides.all(|side| side.axis() == first.axis()).then_some(first.axis())
    }

    fn open(state: &BlockState, side: Direction) -> bool {
        state.properties.get(side.name()).is_some_and(|value| value == "true")
    }

    /// `FluidPipeBlock.canConnectTo` for the blocks this port moves fluid
    /// through: any pipe, a tank, and pumps and valves along their axis.
    fn joins(adjacent: &BlockState, side: Direction) -> bool {
        match adjacent.name.as_str() {
            PIPE | tank::BLOCK => true,
            PUMP => front(adjacent).is_some_and(|front| front.axis() == side.axis()),
            VALVE => valve_axis(adjacent, false) == Some(side.axis()),
            _ => false,
        }
    }

    fn joins_at(game: &GameLevel<'_>, pos: Pos, side: Direction) -> bool {
        let [x, y, z] = relative(pos, side, 1);
        game.world.loaded(x, z)
            && game
                .registry
                .state(game.world.block(x, y, z))
                .is_some_and(|adjacent| joins(adjacent, side))
    }

    /// `FluidPipeBlock.updateBlockState`: every face but `ignore` follows its
    /// neighbour (`known` answers for a neighbour not yet in the world); a
    /// single connection opens the opposite end; with none, a straight pipe
    /// stays as it was and anything else straightens along `preferred`.
    /// Corners, tees and crosses are kept, as in Create.
    fn update_faces(
        game: &GameLevel<'_>,
        pos: Pos,
        previous: &[(Direction, bool)],
        preferred: Direction,
        ignore: Option<Direction>,
        known: Option<(Direction, bool)>,
    ) -> Vec<(Direction, bool)> {
        let before = previous.iter().filter(|(_, open)| *open).count();
        let mut faces: Vec<(Direction, bool)> = previous
            .iter()
            .map(|&(side, open)| {
                if Some(side) == ignore {
                    (side, open)
                } else if let Some((_, value)) = known.filter(|(known, _)| *known == side) {
                    (side, value)
                } else {
                    (side, joins_at(game, pos, side))
                }
            })
            .collect();
        let connected: Vec<Direction> = faces.iter().filter(|f| f.1).map(|f| f.0).collect();
        match connected.as_slice() {
            [_, _, ..] => {}
            [only] => {
                let opposite = only.opposite();
                for face in &mut faces {
                    if face.0 == opposite {
                        face.1 = true;
                    }
                }
            }
            [] if before == 2 => return previous.to_vec(),
            [] => {
                for face in &mut faces {
                    face.1 = face.0 == preferred || face.0 == preferred.opposite();
                }
            }
        }
        faces
    }

    fn with_faces(
        game: &GameLevel<'_>,
        mut state: BlockStateId,
        faces: &[(Direction, bool)],
    ) -> Option<BlockStateId> {
        for &(side, open) in faces {
            state = game.native_state_with_property(
                state,
                side.name(),
                if open { "true" } else { "false" },
            )?;
        }
        Some(state)
    }

    /// `FluidPipeBlock.updateShape` after a neighbouring block changes.
    pub(in crate::game) fn shape(
        game: &GameLevel<'_>,
        pos: Pos,
        state: BlockStateId,
        side: Direction,
        neighbor: BlockStateId,
        new: &mut Option<BlockStateId>,
    ) {
        let Some(current) = game.registry.state(state) else {
            return;
        };
        if current.name != PIPE {
            return;
        }
        let previous: Vec<(Direction, bool)> =
            Direction::ALL.into_iter().map(|face| (face, open(current, face))).collect();
        let joined = game
            .registry
            .state(neighbor)
            .is_some_and(|adjacent| joins(adjacent, side));
        let faces = update_faces(
            game,
            pos,
            &previous,
            side,
            Some(side.opposite()),
            Some((side, joined)),
        );
        if faces == previous {
            return;
        }
        if let Some(next) = with_faces(game, state, &faces) {
            *new = Some(next);
        }
    }

    fn enabled(state: &BlockState) -> bool {
        state
            .properties
            .get("enabled")
            .is_some_and(|value| value == "true")
    }

    fn valve_axis(state: &BlockState, shaft: bool) -> Option<create_engine::kinetics::Axis> {
        let first = state.properties.get("axis_along_first")? == "true";
        Some(create_engine::placement::gauge_axis(
            front(state)?,
            first == shaft,
        ))
    }

    fn state<'a>(game: &'a Game<'_>, pos: Pos) -> Option<&'a BlockState> {
        let [x, y, z] = pos;
        if !game.world.loaded(x, z) {
            return None;
        }
        game.pack.assets.registry.state(game.world.block(x, y, z))
    }

    fn device_axis(state: &BlockState) -> Option<create_engine::kinetics::Axis> {
        if !dry(state) {
            return None;
        }
        match state.name.as_str() {
            PIPE => axis(state),
            PUMP => front(state).map(Direction::axis),
            VALVE => valve_axis(state, false),
            _ => None,
        }
    }

    /// The two faces a pipe or valve passes fluid through: a pipe with
    /// exactly two open faces (straight or a bend), or a valve along its axis.
    /// Tees and crosses are branches, which this port does not route yet.
    fn passage(state: &BlockState) -> Option<[Direction; 2]> {
        if !dry(state) {
            return None;
        }
        match state.name.as_str() {
            PIPE => {
                let connected: Vec<Direction> =
                    Direction::ALL.into_iter().filter(|&side| open(state, side)).collect();
                match connected.as_slice() {
                    [a, b] => Some([*a, *b]),
                    _ => None,
                }
            }
            VALVE => {
                let axis = valve_axis(state, false)?;
                let side = Direction::ALL.into_iter().find(|side| side.axis() == axis)?;
                Some([side, side.opposite()])
            }
            _ => None,
        }
    }

    fn pump_at(game: &Game<'_>, pos: Pos, origin: &BlockState) -> Option<Pos> {
        if origin.name == PUMP {
            return Some(pos);
        }
        for start in passage(origin)? {
            let (mut at, mut out) = (pos, start);
            for _ in 0..=2 * flow::MAX_PIPES_PER_SIDE + 1 {
                let next = relative(at, out, 1);
                let Some(state) = state(game, next) else {
                    break;
                };
                if state.name == PUMP {
                    if front_of_pump(state).is_some_and(|front| front.axis() == out.axis()) {
                        return Some(next);
                    }
                    break;
                }
                let Some(faces) = passage(state) else {
                    break;
                };
                let inlet = out.opposite();
                if !faces.contains(&inlet) {
                    break;
                }
                out = if faces[0] == inlet { faces[1] } else { faces[0] };
                at = next;
            }
        }
        None
    }

    fn find_line(game: &Game<'_>, pos: Pos, origin: &BlockState) -> Option<Line> {
        let pump = pump_at(game, pos, origin)?;
        let block = state(game, pump)?;
        let direction = front(block)?;
        if !dry(block) {
            return None;
        }
        // Follow the pipe away from the pump through straight runs and bends
        // until it reaches a tank. `toward_pump` says which way fluid flows.
        let scan = |side: Direction, toward_pump: bool| {
            let mut devices = Vec::new();
            let mut sides = Vec::new();
            let mut valve = None;
            let (mut at, mut out) = (pump, side);
            for _ in 1..=flow::MAX_PIPES_PER_SIDE + 1 {
                let next = relative(at, out, 1);
                let state = state(game, next)?;
                let inlet = out.opposite();
                if state.name == tank::BLOCK && tank::endpoint(game, next) {
                    return Some((next, devices, sides, valve));
                }
                if !matches!(state.name.as_str(), PIPE | VALVE) {
                    return None;
                }
                let faces = passage(state)?;
                if !faces.contains(&inlet) {
                    return None;
                }
                if state.name == VALVE && valve.replace((next, enabled(state))).is_some() {
                    return None;
                }
                let other = if faces[0] == inlet { faces[1] } else { faces[0] };
                devices.push(next);
                sides.push(if toward_pump { (other, inlet) } else { (inlet, other) });
                at = next;
                out = other;
            }
            None
        };
        let (source, mut behind, mut behind_sides, inlet_valve) = scan(direction.opposite(), true)?;
        let (target, ahead, ahead_sides, outlet_valve) = scan(direction, false)?;
        if inlet_valve.is_some() && outlet_valve.is_some() {
            return None;
        }
        behind.reverse();
        behind_sides.reverse();
        behind.push(pump);
        behind_sides.push((direction.opposite(), direction));
        behind.extend(ahead);
        behind_sides.extend(ahead_sides);
        Some(Line {
            pump,
            front: direction,
            source,
            target,
            devices: behind,
            sides: behind_sides,
            valve: inlet_valve.or(outlet_valve),
        })
    }

    fn line(game: &Game<'_>, pos: Pos, origin: &BlockState) -> Option<Rc<Line>> {
        NETWORKS.with(|cache| {
            let mut cache = cache.borrow_mut();
            let index = cache.dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id());
            let now = game.world.game_time;
            if index.tick != Some(now) {
                index.by_device.clear();
                index.tick = Some(now);
                if now % 20 == 0 {
                    index.live.retain(|p, _| {
                        state(game, *p)
                            .is_some_and(|s| matches!(s.name.as_str(), PIPE | PUMP | VALVE))
                    });
                }
            }
            if let Some(line) = index.by_device.get(&pos) {
                return line.clone();
            }
            let found = find_line(game, pos, origin).map(Rc::new);
            if let Some(line) = &found {
                for &device in &line.devices {
                    index.by_device.insert(device, Some(line.clone()));
                }
            } else {
                index.by_device.insert(pos, None);
            }
            found
        })
    }

    fn stored(entity: &ModBlockEntity, side: Direction) -> Option<Option<(flow::Flow, bool)>> {
        let Some(tag) = entity.nbt.get(&side.name().into()) else {
            return Some(None);
        };
        let Tag::Compound(connection) = tag else {
            return None;
        };
        if connection
            .keys()
            .any(|key| !matches!(key.to_string_lossy().as_str(), "Pressure" | "Flow"))
        {
            return None;
        }
        if let Some(pressure) = connection.get(&"Pressure".into()) {
            let Tag::List(values) = pressure else {
                return None;
            };
            let [Tag::Float(inward), Tag::Float(outward)] = values.as_slice() else {
                return None;
            };
            let inward = f32::from_bits(*inward);
            let outward = f32::from_bits(*outward);
            if !inward.is_finite()
                || !outward.is_finite()
                || inward < 0.0
                || outward < 0.0
                || inward > 0.0 && outward > 0.0
            {
                return None;
            }
        }
        let Some(tag) = connection.get(&"Flow".into()) else {
            return Some(None);
        };
        let Tag::Compound(data) = tag else {
            return None;
        };
        if data
            .keys()
            .any(|key| !matches!(key.to_string_lossy().as_str(), "Fluid" | "In" | "Progress"))
        {
            return None;
        }
        let Tag::Compound(fluid) = data.get(&"Fluid".into())? else {
            return None;
        };
        if fluid.len() != 2 || !matches!(fluid.get(&"amount".into()), Some(Tag::Int(1))) {
            return None;
        }
        let Tag::String(id) = fluid.get(&"id".into())? else {
            return None;
        };
        let Tag::Byte(inbound @ (0 | 1)) = data.get(&"In".into())? else {
            return None;
        };
        let progress = match data.get(&"Progress".into()) {
            None => 1.0,
            Some(Tag::Compound(fields))
                if fields.keys().all(|key| {
                    matches!(
                        key.to_string_lossy().as_str(),
                        "Value" | "Target" | "Speed" | "Force"
                    )
                }) =>
            {
                if !matches!(fields.get(&"Target".into()), Some(Tag::Float(0)))
                    || !matches!(fields.get(&"Speed".into()), Some(Tag::Float(0)))
                {
                    return None;
                }
                if fields
                    .get(&"Force".into())
                    .is_some_and(|tag| !matches!(tag, Tag::Byte(1)))
                {
                    return None;
                }
                let Tag::Float(value) = fields.get(&"Value".into())? else {
                    return None;
                };
                let value = f32::from_bits(*value);
                if !(0.0..1.0).contains(&value) {
                    return None;
                }
                value
            }
            _ => return None,
        };
        Some(Some((
            flow::Flow {
                fluid: flow::Fluid::from_id(&id.to_string_lossy())?,
                progress,
            },
            *inbound != 0,
        )))
    }

    fn faces(entity: &ModBlockEntity, (inward, outward): (Direction, Direction)) -> Option<flow::Faces> {
        let inlet = stored(entity, inward)?;
        let outlet = stored(entity, outward)?;
        if inlet.is_none_or(|(_, inward)| inward) && outlet.is_none_or(|(_, inward)| !inward) {
            Some(flow::Faces {
                inlet: inlet.map(|(f, _)| f),
                outlet: outlet.map(|(f, _)| f),
            })
        } else if inlet.is_none_or(|(_, inward)| !inward) && outlet.is_none_or(|(_, inward)| inward)
        {
            Some(
                flow::Faces {
                    inlet: outlet.map(|(f, _)| f),
                    outlet: inlet.map(|(f, _)| f),
                }
                .reversed(),
            )
        } else {
            None
        }
    }

    fn tag_number(n: f32) -> Tag {
        Tag::Float(n.to_bits())
    }

    #[derive(Clone, Copy, Default, PartialEq)]
    struct Pointer {
        value: f32,
        target: f32,
        speed: f32,
    }

    impl Pointer {
        fn read(nbt: &Compound) -> Option<Self> {
            let Some(tag) = nbt.get(&"Pointer".into()) else {
                return Some(Self::default());
            };
            let Tag::Compound(fields) = tag else {
                return None;
            };
            let number = |key: &str| match fields.get(&key.into()) {
                Some(Tag::Float(bits)) => Some(f32::from_bits(*bits)),
                _ => None,
            };
            let value = number("Value")?;
            let target = number("Target")?;
            let speed = number("Speed")?;
            ((0.0..=1.0).contains(&value)
                && matches!(target, 0.0 | 1.0)
                && (0.0..=1.0).contains(&speed))
            .then_some(Self {
                value,
                target,
                speed,
            })
        }

        fn tick(&mut self, rpm: f32) {
            self.target = if rpm > 0.0 { 1.0 } else { 0.0 };
            self.speed = (rpm.abs() / 16.0 / 20.0).clamp(0.0, 1.0);
            if self.value < self.target {
                self.value = (self.value + self.speed).min(self.target);
            } else if self.value > self.target {
                self.value = (self.value - self.speed).max(self.target);
            }
        }

        fn save(self, nbt: &mut Compound) {
            if nbt.get(&"Pointer".into()).is_none() {
                nbt.insert("Pointer".into(), Tag::Compound(Compound::new()));
            }
            if let Some(Tag::Compound(fields)) = nbt.get_mut(&"Pointer".into()) {
                fields.insert("Value".into(), tag_number(self.value));
                fields.insert("Target".into(), tag_number(self.target));
                fields.insert("Speed".into(), tag_number(self.speed));
            }
        }
    }

    pub(in crate::game) fn valve_nbt() -> Compound {
        let mut nbt = Compound::new();
        Pointer::default().save(&mut nbt);
        nbt
    }

    pub(in crate::game) fn tick_valve(
        game: &mut Game<'_>,
        pos: Pos,
        entity: &mut ModBlockEntity,
        rpm: f32,
    ) -> bool {
        let mut changed = tick(game, pos, entity, rpm);
        let Some(mut pointer) = Pointer::read(&entity.nbt) else {
            return changed;
        };
        let previous = pointer;
        pointer.tick(rpm);
        if pointer != previous || entity.nbt.get(&"Pointer".into()).is_none() {
            pointer.save(&mut entity.nbt);
            changed = true;
        }
        let value = match pointer.value {
            0.0 => Some("false"),
            1.0 => Some("true"),
            _ => None,
        };
        if let Some(value) = value {
            changed |= game.native_set_block_property(pos, "enabled", value);
        }
        if trace_enabled() {
            log::info!(
                "Create fluid valve: {}",
                serde_json::json!({
                    "time": game.world.game_time, "pos": pos, "rpm": rpm,
                    "enabled": state(game, pos).is_some_and(enabled),
                    "pointer": [pointer.value, pointer.target, pointer.speed],
                })
            );
        }
        changed
    }

    fn save_face(
        entity: &mut ModBlockEntity,
        side: Direction,
        pressure: f32,
        inbound: bool,
        fluid: Option<flow::Flow>,
        force: bool,
    ) -> bool {
        let mut connection = Compound::new();
        if pressure != 0.0 {
            let values = if inbound {
                [pressure, 0.0]
            } else {
                [0.0, pressure]
            };
            connection.insert("Pressure".into(), Tag::List(values.map(tag_number).into()));
        }
        if let Some(flow) = fluid {
            let mut data = Compound::from([
                (
                    "Fluid".into(),
                    Tag::Compound(Compound::from([
                        ("id".into(), Tag::String(flow.fluid.id().into())),
                        ("amount".into(), Tag::Int(1)),
                    ])),
                ),
                ("In".into(), Tag::Byte(i8::from(inbound))),
            ]);
            if flow.progress != 1.0 {
                let mut progress = Compound::from([
                    ("Value".into(), tag_number(flow.progress)),
                    ("Target".into(), tag_number(0.0)),
                    ("Speed".into(), tag_number(0.0)),
                ]);
                if force {
                    progress.insert("Force".into(), Tag::Byte(1));
                }
                data.insert("Progress".into(), Tag::Compound(progress));
            }
            connection.insert("Flow".into(), Tag::Compound(data));
        }
        let value = Tag::Compound(connection);
        let key = side.name().into();
        if entity.nbt.get(&key) == Some(&value) {
            return false;
        }
        entity.nbt.insert(key, value);
        true
    }

    fn save(
        entity: &mut ModBlockEntity,
        (inward, outward): (Direction, Direction),
        pressure: f32,
        before: flow::Faces,
        after: flow::Faces,
    ) -> bool {
        let incoming = save_face(
            entity,
            inward,
            pressure,
            true,
            after.inlet,
            before.inlet.is_none(),
        );
        let outgoing = save_face(
            entity,
            outward,
            pressure,
            false,
            after.outlet,
            before.outlet.is_none(),
        );
        incoming || outgoing
    }

    fn other_faces(game: &Game<'_>, pos: Pos, front: (Direction, Direction)) -> Option<flow::Faces> {
        let BlockEntity::Mod(entity) = game.world.block_entities.get(&(pos[0], pos[1], pos[2]))?
        else {
            return None;
        };
        matches!(entity.id.as_str(), PIPE | PUMP | VALVE)
            .then(|| faces(entity, front))
            .flatten()
    }

    fn controls(
        game: &Game<'_>,
        pos: Pos,
        owner: ModRevision,
        line: Option<&Line>,
        pressure: f32,
        source_flow: bool,
    ) -> (u8, bool) {
        let valve = line.and_then(|line| line.valve);
        let line = line.map(|line| (line.pump, line.front, line.source, line.target));
        NETWORKS.with(|cache| {
            let mut cache = cache.borrow_mut();
            let state = cache
                .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
                .live
                .entry(pos)
                .or_default();
            if state
                .owner
                .is_none_or(|old| !old.is_same_create_entity(owner))
                || state.line != line
                || state.valve != valve
                || state.pressure != pressure
            {
                *state = TickState {
                    owner: Some(owner),
                    line,
                    valve,
                    pressure,
                    phase: 2,
                    source_ticks: 0,
                };
            }
            if state.phase != 0 {
                let phase = state.phase;
                state.phase -= 1;
                return (phase, false);
            }
            state.source_ticks = if source_flow {
                (state.source_ticks + 1).min(3)
            } else {
                0
            };
            (0, state.source_ticks == 3)
        })
    }

    pub(in crate::game) fn tick(
        game: &mut Game<'_>,
        pos: Pos,
        entity: &mut ModBlockEntity,
        rpm: f32,
    ) -> bool {
        if !matches!(entity.id.as_str(), PIPE | PUMP | VALVE) {
            return false;
        }
        let Some(origin) = state(game, pos) else {
            return false;
        };
        if origin.name != PIPE && device_axis(origin).is_none() {
            return false;
        }
        let Some(line) = line(game, pos, origin) else {
            // An open, unsupported or unloaded path must not discard saved
            // connections. It has no authority to drain either endpoint.
            controls(game, pos, entity.revision(), None, 0.0, false);
            return false;
        };
        let Some(index) = line.devices.iter().position(|&device| device == pos) else {
            controls(game, pos, entity.revision(), None, 0.0, false);
            return false;
        };
        let front = line.sides[index];
        let Some(before) = faces(entity, front) else {
            return false;
        };
        let pressure = if pos == line.pump {
            rpm.abs()
        } else {
            let p = line.pump;
            match game.world.block_entities.get(&(p[0], p[1], p[2])) {
                Some(BlockEntity::Mod(entity)) if entity.id == PUMP => {
                    crate::game::create_port::running_speed(game, &entity.nbt).abs()
                }
                _ => 0.0,
            }
        };
        let is_source = index == 0;
        let valve_closed_here = line.valve == Some((pos, false));
        let input = if pressure == 0.0 || valve_closed_here {
            None
        } else if is_source {
            tank::sample(game, line.source)
        } else {
            other_faces(game, line.devices[index - 1], line.sides[index - 1])
                .and_then(|faces| faces.outlet?.complete())
        };
        let source_flow = is_source
            && input.is_some_and(|fluid| before.inlet.is_some_and(|inlet| inlet.fluid == fluid));
        let (phase, ready) = controls(
            game,
            pos,
            entity.revision(),
            Some(&line),
            pressure,
            source_flow,
        );
        if phase == 2 {
            return false;
        }
        if phase == 1 {
            return save(entity, front, pressure, before, before);
        }
        if ready
            && let Some(fluid) = input
            && line.valve.is_none_or(|(at, open)| {
                open && state(game, at).is_some_and(|s| s.name == VALVE && dry(s))
            })
            && before.complete(fluid)
            && line.devices.iter().zip(&line.sides).skip(1).all(|(&device, &sides)| {
                state(game, device).is_some_and(|s| {
                    if device == line.pump {
                        front_of_pump(s) == Some(line.front)
                    } else {
                        matches!(s.name.as_str(), PIPE | VALVE)
                            && passage(s).is_some_and(|faces| {
                                faces.contains(&sides.0) && faces.contains(&sides.1)
                            })
                    }
                }) && other_faces(game, device, sides).is_some_and(|pair| pair.complete(fluid))
            })
        {
            tank::transfer_pair(
                game,
                line.source,
                line.target,
                fluid,
                flow::transfer_rate(pressure),
            );
        }
        let mut after = before;
        if pressure > 0.0 {
            after.tick(input, pressure);
        } else {
            after = flow::Faces::default();
        }
        trace(game, pos, &line, pressure, after, is_source);
        before != after && save(entity, front, pressure, before, after)
    }

    fn trace(
        game: &Game<'_>,
        pos: Pos,
        line: &Line,
        pressure: f32,
        faces: flow::Faces,
        source: bool,
    ) {
        if !trace_enabled() {
            return;
        }
        let flow = |face: Option<flow::Flow>| face.map(|f| (f.fluid.id(), f.progress));
        log::info!(
            "Create fluid pump: {}",
            serde_json::json!({
                "time": game.world.game_time, "pos": pos, "pressure": pressure, "front": line.front.name(),
                "inlet": flow(faces.inlet), "outlet": flow(faces.outlet),
                "storage": source.then(|| [tank::amount(game, line.source), tank::amount(game, line.target)]),
            })
        );
    }

    fn trace_enabled() -> bool {
        static TRACE: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
        *TRACE.get_or_init(|| std::env::var_os("CREATE_TRACE_FLUID_PUMP").is_some())
    }

    fn trace_attachment(pos: Pos, model: &'static str) {
        if !trace_enabled() {
            return;
        }
        thread_local! {
            static DRAWN: RefCell<std::collections::BTreeSet<(Pos, &'static str)>> = const { RefCell::new(std::collections::BTreeSet::new()) };
        }
        if DRAWN.with(|drawn| drawn.borrow_mut().insert((pos, model))) {
            log::info!(
                "Create fluid attachment: {}",
                serde_json::json!({"pos": pos, "model": model})
            );
        }
    }

    fn front_of_pump(state: &BlockState) -> Option<Direction> {
        (state.name == PUMP && dry(state))
            .then(|| front(state))
            .flatten()
    }

    pub(in crate::game) fn reacts(game: &Game<'_>, pos: Pos) -> bool {
        game.native_on("create")
            && game.native_block(pos) == PUMP
            && game.may_build()
            && !game.native_sneaking()
            && game
                .held()
                .is_some_and(|held| crate::game::create_port_chassis::wrench(game, held))
    }

    pub(in crate::game) fn right_click(game: &mut Game<'_>, pos: Pos) -> bool {
        if !reacts(game, pos) {
            return false;
        }
        if let Some(front) = state(game, pos).and_then(front_of_pump)
            && game.native_set_block_property(pos, "facing", front.opposite().name())
        {
            crate::game::create_port_sounds::cog_wrench(game, pos);
        }
        true
    }

    pub(in crate::game) fn placement(
        game: &GameLevel<'_>,
        mut state: BlockStateId,
        ctx: &PlacementContext,
        block: &str,
    ) -> Option<BlockStateId> {
        let pos = [ctx.pos.x, ctx.pos.y, ctx.pos.z];
        let target = game.native_state_block(game.world.block(pos[0], pos[1], pos[2]))?;
        if matches!(target, "minecraft:water" | "minecraft:lava") {
            return None;
        }
        let look = crate::game::create_port::nearest(ctx.yaw, ctx.pitch);
        if block == VALVE {
            use create_engine::kinetics::Axis;
            let facing = if ctx.sneaking { look } else { look.opposite() };
            let ports = crate::game::create_port_placement::level_ports(game, pos);
            let has_shaft = |side: Direction| ports[side as usize];
            let has_pipe = |side: Direction| {
                let at = relative(pos, side, 1);
                game.registry
                    .state(game.world.block(at[0], at[1], at[2]))
                    .is_some_and(|s| s.name == tank::BLOCK || device_axis(s) == Some(side.axis()))
            };
            let first = match facing.axis() {
                axis @ (Axis::X | Axis::Z) => {
                    let perpendicular = if axis == Axis::X {
                        Direction::South
                    } else {
                        Direction::East
                    };
                    let vertical_shaft = has_shaft(Direction::Up) || has_shaft(Direction::Down);
                    let horizontal_pipe =
                        has_pipe(perpendicular) || has_pipe(perpendicular.opposite());
                    (axis == Axis::X) == (vertical_shaft || horizontal_pipe)
                }
                Axis::Y => {
                    let prefer = |s: Direction| has_shaft(s) || has_pipe(s.clockwise(Axis::Y));
                    let x = prefer(Direction::East) || prefer(Direction::West);
                    let z = prefer(Direction::North) || prefer(Direction::South);
                    if x != z {
                        x
                    } else {
                        crate::game::create_port_placement::horizontal(ctx.yaw).axis() == Axis::X
                    }
                }
            };
            let state = game.native_state_with_property(state, "facing", facing.name())?;
            return game.native_state_with_property(
                state,
                "axis_along_first",
                if first { "true" } else { "false" },
            );
        }
        let joined: Vec<_> = Direction::ALL
            .into_iter()
            .filter(|&side| {
                let at = relative(pos, side, 1);
                let Some(adjacent) = game.registry.state(game.world.block(at[0], at[1], at[2]))
                else {
                    return false;
                };
                adjacent.name == tank::BLOCK || device_axis(adjacent) == Some(side.axis())
            })
            .collect();
        if block == PUMP {
            let want = if ctx.sneaking { look } else { look.opposite() };
            let closest = joined.iter().rev().min_by_key(|&&side| {
                if side == want {
                    0
                } else if side == want.opposite() {
                    2
                } else {
                    1
                }
            });
            let base = if ctx.sneaking {
                want
            } else {
                create_engine::placement::preferred(
                    crate::game::create_port_placement::level_ports(game, pos),
                )
                .map_or(want, Direction::opposite)
            };
            let front = closest
                .filter(|&&side| side.axis() != want.axis() && !ctx.sneaking)
                .copied()
                .unwrap_or(base);
            return game.native_state_with_property(state, "facing", front.name());
        }
        let empty: Vec<(Direction, bool)> = Direction::ALL.into_iter().map(|side| (side, false)).collect();
        let faces = update_faces(game, pos, &empty, look, None, None);
        state = with_faces(game, state, &faces)?;
        Some(state)
    }

    pub(in crate::game) fn draw(
        game: &Game<'_>,
        pos: Pos,
        entity: &ModBlockEntity,
        draw: &mut BlockEntityDraw,
    ) {
        let Some(block) = state(game, pos) else {
            return;
        };
        let axis = device_axis(block);
        if block.name == PUMP
            && let Some(axis) = axis
        {
            let angle = create_engine::visual::angle(
                draw.game_time as f64 + f64::from(draw.partial),
                crate::game::create_port::number(&entity.nbt, "Speed"),
                create_engine::visual::rotation_offset(pos, axis, false),
            );
            draw.push();
            draw.rotate_about(create_engine::visual::positive_axis(axis), angle, [0.5; 3]);
            crate::game::create_port::face_south(
                draw,
                [Direction::East, Direction::Up, Direction::South][axis.index()],
            );
            game.native_draw_model(draw, "create:block/mechanical_pump/cog", 0xFFFFFF);
            draw.pop();
        }
        if block.name == VALVE
            && let Some(axis) = axis
        {
            let (Some(facing), Some(shaft)) = (front(block), valve_axis(block, true)) else {
                return;
            };
            let angle = create_engine::visual::angle(
                draw.game_time as f64 + f64::from(draw.partial),
                crate::game::create_port::number(&entity.nbt, "Speed"),
                create_engine::visual::rotation_offset(pos, shaft, false),
            );
            draw.push();
            crate::game::create_port::orient(draw, shaft);
            draw.rotate_about([0.0, 1.0, 0.0], angle, [0.5; 3]);
            game.native_draw_model(draw, "create:block/shaft", 0xFFFFFF);
            draw.pop();
            let angle = Pointer::read(&entity.nbt).unwrap_or_default().value * -90.0;
            let offset = if axis.index() == 1 || shaft.index() == 0 {
                90.0
            } else {
                0.0
            };
            let yaw = match facing {
                Direction::North => 180.0,
                Direction::East => 270.0,
                Direction::West => 90.0,
                _ => 0.0,
            };
            let pitch = match facing {
                Direction::Up => 0.0,
                Direction::Down => 180.0,
                _ => 90.0,
            };
            draw.push();
            draw.rotate_about([0.0, 1.0, 0.0], yaw, [0.5; 3]);
            draw.rotate_about([1.0, 0.0, 0.0], pitch, [0.5; 3]);
            draw.rotate_about([0.0, 1.0, 0.0], offset + angle, [0.5; 3]);
            if game.native_draw_model(draw, "create:block/fluid_valve/pointer", 0xFFFFFF) {
                trace_attachment(pos, "create:block/fluid_valve/pointer");
            }
            draw.pop();
        }
        if !crate::game::create_port::original_assets() {
            return;
        }
        // PipeAttachmentModel quads supply the tube beyond its core, on every
        // open face of a pipe (corners and tees too) and along a pump or valve.
        use create_assets::PipeAttachment::{Connection, Drain, Rim, RimConnector};
        let sides: Vec<Direction> = if block.name == PIPE {
            Direction::ALL.into_iter().filter(|&side| open(block, side)).collect()
        } else if let Some(axis) = axis {
            Direction::ALL.into_iter().filter(|side| side.axis() == axis).collect()
        } else {
            return;
        };
        for side in sides {
            let neighbor = state(game, relative(pos, side, 1));
            let models: &[create_assets::PipeAttachment] = if block.name == VALVE {
                if neighbor.is_some_and(|state| state.name == tank::BLOCK) {
                    &[Drain]
                } else {
                    &[]
                }
            } else if neighbor.is_some_and(|state| state.name == tank::BLOCK) {
                &[RimConnector, Drain]
            } else if block.name == PUMP {
                &[]
            } else if let Some(state) = neighbor.filter(|state| {
                if state.name == PIPE {
                    open(state, side.opposite())
                } else {
                    joins(state, side) && device_axis(state) == Some(side.axis())
                }
            }) {
                if state.name == PUMP {
                    &[RimConnector]
                } else {
                    &[Connection]
                }
            } else {
                &[RimConnector, Rim]
            };
            for part in models {
                let model = part.model(side as usize);
                if game.native_draw_model(draw, model, 0xFFFFFF) {
                    trace_attachment(pos, model);
                }
            }
        }
    }
}

pub(super) fn client_tick(game: &mut Game<'_>) {
    if !game.native_window() || game.remote.is_none() || !game.native_on("create") {
        return;
    }
    let time = game.world.game_time;
    let session = std::ptr::from_ref(&game.world) as usize;
    let dimension = game.dim.id().to_owned();
    let entries: Vec<_> = game
        .world
        .block_entities
        .iter()
        .filter_map(|(&(x, y, z), e)| match e {
            BlockEntity::Mod(e) if matches!(e.id.as_str(), ID | tank::BLOCK) => {
                Some(([x, y, z], e.as_ref()))
            }
            _ => None,
        })
        .collect();
    tank::client_tick(session, &dimension, time, &entries);
    let entries = entries.into_iter().filter_map(|(pos, e)| (e.id == ID).then(|| (pos, e.revision())));
    let entries: Vec<_> = entries.collect();
    let live: std::collections::BTreeSet<_> = entries.iter().map(|(pos, _)| *pos).collect();
    MOTION.with(|cache| {
        let mut cache = cache.borrow_mut();
        let cache = cache.dimension(session, &dimension);
        cache.retain(|p, _| live.contains(p));
        for (pos, owner) in entries {
            let m = cache.entry(pos).or_default();
            if m.tick.is_some_and(|t| t > time)
                || m.owner.is_some_and(|old| !old.is_same_create_entity(owner))
            {
                *m = Motion::default();
            }
            m.owner = Some(owner);
            if m.tick == Some(time) { continue; }
            // read(clientPacket) updates the chase target; the lazy tick is a
            // fallback for absent/removed mixers, as in BasinBlockEntity.
            let mixer = game.world.block_entities.get(&(pos[0],pos[1]+2,pos[2]));
            let moving = matches!(mixer, Some(BlockEntity::Mod(e)) if e.id == "create:mechanical_mixer" && crate::game::create_port::integer(&e.nbt,"Running") != 0 && crate::game::create_port::integer(&e.nbt,"Ticks") <= 20);
            if m.tick.is_none() || m.lazy <= 0 || m.moving != moving {
                m.moving = moving;
                m.lazy = 10;
            } else { m.lazy -= 1; }
            m.previous = m.angle;
            m.speed += ((if m.moving {20.0} else {0.0}) - m.speed) * 0.1;
            m.angle += m.speed;
            if let Some(BlockEntity::Mod(entity))=game.world.block_entities.get(&(pos[0],pos[1],pos[2])) {
                for (half,key) in ["InputTanks","OutputTanks"].into_iter().enumerate() {
                    let Ok(levels)=fluids::read_levels(entity.nbt.get(&key.into())) else {continue;};
                    let Ok(contents)=read_tanks(entity,key) else {continue;};
                    for (i,level) in levels.into_iter().enumerate() {
                        let index=half*2+i;
                        if let Some(fluid)=contents[i].as_ref(){m.rendered_fluids[index]=Some(fluid.clone());}
                        let chase=&mut m.fluid_levels[index];
                        if m.received_fluids[index]!=Some(level) {
                            if level.force {chase.value=level.value;chase.previous=level.value;}
                            chase.target=level.target;chase.speed=level.speed;
                            m.received_fluids[index]=Some(level);
                        }
                        chase.tick();
                    }
                }
            }
            m.tick = Some(time);
        }
    });
}
fn draw_fluids(
    game: &Game<'_>,
    pos: Pos,
    entity: &ModBlockEntity,
    draw: &mut BlockEntityDraw,
) -> f32 {
    let rendered = MOTION.with(|cache| {
        let mut cache = cache.borrow_mut();
        let motion = cache
            .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
            .get(&pos);
        std::array::from_fn::<_, 4, _>(|i| {
            if let Some(m) = motion {
                return (
                    m.rendered_fluids[i].clone(),
                    m.fluid_levels[i].at(draw.partial) * rules::TANK_CAPACITY as f32,
                );
            }
            let key = if i < 2 { "InputTanks" } else { "OutputTanks" };
            let fluid = read_tanks(entity, key).ok().and_then(|t| t[i % 2].clone());
            let units = fluids::read_levels(entity.nbt.get(&key.into()))
                .map_or(0.0, |l| l[i % 2].value * rules::TANK_CAPACITY as f32);
            (fluid, units)
        })
    });
    let total: f32 = rendered.iter().map(|(_, units)| units).sum();
    if total < 1.0 {
        return 0.0;
    }
    let ratio = (total / 2000.0).clamp(0.0, 1.0);
    let height = 2.0 / 16.0 + 12.0 / 16.0 * (1.0 - (1.0 - ratio) * (1.0 - ratio));
    let mut x = 2.0 / 16.0;
    for (fluid, units) in rendered {
        let Some(fluid) = fluid else {
            continue;
        };
        if units < 1.0 {
            continue;
        }
        let next = x + (units / total).clamp(0.0, 1.0) * 12.0 / 16.0;
        game.native_draw_fluid_box(
            draw,
            &native_fluid(&fluid),
            [x, 2.0 / 16.0, 2.0 / 16.0, next, height, 14.0 / 16.0],
            NativeFluidRenderOptions {
                argb: None,
                render_bottom: false,
                // Actual source fixture's stitched blocks atlas is 2048x1024.
                // This is explicit because Horizon stores block sprites in arrays.
                uv_shrink_ratio: 4.0 / 2048.0,
            },
        );
        x = next;
    }
    height
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
    super::create_port_basin_filter::draw(game, pos, entity, draw);
    // Retained motion belongs to this live BE, including ordinary NBT changes.
    MOTION.with(|cache| {
        let mut cache = cache.borrow_mut();
        let motions = cache.dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id());
        if motions.get(&pos).is_some_and(|m| {
            m.owner
                .is_some_and(|old| !old.is_same_create_entity(entity.revision()))
        }) {
            motions.remove(&pos);
        }
    });
    // restore() truncates supported inventories to18, while opaque unsupported
    // inventories retain every live slot. Borrow the same visible range.
    let end = if crate::game::create_port::inventory_supported(entity) {
        entity.items.len().min(18)
    } else {
        entity.items.len()
    };
    let items = &entity.items[..end];
    let fluid_height = draw_fluids(game, pos, entity, draw);
    let item_height = (fluid_height - 0.3).clamp(0.125, 0.6);
    let mut count = items.iter().flatten().filter(|s| s.count > 0).count();
    if count == 0 {
        return true;
    }
    let rotation = MOTION.with(|cache| {
        let mut cache = cache.borrow_mut();
        cache
            .dimension(std::ptr::from_ref(&game.world) as usize, game.dim.id())
            .get(&pos)
            .map_or(0.0, |m| m.previous + (m.angle - m.previous) * draw.partial)
    });
    // BlockPos.hashCode and RandomSource.create preserve stable item pile offsets.
    let hash = pos[1]
        .wrapping_add(pos[2].wrapping_mul(31))
        .wrapping_mul(31)
        .wrapping_add(pos[0]);
    let mut random = LegacyRandom::new(i64::from(hash));
    let partition = 360.0 / count as f32;
    let radius = if count == 1 { 0.0 } else { 0.125 };
    draw.push();
    draw.translate([0.5, 0.2, 0.5]);
    draw.rotate_about([0.0, 1.0, 0.0], rotation, [0.0; 3]);
    for item in items.iter().flatten().filter(|s| s.count > 0) {
        let angle = partition * count as f32;
        let at =
            crate::game::create_port_mixer::rotate_y([radius, f64::from(item_height), 0.0], angle);
        draw.push();
        if fluid_height > 0.0 {
            let phase = (draw.game_time as f32 + draw.partial) / 12.0 + angle;
            let bob = (crate::game::create_port_mixer::sin(phase) + 1.5) / 32.0;
            draw.translate([0.0, bob, 0.0]);
        }
        draw.translate(at.map(|v| v as f32));
        draw.rotate_about([0.0, 1.0, 0.0], angle + 35.0, [0.0; 3]);
        draw.rotate_about([1.0, 0.0, 0.0], 65.0, [0.0; 3]);
        for _ in 0..=item.count / 8 {
            draw.push();
            draw.translate(std::array::from_fn(|_| {
                (random.next_float() - 0.5) * 2.0 / 16.0
            }));
            game.native_draw_item(
                draw,
                item,
                horizon_assets::item_model::DisplayContext::Ground,
                None,
                0,
            );
            draw.pop();
        }
        draw.pop();
        count -= 1;
    }
    draw.pop();
    true
}
