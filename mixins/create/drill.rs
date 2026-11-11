// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT
// Stationary DrillBlockEntity and BlockBreakingKineticBlockEntity adapter.
use super::{Game, native_block_entity_draw::BlockEntityDraw};
use crate::containers::{BlockEntity, HOPPER_SLOTS, ModBlockEntity};
use create_engine::{
    drilling::{Action, DrillCycle},
    placement::Direction,
};
use horizon_protocol::packets::play::{self, Clientbound};
use horizon_world::{
    fluid::FluidKind, loot::with_native_loot_place, nbt::Tag, registry::BlockStateId,
};
use std::{
    cell::RefCell,
    collections::BTreeMap,
    sync::atomic::{AtomicI32, Ordering},
};

const ID: &str = "create:mechanical_drill";
pub(super) const SAW: &str = "create:mechanical_saw";
static NEXT_BREAKER: AtomicI32 = AtomicI32::new(-1);
const MAX_RECENT_CHANGES: usize = 8192;
const NEIGHBORS: [[i32; 3]; 6] = [
    [1, 0, 0],
    [-1, 0, 0],
    [0, 1, 0],
    [0, -1, 0],
    [0, 0, 1],
    [0, 0, -1],
];

struct Running {
    lazy: i32,
    dirty: bool,
    breaker: i32,
    seen: i64,
    target: [i32; 3],
}
#[derive(Default)]
struct DimensionState {
    drills: BTreeMap<[i32; 3], Running>,
    cleaned: Option<i64>,
    changes: BTreeMap<[i32; 3], u64>,
    changes_by_age: BTreeMap<u64, [i32; 3]>,
    change_sequence: u64,
    changes_through_last_tick: u64,
}
impl DimensionState {
    fn record_change(&mut self, pos: [i32; 3]) {
        self.change_sequence += 1;
        if let Some(old) = self.changes.insert(pos, self.change_sequence) {
            self.changes_by_age.remove(&old);
        }
        self.changes_by_age.insert(self.change_sequence, pos);
        // Large edits during a frozen tick can outlive normal maintenance.
        if self.changes.len() > MAX_RECENT_CHANGES {
            self.discard_oldest_change();
        }
    }

    fn discard_oldest_change(&mut self) {
        if let Some((_, pos)) = self.changes_by_age.pop_first() {
            self.changes.remove(&pos);
        }
    }

    fn expire_changes(&mut self) {
        while self
            .changes_by_age
            .first_key_value()
            .is_some_and(|(sequence, _)| *sequence <= self.changes_through_last_tick)
        {
            self.discard_oldest_change();
        }
        self.changes_through_last_tick = self.change_sequence;
    }

    fn neighbor_changed_after_placement(&self, pos: [i32; 3]) -> bool {
        self.changes.get(&pos).is_some_and(|placed| {
            NEIGHBORS.into_iter().any(|offset| {
                let neighbor = std::array::from_fn(|i| pos[i] + offset[i]);
                self.changes
                    .get(&neighbor)
                    .is_some_and(|changed| changed > placed)
            })
        })
    }
}
#[derive(Default)]
struct State {
    game: Option<usize>,
    dimensions: BTreeMap<&'static str, DimensionState>,
}
impl State {
    fn dimension(&mut self, game: usize, dimension: &'static str) -> &mut DimensionState {
        if self
            .game
            .replace(game)
            .is_some_and(|previous| previous != game)
        {
            self.dimensions.clear();
        }
        self.dimensions.entry(dimension).or_default()
    }
}
thread_local! {static STATE: RefCell<State> = RefCell::new(State::default());}

pub(super) fn reset(reload: bool) {
    if !reload {
        STATE.with(|state| *state.borrow_mut() = State::default());
    }
}

/// DrillBlock.neighborChanged: wakes progress after one intervening tick.
/// Keep recent positions until their first drill tick, including changes
/// between placement and the creation of the transient drill entry.
pub(super) fn changed(dimension: &'static str, pos: [i32; 3]) {
    STATE.with(|state| {
        let mut state = state.borrow_mut();
        let dimension = state.dimensions.entry(dimension).or_default();
        dimension.record_change(pos);
        for offset in std::iter::once([0, 0, 0]).chain(NEIGHBORS) {
            let neighbor = std::array::from_fn(|i| pos[i] + offset[i]);
            if let Some(drill) = dimension.drills.get_mut(&neighbor) {
                drill.dirty = true;
            }
        }
    });
}

/// Clear destroyed or unloaded drill cracks once per server tick. This also
/// bounds transient state without scanning every drill for every drill tick.
pub(super) fn maintenance(game: &mut Game<'_>) {
    let removed = STATE.with(|state| {
        let mut state = state.borrow_mut();
        let state = state.dimension(std::ptr::from_ref(game) as usize, game.dim.id());
        let time = game.world.game_time;
        if state.cleaned == Some(time) {
            return Vec::new();
        }
        state.cleaned = Some(time);
        state.expire_changes();
        let mut removed = Vec::new();
        state.drills.retain(|pos, value| {
            let live = time >= value.seen
                && time - value.seen < 400
                && matches!(game.native_block(*pos).as_str(), ID | SAW);
            if !live {
                removed.push((value.breaker, value.target));
            }
            live
        });
        removed
    });
    for (breaker, target) in removed {
        crack(game, breaker, target, -1);
    }
}

fn facing(game: &Game<'_>, pos: [i32; 3]) -> Direction {
    let name = game.native_block_property(pos, "facing");
    Direction::ALL
        .into_iter()
        .find(|d| Some(d.name()) == name.as_deref())
        .unwrap_or(Direction::North)
}

fn crack(game: &mut Game<'_>, breaker: i32, target: [i32; 3], progress: i32) {
    game.destroy_block_progress(breaker, target, progress);
    if let Some(host) = game.lan.as_ref() {
        host.hub.broadcast_near(
            target.map(|v| f64::from(v) + 0.5),
            64.0,
            &Clientbound::BlockDestruction(play::BlockDestruction {
                id: breaker,
                pos: target,
                progress: progress as u8,
            }),
            None,
        );
    }
}

/// The vanilla water/lava and hopper branch of DrillBlockEntity.optimiseCobbleGen.
fn cobble_into_hopper(game: &mut Game<'_>, target: [i32; 3], state: BlockStateId) -> bool {
    let registry = game.pack.assets.registry;
    if registry.default_state("minecraft:cobblestone") != Some(state) {
        return false;
    }
    let [x, y, z] = target;
    let below = [x, y - 1, z];
    let hopper = (x, y - 1, z);
    if game.native_block(below) != "minecraft:hopper"
        || !matches!(game.world.block_entities.get(&hopper), Some(BlockEntity::Chest(slots)) if slots.len() == HOPPER_SLOTS)
    {
        return false;
    }
    // CobbleGenOptimisation supplies hypothetical flowing lava from any
    // neighbouring lava state, then looks for water on a horizontal face.
    let mut lava = false;
    let mut water = false;
    for [dx, dy, dz] in NEIGHBORS {
        let neighbor = [x + dx, y + dy, z + dz];
        if !super::create_port_contraption::resident(game, neighbor) {
            return false;
        }
        let state = super::create_port_contraption::state(game, neighbor);
        let fluid = game.res.behaviours().fluid_kind(state);
        lava |= fluid.same_family(FluidKind::Lava);
        water |= dy == 0 && fluid.same_family(FluidKind::Water);
    }
    if !lava || !water {
        return false;
    }

    // Java rolls Block.getDrops without destroying the block or applying the
    // ordinary block-drops gamerule. The collector discards any remainder.
    let at = target.map(|coordinate| f64::from(coordinate) + 0.5);
    let loot = game.loot_place_at(at, None);
    let drops = with_native_loot_place(loot, || {
        world_items!(game).block_drops_exploded(
            registry,
            state,
            None,
            &[],
            &mut game.world.random,
            Some((&mut game.rand_sequences, game.level.seed)),
            None,
            false,
        )
    });
    for stack in drops {
        let limit = super::create_port::stack_maximum(game, &stack);
        let Some(BlockEntity::Chest(slots)) = game.world.block_entities.get_mut(&hopper) else {
            break;
        };
        if slots.iter().all(Option::is_none) {
            // VanillaHopperItemHandler gives an empty hopper its transfer
            // cooldown. The standard insertion path already does that.
            let _ = game.native_insert_item(below, horizon_core::geometry::Direction::Up, stack);
        } else {
            // NeoForge's insertItemStacked merges before taking an empty slot.
            let count = stack.count;
            let remainder = super::create_port_inventory::insert(slots, stack, limit);
            if remainder.map_or(0, |stack| stack.count) < count {
                game.container_changed(hopper);
            }
        }
    }
    game.level_event_at(2001, target, state.0 as i32);
    true
}

/// Called after the network has written effective RPM, including overstress.
pub(super) fn tick(
    game: &mut Game<'_>,
    pos: [i32; 3],
    entity: &mut ModBlockEntity,
    rpm: f32,
) -> bool {
    let is_saw = entity.id == "create:saw";
    if !is_saw && !matches!(entity.id.as_str(), ID | "create:drill") {
        return false;
    }
    let direction = facing(game, pos);
    if is_saw && direction.axis() == create_engine::kinetics::Axis::Y {
        return false;
    }
    let target = {
        let delta = direction.vector();
        std::array::from_fn(|i| pos[i] + delta[i])
    };
    let time = game.world.game_time;
    let (lazy, dirty, breaker) = STATE.with(|state| {
        let mut state = state.borrow_mut();
        let state = state.dimension(std::ptr::from_ref(game) as usize, game.dim.id());
        let fresh = !state.drills.contains_key(&pos);
        let dirty = fresh && !is_saw && state.neighbor_changed_after_placement(pos);
        let state = state.drills.entry(pos).or_insert_with(|| Running {
            lazy: 10,
            dirty,
            breaker: NEXT_BREAKER.fetch_sub(1, Ordering::Relaxed),
            seen: time,
            target,
        });
        let lazy = fresh || state.lazy <= 0;
        if state.lazy <= 0 {
            state.lazy = 10;
        } else {
            state.lazy -= 1;
        }
        state.seen = time;
        state.target = target;
        (lazy, std::mem::take(&mut state.dirty), state.breaker)
    });
    let mut cycle = DrillCycle {
        progress: crate::game::create_port::integer(&entity.nbt, "Progress"),
        next_tick: crate::game::create_port::integer(&entity.nbt, "NextTick"),
    };
    if lazy {
        cycle.lazy_tick();
    }
    if (!is_saw && dirty) || (is_saw && cycle.next_tick < 0) {
        cycle.wake();
    }
    if rpm != 0.0 {
        entity
            .nbt
            .insert("Breaking".into(), Tag::IntArray(target.to_vec()));
    }
    let state_id = game.world.block(target[0], target[1], target[2]);
    let facts = game.res.facts().get(state_id);
    let hardness = facts.hardness;
    let air = matches!(
        facts.name.as_ref(),
        "minecraft:air" | "minecraft:cave_air" | "minecraft:void_air"
    );
    // A waterlogged solid is not a liquid block. DrillBlock also accepts a
    // waterlogged machine casing, independently of the fluid it contains.
    let liquid = matches!(facts.name.as_ref(), "minecraft:water" | "minecraft:lava");
    let non_breakable = game
        .pack
        .assets
        .registry
        .state(state_id)
        .is_some_and(|state| {
            game.native_server_block_in_tag(state, "create:non_breakable")
                .unwrap_or(false)
        });
    let hit = facts.sounds.hit.to_string();
    let action = cycle.tick(
        rpm,
        hardness,
        if is_saw {
            super::create_port_contraption_actors::saw_can_break(game, target)
        } else {
            !air && !liquid && hardness != -1.0 && !non_breakable
        },
    );
    if matches!(action, Action::Hit | Action::Break) {
        game.with_level(|_, level, _| {
            level.native_play_sound(&hit, pos.map(|v| f64::from(v) + 0.5), 4, 0.25, 1.0);
        });
    }
    match action {
        Action::Hit => crack(game, breaker, target, cycle.progress),
        Action::Clear => crack(game, breaker, target, -1),
        Action::Break => {
            if is_saw {
                super::create_port_contraption_actors::finish_stationary_saw(game, pos, target);
            } else if !cobble_into_hopper(game, target, state_id) {
                let at =
                    super::create_port_contraption_actors::stationary_drop_origin(game, target);
                if let Some(drops) = game.native_machine_destroy_block(target, None, true) {
                    for stack in drops {
                        game.spawn_item(stack, at, [0.0; 3], 10);
                    }
                }
            }
            crack(game, breaker, target, -1);
        }
        Action::None => {}
    }
    let before_progress = crate::game::create_port::integer(&entity.nbt, "Progress");
    entity
        .nbt
        .insert("Progress".into(), Tag::Int(cycle.progress));
    entity
        .nbt
        .insert("NextTick".into(), Tag::Int(cycle.next_tick));
    before_progress != cycle.progress || action == Action::Break
}

pub(super) fn draw(
    game: &Game<'_>,
    pos: [i32; 3],
    entity: &ModBlockEntity,
    draw: &mut BlockEntityDraw,
) -> bool {
    if !matches!(entity.id.as_str(), ID | "create:drill") {
        return false;
    }
    let direction = facing(game, pos);
    let axis = direction.axis();
    let angle = create_engine::visual::angle(
        draw.game_time as f64 + f64::from(draw.partial),
        crate::game::create_port::number(&entity.nbt, "Speed"),
        create_engine::visual::rotation_offset(pos, axis, false),
    );
    draw.push();
    draw.rotate_about(create_engine::visual::positive_axis(axis), angle, [0.5; 3]);
    crate::game::create_port::face_south(draw, direction);
    game.native_draw_model(draw, "create:block/mechanical_drill/head", 0xFFFFFF);
    draw.pop();
    true
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn drill_change_journal_keeps_recent_order_with_a_bounded_paused_world() {
        let mut state = DimensionState::default();
        let old = [0, 64, 0];
        state.record_change(old);
        for x in 1..=MAX_RECENT_CHANGES as i32 {
            state.record_change([x, 64, 0]);
        }
        assert_eq!(state.changes.len(), MAX_RECENT_CHANGES);
        assert!(!state.changes.contains_key(&old));

        let drill = [0, 70, 0];
        let target = [1, 70, 0];
        state.record_change(target);
        state.record_change(drill);
        assert!(!state.neighbor_changed_after_placement(drill));
        state.record_change(target);
        assert!(state.neighbor_changed_after_placement(drill));
        assert_eq!(state.changes_by_age.len(), MAX_RECENT_CHANGES);

        state.expire_changes();
        assert!(state.neighbor_changed_after_placement(drill));
        state.expire_changes();
        assert!(state.changes.is_empty() && state.changes_by_age.is_empty());
    }
}
