// Copyright (c) The Create Team / The Creators of Create
// SPDX-License-Identifier: MIT
// DepotItemHandler.insertItem: the ordinary depot does not merge incoming
// automation stacks, nor accept a new input while its output buffer is occupied.
fn create_depot_can_place(
    containers: &crate::game::machines::Containers<'_>,
    view: &crate::game::machines::View,
    slot: usize,
    stack: &crate::items::ItemStack,
) -> std::ops::ControlFlow<bool> {
    let Some((pos, local)) = view.locate(slot) else {
        return std::ops::ControlFlow::Continue(());
    };
    if let Some(crate::containers::BlockEntity::Mod(entity)) =
        containers.world.block_entities.get(&pos)
    {
        if !crate::game::create_port::inventory_supported(entity) {
            return std::ops::ControlFlow::Break(false);
        }
        if entity.id == crate::game::create_port_chute::BLOCK {
            let state = containers.world.block(pos.0, pos.1, pos.2);
            return std::ops::ControlFlow::Break(
                local == 0
                    && entity.items.iter().all(Option::is_none)
                    && containers.prop(state, "facing") == Some("down")
                    && containers.prop(state, "waterlogged") == Some("false"),
            );
        }
        if entity.id == "create:millstone" {
            return std::ops::ControlFlow::Break(
                local == 0 && crate::game::create_port_millstone::automation_accepts(stack),
            );
        }
        if entity.id == "create:basin" {
            return std::ops::ControlFlow::Break(crate::game::create_port_basin::can_place(
                &entity.items,
                local,
                stack,
                containers.max_stack(stack),
            ));
        }
        if entity.id == "create:depot" {
            return std::ops::ControlFlow::Break(
                crate::game::create_port::inventory_supported(entity)
                    && local == 0
                    && entity.items.iter().all(Option::is_none),
            );
        }
    }
    std::ops::ControlFlow::Continue(())
}
