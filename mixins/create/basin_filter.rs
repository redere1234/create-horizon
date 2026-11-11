// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use super::{
    Game, Hit, create_port_basin as basin, create_port_chassis as chassis,
    create_port_motor_value_world::{FilterDisplay, FilterLabel},
    create_port_saw_filter,
    create_port_saw_processing::ordinary_filter_item,
    native_block_entity_draw::BlockEntityDraw,
};
use crate::{
    containers::{BlockEntity, ModBlockEntity},
    items::ItemStack,
};
use create_engine::{kinetics::Pos, placement::Direction};
use horizon_items::item_nbt::{item_from_nbt, item_to_nbt};
use horizon_world::nbt::{Compound, Tag};

pub(super) fn read(game: &Game<'_>, entity: &ModBlockEntity) -> Option<Option<ItemStack>> {
    match entity.nbt.get(&"Filter".into()) {
        None => Some(None),
        Some(Tag::Compound(tag)) if tag.is_empty() => Some(None),
        Some(tag) => {
            let stack = item_from_nbt(tag)?;
            (ordinary_filter_item(game, &stack) && item_to_nbt(&stack) == *tag)
                .then_some(Some(stack))
        }
    }
}

fn entity<'g>(game: &'g Game<'_>, pos: Pos) -> Option<&'g ModBlockEntity> {
    let BlockEntity::Mod(entity) = game.world.block_entities.get(&(pos[0], pos[1], pos[2]))? else {
        return None;
    };
    (entity.id == basin::ID).then_some(entity)
}

pub(super) fn current(game: &Game<'_>, pos: Pos) -> Option<Option<ItemStack>> {
    read(game, entity(game, pos)?)
}

// BasinValueBox uses one shared filter on all four horizontal faces.
struct Slot {
    center: [f32; 3],
    yaw: f32,
}

impl Slot {
    fn on(side: Direction) -> Option<Self> {
        let yaw = match side {
            Direction::North => 0.0,
            Direction::South => 180.0,
            Direction::West => 90.0,
            Direction::East => -90.0,
            _ => return None,
        };
        let [x, _, z] = side.vector();
        let radius = 16.05_f32 / 16.0 - 0.5;
        Some(Self {
            center: [0.5 + x as f32 * radius, 0.75, 0.5 + z as f32 * radius],
            yaw,
        })
    }

    fn at(hit: &Hit) -> Option<Self> {
        Self::on(
            Direction::ALL
                .into_iter()
                .find(|side| side.vector() == hit.face)?,
        )
    }

    fn hit(&self, hit: &Hit) -> bool {
        (0..3)
            .map(|i| (hit.point[i] - f64::from(hit.pos[i]) - f64::from(self.center[i])).powi(2))
            .sum::<f64>()
            < 0.25 * 0.25
    }
}

pub(super) fn display(game: &Game<'_>, hit: &Hit) -> Option<FilterDisplay> {
    let slot = Slot::at(hit)?;
    let filter = current(game, hit.pos)?;
    Some(FilterDisplay::sample(
        slot.center,
        [slot.yaw, 0.0, 0.0],
        FilterLabel::Recipe,
        slot.hit(hit),
        filter.is_some(),
    ))
}

pub(super) fn predicts(game: &Game<'_>, hit: &Hit, held: Option<&ItemStack>) -> bool {
    game.native_on("create")
        && game.may_build()
        && !game.native_sneaking()
        && entity(game, hit.pos).is_some()
        && !held.is_some_and(|item| {
            item.item.as_ref() == "create:clipboard"
                || (item.item.as_ref() != "create:wrench" && chassis::wrench(game, item))
        })
        && Slot::at(hit).is_some_and(|slot| slot.hit(hit))
}

pub(super) fn right_click(game: &mut Game<'_>, pos: Pos) -> bool {
    let Some(hit) = game.pick().filter(|hit| hit.pos == pos) else {
        return false;
    };
    let held = game.held().filter(|item| item.count != 0);
    if !predicts(game, &hit, held) {
        return false;
    }
    if held.is_some_and(|item| {
        matches!(
            item.item.as_ref(),
            "create:wrench" | "create:mechanical_arm"
        ) || !ordinary_filter_item(game, item)
    }) || current(game, pos).is_none()
    {
        return true;
    }
    let value = held.map_or_else(|| Tag::Compound(Compound::new()), item_to_nbt);
    let maximum = held.map(|item| game.max_stack(item) as i32);
    if game
        .native_with_mod_block_entity(pos, |entity| {
            entity.nbt.insert("Filter".into(), value);
            let exact = entity.nbt.get(&"UpTo".into()) == Some(&Tag::Byte(0));
            if exact
                && let Some(maximum) = maximum
                && let Some(Tag::Int(amount)) = entity.nbt.get_mut(&"FilterAmount".into())
            {
                *amount = (*amount).min(maximum);
            }
        })
        .is_none()
    {
        return false;
    }
    basin::notify_contents(game, pos);
    game.native_block_entity_sync(pos);
    game.with_level(|_, level, _| {
        level.native_play_sound(
            "minecraft:entity.item_frame.add_item",
            pos.map(|coordinate| f64::from(coordinate) + 0.5),
            4,
            0.25,
            0.1,
        );
    });
    true
}

pub(super) fn draw(game: &Game<'_>, pos: Pos, entity: &ModBlockEntity, draw: &mut BlockEntityDraw) {
    if game.player.as_ref().is_some_and(|player| {
        player
            .position
            .components()
            .into_iter()
            .zip(pos)
            .map(|(coordinate, block)| (coordinate - f64::from(block) - 0.5).powi(2))
            .sum::<f64>()
            > 100.0
    }) {
        return;
    }
    let Some(Some(item)) = read(game, entity) else {
        return;
    };
    for slot in Direction::ALL.into_iter().filter_map(Slot::on) {
        draw.push();
        draw.translate(slot.center);
        draw.rotate_about([0.0, 1.0, 0.0], slot.yaw, [0.0; 3]);
        create_port_saw_filter::draw_sample(game, draw, &item);
        draw.pop();
    }
}
