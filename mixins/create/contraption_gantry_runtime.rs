// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use super::{
    Game, GameLevel,
    create_port_contraption::{
        MountedCapture, column, commit_linear_capture, commit_linear_landing, entries, facing,
        movement_sound, resident, set_records, state,
    },
    create_port_contraption_actors as actors,
    create_port_piston::collides_at,
    create_port_super_glue as glue,
};
use crate::containers::{BlockEntity, ModBlockEntity};
use create_engine::{
    contraption::{
        Assembly,
        gantry::{Action, GantryMotion, Part, Shaft, pinion_axis},
    },
    kinetics::{Axis, Pos},
    placement::Direction,
};
use horizon_client_render::create_contraption_scene::{
    MAX_BLOCKS, MAX_RECORDS, Record, Stroke, StrokeKind, read,
};
use horizon_world::{
    attachments::AttachmentType,
    level::{PlacementContext, flags},
    nbt::Tag,
    registry::BlockStateId,
};
use std::collections::{BTreeMap, BTreeSet};

pub(super) const SHAFT: &str = "create:gantry_shaft";
pub(super) const CARRIAGE: &str = "create:gantry_carriage";
const PINION: &str = "create:gantry_pinion";
const PROBE: &str = "create_horizon:GantryAssemblyProbe";
const MAX_RAILS: usize = 65;

const AGES: AttachmentType<BTreeMap<Pos, u32>> = AttachmentType {
    namespace: "create",
    name: "gantry_entity_ages",
    default: BTreeMap::new,
    codec: None,
    copy_on_death: false,
    sync: false,
};

pub(super) fn entity_id(block: &str) -> &str {
    if block == CARRIAGE { PINION } else { block }
}

pub(super) fn placement(
    game: &GameLevel<'_>,
    state: BlockStateId,
    block: &str,
    ctx: &PlacementContext,
    face: Direction,
) -> Option<BlockStateId> {
    let pos = [ctx.pos.x, ctx.pos.y, ctx.pos.z];
    let rail_at = |[x, y, z]: Pos| {
        let rail = game.registry.state(game.world.block(x, y, z))?;
        if rail.name != SHAFT {
            return None;
        }
        let facing = rail.properties.get("facing")?;
        Direction::ALL.into_iter().find(|d| d.name() == facing)
    };
    if block == CARRIAGE {
        let shaft = rail_at(step(pos, face.opposite()))?;
        let axis = pinion_axis(face, shaft)?;
        let first = match face.axis() {
            Axis::X => axis == Axis::Y,
            Axis::Y | Axis::Z => axis == Axis::X,
        };
        let state = game.native_state_with_property(state, "facing", face.name())?;
        return game.native_state_with_property(
            state,
            "axis_along_first",
            if first { "true" } else { "false" },
        );
    }
    let look = super::create_port::nearest(ctx.yaw, ctx.pitch);
    let preferred =
        create_engine::placement::preferred(super::create_port_placement::level_ports(game, pos));
    let facing = if ctx.sneaking {
        look
    } else {
        preferred.unwrap_or(look).opposite()
    };
    let neighbor =
        rail_at(step(pos, facing.opposite())).or_else(|| rail_at(step(pos, face.opposite())));
    let facing = neighbor
        .filter(|neighbor| neighbor.axis() == facing.axis())
        .map_or(facing, |neighbor| {
            if ctx.sneaking {
                neighbor.opposite()
            } else {
                neighbor
            }
        });
    game.native_state_with_property(state, "facing", facing.name())
}

fn step(pos: Pos, direction: Direction) -> Pos {
    let normal = direction.vector();
    std::array::from_fn(|i| pos[i] + normal[i])
}

fn shaft_facing(game: &Game<'_>, pos: Pos) -> Option<Direction> {
    (game.native_block(pos) == SHAFT)
        .then(|| facing(game, pos))
        .flatten()
}

fn shaft(game: &Game<'_>, pos: Pos) -> Option<Shaft> {
    let facing = shaft_facing(game, pos)?;
    let part = match game.native_block_property(pos, "part")?.as_str() {
        "start" => Part::Start,
        "middle" => Part::Middle,
        "end" => Part::End,
        "single" => Part::Single,
        _ => return None,
    };
    let BlockEntity::Mod(entity) = game.world.block_entities.get(&(pos[0], pos[1], pos[2]))? else {
        return None;
    };
    Some(Shaft {
        facing,
        part,
        powered: game.native_block_property(pos, "powered").as_deref() == Some("true"),
        rpm: super::create_port::running_speed(game, &entity.nbt),
    })
}

fn rail(game: &Game<'_>, seed: Pos, facing: Direction) -> Option<Vec<Pos>> {
    let mut rail = vec![seed];
    for direction in [facing, facing.opposite()] {
        let mut p = step(seed, direction);
        while resident(game, p) && shaft_facing(game, p) == Some(facing) {
            if rail.len() == MAX_RAILS {
                return None;
            }
            rail.push(p);
            p = step(p, direction);
        }
    }
    rail.sort_unstable_by_key(|p| p[facing.axis().index()]);
    Some(rail)
}

fn rail_state(game: &mut Game<'_>) {
    let shafts: Vec<Pos> = game
        .world
        .block_entities
        .iter()
        .filter_map(|(&(x, y, z), entity)| {
            matches!(entity, BlockEntity::Mod(entity) if entity.id == SHAFT).then_some([x, y, z])
        })
        .collect();
    let dimension = game.dim.id().to_owned();
    let mut visited = BTreeSet::new();
    for seed in shafts {
        if visited.contains(&seed) {
            continue;
        }
        let Some(facing) = shaft_facing(game, seed) else {
            continue;
        };
        let Some(mut rail) = rail(game, seed, facing) else {
            continue;
        };
        if facing.vector()[facing.axis().index()] < 0 {
            rail.reverse();
        }
        let powered = rail
            .iter()
            .any(|&p| game.native_neighbor_signal(&dimension, p) > 0);
        for (index, p) in rail.iter().copied().enumerate() {
            visited.insert(p);
            let part = match (index != 0, index + 1 != rail.len()) {
                (true, true) => "middle",
                (false, true) => "start",
                (true, false) => "end",
                (false, false) => "single",
            };
            let powered = if powered { "true" } else { "false" };
            for (key, value) in [("part", part), ("powered", powered)] {
                if game.native_block_property(p, key).as_deref() != Some(value) {
                    game.native_set_block_property_with(p, key, value, flags::UPDATE_CLIENTS);
                }
            }
        }
    }
}

fn capture(
    game: &mut Game<'_>,
    pos: Pos,
    carriage: Direction,
    shaft: Shaft,
    movement: Direction,
) -> bool {
    let key = column(pos);
    let Ok(records) = entries(game, key) else {
        return false;
    };
    if records.len() >= MAX_RECORDS || records.iter().any(|record| record.controller == pos) {
        return false;
    }
    let support = step(pos, carriage.opposite());
    let Some(rail) = rail(game, support, shaft.facing) else {
        return false;
    };
    let axis = shaft.facing.axis().index();
    if rail.len() < 2
        || rail
            .iter()
            .any(|&p| column(p) != key || column(step(p, carriage)) != key)
    {
        return false;
    }
    let anchor = step(rail[0], carriage);
    let end = step(rail[rail.len() - 1], carriage);
    let initial = pos[axis].abs_diff(anchor[axis]);
    let limit = end[axis].abs_diff(anchor[axis]);
    let Ok(stationary_glue) = glue::read(game, key) else {
        return false;
    };
    // GantryContraption.assemble leaves the force direction unset even when
    // the rail provides a direction for the terrain collision check below.
    let Ok(payload) = Assembly::capture_from(
        &MountedCapture::for_linear(game, &stationary_glue),
        pos,
        [step(pos, carriage)],
        |p| p == pos || rail.contains(&p),
        None,
        MAX_BLOCKS - 1,
    ) else {
        return false;
    };
    let registry = game.pack.assets.registry;
    let Some(carriage_state) = registry.state(state(game, pos)) else {
        return false;
    };
    let mut blocks = payload.blocks().to_vec();
    blocks.push(([0; 3], carriage_state.clone()));
    let cell = |origin: Pos, local: Pos| -> Pos { std::array::from_fn(|i| origin[i] + local[i]) };
    if blocks.iter().any(|&(local, _)| {
        [anchor, end].into_iter().any(|origin| {
            let p = cell(origin, local);
            column(p) != key || !resident(game, p)
        })
    }) {
        return false;
    }
    let edits: Vec<_> = blocks
        .iter()
        .map(|&(local, _)| {
            let p = cell(pos, local);
            (p, state(game, p), game.world.air)
        })
        .collect();
    let record = Record {
        controller: pos,
        anchor,
        axis,
        angle: 0.0,
        previous_angle: 0.0,
        rpm: shaft.rpm,
        stalled: false,
        return_home: false,
        clock_hand: None,
        stroke: Some(Stroke {
            kind: StrokeKind::Gantry,
            initial,
            limit,
            offset: initial as f32,
            previous: initial as f32,
            waiting: false,
        }),
        blocks: blocks.into(),
    };
    if collides_at(game, &record, step(pos, movement), movement.vector(), |p| {
        edits.iter().any(|&(from, _, _)| p == from)
    }) {
        return false;
    }
    if !commit_linear_capture(game, key, records, record, pos, &edits) {
        return false;
    }
    movement_sound(game, pos, true);
    true
}

pub(super) fn tick_carriage(game: &mut Game<'_>, pos: Pos, entity: &mut ModBlockEntity) {
    let candidate = facing(game, pos).and_then(|carriage| {
        let shaft = shaft(game, step(pos, carriage.opposite()))?;
        let movement = shaft.assembly_direction(carriage)?;
        Some((carriage, shaft, movement))
    });
    let Some((carriage, shaft, movement)) = candidate else {
        entity.nbt.remove(&PROBE.into());
        return;
    };
    let probe = Tag::Long(
        i64::from(shaft.rpm.to_bits())
            | ((shaft.part as i64) << 32)
            | ((shaft.facing as i64) << 40),
    );
    if entity.nbt.get(&PROBE.into()) != Some(&probe) {
        entity.nbt.insert(PROBE.into(), probe);
        capture(game, pos, carriage, shaft, movement);
    }
}

pub(super) fn right_click(game: &mut Game<'_>, pos: Pos) -> bool {
    if !game.native_on("create")
        || game.native_block(pos) != CARRIAGE
        || game.held().is_some()
        || game.keys.contains(&winit::keyboard::KeyCode::ShiftLeft)
        || !game.may_build()
    {
        return false;
    }
    game.native_with_mod_block_entity(pos, |entity| entity.nbt.remove(&PROBE.into()))
        .is_some()
}

fn land(game: &mut Game<'_>, key: [i32; 2], mut records: Vec<Record>, index: usize, origin: Pos) {
    let record = records.remove(index);
    let registry = game.pack.assets.registry;
    let edits = record
        .blocks
        .iter()
        .map(|(local, block)| {
            let p = std::array::from_fn(|i| origin[i] + local[i]);
            let before = state(game, p);
            if column(p) != key || !resident(game, p) || !game.res.facts().is_air(before) {
                return None;
            }
            Some((p, before, registry.id(block)?))
        })
        .collect::<Option<Vec<_>>>();
    if let Some(edits) = edits
        && commit_linear_landing(game, key, records.clone(), &record, origin, &edits)
    {
        actors::remove(game, record.controller);
        movement_sound(game, origin, false);
    } else if let Some(stroke) = record.stroke
        && !stroke.waiting
    {
        // The attachment remains the only owner until every target is safe.
        let mut parked = record;
        parked.stroke = Some(Stroke {
            waiting: true,
            previous: stroke.offset,
            ..stroke
        });
        records.insert(index, parked);
        let _ = set_records(game, key, records);
    }
}

fn tick_record(game: &mut Game<'_>, owner: Pos, age: u32) {
    let key = column(owner);
    let Ok(mut records) = entries(game, key) else {
        return;
    };
    let Some(index) = records.iter().position(|record| {
        record.controller == owner && record.stroke_kind() == Some(StrokeKind::Gantry)
    }) else {
        return;
    };
    let record = &records[index];
    let Some(stroke) = record.stroke else { return };
    let origin = record.origin_at(1.0);
    let centered = origin.map(|p| (p + 0.5).floor() as i32);
    if stroke.waiting {
        land(game, key, records, index, centered);
        return;
    }
    let Some(carriage) = record
        .blocks
        .iter()
        .find(|(local, _)| *local == [0; 3])
        .and_then(|(_, block)| block.properties.get("facing"))
        .and_then(|facing| Direction::ALL.into_iter().find(|d| d.name() == facing))
    else {
        return;
    };
    if !resident(game, step(centered, carriage.opposite())) {
        return;
    }
    let previous_axis_motion = (-record.rpm / 512.0).clamp(-0.49, 0.49);
    let Some(mut motion) = GantryMotion::resume(carriage, origin, previous_axis_motion, None)
    else {
        return;
    };
    let axis = record.axis;
    let stalled = actors::stalled(game, owner);
    let action = motion.tick(
        age,
        stalled,
        |p| shaft(game, p).filter(|shaft| shaft.facing.axis().index() == axis),
        |from, movement| {
            let to: [f64; 3] = std::array::from_fn(|i| from[i] + movement[i]);
            let offset = to[axis] - f64::from(record.anchor[axis]);
            if !(0.0..=f64::from(stroke.limit)).contains(&offset) {
                return true;
            }
            let direction = movement.map(|d| {
                if d > 0.0 {
                    1
                } else if d < 0.0 {
                    -1
                } else {
                    0
                }
            });
            // Gantry checks its leading terrain slice before moving the entity.
            let leading = std::array::from_fn(|i| from[i].floor() as i32 + direction[i].max(0));
            collides_at(game, record, leading, direction, |_| false)
        },
    );
    match action {
        Action::Place { anchor } => land(game, key, records, index, anchor),
        Action::Active { stop_actors, .. } => {
            let previous = record.clone();
            let record = &mut records[index];
            record.rpm = -motion.axis_motion() * 512.0;
            record.stalled = stalled;
            record.stroke = Some(Stroke {
                offset: (motion.anchor()[axis] - f64::from(record.anchor[axis])) as f32,
                previous: stroke.offset,
                ..stroke
            });
            let current = record.clone();
            if set_records(game, key, records).is_ok() {
                if stop_actors {
                    actors::remove(game, owner);
                }
                actors::tick(game, &previous, &current);
            }
        }
    }
}

pub(super) fn maintenance(game: &mut Game<'_>) {
    if game.options.execution_role.is_client() || !game.native_on("create") {
        return;
    }
    rail_state(game);
    let owners: BTreeSet<_> = game
        .world
        .chunks
        .values()
        .filter_map(|chunk| read(chunk).ok())
        .flat_map(|records| {
            records
                .iter()
                .filter_map(|record| {
                    (record.stroke_kind() == Some(StrokeKind::Gantry)).then_some(record.controller)
                })
                .collect::<Vec<_>>()
        })
        .collect();
    if owners.is_empty() {
        let _ = game.world.attachments.remove(&AGES);
        return;
    }
    let Ok(mut ages) = game.world.attachments.get(&AGES) else {
        return;
    };
    ages.retain(|owner, _| owners.contains(owner));
    for owner in owners {
        let age = ages.entry(owner).or_default();
        *age = age.saturating_add(1);
        tick_record(game, owner, *age);
    }
    let _ = game.world.attachments.set(&AGES, ages);
}
