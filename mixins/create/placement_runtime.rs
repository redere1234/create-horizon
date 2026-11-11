// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT
// Vanilla placement remains responsible for obstruction, permissions and consumption.
use super::{Game, GameLevel, create_port_contraption_actors as actors};
use crate::items::ItemStack;
use create_engine::{
    kinetics::Axis,
    placement::{self, Direction},
};
use horizon_core::{
    geometry::{Direction as D, Vec3},
    position::BlockPos,
};
use horizon_world::{
    collision_context::CollisionContext,
    fluid::FluidState,
    level::{PlaceContext, PlaceOutcome, PlacementContext},
    registry::BlockStateId,
};

fn direction(d: D) -> Direction {
    match d {
        D::Down => Direction::Down,
        D::Up => Direction::Up,
        D::North => Direction::North,
        D::South => Direction::South,
        D::West => Direction::West,
        D::East => Direction::East,
    }
}
fn ports(game: &Game<'_>, pos: [i32; 3]) -> [bool; 6] {
    Direction::ALL.map(|d| {
        let delta = d.vector();
        super::create_port::node(game, std::array::from_fn(|i| pos[i] + delta[i]))
            .is_some_and(|n| n.shaft_port(delta.map(|v| -v)))
    })
}
pub(super) fn horizontal(yaw: f32) -> Direction {
    [
        Direction::South,
        Direction::West,
        Direction::North,
        Direction::East,
    ][((f64::from(yaw) / 90.0 + 0.5).floor() as i64 & 3) as usize]
}
pub(super) fn state(
    game: &GameLevel<'_>,
    mut state: BlockStateId,
    ctx: &PlacementContext,
    fluid: FluidState,
    answer: &mut Option<Option<BlockStateId>>,
) {
    let block = game.native_state_block(state).unwrap_or("");
    if block == "create:hand_crank" {
        let pos = [ctx.pos.x, ctx.pos.y, ctx.pos.z];
        let facing = placement::crank(direction(ctx.face), ctx.sneaking, level_ports(game, pos));
        let waterlogged = if fluid == FluidState::WATER { "true" } else { "false" };
        *answer = Some(
            game.native_state_with_property(state, "facing", facing.name())
                .and_then(|state| game.native_state_with_property(state, "waterlogged", waterlogged)),
        );
        return;
    }
    if matches!(block, super::create_port_basin::pump::PIPE | super::create_port_basin::pump::PUMP | super::create_port_basin::pump::VALVE) {
        *answer = Some(super::create_port_basin::pump::placement(game, state, ctx, block));
        return;
    }
    if block == super::create_port_basin::tank::BLOCK {
        *answer = Some(super::create_port_basin::tank::placement(game, ctx).then_some(state));
        return;
    }
    if block == super::create_port_chute::BLOCK {
        *answer = Some(super::create_port_chute::placement(game, state, ctx));
        return;
    }
    if let Some(large) = super::create_port_interactions::encased_cog_size(block) {
        let pos = [ctx.pos.x, ctx.pos.y, ctx.pos.z];
        let face = direction(ctx.face);
        let [dx, dy, dz] = face.vector();
        let read = |p: [i32; 3]| game.registry.state(game.world.block(p[0], p[1], p[2]));
        let axis = read([pos[0] - dx, pos[1] - dy, pos[2] - dz])
            .filter(|support| cog_size(&support.name) == Some(false))
            .map(state_axis)
            .unwrap_or_else(|| {
                let look = super::create_port::nearest(ctx.yaw, ctx.pitch);
                placement::shaft(look, face, ctx.sneaking, level_ports(game, pos))
            });
        *answer = Some(if cog_survives(pos, axis, large, read) {
            game.native_state_with_property(state, "axis", axis.name())
        } else {
            None
        });
        return;
    }
    if block == super::create_port_saw_processing::crafter::BLOCK {
        use create_engine::crafter::Pointing;
        let face = direction(ctx.face);
        let facing = horizontal(ctx.yaw).opposite();
        let [dx, dy, dz] = face.vector();
        let support = game.registry.state(game.world.block(ctx.pos.x - dx, ctx.pos.y - dy, ctx.pos.z - dz));
        let other = support.filter(|support| !ctx.sneaking && support.name == block)
            .and_then(|support| support.properties.get("facing"))
            .and_then(|name| Direction::ALL.into_iter().find(|side| side.name() == name));
        let facing = other.unwrap_or(facing);
        let pointing = if other.is_some() || facing != face {
            Pointing::from_clicked_face(face, facing)
        } else {
            Pointing::Up
        };
        *answer = Some(game.native_state_with_property(state, "facing", facing.name())
            .and_then(|state| game.native_state_with_property(state, "pointing", pointing.name())));
        return;
    }
    if block == super::create_port_saw_processing::crushing::WHEEL {
        use super::create_port_saw_processing::crushing::{CONTROLLER, WHEEL};
        let pos = [ctx.pos.x, ctx.pos.y, ctx.pos.z];
        let face = direction(ctx.face);
        let look = super::create_port::nearest(ctx.yaw, ctx.pitch);
        let axis = placement::shaft(look, face, ctx.sneaking, level_ports(game, pos));
        let survives = Direction::ALL.into_iter().all(|side| {
            let [x, y, z] = side.vector();
            game.registry
                .state(game.world.block(pos[0] + x, pos[1] + y, pos[2] + z))
                .is_none_or(|adjacent| match adjacent.name.as_str() {
                    CONTROLLER => side.axis() == axis,
                    WHEEL => side.axis() == axis && state_axis(adjacent) == axis,
                    _ => true,
                })
        });
        *answer = Some(if survives {
            game.native_state_with_property(state, "axis", match axis {
                Axis::X => "x",
                Axis::Y => "y",
                Axis::Z => "z",
            })
        } else {
            None
        });
        return;
    }
    if super::create_port_chute::funnel::is_funnel(block) {
        *answer = Some(super::create_port_chute::funnel::placement(
            game,
            state,
            ctx,
            direction(ctx.face),
        ));
        return;
    }
    if matches!(
        block,
        super::create_port_portable_storage::BLOCK | super::create_port_sticker::BLOCK
    ) {
        let look = super::create_port::nearest(ctx.yaw, ctx.pitch);
        let facing = if ctx.sneaking { look } else { look.opposite() };
        *answer = Some(game.native_state_with_property(state, "facing", facing.name()));
        return;
    }
    if super::create_port_chassis::is_chassis(block) {
        *answer = Some(super::create_port_chassis::placement(
            game,
            block,
            state,
            ctx,
            direction(ctx.face),
        ));
        return;
    }
    if create_engine::sail::material(block).is_some() {
        let facing = super::create_port::nearest(ctx.yaw, ctx.pitch).opposite();
        *answer = Some(game.native_state_with_property(state, "facing", facing.name()));
        return;
    }
    if matches!(
        block,
        super::create_port_gantry::SHAFT | super::create_port_gantry::CARRIAGE
    ) {
        *answer = Some(super::create_port_gantry::placement(
            game,
            state,
            block,
            ctx,
            direction(ctx.face),
        ));
        return;
    }
    if super::create_port_chain::is_chain(block) {
        *answer = Some(super::create_port_chain::placement(game, state, ctx));
        return;
    }
    if block == super::create_port_pulley::BLOCK {
        let p = [ctx.pos.x, ctx.pos.y, ctx.pos.z];
        let mut ports = level_ports(game, p);
        ports[Direction::Up as usize] = false;
        ports[Direction::Down as usize] = false;
        let axis = placement::preferred(ports).map_or_else(
            || horizontal(ctx.yaw).clockwise(Axis::Y).axis(),
            Direction::axis,
        );
        *answer = Some(game.native_state_with_property(
            state,
            "axis",
            if axis == Axis::X { "x" } else { "z" },
        ));
        return;
    }
    if super::create_port_contraption::is_bearing(block) {
        let pos = [ctx.pos.x, ctx.pos.y, ctx.pos.z];
        let look = super::create_port::nearest(ctx.yaw, ctx.pitch);
        let preferred = placement::preferred(level_ports(game, pos)).unwrap_or(look);
        let facing = if ctx.sneaking {
            look
        } else {
            preferred.opposite()
        };
        *answer = Some(game.native_state_with_property(state, "facing", facing.name()));
        return;
    }
    if super::create_port_piston::is_piston(block)
        || matches!(
            block,
            "create:mechanical_saw" | super::create_port_deployer::BLOCK
        )
    {
        let pos = [ctx.pos.x, ctx.pos.y, ctx.pos.z];
        let look = super::create_port::nearest(ctx.yaw, ctx.pitch);
        let facing = if ctx.sneaking { look } else { look.opposite() };
        let ports = level_ports(game, pos);
        let has = |side: Direction| ports[side as usize];
        let first = match facing.axis() {
            Axis::X => has(Direction::Up) || has(Direction::Down),
            Axis::Z => !has(Direction::Up) && !has(Direction::Down),
            Axis::Y => {
                let x = has(Direction::East) || has(Direction::West);
                let z = has(Direction::North) || has(Direction::South);
                if x != z {
                    x
                } else {
                    horizontal(ctx.yaw).axis() == Axis::X
                }
            }
        };
        *answer = Some(
            game.native_state_with_property(state, "facing", facing.name())
                .and_then(|id| {
                    game.native_state_with_property(
                        id,
                        "axis_along_first",
                        if first { "true" } else { "false" },
                    )
                }),
        );
        if block == "create:mechanical_saw" {
            let positive = matches!(horizontal(ctx.yaw), Direction::South | Direction::East);
            let flipped = facing.axis() == Axis::Y && positive;
            if let Some(Some(id)) = *answer {
                *answer = Some(game.native_state_with_property(
                    id,
                    "flipped",
                    if flipped { "true" } else { "false" },
                ));
            }
        }
        return;
    }
    if block == super::create_port_piston::POLE {
        *answer = Some(game.native_state_with_property(
            state,
            "facing",
            direction(ctx.face).opposite().name(),
        ));
        return;
    }
    if actors::attached_actor(block) {
        let face = direction(ctx.face);
        let facing = if face.axis() == Axis::Y {
            horizontal(ctx.yaw).opposite()
        } else {
            let [x, y, z] = face.vector();
            let support = game
                .world
                .block(ctx.pos.x - x, ctx.pos.y - y, ctx.pos.z - z);
            game.registry
                .state(support)
                .filter(|s| actors::attached_actor(&s.name))
                .and_then(|s| s.properties.get("facing"))
                .and_then(|f| Direction::ALL.into_iter().find(|d| d.name() == f))
                .unwrap_or(face)
        };
        let [x, _, z] = facing.vector();
        let support = game.world.block(ctx.pos.x - x, ctx.pos.y, ctx.pos.z - z);
        let sturdy_face = match facing {
            Direction::North => D::North,
            Direction::East => D::East,
            Direction::South => D::South,
            Direction::West => D::West,
            _ => unreachable!("attached actors only use horizontal facings"),
        };
        *answer = Some(
            (game.behaviours.is_face_sturdy(support, sturdy_face)
                && !game.facts.get(support).has_class("LeavesBlock"))
            .then(|| game.native_state_with_property(state, "facing", facing.name()))
            .flatten(),
        );
        return;
    }
    if block == "create:blaze_burner" {
        // BlazeBurnerBlock.getStateForPlacement reads the actual BlockItem,
        // including the empty item alias. Other placement callers get the
        // block default unchanged, as in the original instanceof guard.
        let heat = match ctx.item.as_str() {
            "create:blaze_burner" => "smouldering",
            "create:empty_blaze_burner" => "none",
            _ => {
                *answer = Some(Some(state));
                return;
            }
        };
        state = game
            .native_state_with_property(state, "blaze", heat)
            .unwrap_or(state);
        state = game
            .native_state_with_property(state, "facing", horizontal(ctx.yaw).opposite().name())
            .unwrap_or(state);
        *answer = Some(Some(state));
        return;
    }
    if !matches!(
        block,
        "create:speedometer"
            | "create:encased_fan"
            | "create:mechanical_drill"
            | "create:stressometer"
            | "create:water_wheel"
            | "create:large_water_wheel"
    ) {
        return;
    }
    let pos = [ctx.pos.x, ctx.pos.y, ctx.pos.z];
    let face = direction(ctx.face);
    let look = super::create_port::nearest(ctx.yaw, ctx.pitch);
    let ports = level_ports(game, pos);
    let mut set = |name: &str, value: &str| {
        if let Some(s) = game.native_state_with_property(state, name, value) {
            state = s;
        }
    };
    if matches!(block, "create:encased_fan" | "create:mechanical_drill") {
        let preferred = placement::preferred(ports).unwrap_or(look);
        set(
            "facing",
            if ctx.sneaking {
                preferred.name()
            } else {
                preferred.opposite().name()
            },
        );
    } else if block.ends_with("ometer") {
        let attached = ports[Direction::ALL
            .iter()
            .position(|d| *d == face.opposite())
            .unwrap()];
        let (facing, first) = placement::gauge(face, look, horizontal(ctx.yaw), ports, attached);
        set("facing", facing.name());
        set("axis_along_first", if first { "true" } else { "false" });
    } else {
        let facing = if !ctx.sneaking {
            placement::preferred(ports)
                .map(Direction::opposite)
                .unwrap_or(look.opposite())
        } else {
            look
        };
        let axis = if block == "create:water_wheel" {
            facing.axis()
        } else {
            placement::shaft(look, face, ctx.sneaking, ports)
        };
        if block == "create:large_water_wheel" {
            if !create_engine::waterwheel::structure(axis)
                .into_iter()
                .all(|delta| {
                    let p: [i32; 3] = std::array::from_fn(|i| pos[i] + delta[i]);
                    game.facts
                        .get(game.world.block(p[0], p[1], p[2]))
                        .replaceable
                })
            {
                if std::env::var_os("CREATE_HORIZON_TRACE").is_some() {
                    log::info!("Create placement refused: {:?} {:?}", pos, axis);
                }
                *answer = Some(None);
                return;
            }
            if std::env::var_os("CREATE_HORIZON_TRACE").is_some() {
                log::info!("Create placement accepted: {:?} {:?}", pos, axis);
            }
            set(
                "axis",
                match axis {
                    Axis::X => "x",
                    Axis::Y => "y",
                    Axis::Z => "z",
                },
            );
        } else {
            for d in Direction::ALL {
                let delta = d.vector();
                let p = std::array::from_fn(|i| pos[i] + delta[i]);
                if game
                    .facts
                    .get(game.world.block(p[0], p[1], p[2]))
                    .name
                    .as_ref()
                    == "create:water_wheel"
                    && (level_axis(game, p) != axis || d.axis() != axis)
                {
                    *answer = Some(None);
                    return;
                }
            }
            set("facing", facing.name());
        }
    }
    *answer = Some(Some(state));
}

fn crank_support(game: &GameLevel<'_>, state: BlockStateId) -> Option<Direction> {
    let state = game.registry.state(state)?;
    if state.name != "create:hand_crank" {
        return None;
    }
    let facing = state.properties.get("facing")?;
    Direction::ALL
        .into_iter()
        .find(|side| side.name() == facing)
        .map(Direction::opposite)
}

fn has_collision(game: &GameLevel<'_>, pos: BlockPos) -> bool {
    let mut scene = horizon_client::collisions::SceneCollisions {
        world: game.world,
        binding: game.collision,
        subject: None,
    };
    game.collision
        .collision_shape_with_context(
            &mut scene,
            game.world.block(pos.x, pos.y, pos.z),
            pos,
            &CollisionContext::empty(false),
        )
        .is_ok_and(|shape| !shape.is_empty())
}

pub(super) fn crank_can_survive(
    game: &GameLevel<'_>,
    pos: BlockPos,
    state: BlockStateId,
    survives: &mut Option<bool>,
) {
    if let Some(side) = crank_support(game, state) {
        let [dx, dy, dz] = side.vector();
        *survives = Some(has_collision(game, BlockPos::new(pos.x + dx, pos.y + dy, pos.z + dz)));
    }
}

pub(super) fn crank_update_shape(
    game: &GameLevel<'_>,
    ticks: &mut horizon_world::level::Ticks,
    pos: BlockPos,
    state: BlockStateId,
    changed: D,
    neighbor_pos: BlockPos,
    new: &mut Option<BlockStateId>,
) {
    let Some(support) = crank_support(game, state) else {
        return;
    };
    if game.facts.get(state).waterlogged {
        game.native_schedule_fluid_tick(ticks, [pos.x, pos.y, pos.z], "minecraft:water", 5);
    }
    // A shape prepass also runs for blocks that have yet to be placed.
    if support == direction(changed)
        && game.world.block(pos.x, pos.y, pos.z) == state
        && !has_collision(game, neighbor_pos)
    {
        // updateOrDestroy drops the crank and retains its fluid, if any.
        *new = Some(game.world.air);
    }
}

pub(super) fn alias(game: &mut Game<'_>, stack: &ItemStack, pos: [i32; 3], face: [i32; 3]) -> bool {
    if !game.native_on("create")
        || !matches!(
            stack.item.as_ref(),
            "create:vertical_gearbox" | "create:large_water_wheel"
        )
    {
        return false;
    }
    if !game.may_build() && !game.can_place_on_in_adventure(pos) {
        return true;
    }
    let Some(d) = Direction::from_vector(face) else {
        return true;
    };
    let vertical = stack.item.as_ref() == "create:vertical_gearbox";
    let mut ctx = PlaceContext {
        clicked_pos: BlockPos::new(pos[0], pos[1], pos[2]),
        face: match d {
            Direction::Down => D::Down,
            Direction::Up => D::Up,
            Direction::North => D::North,
            Direction::South => D::South,
            Direction::West => D::West,
            Direction::East => D::East,
        },
        hit: Vec3::new(
            f64::from(pos[0]) + 0.5 + f64::from(face[0]) * 0.5,
            f64::from(pos[1]) + 0.5 + f64::from(face[1]) * 0.5,
            f64::from(pos[2]) + 0.5 + f64::from(face[2]) * 0.5,
        ),
        inside: false,
        yaw: game.yaw,
        pitch: game.pitch,
        sneaking: game.keys.contains(&winit::keyboard::KeyCode::ShiftLeft),
        item: if vertical {
            "create:gearbox".into()
        } else {
            stack.item.to_string()
        },
        can_use_game_master_blocks: game.can_use_game_master_blocks(),
    };
    let mut outcome = game.with_level(|b, l, t| b.place_block(l, t, &ctx));
    if std::env::var_os("CREATE_HORIZON_TRACE").is_some() {
        log::info!("Create placement initial: {outcome:?}");
    }
    if !vertical && matches!(outcome, PlaceOutcome::Failed) {
        let p = if super::create_port_generators::replaceable(game, pos) {
            pos
        } else {
            std::array::from_fn(|i| pos[i] + face[i])
        };
        let axis = placement::shaft(
            super::create_port::nearest(game.yaw, game.pitch),
            d,
            ctx.sneaking,
            ports(game, p),
        );
        if axis != d.axis() {
            ctx.clicked_pos = BlockPos::new(p[0] + face[0], p[1] + face[1], p[2] + face[2]);
            ctx.hit = Vec3::new(
                ctx.hit.x + f64::from(face[0]),
                ctx.hit.y + f64::from(face[1]),
                ctx.hit.z + f64::from(face[2]),
            );
            outcome = game.with_level(|b, l, t| b.place_block(l, t, &ctx));
        }
    }
    if let PlaceOutcome::Placed { pos, state } = outcome {
        let target = [pos.x, pos.y, pos.z];
        if let Some(entity) = game.new_block_entity(if vertical {
            "create:gearbox"
        } else {
            "create:large_water_wheel"
        }) {
            game.world
                .block_entities
                .insert((pos.x, pos.y, pos.z), entity);
        }
        if vertical {
            let axis = placement::vertical_gearbox(horizontal(game.yaw), ports(game, target));
            game.native_set_block_property(target, "axis", if axis == Axis::X { "x" } else { "z" });
        }
        game.award_stat("used", &stack.item, 1);
        game.trigger_block("minecraft:placed_block", target, stack);
        game.native_place_block(stack, target, state);
        game.consume_held();
        super::create_port_kinetic_runtime::invalidate();
    } else {
        game.use_failed = true;
    }
    if let Err(error) = game.process_level_events() {
        log::warn!("Create placement: {error}");
    }
    true
}

pub(super) fn destroy(game: &mut Game<'_>, pos: [i32; 3], canceled: &mut bool) {
    if !game.native_on("create") {
        return;
    }
    if !*canceled {
        super::create_port_saw_processing::crafter::removed(game, pos);
        super::create_port_pulley::break_line(game, pos);
        super::create_port_piston::break_static_line(game, pos);
    }
    let block = game.native_block(pos);
    if !matches!(
        block.as_str(),
        "create:water_wheel_structure" | "create:large_water_wheel"
    ) {
        return;
    }
    let Some(master) = super::create_port_generators::master(game, pos) else {
        return;
    };
    let axis = super::create_port::node(game, master).map_or(Axis::X, |n| n.axis);
    let dim = game.dim.id().to_owned();
    let air = game
        .pack
        .assets
        .registry
        .default_state("minecraft:air")
        .unwrap();
    for delta in create_engine::waterwheel::structure(axis) {
        let p = std::array::from_fn(|i| master[i] + delta[i]);
        if game.native_block(p) == "create:water_wheel_structure" {
            game.native_set_block(&dim, p, air, 3);
        }
    }
    game.native_set_block(&dim, master, air, 3);
    if !game.creative {
        game.spawn_item(
            ItemStack::new("create:large_water_wheel", 1),
            master.map(|v| f64::from(v) + 0.5),
            [0.0; 3],
            10,
        );
    }
    super::create_port_kinetic_runtime::invalidate();
    *canceled = true;
}

fn level_axis(game: &GameLevel<'_>, p: [i32; 3]) -> Axis {
    let state = game
        .registry
        .state(game.world.block(p[0], p[1], p[2]))
        .unwrap();
    state_axis(state)
}

fn state_axis(state: &horizon_world::chunk::BlockState) -> Axis {
    let prop = |key: &str| state.properties.get(key).map(String::as_str).unwrap_or("");
    let facing = Direction::ALL
        .into_iter()
        .find(|d| d.name() == prop("facing"))
        .unwrap_or(Direction::Up);
    if state.name.ends_with("ometer") || state.name == super::create_port_basin::pump::VALVE {
        return placement::gauge_axis(facing, prop("axis_along_first") == "true");
    }
    if state.name == "create:belt" {
        return if prop("slope") == "sideways" {
            Axis::Y
        } else if facing.axis() == Axis::X {
            Axis::Z
        } else {
            Axis::X
        };
    }
    match prop("axis") {
        "x" => Axis::X,
        "z" => Axis::Z,
        "y" => Axis::Y,
        _ => facing.axis(),
    }
}

pub(super) fn cog_size(block: &str) -> Option<bool> {
    match block {
        "create:large_cogwheel" => Some(true),
        "create:cogwheel"
        | "create:millstone"
        | "create:mechanical_mixer"
        | super::create_port_basin::pump::PUMP
        | super::create_port_saw_processing::crafter::BLOCK => Some(false),
        _ => super::create_port_interactions::encased_cog_size(block),
    }
}

pub(super) fn cog_survives<'a>(
    pos: [i32; 3],
    axis: Axis,
    large: bool,
    mut read: impl FnMut([i32; 3]) -> Option<&'a horizon_world::chunk::BlockState>,
) -> bool {
    Direction::ALL.into_iter().all(|side| {
        if side.axis() == axis {
            return true;
        }
        let delta = side.vector();
        read(std::array::from_fn(|i| pos[i] + delta[i])).is_none_or(|adjacent| {
            adjacent
                .properties
                .get("axis")
                .is_some_and(|axis| axis == side.axis().name())
                || match cog_size(&adjacent.name) {
                    Some(other_large) => !large && !other_large,
                    None => true,
                }
        })
    })
}

// IRotate.hasShaftTowards for implemented blocks. Ownership does not imply a shaft.
fn state_shaft_port(state: &horizon_world::chunk::BlockState, face: Direction) -> bool {
    let facing = || {
        state.properties.get("facing").and_then(|value| {
            Direction::ALL
                .into_iter()
                .find(|direction| direction.name() == value)
        })
    };
    match state.name.as_str() {
        block if super::create_port_interactions::encased_cog_size(block).is_some() => {
            face.axis() == state_axis(state)
                && state
                    .properties
                    .get(if face.vector()[face.axis().index()] > 0 {
                        "top_shaft"
                    } else {
                        "bottom_shaft"
                    })
                    .is_some_and(|open| open == "true")
        }
        "create:creative_motor" => facing() == Some(face),
        "create:hand_crank" | "create:encased_fan" | "create:mechanical_drill" => {
            facing() == Some(face.opposite())
        }
        "create:millstone" => face == Direction::Down,
        "create:gearbox" => state_axis(state) != face.axis(),
        "create:belt" => {
            state
                .properties
                .get("part")
                .is_some_and(|part| part != "middle")
                && state_axis(state) == face.axis()
        }
        "create:shaft"
        | super::create_port::FLYWHEEL
        | super::create_port_saw_processing::crushing::WHEEL
        | "create:andesite_encased_shaft"
        | "create:brass_encased_shaft"
        | "create:encased_chain_drive"
        | super::create_port_chain::ADJUSTABLE
        | "create:cogwheel"
        | "create:large_cogwheel"
        | "create:clutch"
        | "create:gearshift"
        | "create:mechanical_press"
        | "create:speedometer"
        | "create:stressometer"
        | super::create_port_basin::pump::VALVE
        | "create:water_wheel"
        | "create:large_water_wheel" => state_axis(state) == face.axis(),
        super::create_port_pulley::BLOCK => state_axis(state) == face.axis(),
        _ => false,
    }
}

pub(super) fn level_ports(game: &GameLevel<'_>, pos: [i32; 3]) -> [bool; 6] {
    Direction::ALL.map(|d| {
        let delta = d.vector();
        let p: [i32; 3] = std::array::from_fn(|i| pos[i] + delta[i]);
        let state = game
            .registry
            .state(game.world.block(p[0], p[1], p[2]))
            .unwrap();
        state_shaft_port(state, d.opposite())
    })
}
