// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

// SandPaperItem, SandPaperItemComponent and SandPaperPolishingRecipe.
use super::{Game, shield::OFFHAND_SLOT};
use horizon_client::{first_person::Hand, items::ItemStack};
use horizon_core::{
    geometry::{Aabb, Vec3},
    random::RandomSource,
};
use horizon_items::item_nbt::{item_from_nbt, item_to_nbt};
use horizon_world::{consumable::UseAnimation, nbt::Tag, player_inventory::EquipmentSlot};

pub(super) const COMPONENT: &str = "create:sand_paper_polishing";
pub(super) const RECIPE: &str = "create:sandpaper_polishing";
const DURATION: i32 = 32;

fn is_paper(stack: &ItemStack) -> bool {
    matches!(
        stack.item.as_ref(),
        "create:sand_paper" | "create:red_sand_paper"
    )
}

pub(super) fn duration(game: &Game<'_>, stack: &ItemStack, duration: &mut i32) {
    if game.native_on("create") && is_paper(stack) {
        *duration = DURATION;
    }
}

pub(super) fn animation(game: &Game<'_>, stack: &ItemStack, animation: &mut UseAnimation) {
    if game.native_on("create") && is_paper(stack) {
        *animation = UseAnimation::Eat;
    }
}

fn polished(game: &Game<'_>, stack: &ItemStack) -> Option<ItemStack> {
    for recipe in game.native_recipes_of_type(RECIPE) {
        let (Some(ingredients), Some(results)) = (
            recipe.json["ingredients"].as_array(),
            recipe.json["results"].as_array(),
        ) else {
            continue;
        };
        let ([ingredient], [result]) = (ingredients.as_slice(), results.as_slice()) else {
            continue;
        };
        if result
            .get("chance")
            .is_some_and(|chance| chance.as_f64() != Some(1.0))
        {
            continue;
        }
        let Some(ingredient) = super::create_port::ingredient(ingredient)
            .and_then(|input| game.native_recipe_ingredient(&input))
        else {
            continue;
        };
        if !ingredient.test(stack) {
            continue;
        }
        let Some(output) = game.native_recipe_result(result) else {
            continue;
        };
        if output.count <= game.native_max_stack_size(&output.item)? {
            return Some(output);
        }
    }
    None
}

enum Source {
    Hand(usize),
    Dropped(u32),
}

fn vector([x, y, z]: [f64; 3]) -> Vec3 {
    Vec3::new(x, y, z)
}

fn input(game: &Game<'_>, hand: Hand) -> Option<(Source, ItemStack)> {
    let other_slot = match hand {
        Hand::Main => OFFHAND_SLOT,
        Hand::Off => game.selected,
    };
    if let Some(stack) = game.stack_in(other_slot)
        && polished(game, stack).is_some()
    {
        return Some((Source::Hand(other_slot), stack.clone()));
    }
    let (eye, look) = game.aim()?;
    let reach = game.reach();
    let end = game.clip_ray(eye, look, reach).map_or_else(
        || std::array::from_fn(|i| eye[i] + look[i] * reach),
        |hit| hit.point,
    );
    let bounds = Aabb::new(vector(end.map(|p| p - 1.0)), vector(end.map(|p| p + 1.0)));
    let position = game.player.as_ref()?.position;
    // The visible entity list also permits the window to predict the original
    // use. Only the authoritative side changes the stack or discards an entity.
    game.dropped
        .iter()
        .find(|entity| {
            entity.stack.count != 0
                && entity.bounds().intersects(bounds)
                && entity.position.distance_squared(position) <= 9.0
                && polished(game, &entity.stack).is_some()
        })
        .map(|entity| (Source::Dropped(entity.id), entity.stack.clone()))
}

fn read_reservation(value: &Tag) -> Option<ItemStack> {
    let reserved = item_from_nbt(value.get("item")?)?;
    (reserved.count == 1).then_some(reserved)
}

fn reserved(game: &Game<'_>, paper: &ItemStack) -> Option<ItemStack> {
    let input = read_reservation(game.native_component(paper, COMPONENT).ok()??)?;
    game.items().get(&input.item).map(|_| input)
}

pub(super) fn start(
    game: &mut Game<'_>,
    paper: &ItemStack,
    hand: Hand,
    duration: i32,
    canceled: &mut bool,
) {
    if *canceled || duration < 0 || !game.native_on("create") || !is_paper(paper) {
        return;
    }
    match game.native_component(paper, COMPONENT) {
        Ok(Some(value)) => {
            *canceled = read_reservation(value).is_none();
            return;
        }
        Err(_) => {
            *canceled = true;
            return;
        }
        Ok(None) => {}
    }
    let Some((source, mut remaining)) = input(game, hand) else {
        *canceled = true;
        return;
    };
    if !game.native_authoritative() {
        return;
    }
    let mut reserved = remaining.clone();
    reserved.count = 1;
    remaining.count -= 1;
    let mut paper = paper.clone();
    if game
        .native_set_component(
            &mut paper,
            COMPONENT,
            Tag::compound([("item", item_to_nbt(&reserved))]),
        )
        .is_err()
    {
        *canceled = true;
        return;
    }
    match source {
        Source::Hand(slot) => {
            *game.stack_in_mut(slot) = (remaining.count != 0).then_some(remaining)
        }
        Source::Dropped(id) => {
            let dimension = game.dim.id();
            if !game.native_set_item_entity(dimension, id, remaining) {
                *canceled = true;
                return;
            }
        }
    }
    *game.held_mut() = Some(paper);
}

fn take_reservation(game: &Game<'_>, stack: &ItemStack) -> Option<(ItemStack, ItemStack)> {
    if !game.native_authoritative() || !game.native_on("create") || !is_paper(stack) {
        return None;
    }
    let mut paper = game.held()?.clone();
    if paper.item != stack.item {
        return None;
    }
    let input = reserved(game, &paper)?;
    game.native_remove_component(&mut paper, COMPONENT).ok()?;
    Some((paper, input))
}

fn give(game: &mut Game<'_>, stack: ItemStack) {
    if let Some(left) = game.give(stack) {
        game.player_drop(left);
    }
}

pub(super) fn finish(
    game: &mut Game<'_>,
    paper: &ItemStack,
    hand: Hand,
    result: &mut Option<ItemStack>,
) {
    let Some((paper, input)) = take_reservation(game, paper) else {
        return;
    };
    let result_stack = polished(game, &input).unwrap_or_else(|| input.clone());
    give(game, result_stack);
    let remainder = game
        .items()
        .get(&input.item)
        .and_then(|item| item.crafting_remainder.clone());
    if let Some(remainder) = remainder {
        give(game, ItemStack::new(&remainder, 1));
    }
    *game.held_mut() = Some(paper);
    let slot = match hand {
        Hand::Main => EquipmentSlot::MainHand,
        Hand::Off => EquipmentSlot::OffHand,
    };
    game.damage_held_in_slot(1, slot);
    *result = game.held().cloned();
}

pub(super) fn release(game: &mut Game<'_>, paper: &ItemStack) {
    let Some((paper, input)) = take_reservation(game, paper) else {
        return;
    };
    give(game, input);
    *game.held_mut() = Some(paper);
}

pub(super) fn effects(game: &mut Game<'_>, paper: &ItemStack, remaining: i32) {
    if !is_paper(paper) || !game.native_on("create") {
        return;
    }
    let Some(input) = reserved(game, paper) else {
        return;
    };
    if game.native_window() {
        game.eat_particles(&input, 1);
    } else if let Some(player) = game.native_player()
        && (DURATION - remaining - 6) % 7 == 0
    {
        let volume = 0.9 + 0.2 * game.world.random.next_float();
        let pitch = 0.9 + 0.2 * game.world.random.next_float();
        let position = [player.x, player.y, player.z];
        game.with_level(|_, level, _| {
            level.native_play_sound("create:sanding_short", position, 4, volume, pitch);
        });
    }
}
