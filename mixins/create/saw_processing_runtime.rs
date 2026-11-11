// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use super::{
    Game, create_port as create, create_port_belt as belt,
    native_block_entity_draw::BlockEntityDraw,
};
use crate::{
    containers::{BlockEntity, ModBlockEntity, ModContainer},
    items::ItemStack,
};
use create_engine::{
    kinetics::Pos,
    milling::roll_count,
    placement::Direction,
    saw_processing::{self, Action, CuttingCycle},
    transport::Transported,
};
use horizon_core::random::RandomSource;
use horizon_items::item_nbt::item_from_nbt;
use horizon_world::nbt::{Compound, Tag};

const SLOTS: usize = 32;
const INVENTORY: &str = "Inventory";

/// MechanicalCrafterBlockEntity and RecipeGridHandler. The kinetic and
/// transport adapters in this source share the host's ordinary ticker.
pub(super) mod crafter {
    use super::{
        BlockEntity, BlockEntityDraw, Compound, Game, ItemStack, ModBlockEntity, Pos, Tag,
        Transported, belt, create,
    };
    use crate::particles::{ParticleOptions, ParticleType};
    use create_engine::{
        crafter::{self, Cycle, GroupedItems, Layout, Phase, Pointing, Tick},
        kinetics::Axis,
        placement::Direction,
    };
    use horizon_core::{
        geometry::{ShapeOp, Vec3, VoxelShape, traverse_blocks},
        random::RandomSource,
    };
    use horizon_items::item_nbt::{item_from_nbt, item_to_nbt};
    use std::collections::{BTreeSet, VecDeque};

    pub(in crate::game) const BLOCK: &str = "create:mechanical_crafter";
    const SLOT_COVER: &str = "create:crafter_slot_cover";
    const INVENTORY: &str = "Inventory";
    const CONNECTED_INPUT: &str = "ConnectedInput";
    const MAX_INPUT_GROUP: usize = 4096;
    const GROUPED: &str = "GroupedItems";
    const PHASE: &str = "Phase";
    const COUNTDOWN: &str = "CountDown";
    const ANIMATION_TIME: &str = "CreateHorizonCrafterTime";
    const CLIENT_INPUTS: &str = "CreateHorizonCrafterInputs";
    const TIME_SLOT: usize = 2;

    fn authoritative(game: &Game<'_>) -> bool {
        game.serving.is_some() || game.options.dedicated.is_some()
    }

    fn layout(game: &Game<'_>, pos: Pos) -> Option<Layout> {
        if game.native_block(pos) != BLOCK {
            return None;
        }
        let name = game.native_block_property(pos, "facing")?;
        let facing = Direction::ALL
            .into_iter()
            .find(|side| side.axis() != Axis::Y && side.name() == name)?;
        let pointing = Pointing::from_name(&game.native_block_property(pos, "pointing")?)?;
        Some(Layout { facing, pointing })
    }

    fn entity<'a>(game: &'a Game<'_>, [x, y, z]: Pos) -> Option<&'a ModBlockEntity> {
        match game.world.block_entities.get(&(x, y, z)) {
            Some(BlockEntity::Mod(entity))
                if entity.id == BLOCK && create::inventory_supported(entity) =>
            {
                Some(entity)
            }
            _ => None,
        }
    }

    fn cycle(nbt: &Compound) -> Cycle {
        let phase = match nbt.get(&PHASE.into()) {
            Some(Tag::String(name)) => name
                .to_string()
                .ok()
                .and_then(|value| Phase::from_name(&value))
                .unwrap_or_default(),
            _ => Phase::default(),
        };
        Cycle {
            phase,
            countdown: create::integer(nbt, COUNTDOWN),
        }
    }

    fn set_cycle(nbt: &mut Compound, value: Cycle) {
        nbt.insert(PHASE.into(), Tag::String(value.phase.name().into()));
        nbt.insert(COUNTDOWN.into(), Tag::Int(value.countdown));
    }

    fn grid(nbt: &Compound) -> GroupedItems<ItemStack> {
        read_grid(nbt.get(&GROUPED.into()))
    }

    fn read_grid(tag: Option<&Tag>) -> GroupedItems<ItemStack> {
        let Some(Tag::List(rows)) = tag.and_then(|tag| tag.get("Grid")) else {
            return GroupedItems::default();
        };
        GroupedItems {
            grid: rows
                .iter()
                .filter_map(|row| {
                    let (Tag::Int(x), Tag::Int(y)) = (row.get("x")?, row.get("y")?) else {
                        return None;
                    };
                    Some(((*x, *y), row.get("item").and_then(item_from_nbt)))
                })
                .collect(),
        }
    }

    fn set_grid(nbt: &mut Compound, grouped: &GroupedItems<ItemStack>) {
        let cells = grouped
            .grid
            .iter()
            .map(|(&(x, y), stack)| {
                Tag::Compound(Compound::from([
                    ("x".into(), Tag::Int(x)),
                    ("y".into(), Tag::Int(y)),
                    (
                        "item".into(),
                        stack
                            .as_ref()
                            .map_or_else(|| Tag::Compound(Compound::new()), item_to_nbt),
                    ),
                ]))
            })
            .collect();
        nbt.insert(
            GROUPED.into(),
            Tag::Compound(Compound::from([("Grid".into(), Tag::List(cells))])),
        );
    }

    fn inventory(item: Option<&ItemStack>) -> Tag {
        let mut items = Vec::new();
        if let Some(Tag::Compound(mut row)) = item.map(item_to_nbt) {
            row.insert("Slot".into(), Tag::Int(0));
            items.push(Tag::Compound(row));
        }
        Tag::Compound(Compound::from([
            ("Size".into(), Tag::Int(1)),
            ("Items".into(), Tag::List(items)),
        ]))
    }

    fn save_inventory(entity: &mut ModBlockEntity) {
        let saved = inventory(entity.items.first().and_then(Option::as_ref));
        entity.nbt.insert(INVENTORY.into(), saved);
    }

    pub(in crate::game) fn default_nbt() -> Compound {
        let mut fields = Compound::from([
            (INVENTORY.into(), inventory(None)),
            ("Cover".into(), Tag::Byte(0)),
            (CONNECTED_INPUT.into(), input_tag(true, [[0; 3]])),
        ]);
        set_cycle(&mut fields, Cycle::default());
        set_grid(&mut fields, &GroupedItems::default());
        fields
    }

    fn chain(game: &Game<'_>, pos: Pos) -> Option<Vec<Pos>> {
        let chain = crafter::chain(pos, |at| layout(game, at)).ok()?;
        let column = |[x, _, z]: Pos| (x.div_euclid(16), z.div_euclid(16));
        chain
            .iter()
            .all(|&at| column(at) == column(pos))
            .then_some(chain)
    }

    #[derive(Clone, Copy)]
    enum Outlet {
        Open,
        Depot,
        Belt,
        Container,
    }

    fn outlet(game: &Game<'_>, pos: Pos, layout: Layout) -> Option<Outlet> {
        let target @ [x, y, z] = layout.target_position(pos);
        let block = game.native_block(target);
        if block == "create:depot" {
            return Some(Outlet::Depot);
        }
        if layout.target_direction() == Direction::Down
            && block == "create:belt"
            && game.native_block_property(target, "slope").as_deref() == Some("horizontal")
        {
            return Some(Outlet::Belt);
        }
        if layout.target_direction() == Direction::Down
            && matches!(
                block.as_str(),
                "minecraft:chest"
                    | "minecraft:trapped_chest"
                    | "minecraft:barrel"
                    | "minecraft:hopper"
            )
            && game.chute_source_available((x, y, z))
        {
            return Some(Outlet::Container);
        }
        game.res
            .behaviours()
            .is_air(game.world.block(x, y, z))
            .then_some(Outlet::Open)
    }

    fn start_plan(
        game: &Game<'_>,
        pos: Pos,
        ticking: Option<&ModBlockEntity>,
        powered: bool,
    ) -> Option<Vec<(Pos, bool)>> {
        let chain = chain(game, pos)?;
        let mut plan = Vec::with_capacity(chain.len());
        let mut nonempty = false;
        for at in chain {
            let member = if at == pos {
                ticking.or_else(|| entity(game, at))
            } else {
                entity(game, at)
            }?;
            let has_item = member.items.first().is_some_and(Option::is_some);
            nonempty |= has_item;
            if cycle(&member.nbt).phase != Phase::Idle
                || (!powered && !has_item && create::integer(&member.nbt, "Cover") == 0)
                || create::running_speed(game, &member.nbt) == 0.0
            {
                return None;
            }
            let state = layout(game, at)?;
            if crafter::target(at, state, &mut |p| layout(game, p)).is_none()
                && outlet(game, at, state).is_none()
            {
                return None;
            }
            let waits = !crafter::preceding(at, state, &mut |p| layout(game, p)).is_empty();
            plan.push((at, waits));
        }
        nonempty.then_some(plan)
    }

    fn begin(entity: &mut ModBlockEntity, waits: bool) {
        let item = entity.items.first_mut().and_then(Option::take);
        save_inventory(entity);
        set_grid(&mut entity.nbt, &GroupedItems::single(item));
        let before = cycle(&entity.nbt);
        set_cycle(&mut entity.nbt, before.begin(waits));
    }

    fn start(
        game: &mut Game<'_>,
        pos: Pos,
        mut ticking: Option<&mut ModBlockEntity>,
        powered: bool,
    ) -> bool {
        let Some(plan) = start_plan(game, pos, ticking.as_deref(), powered) else {
            return false;
        };
        for (at, waits) in plan {
            if at == pos
                && let Some(entity) = ticking.as_deref_mut()
            {
                begin(entity, waits);
            } else {
                game.native_with_mod_block_entity(at, |entity| begin(entity, waits));
                game.native_block_entity_sync(at);
            }
        }
        true
    }

    fn drop_position(pos: Pos, facing: Direction) -> [f64; 3] {
        let normal = facing.vector();
        std::array::from_fn(|axis| f64::from(pos[axis]) + 0.5 + 0.75 * f64::from(normal[axis]))
    }

    fn eject(entity: &mut ModBlockEntity) -> Vec<ItemStack> {
        let mut stacks = grid(&entity.nbt)
            .grid
            .into_values()
            .flatten()
            .collect::<Vec<_>>();
        stacks.extend(entity.items.iter_mut().filter_map(Option::take));
        let countdown = cycle(&entity.nbt).countdown;
        set_cycle(
            &mut entity.nbt,
            Cycle {
                phase: Phase::Idle,
                countdown,
            },
        );
        set_grid(&mut entity.nbt, &GroupedItems::default());
        save_inventory(entity);
        stacks
    }

    fn eject_chain(game: &mut Game<'_>, pos: Pos, mut ticking: Option<&mut ModBlockEntity>) {
        for at in chain(game, pos).unwrap_or_else(|| vec![pos]) {
            let Some(state) = layout(game, at) else {
                continue;
            };
            let stacks = if at == pos
                && let Some(entity) = ticking.as_deref_mut()
            {
                eject(entity)
            } else {
                let Some(stacks) = game.native_with_mod_block_entity(at, eject) else {
                    continue;
                };
                game.native_block_entity_sync(at);
                stacks
            };
            let spawn = drop_position(at, state.facing);
            for stack in stacks {
                let speed = &mut game.world.random;
                let velocity = [
                    speed.next_double() * 0.2 - 0.1,
                    0.2,
                    speed.next_double() * 0.2 - 0.1,
                ];
                game.spawn_item(stack, spawn, velocity, 10);
            }
        }
    }

    pub(in crate::game) fn removed(game: &mut Game<'_>, pos: Pos) {
        let Some(member) = entity(game, pos) else {
            return;
        };
        if create::integer(&member.nbt, "Cover") != 0 {
            game.spawn_item(
                ItemStack::new(SLOT_COVER, 1),
                pos.map(|v| f64::from(v) + 0.5),
                [0.0, 0.2, 0.0],
                10,
            );
        }
        eject_chain(game, pos, None);
        if let Some(tags) = removal_links(game, pos) {
            write_inputs(game, tags);
        }
    }

    fn return_stack(game: &mut Game<'_>, item: ItemStack) {
        let uuid = game.native_acting_id();
        if let Some(rest) = game.native_give_stack(uuid, item)
            && let Some(player) = game.native_player()
        {
            game.spawn_item(
                rest,
                [player.x, player.y + 1.0, player.z],
                [0.0, 0.2, 0.0],
                10,
            );
        }
    }

    fn set_cover(game: &mut Game<'_>, pos: Pos, value: bool) {
        game.native_with_mod_block_entity(pos, |entity| {
            entity
                .nbt
                .insert("Cover".into(), Tag::Byte(i8::from(value)));
        });
        game.native_block_entity_sync(pos);
    }

    fn input_tag(controller: bool, offsets: impl IntoIterator<Item = Pos>) -> Tag {
        let data = offsets
            .into_iter()
            .map(|offset| {
                Tag::Compound(Compound::from_iter(
                    ["X", "Y", "Z"]
                        .into_iter()
                        .zip(offset)
                        .map(|(axis, delta)| (axis.into(), Tag::Int(delta))),
                ))
            })
            .collect();
        Tag::Compound(Compound::from([
            ("Controller".into(), Tag::Byte(i8::from(controller))),
            ("Data".into(), Tag::List(data)),
        ]))
    }

    fn read_input(entity: &ModBlockEntity) -> Option<(bool, Vec<Pos>)> {
        let Some(tag) = entity.nbt.get(&CONNECTED_INPUT.into()) else {
            return Some((true, vec![[0; 3]]));
        };
        let Tag::List(data) = tag.get("Data")? else {
            return None;
        };
        if data.is_empty() {
            return Some((true, vec![[0; 3]]));
        }
        let controller = matches!(tag.get("Controller"), Some(Tag::Byte(1)));
        if data.len() > MAX_INPUT_GROUP || (!controller && data.len() != 1) {
            return None;
        }
        let offsets: Option<Vec<Pos>> = data
            .iter()
            .map(|row| {
                let (Tag::Int(x), Tag::Int(y), Tag::Int(z)) =
                    (row.get("X")?, row.get("Y")?, row.get("Z")?)
                else {
                    return None;
                };
                Some([*x, *y, *z])
            })
            .collect();
        let offsets = offsets?;
        (!controller || offsets[0] == [0; 3]).then_some((controller, offsets))
    }

    fn add(a: Pos, b: Pos) -> Option<Pos> {
        Some([
            a[0].checked_add(b[0])?,
            a[1].checked_add(b[1])?,
            a[2].checked_add(b[2])?,
        ])
    }

    fn relative(pos: Pos, root: Pos) -> Option<Pos> {
        Some([
            pos[0].checked_sub(root[0])?,
            pos[1].checked_sub(root[1])?,
            pos[2].checked_sub(root[2])?,
        ])
    }

    struct InputGroup {
        root: Pos,
        members: Vec<Pos>,
    }

    fn input_group(game: &Game<'_>, pos: Pos) -> Option<InputGroup> {
        let (controller, offsets) = read_input(entity(game, pos)?)?;
        let (root, offsets) = if controller {
            (pos, offsets)
        } else {
            let root = add(pos, offsets[0])?;
            let (controller, offsets) = read_input(entity(game, root)?)?;
            if !controller {
                return None;
            }
            (root, offsets)
        };
        let members: Vec<Pos> = offsets
            .into_iter()
            .map(|delta| add(root, delta))
            .collect::<Option<_>>()?;
        let unique: BTreeSet<_> = members.iter().copied().collect();
        (unique.len() == members.len() && unique.contains(&pos))
            .then_some(InputGroup { root, members })
    }

    fn group_loaded(game: &Game<'_>, group: &InputGroup) -> bool {
        let Some(root_layout) = layout(game, group.root) else {
            return false;
        };
        group.members.iter().copied().all(|pos| {
            pos == group.root
                || (layout(game, pos).is_some_and(|member| member.facing == root_layout.facing)
                    && entity(game, pos).is_some_and(|member| attached_to(member, pos, group.root)))
        })
    }

    fn attached_to(entity: &ModBlockEntity, pos: Pos, root: Pos) -> bool {
        read_input(entity)
            .is_some_and(|(controller, offsets)| !controller && add(pos, offsets[0]) == Some(root))
    }

    fn group_tags(group: InputGroup) -> Option<Vec<(Pos, Tag)>> {
        let offsets = group
            .members
            .iter()
            .map(|pos| relative(*pos, group.root))
            .collect::<Option<Vec<_>>>()?;
        let mut tags = Vec::with_capacity(group.members.len());
        tags.push((group.root, input_tag(true, offsets)));
        for pos in group.members.into_iter().skip(1) {
            tags.push((pos, input_tag(false, [relative(group.root, pos)?])));
        }
        Some(tags)
    }

    fn take_connected(root: Pos, rest: &mut BTreeSet<Pos>) -> InputGroup {
        let mut members = vec![root];
        let mut frontier = VecDeque::from([root]);
        while let Some(at) = frontier.pop_front() {
            for side in Direction::ALL {
                if let Some(next) = add(at, side.vector())
                    && rest.remove(&next)
                {
                    members.push(next);
                    frontier.push_back(next);
                }
            }
        }
        InputGroup { root, members }
    }

    fn input_changes(game: &Game<'_>, pos: Pos, other: Pos) -> Option<Vec<(Pos, Tag)>> {
        let mut first = input_group(game, pos)?;
        if !group_loaded(game, &first) {
            return None;
        }
        if first.members.contains(&other) {
            let mut rest: BTreeSet<_> = first.members.into_iter().collect();
            rest.remove(&pos);
            rest.remove(&other);
            let split = take_connected(other, &mut rest);
            let mut first = group_tags(InputGroup {
                root: pos,
                members: std::iter::once(pos).chain(rest).collect(),
            })?;
            first.extend(group_tags(split)?);
            return Some(first);
        }
        let second = input_group(game, other)?;
        if !group_loaded(game, &second)
            || first.members.len() + second.members.len() > MAX_INPUT_GROUP
        {
            return None;
        }
        first.members.extend(second.members.into_iter().skip(1));
        first.members.push(second.root);
        group_tags(first)
    }

    pub(in crate::game) fn removal_links(game: &Game<'_>, pos: Pos) -> Option<Vec<(Pos, Tag)>> {
        let group = input_group(game, pos)?;
        if !group_loaded(game, &group) {
            return None;
        }
        let mut rest: BTreeSet<_> = group.members.into_iter().collect();
        rest.remove(&pos);
        let mut tags = Vec::new();
        for side in Direction::ALL {
            if let Some(next) = add(pos, side.vector())
                && rest.remove(&next)
            {
                tags.extend(group_tags(take_connected(next, &mut rest))?);
            }
        }
        rest.is_empty().then_some(tags)
    }

    pub(in crate::game) fn write_inputs(game: &mut Game<'_>, tags: Vec<(Pos, Tag)>) {
        // All offsets and reciprocal owners are validated before any write.
        // Block entities stay in place during this single authoritative use.
        if !authoritative(game) {
            return;
        }
        let changed: Vec<_> = tags.iter().map(|(pos, _)| *pos).collect();
        for (pos, tag) in tags {
            game.native_with_mod_block_entity(pos, |entity| {
                entity.nbt.insert(CONNECTED_INPUT.into(), tag);
            });
        }
        for pos in changed {
            game.native_block_entity_sync(pos);
        }
    }

    fn blocks_link_edge(game: &Game<'_>, pos: Pos, side: Direction) -> bool {
        if game
            .native_block_name_in_tag(&game.native_block(pos), "minecraft:leaves")
            .is_ok_and(|leaves| leaves)
        {
            return false;
        }
        game.block_collision_shape(pos)
            .face_shape(belt::world_direction(side))
            .and_then(|face| VoxelShape::block().join_is_not_empty(&face, ShapeOp::ONLY_FIRST))
            .is_ok_and(|uncovered| !uncovered)
    }

    fn wrench_edge(game: &Game<'_>, pos: Pos, state: Layout) -> Option<Pos> {
        if game.native_sneaking()
            || game.spectator()
            || !game
                .held()
                .is_some_and(|stack| super::super::create_port_chassis::wrench(game, stack))
        {
            return None;
        }
        let [x, y, z] = game.eye_position()?;
        let origin = Vec3::new(x, y, z);
        let target = origin.add_vector(
            horizon_world::view_direction::view_vector(game.pitch, game.yaw).scale(10.0),
        );
        let hit = traverse_blocks(origin, target, 64, |block| {
            game.block_collision_shape([block.x, block.y, block.z])
                .clip(origin, target, block)
        })
        .ok()??;
        if [hit.block.x, hit.block.y, hit.block.z] != pos {
            return None;
        }
        let face = Direction::from_vector(hit.direction.normal())?;
        if face == state.facing || blocks_link_edge(game, add(pos, face.vector())?, face.opposite())
        {
            return None;
        }
        let local = hit
            .location
            .subtract(Vec3::new(
                f64::from(pos[0]),
                f64::from(pos[1]),
                f64::from(pos[2]),
            ))
            .components();
        const EPSILON: f64 = 1.0 / 256.0;
        Direction::ALL.into_iter().find_map(|edge| {
            let axis = edge.axis().index();
            let delta = edge.vector();
            let boundary = if delta[axis] > 0 { 1.0 } else { 0.0 };
            if edge.axis() == face.axis()
                || edge.axis() == state.facing.axis()
                || (local[axis] - boundary).abs() >= 3.0 / 16.0 + EPSILON
                || local.iter().any(|v| *v < -EPSILON || *v >= 1.0 + EPSILON)
            {
                return None;
            }
            let neighbor = add(pos, delta)?;
            (layout(game, neighbor).is_some_and(|next| next.facing == state.facing)
                && !blocks_link_edge(game, add(neighbor, face.vector())?, face.opposite()))
            .then_some(neighbor)
        })
    }

    fn hand_feed(game: &mut Game<'_>, pos: Pos, stack: &ItemStack) {
        if !authoritative(game) {
            return;
        }
        let Some(group) = input_group(game, pos) else {
            return;
        };
        let Some(layout) = layout(game, group.root) else {
            return;
        };
        let right = layout.facing.clockwise(Axis::Y).opposite();
        let horizontal = right.axis().index();
        let sign = i64::from(right.vector()[horizontal]);
        let mut members = group.members;
        members.sort_by_key(|pos| (-i64::from(pos[1]), i64::from(pos[horizontal]) * sign));
        for pos in members {
            if game.held().is_none() {
                break;
            }
            let Some(member) = entity(game, pos) else {
                continue;
            };
            if (pos != group.root && !attached_to(member, pos, group.root))
                || cycle(&member.nbt).phase != Phase::Idle
                || create::integer(&member.nbt, "Cover") != 0
                || member.items.first().is_some_and(Option::is_some)
            {
                continue;
            }
            let mut one = stack.clone();
            one.count = 1;
            if game
                .native_with_mod_block_entity(pos, |entity| {
                    entity.items.resize(1, None);
                    entity.items[0] = Some(one);
                    save_inventory(entity);
                })
                .is_none()
            {
                continue;
            }
            let hand = game.held_mut();
            if let Some(held) = hand {
                held.count -= 1;
                if held.count == 0 {
                    *hand = None;
                }
            }
            game.native_block_entity_sync(pos);
            crate::game::create_port_sounds::crafter_feed(game, pos);
            start(game, pos, None, false);
        }
    }

    pub(in crate::game) fn predicts_use(game: &Game<'_>, pos: Pos, face: Pos) -> bool {
        game.native_on("create")
            && layout(game, pos).is_some_and(|state| {
                state.facing.vector() == face || wrench_edge(game, pos, state).is_some()
            })
    }

    pub(in crate::game) fn right_click(game: &mut Game<'_>, pos: Pos, face: Pos) -> bool {
        if !game.native_on("create") {
            return false;
        }
        let Some(state) = layout(game, pos) else {
            return false;
        };
        if let Some(other) = wrench_edge(game, pos, state) {
            if authoritative(game)
                && let Some(tags) = input_changes(game, pos, other)
            {
                write_inputs(game, tags);
                let at = pos.map(|v| f64::from(v) + 0.5);
                game.with_level(|_, level, _| {
                    level.native_play_sound(
                        "minecraft:entity.item_frame.add_item",
                        at,
                        4,
                        0.25,
                        0.1,
                    );
                });
            }
            return true;
        }
        if state.facing.vector() != face {
            return false;
        }
        let Some(member) = entity(game, pos) else {
            return false;
        };
        let phase = cycle(&member.nbt).phase;
        if game
            .held()
            .is_some_and(|stack| stack.item.as_ref() == "create:wrench")
        {
            if game.native_sneaking() {
                return false;
            }
            // A live group keeps its topology until its cargo is recovered.
            if phase == Phase::Idle {
                game.native_set_block_property(pos, "pointing", state.pointing.next().name());
            }
            return true;
        }
        if phase != Phase::Idle {
            eject_chain(game, pos, None);
            return true;
        }
        let occupied = member.items.first().is_some_and(Option::is_some);
        let covered = create::integer(&member.nbt, "Cover") != 0;
        let held = game.held();
        if held.is_some_and(|stack| stack.item.as_ref() == SLOT_COVER) {
            if occupied || covered {
                return false;
            }
            set_cover(game, pos, true);
            if !game.creative {
                game.consume_held();
            }
            return true;
        }
        if let Some(stack) = held.cloned() {
            hand_feed(game, pos, &stack);
        } else if covered {
            set_cover(game, pos, false);
            if !game.creative {
                return_stack(game, ItemStack::new(SLOT_COVER, 1));
            }
        } else if occupied {
            if let Some(Some(stack)) = game.native_with_mod_block_entity(pos, |entity| {
                let item = entity.items.first_mut().and_then(Option::take);
                save_inventory(entity);
                item
            }) {
                return_stack(game, stack);
                game.native_block_entity_sync(pos);
            }
        } else {
            return false;
        }
        true
    }

    fn recipe(
        game: &Game<'_>,
        grouped: &GroupedItems<ItemStack>,
    ) -> Option<GroupedItems<ItemStack>> {
        let grid = grouped.recipe_grid()?;
        // Regular crafting is enabled by default. The same recipe manager
        // used by a crafting table selects the first match before Create's
        // automation filter is applied.
        let size = grid.width.max(grid.height);
        if size <= 3 {
            let recipes = game.recipes();
            let input: Vec<_> = (0..size * size)
                .map(|i| grid.get(i % size, i / size).cloned())
                .collect();
            if let Some((id, result)) = recipes.find(&input, size)
                && !id.ends_with("_manual_only")
                && recipes
                    .recipe(id)
                    .is_some_and(|recipe| !recipe.is_special())
            {
                let remainders: Vec<_> = recipes
                    .remainders(id, &input, size)
                    .into_iter()
                    .flatten()
                    .collect();
                // Java visits the input's unordered GroupedItems map. Equal
                // remainders need no reconstruction of that map's order.
                if remainders.first().is_some_and(|first| {
                    remainders
                        .iter()
                        .any(|stack| !stack.same_item_same_components(first))
                }) {
                    return None;
                }
                let mut output = GroupedItems::single(Some(result));
                output.grid.extend(
                    remainders
                        .into_iter()
                        .enumerate()
                        .map(|(i, stack)| ((i as i32 + 1, 0), Some(stack))),
                );
                return Some(output);
            }
        }
        for candidate in game.native_recipes_of_type("create:mechanical_crafting") {
            let data = &candidate.json;
            // Only this mechanical recipe is currently imported.
            if data["result"]["id"] != "create:crushing_wheel" {
                continue;
            }
            let Some(rows) = data["pattern"]
                .as_array()
                .filter(|rows| rows.len() == grid.height)
            else {
                continue;
            };
            let fits = rows.iter().enumerate().all(|(y, row)| {
                row.as_str()
                    .filter(|row| row.len() == grid.width)
                    .is_some_and(|row| {
                        row.chars().enumerate().all(|(x, symbol)| {
                            let item = grid.get(x, y);
                            if symbol == ' ' {
                                return item.is_none();
                            }
                            let Some(item) = item else { return false };
                            create::ingredient(&data["key"][symbol.to_string()])
                                .and_then(|value| game.native_recipe_ingredient(&value))
                                .is_some_and(|ingredient| ingredient.test(item))
                        })
                    })
            });
            if fits {
                return game
                    .native_recipe_result(&data["result"])
                    .map(|stack| GroupedItems::single(Some(stack)));
            }
        }
        None
    }

    fn lazy_turn(entity: &mut ModBlockEntity) -> bool {
        const RATE: i32 = 20;
        let Some(counter) = entity.data.first_mut() else {
            // SmartBlockEntity.initialize invokes lazyTick before tick's
            // initial post-decrement. This counter is not saved.
            entity.data.extend([RATE - 1, 1]);
            return true;
        };
        if *counter == 0 {
            *counter = RATE;
            true
        } else {
            *counter -= 1;
            false
        }
    }

    fn stamp_animation(entity: &mut ModBlockEntity, tick: i64) {
        if entity.data.len() <= TIME_SLOT {
            entity.data.resize(TIME_SLOT + 1, 0);
        }
        entity.data[TIME_SLOT] = tick as i32;
    }

    pub(in crate::game) fn render_update(entity: &ModBlockEntity, snapshot: &mut Compound) {
        if let Some(&tick) = entity.data.get(TIME_SLOT) {
            snapshot.insert(ANIMATION_TIME.into(), Tag::Int(tick));
        }
    }

    fn elapsed_ticks(entity: &ModBlockEntity, time: i64) -> i32 {
        match entity.nbt.get(&ANIMATION_TIME.into()) {
            Some(Tag::Int(tick)) => (time as i32).wrapping_sub(*tick).max(0),
            _ => 0,
        }
    }

    fn export_particle(game: &mut Game<'_>, pos: Pos, layout: Layout) {
        let facing = layout.facing.vector();
        let target = layout.target_direction().vector();
        let at = std::array::from_fn(|i| {
            f64::from(pos[i]) + 0.5 + 0.75 * f64::from(facing[i]) + f64::from(target[i])
        });
        game.with_level(|_, level, _| {
            level.native_send_particles(
                &ParticleOptions::simple(ParticleType::Crit),
                None,
                at,
                [0.0; 3],
                0.0,
                0,
            );
        });
    }

    pub(in crate::game) fn client_particles(game: &mut Game<'_>, pos: Pos) {
        let Some(layout) = layout(game, pos) else {
            return;
        };
        let Some(entity) = entity(game, pos) else {
            return;
        };
        if !entity.nbt.contains_key(&CLIENT_INPUTS.into()) {
            return;
        }
        let state = cycle(&entity.nbt);
        let elapsed = elapsed_ticks(entity, game.world.game_time);
        let speed = crafter::countdown_speed(create::running_speed(game, &entity.nbt));
        if state.phase != Phase::Crafting
            || state
                .countdown
                .saturating_sub(elapsed.saturating_mul(speed))
                >= 1000
        {
            return;
        }
        let Some(Some(item)) = grid(&entity.nbt).grid.remove(&(0, 0)) else {
            return;
        };
        if let Some(BlockEntity::Mod(entity)) =
            game.world.block_entities.get_mut(&(pos[0], pos[1], pos[2]))
        {
            entity.nbt.remove(&CLIENT_INPUTS.into());
        }
        let face = layout.facing.vector().map(f64::from);
        let center: [f64; 3] = std::array::from_fn(|i| f64::from(pos[i]) + 0.5 + 0.65 * face[i]);
        let options = game.item_particle(&item);
        // The original computes one unused random offset before the burst.
        for _ in 0..3 {
            game.world.random.next_float();
        }
        for _ in 0..10 {
            let sample: [f64; 3] = std::array::from_fn(|i| {
                f64::from((game.world.random.next_float() - 0.5) * 0.25) * (1.0 - face[i].abs())
            });
            let length = sample
                .iter()
                .map(|coordinate| coordinate * coordinate)
                .sum::<f64>()
                .sqrt();
            let offset = if length < 1.0e-4 {
                [0.0; 3]
            } else {
                sample.map(|coordinate| coordinate * 0.25 / length)
            };
            let at = std::array::from_fn(|i| center[i] + offset[i]);
            game.particles
                .add(&options, at, offset.map(|coordinate| coordinate * 0.35));
        }
    }

    fn powered_edge(game: &mut Game<'_>, pos: Pos, entity: &mut ModBlockEntity) -> bool {
        let dimension = game.dim.id().to_owned();
        let powered = game.native_neighbor_signal(&dimension, pos) > 0;
        let previous = std::mem::replace(&mut entity.data[1], i32::from(powered));
        powered && previous == 0
    }

    fn try_output(
        game: &mut Game<'_>,
        pos: Pos,
        entity: &mut ModBlockEntity,
        layout: Layout,
        outlet: Option<Outlet>,
    ) -> bool {
        let Some(outlet @ (Outlet::Depot | Outlet::Belt | Outlet::Container)) = outlet else {
            eject_chain(game, pos, Some(entity));
            return true;
        };
        let destination @ [x, y, z] = layout.target_position(pos);
        let mut grouped = grid(&entity.nbt);
        let mut changed = false;
        grouped.grid.retain(|_, stack| {
            let Some(stack) = stack else { return false };
            let moved = match outlet {
                Outlet::Depot | Outlet::Belt => {
                    let item = Transported::new(
                        belt::core_stack(game, stack.clone()),
                        belt::angle(game, stack),
                    );
                    let direction = layout.target_direction();
                    if matches!(outlet, Outlet::Belt) {
                        if belt::insert_belt_from_side(game, destination, &item, direction, false) {
                            stack.count
                        } else {
                            0
                        }
                    } else {
                        belt::insert_depot_from_side(game, destination, &item, direction)
                    }
                }
                Outlet::Container => game.chute_insert((x, y, z), stack, false).unwrap_or(0),
                Outlet::Open => unreachable!("only accepting outlets reach insertion"),
            };
            changed |= moved != 0;
            stack.count -= moved;
            stack.count != 0
        });
        let phase = cycle(&entity.nbt).phase;
        if !changed && phase == Phase::Inserting {
            return false;
        }
        set_grid(&mut entity.nbt, &grouped);
        if grouped.grid.is_empty() {
            eject_chain(game, pos, Some(entity));
        } else {
            set_cycle(
                &mut entity.nbt,
                Cycle {
                    phase: Phase::Inserting,
                    countdown: 0,
                },
            );
        }
        true
    }

    pub(in crate::game) fn tick(
        game: &mut Game<'_>,
        pos: Pos,
        entity: &mut ModBlockEntity,
        rpm: f32,
    ) -> bool {
        let Some(layout_here) = layout(game, pos) else {
            return false;
        };
        let before = cycle(&entity.nbt);
        let lazy = lazy_turn(entity);
        if lazy
            && before.phase == Phase::Idle
            && rpm != 0.0
            && entity.items.first().is_some_and(Option::is_some)
        {
            start(game, pos, Some(entity), false);
        }
        if cycle(&entity.nbt).phase != Phase::Accepting && powered_edge(game, pos, entity) {
            start(game, pos, Some(entity), true);
        }
        let mut state = cycle(&entity.nbt);
        if matches!(
            state.phase,
            Phase::Assembling | Phase::Exporting | Phase::Crafting
        ) {
            stamp_animation(entity, game.world.game_time);
        }
        if state.phase == Phase::Inserting {
            let target = outlet(game, pos, layout_here);
            return (lazy || matches!(target, Some(Outlet::Depot | Outlet::Belt)))
                && try_output(game, pos, entity, layout_here, target);
        }
        let action = state.tick(rpm);
        if state != before {
            set_cycle(&mut entity.nbt, state);
        }
        match action {
            Tick::None => return state.phase != before.phase,
            Tick::AssemblyComplete => {
                let grouped = grid(&entity.nbt);
                if crafter::target(pos, layout_here, &mut |p| layout(game, p)).is_some() {
                    set_cycle(&mut entity.nbt, Cycle::exporting(grouped.only_empty()));
                } else if let Some(output) = recipe(game, &grouped) {
                    set_grid(&mut entity.nbt, &output);
                    set_cycle(&mut entity.nbt, Cycle::crafting());
                } else {
                    eject_chain(game, pos, Some(entity));
                }
            }
            Tick::ExportComplete => {
                let Some(at) = crafter::target(pos, layout_here, &mut |p| layout(game, p)) else {
                    eject_chain(game, pos, Some(entity));
                    return true;
                };
                let mut source = grid(&entity.nbt);
                let empty = source.only_empty();
                let Some(receiver) = self::entity(game, at) else {
                    eject_chain(game, pos, Some(entity));
                    return true;
                };
                let mut next = grid(&receiver.nbt);
                if cycle(&receiver.nbt).phase != Phase::Accepting
                    || !source.merge_onto(&mut next, layout_here.pointing)
                {
                    eject_chain(game, pos, Some(entity));
                    return true;
                }
                set_grid(&mut entity.nbt, &source);
                set_cycle(
                    &mut entity.nbt,
                    Cycle {
                        phase: Phase::Waiting,
                        countdown: 0,
                    },
                );
                let receiver_layout = layout(game, at).expect("targeting crafter has a layout");
                let ready = crafter::preceding(at, receiver_layout, &mut |p| layout(game, p))
                    .into_iter()
                    .all(|previous| {
                        previous == pos
                            || self::entity(game, previous)
                                .is_some_and(|e| cycle(&e.nbt).phase == Phase::Waiting)
                    });
                game.native_with_mod_block_entity(at, |receiver| {
                    set_grid(&mut receiver.nbt, &next);
                    if ready {
                        set_cycle(&mut receiver.nbt, Cycle::assembling());
                    }
                });
                game.native_block_entity_sync(at);
                if !empty {
                    export_particle(game, pos, layout_here);
                    crate::game::create_port_sounds::crafter_click(
                        game,
                        pos,
                        next.grid.len() as f32 / 16.0 + 0.5,
                    );
                }
            }
            Tick::CraftMiddle => {
                crate::game::create_port_sounds::crafter_craft(game, pos);
                return false;
            }
            Tick::CraftComplete => {
                let target = outlet(game, pos, layout_here);
                try_output(game, pos, entity, layout_here, target);
            }
        }
        true
    }

    pub(in crate::game) fn draw(
        game: &Game<'_>,
        pos: Pos,
        entity: &ModBlockEntity,
        draw: &mut BlockEntityDraw,
    ) {
        let Some(state) = layout(game, pos) else {
            return;
        };
        let axis = state.facing.axis();
        draw.push();
        create::orient(draw, axis);
        let time = draw.game_time as f64 + f64::from(draw.partial);
        let angle = create_engine::visual::angle(
            time,
            create::number(&entity.nbt, "Speed"),
            create_engine::visual::rotation_offset(pos, axis, false),
        );
        draw.rotate_about([0.0, 1.0, 0.0], angle, [0.5; 3]);
        game.native_draw_model(draw, "create:block/cogwheel_shaftless", 0xFFFFFF);
        draw.pop();

        draw.push();
        create::face_south(draw, state.facing);
        draw.rotate_about([0.0, 1.0, 0.0], 90.0, [0.5; 3]);
        let angle = match state.pointing {
            Pointing::Up => 0.0,
            Pointing::Left => 270.0,
            Pointing::Down => 180.0,
            Pointing::Right => 90.0,
        };
        draw.rotate_about([1.0, 0.0, 0.0], angle, [0.5; 3]);
        let connected = crafter::target(pos, state, &mut |p| layout(game, p)).is_some();
        let base = "create:block/mechanical_crafter/";
        if connected {
            game.native_draw_model(draw, &format!("{base}belt"), 0xFFFFFF);
            game.native_draw_model(draw, &format!("{base}belt_animated"), 0xFFFFFF);
        } else {
            game.native_draw_model(draw, &format!("{base}arrow"), 0xFFFFFF);
        }
        draw.pop();

        let running = cycle(&entity.nbt);
        if !matches!(running.phase, Phase::Crafting | Phase::Inserting)
            && (running.phase != Phase::Idle || create::integer(&entity.nbt, "Cover") != 0)
        {
            draw.push();
            create::face_south(draw, state.facing);
            draw.rotate_about([0.0, 1.0, 0.0], 90.0, [0.5; 3]);
            game.native_draw_model(draw, &format!("{base}lid"), 0xFFFFFF);
            draw.pop();
        }

        let elapsed = elapsed_ticks(entity, draw.game_time);
        let remaining = running.countdown as f32
            - crafter::countdown_speed(create::running_speed(game, &entity.nbt)) as f32
                * (elapsed as f32 + draw.partial);
        let advance = if running.phase == Phase::Exporting {
            0.75 * ((1000.0 - remaining) / 1000.0).clamp(0.0, 1.0)
        } else {
            0.0
        };
        let local = state.pointing.direction(Direction::South).vector();
        draw.push();
        create::face_south(draw, state.facing);
        draw.translate([
            0.5 + local[0] as f32 * advance,
            0.5 + local[1] as f32 * advance,
            1.08,
        ]);
        draw.scale([0.5; 3]);
        match running.phase {
            Phase::Idle => {
                if let Some(Some(stack)) = entity.items.first() {
                    draw.translate([0.0, 0.0, -1.0 / 256.0]);
                    draw_stack(game, draw, stack);
                }
            }
            Phase::Crafting => draw_craft(game, entity, draw, remaining),
            phase => {
                let grid = grid(&entity.nbt);
                let depth = if phase == Phase::Exporting {
                    match state.pointing {
                        Pointing::Up => -9.0,
                        Pointing::Left => 18.0,
                        Pointing::Right => -18.0,
                        Pointing::Down => 9.0,
                    }
                } else {
                    0.0
                };
                draw_group(game, draw, &grid, 0.5, depth, phase == Phase::Inserting);
            }
        }
        draw.pop();
    }

    fn draw_stack(game: &Game<'_>, draw: &mut BlockEntityDraw, stack: &ItemStack) {
        game.native_draw_item(
            draw,
            stack,
            horizon_assets::item_model::DisplayContext::Fixed,
            None,
            0,
        );
    }

    fn draw_group(
        game: &Game<'_>,
        draw: &mut BlockEntityDraw,
        grid: &GroupedItems<ItemStack>,
        spacing: f32,
        depth: f32,
        only_center: bool,
    ) {
        for (&(x, y), stack) in &grid.grid {
            let Some(stack) = stack else { continue };
            if only_center && (x, y) != (0, 0) {
                continue;
            }
            draw.push();
            draw.translate([
                x as f32 * spacing,
                y as f32 * spacing,
                (x as f32 + y as f32 * 3.0 + depth) / 1024.0,
            ]);
            draw_stack(game, draw, stack);
            draw.pop();
        }
    }

    fn draw_craft(
        game: &Game<'_>,
        entity: &ModBlockEntity,
        draw: &mut BlockEntityDraw,
        remaining: f32,
    ) {
        let pose = crafter::craft_pose(remaining);
        if pose.input_scale > 0.0 {
            let inputs = read_grid(entity.nbt.get(&CLIENT_INPUTS.into()));
            let (min, max) =
                inputs
                    .grid
                    .keys()
                    .fold(([0; 2], [0; 2]), |(mut min, mut max), &(x, y)| {
                        min[0] = min[0].min(x);
                        min[1] = min[1].min(y);
                        max[0] = max[0].max(x);
                        max[1] = max[1].max(y);
                        (min, max)
                    });
            draw.push();
            draw.scale([pose.input_scale; 3]);
            draw.translate([
                -0.25 * (min[0] as f32 + max[0] as f32) * pose.center,
                -0.25 * (min[1] as f32 + max[1] as f32) * pose.center,
                0.0,
            ]);
            draw_group(game, draw, &inputs, pose.spacing, 0.0, false);
            draw.pop();
        }
        if pose.result_scale > 0.0
            && let Some(Some(stack)) = grid(&entity.nbt).grid.get(&(0, 0))
        {
            draw.rotate_about([0.0, 0.0, 1.0], pose.result_angle, [0.0; 3]);
            draw.scale([pose.result_scale; 3]);
            draw_stack(game, draw, stack);
        }
    }
}

pub(super) mod crushing {
    use super::super::{create_port_chute as chute, create_port_millstone as millstone};
    use super::{
        BlockEntity, Compound, Game, INVENTORY, ItemStack, ModBlockEntity, Pos, SLOTS, Tag,
        Transported, belt, create, processing_inventory, roll_count,
    };
    use create_engine::{
        crushing::{Action, Cycle, direction},
        kinetics::Axis,
        placement::Direction,
    };
    use horizon_core::geometry::Vec3;
    use horizon_core::random::RandomSource;
    use horizon_world::{chunk::BlockState, level::flags, registry::BlockStateId};
    use std::collections::BTreeMap;

    pub(in crate::game) const WHEEL: &str = "create:crushing_wheel";
    pub(in crate::game) const CONTROLLER: &str = "create:crushing_wheel_controller";

    const GAPS: [Direction; 2] = [Direction::East, Direction::South];
    const PROCESSING_ENTITY: &str = "Entity";

    fn offset(pos: Pos, side: Direction) -> Pos {
        let normal = side.vector();
        std::array::from_fn(|axis| pos[axis] + normal[axis])
    }

    fn axis(game: &Game<'_>, pos: Pos) -> Option<Axis> {
        if game.native_block(pos) != WHEEL {
            return None;
        }
        match game.native_block_property(pos, "axis").as_deref() {
            Some("x") => Some(Axis::X),
            Some("z") => Some(Axis::Z),
            _ => None,
        }
    }

    fn pair(game: &Game<'_>, center: Pos) -> Option<(Direction, Axis)> {
        let mut matches = GAPS.into_iter().filter_map(|side| {
            let a = offset(center, side.opposite());
            let b = offset(center, side);
            let axis = axis(game, a)?;
            (axis != side.axis() && self::axis(game, b) == Some(axis)).then_some((side, axis))
        });
        let pair = matches.next()?;
        matches.next().is_none().then_some(pair)
    }

    fn rpm(game: &Game<'_>, pos: Pos, update: (Pos, f32)) -> f32 {
        if pos == update.0 {
            return update.1;
        }
        match game.world.block_entities.get(&(pos[0], pos[1], pos[2])) {
            Some(BlockEntity::Mod(entity)) if entity.id == WHEEL => {
                create::number(&entity.nbt, "Speed")
            }
            _ => 0.0,
        }
    }

    fn state(facing: Direction, valid: bool, game: &Game<'_>) -> Option<BlockStateId> {
        game.pack.assets.registry.id(&BlockState {
            name: CONTROLLER.into(),
            properties: BTreeMap::from([
                ("facing".to_owned(), facing.name().into()),
                ("valid".to_owned(), valid.to_string()),
            ])
            .into(),
        })
    }

    pub(in crate::game) fn wheel_updated(game: &mut Game<'_>, pos: Pos, axis: Axis, rpm: f32) {
        if axis == Axis::Y {
            return;
        }
        let sides = if axis == Axis::X {
            [Direction::North, Direction::South]
        } else {
            [Direction::West, Direction::East]
        };
        for side in sides {
            let center = offset(pos, side);
            let Some((gap, wheel_axis)) = pair(game, center) else {
                continue;
            };
            let current = game.world.block(center[0], center[1], center[2]);
            if !game.res.behaviours().is_air(current) && game.native_block(center) != CONTROLLER {
                continue;
            }
            // Iterate.directions sees the negative Z/X side before the positive side.
            let speed = self::rpm(game, offset(center, gap.opposite()), (pos, rpm));
            let other = self::rpm(game, offset(center, gap), (pos, rpm));
            let facing = direction(wheel_axis, gap, speed, other);
            let Some(target) = state(facing.unwrap_or(Direction::Down), facing.is_some(), game)
            else {
                continue;
            };
            if current != target {
                let dim = game.dim.id().to_owned();
                if !game.native_set_block(&dim, center, target, flags::UPDATE_ALL) {
                    continue;
                }
            }
            let speed = if facing.is_some() {
                (speed / 50.0).abs()
            } else {
                0.0
            };
            if game.native_with_mod_block_entity(center, |entity| {
                let changed = create::number(&entity.nbt, "Speed") != speed;
                if changed {
                    entity
                        .nbt
                        .insert("Speed".into(), Tag::Float(speed.to_bits()));
                }
                changed
            }) == Some(true)
            {
                game.native_block_entity_sync(center);
            }
        }
    }

    fn save(entity: &mut ModBlockEntity, cycle: Cycle) {
        let inventory = processing_inventory(
            &entity.items,
            cycle.remaining,
            cycle.recipe_time,
            cycle.applied,
        );
        entity.nbt.insert(INVENTORY.into(), inventory);
    }

    pub(in crate::game) fn default_nbt() -> Compound {
        Compound::from([
            (INVENTORY.into(), processing_inventory(&[], 0.0, 0.0, false)),
            ("Speed".into(), Tag::Float(0)),
        ])
    }

    fn cycle(entity: &ModBlockEntity) -> Option<Cycle> {
        let Tag::Compound(saved) = entity.nbt.get(&INVENTORY.into())? else {
            return None;
        };
        let remaining = create::number(saved, "ProcessingTime");
        let recipe_time = create::number(saved, "RecipeTime");
        (create::integer(saved, "Size") == SLOTS as i32
            && entity.items.len() == SLOTS
            && remaining.is_finite()
            && remaining >= 0.0
            && recipe_time.is_finite()
            && recipe_time >= 0.0)
            .then_some(Cycle {
                remaining,
                recipe_time,
                applied: create::integer(saved, "AppliedRecipe") != 0,
            })
    }

    fn down(game: &Game<'_>, pos: Pos) -> bool {
        game.native_block_property(pos, "facing").as_deref() == Some("down")
    }

    fn recipe(game: &Game<'_>, stack: &ItemStack) -> Option<(i32, Vec<(ItemStack, f32)>)> {
        let crushing = game.native_recipes_of_type("create:crushing");
        let milling = game.native_recipes_of_type("create:milling");
        for recipe in crushing.iter().chain(milling) {
            let json = &recipe.json;
            let Some(input) = json["ingredients"]
                .as_array()
                .filter(|list| list.len() == 1)
                .and_then(|list| create::ingredient(&list[0]))
                .and_then(|value| game.native_recipe_ingredient(&value))
            else {
                continue;
            };
            if !input.test(stack) {
                continue;
            }
            let duration = i32::try_from(json["processing_time"].as_i64()?).ok()?;
            let results = json["results"]
                .as_array()?
                .iter()
                .map(|row| {
                    let id = row["id"].as_str()?;
                    let count = row["count"].as_u64().unwrap_or(1);
                    let chance = row["chance"].as_f64().unwrap_or(1.0);
                    (count > 0
                        && count <= 64
                        && (0.0..=1.0).contains(&chance)
                        && game.native_max_stack_size(id).is_some())
                    .then(|| (ItemStack::new(id, count as u32), chance as f32))
                })
                .collect::<Option<Vec<_>>>()?;
            return (duration > 0 && !results.is_empty() && results.len() < SLOTS)
                .then_some((duration, results));
        }
        None
    }

    fn bypasses(game: &Game<'_>, id: u32, pos: Pos) -> bool {
        matches!(game.persist.raw.get(&id)
            .and_then(|tag| tag.get("NeoForgeData"))
            .and_then(|tag| tag.get("BypassCrushingWheel")),
            Some(Tag::IntArray(value)) if value.as_slice() == pos)
    }

    fn catch_falling_item(game: &mut Game<'_>, pos: Pos, entity: &mut ModBlockEntity, speed: f32) {
        let tracked = match entity.nbt.get(&PROCESSING_ENTITY.into()) {
            Some(Tag::IntArray(uuid)) => <[i32; 4]>::try_from(uuid.as_slice()).ok(),
            _ => None,
        };
        let origin = pos.map(f64::from);
        let margin = if tracked.is_some() { 0.5 } else { 0.0 };
        let dim = game.dim.id().to_owned();
        let candidates = game.native_item_entities(
            &dim,
            origin.map(|coordinate| coordinate - margin),
            origin.map(|coordinate| coordinate + 1.0 + margin),
        );
        let Some(item) = candidates.into_iter().find(|item| match tracked {
            Some(uuid) => game.persist.uuid_of(item.id) == Some(uuid),
            None => !bypasses(game, item.id, pos) && recipe(game, &item.stack).is_some(),
        }) else {
            if entity.nbt.remove(&PROCESSING_ENTITY.into()).is_some() {
                game.native_block_entity_sync(pos);
            }
            return;
        };

        if item.position[1] < origin[1] + 0.25 {
            let Some((duration, _)) = recipe(game, &item.stack) else {
                entity.nbt.remove(&PROCESSING_ENTITY.into());
                game.native_block_entity_sync(pos);
                return;
            };
            let mut discarded = item.stack.clone();
            discarded.count = 0;
            let uuid = game.uuid_for(item.id);
            if game.native_set_item_entity(&dim, item.id, discarded) {
                entity.items[0] = Some(item.stack);
                let mut cycle = Cycle::default();
                cycle.start(duration);
                save(entity, cycle);
                entity
                    .nbt
                    .insert(PROCESSING_ENTITY.into(), Tag::IntArray(uuid.to_vec()));
                game.native_block_entity_sync(pos);
            }
            return;
        }

        // Create pulls a captured ItemEntity toward the center and marks its
        // next move as stuck. Ordinary item physics applies the multiplier,
        // gravity and world collisions on that next tick.
        let Some(dropped) = game.dropped.iter_mut().find(|drop| drop.id == item.id) else {
            return;
        };
        dropped.velocity = Vec3::new(
            (origin[0] + 0.5 - item.position[0]) / 2.0,
            -f64::from(speed.min(0.5)),
            (origin[2] + 0.5 - item.position[2]) / 2.0,
        );
        dropped.stuck = Vec3::new(0.25, f64::from(0.05_f32), 0.25);
        dropped.pickup_delay = 20;
        if tracked.is_none() {
            let uuid = game.uuid_for(item.id);
            entity
                .nbt
                .insert(PROCESSING_ENTITY.into(), Tag::IntArray(uuid.to_vec()));
            game.native_block_entity_sync(pos);
        }
    }

    pub(in crate::game) fn insert(
        game: &mut Game<'_>,
        pos: Pos,
        stack: &ItemStack,
        simulate: bool,
    ) -> u32 {
        if !down(game, pos) || pair(game, pos).is_none() {
            return 0;
        }
        let Some(BlockEntity::Mod(entity)) =
            game.world.block_entities.get(&(pos[0], pos[1], pos[2]))
        else {
            return 0;
        };
        if entity.id != CONTROLLER
            || cycle(entity).is_none()
            || entity.items.iter().any(Option::is_some)
            || entity.nbt.contains_key(&PROCESSING_ENTITY.into())
        {
            return 0;
        }
        let Some((duration, _)) = recipe(game, stack) else {
            return 0;
        };
        let moved = stack.count.min(create::stack_maximum(game, stack));
        if moved == 0 || simulate {
            return moved;
        }
        let accepted = game.native_with_mod_block_entity(pos, |entity| {
            let mut stack = stack.clone();
            stack.count = moved;
            entity.items[0] = Some(stack);
            let mut cycle = Cycle::default();
            cycle.start(duration);
            save(entity, cycle);
        });
        if accepted.is_some() {
            game.native_block_entity_sync(pos);
            moved
        } else {
            0
        }
    }

    fn eject(game: &mut Game<'_>, pos: Pos, stack: ItemStack) {
        let center = pos.map(|value| f64::from(value) + 0.5);
        let location = [center[0], center[1] - f64::from(0.55_f32), center[2]];
        let id = game.next_entity + 1;
        game.spawn_item(stack, location, [0.0; 3], 0);
        if !game.dropped.iter().rev().any(|item| item.id == id) {
            return;
        }
        let root = game
            .persist
            .raw
            .entry(id)
            .or_insert_with(|| Tag::Compound(Compound::new()));
        if let Tag::Compound(root) = root
            && let Tag::Compound(data) = root
                .entry("NeoForgeData".into())
                .or_insert_with(|| Tag::Compound(Compound::new()))
        {
            data.insert("BypassCrushingWheel".into(), Tag::IntArray(pos.to_vec()));
        }
    }

    fn insert_output(game: &mut Game<'_>, target: Pos, block: &str, stack: &ItemStack) -> u32 {
        match block {
            chute::BLOCK | chute::SMART => chute::insert_from_transport(game, target, stack),
            chute::funnel::BLOCK | chute::funnel::BRASS => {
                chute::funnel::insert_from_transport(game, target, block, stack)
            }
            "create:millstone" => millstone::insert_from_transport(game, target, stack, false),
            "create:depot" | "create:belt" => {
                let item = Transported::new(
                    belt::core_stack(game, stack.clone()),
                    belt::angle(game, stack),
                );
                if block == "create:depot" {
                    belt::insert_depot_from_side(game, target, &item, Direction::Down)
                } else if belt::insert_belt_from_side(game, target, &item, Direction::Down, false) {
                    stack.count
                } else {
                    0
                }
            }
            _ => unreachable!("output receiver was checked"),
        }
    }

    pub(in crate::game) fn tick(game: &mut Game<'_>, pos: Pos, entity: &mut ModBlockEntity) {
        let Some(mut cycle) = cycle(entity) else {
            return;
        };
        let resident = |at| crate::game::create_port_contraption::resident(game, at);
        if GAPS
            .into_iter()
            .any(|side| !resident(offset(pos, side)) || !resident(offset(pos, side.opposite())))
        {
            return;
        }
        if pair(game, pos).is_none() {
            let dim = game.dim.id().to_owned();
            if let Some(air) = game.pack.assets.registry.default_state("minecraft:air")
                && game.native_set_block(&dim, pos, air, flags::UPDATE_ALL)
            {
                for stack in entity.items.iter_mut().filter_map(Option::take) {
                    game.pop_resource(pos, stack);
                }
            }
            return;
        }
        let speed = create::running_speed(game, &entity.nbt);
        if !down(game, pos) || speed <= 0.0 || !speed.is_finite() {
            return;
        }
        if entity.items.iter().all(Option::is_none) {
            if !game.dropped.is_empty() || entity.nbt.contains_key(&PROCESSING_ENTITY.into()) {
                catch_falling_item(game, pos, entity, speed);
            }
            return;
        }
        if entity.nbt.remove(&PROCESSING_ENTITY.into()).is_some() {
            // Java clears the discarded entity on the tick after intake;
            // inventory processing starts on the following tick.
            game.native_block_entity_sync(pos);
            return;
        }
        let count = entity.items[0].as_ref().map_or(0, |stack| stack.count);
        if !cycle.applied && count == 0 {
            return;
        }
        let previous = cycle;
        match cycle.tick(speed, count) {
            Action::Idle => {
                if let Some(Tag::Compound(saved)) = entity.nbt.get_mut(&INVENTORY.into()) {
                    saved.insert(
                        "ProcessingTime".into(),
                        Tag::Float(cycle.remaining.to_bits()),
                    );
                }
            }
            Action::Apply => {
                let Some((_, results)) = entity.items[0]
                    .as_ref()
                    .and_then(|stack| recipe(game, stack))
                else {
                    // A data reload can remove a recipe while it is in progress.
                    return;
                };
                let outputs = results
                    .into_iter()
                    .map(|(stack, chance)| {
                        let limit = create::stack_maximum(game, &stack);
                        (stack, chance, limit)
                    })
                    .collect::<Vec<_>>();
                entity.items.fill(None);
                for _ in 0..count {
                    for (stack, chance, limit) in &outputs {
                        let count =
                            roll_count(stack.count, *chance, || game.world.random.next_float());
                        if count != 0 {
                            let mut output = stack.clone();
                            output.count = count;
                            super::super::create_port_inventory::insert(
                                &mut entity.items[1..],
                                output,
                                *limit,
                            );
                        }
                    }
                }
                save(entity, cycle);
                game.native_block_entity_sync(pos);
            }
            Action::Eject => {
                let below = offset(pos, Direction::Down);
                let state = game.world.block(below[0], below[1], below[2]);
                let block = game.res.facts().get(state).name.clone();
                if matches!(
                    block.as_ref(),
                    "create:depot"
                        | "create:belt"
                        | millstone::ID
                        | chute::BLOCK
                        | chute::SMART
                        | chute::funnel::BLOCK
                        | chute::funnel::BRASS
                ) {
                    let mut changed = false;
                    for slot in &mut entity.items {
                        let Some(stack) = slot else { continue };
                        let moved = insert_output(game, below, &block, stack);
                        if moved != 0 {
                            stack.count -= moved;
                            if stack.count == 0 {
                                *slot = None;
                            }
                            changed = true;
                        }
                    }
                    // Direct input keeps the applied phase, even when the receiver
                    // takes the final result. Open-space ejection clears the cycle.
                    if changed || cycle != previous {
                        save(entity, cycle);
                    }
                    if changed {
                        game.native_block_entity_sync(pos);
                    }
                    return;
                }
                if !game.res.behaviours().is_air(state) {
                    return;
                }
                for stack in entity.items.iter_mut().filter_map(Option::take) {
                    eject(game, pos, stack);
                }
                save(entity, Cycle::default());
                game.native_block_entity_sync(pos);
            }
        }
    }
}

pub(super) fn container() -> ModContainer {
    ModContainer {
        slots: SLOTS,
        faces: std::array::from_fn(|_| Vec::new()),
        inputs: Vec::new(),
        outputs: Vec::new(),
        menu: None,
    }
}

pub(super) fn default_nbt() -> Compound {
    let cycle = CuttingCycle::default();
    Compound::from([
        (
            INVENTORY.into(),
            processing_inventory(&[], cycle.remaining, cycle.duration, cycle.applied),
        ),
        ("RecipeIndex".into(), Tag::Int(0)),
    ])
}

/// These fields are recreated by the ordinary idle Saw factory after landing.
/// Non-default recipes, filters, or inventory data still require cargo storage.
pub(super) fn idle_capture_field(key: &str, tag: &Tag) -> bool {
    match key {
        INVENTORY => {
            let idle = CuttingCycle::default();
            *tag == processing_inventory(&[], idle.remaining, idle.duration, idle.applied)
        }
        "RecipeIndex" => *tag == Tag::Int(0),
        "Filter" => matches!(tag, Tag::Compound(filter) if filter.is_empty()),
        "FilterAmount" => *tag == Tag::Int(64),
        "UpTo" => *tag == Tag::Byte(1),
        _ => false,
    }
}

fn cycle(entity: &ModBlockEntity) -> Option<CuttingCycle> {
    let Some(saved) = entity.nbt.get(&INVENTORY.into()) else {
        return Some(CuttingCycle::default());
    };
    let Tag::Compound(saved) = saved else {
        return None;
    };
    if create::integer(saved, "Size") != SLOTS as i32 {
        return None;
    }
    let remaining = create::number(saved, "ProcessingTime");
    let duration = create::number(saved, "RecipeTime");
    if !remaining.is_finite() || remaining < -1.0 || !duration.is_finite() || duration < 0.0 {
        return None;
    }
    Some(CuttingCycle {
        remaining,
        duration,
        applied: create::integer(saved, "AppliedRecipe") != 0,
        recipe_index: create::integer(&entity.nbt, "RecipeIndex").max(0) as usize,
    })
}

fn save(entity: &mut ModBlockEntity, cycle: CuttingCycle) {
    let inventory = processing_inventory(
        &entity.items,
        cycle.remaining,
        cycle.duration,
        cycle.applied,
    );
    entity.nbt.insert(INVENTORY.into(), inventory);
    entity
        .nbt
        .insert("RecipeIndex".into(), Tag::Int(cycle.recipe_index as i32));
}

fn processing_inventory(
    items: &[Option<ItemStack>],
    remaining: f32,
    duration: f32,
    applied: bool,
) -> Tag {
    let items = items
        .iter()
        .enumerate()
        .filter_map(|(slot, stack)| {
            let Tag::Compound(mut item) = horizon_items::item_nbt::item_to_nbt(stack.as_ref()?)
            else {
                return None;
            };
            item.insert("Slot".into(), Tag::Int(slot as i32));
            Some(Tag::Compound(item))
        })
        .collect();
    Tag::Compound(Compound::from([
        ("Size".into(), Tag::Int(SLOTS as i32)),
        ("Items".into(), Tag::List(items)),
        ("ProcessingTime".into(), Tag::Float(remaining.to_bits())),
        ("RecipeTime".into(), Tag::Float(duration.to_bits())),
        ("AppliedRecipe".into(), Tag::Byte(i8::from(applied))),
    ]))
}

struct CuttingRecipe {
    duration: u32,
    outputs: Vec<(ItemStack, f32)>,
}

pub(super) fn read_filter(game: &Game<'_>, entity: &ModBlockEntity) -> Option<Option<ItemStack>> {
    let Some(saved) = entity.nbt.get(&"Filter".into()) else {
        return Some(None);
    };
    if matches!(saved, Tag::Compound(values) if values.is_empty()) {
        return Some(None);
    }
    let item = item_from_nbt(saved)?;
    ordinary_filter_item(game, &item).then_some(Some(item))
}

pub(super) fn ordinary_filter_item(game: &Game<'_>, item: &ItemStack) -> bool {
    item.count != 0
        && !matches!(
            item.item.as_ref(),
            "create:filter" | "create:attribute_filter" | "create:package_filter"
        )
        && game.items().get(&item.item).is_some()
}

fn cutting_recipes(
    game: &Game<'_>,
    input: &ItemStack,
    filter: Option<&ItemStack>,
) -> Vec<CuttingRecipe> {
    let accepts = |item: &ItemStack| filter.is_none_or(|filter| filter.item == item.item);
    let custom = game.native_recipes_of_type("create:cutting");
    let mut recipes: Vec<_> = custom
        .iter()
        .filter_map(|recipe| {
            if !saw_processing::automated_recipe(&recipe.id) {
                return None;
            }
            let [ingredient] = recipe.json["ingredients"].as_array()?.as_slice() else {
                return None;
            };
            // Bundled single-item recipes use qualified strings. Skip
            // unrelated ones before resolving tags or allocating ingredients.
            if ingredient.as_str().is_some_and(|id| {
                !id.starts_with('#') && id.contains(':') && id != input.item.as_ref()
            }) {
                return None;
            }
            let ingredient = create::ingredient(ingredient)
                .and_then(|json| game.native_recipe_ingredient(&json))?;
            if !ingredient.test(input) {
                return None;
            }
            let duration = recipe
                .json
                .get("processing_time")
                .or_else(|| recipe.json.get("processingTime"))
                .map_or(Some(0), |value| u32::try_from(value.as_u64()?).ok())?;
            let results = recipe.json["results"].as_array()?;
            if !(1..=4).contains(&results.len()) {
                return None;
            }
            let outputs = results
                .iter()
                .map(|output| {
                    let chance = output
                        .get("chance")
                        .map_or(Some(1.0), |value| value.as_f64())?;
                    if !(0.0..=1.0).contains(&chance) {
                        return None;
                    }
                    let stack = if output.get("id").is_some() {
                        game.native_recipe_result(output)
                    } else {
                        let mut output = output.clone();
                        output["id"] = output["item"].clone();
                        game.native_recipe_result(&output)
                    }?;
                    Some((stack, chance as f32))
                })
                .collect::<Option<Vec<_>>>()?;
            accepts(&outputs[0].0)
                .then_some((recipe.id.as_str(), CuttingRecipe { duration, outputs }))
        })
        .collect();
    // The same authoritative provider as the native Stonecutter, including
    // merged world recipes and item tags. The original default enables these.
    recipes.extend(
        game.stations()
            .recipes
            .stonecutting
            .iter()
            .filter_map(|recipe| {
                let id = saw_processing::stonecutting_source_id(&recipe.id)?;
                (saw_processing::automated_recipe(id)
                    && recipe.input.test(input)
                    && accepts(&recipe.result)
                    && game.items().get(&recipe.result.item).is_some())
                .then(|| {
                    (
                        id,
                        CuttingRecipe {
                            duration: 50,
                            outputs: vec![(recipe.result.clone(), 1.0)],
                        },
                    )
                })
            }),
    );
    recipes.sort_by_key(|(id, _)| saw_processing::source_recipe_order(id));
    recipes.into_iter().map(|(_, recipe)| recipe).collect()
}

fn start(game: &Game<'_>, cycle: &mut CuttingCycle, input: &ItemStack, filter: Option<&ItemStack>) {
    let durations: Vec<_> = cutting_recipes(game, input, filter)
        .into_iter()
        .map(|recipe| recipe.duration)
        .collect();
    cycle.start(input.count, &durations);
}

fn apply(
    game: &mut Game<'_>,
    entity: &mut ModBlockEntity,
    input: &ItemStack,
    recipe: &CuttingRecipe,
) {
    entity.items.fill(None);
    let remainder = game
        .items()
        .get(&input.item)
        .and_then(|item| item.crafting_remainder.as_ref())
        .map(|id| ItemStack::new(id, 1));
    for _ in 0..input.count {
        for (stack, chance) in &recipe.outputs {
            let mut output = stack.clone();
            output.count = roll_count(output.count, *chance, || game.world.random.next_float());
            if output.count > 0 {
                let max = create::stack_maximum(game, &output);
                super::create_port_inventory::insert(&mut entity.items[1..], output, max);
            }
        }
        if let Some(output) = &remainder {
            let max = create::stack_maximum(game, output);
            super::create_port_inventory::insert(&mut entity.items[1..], output.clone(), max);
        }
    }
}

pub(super) fn insert_from_transport(
    game: &mut Game<'_>,
    pos: Pos,
    stack: &ItemStack,
    simulate: bool,
) -> u32 {
    if stack.count == 0
        || !game.native_on("create")
        || game.native_block(pos) != super::create_port_drill::SAW
        || game.native_block_property(pos, "facing").as_deref() != Some("up")
    {
        return 0;
    }
    let Some(BlockEntity::Mod(entity)) = game.world.block_entities.get(&(pos[0], pos[1], pos[2]))
    else {
        return 0;
    };
    if entity.id != "create:saw"
        || entity.items.len() != SLOTS
        || entity.items.iter().any(Option::is_some)
    {
        return 0;
    }
    let (Some(filter), Some(mut cycle)) = (read_filter(game, entity), cycle(entity)) else {
        return 0;
    };
    if simulate {
        return 1;
    }
    let mut inserted = stack.clone();
    inserted.count = 1;
    start(game, &mut cycle, &inserted, filter.as_ref());
    if game
        .native_with_mod_block_entity(pos, |entity| {
            entity.items[0] = Some(inserted);
            save(entity, cycle);
        })
        .is_none()
    {
        return 0;
    }
    game.native_block_entity_sync(pos);
    1
}

pub(super) fn landed(game: &mut Game<'_>, pos: Pos, stack: &mut ItemStack) -> bool {
    let [x, y, z] = pos;
    let Some(BlockEntity::Mod(entity)) = game.world.block_entities.get(&(x, y, z)) else {
        return false;
    };
    if game.clock.frozen() || create::number(&entity.nbt, "Speed") == 0.0 {
        return false;
    }
    if insert_from_transport(game, pos, stack, false) == 0 {
        return false;
    }
    stack.count -= 1;
    true
}

pub(super) fn tick(game: &mut Game<'_>, pos: Pos, entity: &mut ModBlockEntity, rpm: f32) -> bool {
    if entity.items.len() != SLOTS {
        return false;
    }
    let (Some(filter), Some(mut cycle)) = (read_filter(game, entity), cycle(entity)) else {
        return false;
    };
    let first = game
        .native_block_property(pos, "axis_along_first")
        .as_deref()
        == Some("true");
    let motion = saw_processing::item_motion(first, rpm);
    let Some(input) = entity.items[0]
        .as_ref()
        .filter(|item| item.count > 0)
        .cloned()
        .or_else(|| entity.items.iter().flatten().next().cloned())
    else {
        return false;
    };
    let previous = cycle;
    match cycle.tick(rpm, entity.items[0].is_some()) {
        Action::Idle => return false,
        Action::Start => start(game, &mut cycle, &input, filter.as_ref()),
        Action::Advance => {}
        Action::Apply => {
            let recipes = cutting_recipes(game, &input, filter.as_ref());
            if let Some(index) = cycle.select_current(recipes.len()) {
                apply(game, entity, &input, &recipes[index]);
            }
            cycle.finish_application();
            activation_sound(game, pos, &input);
        }
        Action::Export => {
            use super::create_port_chute as chute;

            let target = std::array::from_fn(|axis| pos[axis] + motion[axis]);
            let target_block = game.native_block(target);
            let millstone = target_block == "create:millstone";
            if millstone
                || chute::is_chute(&target_block)
                || chute::funnel::is_funnel(&target_block)
                || matches!(target_block.as_str(), "create:depot" | "create:belt")
            {
                let from = Direction::from_vector(motion).expect("horizontal saw output");
                let mut changed = false;
                for slot in &mut entity.items {
                    let Some(stack) = slot else { continue };
                    let remaining = match target_block.as_str() {
                        "create:millstone" => {
                            // The source uses the Millstone's recipe-filtered capability.
                            game.native_insert_item(
                                target,
                                belt::world_direction(from),
                                stack.clone(),
                            )
                            .map_or(0, |remainder| remainder.count)
                        }
                        chute::BLOCK | chute::SMART => {
                            stack.count - chute::insert_from_transport(game, target, stack)
                        }
                        chute::funnel::BLOCK | chute::funnel::BRASS => {
                            stack.count
                                - chute::funnel::insert_from_transport(
                                    game,
                                    target,
                                    &target_block,
                                    stack,
                                )
                        }
                        _ => {
                            let item = Transported::new(
                                belt::core_stack(game, stack.clone()),
                                belt::angle(game, stack),
                            );
                            if target_block == "create:depot" {
                                stack.count
                                    - belt::insert_depot_from_side(game, target, &item, from)
                            } else if belt::insert_belt_from_side(game, target, &item, from, false)
                            {
                                0
                            } else {
                                stack.count
                            }
                        }
                    };
                    if remaining != stack.count {
                        if remaining == 0 {
                            *slot = None;
                        } else {
                            stack.count = remaining;
                        }
                        changed = true;
                    }
                }
                if changed && millstone {
                    super::create_port_millstone::publish_inventory(game, target);
                }
                // Direct input retains the finished phase. Keep rejected
                // stacks in their slots and try again on the next tick.
                if !changed && cycle == previous {
                    return false;
                }
            } else {
                let motion = motion.map(f64::from);
                let at = [
                    f64::from(pos[0]) + 0.5 + motion[0] * 0.5,
                    f64::from(pos[1]) + 1.0,
                    f64::from(pos[2]) + 0.5 + motion[2] * 0.5,
                ];
                let velocity = [motion[0] * 0.0625, 0.125, motion[2] * 0.0625];
                for stack in entity.items.iter_mut().filter_map(Option::take) {
                    game.spawn_item(stack, at, velocity, 0);
                }
                cycle.finish_export();
            }
        }
    }
    save(entity, cycle);
    true
}

fn activation_sound(game: &mut Game<'_>, pos: Pos, input: &ItemStack) {
    let is_wood = game
        .pack
        .assets
        .registry
        .default_state(&input.item)
        .is_some_and(|id| {
            game.res.facts().get(id).sounds.place.as_ref() == "minecraft:block.wood.place"
        });
    let (sound, volume, pitch) = if is_wood {
        ("minecraft:entity.boat.paddle_land", 2.25, 1.5)
    } else {
        ("minecraft:ui.stonecutter.take_result", 0.375, 1.25)
    };
    let at = pos.map(|v| f64::from(v) + 0.5);
    game.with_level(|_, level, _| {
        level.native_play_sound(sound, at, 4, volume, pitch);
    });
}

pub(super) fn draw(game: &Game<'_>, pos: Pos, entity: &ModBlockEntity, draw: &mut BlockEntityDraw) {
    let Some(Tag::List(stacks)) = entity
        .nbt
        .get(&INVENTORY.into())
        .and_then(|t| t.get("Items"))
    else {
        return;
    };
    // The supported default recipe emits a single output stack.
    let [saved] = stacks.as_slice() else { return };
    let Some(stack) = horizon_items::item_nbt::item_from_nbt(saved) else {
        return;
    };
    let Some(cycle) = cycle(entity) else { return };
    let rpm = create::number(&entity.nbt, "Speed");
    let along_z = game
        .native_block_property(pos, "axis_along_first")
        .as_deref()
        != Some("true");
    let mut offset = if rpm == 0.0 {
        0.5
    } else if cycle.duration > 0.0 {
        let speed = (rpm.abs() / 32.0).clamp(1.0, 128.0);
        let offset =
            ((cycle.remaining + (0.5 - draw.partial) * speed) / cycle.duration).clamp(0.125, 1.0);
        (offset + if cycle.applied { 0.0 } else { 1.0 }) / 2.0
    } else {
        0.0
    };
    if (rpm < 0.0) ^ along_z {
        offset = 1.0 - offset;
    }
    let block = game
        .pack
        .assets
        .registry
        .default_state(&stack.item)
        .is_some();
    draw.push();
    if along_z {
        draw.rotate_about([0.0, 1.0, 0.0], 90.0, [0.0; 3]);
    }
    draw.translate([
        if along_z { -0.5 } else { 0.5 },
        if block { 0.925 } else { 13.0 / 16.0 },
        offset,
    ]);
    draw.scale([0.5; 3]);
    draw.rotate_about([1.0, 0.0, 0.0], 90.0, [0.0; 3]);
    game.native_draw_item(
        draw,
        &stack,
        horizon_assets::item_model::DisplayContext::Fixed,
        None,
        0,
    );
    draw.pop();
}
