// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

// CrushingWheelControllerBlock.animateTick, including the draw for nextInt(1).
fn create_crusher_animate(
    engine: &mut crate::particles::ParticleEngine,
    ctx: &crate::animate_tick::AnimateContext<'_>,
    state: horizon_world::registry::BlockStateId,
    controller: [i32; 3],
) {
    use crate::particles::{ParticleOptions, ParticleType};
    use horizon_core::random::RandomSource;
    let Some(state) = ctx.registry.state(state) else {
        return;
    };
    if state.name != "create:crushing_wheel_controller"
        || state
            .properties
            .get("valid")
            .is_none_or(|value| value != "true")
    {
        return;
    }
    let random = engine.random();
    if random.next_int_bound(1).unwrap_or(0) != 0 {
        return;
    }
    let position = controller.map(|coordinate| f64::from(coordinate as f32 + random.next_float()));
    static TRACE: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
    let trace = *TRACE.get_or_init(|| std::env::var_os("CREATE_HORIZON_PARTICLE_TRACE").is_some());
    let previous = trace.then(|| engine.made().get("crit").copied().unwrap_or(0));
    engine.add(
        &ParticleOptions::simple(ParticleType::Crit),
        position,
        [0.0; 3],
    );
    if let Some(previous) = previous {
        let accepted = engine.made().get("crit").copied().unwrap_or(0) - previous;
        log::info!(
            "Create crusher particle: {}",
            serde_json::json!({
                "event":"crit", "controller":controller, "position":position, "accepted":accepted,
            })
        );
    }
}
