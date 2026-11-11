// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use super::{
    Game,
    create_port_contraption::{
        Capture, MountedCapture, column, commit_linear_capture, commit_linear_landing, entries,
        facing, movement_sound, resident, set_records, state,
    },
    create_port_contraption_actors as actors, create_port_super_glue as glue,
};
use crate::containers::ModBlockEntity;
use create_engine::{
    contraption::{
        Assembly, CaptureView, Cell,
        linear::{Action, LinearActuator, Mode, Motion},
        piston::{self, Layout, Part},
    },
    kinetics::Pos,
    placement::Direction,
};
use horizon_client_render::create_contraption_scene::{
    MAX_BLOCKS, MAX_RECORDS, Record, Stroke, StrokeKind,
};
use horizon_world::{chunk::BlockState, level::flags, nbt::Tag};

pub(super) const NORMAL: &str = "create:mechanical_piston";
pub(super) const STICKY: &str = "create:sticky_mechanical_piston";
pub(super) const POLE: &str = "create:piston_extension_pole";
pub(super) const HEAD: &str = "create:mechanical_piston_head";
const RUNNING: &str = "Running";
const LAST_SPEED: &str = "create_horizon:PistonPower";
const REQUEST: &str = "AssembleNextTick";

pub(super) fn is_piston(block: &str) -> bool {
    matches!(block, NORMAL | STICKY)
}

fn part(state: &BlockState) -> Option<Part> {
    let waterlogged = state
        .properties
        .get("waterlogged")
        .is_some_and(|s| s == "true");
    match state.name.as_str() {
        POLE => Some(Part::Pole { waterlogged }),
        HEAD => Some(Part::Head {
            sticky: state.properties.get("type").is_some_and(|s| s == "sticky"),
            waterlogged,
        }),
        _ => None,
    }
}

fn part_state(game: &Game<'_>, part: Part, facing: Direction) -> Option<BlockState> {
    let (name, wet) = match part {
        Part::Pole { waterlogged } => (POLE, waterlogged),
        Part::Head { waterlogged, .. } => (HEAD, waterlogged),
    };
    // The pinned Horizon build has no native moving-fluid bridge.
    if wet {
        return None;
    }
    let registry = game.pack.assets.registry;
    let mut block = registry.state(registry.default_state(name)?)?.clone();
    block
        .properties
        .insert("facing".into(), facing.name().into());
    if let Part::Head { sticky, .. } = part {
        block.properties.insert(
            "type".into(),
            if sticky { "sticky" } else { "normal" }.into(),
        );
    }
    registry.id(&block)?;
    Some(block)
}

fn base_state(
    game: &Game<'_>,
    id: horizon_world::registry::BlockStateId,
    state: &str,
) -> Option<horizon_world::registry::BlockStateId> {
    let registry = game.pack.assets.registry;
    let mut block = registry.state(id)?.clone();
    block.properties.insert("state".into(), state.into());
    registry.id(&block)
}

fn inspect(game: &Game<'_>, pos: Pos) -> piston::Cell {
    match Capture(game).inspect(pos) {
        Cell::Empty => piston::Cell::Empty,
        Cell::Unloaded => piston::Cell::Unloaded,
        Cell::OutsideWorld => piston::Cell::OutsideWorld,
        Cell::Block(rules) => {
            let block = game.pack.assets.registry.state(state(game, pos));
            if let Some((part, facing)) = block.and_then(part).zip(facing(game, pos)) {
                return piston::Cell::Extension { facing, part };
            }
            piston::Cell::Block {
                rules,
                wool_carpet: false,
            }
        }
    }
}

fn world_cell(record: &Record, local: Pos, offset: u32) -> Pos {
    let mut result = std::array::from_fn(|i| record.anchor[i] + local[i]);
    result[record.axis] +=
        (record.anchor[record.axis] - record.controller[record.axis]) * offset as i32;
    result
}

fn capture(game: &mut Game<'_>, pos: Pos, facing: Direction, rpm: f32) -> Option<u32> {
    let key = column(pos);
    let records = entries(game, key).ok()?;
    if records.len() >= MAX_RECORDS || records.iter().any(|r| r.controller == pos) {
        return None;
    }
    let layout = Layout::scan(
        pos,
        facing,
        game.native_block(pos) == STICKY,
        game.native_block_property(pos, "state").as_deref() == Some("extended"),
        piston::MAX_POLES,
        |p| inspect(game, p),
    )
    .ok()?;
    let speed = piston::directional_speed(rpm, facing);
    if !layout.can_start(speed) || layout.parts.len() > MAX_BLOCKS {
        return None;
    }
    let origin = layout.world_cell([0; 3], layout.initial_offset).ok()?;
    let seeds = layout
        .payload_frontier(speed < 0.0, piston::MAX_CHASSIS_RANGE, |p| inspect(game, p))
        .ok()?;
    let movement = if speed > 0.0 {
        facing
    } else {
        facing.opposite()
    };
    let volumes = glue::read(game, key).ok()?;
    let payload = Assembly::capture_from(
        &MountedCapture::for_linear(game, &volumes),
        origin,
        seeds,
        |p| {
            layout.anchors(p)
                || layout
                    .parts
                    .iter()
                    .any(|part| layout.world_cell(part.local, layout.initial_offset) == Ok(p))
        },
        Some(movement),
        MAX_BLOCKS - layout.parts.len(),
    )
    .ok()?;
    let mut blocks = payload.blocks().to_vec();
    for entry in &layout.parts {
        blocks.push((entry.local, part_state(game, entry.part, facing)?));
    }
    let record = Record {
        controller: pos,
        anchor: layout.anchor,
        axis: facing.axis().index(),
        angle: 0.0,
        previous_angle: 0.0,
        rpm,
        stalled: false,
        return_home: false,
        clock_hand: None,
        stroke: Some(Stroke {
            kind: StrokeKind::Piston,
            initial: layout.initial_offset,
            limit: layout.extension_length,
            offset: layout.initial_offset as f32,
            previous: layout.initial_offset as f32,
            waiting: false,
        }),
        blocks: blocks.into(),
    };
    // A linear sweep lies entirely inside a column when both ends do.
    if record.blocks.iter().any(|&(local, _)| {
        local.iter().any(|v| v.unsigned_abs() > 63)
            || [0, layout.extension_length].into_iter().any(|offset| {
                let p = world_cell(&record, local, offset);
                column(p) != key || !resident(game, p)
            })
    }) {
        return None;
    }
    let mut edits = Vec::new();
    for (local, block) in record.blocks.iter() {
        let p = world_cell(&record, *local, layout.initial_offset);
        if p == pos {
            continue;
        }
        let before = state(game, p);
        let original = game.pack.assets.registry.state(before)?;
        if part(block).is_some() {
            if part(original) != part(block)
                || super::create_port_contraption::facing(game, p)
                    .is_none_or(|direction| direction.axis() != facing.axis())
            {
                return None;
            }
        } else if block != original {
            return None;
        }
        edits.push((p, before, game.world.air));
    }
    let base = state(game, pos);
    edits.push((pos, base, base_state(game, base, "moving")?));
    // Java checks the next terrain slice before removing blocks. Treat the
    // current source cells as air; they move together as a single structure.
    let owned: std::collections::BTreeSet<_> = edits.iter().map(|&(p, _, _)| p).collect();
    let movement = movement.vector();
    let leading = std::array::from_fn(|i| origin[i] + movement[i]);
    if collides_at(game, &record, leading, movement, |p| owned.contains(&p)) {
        return None;
    }
    if !commit_linear_capture(game, key, records, record, origin, &edits) {
        return None;
    }
    movement_sound(game, pos, true);
    Some(layout.initial_offset)
}

fn collides(game: &Game<'_>, record: &Record, motion: Motion, skip: impl Fn(Pos) -> bool) -> bool {
    let sign = record.anchor[record.axis] - record.controller[record.axis];
    let origin = world_cell(record, [0; 3], 0);
    let mut leading = origin;
    let mut movement = [0; 3];
    movement[record.axis] = if (motion.to - motion.from) * sign as f32 > 0.0 {
        1
    } else {
        -1
    };
    // Java moves the entity first, then floors its new origin to find the
    // terrain slice. Only positive motion adds a further block.
    leading[record.axis] += (motion.to * sign as f32).floor() as i32 + movement[record.axis].max(0);
    collides_at(game, record, leading, movement, skip)
}

pub(super) fn collides_at(
    game: &Game<'_>,
    record: &Record,
    leading: Pos,
    movement: Pos,
    skip: impl Fn(Pos) -> bool,
) -> bool {
    let registry = game.pack.assets.registry;
    let collidable = |block: &BlockState| {
        registry
            .id(block)
            .is_none_or(|id| game.collision.may_collide(id))
    };
    record.blocks.iter().any(|(local, block)| {
        if !collidable(block) {
            return false;
        }
        let neighbour = std::array::from_fn(|i| local[i] + movement[i]);
        if record
            .blocks
            .iter()
            .any(|(at, other)| *at == neighbour && collidable(other))
        {
            return false;
        }
        let p = std::array::from_fn(|i| leading[i] + local[i]);
        if skip(p) || (p == record.controller && part(block).is_some()) {
            return false;
        }
        if !resident(game, p) {
            return true;
        }
        let state = state(game, p);
        if !game.collision.may_collide(state)
            || registry
                .state(state)
                .is_some_and(|s| s.name == "minecraft:cocoa")
        {
            return false;
        }
        match block.name.as_str() {
            "create:mechanical_saw" => !actors::saw_can_break(game, p),
            "create:mechanical_drill" => !actors::drill_can_break(game, p),
            "create:mechanical_harvester" => !actors::harvester_can_pass(game, p),
            actors::PLOUGH => !actors::plough_can_break(game, p),
            _ => !game.res.facts().get(state).replaceable,
        }
    })
}

fn land(game: &mut Game<'_>, pos: Pos, grid_offset: u32, owned: bool) -> bool {
    let key = column(pos);
    let Ok(mut records) = entries(game, key) else {
        return false;
    };
    let Some(index) = records
        .iter()
        .position(|r| r.controller == pos && r.stroke_kind() == Some(StrokeKind::Piston))
    else {
        return false;
    };
    let record = records.remove(index);
    let mut edits = Vec::new();
    for (local, block) in record.blocks.iter() {
        let p = world_cell(&record, *local, grid_offset);
        let before = state(game, p);
        let after = if owned && p == pos {
            let Some(part) = part(block) else {
                return false;
            };
            let state = if matches!(part, Part::Head { .. }) {
                "retracted"
            } else {
                "extended"
            };
            base_state(game, before, state)
        } else {
            if !game.res.facts().is_air(before) {
                return false;
            }
            game.pack.assets.registry.id(block)
        };
        let Some(after) = after else { return false };
        edits.push((p, before, after));
    }
    let origin = world_cell(&record, [0; 3], grid_offset);
    if !commit_linear_landing(game, key, records, &record, origin, &edits) {
        return false;
    }
    movement_sound(game, pos, false);
    true
}

pub(super) fn break_static_line(game: &mut Game<'_>, pos: Pos) {
    let block = game.native_block(pos);
    if !matches!(block.as_str(), NORMAL | STICKY | POLE | HEAD) {
        return;
    }
    let plan = piston::break_parts(pos, piston::MAX_POLES, |at| {
        use piston::LineCell;
        let Some(direction) = facing(game, at) else {
            return LineCell::Other;
        };
        match game.native_block(at).as_str() {
            POLE => LineCell::Pole(direction.axis()),
            HEAD => LineCell::Head(direction),
            NORMAL | STICKY
                if game.native_block_property(at, "state").as_deref() != Some("moving") =>
            {
                LineCell::Base(direction)
            }
            _ => LineCell::Other,
        }
    });
    for at in plan.remove {
        if game.creative {
            let id = state(game, at);
            let behaviour = game.res.behaviours();
            let replacement = behaviour.legacy_block(behaviour.fluid(id));
            let dim = game.dim.id().to_owned();
            if game.native_set_block(
                &dim,
                at,
                replacement,
                flags::UPDATE_NEIGHBORS | flags::UPDATE_CLIENTS,
            ) {
                game.level_event_at(2001, at, id.0 as i32);
            }
        } else if let Err(error) = game.destroy_block_dropping(at) {
            log::warn!("Create could not remove piston part at {at:?}: {error:?}");
        }
    }
    if let Some(base) = plan.retract {
        game.native_set_block_property(base, "state", "retracted");
        if plan.reset_offset {
            game.native_with_mod_block_entity(base, |entity| write(entity, false, 0.0));
            game.native_block_entity_sync(base);
        }
    }
}

pub(super) fn recover(game: &mut Game<'_>, pos: Pos) {
    let stroke = entries(game, column(pos)).ok().and_then(|records| {
        records
            .into_iter()
            .find(|r| r.controller == pos)
            .and_then(|r| r.stroke)
            .filter(|stroke| stroke.kind == StrokeKind::Piston)
    });
    if let Some(stroke) = stroke
        && land(
            game,
            pos,
            ((stroke.offset + 0.5) as u32).min(stroke.limit),
            false,
        )
    {
        actors::remove(game, pos);
    }
}

pub(super) fn right_click(game: &mut Game<'_>, pos: Pos, face: Pos) -> bool {
    let name = game.native_block(pos);
    if !game.native_on("create")
        || !is_piston(&name)
        || game.keys.contains(&winit::keyboard::KeyCode::ShiftLeft)
        || !game.may_build()
    {
        return false;
    }
    if let Some(held) = game.held() {
        let slime = held.item.as_ref() == "minecraft:slime_ball"
            || game
                .native_server_item_in_tag(held, "c:slime_balls")
                .unwrap_or(false);
        if !slime
            || name != NORMAL
            || facing(game, pos).is_none_or(|direction| direction.vector() != face)
        {
            return false;
        }
        return make_sticky(game, pos);
    }
    game.native_with_mod_block_entity(pos, |entity| {
        entity.nbt.insert(REQUEST.into(), Tag::Byte(1));
    })
    .is_some()
}

pub(super) fn wrench(game: &mut Game<'_>, pos: Pos, face: Direction) -> bool {
    let registry = game.pack.assets.registry;
    let Some(before) = registry.state(state(game, pos)) else {
        return false;
    };
    if before
        .properties
        .get("state")
        .is_none_or(|state| state != "retracted")
    {
        return false;
    }
    super::create_port_interactions::wrench_directional_axis(game, pos, face)
}

fn make_sticky(game: &mut Game<'_>, pos: Pos) -> bool {
    let registry = game.pack.assets.registry;
    let Some(before) = registry.state(state(game, pos)) else {
        return false;
    };
    if before
        .properties
        .get("state")
        .is_none_or(|state| state != "retracted")
    {
        return false;
    }
    let mut sticky = before.clone();
    sticky.name = STICKY.into();
    let Some(sticky) = registry.id(&sticky) else {
        return false;
    };
    let dim = game.dim.id().to_owned();
    if !game.native_set_block(
        &dim,
        pos,
        sticky,
        flags::UPDATE_NEIGHBORS | flags::UPDATE_CLIENTS,
    ) {
        return false;
    }
    if !game.creative {
        game.consume_held();
    }
    super::create_port_kinetic_runtime::invalidate();
    game.with_level(|_, level, _| {
        level.native_play_sound(
            "minecraft:block.slime_block.place",
            pos.map(|value| f64::from(value) + 0.5),
            4,
            0.5,
            1.0,
        )
    });
    true
}

fn write(entity: &mut ModBlockEntity, running: bool, offset: f32) {
    entity
        .nbt
        .insert(RUNNING.into(), Tag::Byte(i8::from(running)));
    entity
        .nbt
        .insert("Offset".into(), Tag::Float(offset.to_bits()));
}

pub(super) fn tick(game: &mut Game<'_>, pos: Pos, entity: &mut ModBlockEntity, rpm: f32) {
    let Some(facing) = facing(game, pos) else {
        return;
    };
    let key = column(pos);
    let Ok(mut records) = entries(game, key) else {
        return;
    };
    let previous = super::create_port::number(&entity.nbt, LAST_SPEED);
    let mode_changed = super::create_port_motor_control::take_linear_mode_change(entity);
    entity
        .nbt
        .insert(LAST_SPEED.into(), Tag::Float(rpm.to_bits()));
    let Some(index) = records.iter().position(|r| r.controller == pos) else {
        let pending = entity.nbt.remove(&REQUEST.into()).is_some();
        if (pending || previous != rpm)
            && rpm != 0.0
            && let Some(initial) = capture(game, pos, facing, rpm)
        {
            write(entity, true, initial as f32);
        }
        return;
    };
    if entity.nbt.get(&RUNNING.into()) != Some(&Tag::Byte(1)) {
        return;
    }
    let record = &mut records[index];
    let Some(stroke) = record
        .stroke
        .filter(|stroke| stroke.kind == StrokeKind::Piston)
    else {
        return;
    };
    let Some(mut actuator) = LinearActuator::resume(
        stroke.initial,
        stroke.limit,
        stroke.offset,
        stroke.waiting,
        None,
    ) else {
        return;
    };
    if mode_changed {
        actuator.mode_changed();
    }
    let mut stalled = actors::stalled(game, pos);
    if rpm != record.rpm && actuator.speed_changed(record.rpm, rpm, stalled, None) {
        actors::remove(game, pos);
        stalled = false;
    }
    // Java returns on Waiting before it consumes AssembleNextTick.
    if !actuator.waiting() && entity.nbt.remove(&REQUEST.into()).is_some() {
        actuator.request_refresh();
    }
    let mode = match super::create_port::integer(&entity.nbt, "ScrollValue") {
        1 => Mode::PlaceReturned,
        2 => Mode::NeverPlace,
        _ => Mode::Place,
    };
    let action = actuator.tick(
        rpm,
        piston::directional_speed(rpm, facing),
        mode,
        stalled,
        |motion| collides(game, record, motion, |_| false),
    );
    let previous = record.clone();
    if let Action::Place {
        grid_offset,
        retry_extension,
    } = action
    {
        if land(game, pos, grid_offset, true) {
            write(entity, false, grid_offset as f32);
            let mut landed = previous.clone();
            landed.stroke = Some(Stroke {
                offset: grid_offset as f32,
                previous: stroke.offset,
                ..stroke
            });
            actors::tick(game, &previous, &landed);
            actors::remove(game, pos);
            if retry_extension {
                entity.nbt.insert(REQUEST.into(), Tag::Byte(1));
            }
        }
        return;
    }
    record.stroke = Some(Stroke {
        offset: actuator.offset(),
        previous: stroke.offset,
        waiting: actuator.waiting(),
        ..stroke
    });
    record.rpm = rpm;
    record.stalled = stalled;
    let current = record.clone();
    if set_records(game, key, records).is_ok() {
        write(entity, true, actuator.offset());
        actors::tick(game, &previous, &current);
    }
}
