// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

// Authoritative world adapter for moving contraption actors.

use super::{
    Game, create_port_contraption as contraption, create_port_contraption_storage as storage,
    create_port_deployer as deployer,
};
use crate::items::ItemStack;
use create_engine::{
    contraption::actors::{
        MotionState, MotionTracker, Movement, Sample, Tool,
        breaking::{self, BreakState, Breaker, ContraptionKind, Step},
        drop_velocity,
        harvester::{self, Age, Block, LootTool, Plant, Replacement, Rules},
        saw::{self, Material, Target, TreeBlock, TreeStem},
        throw_boost,
    },
    deployer as deployer_core,
    kinetics::{Axis, Pos},
    placement::Direction,
};
use glam::{DQuat, DVec3};
use horizon_client_render::create_contraption_scene::{MAX_BLOCKS, MAX_RECORDS, Record};
use horizon_core::{
    geometry::{Aabb, Vec3},
    position::BlockPos,
    random::RandomSource,
};
use horizon_protocol::packets::play::{self, Clientbound};
use horizon_world::{
    attachments::{AttachmentCodec, AttachmentError, AttachmentType, Holder},
    chunk::BlockState,
    level::{data::state_flags, flags},
    loot::with_native_loot_place,
    nbt::{Compound, Tag},
    registry::BlockStateId,
};
use std::{
    collections::BTreeMap,
    sync::atomic::{AtomicI32, Ordering},
};

const HARVESTER: &str = "create:mechanical_harvester";
pub(super) const PLOUGH: &str = "create:mechanical_plough";
const SAW: &str = "create:mechanical_saw";
const DRILL: &str = "create:mechanical_drill";
const UPDATE: i32 = flags::UPDATE_NEIGHBORS | flags::UPDATE_CLIENTS;
const TREE_SEARCH_LIMIT: usize = 16_384;
static NEXT_BREAKER: AtomicI32 = AtomicI32::new(i32::MIN);

pub(super) fn attached_actor(block: &str) -> bool {
    matches!(block, HARVESTER | PLOUGH)
}

#[derive(Clone, Default)]
struct Actor {
    tracker: MotionTracker,
    cutter: Option<MovingCutter>,
    mounted_deployer: bool,
}

#[derive(Clone)]
struct MovingCutter {
    breaker: Breaker,
    id: i32,
}

type Actors = BTreeMap<Pos, BTreeMap<Pos, Actor>>;

const ACTORS: AttachmentType<Actors> = AttachmentType {
    namespace: "create",
    name: "moving_actor_ticks",
    default: Actors::new,
    codec: Some(AttachmentCodec { encode, decode }),
    copy_on_death: false,
    sync: false,
};

fn vector_tag(vector: [f64; 3]) -> Tag {
    Tag::List(
        vector
            .into_iter()
            .map(|v| Tag::Double(v.to_bits()))
            .collect(),
    )
}

// Live cuts constrain the driver. Moving Deployers also retain the previous
// visit across reload so that a shared chest item is consumed at most once.
fn actor_tag(local: Pos, actor: &Actor) -> Option<Tag> {
    let motion = actor.tracker.state();
    let cut = actor
        .cutter
        .as_ref()
        .map(|cutter| cutter.breaker.state())
        .filter(|state| state.stalled);
    if !actor.mounted_deployer && cut.is_none() {
        return None;
    }
    let mut nbt = Compound::from([
        ("Local".into(), Tag::IntArray(local.to_vec())),
        ("Position".into(), vector_tag(motion.position?)),
        ("Motion".into(), vector_tag(motion.motion)),
        ("RelativeMotion".into(), vector_tag(motion.relative_motion)),
        (
            "FirstMovement".into(),
            Tag::Byte(i8::from(motion.first_movement)),
        ),
    ]);
    if let Some(state) = cut {
        nbt.insert("BreakingPos".into(), Tag::IntArray(state.target?.to_vec()));
        nbt.insert("Progress".into(), Tag::Int(i32::from(state.progress)));
        nbt.insert(
            "TicksUntilNextProgress".into(),
            Tag::Int(state.ticks_until_progress),
        );
    } else {
        nbt.insert("Deployer".into(), Tag::Byte(1));
    }
    Some(Tag::Compound(nbt))
}

fn encode(actors: &Actors) -> Result<Compound, AttachmentError> {
    if actors.len() > MAX_RECORDS || actors.values().any(|group| group.len() > MAX_BLOCKS) {
        return Err(AttachmentError::Encode);
    }
    let mut version = 1;
    let structures = actors
        .iter()
        .filter_map(|(controller, group)| {
            let saved: Vec<_> = group
                .iter()
                .filter_map(|(&local, actor)| {
                    let tag = actor_tag(local, actor)?;
                    if actor.mounted_deployer {
                        version = 2;
                    }
                    Some(tag)
                })
                .collect();
            (!saved.is_empty()).then(|| {
                Tag::Compound(Compound::from([
                    ("Controller".into(), Tag::IntArray(controller.to_vec())),
                    ("Actors".into(), Tag::List(saved)),
                ]))
            })
        })
        .collect();
    Ok(Compound::from([
        ("Version".into(), Tag::Int(version)),
        ("Structures".into(), Tag::List(structures)),
    ]))
}

fn decode(attachment: &Compound) -> Result<Actors, AttachmentError> {
    fn load_pos(tag: &Tag) -> Option<Pos> {
        match tag {
            Tag::IntArray(coords) => coords.as_slice().try_into().ok(),
            _ => None,
        }
    }
    fn load_vector(tag: &Tag) -> Option<[f64; 3]> {
        let Tag::List(coords) = tag else { return None };
        let [Tag::Double(x), Tag::Double(y), Tag::Double(z)] = coords.as_slice() else {
            return None;
        };
        Some([*x, *y, *z].map(f64::from_bits))
    }
    fn load_flag(tag: &Tag) -> Option<bool> {
        match tag {
            Tag::Byte(0) => Some(false),
            Tag::Byte(1) => Some(true),
            _ => None,
        }
    }
    fn read_actor(tag: &Compound, version: i32) -> Option<(Pos, Actor)> {
        let local = load_pos(tag.get(&"Local".into())?)?;
        let tracker = MotionTracker::restore(MotionState {
            position: Some(load_vector(tag.get(&"Position".into())?)?),
            motion: load_vector(tag.get(&"Motion".into())?)?,
            relative_motion: load_vector(tag.get(&"RelativeMotion".into())?)?,
            first_movement: load_flag(tag.get(&"FirstMovement".into())?)?,
        })?;
        if let Some(deployer) = tag.get(&"Deployer".into()) {
            return (version == 2 && *deployer == Tag::Byte(1) && tag.len() == 6).then_some((
                local,
                Actor {
                    tracker,
                    cutter: None,
                    mounted_deployer: true,
                },
            ));
        }
        let (Some(Tag::Int(progress)), Some(Tag::Int(ticks))) = (
            tag.get(&"Progress".into()),
            tag.get(&"TicksUntilNextProgress".into()),
        ) else {
            return None;
        };
        let breaker = Breaker::restore(BreakState {
            target: Some(load_pos(tag.get(&"BreakingPos".into())?)?),
            progress: u8::try_from(*progress).ok()?,
            ticks_until_progress: *ticks,
            stalled: true,
        })?;
        let cutter = MovingCutter {
            breaker,
            id: NEXT_BREAKER.fetch_add(1, Ordering::Relaxed),
        };
        Some((
            local,
            Actor {
                tracker,
                cutter: Some(cutter),
                mounted_deployer: false,
            },
        ))
    }

    let error = AttachmentError::Decode;
    let (Some(Tag::Int(version @ (1 | 2))), Some(Tag::List(structures))) = (
        attachment.get(&"Version".into()),
        attachment.get(&"Structures".into()),
    ) else {
        return Err(error);
    };
    if structures.len() > MAX_RECORDS {
        return Err(error);
    }
    let mut actors = Actors::new();
    for structure in structures {
        let Tag::Compound(structure) = structure else {
            return Err(error);
        };
        let controller = structure
            .get(&"Controller".into())
            .and_then(load_pos)
            .ok_or(error)?;
        let Some(Tag::List(group)) = structure.get(&"Actors".into()) else {
            return Err(error);
        };
        if group.len() > MAX_BLOCKS {
            return Err(error);
        }
        let mut local_actors = BTreeMap::new();
        for entry in group {
            let Tag::Compound(entry) = entry else {
                return Err(error);
            };
            let (local, actor) = read_actor(entry, *version).ok_or(error)?;
            if local_actors.insert(local, actor).is_some() {
                return Err(error);
            }
        }
        if actors.insert(controller, local_actors).is_some() {
            return Err(error);
        }
    }
    Ok(actors)
}

pub(super) fn stalled(game: &mut Game<'_>, controller: Pos) -> bool {
    let [x, z] = contraption::column(controller);
    if !game
        .world
        .chunks
        .get(&(x, z))
        .and_then(|chunk| chunk.saved.as_ref())
        .is_some_and(|saved| saved.attachments.has(&ACTORS))
    {
        return false;
    }
    game.attachment_map_quiet(Holder::Chunk([x, z]))
        .and_then(|attachments| attachments.get_existing(&ACTORS))
        .ok()
        .flatten()
        .and_then(|mut actors| actors.remove(&controller))
        .is_some_and(|actors| {
            actors.values().any(|actor| {
                actor
                    .cutter
                    .as_ref()
                    .is_some_and(|saw| saw.breaker.stalled())
            })
        })
}

pub(super) fn remove(game: &mut Game<'_>, controller: Pos) {
    let holder = Holder::Chunk(contraption::column(controller));
    let Ok(attachments) = game.attachment_map_quiet(holder) else {
        return;
    };
    let Ok(Some(mut entries)) = attachments.get_existing(&ACTORS) else {
        return;
    };
    let Some(actors) = entries.remove(&controller) else {
        return;
    };
    if entries.is_empty() {
        let _ = attachments.remove(&ACTORS);
    } else {
        let _ = attachments.set(&ACTORS, entries);
    }
    for mut saw in actors.into_values().filter_map(|actor| actor.cutter) {
        if let Step::Clear { position } = saw.breaker.cancel() {
            crack(game, saw.id, position, -1);
        }
    }
}

pub(super) fn tick(game: &mut Game<'_>, previous: &Record, current: &Record) {
    tick_actors(game, previous, current, Phase::Driver);
}

pub(super) fn tick_bearing_tools(game: &mut Game<'_>, published: &Record) {
    // Java's entity visits the last published pose before the bearing's block
    // entity advances it. A stall started or released here affects that turn.
    tick_actors(game, published, published, Phase::BearingTools);
}

pub(super) fn tick_bearing_deployer(game: &mut Game<'_>, previous: &Record, current: &Record) {
    tick_actors(game, previous, current, Phase::BearingDeployer);
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Phase {
    Driver,
    BearingTools,
    BearingDeployer,
}

impl Phase {
    fn handles(self, name: &str) -> bool {
        if name == deployer::BLOCK {
            return self != Self::BearingTools;
        }
        self != Self::BearingDeployer && matches!(name, HARVESTER | PLOUGH | SAW | DRILL)
    }
}

fn tick_actors(game: &mut Game<'_>, previous: &Record, current: &Record, phase: Phase) {
    if game.options.execution_role.is_client()
        || !current
            .blocks
            .iter()
            .any(|(_, state)| phase.handles(state.name.as_str()))
    {
        return;
    }
    let holder = Holder::Chunk(contraption::column(current.controller));
    let Ok(mut entries) = game
        .attachment_map_quiet(holder)
        .and_then(|attachments| attachments.get(&ACTORS))
    else {
        return;
    };
    let mut actors = entries.remove(&current.controller).unwrap_or_default();
    let before = previous.orientation(previous.angle);
    let after = current.orientation(current.angle);
    let origin_before = DVec3::from_array(previous.origin_at(1.0));
    let origin_after = DVec3::from_array(current.origin_at(1.0));
    let mount = storage::mounted_chest(current);
    for (local, state) in current.blocks.iter() {
        if !phase.handles(state.name.as_str()) {
            continue;
        }
        let Some(facing) = state
            .properties
            .get("facing")
            .and_then(|name| Direction::ALL.into_iter().find(|dir| dir.name() == name))
        else {
            continue;
        };
        if state.name == deployer::BLOCK && deployer::supported_record(current) {
            let local_point = DVec3::from_array(deployer_core::active_point(*local, facing));
            // Java's bearing publishes an angle during its block entity turn.
            // Its independently ticked contraption first samples the published
            // moving pose, then visits cells using the preceding angle.
            if !actors.contains_key(local) && previous.angle == 0.0 {
                continue;
            }
            let angle = previous.angle;
            let center = DVec3::splat(0.5);
            let rotate = |point, angle| create_engine::source_trig::rotate(point, angle, Axis::Y);
            let point = (origin_before
                + center
                + DVec3::from_array(rotate((local_point - center).to_array(), angle)))
            .to_array();
            let sample = |position| Sample {
                position,
                facing,
                stalled: false,
                disabled: false,
                allow_stationary_first_visit: false,
            };
            let actor = actors.entry(*local).or_default();
            actor.mounted_deployer = true;
            let movement = deployer_core::track_actor(
                &mut actor.tracker,
                sample(point),
                |m| m,
                |m| rotate(m, -angle),
            );
            if let Some(cell) = movement.visit {
                let forward = rotate(facing.vector().map(f64::from), angle);
                let vertical = rotate(DVec3::Z.to_array(), angle);
                deployer::plant(
                    game,
                    current,
                    *local,
                    deployer_core::moving_aim(cell, point, forward, vertical),
                );
            }
            continue;
        }
        let tool = match state.name.as_str() {
            HARVESTER => Tool::Harvester,
            PLOUGH => Tool::Plough,
            SAW => Tool::Saw,
            DRILL => Tool::Drill,
            _ => continue,
        };
        if matches!(tool, Tool::Harvester | Tool::Plough) && facing.axis() == Axis::Y {
            continue;
        }
        let point = DVec3::from_array(tool.active_point(*local, facing));
        let after_point = world_point(origin_after, after, point);
        let identity = |motion| motion;
        let actor = actors.entry(*local).or_insert_with(|| {
            let mut actor = Actor::default();
            // A newly spawned bearing entity starts with no previous actor
            // position. The other drivers still use their advancing pose.
            if phase == Phase::Driver {
                actor.tracker.sample(
                    Sample {
                        position: world_point(origin_before, before, point),
                        facing,
                        stalled: false,
                        disabled: false,
                        allow_stationary_first_visit: false,
                    },
                    identity,
                    identity,
                );
            }
            if tool != Tool::Harvester {
                actor.cutter = Some(MovingCutter {
                    breaker: Breaker::default(),
                    id: NEXT_BREAKER.fetch_add(1, Ordering::Relaxed),
                });
            }
            actor
        });
        let movement = actor.tracker.sample(
            Sample {
                position: after_point,
                facing,
                stalled: actor
                    .cutter
                    .as_ref()
                    .is_some_and(|saw| saw.breaker.stalled()),
                disabled: false,
                allow_stationary_first_visit: false,
            },
            identity,
            |motion| (after.conjugate() * DVec3::from_array(motion)).to_array(),
        );
        if let Some(saw) = &mut actor.cutter {
            if movement.active {
                let normal = DVec3::from_array(facing.vector().map(f64::from));
                tick_cutter(
                    game,
                    mount,
                    tool,
                    saw,
                    movement,
                    after_point,
                    (after * normal).to_array(),
                );
            }
        } else if let Some(position) = movement.visit {
            harvest(game, mount, position, after_point, movement.motion);
        }
    }
    entries.insert(current.controller, actors);
    if let Ok(attachments) = game.attachment_map_quiet(holder) {
        let _ = attachments.set(&ACTORS, entries);
    }
}

fn world_point(origin: DVec3, orientation: DQuat, local: DVec3) -> [f64; 3] {
    let center = DVec3::splat(0.5);
    (origin + center + orientation * (local - center)).to_array()
}

fn loaded_state(game: &Game<'_>, position: Pos) -> Option<BlockStateId> {
    (game.world.loaded(position[0], position[2]) && contraption::resident(game, position))
        .then(|| contraption::state(game, position))
}

fn tree_block(game: &Game<'_>, state: &BlockState) -> TreeBlock {
    let name = state.name.as_str();
    if !name.starts_with("minecraft:") {
        return TreeBlock::default();
    }
    let stem = match name {
        "minecraft:mangrove_roots" => TreeStem::Root,
        "minecraft:mushroom_stem" => TreeStem::Log,
        "minecraft:bamboo"
        | "minecraft:cactus"
        | "minecraft:sugar_cane"
        | "minecraft:kelp"
        | "minecraft:kelp_plant" => TreeStem::VerticalPlant,
        "minecraft:chorus_plant" | "minecraft:chorus_flower" => TreeStem::Chorus,
        _ if in_tag(game, state, "minecraft:logs") => TreeStem::Log,
        _ => TreeStem::None,
    };
    let attachment = matches!(
        name,
        "minecraft:bee_nest"
            | "minecraft:cocoa"
            | "minecraft:mangrove_propagule"
            | "minecraft:moss_carpet"
            | "minecraft:shroomlight"
            | "minecraft:vine"
    ) || in_tag(game, state, "create:tree_attachments");
    let nondecaying_leaf_radius = match name {
        "minecraft:red_mushroom_block" => Some(2),
        "minecraft:brown_mushroom_block"
        | "minecraft:weeping_vines"
        | "minecraft:weeping_vines_plant" => Some(3),
        _ if in_tag(game, state, "minecraft:wart_blocks") => Some(3),
        _ => None,
    };
    let leaf_distance = if name == "minecraft:scaffolding" {
        None
    } else {
        state
            .properties
            .get("distance")
            .and_then(|value| value.parse().ok())
    };
    TreeBlock {
        stem,
        attachment,
        nondecaying_leaf_radius,
        leaf_distance,
    }
}

fn in_tag(game: &Game<'_>, state: &BlockState, tag: &str) -> bool {
    game.native_server_block_in_tag(state, tag).unwrap_or(false)
}

pub(super) fn saw_can_break(game: &Game<'_>, position: Pos) -> bool {
    saw_target(game, position).is_sawable()
}

fn saw_target(game: &Game<'_>, position: Pos) -> Target {
    let invalid = Target {
        material: Material::Other,
        hardness: -1.0,
        excluded: true,
    };
    let Some(id) = loaded_state(game, position) else {
        return invalid;
    };
    let Some(state) = game.pack.assets.registry.state(id) else {
        return invalid;
    };
    if !state.name.starts_with("minecraft:") {
        return invalid;
    }
    let material = match state.name.as_str() {
        "minecraft:pumpkin" | "minecraft:melon" => Material::PumpkinOrMelon,
        "minecraft:chorus_plant" => Material::ChorusPlant,
        _ if in_tag(game, state, "minecraft:leaves") => Material::Leaves,
        _ => match tree_block(game, state).stem {
            TreeStem::Log | TreeStem::Root => Material::LogOrRoot,
            TreeStem::VerticalPlant => Material::VerticalPlant,
            _ => Material::Other,
        },
    };
    let facts = game.res.facts().get(id);
    let excluded = in_tag(game, state, "minecraft:saplings")
        || !matches!(
            game.native_server_block_in_tag(state, "create:non_breakable"),
            Ok(false)
        );
    Target {
        material,
        hardness: facts.hardness,
        excluded,
    }
}

fn drill_target(game: &Game<'_>, position: Pos) -> breaking::Target {
    let invalid = breaking::Target {
        hardness: -1.0,
        breakable: false,
    };
    let Some(id) = loaded_state(game, position) else {
        return invalid;
    };
    let Some(state) = game.pack.assets.registry.state(id) else {
        return invalid;
    };
    let facts = game.res.facts().get(id);
    let breakable = facts.hardness != -1.0
        && state.name.starts_with("minecraft:")
        && !matches!(state.name.as_str(), "minecraft:water" | "minecraft:lava")
        && game.collision.may_collide(id)
        && !in_tag(game, state, "create:tracks")
        && matches!(
            game.native_server_block_in_tag(state, "create:non_breakable"),
            Ok(false)
        )
        && !game
            .world
            .block_entities
            .contains_key(&(position[0], position[1], position[2]));
    breaking::Target {
        hardness: facts.hardness,
        breakable,
    }
}

pub(super) fn drill_can_break(game: &Game<'_>, position: Pos) -> bool {
    drill_target(game, position).breakable
}

pub(super) fn plough_can_break(game: &Game<'_>, position: Pos) -> bool {
    plough_target(game, position).breakable
}

fn plough_target(game: &Game<'_>, position: Pos) -> breaking::Target {
    let invalid = breaking::Target {
        hardness: -1.0,
        breakable: false,
    };
    let Some(id) = loaded_state(game, position) else {
        return invalid;
    };
    let Some(state) = game.pack.assets.registry.state(id) else {
        return invalid;
    };
    let below = [position[0], position[1] - 1, position[2]];
    let facts = game.res.facts().get(id);
    let breakable = state.name.starts_with("minecraft:")
        && !game.res.facts().is_air(id)
        && facts.hardness >= 0.0
        && loaded_state(game, below).is_some()
        && game.native_block(below) != "minecraft:farmland"
        && !matches!(
            state.name.as_str(),
            "minecraft:water" | "minecraft:lava" | "minecraft:bubble_column"
        )
        && !in_tag(game, state, "create:plough_blacklist")
        && (in_tag(game, state, "create:plough_whitelist") || !game.collision.may_collide(id))
        && !game
            .world
            .block_entities
            .contains_key(&(position[0], position[1], position[2]));
    breaking::Target {
        hardness: facts.hardness,
        breakable,
    }
}

// PloughMovementBehaviour clips from the active cell's center to the center
// of the cell below, then uses an unbreakable diamond hoe on that top face.
// This adapter supports an unobstructed ray to the ordinary vanilla soils.
fn till(game: &mut Game<'_>, position: Pos) {
    let [x, y, z] = position;
    let ground = [x, y - 1, z];
    if !loaded_state(game, position).is_some_and(|id| game.res.facts().is_air(id))
        || loaded_state(game, ground).is_none()
    {
        return;
    }
    let soil = game.native_block(ground);
    let replacement = match soil.as_str() {
        "minecraft:grass_block" | "minecraft:dirt" | "minecraft:dirt_path" => "minecraft:farmland",
        "minecraft:coarse_dirt" | "minecraft:rooted_dirt" => "minecraft:dirt",
        _ => return,
    };
    let Some(state) = game.pack.assets.registry.default_state(replacement) else {
        return;
    };
    let changed = game.with_level(|behaviour, level, ticks| {
        if !behaviour.set_block(level, ticks, BlockPos::new(x, y - 1, z), state, UPDATE) {
            return false;
        }
        level.native_play_sound("minecraft:item.hoe.till", block_center(ground), 4, 1.0, 1.0);
        true
    });
    if changed && soil == "minecraft:rooted_dirt" {
        game.pop_resource(position, ItemStack::new("minecraft:hanging_roots", 1));
    }
    if let Err(error) = game.process_level_events() {
        log::warn!("Create Plough could not update {ground:?}: {error}");
    }
}

pub(super) fn harvester_can_pass(game: &Game<'_>, position: Pos) -> bool {
    let Some(id) = loaded_state(game, position) else {
        return false;
    };
    game.pack
        .assets
        .registry
        .state(id)
        .and_then(|state| crop_at(game, id, state))
        .is_some_and(|(crop, _)| {
            // The translating collider asks isValidCrop/isValidOther directly,
            // before the harvest visit checks the non-harvestable tag.
            harvester::plan(
                Block {
                    excluded: false,
                    ..crop
                },
                Rules::default(),
            )
            .is_some()
        })
}

fn tick_cutter(
    game: &mut Game<'_>,
    mount: Option<storage::Mount>,
    tool: Tool,
    cutter: &mut MovingCutter,
    movement: Movement,
    at: [f64; 3],
    facing: [f64; 3],
) {
    if let Some(position) = movement.visit {
        if tool == Tool::Plough {
            throw_plough_mobs(game, position, movement.motion);
        }
        cutter
            .breaker
            .visit(position, cutter_target(game, tool, position));
        if tool == Tool::Saw && saw::vertical(facing) {
            cutter.breaker.forget_target();
        }
        if tool == Tool::Plough {
            till(game, position);
        }
    }
    let step = cutter.breaker.tick(
        movement.relative_motion,
        movement.motion,
        ContraptionKind::Other,
        |position| cutter_target(game, tool, position),
    );
    let strike = match step {
        Step::Hit { position, .. } | Step::Finish { position } => position,
        Step::Clear { position } => {
            crack(game, cutter.id, position, -1);
            return;
        }
        Step::Idle => return,
    };
    let state = contraption::state(game, strike);
    let hit = game.res.facts().get(state).sounds.hit.to_string();
    game.with_level(|_, level, _| {
        level.native_play_sound(&hit, block_center(strike), 6, 0.25, 1.0)
    });
    match step {
        Step::Hit { progress, .. } => crack(game, cutter.id, strike, i32::from(progress)),
        Step::Finish { .. } => {
            crack(game, cutter.id, strike, -1);
            if tool == Tool::Saw {
                finish_saw(game, mount, strike, at, movement);
            } else {
                break_target(game, mount, strike, at, movement.motion, tool);
            }
        }
        _ => unreachable!(),
    }
}

fn throw_plough_mobs(game: &mut Game<'_>, position: Pos, motion: [f64; 3]) {
    let Some(state) = loaded_state(game, position) else {
        return;
    };
    if game.res.behaviours().facts(state).flags & state_flags::CONDUCTOR != 0 {
        return;
    }
    let [x, y, z] = position;
    let cell = Aabb::block(BlockPos::new(x, y, z));
    let [x, y, z] = throw_boost(motion);
    let boost = Vec3::new(x, y, z);
    for mob in &mut game.mobs {
        if !mob.removed && mob.alive() && cell.intersects(mob.bounds()) {
            mob.velocity = mob.velocity.add_vector(boost);
            mob.needs_sync = true;
        }
    }
}

fn cutter_target(game: &Game<'_>, tool: Tool, position: Pos) -> breaking::Target {
    match tool {
        Tool::Plough => plough_target(game, position),
        Tool::Saw => saw_target(game, position).breaking_target(),
        Tool::Drill => drill_target(game, position),
        Tool::Harvester => unreachable!("harvesters do not stall and break blocks"),
    }
}

fn crack(game: &mut Game<'_>, id: i32, position: Pos, progress: i32) {
    game.destroy_block_progress(id, position, progress);
    if let Some(host) = game.lan.as_ref() {
        host.hub.broadcast_near(
            block_center(position),
            64.0,
            &Clientbound::BlockDestruction(play::BlockDestruction {
                id,
                pos: position,
                progress: progress as u8,
            }),
            None,
        );
    }
}

fn top_falling_block(game: &Game<'_>, position: Pos) -> Pos {
    let mut top = position;
    // The shared Java block breaker removes the top of a falling-block stack.
    while let Some(y) = top[1].checked_add(1) {
        let above = [top[0], y, top[2]];
        if !loaded_state(game, above)
            .is_some_and(|id| game.res.facts().get(id).has_class("FallingBlock"))
        {
            break;
        }
        top = above;
    }
    top
}

fn break_target(
    game: &mut Game<'_>,
    mount: Option<storage::Mount>,
    position: Pos,
    at: [f64; 3],
    motion: [f64; 3],
    tool: Tool,
) {
    let top = top_falling_block(game, position);
    if let Some(id) = loaded_state(game, top) {
        let shovel = (tool == Tool::Plough && game.native_block(top) == "minecraft:snow")
            .then(|| ItemStack::new("minecraft:iron_shovel", 1));
        chop(
            game,
            top,
            id,
            1.0,
            at,
            DropMotion::Actor { mount, motion },
            shovel.as_ref().map_or(DropTool::None, DropTool::Actor),
        );
    }
}

fn finish_saw(
    game: &mut Game<'_>,
    mount: Option<storage::Mount>,
    position: Pos,
    at: [f64; 3],
    movement: Movement,
) {
    let registry = game.pack.assets.registry;
    let top = top_falling_block(game, position);
    let Some(id) = loaded_state(game, top) else {
        return;
    };
    let Some(state) = registry.state(id) else {
        return;
    };
    if !state.name.starts_with("minecraft:") {
        return;
    }
    let is_leaves = in_tag(game, state, "minecraft:leaves");
    let broken = tree_block(game, state);
    let drop = DropMotion::Actor {
        mount,
        motion: movement.motion,
    };
    if !chop(game, top, id, 1.0, at, drop, DropTool::None) || is_leaves {
        return;
    }

    fell_tree(game, mount, position, broken, |cell| {
        saw::tree_drop_velocity(movement.relative_motion, cell, Some(at))
    });
}

pub(super) fn finish_stationary_saw(game: &mut Game<'_>, origin: Pos, target: Pos) {
    let Some(id) = loaded_state(game, target) else {
        return;
    };
    let registry = game.pack.assets.registry;
    let Some(state) = registry.state(id) else {
        return;
    };
    let broken = tree_block(game, state);
    let at = stationary_drop_origin(game, target);
    if !chop(
        game,
        target,
        id,
        1.0,
        at,
        DropMotion::Stationary,
        DropTool::None,
    ) {
        return;
    }
    let direction = std::array::from_fn(|i| f64::from(target[i] - origin[i]));
    fell_tree(game, None, target, broken, |cell| {
        saw::tree_drop_velocity(direction, cell, Some(block_center(target)))
    });
}

/// BlockBreakingKineticBlockEntity gives every loot stack from this block
/// the same randomized origin within one eighth of the block's center.
pub(super) fn stationary_drop_origin(game: &mut Game<'_>, target: Pos) -> [f64; 3] {
    let mut at = block_center(target);
    for coord in &mut at {
        *coord += f64::from((game.world.random.next_float() - 0.5) * 0.25);
    }
    at
}

fn fell_tree(
    game: &mut Game<'_>,
    mount: Option<storage::Mount>,
    position: Pos,
    broken: TreeBlock,
    velocity_at: impl Fn(Pos) -> [f64; 3],
) {
    let registry = game.pack.assets.registry;
    let (min_y, height) = game.native_world_height();
    let Ok(tree) = saw::find_tree(position, broken, height as u32, TREE_SEARCH_LIMIT, |cell| {
        if !(min_y..min_y.saturating_add(height)).contains(&cell[1]) {
            return Some(TreeBlock::default());
        }
        let state = registry.state(loaded_state(game, cell)?)?;
        Some(tree_block(game, state))
    }) else {
        return;
    };

    // Keep a state snapshot so a changed or self-removed branch is never
    // broken a second time. Java's vertical-plant queue may visit it twice.
    let planned: Vec<_> = tree
        .actions()
        .filter_map(|(part, cell)| {
            let state = loaded_state(game, cell)?;
            Some((part, cell, state))
        })
        .collect();
    for (part, cell, state) in planned {
        let velocity = velocity_at(cell);
        chop(
            game,
            cell,
            state,
            part.particles_chance(),
            block_center(cell),
            DropMotion::Tree { mount, velocity },
            DropTool::None,
        );
    }
}

enum DropMotion {
    Stationary,
    Actor {
        mount: Option<storage::Mount>,
        motion: [f64; 3],
    },
    Tree {
        mount: Option<storage::Mount>,
        velocity: [f64; 3],
    },
}

enum DropTool<'a> {
    None,
    Passive(&'a ItemStack),
    Actor(&'a ItemStack),
}

fn chop(
    game: &mut Game<'_>,
    position: Pos,
    state: BlockStateId,
    particles_chance: f32,
    at: [f64; 3],
    motion: DropMotion,
    loot_tool: DropTool<'_>,
) -> bool {
    if loaded_state(game, position) != Some(state) {
        return false;
    }
    let behaviour = game.res.behaviours();
    let fluid = behaviour.legacy_block(behaviour.fluid(state));
    if fluid == state {
        return false;
    }
    let mut drops = drops(game, position, state, particles_chance, loot_tool);
    if loaded_state(game, position) != Some(state) {
        return false;
    }
    let pos = BlockPos::new(position[0], position[1], position[2]);
    let updated = game.with_level(|b, level, ticks| b.set_block(level, ticks, pos, fluid, UPDATE));
    if let Err(error) = game.process_level_events() {
        log::warn!("Create saw could not process the update at {position:?}: {error:?}");
    }
    if updated {
        let mount = match motion {
            DropMotion::Stationary => None,
            DropMotion::Actor { mount, .. } | DropMotion::Tree { mount, .. } => mount,
        };
        if let Some(mount) = mount {
            storage::deposit(game, mount, position, &mut drops);
        }
        for stack in drops.into_iter().filter(|stack| stack.count > 0) {
            let (velocity, delay) = match motion {
                DropMotion::Stationary => ([0.0; 3], 10),
                DropMotion::Actor { motion, .. } => {
                    (drop_velocity(motion, game.world.random.next_float()), 0)
                }
                DropMotion::Tree { velocity, .. } => (velocity, 0),
            };
            game.spawn_item(stack, at, velocity, delay);
        }
    }
    updated
}

fn block_center(position: Pos) -> [f64; 3] {
    position.map(|coordinate| f64::from(coordinate) + 0.5)
}

fn drops(
    game: &mut Game<'_>,
    position: Pos,
    state: BlockStateId,
    particles_chance: f32,
    tool: DropTool<'_>,
) -> Vec<ItemStack> {
    if game.world.random.next_float() < particles_chance {
        game.level_event_at(2001, position, state.0 as i32);
    }
    if !game.ui.rules.bool("block_drops") {
        return Vec::new();
    }
    let registry = game.pack.assets.registry;
    let saved = registry
        .state(state)
        .and_then(|block| game.loot_block_entity(position, &block.name));
    let loot_place = game.loot_place_at(block_center(position), saved);
    let (tool, breaker) = match tool {
        DropTool::None => (None, false),
        DropTool::Passive(stack) => (Some(stack), false),
        DropTool::Actor(stack) => (Some(stack), true),
    };
    let mut drops = with_native_loot_place(loot_place, || {
        world_items!(game).block_drops_exploded(
            registry,
            state,
            tool,
            &[],
            &mut game.world.random,
            Some((&mut game.rand_sequences, game.level.seed)),
            None,
            breaker,
        )
    });
    game.native_block_drops(position, state, None, tool, None, &mut drops);
    drops
}

fn crop_at<'s>(
    game: &Game<'_>,
    id: BlockStateId,
    state: &'s BlockState,
) -> Option<(Block, &'s str)> {
    let name = state.name.as_str();
    if !name.starts_with("minecraft:") {
        return None;
    }
    let age = |mature_value| {
        let value = state.properties.get("age")?.parse().ok()?;
        (value <= mature_value).then_some(Age {
            value,
            mature_value,
        })
    };
    let plant;
    let seed;
    let mut generic_age = None;
    let leaves = in_tag(game, state, "minecraft:leaves");
    match name {
        "minecraft:wheat" | "minecraft:carrots" | "minecraft:potatoes" | "minecraft:beetroots" => {
            let (max, item) = match name {
                "minecraft:wheat" => (7, "minecraft:wheat_seeds"),
                "minecraft:carrots" => (7, "minecraft:carrot"),
                "minecraft:potatoes" => (7, "minecraft:potato"),
                _ => (3, "minecraft:beetroot_seeds"),
            };
            let age = age(max)?;
            plant = Plant::Crop {
                age,
                matches_default_zero_state: age.value == 0,
            };
            seed = item;
        }
        "minecraft:nether_wart" | "minecraft:cocoa" | "minecraft:sweet_berry_bush" => {
            let (kind, max, item) = match name {
                "minecraft:nether_wart" => (Plant::Other, 3, "minecraft:nether_wart"),
                "minecraft:cocoa" => (Plant::Cocoa, 2, "minecraft:cocoa_beans"),
                _ => (Plant::SweetBerryBush, 3, "minecraft:sweet_berries"),
            };
            generic_age = Some(age(max)?);
            plant = kind;
            seed = item;
        }
        "minecraft:sugar_cane" => {
            generic_age = age(15);
            plant = Plant::SugarCane;
            seed = name;
        }
        // These vanilla BushBlocks have no `age` property in Create 6.0.10.
        "minecraft:dandelion"
        | "minecraft:poppy"
        | "minecraft:oak_sapling"
        | "minecraft:birch_sapling" => {
            plant = Plant::BushOrSpecialPlantable;
            seed = name;
        }
        _ if leaves => {
            plant = Plant::Other;
            seed = name;
        }
        _ if game.res.facts().get(id).has_class("GrowingPlantBlock") => {
            // A head with an age property can qualify for the seed reservation,
            // although the plant is cut even before it reaches maturity.
            generic_age = age(25);
            plant = Plant::GrowingPlant;
            seed = match name {
                "minecraft:kelp_plant" => "minecraft:kelp",
                "minecraft:twisting_vines_plant" => "minecraft:twisting_vines",
                "minecraft:weeping_vines_plant" => "minecraft:weeping_vines",
                "minecraft:cave_vines" | "minecraft:cave_vines_plant" => "minecraft:glow_berries",
                _ => name,
            };
        }
        _ => return None,
    }
    let excluded = game
        .native_server_block_in_tag(state, "create:non_harvestable")
        .ok()?;
    Some((
        Block {
            plant,
            generic_age,
            leaves,
            excluded,
            collision_empty: !game.collision.may_collide(id),
            sugar_cane_variant: name == "minecraft:sugar_cane",
        },
        seed,
    ))
}

fn harvest(
    game: &mut Game<'_>,
    mount: Option<storage::Mount>,
    position: Pos,
    active_point: [f64; 3],
    motion: [f64; 3],
) {
    let registry = game.pack.assets.registry;
    let Some(original) = loaded_state(game, position) else {
        return;
    };
    let Some(state) = registry.state(original) else {
        return;
    };
    let Some((crop, seed)) = crop_at(game, original, state) else {
        return;
    };
    let Some(mut cut) = harvester::plan(crop, Rules::default()) else {
        return;
    };
    let fluid = game
        .res
        .behaviours()
        .legacy_block(game.res.behaviours().fluid(original));
    let replacement = match cut.replacement {
        Replacement::FluidOrAir => fluid,
        Replacement::ResetCropAge | Replacement::SetGenericAge(_) => {
            let age = match cut.replacement {
                Replacement::SetGenericAge(age) => age,
                _ => 0,
            };
            let mut replanted = state.clone();
            replanted.properties.insert("age".into(), age.to_string());
            let Some(id) = registry.id(&replanted) else {
                return;
            };
            id
        }
    };
    let tool = (cut.loot_tool == LootTool::Shears).then(|| ItemStack::new("minecraft:shears", 1));
    let mut drops = drops(
        game,
        position,
        original,
        cut.particles_chance,
        tool.as_ref().map_or(DropTool::None, DropTool::Passive),
    );
    if contraption::state(game, position) != original {
        return;
    }
    let at = BlockPos::new(position[0], position[1], position[2]);
    let game_air = game.world.air;
    let updated = game.with_level(|behaviour, level, ticks| {
        if !behaviour.set_block(level, ticks, at, fluid, UPDATE) {
            return false;
        }
        let final_state = if behaviour.can_survive(level, ticks, at, replacement) {
            replacement
        } else {
            game_air
        };
        if final_state != fluid {
            behaviour.set_block(level, ticks, at, final_state, UPDATE);
        }
        true
    });
    if let Err(error) = game.process_level_events() {
        log::warn!("Create harvester could not process the crop update at {position:?}: {error:?}");
    }
    if !updated {
        return;
    }

    for stack in &mut drops {
        stack.count = cut.accept_drop(stack.item.as_ref() == seed, stack.count);
    }
    if let Some(mount) = mount {
        storage::deposit(game, mount, position, &mut drops);
    }
    for stack in drops.into_iter().filter(|stack| stack.count > 0) {
        let random = game.world.random.next_float();
        game.spawn_item(stack, active_point, drop_velocity(motion, random), 0);
    }
}
