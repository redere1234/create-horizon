// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use super::Game;
use crate::items::ItemStack;
use create_engine::{
    kinetics::Pos,
    placement::Direction,
    sail::{self, Sail},
};
use horizon_core::{
    geometry::{Direction as Face, Vec3},
    position::BlockPos,
    random::RandomSource,
};
use horizon_world::{
    chunk::BlockState,
    level::{PlaceContext, PlaceOutcome},
};

pub(super) fn from_state(state: &BlockState) -> Option<Sail> {
    let material = sail::material(&state.name)?;
    let facing = state.properties.get("facing")?;
    let facing = Direction::ALL.into_iter().find(|d| d.name() == facing)?;
    Some(Sail { material, facing })
}

fn at(game: &Game<'_>, pos: Pos) -> Option<Sail> {
    from_state(
        game.pack
            .assets
            .registry
            .state(game.world.block(pos[0], pos[1], pos[2]))?,
    )
}

pub(super) fn pickup(block: &str) -> Option<&'static str> {
    sail::material(block).map(|material| {
        if material == sail::FRAME {
            sail::FRAME
        } else {
            sail::WHITE
        }
    })
}

fn reacts_to(game: &Game<'_>, sail: Sail, item: &str) -> bool {
    if game.keys.contains(&winit::keyboard::KeyCode::ShiftLeft) {
        return false;
    }
    if matches!(item, sail::FRAME | sail::WHITE) {
        return game.may_build();
    }
    item == "minecraft:shears"
        || sail.material != sail::FRAME && sail::canvas_for_dye(item).is_some()
}

pub(super) fn reacts(game: &Game<'_>, pos: Pos, held: Option<&ItemStack>) -> bool {
    game.native_on("create")
        && held
            .is_some_and(|item| at(game, pos).is_some_and(|sail| reacts_to(game, sail, &item.item)))
}

fn extend(game: &mut Game<'_>, base: Sail, pos: Pos, hit: [f64; 3], face: Pos, item: &ItemStack) {
    let Some(target) = base.adjacent(pos, hit).find(|&p| {
        super::create_port_contraption::resident(game, p)
            && super::create_port_generators::replaceable(game, p)
    }) else {
        return;
    };
    // The helper fixes the new state to the existing sail's orientation. Feed
    // its corresponding placement direction through Horizon's block placement.
    let (yaw, pitch) = match base.facing {
        Direction::Down => (0.0, -90.0),
        Direction::Up => (0.0, 90.0),
        Direction::North => (0.0, 0.0),
        Direction::South => (180.0, 0.0),
        Direction::West => (-90.0, 0.0),
        Direction::East => (90.0, 0.0),
    };
    let face = match face {
        [0, -1, 0] => Face::Down,
        [0, 1, 0] => Face::Up,
        [0, 0, -1] => Face::North,
        [0, 0, 1] => Face::South,
        [-1, 0, 0] => Face::West,
        _ => Face::East,
    };
    let ctx = PlaceContext {
        clicked_pos: BlockPos::new(target[0], target[1], target[2]),
        face,
        hit: Vec3::new(hit[0], hit[1], hit[2]),
        inside: false,
        yaw,
        pitch,
        sneaking: false,
        item: item.item.to_string(),
        can_use_game_master_blocks: game.can_use_game_master_blocks(),
    };
    if let PlaceOutcome::Placed { pos, state } =
        game.with_level(|b, l, t| b.place_block(l, t, &ctx))
    {
        let pos = [pos.x, pos.y, pos.z];
        game.award_stat("used", &item.item, 1);
        game.trigger_block("minecraft:placed_block", pos, item);
        game.native_place_block(item, pos, state);
        game.consume_held();
    }
    if let Err(error) = game.process_level_events() {
        log::warn!("Create sail placement: {error}");
    }
}

pub(super) fn right_click(game: &mut Game<'_>, pos: Pos, face: Pos) -> bool {
    let Some(base) = at(game, pos).filter(|_| game.native_on("create")) else {
        return false;
    };
    let Some(item) = game
        .held()
        .filter(|item| reacts_to(game, base, &item.item))
        .cloned()
    else {
        return false;
    };
    let Some(hit) = game.pick().filter(|hit| hit.pos == pos) else {
        return false;
    };
    if matches!(item.item.as_ref(), sail::FRAME | sail::WHITE) {
        extend(game, base, pos, hit.point, face, &item);
        return true;
    }
    let (target, sound, pitch) = if item.item.as_ref() == "minecraft:shears" {
        (sail::FRAME, "minecraft:entity.sheep.shear", 1.0)
    } else if let Some(target) = sail::canvas_for_dye(&item.item) {
        (
            target,
            "minecraft:item.dye.use",
            1.1 - game.world.random.next_float() * 0.2,
        )
    } else {
        return false;
    };
    let registry = game.pack.assets.registry;
    let Some(new_state) = registry.id(&BlockState {
        name: target.into(),
        properties: [("facing".into(), base.facing.name().into())].into(),
    }) else {
        return false;
    };
    let edits = sail::repaint(base, target, pos, hit.point, |p| at(game, p));
    let center = pos.map(|v| f64::from(v) + 0.5);
    game.with_level(|_, level, _| level.native_play_sound(sound, center, 4, 1.0, pitch));
    let dimension = game.dim.id();
    for p in edits {
        game.native_set_block(
            dimension,
            p,
            new_state,
            horizon_world::level::flags::UPDATE_ALL,
        );
    }
    true
}
