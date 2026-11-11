// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use super::{
    Game,
    create_port_contraption::{
        Capture, MountedCapture, column, commit_linear_capture, commit_linear_landing, entries,
        movement_sound, resident, set_records, state,
    },
    create_port_contraption_actors as actors,
    create_port_piston::collides_at,
    create_port_super_glue as glue,
    native_block_entity_draw::BlockEntityDraw,
    native_world_draw::NativeWorldDraw,
};
use crate::containers::{BlockEntity, ModBlockEntity};
use create_engine::{
    contraption::{
        CaptureView, Cell as PayloadCell,
        linear::{Action, LinearActuator, Mode},
        pulley::{self, Cell, Drive, LandingCell, Layout, Part, Probe, RopeEdit, Segment},
    },
    kinetics::Pos,
    placement::Direction,
};
use glam::DVec3;
use horizon_client_render::create_contraption_scene::{
    MAX_BLOCKS, MAX_RECORDS, Record, Stroke, StrokeKind, read,
};
use horizon_world::{chunk::BlockState, nbt::Tag, registry::BlockStateId};
use std::collections::BTreeSet;

pub(super) const BLOCK: &str = "create:rope_pulley";
const ROPE: &str = "create:rope";
const MAGNET: &str = "create:pulley_magnet";
const RUNNING: &str = "Running";
const LAST_SPEED: &str = "create_horizon:PulleyPower";
const REQUEST: &str = "AssembleNextTick";
const COIL_MODEL: &str = "create:block/rope_pulley/rope_coil";
const COIL_SPRITE: &str = "create:block/rope_pulley_coil";
const COIL_SCROLL_SPRITE: &str = "create:gui/scrolling/rope_pulley_coil_scroll";

fn segment(block: &BlockState) -> Option<Segment> {
    let part = match block.name.as_str() {
        ROPE => Part::Rope,
        MAGNET => Part::Magnet,
        _ => return None,
    };
    let waterlogged = match block.properties.get("waterlogged")?.as_str() {
        "true" => true,
        "false" => false,
        _ => return None,
    };
    Some(Segment { part, waterlogged })
}

fn cell(game: &Game<'_>, position: Pos) -> Cell {
    if !game.world.loaded(position[0], position[2]) {
        return Cell::Unloaded;
    }
    let Some(block) = game.pack.assets.registry.state(state(game, position)) else {
        return Cell::Unloaded;
    };
    if block.name == BLOCK {
        Cell::Pulley
    } else {
        segment(block).map_or(Cell::Other, Cell::Rope)
    }
}

fn cargo_cell(controller: Pos, local: Pos, offset: u32) -> Option<Pos> {
    let x = controller[0].checked_add(local[0])?;
    let y = i32::try_from(i64::from(controller[1]) - 1 - i64::from(offset) + i64::from(local[1]))
        .ok()?;
    let z = controller[2].checked_add(local[2])?;
    Some([x, y, z])
}

fn collides(game: &Game<'_>, record: &Record, probe: Probe, owned: impl Fn(Pos) -> bool) -> bool {
    collides_at(game, record, probe.anchor, probe.direction.vector(), |p| {
        owned(p)
            || (probe.direction == Direction::Up
                && p == probe.anchor
                && game.native_block(p) == MAGNET)
    })
}

fn assemble(game: &mut Game<'_>, controller: Pos, rpm: f32) -> Option<u32> {
    let key = column(controller);
    let records = entries(game, key).ok()?;
    if records.len() >= MAX_RECORDS || records.iter().any(|r| r.controller == controller) {
        return None;
    }
    let (min_y, _) = game.native_world_height();
    let layout = Layout::scan(controller, min_y, pulley::DEFAULT_MAX_ROPE_LENGTH, |p| {
        cell(game, p)
    })
    .ok()?;
    let origin = cargo_cell(controller, [0; 3], layout.initial_offset)?;
    let volumes = glue::read(game, key).ok()?;
    let assembly = layout
        .capture(&MountedCapture::for_linear(game, &volumes), MAX_BLOCKS)
        .ok()?;
    let blocks = assembly.blocks().to_vec();
    let registry = game.pack.assets.registry;
    let mut edits = Vec::new();
    for &(position, rope) in &layout.remove {
        if rope.waterlogged {
            return None;
        }
        edits.push((position, state(game, position), game.world.air));
    }
    for (local, block) in &blocks {
        let position = cargo_cell(controller, *local, layout.initial_offset)?;
        if column(position) != key || local.iter().any(|value| value.unsigned_abs() > 15) {
            return None;
        }
        edits.push((position, registry.id(block)?, game.world.air));
    }
    let anchor = cargo_cell(controller, [0; 3], 0)?;
    let record = Record {
        controller,
        anchor,
        axis: 1,
        angle: 0.0,
        previous_angle: 0.0,
        rpm,
        stalled: false,
        return_home: false,
        clock_hand: None,
        blocks: blocks.into(),
        stroke: Some(Stroke {
            kind: StrokeKind::RopePulley,
            initial: layout.initial_offset,
            limit: layout.extension_range,
            offset: layout.initial_offset as f32,
            previous: layout.initial_offset as f32,
            waiting: false,
        }),
    };
    let owned: BTreeSet<_> = edits.iter().map(|&(position, _, _)| position).collect();
    let probe = layout.assembly_probe(rpm)?;
    if collides(game, &record, probe, |p| owned.contains(&p)) {
        return None;
    }
    layout.start(rpm, true, !record.blocks.is_empty())?;
    let has_payload = !record.blocks.is_empty();
    if !commit_linear_capture(game, key, records, record, origin, &edits) {
        return None;
    }
    if has_payload {
        movement_sound(game, controller, true);
    }
    Some(layout.initial_offset)
}

fn dry_air(game: &Game<'_>, position: Pos) -> bool {
    resident(game, position) && game.res.facts().is_air(state(game, position))
}

fn rope_state(game: &Game<'_>, rope: Segment) -> Option<BlockStateId> {
    if rope.waterlogged {
        return None;
    }
    let name = match rope.part {
        Part::Rope => ROPE,
        Part::Magnet => MAGNET,
    };
    game.pack.assets.registry.default_state(name)
}

fn land(game: &mut Game<'_>, controller: Pos, offset: u32, rehang: bool) -> Option<()> {
    let key = column(controller);
    let mut records = entries(game, key).ok()?;
    let index = records.iter().position(|r| {
        r.controller == controller && r.stroke_kind() == Some(StrokeKind::RopePulley)
    })?;
    let record = records.remove(index);
    let registry = game.pack.assets.registry;
    let mut edits = Vec::new();
    let mut positions = BTreeSet::new();
    let rope = pulley::plan_rope_landing(controller, offset, !rehang, |position| {
        // Preserve any world block that appeared while the rope was animated.
        if dry_air(game, position) {
            LandingCell::Present {
                breakable: true,
                collision_empty: true,
                source_water: false,
            }
        } else {
            LandingCell::OutsideWorld
        }
    })
    .ok()?;
    for edit in rope {
        let RopeEdit::Place { position, segment } = edit else {
            continue;
        };
        if !positions.insert(position) {
            return None;
        }
        edits.push((position, state(game, position), rope_state(game, segment)?));
    }
    for (local, block) in record.blocks.iter() {
        let position = cargo_cell(controller, *local, offset)?;
        if !positions.insert(position) || !dry_air(game, position) {
            return None;
        }
        edits.push((position, state(game, position), registry.id(block)?));
    }
    let origin = cargo_cell(controller, [0; 3], offset)?;
    if !commit_linear_landing(game, key, records, &record, origin, &edits) {
        return None;
    }
    if !record.blocks.is_empty() {
        movement_sound(game, controller, false);
    }
    Some(())
}

pub(super) fn recover(game: &mut Game<'_>, pos: Pos) {
    let stroke = entries(game, column(pos)).ok().and_then(|records| {
        records
            .into_iter()
            .find(|r| r.controller == pos && r.stroke_kind() == Some(StrokeKind::RopePulley))?
            .stroke
    });
    if let Some(stroke) = stroke
        && land(
            game,
            pos,
            ((stroke.offset + 0.5) as u32).min(stroke.limit),
            false,
        )
        .is_some()
    {
        actors::remove(game, pos);
    }
}

pub(super) fn right_click(game: &mut Game<'_>, pos: Pos) -> bool {
    game.native_on("create")
        && game.native_block(pos) == BLOCK
        && game.held().is_none()
        && !game.keys.contains(&winit::keyboard::KeyCode::ShiftLeft)
        && game.may_build()
        && game
            .native_with_mod_block_entity(pos, |entity| {
                entity.nbt.insert(REQUEST.into(), Tag::Byte(1));
            })
            .is_some()
}

/// Player destruction follows the original contiguous physical line. Runtime
/// rope removals are already part of a structure commit and do not call this.
pub(super) fn break_line(game: &mut Game<'_>, position: Pos) {
    let block = game.native_block(position);
    if !matches!(block.as_str(), BLOCK | ROPE | MAGNET) {
        return;
    }
    let removing_pulley = block == BLOCK;
    let broken = if removing_pulley {
        let Some(y) = position[1].checked_sub(1) else {
            return;
        };
        [position[0], y, position[2]]
    } else {
        position
    };
    if !matches!(
        cell(game, broken),
        Cell::Rope(Segment {
            waterlogged: false,
            ..
        })
    ) {
        return;
    }
    let Ok(mut line) =
        pulley::plan_rope_break(broken, pulley::DEFAULT_MAX_ROPE_LENGTH as usize, |p| {
            cell(game, p)
        })
    else {
        return;
    };
    if line.segments.iter().any(|&p| {
        !matches!(
            cell(game, p),
            Cell::Rope(Segment {
                waterlogged: false,
                ..
            })
        )
    }) {
        return;
    }
    if removing_pulley {
        line.segments.insert(0, broken);
    } else if let Some(controller) = line.reset_controller {
        game.native_with_mod_block_entity(controller, |entity| {
            if entity.nbt.get(&RUNNING.into()) != Some(&Tag::Byte(1)) {
                write(entity, false, 0, 0.0, false);
            }
        });
        game.native_block_entity_sync(controller);
    }
    for segment in line.segments {
        if let Err(error) = game.destroy_block_dropping(segment) {
            log::warn!("Create could not remove pulley rope at {segment:?}: {error:?}");
        }
    }
}

fn write(entity: &mut ModBlockEntity, running: bool, initial: u32, offset: f32, waiting: bool) {
    entity
        .nbt
        .insert(RUNNING.into(), Tag::Byte(i8::from(running)));
    entity
        .nbt
        .insert("Waiting".into(), Tag::Byte(i8::from(waiting)));
    entity
        .nbt
        .insert("InitialOffset".into(), Tag::Int(initial as i32));
    entity
        .nbt
        .insert("Offset".into(), Tag::Float(offset.to_bits()));
}

pub(super) fn tick(game: &mut Game<'_>, pos: Pos, entity: &mut ModBlockEntity, rpm: f32) -> bool {
    let key = column(pos);
    let Ok(mut records) = entries(game, key) else {
        return false;
    };
    let last = super::create_port::number(&entity.nbt, LAST_SPEED);
    let mode_changed = super::create_port_motor_control::take_linear_mode_change(entity);
    entity
        .nbt
        .insert(LAST_SPEED.into(), Tag::Float(rpm.to_bits()));
    let Some(record) = records.iter_mut().find(|r| r.controller == pos) else {
        let pending = entity.nbt.remove(&REQUEST.into()).is_some();
        if (pending || last != rpm)
            && rpm != 0.0
            && let Some(initial) = assemble(game, pos, rpm)
        {
            write(entity, true, initial, initial as f32, false);
            return true;
        }
        return false;
    };
    if entity.nbt.get(&RUNNING.into()) != Some(&Tag::Byte(1)) {
        return false;
    }
    let Some(stroke) = record
        .stroke
        .filter(|stroke| stroke.kind == StrokeKind::RopePulley)
    else {
        return false;
    };
    let Some(actuator) = LinearActuator::resume(
        stroke.initial,
        stroke.limit,
        stroke.offset,
        stroke.waiting,
        None,
    ) else {
        return false;
    };
    let mut drive = Drive {
        actuator,
        has_payload: !record.blocks.is_empty(),
    };
    if mode_changed {
        drive.actuator.mode_changed();
    }
    let mut stalled = actors::stalled(game, pos);
    if rpm != record.rpm {
        if drive.actuator.speed_changed(record.rpm, rpm, stalled, None) {
            actors::remove(game, pos);
            stalled = false;
        }
    }
    if !drive.actuator.waiting() && entity.nbt.remove(&REQUEST.into()).is_some() {
        drive.actuator.request_refresh();
    }
    let mode = match super::create_port::integer(&entity.nbt, "ScrollValue") {
        1 => Mode::PlaceReturned,
        2 => Mode::NeverPlace,
        _ => Mode::Place,
    };
    let action = drive.tick(pos, rpm, mode, stalled,
        |probe| collides(game, record, probe, |_| false),
        |position| matches!(Capture(game).inspect(position), PayloadCell::Block(rules) if !rules.brittle),
    );
    if let Action::Place {
        grid_offset,
        retry_extension,
    } = action
    {
        if land(game, pos, grid_offset, true).is_some() {
            write(entity, false, 0, grid_offset as f32, false);
            actors::remove(game, pos);
            if retry_extension {
                entity.nbt.insert(REQUEST.into(), Tag::Byte(1));
            }
            return true;
        }
        return false;
    }
    let previous = record.clone();
    record.stroke = Some(Stroke {
        offset: drive.actuator.offset(),
        previous: stroke.offset,
        waiting: drive.actuator.waiting(),
        ..stroke
    });
    record.rpm = rpm;
    record.stalled = stalled;
    let current = record.clone();
    if set_records(game, key, records).is_ok() {
        write(
            entity,
            true,
            stroke.initial,
            drive.actuator.offset(),
            drive.actuator.waiting(),
        );
        actors::tick(game, &previous, &current);
        return stroke.waiting != drive.actuator.waiting();
    }
    false
}

fn coil_scroll(offset: f32, strip_height: f32) -> f32 {
    // RopePulleyVisual uses ScrollInstance's half-height scale with offsetV=-offset.
    let winding = -offset;
    (winding - winding.floor()) * (strip_height * 0.5)
}

fn draw_coil(game: &Game<'_>, pos: Pos, draw: &mut BlockEntityDraw, offset: f32) {
    draw.push();
    if game.native_block_property(pos, "axis").as_deref() == Some("x") {
        draw.rotate_about([0.0, 1.0, 0.0], 90.0, [0.5; 3]);
    }
    let start = draw.vertices_mut().len();
    game.native_draw_model(draw, COIL_MODEL, 0xFFFFFF);
    let sprites = &game.gui.atlas.sprites;
    if offset.is_finite()
        && let (Some(original), Some(strip)) =
            (sprites.get(COIL_SPRITE), sprites.get(COIL_SCROLL_SPRITE))
    {
        let scroll = coil_scroll(offset, strip.v1 - strip.v0);
        // Shift the original atlas UVs without rebaking the rotated model faces.
        for quad in draw.vertices_mut()[start..].chunks_exact_mut(4) {
            if quad.iter().all(|vertex| {
                (original.u0..=original.u1).contains(&vertex.uv[0])
                    && (original.v0..=original.v1).contains(&vertex.uv[1])
            }) {
                for vertex in quad {
                    vertex.uv[0] = strip.u0 + (vertex.uv[0] - original.u0);
                    vertex.uv[1] = strip.v0 + (vertex.uv[1] - original.v0) + scroll;
                }
            }
        }
    }
    draw.pop();
}

fn draw_at(
    game: &Game<'_>,
    draw: &mut NativeWorldDraw,
    [x, y, z]: Pos,
    distance: f32,
    render: impl FnOnce(&mut BlockEntityDraw),
) {
    use horizon_client::block_entity_render::vertex_light;
    let position = [
        f64::from(x),
        f64::from(y) - f64::from(distance),
        f64::from(z),
    ];
    if DVec3::from_array(position).distance_squared(DVec3::from_array(draw.camera)) > 64.0 * 64.0 {
        return;
    }
    let light = draw.light;
    draw.light = vertex_light(game.world.light(x, y.saturating_sub(distance as i32), z));
    draw.push();
    draw.translate_world(position);
    render(draw);
    draw.pop();
    draw.light = light;
}

pub(super) fn draw_line(
    game: &Game<'_>,
    draw: &mut NativeWorldDraw,
    record: &Record,
    payload_offset: f32,
) {
    let Some(stroke) = record.stroke.filter(|s| s.kind == StrokeKind::RopePulley) else {
        return;
    };
    let offset = if record.blocks.is_empty() {
        (stroke.offset + (draw.partial - 0.5) * pulley::directional_speed(record.rpm))
            .clamp(0.0, stroke.limit as f32)
    } else {
        payload_offset
    };
    let [x, y, z] = record.controller;
    if super::create_port::original_assets()
        && matches!(game.world.block_entities.get(&(x, y, z)), Some(BlockEntity::Mod(entity))
            if entity.nbt.get(&RUNNING.into()) == Some(&Tag::Byte(1)))
    {
        draw_at(game, draw, record.controller, 0.0, |draw| {
            draw_coil(game, record.controller, draw, offset);
        });
    }
    let mut draw_part = |distance: f32, model: &str| {
        draw_at(game, draw, record.controller, distance, |draw| {
            game.native_draw_model(draw, model, 0xFFFFFF);
        });
    };
    draw_part(
        offset,
        if offset > 0.25 {
            "create:block/rope_pulley/pulley_magnet"
        } else {
            "create:block/rope_pulley/rope_half_magnet"
        },
    );
    let fraction = offset.fract();
    if offset > 0.75 && !(0.25..=0.75).contains(&fraction) {
        draw_part(
            if fraction > 0.75 {
                fraction - 1.0
            } else {
                fraction
            },
            "create:block/rope_pulley/rope_half",
        );
    }
    for segment in 0..(offset - 1.25).ceil().max(0.0) as u32 {
        draw_part(
            offset - segment as f32 - 1.0,
            "create:block/rope_pulley/rope",
        );
    }
}

pub(super) fn draw_controller(
    game: &Game<'_>,
    pos: Pos,
    entity: &ModBlockEntity,
    draw: &mut BlockEntityDraw,
) {
    let running = entity.nbt.get(&RUNNING.into()) == Some(&Tag::Byte(1));
    let offset = super::create_port::number(&entity.nbt, "Offset");
    let [x, z] = column(pos);
    let draws_with_line = running
        && super::create_port::original_assets()
        && game.world.chunks.get(&(x, z)).is_some_and(|chunk| {
            read(chunk).is_ok_and(|records| {
                records.iter().any(|record| {
                    record.controller == pos && record.stroke_kind() == Some(StrokeKind::RopePulley)
                })
            })
        });
    if !draws_with_line {
        draw_coil(game, pos, draw, offset);
    }
    if !running {
        if offset == 0.0 {
            game.native_draw_model(draw, "create:block/rope_pulley/rope_half_magnet", 0xFFFFFF);
        } else if offset > 0.75 && !(0.25..=0.75).contains(&offset.fract()) {
            draw.push();
            let fraction = offset.fract();
            let distance = if fraction > 0.75 {
                fraction - 1.0
            } else {
                fraction
            };
            draw.translate([0.0, -distance, 0.0]);
            game.native_draw_model(draw, "create:block/rope_pulley/rope_half", 0xFFFFFF);
            draw.pop();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::coil_scroll;

    #[test]
    fn flywheel_coil_scroll_wraps_in_half_the_strip() {
        for (offset, rows) in [
            (0.0, 0.0),
            (0.25, 12.0),
            (0.5, 8.0),
            (0.75, 4.0),
            (1.0, 0.0),
        ] {
            assert_eq!(coil_scroll(offset, 32.0), rows);
            assert_eq!(coil_scroll(offset + 127.0, 32.0), rows);
        }
        assert_eq!(coil_scroll(-0.25, 32.0), 4.0);
    }
}
