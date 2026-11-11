// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT
// IWrenchable, EncasableBlock, ManualApplicationRecipe and HandCrankBlock.
use super::Game;
use crate::{containers::BlockEntity, items::ItemStack};
use create_engine::{kinetics::Axis, placement::Direction};
use horizon_core::{position::BlockPos, random::RandomSource};
use horizon_world::nbt::Tag;

fn secondary(game: &Game<'_>) -> bool {
    game.keys.contains(&winit::keyboard::KeyCode::ShiftLeft)
}
fn bypass(game: &Game<'_>) -> bool {
    secondary(game)
        && (game
            .inventory
            .get(game.selected)
            .is_some_and(Option::is_some)
            || game.offhand.is_some())
}

fn static_wrench_pickup(game: &Game<'_>, block: &str) -> bool {
    matches!(block, "create:industrial_iron_block" | "create:weathered_iron_block")
        && game.may_build()
        && game.native_sneaking()
        && game
            .native_block_name_in_tag(block, "create:wrench_pickup")
            .is_ok_and(|tagged| tagged)
}

fn manual(game: &Game<'_>, pos: [i32; 3]) -> Option<(String, bool)> {
    let held = game.held()?;
    let block = game.native_block(pos);
    let block_stack = ItemStack::new(block.as_str(), 1);
    for recipe in game.native_recipes_of_type("create:item_application") {
        let ingredients = recipe.json["ingredients"].as_array()?;
        if ingredients.len() != 2 {
            continue;
        }
        let Some(a) = crate::game::create_port::ingredient(&ingredients[0])
            .and_then(|v| game.native_recipe_ingredient(&v))
        else {
            continue;
        };
        let Some(b) = crate::game::create_port::ingredient(&ingredients[1])
            .and_then(|v| game.native_recipe_ingredient(&v))
        else {
            continue;
        };
        if a.test(&block_stack) && b.test(held) {
            return Some((
                recipe.json["results"][0]["id"].as_str()?.to_owned(),
                !recipe.json["keepHeldItem"].as_bool().unwrap_or(false),
            ));
        }
    }
    None
}
pub(super) fn reacts(game: &Game<'_>, pos: [i32; 3]) -> bool {
    if !game.native_on("create") {
        return false;
    }
    let block = game.native_block(pos);
    let held = game.held().map(|s| s.item.as_ref());
    if held == Some("create:wrench")
        && (crate::game::create_port::owns(&block)
            || block == "create:lit_blaze_burner"
            || create_engine::sail::material(&block).is_some()
            || static_wrench_pickup(game, &block))
    {
        return true;
    }
    if encased_cog_target(&block, held).is_some() {
        return game.may_build() && !game.native_sneaking();
    }
    if bypass(game) {
        return false;
    }
    if matches!(
        block.as_str(),
        "create:water_wheel" | "create:large_water_wheel" | "create:water_wheel_structure"
    ) && wheel_material(game).is_some()
    {
        return true;
    }
    block == "create:hand_crank"
        || (block == "create:shaft"
            && matches!(held, Some("create:andesite_casing" | "create:brass_casing")))
        || manual(game, pos).is_some()
}
fn wheel_material(game: &Game<'_>) -> Option<String> {
    let held = game.held()?;
    let name = held
        .item
        .strip_prefix("minecraft:")?
        .strip_suffix("_planks")?;
    create_assets::WOODS
        .contains(&name)
        .then(|| held.item.to_string())
}
fn give(game: &mut Game<'_>, stack: ItemStack, pos: [i32; 3]) {
    let uuid = game.native_acting_id();
    if let Some(rest) = game.native_give_stack(uuid, stack) {
        game.spawn_item(rest, pos.map(|v| f64::from(v) + 0.5), [0.0, 0.2, 0.0], 10);
    }
}
fn switch(game: &mut Game<'_>, pos: [i32; 3], block: &str) -> bool {
    let Some(state) = game.pack.assets.registry.default_state(block) else {
        return false;
    };
    let axis = game.native_block_property(pos, "axis");
    let nbt = match game.world.block_entities.get(&(pos[0], pos[1], pos[2])) {
        Some(BlockEntity::Mod(e)) => Some(e.nbt.clone()),
        _ => None,
    };
    let dim = game.dim.id().to_owned();
    if !game.native_set_block(&dim, pos, state, 3) {
        return false;
    }
    if let Some(axis) = axis {
        game.native_set_block_property(pos, "axis", &axis);
    }
    if let Some(nbt) = nbt {
        game.native_with_mod_block_entity(pos, |e| e.nbt = nbt);
    }
    crate::game::create_port_kinetic_runtime::invalidate();
    game.native_block_entity_sync(pos);
    true
}
pub(super) fn right_click(game: &mut Game<'_>, pos: [i32; 3], face: [i32; 3]) -> bool {
    if super::create_port::inventory_blocked(game, pos) {
        return true;
    }
    if super::create_port_sail::right_click(game, pos, face) {
        return true;
    }
    if !reacts(game, pos) {
        return false;
    }
    let block = game.native_block(pos);
    let pos = if block == "create:water_wheel_structure" {
        super::create_port_generators::master(game, pos).unwrap_or(pos)
    } else {
        pos
    };
    let block = game.native_block(pos);
    let wrench = game
        .held()
        .is_some_and(|s| s.item.as_ref() == "create:wrench");
    // Ordinary use is consumed by HandCrankBlock.useItemOn before the item.
    // Sneaking with a wrench still takes the pickup path.
    if wrench && (block != "create:hand_crank" || secondary(game)) {
        if block == super::create_port_saw_processing::crafter::BLOCK && !game.native_sneaking() {
            return false;
        }
        if encased_cog_size(&block).is_some() {
            return wrench_cog(game, pos, face);
        }
        if static_wrench_pickup(game, &block) {
            let drops = if game.creative {
                Vec::new()
            } else {
                let state = game.world.block(pos[0], pos[1], pos[2]);
                let tool = game.held().cloned();
                game.block_loot_at(pos, state, tool.as_ref(), None)
            };
            let at = BlockPos::new(pos[0], pos[1], pos[2]);
            if game.with_level(|b, level, ticks| b.destroy_block(level, ticks, at, false)) {
                let _ = game.process_level_events();
                for stack in drops {
                    game.give_or_drop(stack);
                }
                let pitch = 0.5 + game.world.random.next_float() * 0.5;
                super::create_port_sounds::wrench_remove(game, pos, pitch);
            }
            return true;
        }
        if secondary(game)
            && matches!(
                block.as_str(),
                "create:blaze_burner" | "create:lit_blaze_burner"
            )
        {
            // IWrenchable.onSneakWrenched uses Block.getDrops, not the
            // block's primary item or Ctrl+Pick data. Empty/lit cages drop
            // the empty alias; captured burners drop a fresh filled item.
            let drops = if game.creative {
                Vec::new()
            } else {
                let state = game.world.block(pos[0], pos[1], pos[2]);
                let tool = game.held().cloned();
                let saved = game
                    .world
                    .block_entities
                    .get(&(pos[0], pos[1], pos[2]))
                    .map(|entity| {
                        crate::save::encode_block_entity((pos[0], pos[1], pos[2]), entity, &block)
                    });
                game.block_loot_at(pos, state, tool.as_ref(), saved)
            };
            if switch(game, pos, "minecraft:air") {
                for stack in drops {
                    give(game, stack, pos);
                }
                crate::game::create_port_sounds::wrench(game, pos, true);
            }
            return true;
        }
        let pickup = if let Some(item) = super::create_port_sail::pickup(&block) {
            item
        } else if block == "create:gearbox"
            && game.native_block_property(pos, "axis").as_deref() != Some("y")
        {
            "create:vertical_gearbox"
        } else {
            block.as_str()
        };
        if secondary(game) {
            if block == "create:large_water_wheel" {
                let mut canceled = false;
                super::create_port_placement::destroy(game, pos, &mut canceled);
                super::create_port_sounds::wrench(game, pos, true);
                return true;
            }
            if block.ends_with("encased_shaft") {
                switch(game, pos, "create:shaft");
            } else {
                use super::create_port_saw_processing::crafter;
                let links = (block == crafter::BLOCK)
                    .then(|| crafter::removal_links(game, pos))
                    .flatten();
                let contents = game
                    .native_with_mod_block_entity(pos, |e| {
                        e.items
                            .iter_mut()
                            .filter_map(Option::take)
                            .collect::<Vec<_>>()
                    })
                    .unwrap_or_default();
                if switch(game, pos, "minecraft:air") {
                    if let Some(links) = links {
                        crafter::write_inputs(game, links);
                    }
                    for stack in contents {
                        give(game, stack, pos);
                    }
                    if !game.creative {
                        give(game, ItemStack::new(pickup, 1), pos);
                    }
                } else {
                    game.native_with_mod_block_entity(pos, |e| {
                        for (slot, item) in e.items.iter_mut().zip(contents) {
                            *slot = Some(item);
                        }
                    });
                }
            }
            crate::game::create_port_sounds::wrench(game, pos, true);
        } else if block == "create:large_water_wheel"
            || super::create_port_contraption_actors::attached_actor(&block)
        {
            return false;
        } else if let Some(face) = Direction::from_vector(face) {
            if super::create_port_piston::is_piston(&block) {
                return super::create_port_piston::wrench(game, pos, face);
            }
            if block == super::create_port_deployer::BLOCK {
                return super::create_port_deployer::wrench(game, pos, face);
            }
            if block == super::create_port_basin::pump::VALVE {
                return wrench_directional_axis(game, pos, face);
            }
            let before_rotation = game.world.block(pos[0], pos[1], pos[2]);
            if super::create_port_chain::is_chain(&block) {
                if super::create_port_chain::wrench(game, pos, face) {
                    crate::game::create_port_sounds::wrench(game, pos, false);
                }
            } else if let Some(axis) = game.native_block_property(pos, "axis") {
                let axis = match axis.as_str() {
                    "x" => Axis::X,
                    "y" => Axis::Y,
                    _ => Axis::Z,
                };
                let direction = match axis {
                    Axis::X => Direction::East,
                    Axis::Y => Direction::Up,
                    Axis::Z => Direction::South,
                };
                let rotated = direction.clockwise(face.axis()).axis();
                let changed = game.native_set_block_property(
                    pos,
                    "axis",
                    match rotated {
                        Axis::X => "x",
                        Axis::Y => "y",
                        Axis::Z => "z",
                    },
                );
                if changed {
                    crate::game::create_port_sounds::wrench(game, pos, false);
                }
            } else if let Some(direction) = game.native_block_property(pos, "facing")
                && (block != "create:mechanical_press" || face.axis() == Axis::Y)
            {
                let direction = Direction::ALL
                    .into_iter()
                    .find(|d| d.name() == direction)
                    .unwrap();
                if game.native_set_block_property(
                    pos,
                    "facing",
                    direction.clockwise(face.axis()).name(),
                ) {
                    crate::game::create_port_sounds::wrench(game, pos, false);
                }
            }
            if game.world.block(pos[0], pos[1], pos[2]) != before_rotation
                && matches!(
                    block.as_str(),
                    "create:creative_motor"
                        | "create:hand_crank"
                        | "create:water_wheel"
                        | "create:large_water_wheel"
                )
            {
                crate::game::create_port_kinetic_runtime::wrenched(game, pos);
            }
            crate::game::create_port_kinetic_runtime::invalidate();
        }
        return true;
    }
    if matches!(
        block.as_str(),
        "create:water_wheel" | "create:large_water_wheel"
    ) && let Some(material) = wheel_material(game)
    {
        game.native_with_mod_block_entity(pos, |e| {
            e.nbt.insert(
                "Material".into(),
                Tag::Compound(horizon_world::nbt::Compound::from([(
                    "Name".into(),
                    Tag::String(material.as_str().into()),
                )])),
            );
        });
        game.native_block_entity_sync(pos);
        return true;
    }
    if block == "create:hand_crank" {
        let back = secondary(game);
        let mut update = false;
        game.native_with_mod_block_entity(pos, |e| {
            update = crate::game::create_port::integer(&e.nbt, "InUse") == 0
                || (crate::game::create_port::integer(&e.nbt, "Backwards") != 0) != back;
            e.nbt.insert("InUse".into(), Tag::Int(10));
            e.nbt.insert("Backwards".into(), Tag::Byte(i8::from(back)));
        });
        if update {
            crate::game::create_port_kinetic_runtime::generated_changed(game, pos);
            game.native_block_entity_sync(pos);
        }
        if let Some(player) = game.player.as_mut() {
            player.cause_food_exhaustion(32.0 * 0.01);
        }
        return true;
    }
    if block == "create:shaft" {
        let item = game.held().map(|s| s.item.to_string()).unwrap_or_default();
        let target = match item.as_str() {
            "create:andesite_casing" => Some("create:andesite_encased_shaft"),
            "create:brass_casing" => Some("create:brass_encased_shaft"),
            _ => None,
        };
        if let Some(target) = target {
            switch(game, pos, target);
            crate::game::create_port_sounds::casing(game, pos);
            return true;
        }
    }
    if let Some(target) = encased_cog_target(&block, game.held().map(|s| s.item.as_ref())) {
        return case_cog(game, pos, target);
    }
    if let Some((result, consume)) = manual(game, pos) {
        if !game.may_build() {
            return true;
        }
        let dim = game.dim.id().to_owned();
        if let Some(state) = game.pack.assets.registry.default_state(&result)
            && game.native_set_block(&dim, pos, state, 3)
        {
            if consume {
                game.consume_held();
            }
            crate::game::create_port_sounds::manual_application(game, pos);
        }
        return true;
    }
    false
}

/// `IWrenchable` rotation for `DirectionalAxisKineticBlock` states.
pub(super) fn wrench_directional_axis(game: &mut Game<'_>, pos: [i32; 3], face: Direction) -> bool {
    let registry = game.pack.assets.registry;
    let Some(before) = registry.state(game.world.block(pos[0], pos[1], pos[2])) else {
        return false;
    };
    let Some(direction) = before.properties.get("facing").and_then(|name| {
        Direction::ALL
            .into_iter()
            .find(|direction| direction.name() == name)
    }) else {
        return false;
    };
    let mut rotated = before.clone();
    let face_axis = face.axis();
    if direction.axis() != face_axis {
        rotated.properties.insert(
            "facing".into(),
            direction.clockwise(face_axis).name().into(),
        );
    }
    if direction.axis() == face_axis || face_axis == Axis::Y {
        let Some(first) = rotated.properties.get_mut("axis_along_first") else {
            return false;
        };
        *first = if first == "true" { "false" } else { "true" }.into();
    }
    let Some(rotated) = registry.id(&rotated) else {
        return false;
    };
    let dim = game.dim.id().to_owned();
    if !game.native_set_block(&dim, pos, rotated, horizon_world::level::flags::UPDATE_ALL) {
        return false;
    }
    super::create_port_kinetic_runtime::invalidate();
    super::create_port_sounds::wrench(game, pos, false);
    true
}

pub(super) fn encased_cog_size(block: &str) -> Option<bool> {
    match block {
        "create:andesite_encased_cogwheel" | "create:brass_encased_cogwheel" => Some(false),
        "create:andesite_encased_large_cogwheel" | "create:brass_encased_large_cogwheel" => {
            Some(true)
        }
        _ => None,
    }
}

fn encased_cog_target(block: &str, casing: Option<&str>) -> Option<&'static str> {
    match (block, casing?) {
        ("create:cogwheel", "create:andesite_casing") => Some("create:andesite_encased_cogwheel"),
        ("create:large_cogwheel", "create:andesite_casing") => {
            Some("create:andesite_encased_large_cogwheel")
        }
        ("create:cogwheel", "create:brass_casing") => Some("create:brass_encased_cogwheel"),
        ("create:large_cogwheel", "create:brass_casing") => {
            Some("create:brass_encased_large_cogwheel")
        }
        _ => None,
    }
}

fn set_cog(
    game: &mut Game<'_>,
    pos: [i32; 3],
    base: horizon_world::registry::BlockStateId,
    axis: Axis,
    ends: Option<[bool; 2]>,
) -> bool {
    let registry = game.pack.assets.registry;
    let Some(mut state) = registry.state(base).cloned() else {
        return false;
    };
    state.properties.insert("axis".into(), axis.name().into());
    if let Some([top, bottom]) = ends {
        state.properties.insert("top_shaft".into(), top.to_string());
        state
            .properties
            .insert("bottom_shaft".into(), bottom.to_string());
    }
    let Some(state) = registry.id(&state) else {
        return false;
    };
    let dimension = game.dim.id().to_owned();
    if !game.native_set_block(
        &dimension,
        pos,
        state,
        horizon_world::level::flags::UPDATE_ALL,
    ) {
        return false;
    }
    super::create_port_kinetic_runtime::invalidate();
    true
}

fn case_cog(game: &mut Game<'_>, pos: [i32; 3], target: &str) -> bool {
    let Some(gear) = super::create_port::node(game, pos) else {
        return false;
    };
    let positive = [Direction::East, Direction::Up, Direction::South][gear.axis.index()];
    let ends = [positive, positive.opposite()].map(|side| {
        let delta = side.vector();
        super::create_port::node(game, std::array::from_fn(|i| pos[i] + delta[i]))
            .is_some_and(|other| other.shaft_port(side.opposite().vector()))
    });
    if let Some(base) = game.pack.assets.registry.default_state(target)
        && set_cog(game, pos, base, gear.axis, Some(ends))
    {
        super::create_port_sounds::cog_casing(game, pos);
    }
    true
}

fn wrench_cog(game: &mut Game<'_>, pos: [i32; 3], face: [i32; 3]) -> bool {
    if !game.may_build() {
        return false;
    }
    let Some(gear) = super::create_port::node(game, pos) else {
        return false;
    };
    let create_engine::kinetics::Kind::EncasedCog {
        large,
        top_shaft,
        bottom_shaft,
    } = gear.kind
    else {
        return false;
    };
    let current = game.world.block(pos[0], pos[1], pos[2]);
    if game.native_sneaking() {
        let bare = if large {
            "create:large_cogwheel"
        } else {
            "create:cogwheel"
        };
        if let Some(base) = game.pack.assets.registry.default_state(bare)
            && set_cog(game, pos, base, gear.axis, None)
        {
            game.level_event_at(2001, pos, current.0 as i32);
        }
        return true;
    }
    let Some(face) = Direction::from_vector(face) else {
        return false;
    };
    let (axis, ends) = if face.axis() == gear.axis {
        let positive = face.vector()[gear.axis.index()] > 0;
        (gear.axis, [top_shaft ^ positive, bottom_shaft ^ !positive])
    } else {
        let new_positive = [Direction::East, Direction::Up, Direction::South][gear.axis.index()]
            .clockwise(face.axis());
        let axis = new_positive.axis();
        let registry = game.pack.assets.registry;
        if !super::create_port_placement::cog_survives(pos, axis, large, |p| {
            registry.state(game.world.block(p[0], p[1], p[2]))
        }) {
            return false;
        }
        let ends = if new_positive.vector()[axis.index()] < 0 {
            [bottom_shaft, top_shaft]
        } else {
            [top_shaft, bottom_shaft]
        };
        (axis, ends)
    };
    if set_cog(game, pos, current, axis, Some(ends)) {
        super::create_port_sounds::cog_wrench(game, pos);
    }
    true
}
