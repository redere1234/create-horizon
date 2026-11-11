// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use super::{Game, create_port as port, create_port_saw_processing::crushing::CONTROLLER};
use crate::{
    containers::{BlockEntity, ModBlockEntity},
    items::ItemStack,
    particles::{ParticleOptions, ParticleType},
};
use horizon_core::random::RandomSource;
use horizon_world::{
    level::ItemKind,
    nbt::{Compound, Tag},
};

const PARTICLE_ITEM: &str = "ParticleItem";

pub(super) fn update_tag(entity: &ModBlockEntity) -> Compound {
    let speed = port::number(&entity.nbt, "Speed");
    let input = entity
        .items
        .first()
        .and_then(Option::as_ref)
        .filter(|stack| {
            stack.count != 0
                && speed.is_finite()
                && speed != 0.0
                && !entity.nbt.contains_key(&"Entity".into())
        });
    // Horizon merges update tags. The empty value clears a previously sent
    // ingredient when the recipe applies, rotation stops or the input is removed.
    let item = input.map_or_else(
        || Tag::Compound(Compound::new()),
        horizon_items::item_nbt::item_to_nbt,
    );
    Compound::from([(PARTICLE_ITEM.into(), item)])
}

fn material(game: &Game<'_>, pos: [i32; 3], input: &ItemStack) -> Option<ParticleOptions> {
    let behaviours = game.res.behaviours();
    if let Some(binding) = behaviours.item_binding(&input.item)
        && binding.kind != ItemKind::Other
    {
        let state = behaviours.table.default_state(binding.block);
        let (sprite, tint) = game.particle_sprite(state, pos)?;
        return Some(ParticleOptions::block(ParticleType::Block, sprite, tint));
    }
    Some(game.item_particle(input))
}

// CrushingWheelControllerBlockEntity.spawnParticles. The server sends only
// slot zero while it is the active ingredient. Output slots are never shown.
pub(super) fn tick(game: &mut Game<'_>) {
    if !game.native_window() || !game.native_on("create") {
        return;
    }
    let active = game
        .world
        .block_entities
        .iter()
        .filter_map(|(&(x, y, z), entity)| {
            let BlockEntity::Mod(entity) = entity else {
                return None;
            };
            if entity.id != CONTROLLER {
                return None;
            }
            let input = entity.nbt.get(&PARTICLE_ITEM.into())?;
            let input = horizon_items::item_nbt::item_from_nbt(input)?;
            (input.count != 0).then_some(([x, y, z], input))
        })
        .collect::<Vec<_>>();
    for (controller, input) in active {
        let Some(options) = material(game, controller, &input) else {
            continue;
        };
        let random = game.particles.level_random();
        let positions: [[f64; 3]; 4] = std::array::from_fn(|_| {
            controller.map(|coordinate| f64::from(coordinate as f32 + random.next_float()))
        });
        let velocity = [0.0; 3];
        let kind = options.ty.name();
        static TRACE: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
        let trace =
            *TRACE.get_or_init(|| std::env::var_os("CREATE_HORIZON_PARTICLE_TRACE").is_some());
        let previous = trace.then(|| game.particles.made().get(kind).copied().unwrap_or(0));
        for position in positions {
            game.particles.add(&options, position, velocity);
        }
        if let Some(previous) = previous {
            let accepted = game.particles.made().get(kind).copied().unwrap_or(0) - previous;
            let sprites = options.block.as_ref().map_or_else(
                || options.item.as_deref().unwrap_or_default(),
                |(sprite, _)| std::slice::from_ref(sprite),
            );
            log::info!(
                "Create crusher particle: {}",
                serde_json::json!({
                    "event":"material", "controller":controller, "game_time":game.world.game_time,
                    "kind":kind, "input":input.item.as_ref(), "positions":positions,
                    "velocity":velocity, "accepted":accepted, "sprite":sprites,
                })
            );
        }
    }
}
