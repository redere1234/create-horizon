// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

// Source Block.animateTick, invoked by the ordinary ClientLevel random sampler.
// This client-library boundary needs no Game, block-entity scan or engine-crate dependency.
fn create_burner_animate(
    engine: &mut crate::particles::ParticleEngine,
    ctx: &crate::animate_tick::AnimateContext<'_>,
    state: horizon_world::registry::BlockStateId,
    pos: [i32; 3],
) {
    use crate::particles::{ParticleOptions, ParticleType};
    use horizon_core::random::RandomSource;
    let Some(state) = ctx.registry.state(state) else {
        return;
    };
    let center = pos.map(|v| f64::from(v as f32 + 0.5));
    if state.name == "create:blaze_burner" {
        if engine.random().next_int_bound(10).unwrap_or(0) != 0 {
            return;
        }
        if state.properties.get("blaze").is_none_or(|v| v == "none") {
            return;
        }
        let random = engine.random();
        let volume = 0.5 + random.next_float();
        let pitch = random.next_float() * 0.7 + 0.6;
        engine.sounds.push((
            "minecraft:block.campfire.crackle",
            center,
            volume,
            pitch,
            false,
        ));
        return;
    }
    if state.name != "create:lit_blaze_burner" {
        return;
    }
    let random = engine.random();
    let smoke = [
        f64::from(pos[0])
            + 0.5
            + random.next_double() / 3.0 * if random.next_boolean() { 1.0 } else { -1.0 },
        f64::from(pos[1]) + random.next_double() + random.next_double(),
        f64::from(pos[2])
            + 0.5
            + random.next_double() / 3.0 * if random.next_boolean() { 1.0 } else { -1.0 },
    ];
    // The original supplied block RandomSource is independent of particle constructors.
    // Finish these draws before submitting any effect through the platform engine.
    let mut effects = vec![(ParticleType::LargeSmoke, smoke, [0.0, 0.07, 0.0], true)];
    if engine.random().next_int_bound(10).unwrap_or(0) == 0 {
        let random = engine.random();
        let volume = 0.25 + random.next_float() * 0.25;
        let pitch = random.next_float() * 0.7 + 0.6;
        engine.sounds.push((
            "minecraft:block.campfire.crackle",
            center,
            volume,
            pitch,
            false,
        ));
    }
    if state
        .properties
        .get("flame_type")
        .is_some_and(|v| v == "soul")
    {
        if engine.random().next_int_bound(8).unwrap_or(0) == 0 {
            let random = engine.random();
            let position = [
                f64::from(pos[0] as f32 + 0.5)
                    + random.next_double() / 4.0 * if random.next_boolean() { 1.0 } else { -1.0 },
                f64::from(pos[1] as f32 + 0.3) + random.next_double() / 2.0,
                f64::from(pos[2] as f32 + 0.5)
                    + random.next_double() / 4.0 * if random.next_boolean() { 1.0 } else { -1.0 },
            ];
            let velocity = [0.0, random.next_double() * 0.04 + 0.04, 0.0];
            effects.push((ParticleType::Soul, position, velocity, false));
        }
    } else if engine.random().next_int_bound(5).unwrap_or(0) == 0 {
        let mut i = 0;
        // Preserve the seemingly redundant nextInt(1), evaluated on every loop test.
        while i < engine.random().next_int_bound(1).unwrap_or(0) + 1 {
            let random = engine.random();
            let velocity = [
                f64::from(random.next_float() / 2.0),
                5e-5,
                f64::from(random.next_float() / 2.0),
            ];
            effects.push((ParticleType::Lava, center, velocity, false));
            i += 1;
        }
    }
    for (kind, position, velocity, always) in effects {
        engine.add_with(
            &ParticleOptions::simple(kind),
            position,
            velocity,
            always,
            always,
        );
    }
}
