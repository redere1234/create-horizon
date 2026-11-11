// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT
// Authoritative KineticScrollValueBehaviour settings. Client UI lives separately.
use super::{Game, create_port_chassis as chassis, create_port_chute as chute};
use crate::containers::{BlockEntity, ModBlockEntity};
use create_engine::contraption::chassis::MAX_RANGE;
use horizon_world::nbt::Tag;
use std::{cell::RefCell, path::PathBuf};

struct Request {
    player: u128,
    world: PathBuf,
    dimension: String,
    pos: [i32; 3],
    setting: Setting,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum MotionOptions {
    Mechanical,
    Windmill,
    Clockwork,
    Piston,
    Pulley,
}
impl MotionOptions {
    pub(super) fn for_block(block: &str) -> Option<Self> {
        Some(match block {
            super::create_port_contraption::BLOCK => Self::Mechanical,
            super::create_port_contraption::WINDMILL => Self::Windmill,
            super::create_port_clockwork::BLOCK => Self::Clockwork,
            super::create_port_piston::NORMAL | super::create_port_piston::STICKY => Self::Piston,
            super::create_port_pulley::BLOCK => Self::Pulley,
            _ => return None,
        })
    }

    pub(super) const fn max(self) -> i32 {
        match self {
            Self::Windmill => 1,
            Self::Mechanical | Self::Clockwork | Self::Piston | Self::Pulley => 2,
        }
    }

    pub(super) const fn linear(self) -> bool {
        matches!(self, Self::Piston | Self::Pulley)
    }

    pub(super) const fn wire(self) -> i32 {
        match self {
            Self::Mechanical => 0,
            Self::Windmill => 1,
            Self::Clockwork => 2,
            Self::Piston => 3,
            Self::Pulley => 4,
        }
    }

    fn from_wire(value: i32) -> Option<Self> {
        Some(match value {
            0 => Self::Mechanical,
            1 => Self::Windmill,
            2 => Self::Clockwork,
            3 => Self::Piston,
            4 => Self::Pulley,
            _ => return None,
        })
    }

    pub(super) fn selection(self, entity: &ModBlockEntity) -> i32 {
        match entity.nbt.get(&"ScrollValue".into()) {
            Some(Tag::Int(value)) if (0..=self.max()).contains(value) => *value,
            _ => 0,
        }
    }
}

const MODE_CHANGED: &str = "create_horizon:LinearMovementModeChanged";

pub(super) fn take_linear_mode_change(entity: &mut ModBlockEntity) -> bool {
    entity.nbt.remove(&MODE_CHANGED.into()).is_some()
}

#[derive(Clone, Copy)]
enum Setting {
    Motor {
        row: i32,
        raw: i32,
    },
    Chassis {
        range: u8,
        bulk: bool,
    },
    Motion {
        options: MotionOptions,
        selection: i32,
    },
    FilterAmount {
        row: i32,
        raw: i32,
    },
    FilterTap {
        face: [i32; 3],
        offset: [f32; 3],
    },
}
impl Setting {
    fn allowed(self, game: &mut Game<'_>, player: u128, pos: [i32; 3]) -> bool {
        match self {
            Self::Motor { .. } => game.create_motor_configuration_allowed(player, pos),
            Self::Motion { .. } | Self::FilterAmount { .. } | Self::FilterTap { .. } => {
                game.create_value_configuration_allowed(player, pos, false)
            }
            Self::Chassis { .. } => game.create_value_configuration_allowed(player, pos, true),
        }
    }

    fn filter(self) -> bool {
        matches!(self, Self::FilterAmount { .. } | Self::FilterTap { .. })
    }
}
thread_local! {
    static REQUESTS: RefCell<Vec<Request>> = const { RefCell::new(Vec::new()) };
}
pub(super) fn reset() {
    REQUESTS.with_borrow_mut(Vec::clear);
}
pub(super) fn receive(game: &mut Game<'_>, player: u128, channel: &str, data: &[u8]) {
    if !game.native_on("create") {
        return;
    }
    let word =
        |i: usize| i32::from_be_bytes(data[i * 4..i * 4 + 4].try_into().expect("bounded word"));
    let setting = match (channel, data.len()) {
        ("create:motor_settings_v2", 20) => {
            let (row, raw) = (word(3), word(4));
            if !(0..=1).contains(&row) || !(0..=256).contains(&raw) {
                return;
            }
            Setting::Motor { row, raw }
        }
        ("create:motor_speed", 16) => {
            let value = word(3);
            if value == 0 || !(-256..=256).contains(&value) {
                return;
            }
            Setting::Motor {
                row: i32::from(value >= 0),
                raw: value.abs(),
            }
        }
        ("create:chassis_settings", 20) => {
            let (bulk, raw) = (word(3), word(4));
            if !(0..=1).contains(&bulk) || !(0..i32::from(MAX_RANGE)).contains(&raw) {
                return;
            }
            Setting::Chassis {
                range: raw as u8 + 1,
                bulk: bulk == 1,
            }
        }
        ("create:motion_settings", 20) => {
            let Some(options) = MotionOptions::from_wire(word(3)) else {
                return;
            };
            let selection = word(4);
            if !(0..=options.max()).contains(&selection) {
                return;
            }
            Setting::Motion { options, selection }
        }
        ("create:filter_settings", 20) => {
            let (row, raw) = (word(3), word(4));
            if !(0..=1).contains(&row) || !(0..=99).contains(&raw) {
                return;
            }
            Setting::FilterAmount { row, raw }
        }
        ("create:filter_tap", 32) => {
            let (x, z) = (word(3), word(4));
            let offset = [5, 6, 7].map(|index| f32::from_bits(word(index) as u32));
            if !matches!((x, z), (1 | -1, 0) | (0, 1 | -1))
                || !offset
                    .into_iter()
                    .all(|value| (-0.125..=1.125).contains(&value))
            {
                return;
            }
            Setting::FilterTap {
                face: [x, 0, z],
                offset,
            }
        }
        _ => return,
    };
    let pos = [word(0), word(1), word(2)];
    let Some(world) = game.native_world_dir() else {
        return;
    };
    let Some(p) = game
        .native_server_players()
        .into_iter()
        .find(|p| p.uuid == player)
    else {
        return;
    };
    if (setting.filter() && p.sneaking) || !setting.allowed(game, player, pos) {
        return;
    }
    REQUESTS.with_borrow_mut(|requests| {
        if requests.len() < 256 {
            // Preserve packet order: each distinct raw setting has source feedback.
            requests.push(Request {
                player,
                world,
                dimension: p.dimension,
                pos,
                setting,
            });
        }
    });
}
pub(super) fn level_tick(game: &mut Game<'_>) {
    let dim = game.dim.id().to_owned();
    let world = game.native_world_dir();
    let players = game.native_server_players();
    let requests = REQUESTS.with_borrow_mut(|pending| {
        let mut selected = Vec::new();
        pending.retain(|r| {
            if world.as_ref() != Some(&r.world)
                || !players
                    .iter()
                    .any(|p| p.uuid == r.player && p.dimension == r.dimension)
            {
                false
            } else if r.dimension == dim {
                selected.push((r.player, r.pos, r.setting));
                false
            } else {
                true
            }
        });
        selected
    });
    for (player, pos, setting) in requests {
        let Some(actor) = players
            .iter()
            .find(|p| p.uuid == player && p.dimension == dim)
        else {
            continue;
        };
        if setting.filter() && actor.sneaking {
            continue;
        }
        if !setting.allowed(game, player, pos) || !game.world.loaded(pos[0], pos[2]) {
            continue;
        }
        match setting {
            Setting::Chassis { range, bulk } => {
                if chassis::apply_range(game, pos, range, bulk) {
                    feedback(game, pos);
                }
            }
            Setting::Motor { row, raw } => apply_motor(game, pos, row, raw),
            Setting::Motion { options, selection } => apply_motion(game, pos, options, selection),
            Setting::FilterAmount { row, raw } => {
                if chute::set_filter_amount(game, pos, row, raw) {
                    feedback(game, pos);
                }
            }
            Setting::FilterTap { face, offset } => {
                let sample = game.native_held_stack(player);
                chute::filter_tap(game, pos, face, offset, sample.as_ref());
            }
        }
    }
}

fn apply_motion(game: &mut Game<'_>, pos: [i32; 3], options: MotionOptions, selection: i32) {
    if MotionOptions::for_block(&game.native_block(pos)) != Some(options) {
        return;
    }
    let changed = game
        .native_with_mod_block_entity(pos, |entity| {
            if MotionOptions::for_block(&entity.id) != Some(options)
                || options.selection(entity) == selection
            {
                return false;
            }
            entity.nbt.insert("ScrollValue".into(), Tag::Int(selection));
            if options.linear() && entity.nbt.get(&"Running".into()) == Some(&Tag::Byte(1)) {
                entity.nbt.insert(MODE_CHANGED.into(), Tag::Byte(1));
            }
            true
        })
        .unwrap_or(false);
    if !changed {
        return;
    }
    if options == MotionOptions::Windmill {
        super::create_port_contraption::windmill_direction_changed(game, pos);
    }
    game.native_block_entity_sync(pos);
    feedback(game, pos);
}

fn apply_motor(game: &mut Game<'_>, pos: [i32; 3], row: i32, raw: i32) {
    if game.native_block(pos) != "create:creative_motor" {
        return;
    }
    let Some(BlockEntity::Mod(entity)) = game.world.block_entities.get(&(pos[0], pos[1], pos[2]))
    else {
        return;
    };
    let old = match entity.nbt.get(&"ScrollValue".into()) {
        Some(Tag::Int(value)) => *value,
        _ => 16,
    };
    if row != i32::from(old >= 0) || raw != old.saturating_abs() {
        feedback(game, pos);
    }
    let value = raw.max(1) * if row == 0 { -1 } else { 1 };
    if value != old {
        game.native_with_mod_block_entity(pos, |e| {
            e.nbt.insert("ScrollValue".into(), Tag::Int(value));
        });
        // ScrollValueBehaviour.setValue callback, unlike NBT read.
        crate::game::create_port_kinetic_runtime::generated_changed(game, pos);
        game.native_block_entity_sync(pos);
    }
}

fn feedback(game: &mut Game<'_>, pos: [i32; 3]) {
    let at = pos.map(|value| f64::from(value) + 0.5);
    game.with_level(|_, level, _| {
        level.native_play_sound("minecraft:entity.item_frame.add_item", at, 4, 0.25, 2.0);
        level.native_play_sound(
            "minecraft:block.note_block.iron_xylophone",
            at,
            4,
            0.03,
            1.125,
        );
    });
}
