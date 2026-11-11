// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use super::{Game, GameLevel, create_port_contraption as contraption};
use crate::containers::{BlockEntity, ModBlockEntity, ModBlockEntityFields};
use crate::items::ItemStack;
use create_engine::{
    contraption::{
        CaptureError, Cell, QuarterTurn,
        chassis::{Chassis, DEFAULT_RANGE, Kind, MAX_RANGE},
    },
    kinetics::{Axis, Pos},
    placement::Direction,
};
use horizon_client_render::create_contraption_scene::{MAX_BLOCKS, MAX_RECORDS, Record};
use horizon_world::{
    attachments::{AttachmentCodec, AttachmentError, AttachmentType, Holder},
    chunk::BlockState,
    level::{PlacementContext, flags},
    nbt::{Compound, Tag},
    registry::BlockStateId,
};
use std::collections::{BTreeMap, BTreeSet, VecDeque};

const ENTITY: &str = "create:chassis";
const RANGE: &str = "ScrollValue";
pub(super) type Ranges = BTreeMap<Pos, u8>;
type Mounted = BTreeMap<Pos, Ranges>;
type Edit = (Pos, BlockStateId, BlockStateId);

const MOUNTED: AttachmentType<Mounted> = AttachmentType {
    namespace: "create",
    name: "mounted_chassis",
    default: Mounted::new,
    codec: Some(AttachmentCodec { encode, decode }),
    copy_on_death: false,
    sync: false,
};

fn kind(block: &str) -> Option<Kind> {
    match block {
        "create:linear_chassis" => Some(Kind::Linear),
        "create:secondary_linear_chassis" => Some(Kind::Secondary),
        "create:radial_chassis" => Some(Kind::Radial),
        _ => None,
    }
}

pub(super) fn is_chassis(block: &str) -> bool {
    kind(block).is_some()
}

pub(super) fn factory(block: &str) -> Option<(String, Compound)> {
    is_chassis(block).then(|| (ENTITY.into(), range_nbt(DEFAULT_RANGE)))
}

fn range_nbt(range: u8) -> Compound {
    Compound::from([(RANGE.into(), Tag::Int(i32::from(range)))])
}

fn range(nbt: &Compound) -> Option<u8> {
    match nbt.get(&RANGE.into()) {
        None => Some(DEFAULT_RANGE),
        Some(Tag::Int(value)) if (1..=i32::from(MAX_RANGE)).contains(value) => Some(*value as u8),
        _ => None,
    }
}

pub(super) fn update_tag(entity: &ModBlockEntity, tag: &mut Option<Compound>) {
    if entity.id == ENTITY && tag.is_none() {
        *tag = range(&entity.nbt).map(range_nbt);
    }
}

pub(super) fn configured_range(game: &Game<'_>, pos: Pos) -> Option<u8> {
    if !contraption::resident(game, pos) || !is_chassis(&at(game, pos)?.name) {
        return None;
    }
    let BlockEntity::Mod(entity) = game.world.block_entities.get(&(pos[0], pos[1], pos[2]))? else {
        return None;
    };
    (entity.id == ENTITY).then(|| range(&entity.nbt)).flatten()
}

pub(super) fn wrench(game: &Game<'_>, item: &ItemStack) -> bool {
    item.item.as_ref() == "create:wrench"
        || game
            .native_server_item_in_tag(item, "c:tools/wrench")
            .unwrap_or(false)
}

pub(super) fn value_box_hit(pos: Pos, face: Pos, point: [f64; 3]) -> bool {
    (0..3)
        .map(|i| {
            let offset = 0.5 + f64::from(face[i]) * 7.5 / 16.0;
            (point[i] - f64::from(pos[i]) - offset).powi(2)
        })
        .sum::<f64>()
        < 0.25 * 0.25
}

// ChassisBlockEntity.collectChassisGroup. Stay within loaded columns and
// bound the whole operation before publishing any range changes.
fn settings_group(game: &Game<'_>, start: Pos) -> Option<Vec<Pos>> {
    const MAX_EDIT_GROUP: usize = 512;
    let mut collected = Vec::new();
    let mut visited = BTreeSet::from([start]);
    let mut frontier = VecDeque::from([start]);
    while let Some(pos) = frontier.pop_front() {
        let state = chassis(at(game, pos)?, configured_range(game, pos)?)?;
        collected.push(pos);
        for face in Direction::ALL {
            let Some(next) = offset(pos, face.vector()) else {
                continue;
            };
            if visited.contains(&next) || !contraption::resident(game, next) {
                continue;
            }
            if at(game, next)
                .and_then(|block| chassis(block, DEFAULT_RANGE))
                .is_some_and(|other| state.joins(other, face))
            {
                if visited.len() >= MAX_EDIT_GROUP {
                    return None;
                }
                visited.insert(next);
                frontier.push_back(next);
            }
        }
    }
    Some(collected)
}

// The inherited source setter compares against the chassis' zero-based
// setting after the override already added one. Preserve that comparison
// for feedback, and for the single-block early return.
pub(super) fn apply_range(game: &mut Game<'_>, pos: Pos, value: u8, bulk: bool) -> bool {
    let Some(previous) = configured_range(game, pos) else {
        return false;
    };
    let feedback = value != previous - 1;
    if !bulk && !feedback {
        return false;
    }
    let group = if bulk {
        let Some(group) = settings_group(game, pos) else {
            return false;
        };
        group
    } else {
        vec![pos]
    };
    for member in group {
        if configured_range(game, member) == Some(value) {
            continue;
        }
        game.native_with_mod_block_entity(member, |entity| {
            entity.nbt.insert(RANGE.into(), Tag::Int(i32::from(value)));
        });
        game.native_block_entity_sync(member);
    }
    feedback
}

fn axis(value: &str) -> Option<Axis> {
    match value {
        "x" => Some(Axis::X),
        "y" => Some(Axis::Y),
        "z" => Some(Axis::Z),
        _ => None,
    }
}

fn chassis(block: &BlockState, range: u8) -> Option<Chassis> {
    let kind = kind(&block.name)?;
    if block.properties.len() != if kind == Kind::Radial { 5 } else { 3 } {
        return None;
    }
    let axis = axis(block.properties.get("axis")?)?;
    let mut chassis = Chassis::new(kind, axis, range)?;
    for face in Direction::ALL {
        if let Some(property) = chassis.sticky_property(face) {
            chassis = chassis.with_sticky(
                face,
                match block.properties.get(property)?.as_str() {
                    "true" => true,
                    "false" => false,
                    _ => return None,
                },
            )?;
        }
    }
    Some(chassis)
}

fn encode_state(block: &BlockState, chassis: Chassis) -> BlockState {
    let mut block = block.clone();
    block
        .properties
        .insert("axis".into(), ["x", "y", "z"][chassis.axis.index()].into());
    for face in Direction::ALL {
        if let Some(property) = chassis.sticky_property(face) {
            block
                .properties
                .insert(property.into(), chassis.sticky(face).to_string());
        }
    }
    block
}

pub(super) fn rotate_state(block: &BlockState, turn: QuarterTurn) -> Option<BlockState> {
    Some(encode_state(
        block,
        chassis(block, DEFAULT_RANGE)?.rotated(turn),
    ))
}

fn at<'g>(game: &'g Game<'_>, pos: Pos) -> Option<&'g BlockState> {
    game.pack
        .assets
        .registry
        .state(contraption::state(game, pos))
}

fn offset(pos: Pos, delta: Pos) -> Option<Pos> {
    Some([
        pos[0].checked_add(delta[0])?,
        pos[1].checked_add(delta[1])?,
        pos[2].checked_add(delta[2])?,
    ])
}

pub(super) fn placement(
    game: &GameLevel<'_>,
    block: &str,
    state: BlockStateId,
    ctx: &PlacementContext,
    face: Direction,
) -> Option<BlockStateId> {
    let kind = kind(block)?;
    let mut chosen = face.axis();
    if kind != Kind::Radial && !ctx.sneaking {
        let p = [ctx.pos.x, ctx.pos.y, ctx.pos.z];
        let neighbor = offset(p, face.opposite().vector())?;
        chosen = game
            .registry
            .state(game.world.block(neighbor[0], neighbor[1], neighbor[2]))
            .filter(|state| {
                matches!(
                    self::kind(&state.name),
                    Some(Kind::Linear | Kind::Secondary)
                )
            })
            .and_then(|state| axis(state.properties.get("axis")?))
            .unwrap_or_else(|| super::create_port::nearest(ctx.yaw, ctx.pitch).axis());
    }
    game.native_state_with_property(state, "axis", ["x", "y", "z"][chosen.index()])
}

fn can_glue(game: &Game<'_>, pos: Pos, state: Chassis, face: Direction) -> bool {
    if state.kind == Kind::Radial {
        return true;
    }
    offset(pos, face.vector())
        .and_then(|p| at(game, p))
        .and_then(|block| chassis(block, DEFAULT_RANGE))
        .is_none_or(|other| !state.joins(other, face))
}

fn interaction(game: &Game<'_>, pos: Pos, face: Pos, held: Option<&ItemStack>) -> Option<Chassis> {
    if !game.native_on("create") || !game.may_build() {
        return None;
    }
    let clicked = Direction::from_vector(face)?;
    let mut state = chassis(at(game, pos)?, DEFAULT_RANGE)?;
    state.sticky_property(clicked)?;
    let slime = held.is_some_and(|item| {
        matches!(
            item.item.as_ref(),
            "minecraft:slime_ball" | "create:super_glue"
        ) || game
            .native_server_item_in_tag(item, "c:slime_balls")
            .unwrap_or(false)
    });
    if slime && state.sticky(clicked) {
        for face in Direction::ALL {
            if !state.sticky(face)
                && can_glue(game, pos, state, face)
                && let Some(updated) = state.with_sticky(face, true)
            {
                state = updated;
            }
        }
        return Some(state);
    }
    let clear = held.is_none() && game.keys.contains(&winit::keyboard::KeyCode::ShiftLeft);
    if (!slime && !clear) || state.sticky(clicked) == slime || !can_glue(game, pos, state, clicked)
    {
        return None;
    }
    state.with_sticky(clicked, slime)
}

pub(super) fn predicts(game: &Game<'_>, pos: Pos, face: Pos, held: Option<&ItemStack>) -> bool {
    interaction(game, pos, face, held).is_some()
}

pub(super) fn right_click(game: &mut Game<'_>, pos: Pos, face: Pos) -> bool {
    let Some(updated) = interaction(game, pos, face, game.held()) else {
        return false;
    };
    let Some(before) = at(game, pos) else {
        return false;
    };
    let changed = encode_state(before, updated);
    if &changed == before {
        return true;
    }
    let changed_faces = changed
        .properties
        .iter()
        .filter(|(key, value)| before.properties.get(*key) != Some(*value))
        .count();
    let Some(state) = game.pack.assets.registry.id(&changed) else {
        return false;
    };
    let dimension = game.dim.id().to_owned();
    if !game.native_set_block(
        &dimension,
        pos,
        state,
        flags::UPDATE_NEIGHBORS | flags::UPDATE_CLIENTS,
    ) {
        return false;
    }
    game.with_level(|_, level, _| {
        for _ in 0..changed_faces {
            level.native_play_sound(
                "minecraft:block.slime_block.place",
                pos.map(|coordinate| f64::from(coordinate) + 0.5),
                4,
                0.5,
                1.0,
            );
        }
    });
    true
}

pub(super) fn placed(game: &mut Game<'_>, pos: Pos) {
    let Some(current) = at(game, pos).and_then(|block| chassis(block, DEFAULT_RANGE)) else {
        return;
    };
    if current.kind == Kind::Radial {
        return;
    }
    for face in Direction::ALL
        .into_iter()
        .filter(|face| face.axis() == current.axis)
    {
        let Some(neighbor) = offset(pos, face.vector()) else {
            continue;
        };
        let Some(other) = at(game, neighbor).and_then(|block| chassis(block, DEFAULT_RANGE)) else {
            continue;
        };
        if current.joins(other, face)
            && other.sticky(face.opposite())
            && let Some(property) = other.sticky_property(face.opposite())
        {
            game.native_set_block_property(neighbor, property, "false");
        }
    }
}

fn source_ok(source: &Tag) -> bool {
    let Tag::Compound(fields) = source else {
        return false;
    };
    range(fields).is_some()
        && fields
            .iter()
            .all(|(key, value)| match key.to_string().as_deref() {
                Ok(RANGE) => true,
                Ok("id") => *value == Tag::String(ENTITY.into()),
                Ok("x" | "y" | "z") => matches!(value, Tag::Int(_)),
                Ok("keepPacked") => *value == Tag::Byte(0),
                Ok("components") => matches!(value, Tag::Compound(map) if map.is_empty()),
                Ok("Items") => matches!(value, Tag::List(items) if items.is_empty()),
                _ => false,
            })
}

fn captured(game: &Game<'_>, pos: Pos, block: &BlockState) -> Option<Chassis> {
    let key = (pos[0], pos[1], pos[2]);
    let BlockEntity::Mod(entity) = game.world.block_entities.get(&key)? else {
        return None;
    };
    if entity.id != ENTITY
        || entity.items.iter().any(Option::is_some)
        || entity
            .nbt
            .keys()
            .any(|key| !matches!(key.to_string().as_deref(), Ok(RANGE)))
        || game.world.block_names.contains_key(&key)
        || game.world.block_lock(key).is_some()
    {
        return None;
    }
    let [x, z] = contraption::column(pos);
    if game
        .world
        .block_entities
        .chunk_attachments(x, z)
        .iter()
        .any(|(p, _)| *p == key)
    {
        return None;
    }
    if let Some(saved) = game
        .world
        .chunks
        .get(&(x, z))
        .and_then(|chunk| chunk.saved.as_ref())
        && (saved
            .block_entity_attachments
            .iter()
            .any(|(p, _)| *p == key)
            || saved.rolled_loot.iter().any(|loot| loot.pos == key)
            || saved
                .block_entity_sources
                .iter()
                .find(|(p, _)| *p == key)
                .is_some_and(|(_, source)| !source_ok(source)))
    {
        return None;
    }
    chassis(block, range(&entity.nbt)?)
}

pub(super) fn can_capture(game: &Game<'_>, pos: Pos, block: &BlockState) -> bool {
    is_chassis(&block.name) && captured(game, pos, block).is_some()
}

pub(super) fn expansion(
    game: &Game<'_>,
    pos: Pos,
    forced: Option<Direction>,
    mut inspect: impl FnMut(Pos) -> Cell,
) -> Result<Vec<Pos>, CaptureError> {
    let Some(block) = at(game, pos).filter(|block| is_chassis(&block.name)) else {
        return Ok(Vec::new());
    };
    let state = captured(game, pos, block).ok_or(CaptureError::Unsupported(pos))?;
    let mut neighbors = Vec::new();
    for face in Direction::ALL {
        if state.kind == Kind::Radial && face.axis() != state.axis {
            continue;
        }
        let next = offset(pos, face.vector()).ok_or(CaptureError::CoordinateOverflow)?;
        if !game.world.loaded(next[0], next[2]) {
            return Err(CaptureError::Unloaded(next));
        }
        if at(game, next)
            .and_then(|block| chassis(block, DEFAULT_RANGE))
            .is_some_and(|other| state.joins(other, face))
        {
            neighbors.push(next);
        }
    }
    neighbors.extend(state.included(pos, forced, |target| {
        let cell = inspect(target);
        let Cell::Block(mut rules) = cell else {
            return cell;
        };
        let id = contraption::state(game, target);
        if !game.collision.may_collide(id) {
            return Cell::Empty;
        }
        let block = game.pack.assets.registry.state(id);
        if let Some(block) = block
            && matches!(
                block.name.as_str(),
                "create:mechanical_drill" | contraption::BLOCK
            )
            && let Some(facing) = contraption::facing(game, target)
        {
            rules.unsupported_faces[facing as usize] = true;
        }
        Cell::Block(rules)
    })?);
    Ok(neighbors)
}

pub(super) fn capture(
    game: &Game<'_>,
    anchor: Pos,
    blocks: &[(Pos, BlockState)],
) -> Result<Ranges, AttachmentError> {
    blocks
        .iter()
        .filter(|(_, block)| is_chassis(&block.name))
        .map(|(local, block)| {
            if !valid_local(*local) {
                return Err(AttachmentError::Encode);
            }
            let pos = offset(anchor, *local).ok_or(AttachmentError::Encode)?;
            let state = captured(game, pos, block).ok_or(AttachmentError::Encode)?;
            Ok((*local, state.range()))
        })
        .collect()
}

fn transaction(
    game: &mut Game<'_>,
    key: [i32; 2],
    update: impl FnOnce(&mut Mounted) -> bool,
    apply: impl FnOnce(&mut Game<'_>) -> bool,
) -> bool {
    let holder = Holder::Chunk(key);
    let Ok(map) = game.attachment_map_quiet(holder) else {
        return false;
    };
    let Ok(existing) = map.get_existing(&MOUNTED) else {
        return false;
    };
    let mut mounted = existing.unwrap_or_default();
    if !update(&mut mounted) {
        return false;
    }
    let previous = map.clone();
    let saved = if mounted.is_empty() {
        map.remove(&MOUNTED).map(|_| ())
    } else {
        map.set(&MOUNTED, mounted)
    };
    if saved.is_ok() && apply(game) {
        return true;
    }
    if let Ok(map) = game.attachment_map_quiet(holder) {
        *map = previous;
    }
    false
}

pub(super) fn commit_capture(
    game: &mut Game<'_>,
    key: [i32; 2],
    controller: Pos,
    ranges: Ranges,
    apply: impl FnOnce(&mut Game<'_>) -> bool,
) -> bool {
    if ranges.is_empty() {
        return apply(game);
    }
    transaction(
        game,
        key,
        |map| map.insert(controller, ranges).is_none(),
        apply,
    )
}

pub(super) fn commit_landing(
    game: &mut Game<'_>,
    key: [i32; 2],
    record: &Record,
    origin: Pos,
    turn: QuarterTurn,
    edits: &[Edit],
    apply: impl FnOnce(&mut Game<'_>) -> bool,
) -> bool {
    let mut positions = BTreeMap::new();
    for (local, _) in record
        .blocks
        .iter()
        .filter(|(_, block)| is_chassis(&block.name))
    {
        let Some(pos) = turn.place(origin, *local) else {
            return false;
        };
        if game
            .world
            .block_entities
            .contains_key(&(pos[0], pos[1], pos[2]))
            || !edits.iter().any(|(at, _, after)| {
                *at == pos
                    && game
                        .pack
                        .assets
                        .registry
                        .state(*after)
                        .is_some_and(|state| is_chassis(&state.name))
            })
            || positions.insert(*local, pos).is_some()
        {
            return false;
        }
    }
    if positions.is_empty() {
        return apply(game);
    }
    let mut cargo = Ranges::new();
    if !transaction(
        game,
        key,
        |map| {
            let Some(ranges) = map.remove(&record.controller) else {
                return false;
            };
            if !ranges.keys().eq(positions.keys()) {
                return false;
            }
            cargo = ranges;
            true
        },
        apply,
    ) {
        return false;
    }
    for (local, range) in cargo {
        let pos = positions[&local];
        let entity = ModBlockEntity::new(ModBlockEntityFields {
            id: ENTITY.into(),
            nbt: range_nbt(range),
            ..Default::default()
        });
        game.world
            .block_entities
            .insert((pos[0], pos[1], pos[2]), BlockEntity::Mod(Box::new(entity)));
        game.native_block_entity_sync(pos);
    }
    true
}

fn valid_local(pos: Pos) -> bool {
    pos.iter().all(|p| p.unsigned_abs() <= 15)
}

fn encode(mounted: &Mounted) -> Result<Compound, AttachmentError> {
    if mounted.len() > MAX_RECORDS
        || mounted.values().any(|ranges| {
            ranges.is_empty()
                || ranges.len() > MAX_BLOCKS
                || ranges
                    .iter()
                    .any(|(&pos, &range)| !valid_local(pos) || !(1..=MAX_RANGE).contains(&range))
        })
    {
        return Err(AttachmentError::Encode);
    }
    let entries = mounted
        .iter()
        .map(|(controller, ranges)| {
            let ranges = ranges
                .iter()
                .map(|(pos, range)| Tag::IntArray(vec![pos[0], pos[1], pos[2], i32::from(*range)]))
                .collect();
            Tag::compound([
                ("Controller", Tag::IntArray(controller.to_vec())),
                ("Ranges", Tag::List(ranges)),
            ])
        })
        .collect();
    Ok(Compound::from([
        ("Version".into(), Tag::Int(1)),
        ("Entries".into(), Tag::List(entries)),
    ]))
}

fn decode(saved: &Compound) -> Result<Mounted, AttachmentError> {
    let invalid = AttachmentError::Decode;
    let Some(Tag::List(entries)) = saved.get(&"Entries".into()) else {
        return Err(invalid);
    };
    if saved.len() != 2
        || saved.get(&"Version".into()) != Some(&Tag::Int(1))
        || entries.len() > MAX_RECORDS
    {
        return Err(invalid);
    }
    let mut mounted = Mounted::new();
    for entry in entries {
        if !matches!(entry, Tag::Compound(fields) if fields.len() == 2) {
            return Err(invalid);
        }
        let Some(Tag::IntArray(controller)) = entry.get("Controller") else {
            return Err(invalid);
        };
        let controller = <Pos>::try_from(controller.as_slice()).map_err(|_| invalid)?;
        let Some(Tag::List(ranges)) = entry.get("Ranges") else {
            return Err(invalid);
        };
        if ranges.is_empty() || ranges.len() > MAX_BLOCKS {
            return Err(invalid);
        }
        let mut local = Ranges::new();
        for range in ranges {
            let Tag::IntArray(fields) = range else {
                return Err(invalid);
            };
            let &[x, y, z, range] = fields.as_slice() else {
                return Err(invalid);
            };
            let pos = [x, y, z];
            if !valid_local(pos)
                || !(1..=i32::from(MAX_RANGE)).contains(&range)
                || local.insert(pos, range as u8).is_some()
            {
                return Err(invalid);
            }
        }
        if mounted.insert(controller, local).is_some() {
            return Err(invalid);
        }
    }
    Ok(mounted)
}
