// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

// SawFilterSlot, FilteringBehaviour.forRecipes and the fixed-item ghost.
use super::{
    Game, Hit, create_port_chassis as chassis, create_port_drill as drill,
    create_port_saw_processing as saw, native_block_entity_draw::BlockEntityDraw,
};
use crate::{
    containers::{BlockEntity, ModBlockEntity},
    items::ItemStack,
};
use create_engine::kinetics::Pos;
use horizon_assets::item_model::DisplayContext;
use horizon_items::item_nbt::item_to_nbt;
use horizon_world::nbt::{Compound, Tag};
use winit::keyboard::KeyCode;

const ENTITY: &str = "create:saw";

#[derive(Clone, Copy)]
struct Slot {
    center: [f32; 3],
    yaw: f32,
}

impl Slot {
    fn new(first: bool, flipped: bool) -> Self {
        let side = (if flipped { 5.0 } else { 11.0 }) / 16.0;
        Self {
            center: if first {
                [side, 12.5 / 16.0, 0.5]
            } else {
                [0.5, 12.5 / 16.0, side]
            },
            yaw: (if first { 90.0 } else { 0.0 }) + if flipped { 0.0 } else { 180.0 },
        }
    }

    fn at(game: &Game<'_>, pos: Pos) -> Option<Self> {
        let state = game
            .pack
            .assets
            .registry
            .state(game.world.block(pos[0], pos[1], pos[2]))?;
        if state.name != drill::SAW || state.properties.get("facing")?.as_str() != "up" {
            return None;
        }
        Some(Self::new(
            state.properties.get("axis_along_first")?.as_str() == "true",
            state.properties.get("flipped")?.as_str() == "true",
        ))
    }

    fn hit(self, pos: Pos, point: [f64; 3]) -> bool {
        (0..3)
            .map(|i| (point[i] - f64::from(pos[i]) - f64::from(self.center[i])).powi(2))
            .sum::<f64>()
            < 0.25 * 0.25
    }
}

fn entity<'g>(game: &'g Game<'_>, pos: Pos) -> Option<&'g ModBlockEntity> {
    let BlockEntity::Mod(entity) = game.world.block_entities.get(&(pos[0], pos[1], pos[2]))? else {
        return None;
    };
    (entity.id == ENTITY).then_some(entity)
}

pub(super) fn filter_display(
    game: &Game<'_>,
    hit: &Hit,
) -> Option<super::create_port_motor_value_world::FilterDisplay> {
    use super::create_port_motor_value_world::{FilterDisplay, FilterLabel};

    let slot = Slot::at(game, hit.pos)?;
    let filter = saw::read_filter(game, entity(game, hit.pos)?)?;
    Some(FilterDisplay::sample(
        slot.center,
        [slot.yaw, 90.0, 0.0],
        FilterLabel::Recipe,
        slot.hit(hit.pos, hit.point),
        filter.is_some(),
    ))
}

enum Click<'a> {
    Blocked,
    Sample(Option<&'a ItemStack>),
}

fn click<'a>(game: &Game<'_>, hit: &Hit, held: Option<&'a ItemStack>) -> Option<Click<'a>> {
    if !game.native_on("create")
        || !game.may_build()
        || game.keys.contains(&KeyCode::ShiftLeft)
        || game.keys.contains(&KeyCode::ShiftRight)
        || game.has_shift_down()
        || game
            .inventory
            .get(game.selected)
            .and_then(Option::as_ref)
            .is_some_and(|item| item.item.as_ref() == "create:clipboard")
        || !Slot::at(game, hit.pos)?.hit(hit.pos, hit.point)
    {
        return None;
    }
    // The foreign-wrench handler runs before FilteringBehaviour. Create's
    // own wrench instead reaches canShortInteract, which cancels the click.
    if held.is_some_and(|item| item.item.as_ref() != "create:wrench" && chassis::wrench(game, item))
    {
        return None;
    }
    let entity = entity(game, hit.pos)?;
    let held = held.filter(|item| item.count > 0);
    if held.is_some_and(|item| {
        let name = item.item.as_ref();
        matches!(name, "create:wrench" | "create:mechanical_arm")
            || !saw::ordinary_filter_item(game, item)
    }) || saw::read_filter(game, entity).is_none()
    {
        return Some(Click::Blocked);
    }
    Some(Click::Sample(held))
}

pub(super) fn predicts(game: &Game<'_>, hit: &Hit, held: Option<&ItemStack>) -> bool {
    click(game, hit, held).is_some()
}

pub(super) fn right_click(game: &mut Game<'_>, pos: Pos) -> bool {
    let Some(hit) = game.pick().filter(|hit| hit.pos == pos) else {
        return false;
    };
    let Some(click) = click(game, &hit, game.held()) else {
        return false;
    };
    let Click::Sample(sample) = click else {
        return true;
    };
    let value = sample.map_or_else(|| Tag::Compound(Compound::new()), item_to_nbt);
    let max = sample.map(|item| game.max_stack(item) as i32);
    if game
        .native_with_mod_block_entity(pos, |entity| {
            entity.nbt.insert("Filter".into(), value);
            let up_to = entity.nbt.entry("UpTo".into()).or_insert(Tag::Byte(1));
            let exact = matches!(up_to, Tag::Byte(0));
            let amount = entity
                .nbt
                .entry("FilterAmount".into())
                .or_insert(Tag::Int(64));
            if exact && let (Some(max), Tag::Int(amount)) = (max, amount) {
                *amount = (*amount).min(max);
            }
        })
        .is_none()
    {
        return false;
    }
    game.native_block_entity_sync(pos);
    let at = pos.map(|v| f64::from(v) + 0.5);
    game.with_level(|_, level, _| {
        level.native_play_sound("minecraft:entity.item_frame.add_item", at, 4, 0.25, 0.1);
    });
    true
}

fn custom_depth(game: &Game<'_>, name: &str) -> f32 {
    let saw_nudge = matches!(
        name,
        "create:shaft" | "create:cogwheel" | "create:large_cogwheel" | "minecraft:end_rod"
    ) || name
        .strip_prefix("minecraft:")
        .is_some_and(|item| item.ends_with("_fence"));
    let button = game
        .pack
        .assets
        .registry
        .default_state(name)
        .and_then(|id| game.pack.assets.registry.state(id))
        .is_some_and(|state| {
            game.native_server_block_in_tag(state, "minecraft:buttons")
                .unwrap_or(false)
        });
    if saw_nudge || button { -0.1 } else { 0.0 }
}

pub(super) fn draw(game: &Game<'_>, pos: Pos, entity: &ModBlockEntity, draw: &mut BlockEntityDraw) {
    if game.player.as_ref().is_some_and(|player| {
        [player.position.x, player.position.y, player.position.z]
            .into_iter()
            .zip(pos)
            .map(|(eye, block)| (eye - f64::from(block) - 0.5).powi(2))
            .sum::<f64>()
            > 100.0
    }) {
        return;
    }
    let (Some(slot), Some(Some(item))) = (Slot::at(game, pos), saw::read_filter(game, entity))
    else {
        return;
    };
    draw.push();
    draw.translate(slot.center);
    draw.rotate_about([0.0, 1.0, 0.0], slot.yaw, [0.0; 3]);
    draw.rotate_about([1.0, 0.0, 0.0], 90.0, [0.0; 3]);
    draw_sample(game, draw, &item);
    draw.pop();
}

pub(super) fn draw_sample(game: &Game<'_>, draw: &mut BlockEntityDraw, item: &ItemStack) {
    let rendered = game.resolve_item(item, DisplayContext::Fixed, None, 0);
    if rendered.is_empty() {
        return;
    }
    // Fixed-context models use the host's side-lit profile for solid items
    // and its front-lit profile for generated sprites.
    let solid = rendered.uses_block_light();
    let scale = 0.5 * ((if solid { 1.0 } else { 0.5 }) + 1.0 / 64.0);
    let z = (if solid { 0.0 } else { -0.15 }) + custom_depth(game, &item.item);
    draw.scale([scale; 3]);
    draw.translate([0.0, 0.0, z]);
    game.submit_item_world(&rendered, draw.pose(), draw.light, draw.vertices_mut());
}

#[cfg(test)]
mod tests {
    use super::Slot;

    #[test]
    fn source_filter_slot_transform_and_open_hit_radius() {
        for (first, flipped, center, yaw) in [
            (false, false, [0.5, 0.78125, 0.6875], 180.0),
            (false, true, [0.5, 0.78125, 0.3125], 0.0),
            (true, false, [0.6875, 0.78125, 0.5], 270.0),
            (true, true, [0.3125, 0.78125, 0.5], 90.0),
        ] {
            let slot = Slot::new(first, flipped);
            assert_eq!(slot.center, center);
            assert_eq!(slot.yaw, yaw);
            let pos = [1160, 103, 101];
            let origin = std::array::from_fn(|i| f64::from(pos[i]) + f64::from(center[i]));
            let [x, y, z] = origin;
            assert!(slot.hit(pos, [x + 0.249, y, z]));
            assert!(!slot.hit(pos, [x + 0.25, y, z]));
        }
    }
}
