// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use super::{
    Game, create_port_contraption as contraption, native_block_entity_draw::BlockEntityDraw,
};
use create_engine::{
    contraption::{
        CaptureView, Cell,
        sticker::{Head, State},
    },
    kinetics::Pos,
    placement::Direction,
};
use horizon_world::{
    chunk::BlockState,
    level::flags,
    nbt::{Compound, Tag},
    registry::BlockStateId,
};
use std::{
    cell::RefCell,
    collections::{BTreeMap, BTreeSet},
};

pub(super) const BLOCK: &str = "create:sticker";

thread_local! {
    static CHANGED: RefCell<BTreeMap<&'static str, BTreeSet<Pos>>> =
        const { RefCell::new(BTreeMap::new()) };
}

#[derive(Default)]
struct ClientHeads {
    world: Option<(usize, &'static str)>,
    active: BTreeMap<Pos, (Head, Option<bool>)>,
}

impl ClientHeads {
    fn check_world(&mut self, game: &Game<'_>) {
        let world = (std::ptr::from_ref(&game.world) as usize, game.dim.id());
        if self.world != Some(world) {
            self.world = Some(world);
            self.active.clear();
        }
    }
}

thread_local! {
    static HEADS: RefCell<ClientHeads> = const {
        RefCell::new(ClientHeads { world: None, active: BTreeMap::new() })
    };
}

pub(super) fn default_nbt() -> Compound {
    Compound::from([("HasAttachedComputer".into(), Tag::Byte(0))])
}

fn facing(block: &BlockState) -> Option<Direction> {
    let name = block.properties.get("facing")?;
    Direction::ALL.into_iter().find(|face| face.name() == name)
}

pub(super) fn decode(block: &BlockState) -> Option<State> {
    if block.name != BLOCK {
        return None;
    }
    let flag = |name| match block.properties.get(name)?.as_str() {
        "true" => Some(true),
        "false" => Some(false),
        _ => None,
    };
    Some(State {
        facing: facing(block)?,
        powered: flag("powered")?,
        extended: flag("extended")?,
    })
}

pub(super) fn target_supports(block: &BlockState, side: Direction) -> bool {
    if let Some(sticker) = decode(block) {
        return sticker.supported_face(side);
    }
    if let Some(sail) = super::create_port_sail::from_state(block) {
        return sail.attaches(side);
    }
    // Directional actors expose a non-supportive working face in
    // BlockMovementChecksImpl.isNotSupportiveFallback.
    !matches!(
        block.name.as_str(),
        "create:mechanical_bearing"
            | "create:mechanical_drill"
            | "create:mechanical_saw"
            | "create:mechanical_harvester"
            | "create:mechanical_plough"
            | "create:portable_storage_interface"
    ) || facing(block) != Some(side)
}

pub(super) fn neighbor(pos: Pos, face: Direction) -> Option<Pos> {
    let delta = face.vector();
    let [x, y, z] = std::array::from_fn(|axis| pos[axis].checked_add(delta[axis]));
    Some([x?, y?, z?])
}

pub(super) fn can_capture(game: &Game<'_>, [x, y, z]: Pos, block: &BlockState) -> bool {
    use crate::containers::BlockEntity;
    decode(block).is_some()
        && matches!(game.world.block_entities.get(&(x, y, z)), Some(BlockEntity::Mod(entity))
            if entity.id == BLOCK
                && entity.items.iter().all(Option::is_none)
                && (entity.nbt.is_empty()
                    || entity.nbt.len() == 1
                        && entity.nbt.get(&"HasAttachedComputer".into()) == Some(&Tag::Byte(0))))
}

pub(super) fn changed(dimension: &'static str, pos: Pos) {
    CHANGED.with(|pending| {
        pending
            .borrow_mut()
            .entry(dimension)
            .or_default()
            .insert(pos)
    });
}

fn update(game: &mut Game<'_>, pos: Pos, placement: bool) {
    let dimension = game.dim.id();
    let id = contraption::state(game, pos);
    let registry = game.pack.assets.registry;
    let Some(block) = registry.state(id) else {
        return;
    };
    let Some(old) = decode(block) else { return };
    let powered = game.native_neighbor_signal(dimension, pos) != 0;
    let next = if placement {
        State {
            powered,
            extended: false,
            ..old
        }
    } else {
        old.with_signal(powered)
    };
    if old == next {
        return;
    }
    let mut updated = block.clone();
    updated
        .properties
        .insert("powered".into(), next.powered.to_string());
    updated
        .properties
        .insert("extended".into(), next.extended.to_string());
    if let Some(id) = registry.id(&updated) {
        game.native_set_block(dimension, pos, id, flags::UPDATE_CLIENTS);
    }
}

pub(super) fn refresh(game: &mut Game<'_>) {
    let Some(pending) = CHANGED.with(|changed| changed.borrow_mut().remove(game.dim.id())) else {
        return;
    };
    for pos in pending {
        update(game, pos, false);
    }
}

pub(super) fn placed(game: &mut Game<'_>, pos: Pos) {
    update(game, pos, true);
}

pub(super) fn client_changed(
    game: &Game<'_>,
    pos: Pos,
    previous: Option<BlockStateId>,
    state: BlockStateId,
) {
    if game.remote.is_none() || !game.native_on("create") {
        return;
    }
    let Some(previous) = previous else { return };
    let registry = game.pack.assets.registry;
    let old = registry.state(previous).and_then(decode);
    let new = registry.state(state).and_then(decode);
    if old.is_none() && new.is_none() {
        return;
    }
    HEADS.with_borrow_mut(|heads| {
        heads.check_world(game);
        match (old, new) {
            (Some(old), Some(new)) if old.extended != new.extended => {
                let row = heads
                    .active
                    .entry(pos)
                    .or_insert((Head::settled(old.extended), None));
                row.1 = Some(new.extended);
            }
            (Some(_), Some(_)) => {}
            _ => {
                heads.active.remove(&pos);
            }
        }
    });
}

fn has_support(game: &Game<'_>, pos: Pos, direction: Direction) -> bool {
    let Some(target) = neighbor(pos, direction) else {
        return false;
    };
    let Cell::Block(rules) = contraption::Capture(game).inspect(target) else {
        return false;
    };
    let side = direction.opposite();
    if Direction::ALL
        .into_iter()
        .zip(rules.attached)
        .any(|(face, attached)| face == side && attached)
    {
        return true;
    }
    game.pack
        .assets
        .registry
        .state(contraption::state(game, target))
        .is_some_and(|block| target_supports(block, side))
}

pub(super) fn client_tick(game: &mut Game<'_>) {
    let mut feedback = Vec::new();
    HEADS.with_borrow_mut(|heads| {
        heads.check_world(game);
        heads.active.retain(|&pos, (head, update)| {
            let Some(state) = game
                .pack
                .assets
                .registry
                .state(contraption::state(game, pos))
                .and_then(decode)
            else {
                return false;
            };
            let (attached, detached) = head.tick(update.take());
            if (attached || detached) && has_support(game, pos, state.facing) {
                feedback.push((pos, state.facing, attached, detached));
            }
            !head.idle()
        });
    });
    for (pos, face, attached, detached) in feedback {
        let at = pos.map(|v| f64::from(v) + 0.5);
        if attached {
            super::create_port_super_glue::spawn_face(game, pos, face);
            game.audio
                .play_unshared("minecraft:block.slime_block.place", Some(at), 0.35, 0.75);
        }
        if detached {
            game.audio
                .play_unshared("minecraft:block.slime_block.place", Some(at), 0.35, 0.2);
        }
    }
}

pub(super) fn draw_station(
    game: &Game<'_>,
    pos: Pos,
    draw: &mut BlockEntityDraw,
    block: &BlockState,
) {
    let Some(state) = decode(block) else { return };
    let offset = HEADS.with_borrow(|heads| {
        heads.active.get(&pos).map_or_else(
            || Head::settled(state.extended).offset(1.0),
            |(head, _)| head.offset(draw.partial),
        )
    });
    draw_head(game, draw, state.facing, offset);
}

pub(super) fn draw(game: &Game<'_>, draw: &mut BlockEntityDraw, block: &BlockState) {
    let Some(state) = decode(block) else { return };
    draw_head(
        game,
        draw,
        state.facing,
        Head::settled(state.extended).offset(1.0),
    );
}

fn draw_head(game: &Game<'_>, draw: &mut BlockEntityDraw, facing: Direction, offset: f32) {
    draw.push();
    match facing {
        Direction::Up => {}
        Direction::Down => draw.rotate_about([1.0, 0.0, 0.0], 180.0, [0.5; 3]),
        side => {
            super::create_port::face_south(draw, side);
            draw.rotate_about([1.0, 0.0, 0.0], 90.0, [0.5; 3]);
        }
    }
    draw.translate([0.0, offset, 0.0]);
    game.native_draw_model(draw, "create:block/sticker/head", 0xFFFFFF);
    draw.pop();
}
