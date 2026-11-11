// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_changed(
    level: &crate::game::GameLevel<'_>,
    dimension: horizon_world::level::Dimension,
    pos: horizon_core::position::BlockPos,
    old: horizon_world::registry::BlockStateId,
    new: horizon_world::registry::BlockStateId,
) {
    use crate::game::create_port_kinetic_runtime as kinetics;
    use create_engine::kinetics::Axis;

    let dimension = match dimension {
        horizon_world::level::Dimension::Overworld => "minecraft:overworld",
        horizon_world::level::Dimension::Nether => "minecraft:the_nether",
        horizon_world::level::Dimension::End => "minecraft:the_end",
    };
    let pos = [pos.x, pos.y, pos.z];
    crate::game::create_port_millstone::forget(pos);
    crate::game::create_port_fan::changed(dimension, pos);
    crate::game::create_port_particles::changed(dimension, pos);
    crate::game::create_port_drill::changed(dimension, pos);
    kinetics::invalidate();
    if level.native_state_block(old) == Some("create:shaft")
        && level.native_state_block(new) == Some("minecraft:air")
        && let Some(axis) = [Axis::X, Axis::Y, Axis::Z]
            .into_iter()
            .find(|axis| level.native_state_with_property(old, "axis", axis.name()) == Some(old))
    {
        kinetics::shaft_cut(dimension, pos, axis);
    }
}
