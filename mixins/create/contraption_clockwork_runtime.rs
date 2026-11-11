// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use super::{Dim, Game, create_port_contraption as shared};
use crate::containers::ModBlockEntity;
use create_engine::{
    contraption::{
        Rotation,
        clockwork::{self, Angles, ClockTime, Clockwork, Mode, TickAction},
    },
    kinetics::{Axis, Pos},
    placement::Direction,
};
use horizon_client_render::create_contraption_scene::{ClockHand, MAX_BLOCKS, MAX_RECORDS, Record};
use horizon_world::nbt::Tag;
use std::collections::BTreeSet;

pub(super) const BLOCK: &str = "create:clockwork_bearing";
const RUNNING: &str = "Running";
const REQUEST: &str = "create_horizon:ClockworkAssembly";
const POWER: &str = "create_horizon:ClockworkPower";
const EFFECTIVE: &str = "create_horizon:ClockworkEffectivePower";

fn write(entity: &mut ModBlockEntity, running: bool, angles: Angles) {
    entity
        .nbt
        .insert(RUNNING.into(), Tag::Byte(i8::from(running)));
    entity
        .nbt
        .insert("HourAngle".into(), Tag::Float(angles.hour.to_bits()));
    entity
        .nbt
        .insert("MinuteAngle".into(), Tag::Float(angles.minute.to_bits()));
}

fn hand_angle(records: &[Record], pos: Pos, hand: ClockHand) -> Option<f32> {
    records
        .iter()
        .find(|record| record.controller == pos && record.clock_hand == Some(hand))
        .map(|record| record.angle)
}

fn assemble(game: &mut Game<'_>, controller: Pos, facing: Direction) -> Option<()> {
    let key = shared::column(controller);
    let mut records = shared::entries(game, key).ok()?;
    if records.iter().any(|record| record.controller == controller) {
        return None;
    }
    let hands =
        clockwork::capture(&shared::Capture(game), controller, facing, MAX_BLOCKS).ok()??;
    let count = 1 + usize::from(hands.minute.is_some());
    if records.len() + count > MAX_RECORDS {
        return None;
    }
    let axis = facing.axis();
    let registry = game.pack.assets.registry;
    let mut edits = Vec::new();
    let mut positions = BTreeSet::new();
    for (hand, assembly) in [
        (ClockHand::Hour, Some(hands.hour)),
        (ClockHand::Minute, hands.minute),
    ] {
        let Some(assembly) = assembly else { continue };
        let anchor = assembly.anchor();
        for degrees in [0.0, 90.0, 180.0, 270.0] {
            let turn = Rotation::new(anchor, axis, degrees)?.snapped();
            for (local, block) in assembly.blocks() {
                if !block.name.starts_with("minecraft:")
                    || local.iter().any(|component| component.unsigned_abs() > 15)
                {
                    return None;
                }
                let at = turn.place(anchor, *local)?;
                if shared::column(at) != key || !shared::resident(game, at) {
                    return None;
                }
                if degrees == 0.0 {
                    if !positions.insert(at) {
                        return None;
                    }
                    edits.push((at, registry.id(block)?, game.world.air));
                }
            }
        }
        records.push(Record {
            controller,
            anchor,
            axis: axis.index(),
            angle: clockwork::RESTORE_ANGLE,
            previous_angle: clockwork::RESTORE_ANGLE,
            rpm: 0.0,
            stalled: false,
            return_home: true,
            stroke: None,
            clock_hand: Some(hand),
            blocks: assembly.blocks().into(),
        });
    }
    shared::commit(game, key, records, &edits).then_some(())
}

fn land(game: &mut Game<'_>, controller: Pos) -> Option<()> {
    let key = shared::column(controller);
    let mut records = shared::entries(game, key).ok()?;
    let registry = game.pack.assets.registry;
    let mut edits = Vec::new();
    let mut positions = BTreeSet::new();
    for record in records
        .iter()
        .filter(|record| record.controller == controller && record.clock_hand.is_some())
    {
        let axis = [Axis::X, Axis::Y, Axis::Z][record.axis];
        let turn = Rotation::new(record.anchor, axis, clockwork::RESTORE_ANGLE)?.snapped();
        for (local, block) in record.blocks.iter() {
            let at = turn.place(record.anchor, *local)?;
            let before = shared::state(game, at);
            if !positions.insert(at) || !game.res.facts().is_air(before) {
                return None;
            }
            edits.push((at, before, registry.id(block)?));
        }
    }
    if edits.is_empty() {
        return None;
    }
    records.retain(|record| record.controller != controller || record.clock_hand.is_none());
    shared::commit(game, key, records, &edits).then_some(())
}

pub(super) fn recover(game: &mut Game<'_>, pos: Pos) {
    let _ = land(game, pos);
}

pub(super) fn right_click(game: &mut Game<'_>, pos: Pos) -> bool {
    game.native_with_mod_block_entity(pos, |entity| {
        entity.nbt.insert(REQUEST.into(), Tag::Byte(1));
    })
    .is_some()
}

pub(super) fn tick(
    game: &mut Game<'_>,
    pos: Pos,
    entity: &mut ModBlockEntity,
    theoretical_rpm: f32,
    effective_rpm: f32,
) {
    let Some(facing) = shared::facing(game, pos) else {
        return;
    };
    let key = shared::column(pos);
    let Ok(mut records) = shared::entries(game, key) else {
        return;
    };
    let hour = hand_angle(&records, pos, ClockHand::Hour);
    let minute = hand_angle(&records, pos, ClockHand::Minute);
    let running = hour.is_some();
    let owned = entity.nbt.get(&RUNNING.into()) == Some(&Tag::Byte(1));
    if running && !owned {
        return;
    }
    let requested = entity.nbt.remove(&REQUEST.into()).is_some();
    if requested && running {
        if land(game, pos).is_some() {
            write(entity, false, Angles::default());
            game.native_block_entity_sync(pos);
        }
        return;
    }
    let before = Angles {
        hour: hour.unwrap_or_default(),
        minute: minute.unwrap_or_else(|| super::create_port::number(&entity.nbt, "MinuteAngle")),
    };
    let mut driver = Clockwork::restored(running, before);
    let speed_changed = super::create_port::number(&entity.nbt, POWER) != theoretical_rpm
        || super::create_port::number(&entity.nbt, EFFECTIVE) != effective_rpm;
    if speed_changed {
        driver.speed_changed();
    }
    if requested {
        driver.toggle();
    }
    let mode = Mode::from_scroll_value(super::create_port::integer(&entity.nbt, "ScrollValue"))
        .unwrap_or_default();
    let time = ClockTime {
        day_time: game.native_day_time(),
        natural_dimension: game.dim == Dim::Overworld,
        facing,
    };
    let action = driver.tick(
        time,
        mode,
        theoretical_rpm,
        effective_rpm,
        [false; 2],
        || assemble(game, pos, facing).is_some(),
    );
    if action == TickAction::Disassemble && land(game, pos).is_none() {
        return;
    }
    entity
        .nbt
        .insert(POWER.into(), Tag::Float(theoretical_rpm.to_bits()));
    entity
        .nbt
        .insert(EFFECTIVE.into(), Tag::Float(effective_rpm.to_bits()));
    match action {
        TickAction::Assembled | TickAction::Disassemble => {
            write(entity, action == TickAction::Assembled, Angles::default());
            game.native_block_entity_sync(pos);
        }
        TickAction::None if running => {
            let angles = driver.angles();
            let mut changed = false;
            for record in records.iter_mut().filter(|record| record.controller == pos) {
                let angle = match record.clock_hand {
                    Some(ClockHand::Hour) => angles.hour,
                    Some(ClockHand::Minute) => angles.minute,
                    None => continue,
                };
                changed |= record.previous_angle.to_bits() != record.angle.to_bits()
                    || record.angle.to_bits() != angle.to_bits()
                    || record.rpm != effective_rpm;
                record.previous_angle = record.angle;
                record.angle = angle;
                record.rpm = effective_rpm;
            }
            if !changed || shared::set_records(game, key, records).is_ok() {
                write(entity, true, angles);
            }
        }
        TickAction::None => write(entity, false, Angles::default()),
    }
}
