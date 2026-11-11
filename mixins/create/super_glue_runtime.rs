// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

// SuperGlueSelectionHandler, SuperGlueSelectionPacket and SuperGlueHandler.

use super::{
    Game,
    create_port_contraption::{Capture, column},
    shield::OFFHAND_SLOT,
};
use create_engine::{
    contraption::{
        CaptureView, Cell,
        glue::{OffhandPlacement, Search, SelectionError, Volume, offhand_placement, selection},
    },
    kinetics::Pos,
    particles::{glue_edges, glue_face},
    placement::Direction,
};
use horizon_client::{
    item_render::cit::stack_max_damage,
    items::ItemStack,
    mod_api::Holder,
    particles::{ParticleOptions, ParticleType},
    text::Text,
};
use horizon_core::{
    geometry::{Aabb, Direction as Face, Vec3, traverse_blocks},
    position::BlockPos,
    random::RandomSource,
};
use horizon_world::{
    attachments::{AttachmentCodec, AttachmentError, AttachmentType, Attachments},
    level::PlaceContext,
    nbt::{Compound, Tag},
    player_inventory::EquipmentSlot,
};
use std::borrow::Cow;

const ITEM: &str = "create:super_glue";
const ATTACK_CHANNEL: &str = "create:remove_super_glue";
const FACE_CHANNEL: &str = "create:super_glue_face";
pub(super) const MAX_VOLUMES: usize = 128;
const MAX_SELECTION_BLOCKS: usize = 32_768;
const KEY: &str = "super_glue";

pub(super) const VOLUMES: AttachmentType<Vec<Volume>> = AttachmentType {
    namespace: "create",
    name: KEY,
    default: Vec::new,
    codec: Some(AttachmentCodec { encode, decode }),
    copy_on_death: false,
    sync: true,
};

const FIRST: AttachmentType<Option<(String, Pos)>> = AttachmentType {
    namespace: "create",
    name: "glue_first_corner",
    default: || None,
    codec: None,
    copy_on_death: false,
    sync: false,
};

const ATTACK: AttachmentType<bool> = AttachmentType {
    namespace: "create",
    name: "glue_attack_requested",
    default: || false,
    codec: None,
    copy_on_death: false,
    sync: false,
};

pub(super) fn encode(volumes: &Vec<Volume>) -> Result<Compound, AttachmentError> {
    if volumes.len() > MAX_VOLUMES {
        return Err(AttachmentError::Encode);
    }
    let entries = volumes
        .iter()
        .map(|volume| {
            let [min, max] = volume.corners();
            Tag::IntArray([min, max].concat())
        })
        .collect();
    Ok(Compound::from([
        ("Version".into(), Tag::Int(1)),
        ("Volumes".into(), Tag::List(entries)),
    ]))
}

pub(super) fn decode(saved: &Compound) -> Result<Vec<Volume>, AttachmentError> {
    let error = AttachmentError::Decode;
    if !matches!(saved.get(&"Version".into()), Some(Tag::Int(1))) {
        return Err(error);
    }
    let Some(Tag::List(entries)) = saved.get(&"Volumes".into()) else {
        return Err(error);
    };
    if entries.len() > MAX_VOLUMES {
        return Err(error);
    }
    entries
        .iter()
        .map(|entry| {
            let Tag::IntArray(corners) = entry else {
                return Err(error);
            };
            let &[a, b, c, d, e, f] = corners.as_slice() else {
                return Err(error);
            };
            let min = [a, b, c];
            let max = [d, e, f];
            let span_squared = (0..3)
                .map(|i| (i128::from(max[i]) - i128::from(min[i])).pow(2))
                .sum::<i128>();
            if (0..3).any(|i| min[i] > max[i]) || span_squared >= 625 {
                return Err(error);
            }
            Ok(Volume::span(min, max))
        })
        .collect()
}

pub(super) fn read<'g>(
    game: &'g Game<'_>,
    key: [i32; 2],
) -> Result<Cow<'g, [Volume]>, AttachmentError> {
    let Some(chunk) = game.world.chunks.get(&(key[0], key[1])) else {
        return Err(AttachmentError::MissingHolder);
    };
    let Some(saved) = chunk.saved.as_ref() else {
        return Ok(Cow::Borrowed(&[]));
    };
    read_map(&saved.attachments, key)
}

fn read_map(map: &Attachments, key: [i32; 2]) -> Result<Cow<'_, [Volume]>, AttachmentError> {
    use horizon_world::attachments::create_contraption_attachment::{decoded, encoded};
    if let Some(volumes) = decoded(map, &VOLUMES) {
        return Ok(Cow::Borrowed(volumes));
    }
    if let Some(value) = encoded(map, "create", KEY) {
        let volumes = decode(value)?;
        if volumes
            .iter()
            .any(|volume| volume.corners().into_iter().any(|p| column(p) != key))
        {
            return Err(AttachmentError::Decode);
        }
        return Ok(Cow::Owned(volumes));
    }
    if map.has(&VOLUMES) {
        return Err(AttachmentError::Decode);
    }
    Ok(Cow::Borrowed(&[]))
}

struct GlueView<'g, 'a>(Capture<'g, 'a>);

struct PlacementView<'g, 'a>(&'g Game<'a>);

impl CaptureView for PlacementView<'_, '_> {
    type Block = ();

    fn inspect(&self, pos: Pos) -> Cell {
        let Cell::Block(mut rules) = GlueView(Capture(self.0)).inspect(pos) else {
            return Cell::Empty;
        };
        let game = self.0;
        let block = game.native_block(pos);
        let facing = game.native_block_property(pos, "facing");
        let facing = facing
            .as_deref()
            .and_then(|name| Direction::ALL.into_iter().find(|face| face.name() == name));
        match block.as_str() {
            "create:mechanical_drill"
            | "create:mechanical_saw"
            | "create:mechanical_bearing"
            | "create:portable_storage_interface"
            | "create:mechanical_harvester"
            | "create:mechanical_plough" => {
                if let Some(facing) = facing {
                    rules.unsupported_faces[facing as usize] = true;
                    if matches!(
                        block.as_str(),
                        "create:mechanical_harvester" | "create:mechanical_plough"
                    ) {
                        rules.attached[facing.opposite() as usize] = true;
                    }
                }
            }
            "create:rope_pulley" => rules.unsupported_faces[Direction::Down as usize] = true,
            "create:piston_extension_pole" | "create:mechanical_piston_head" => {
                if let Some(facing) = facing {
                    rules.unsupported_faces =
                        Direction::ALL.map(|face| face.axis() != facing.axis());
                }
            }
            _ => {}
        }
        Cell::Block(rules)
    }

    fn snapshot(&self, _: Pos) -> Option<()> {
        Some(())
    }

    fn glued(&self, pos: Pos, face: Direction) -> bool {
        glued(self.0, pos, face)
    }
}

impl CaptureView for GlueView<'_, '_> {
    type Block = ();

    fn inspect(&self, pos: Pos) -> Cell {
        let inspected = self.0.inspect(pos);
        if !matches!(inspected, Cell::Block(_)) {
            return inspected;
        }
        let game = self.0.0;
        let state = game.world.block(pos[0], pos[1], pos[2]);
        if game.res.facts().get(state).replaceable {
            return Cell::Empty;
        }
        inspected
    }

    fn snapshot(&self, _: Pos) -> Option<()> {
        Some(())
    }

    fn glued(&self, pos: Pos, face: Direction) -> bool {
        glued(self.0.0, pos, face)
    }
}

fn glued(game: &Game<'_>, pos: Pos, face: Direction) -> bool {
    read(game, column(pos)).is_ok_and(|volumes| volumes.iter().any(|v| v.glues(pos, face)))
}

fn sticky(game: &Game<'_>, pos: Pos, side: Direction) -> bool {
    matches!(
        game.native_block(pos).as_str(),
        "create:sticky_mechanical_piston"
            | "create:gantry_carriage"
            | "create:mechanical_bearing"
            | "create:windmill_bearing"
            | "create:clockwork_bearing"
    ) && game.native_block_property(pos, "facing").as_deref() == Some(side.name())
}

fn holds_glue(game: &Game<'_>) -> bool {
    game.stack_in(game.selected)
        .is_some_and(|stack| stack.item.as_ref() == ITEM)
}

pub(super) fn predicts(game: &Game<'_>, held: Option<&ItemStack>) -> bool {
    game.native_on("create")
        && holds_glue(game)
        && held.is_some_and(|stack| stack.item.as_ref() == ITEM)
}

fn available(game: &Game<'_>) -> Option<(usize, ItemStack, u32)> {
    std::iter::once(game.selected)
        .chain(0..game.inventory.len())
        .find_map(|slot| {
            let stack = game.stack_in(slot)?;
            if stack.item.as_ref() != ITEM || stack.count == 0 {
                return None;
            }
            let max = stack_max_damage(
                stack,
                game.items().get(ITEM).map_or(0, |info| info.max_damage),
            );
            (stack.damage < max).then(|| (slot, stack.clone(), max))
        })
}

fn spend(game: &mut Game<'_>) -> bool {
    if game.creative {
        return true;
    }
    let Some((slot, mut stack, max)) = available(game) else {
        return false;
    };
    stack.damage = stack.damage.saturating_add(game.wear(&stack, 1));
    if stack.damage < max {
        *game.stack_in_mut(slot) = Some(stack);
    } else {
        *game.stack_in_mut(slot) = None;
        game.award_stat("broken", ITEM, 1);
        game.player_equipment_broke(EquipmentSlot::MainHand, &stack);
    }
    true
}

fn status(game: &mut Game<'_>, key: &str) {
    let player = game.native_acting_id();
    game.native_action_bar(player, Text::translate(key, &[]));
}

fn sound(game: &mut Game<'_>, pos: Pos, pitch: f32) {
    let at = pos.map(|value| f64::from(value) + 0.5);
    game.with_level(|_, level, _| {
        level.native_play_sound("minecraft:block.slime_block.place", at, 4, 0.5, pitch);
        level.native_play_sound("minecraft:entity.item_frame.add_item", at, 4, 0.75, 1.0);
    });
}

fn send_face(game: &mut Game<'_>, pos: Pos, face: [i32; 3]) {
    let Some(index) = Direction::ALL.iter().position(|d| d.vector() == face) else {
        return;
    };
    let mut data = [0; 13];
    for (bytes, coord) in data[..12].chunks_exact_mut(4).zip(pos) {
        bytes.copy_from_slice(&coord.to_be_bytes());
    }
    data[12] = index as u8;
    let player = game.native_acting_id();
    let _ = game.native_net_send_to_player(player, FACE_CHANNEL, &data);
}

pub(super) fn receive_face(game: &mut Game<'_>, channel: &str, data: &[u8]) {
    if channel != FACE_CHANNEL
        || !game.native_window()
        || !game.native_on("create")
        || data.len() != 13
    {
        return;
    }
    let Some(&face) = Direction::ALL.get(usize::from(data[12])) else {
        return;
    };
    let pos =
        std::array::from_fn(|i| i32::from_be_bytes(data[4 * i..4 * i + 4].try_into().unwrap()));
    spawn_face(game, pos, face);
}

pub(super) fn spawn_face(game: &mut Game<'_>, pos: Pos, face: Direction) {
    let options = game.item_particle(&ItemStack::new("minecraft:slime_ball", 1));
    let particles = glue_face(pos, face, || game.particles.level_random().next_float());
    for (at, velocity) in particles {
        game.particles.add(&options, at, velocity);
    }
}

fn send_edges(game: &mut Game<'_>, volume: Volume) {
    let options = ParticleOptions::simple(ParticleType::ItemSlime);
    game.with_level(|_, level, _| {
        glue_edges(volume, |at| {
            level.native_send_particles(&options, None, at, [0.0; 3], 0.0, 1);
        });
    });
}

fn vector([x, y, z]: [f64; 3]) -> Vec3 {
    Vec3::new(x, y, z)
}

fn offhand_item<'g>(game: &'g Game<'_>) -> Option<&'g ItemStack> {
    if game
        .stack_in(game.selected)
        .is_some_and(|stack| stack.item.as_ref() == "create:wrench")
    {
        return None;
    }
    game.stack_in(OFFHAND_SLOT)
        .filter(|stack| stack.item.as_ref() == ITEM && stack.count != 0)
}

/// SuperGlueHandler clips the outline with just the placed block treated as air.
fn placement_hit(game: &Game<'_>, placed: Pos) -> Option<(Pos, Direction)> {
    let eye = game.eye_position()?;
    let look = super::view_vector(game.yaw, game.pitch);
    let reach = game.reach();
    let start = vector(eye);
    let end = start.add_vector(vector(look).scale(reach));
    // The player reach attribute tops out at 64 blocks. Even a corner-to-
    // corner ray within that range visits fewer than 256 voxels.
    let hit = traverse_blocks(start, end, 256, |p| {
        let pos = [p.x, p.y, p.z];
        if pos == placed {
            return None;
        }
        let state = game.world.block(p.x, p.y, p.z);
        let facts = game.res.facts().get(state);
        if game.res.facts().is_air(state)
            || matches!(
                facts.name.as_ref(),
                "minecraft:water" | "minecraft:lava" | "minecraft:bubble_column"
            )
        {
            return None;
        }
        if let Some([x, y, z, a, b, c]) = game.context_outline(pos, state) {
            return Aabb::clip_boxes(
                [Aabb::new(Vec3::new(x, y, z), Vec3::new(a, b, c))],
                start,
                end,
                p,
            );
        }
        Aabb::clip_boxes(
            facts.outline.iter().map(|[x, y, z, a, b, c]| {
                Aabb::new(Vec3::new(*x, *y, *z), Vec3::new(*a, *b, *c))
            }),
            start,
            end,
            p,
        )
    })
    .ok()??;
    let face = match hit.direction {
        Face::Down => Direction::Down,
        Face::Up => Direction::Up,
        Face::North => Direction::North,
        Face::South => Direction::South,
        Face::West => Direction::West,
        Face::East => Direction::East,
    };
    Some(([hit.block.x, hit.block.y, hit.block.z], face))
}

fn uses_ordinary_placement(stack: &ItemStack) -> bool {
    !matches!(
        stack.item.as_ref(),
        "create:vertical_gearbox"
            | "create:large_water_wheel"
            | "minecraft:lily_pad"
            | "minecraft:frogspawn"
    )
}

fn applies_to_placement(game: &Game<'_>, stack: &ItemStack) -> bool {
    game.native_on("create") && offhand_item(game).is_some() && uses_ordinary_placement(stack)
}

fn wrong_placement_target(game: &Game<'_>, placed: Pos) -> bool {
    offhand_placement(&PlacementView(game), placed, placement_hit(game, placed))
        == OffhandPlacement::CancelPlacement
}

pub(super) fn cancel_prediction(game: &Game<'_>, stack: &ItemStack, placed: Pos) -> bool {
    applies_to_placement(game, stack) && wrong_placement_target(game, placed)
}

/// A placement observer cannot cancel. Check the same ordinary BlockItem
/// placement on Horizon's disposable level before the authoritative write.
pub(super) fn cancels_placement(game: &mut Game<'_>, stack: &ItemStack) -> bool {
    if game.remote.is_some()
        || !applies_to_placement(game, stack)
        || game
            .items()
            .get(&stack.item)
            .is_none_or(|item| item.block.is_none())
    {
        return false;
    }
    let Some(hit) = game.pick() else { return false };
    if !game.may_build() && !game.can_place_on_in_adventure(hit.pos) {
        return false;
    }
    let Some(direction) = Direction::from_vector(hit.face) else {
        return false;
    };
    let context = PlaceContext {
        clicked_pos: BlockPos::new(hit.pos[0], hit.pos[1], hit.pos[2]),
        face: match direction {
            Direction::Down => Face::Down,
            Direction::Up => Face::Up,
            Direction::North => Face::North,
            Direction::South => Face::South,
            Direction::West => Face::West,
            Direction::East => Face::East,
        },
        hit: vector(hit.point),
        inside: false,
        yaw: game.yaw,
        pitch: game.pitch,
        sneaking: game.keys.contains(&winit::keyboard::KeyCode::ShiftLeft),
        item: stack.item.to_string(),
        can_use_game_master_blocks: game.can_use_game_master_blocks(),
    };
    let Some(placed) = game.create_glue_preview_placement(&context) else {
        return false;
    };
    wrong_placement_target(game, placed)
}

pub(super) fn placed(game: &mut Game<'_>, stack: &ItemStack, pos: Pos) {
    if !game.native_on("create") || game.remote.is_some() || !uses_ordinary_placement(stack) {
        return;
    }
    // Java replays existing glued faces when a player replaces a block in a volume.
    if let Ok(volumes) = read(game, column(pos))
        && !volumes.is_empty()
    {
        let replay = Direction::ALL.map(|direction| {
            let delta = direction.vector();
            let neighbor = std::array::from_fn(|axis| pos[axis] + delta[axis]);
            volumes.iter().any(|volume| volume.glues(pos, direction))
                && matches!(PlacementView(game).inspect(neighbor), Cell::Block(_))
        });
        for (direction, replay) in Direction::ALL.into_iter().zip(replay) {
            if replay {
                send_face(game, pos, direction.vector());
            }
        }
    }

    let Some(mut glue) = offhand_item(game).cloned() else {
        return;
    };
    let Some((against, face)) = placement_hit(game, pos) else {
        return;
    };
    let OffhandPlacement::Apply(volume) =
        offhand_placement(&PlacementView(game), pos, Some((against, face)))
    else {
        return;
    };
    let key = column(against);
    if column(pos) != key {
        return;
    }
    let max = stack_max_damage(
        &glue,
        game.items().get(ITEM).map_or(0, |item| item.max_damage),
    );
    if !game.creative && glue.damage >= max {
        return;
    }
    let Ok(volumes) = read(game, key) else { return };
    let mut volumes = volumes.into_owned();
    if volumes.len() == MAX_VOLUMES {
        return;
    }
    volumes.push(volume);
    let Ok(map) = game.native_attachments(Holder::Chunk(key)) else {
        return;
    };
    if map.set(&VOLUMES, volumes).is_err() {
        return;
    }
    if !game.creative {
        glue.damage = glue.damage.saturating_add(game.wear(&glue, 1));
        if glue.damage < max {
            *game.stack_in_mut(OFFHAND_SLOT) = Some(glue);
        } else {
            *game.stack_in_mut(OFFHAND_SLOT) = None;
            game.award_stat("broken", ITEM, 1);
            // Create 6.0.10 consumes the offhand stack but names MAINHAND
            // explicitly for the break event.
            game.player_equipment_broke(EquipmentSlot::MainHand, &glue);
        }
    }
    send_face(game, against, face.vector());
}

fn nearest_volume(game: &Game<'_>) -> Option<([i32; 2], usize, [f64; 3])> {
    let (origin, direction) = game.aim()?;
    let eye = vector(origin);
    let end = eye.add_vector(vector(direction).scale(game.reach() + 1.0));
    let x = origin[0].floor() as i32;
    let z = origin[2].floor() as i32;
    let columns = |axis: i32| (axis - 32).div_euclid(16)..=(axis + 32).div_euclid(16);
    let mut nearest = None;
    let mut distance = f64::INFINITY;
    for x in columns(x) {
        for z in columns(z) {
            let column = [x, z];
            let volumes = if let Some(remote) = &game.remote {
                remote.attachments.get(&Holder::Chunk(column)).map_or_else(
                    || Ok(Cow::<[Volume]>::Borrowed(&[])),
                    |map| read_map(map, column),
                )
            } else {
                read(game, column)
            };
            let Ok(volumes) = volumes else {
                continue;
            };
            for (index, volume) in volumes.iter().enumerate() {
                let [min, max] = volume.corners();
                let lower = vector(min.map(f64::from));
                let upper = vector(max.map(|value| f64::from(value) + 1.0));
                let Some(hit) = Aabb::new(lower, upper).clip(eye, end) else {
                    continue;
                };
                let distance_to_hit = eye.distance_squared(hit);
                if distance_to_hit <= distance {
                    nearest = Some((column, index, hit.components()));
                    distance = distance_to_hit;
                }
            }
        }
    }
    nearest
}

/// An empty request names no world object. The server raycasts independently.
pub(super) fn attack_input(game: &mut Game<'_>, button: i32) -> bool {
    if button != 0
        || !game.native_window()
        || !game.native_on("create")
        || !holds_glue(game)
        || !game.may_build()
    {
        return false;
    }
    if game.entity_targeted() && nearest_volume(game).is_none() {
        return false;
    }
    game.native_net_send_to_server(ATTACK_CHANNEL, &[]).is_ok()
}

pub(super) fn receive_attack(game: &mut Game<'_>, player: u128, channel: &str, data: &[u8]) {
    if channel == ATTACK_CHANNEL
        && data.is_empty()
        && game.native_on("create")
        && let Ok(map) = game.attachment_map_quiet(Holder::Player(player))
    {
        let _ = map.set(&ATTACK, true);
    }
}

pub(super) fn left_click(game: &mut Game<'_>) -> bool {
    if !game.native_on("create") || !holds_glue(game) || !game.may_build() {
        return false;
    }
    if game.player_attachments.has(&FIRST) {
        return true;
    }
    let Some((column, index, at)) = nearest_volume(game) else {
        return true;
    };
    let Ok(volumes) = read(game, column) else {
        return true;
    };
    let mut volumes = volumes.into_owned();
    let volume = volumes.remove(index);
    let Ok(map) = game.native_attachments(Holder::Chunk(column)) else {
        return true;
    };
    let removed = if volumes.is_empty() {
        map.remove(&VOLUMES).map(|_| ())
    } else {
        map.set(&VOLUMES, volumes)
    };
    if removed.is_ok() {
        send_edges(game, volume);
        let sound_pos = at.map(|value| value.floor() + 0.5);
        game.with_level(|_, level, _| {
            level.native_play_sound("minecraft:block.slime_block.place", sound_pos, 4, 0.5, 0.5);
        });
    }
    true
}

pub(super) fn player_tick(game: &mut Game<'_>) {
    if game.player_attachments.remove(&ATTACK).ok().flatten() == Some(true) {
        left_click(game);
    }
    if !game.player_attachments.has(&FIRST) {
        return;
    }
    if !game.native_on("create") || !holds_glue(game) || !game.may_build() {
        let _ = game.player_attachments.remove(&FIRST);
        status(game, "create.super_glue.abort");
    }
}

pub(super) fn right_click(game: &mut Game<'_>, pos: Pos, face: [i32; 3]) -> bool {
    if !game.native_on("create")
        || game.held_slot() != game.selected
        || !holds_glue(game)
        || !game.may_build()
    {
        return false;
    }
    let first = game
        .player_attachments
        .get_existing(&FIRST)
        .ok()
        .flatten()
        .flatten()
        .filter(|(dimension, _)| dimension == game.dim.id());
    if game.keys.contains(&winit::keyboard::KeyCode::ShiftLeft) {
        if first.is_some() {
            let _ = game.player_attachments.remove(&FIRST);
            status(game, "create.super_glue.abort");
        }
        return true;
    }
    let Some((_, first)) = first else {
        if game
            .player_attachments
            .set(&FIRST, Some((game.dim.id().into(), pos)))
            .is_ok()
        {
            status(game, "create.super_glue.first_pos");
            sound(game, pos, 0.85);
            send_face(game, pos, face);
        }
        return true;
    };
    let view = GlueView(Capture(game));
    let planned = selection(
        &view,
        first,
        pos,
        Search::Preview,
        MAX_SELECTION_BLOCKS,
        |pos, side| sticky(game, pos, side),
    );
    match planned {
        Err(SelectionError::TooFar) => {
            status(game, "create.super_glue.too_far");
            return true;
        }
        Ok(cluster) if cluster.can_commit() => {}
        _ => {
            status(game, "create.super_glue.cannot_reach");
            return true;
        }
    }
    if !game.creative && available(game).is_none() {
        status(game, "create.super_glue.not_enough");
        return true;
    }

    let planned = selection(
        &view,
        first,
        pos,
        Search::Commit,
        MAX_SELECTION_BLOCKS,
        |pos, side| sticky(game, pos, side),
    );
    let _ = game.player_attachments.remove(&FIRST);
    let Ok(cluster) = planned else { return true };
    if !cluster.can_commit() {
        return true;
    }
    let volume = cluster.volume;
    let [min, max] = volume.corners();
    let key = column(min);
    if column(max) != key {
        status(game, "create.super_glue.too_far");
        return true;
    }
    let Ok(volumes) = read(game, key) else {
        return true;
    };
    let mut volumes = volumes.into_owned();
    if volumes.len() == MAX_VOLUMES {
        return true;
    }
    volumes.push(volume);
    let Ok(map) = game.native_attachments(Holder::Chunk(key)) else {
        return true;
    };
    if map.set(&VOLUMES, volumes).is_err() {
        return true;
    }
    // 6.0.10's `collectGlueFromInventory` uses its durability path for both
    // calls. The first can break the selected glue. The second then selects
    // the next glue in ordinary inventory order, if one remains.
    spend(game);
    spend(game);
    send_edges(game, volume);
    status(game, "create.super_glue.success");
    sound(game, pos, 0.95);
    true
}
