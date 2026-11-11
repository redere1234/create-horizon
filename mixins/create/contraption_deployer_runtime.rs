// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

// Bounded stationary and mounted Deployer item use.

use super::{
    Game, create_port as kinetics, create_port_belt as belt,
    create_port_contraption as contraption, create_port_contraption_storage as storage,
    native_block_entity_draw::BlockEntityDraw,
};
use crate::{
    containers::{BlockEntity, ModBlockEntity, ModBlockEntityFields},
    items::ItemStack,
};
use create_engine::{
    contraption::QuarterTurn,
    deployer::{
        Aim, BeltAction, HandPose, Held, Mode, MovingAction, Phase, Segment, Stationary, Target,
        TickAction, Waiting, belt_action, grabs_from_storage, hand_pose, moving_action, should_use,
        stationary_aim, timer_speed,
    },
    kinetics::{Axis, Pos},
    placement::Direction,
    sequenced,
    transport::{ProcessingResult, ProcessingUpdate, Transported, TransportedResult},
};
use glam::DVec3;
use horizon_assets::item_model::DisplayContext;
use horizon_client_render::create_contraption_scene::{MAX_RECORDS, Record};
use horizon_core::random::RandomSource;
use horizon_core::{
    geometry::{Direction as Face, Vec3},
    position::BlockPos,
};
use horizon_items::item_nbt::{encode_items, item_from_nbt, item_to_nbt};
use horizon_world::{
    attachments::{AttachmentCodec, AttachmentError, AttachmentType, Holder},
    chunk::BlockState,
    level::{PlaceContext, PlaceOutcome},
    nbt::{Compound, Tag},
    registry::BlockStateId,
};
use std::collections::BTreeMap;

pub(super) const BLOCK: &str = "create:deployer";
const UPDATE_TICK: &str = "create_horizon:DeployerTick";
const BONE_MEAL: &str = "minecraft:bone_meal";
const SEQUENCE_COMPONENT: &str = "create:sequenced_assembly";
const PRECISION_RECIPE: &str = "create:sequenced_assembly/precision_mechanism";

const MAX_DEPLOYERS: usize = 2;
const SAPLINGS: &[&str] = &[
    "minecraft:oak_sapling",
    "minecraft:spruce_sapling",
    "minecraft:birch_sapling",
    "minecraft:jungle_sapling",
    "minecraft:acacia_sapling",
    "minecraft:dark_oak_sapling",
    "minecraft:cherry_sapling",
];

pub(super) type Cargo = BTreeMap<Pos, Compound>;
type Store = BTreeMap<Pos, Cargo>;
type Edit = (Pos, BlockStateId, BlockStateId);

const CARGO: AttachmentType<Store> = AttachmentType {
    namespace: "create",
    name: "mounted_deployer",
    default: Store::new,
    codec: Some(AttachmentCodec { encode, decode }),
    copy_on_death: false,
    sync: false,
};

pub(super) fn block_state(state: &BlockState) -> bool {
    state.name == BLOCK
        && state.properties.len() == 2
        && state
            .properties
            .get("facing")
            .is_some_and(|v| Direction::ALL.into_iter().any(|d| d.name() == v))
        && state
            .properties
            .get("axis_along_first")
            .is_some_and(|v| matches!(v.as_str(), "true" | "false"))
}

pub(super) fn default_nbt() -> Compound {
    Compound::from([
        ("Mode".into(), Tag::String("USE".into())),
        ("State".into(), Tag::String("WAITING".into())),
        ("Timer".into(), Tag::Int(0)),
        ("Powered".into(), Tag::Byte(0)),
    ])
}

pub(super) fn update_tag(entity: &ModBlockEntity) -> Compound {
    let mut update: Compound = [
        "Mode", "HeldItem", "State", "Timer", "Speed", "Powered", "Filter", "NetworkStatus",
        "create_horizon",
    ]
    .into_iter()
    .filter_map(|key| get(&entity.nbt, key).map(|tag| (key.into(), tag.clone())))
    .collect();
    let reach = entity.data.first().copied().unwrap_or(0) as u32;
    update.insert("Reach".into(), Tag::Float(reach));
    if let Some(&tick) = entity.data.get(1) {
        update.insert(UPDATE_TICK.into(), Tag::Int(tick));
    }
    update
}

fn shaft_axis(facing: Direction, first: bool) -> Axis {
    match facing.axis() {
        Axis::X => {
            if first {
                Axis::Y
            } else {
                Axis::Z
            }
        }
        Axis::Y => {
            if first {
                Axis::X
            } else {
                Axis::Z
            }
        }
        Axis::Z => {
            if first {
                Axis::X
            } else {
                Axis::Y
            }
        }
    }
}

fn draw_arm(
    game: &Game<'_>,
    draw: &mut BlockEntityDraw,
    facing: Direction,
    first: bool,
    shaft_angle: f32,
    extension: f32,
    pose: HandPose,
) {
    let shaft_axis = shaft_axis(facing, first);
    draw.push();
    draw.rotate_about(
        create_engine::visual::positive_axis(shaft_axis),
        shaft_angle,
        [0.5; 3],
    );
    match shaft_axis {
        Axis::X => draw.rotate_about([0., 0., 1.], 90., [0.5; 3]),
        Axis::Z => draw.rotate_about([1., 0., 0.], 90., [0.5; 3]),
        Axis::Y => {}
    }
    game.native_draw_model(draw, "create:block/shaft", 0xffffff);
    draw.pop();
    draw.push();
    super::create_port::face_south(draw, facing);
    draw.translate([0.0, 0.0, extension]);
    draw.push();
    if first ^ (facing.axis() == Axis::Z) {
        draw.rotate_about([0., 0., 1.], 90., [0.5; 3]);
    }
    game.native_draw_model(draw, "create:block/deployer/pole", 0xffffff);
    draw.pop();
    let model = match pose {
        HandPose::Pointing => "create:block/deployer/hand_pointing",
        HandPose::Holding => "create:block/deployer/hand_holding",
        HandPose::Punching => "create:block/deployer/hand_punching",
    };
    game.native_draw_model(draw, model, 0xffffff);
    draw.pop();
}

#[derive(Clone, Copy)]
struct FilterSlot {
    center: [f32; 3],
    yaw: f32,
    pitch: f32,
}

impl FilterSlot {
    fn new(facing: Direction, first: bool, side: Direction) -> Option<Self> {
        if side.axis() == facing.axis() || side.axis() == shaft_axis(facing, first) {
            return None;
        }
        let yaw = |direction| match direction {
            Direction::North => 0.0,
            Direction::East => -90.0,
            Direction::West => 90.0,
            _ => 180.0,
        };
        let direction = facing.vector();
        let normal = side.vector();
        Some(Self {
            center: std::array::from_fn(|i| {
                0.5 + normal[i] as f32 * 7.5 / 16.0 - direction[i] as f32 * 2.0 / 16.0
            }),
            yaw: yaw(side)
                + if side.axis() == Axis::Y {
                    yaw(facing)
                } else {
                    0.0
                },
            pitch: match side {
                Direction::Up => 90.0,
                Direction::Down => -90.0,
                _ => 0.0,
            },
        })
    }

    fn contains(self, pos: Pos, hit: [f64; 3]) -> bool {
        (0..3)
            .map(|i| (hit[i] - f64::from(pos[i]) - f64::from(self.center[i])).powi(2))
            .sum::<f64>()
            < 0.25 * 0.25
    }

    fn draw(self, game: &Game<'_>, draw: &mut BlockEntityDraw, stack: &ItemStack) {
        draw.push();
        draw.translate(self.center);
        draw.rotate_about([0., 1., 0.], self.yaw, [0.; 3]);
        draw.rotate_about([1., 0., 0.], self.pitch, [0.; 3]);
        // The supported saplings and bone meal use flat generated models.
        draw.scale([0.5 * (0.5 + 1.0 / 64.0); 3]);
        draw.translate([0., 0., -0.15]);
        game.native_draw_item(draw, stack, DisplayContext::Fixed, None, 0);
        draw.pop();
    }
}

fn draw_filter(
    game: &Game<'_>,
    pos: Pos,
    facing: Direction,
    first: bool,
    entity: &ModBlockEntity,
    draw: &mut BlockEntityDraw,
) {
    let Some(Some(stack)) = read_filter(&entity.nbt) else {
        return;
    };
    if game.player.as_ref().is_some_and(|player| {
        player.position.distance_squared(Vec3::new(
            f64::from(pos[0]) + 0.5,
            f64::from(pos[1]) + 0.5,
            f64::from(pos[2]) + 0.5,
        )) > 100.0
    }) {
        return;
    }
    for side in Direction::ALL {
        if let Some(slot) = FilterSlot::new(facing, first, side) {
            slot.draw(game, draw, &stack);
        }
    }
}

pub(super) fn draw_station(
    game: &Game<'_>,
    pos: Pos,
    entity: &ModBlockEntity,
    draw: &mut BlockEntityDraw,
) {
    let Some(facing) = contraption::facing(game, pos) else {
        return;
    };
    let first = game
        .native_block_property(pos, "axis_along_first")
        .as_deref()
        == Some("true");
    let holding = get(&entity.nbt, "HeldItem").is_some_and(|held| held.get("id").is_some());
    let mode = mode(&entity.nbt).unwrap_or_default();
    let rpm = kinetics::number(&entity.nbt, "Speed");
    let arm = station_state(&entity.nbt).map_or(0.0, |mut cycle| {
        cycle.reach = kinetics::number(&entity.nbt, "Reach");
        if let Some(Tag::Int(sample)) = get(&entity.nbt, UPDATE_TICK) {
            let elapsed = (draw.game_time as i32).wrapping_sub(*sample).clamp(0, 128);
            cycle.timer = (cycle.timer - elapsed * timer_speed(rpm)).max(0);
        }
        cycle.hand_extension(rpm, draw.partial, holding)
    });
    let shaft_angle = kinetics::node(game, pos).map_or(0.0, |node| {
        create_engine::visual::angle(
            draw.game_time as f64 + f64::from(draw.partial),
            rpm,
            create_engine::visual::rotation_offset(pos, node.axis, false),
        )
    });
    draw_arm(
        game, draw, facing, first, shaft_angle, arm, hand_pose(mode, holding),
    );
    draw_filter(game, pos, facing, first, entity, draw);
    if let Some(stack) = get(&entity.nbt, "HeldItem")
        .and_then(item_from_nbt)
        .filter(supported_item)
    {
        draw_held_item(
            game,
            draw,
            facing,
            kinetics::running_speed(game, &entity.nbt),
            arm,
            mode,
            &stack,
        );
    }
}

// DeployerRenderer.renderItem: the supported items use flat generated models.
fn draw_held_item(
    game: &Game<'_>,
    draw: &mut BlockEntityDraw,
    facing: Direction,
    rpm: f32,
    extension: f32,
    mode: Mode,
    stack: &ItemStack,
) {
    draw.push();
    draw.translate(
        facing
            .vector()
            .map(|component| 0.5 + component as f32 * extension),
    );
    let yaw = match facing {
        Direction::North => 0.0,
        Direction::East => -90.0,
        Direction::West => 90.0,
        _ => 180.0,
    };
    draw.rotate_about([0., 1., 0.], yaw, [0.; 3]);
    let display = if facing == Direction::Up && rpm == 0.0 && mode == Mode::Use {
        draw.translate([0., 11. / 16., 0.]);
        // Catnip's client animation clock advances one degree per tick.
        let spin = super::create_port_particles::animation_time(draw.partial);
        draw.rotate_about([0., 1., 0.], spin, [0.; 3]);
        DisplayContext::Ground
    } else {
        let pitch = match facing {
            Direction::Up => 90.0,
            Direction::Down => -90.0,
            _ => 0.0,
        };
        draw.rotate_about([1., 0., 0.], pitch, [0.; 3]);
        draw.translate([0., 0., -11. / 16.]);
        if mode == Mode::Punch {
            draw.translate([0., 1. / 8., -1. / 16.]);
            draw.scale([0.75; 3]);
            DisplayContext::ThirdPersonRightHand
        } else {
            draw.scale([0.5; 3]);
            DisplayContext::Fixed
        }
    };
    game.native_draw_item(draw, stack, display, None, 0);
    draw.pop();
}

pub(super) fn draw_moving(
    game: &Game<'_>,
    draw: &mut BlockEntityDraw,
    record: &Record,
    local: Pos,
    state: &BlockState,
) {
    let Some(facing) = state
        .properties
        .get("facing")
        .and_then(|name| Direction::ALL.into_iter().find(|face| face.name() == name))
    else {
        return;
    };
    let active =
        DVec3::from_array(create_engine::deployer::active_point(local, facing)) - DVec3::splat(0.5);
    let sample = |angle| {
        DVec3::from_array(record.origin_at(1.0))
            + record.orientation(angle) * active
            + DVec3::splat(0.5)
    };
    let point = sample(record.angle);
    let previous = sample(record.previous_angle);
    let render_time = super::create_port_particles::animation_time(draw.partial);
    // Centered actors and disabled movement modes are outside the mounted
    // Deployer adapter's capture scope. A saw, drill or dock can still stall
    // the whole bearing, which drives the hand and pole's source oscillation.
    let extension = create_engine::deployer::moving_extension(
        Some(point.to_array()),
        (point - previous).to_array(),
        record.stalled,
        false,
        render_time,
        draw.partial,
    );
    static TRACE: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
    if *TRACE.get_or_init(|| std::env::var_os("CREATE_TRACE_CONTRAPTION_FRAMES").is_some()) {
        log::info!(
            "Create deployer actor frame: {}",
            serde_json::json!({
                "controller":record.controller, "local":local, "time":draw.game_time,
                "partial":draw.partial, "render_time":render_time, "stalled":record.stalled,
                "extension":extension, "position":point.to_array(),
                "motion":(point - previous).to_array(),
            })
        );
    }
    let first = state
        .properties
        .get("axis_along_first")
        .is_some_and(|value| value == "true");
    draw_arm(game, draw, facing, first, 0.0, extension, HandPose::Pointing);
}

fn get<'a>(nbt: &'a Compound, key: &str) -> Option<&'a Tag> {
    nbt.get(&key.into())
}

pub(super) fn mode(nbt: &Compound) -> Option<Mode> {
    let Tag::String(value) = get(nbt, "Mode")? else {
        return None;
    };
    let value = value.to_string().ok()?;
    matches!(value.as_str(), "USE" | "PUNCH").then(|| Mode::from_saved(&value))
}

fn supported_moving_item(item: &ItemStack) -> bool {
    (SAPLINGS.contains(&item.item.as_ref()) || item.item.as_ref() == BONE_MEAL)
        && (1..=64).contains(&item.count)
        && item.damage == 0
        && item.data().is_none()
}

fn supported_item(item: &ItemStack) -> bool {
    supported_moving_item(item)
        || ((item.item.starts_with("minecraft:") && item.item.ends_with("_planks")
            || matches!(
                item.item.as_ref(),
                "create:cogwheel"
                    | "create:large_cogwheel"
                    | "minecraft:iron_nugget"
                    | "minecraft:honeycomb_block"
            ))
            && (1..=64).contains(&item.count)
            && item.damage == 0)
        || (item.item.starts_with("minecraft:") && item.item.ends_with("_axe") && item.count == 1)
}

fn held_kind(item: &ItemStack) -> Held<'_> {
    if item.item.as_ref() == BONE_MEAL {
        Held::Other
    } else {
        Held::Block(&item.item)
    }
}

fn read_hand(nbt: &Compound) -> Option<Option<ItemStack>> {
    let hand = match get(nbt, "Inventory") {
        None => None,
        Some(Tag::List(items)) if items.is_empty() => None,
        Some(Tag::List(items)) if items.len() == 1 => {
            let item = item_from_nbt(&items[0])?;
            if !supported_item(&item)
                || encode_items(&[Some(item.clone())]) != Tag::List(items.clone())
            {
                return None;
            }
            Some(item)
        }
        _ => return None,
    };
    if let Some(display) = get(nbt, "HeldItem") {
        let expected = hand
            .as_ref()
            .map_or_else(|| Tag::Compound(Compound::new()), item_to_nbt);
        if *display != expected {
            return None;
        }
    }
    Some(hand)
}

fn valid_nbt(nbt: &Compound) -> bool {
    get(nbt, "Mode") == Some(&Tag::String("USE".into()))
        && nbt
            .iter()
            .all(|(key, val)| match key.to_string().as_deref() {
                Ok("Mode" | "Inventory" | "HeldItem") => true,
                Ok("State") => *val == Tag::String("WAITING".into()),
                Ok("Timer") => matches!(val, Tag::Int(-511..=5120)),
                Ok("Powered") => *val == Tag::Byte(0),
                Ok("Owner") => matches!(val, Tag::IntArray(uuid) if uuid.len() == 4),
                Ok("Overflow") => matches!(val, Tag::List(items) if items.is_empty()),
                Ok("Filter") => true,
                Ok("FilterAmount") => matches!(val, Tag::Int(0..=64)),
                Ok("UpTo") => matches!(val, Tag::Byte(0 | 1)),
                Ok("Speed") => *val == Tag::Float(0),
                Ok("Stress" | "Capacity") => matches!(val, Tag::Float(_)),
                Ok("NetworkStatus") => matches!(val, Tag::String(_)),
                Ok("create_horizon") => detached_ports(val),
                _ => false,
            })
        && read_filter(nbt).is_some_and(|filter| {
            filter.as_ref().is_none_or(supported_moving_item)
                && read_hand(nbt).is_some_and(|hand| {
                    hand.as_ref().is_none_or(supported_moving_item)
                        && filter.as_ref().is_none_or(|filter| {
                            hand.as_ref().is_none_or(|held| held.item == filter.item)
                        })
                })
        })
}

fn detached_ports(tag: &Tag) -> bool {
    let Tag::Compound(data) = tag else {
        return false;
    };
    data.len() == 2
        && get(data, "TheoreticalSpeed") == Some(&Tag::Float(0))
        && matches!(get(data, "Ports"), Some(Tag::Compound(ports)) if ports.len() == 6
            && Direction::ALL.into_iter().all(|face| get(ports, face.name()) == Some(&Tag::Float(0)))
        )
}

fn read_filter(nbt: &Compound) -> Option<Option<ItemStack>> {
    let Some(filter) = get(nbt, "Filter") else {
        return Some(None);
    };
    if matches!(filter, Tag::Compound(parts) if parts.is_empty()) {
        return Some(None);
    }
    let stack = item_from_nbt(filter)?;
    (supported_item(&stack) && item_to_nbt(&stack) == *filter).then_some(Some(stack))
}

fn filter_rejects_hand(filter: Option<&ItemStack>, hand: Option<&ItemStack>) -> bool {
    filter
        .zip(hand)
        .is_some_and(|(filter, held)| held.item != filter.item)
}

fn write_hand(nbt: &mut Compound, hand: Option<ItemStack>) {
    nbt.insert(
        "HeldItem".into(),
        hand.as_ref()
            .map_or_else(|| Tag::Compound(Compound::new()), item_to_nbt),
    );
    nbt.insert("Inventory".into(), encode_items(&[hand]));
}

fn consistent_hand(entity: &ModBlockEntity) -> Option<Option<ItemStack>> {
    let hand = read_hand(&entity.nbt)?;
    // Java-shaped commands may initialize only Inventory. The native slot
    // tracks hand swaps and is spillable when an ordinary block breaks. A
    // stack received from the player's inventory may retain a wire patch.
    (entity.items.len() <= 1
        && entity
            .items
            .first()
            .and_then(Option::as_ref)
            .is_none_or(|slot| {
                hand.as_ref()
                    .is_some_and(|held| slot == held || item_to_nbt(slot) == item_to_nbt(held))
            }))
    .then_some(hand)
}

fn entity<'a>(game: &'a Game<'_>, pos: Pos) -> Option<&'a ModBlockEntity> {
    let Some(BlockEntity::Mod(entity)) = game.world.block_entities.get(&(pos[0], pos[1], pos[2]))
    else {
        return None;
    };
    (entity.id == BLOCK && consistent_hand(entity).is_some()).then_some(entity)
}

fn station_state(nbt: &Compound) -> Option<Stationary> {
    let mode = mode(nbt)?;
    let phase = match get(nbt, "State") {
        None => Phase::Waiting,
        Some(Tag::String(phase)) => match phase.to_string().ok()?.as_str() {
            "WAITING" => Phase::Waiting,
            "EXPANDING" => Phase::Expanding,
            "RETRACTING" => Phase::Retracting,
            _ => return None,
        },
        _ => return None,
    };
    let timer = match get(nbt, "Timer") {
        None => 0,
        Some(Tag::Int(timer)) if (-511..=5120).contains(timer) => *timer,
        _ => return None,
    };
    Some(Stationary {
        mode,
        phase,
        timer,
        ..Stationary::default()
    })
}

pub(super) fn transports(game: &Game<'_>, pos: Pos) -> bool {
    game.native_block(pos) == BLOCK
        && contraption::facing(game, pos) == Some(Direction::Down)
        && entity(game, pos).is_some_and(|entity| station_state(&entity.nbt).is_some())
}

enum TransportRecipe {
    Output(ItemStack),
    Weighted(Vec<(ItemStack, f32)>),
}

impl TransportRecipe {
    fn apply(self, game: &mut Game<'_>) -> Option<ItemStack> {
        match self {
            Self::Output(stack) => Some(stack),
            Self::Weighted(mut pool) => {
                let weights = pool.iter().map(|(_, weight)| *weight).collect::<Vec<_>>();
                let index = sequenced::roll_result(&weights, game.world.random.next_float())?;
                Some(pool.swap_remove(index).0)
            }
        }
    }
}

fn ingredient_matches(game: &Game<'_>, data: &serde_json::Value, stack: &ItemStack) -> bool {
    kinetics::ingredient(data)
        .and_then(|value| game.native_recipe_ingredient(&value))
        .is_some_and(|ingredient| ingredient.test(stack))
}

fn sequence_recipe(
    game: &Game<'_>,
    input: &ItemStack,
    hand: &ItemStack,
) -> Option<TransportRecipe> {
    let definition = game
        .native_recipes_of_type("create:sequenced_assembly")
        .iter()
        .find(|recipe| recipe.id == PRECISION_RECIPE)?;
    let data = &definition.json;
    let transitional = &data["transitional_item"];
    let step = if let Some(component) = input.data().and_then(|data| data.other(SEQUENCE_COMPONENT))
    {
        let (Tag::String(recipe), Tag::Int(step), Tag::Float(_)) = (
            component.get("id")?,
            component.get("step")?,
            component.get("progress")?,
        ) else {
            return None;
        };
        if recipe != &PRECISION_RECIPE.into() || transitional["id"].as_str()? != input.item.as_ref()
        {
            return None;
        }
        *step
    } else {
        if !ingredient_matches(game, &data["ingredient"], input) {
            return None;
        }
        0
    };
    let sequence = data["sequence"].as_array()?;
    let loops = u32::try_from(data["loops"].as_u64()?).ok()?;
    let next = sequenced::step(sequence.len(), loops, step)?;
    let recipe = &sequence[next.recipe_index];
    let [_, held] = recipe["ingredients"].as_array()?.as_slice() else {
        return None;
    };
    if recipe["type"] != "create:deploying" || !ingredient_matches(game, held, hand) {
        return None;
    }
    if let Some(progress) = next.next {
        let mut output = game.native_recipe_result(transitional)?;
        output.data_mut().set_other(
            SEQUENCE_COMPONENT,
            Some(Tag::Compound(Compound::from([
                ("id".into(), Tag::String(PRECISION_RECIPE.into())),
                ("step".into(), Tag::Int(progress.step)),
                ("progress".into(), Tag::Float(progress.fraction.to_bits())),
            ]))),
        );
        return Some(TransportRecipe::Output(output));
    }
    let pool = data["results"]
        .as_array()?
        .iter()
        .map(|entry| {
            let weight = entry
                .get("chance")
                .map_or(Some(1.0), serde_json::Value::as_f64)? as f32;
            Some((game.native_recipe_result(entry)?, weight))
        })
        .collect::<Option<Vec<_>>>()?;
    Some(TransportRecipe::Weighted(pool))
}

fn applied_recipe(
    game: &Game<'_>,
    input: &ItemStack,
    hand: &ItemStack,
) -> Option<(TransportRecipe, bool)> {
    if let Some(recipe) = sequence_recipe(game, input, hand) {
        return Some((recipe, false));
    }
    for recipe in game.native_recipes_of_type("create:deploying") {
        let data = &recipe.json;
        let Some([base, held]) = data["ingredients"].as_array().map(Vec::as_slice) else {
            continue;
        };
        let Some([result]) = data["results"].as_array().map(Vec::as_slice) else {
            continue;
        };
        let keep_held = data["keep_held_item"].as_bool().unwrap_or(false);
        let gear = matches!(
            recipe.id.as_str(),
            "create:deploying/cogwheel" | "create:deploying/large_cogwheel"
        );
        let copper = keep_held
            && recipe.id.starts_with("create:deploying/")
            && [
                "_from_adding_wax",
                "_from_removing_wax",
                "_from_deoxidising",
            ]
            .into_iter()
            .any(|suffix| recipe.id.ends_with(suffix));
        if !gear && !copper {
            continue;
        }
        if ingredient_matches(game, base, input) && ingredient_matches(game, held, hand) {
            return game
                .native_recipe_result(result)
                .map(|stack| (TransportRecipe::Output(stack), keep_held));
        }
    }
    None
}

fn start_transport(game: &mut Game<'_>, pos: Pos, mut state: Stationary) {
    let Some(aim) = stationary_aim(pos, Direction::Down) else {
        return;
    };
    let ray = aim.reach_probe();
    state.start(aim.reach(clip(game, ray).map_or(ray.end, |hit| hit.point)));
    let tick = game.world.game_time as i32;
    game.native_with_mod_block_entity(pos, |entity| {
        entity
            .nbt
            .insert("State".into(), Tag::String(state.phase.saved_name().into()));
        entity.nbt.insert("Timer".into(), Tag::Int(state.timer));
        entity.data = vec![state.reach.to_bits() as i32, tick];
    });
    game.native_block_entity_sync(pos);
}

pub(super) fn process_transport(
    game: &mut Game<'_>,
    pos: Pos,
    item: &mut Transported<ItemStack>,
    already_held: bool,
) -> ProcessingUpdate<ItemStack> {
    let Some(member) = entity(game, pos) else {
        return ProcessingResult::Pass.into();
    };
    let (Some(state), Some(hand)) = (station_state(&member.nbt), consistent_hand(member)) else {
        return ProcessingResult::Pass.into();
    };
    // The original refuses new cargo in PUNCH. Its held-item callback still
    // finishes an operation already accepted by USE before the switch.
    if (state.mode == Mode::Punch && !already_held)
        || kinetics::running_speed(game, &member.nbt) == 0.0
    {
        return ProcessingResult::Pass.into();
    }
    let input = belt::game_stack(&item.stack);
    let recipe = hand
        .as_ref()
        .and_then(|stack| applied_recipe(game, &input, stack));
    let may_start = state.phase != Phase::Waiting
        || read_filter(&member.nbt)
            .is_some_and(|filter| !filter_rejects_hand(filter.as_ref(), hand.as_ref()));
    let dimension = game.dim.id().to_owned();
    let powered = game.native_neighbor_signal(&dimension, pos) != 0;
    match belt_action(
        state,
        already_held,
        powered,
        hand.is_some(),
        recipe.is_some(),
    ) {
        BeltAction::Pass => ProcessingResult::Pass.into(),
        BeltAction::Hold => ProcessingResult::Hold.into(),
        BeltAction::Start => {
            if may_start {
                start_transport(game, pos, state);
            }
            ProcessingResult::Hold.into()
        }
        BeltAction::Apply => {
            let (Some(mut hand), Some((recipe, keep_held))) = (hand, recipe) else {
                return ProcessingResult::Pass.into();
            };
            let Some(result) = recipe.apply(game) else {
                return ProcessingResult::Pass.into();
            };
            let mut empty = false;
            if !keep_held {
                hand.count -= 1;
                empty = hand.count == 0;
                let hand = (!empty).then_some(hand);
                if game
                    .native_with_mod_block_entity(pos, |member| {
                        member.items = vec![hand.clone()];
                        write_hand(&mut member.nbt, hand);
                    })
                    .is_none()
                {
                    return ProcessingResult::Pass.into();
                }
                game.native_block_entity_sync(pos);
            }
            super::create_port_sounds::deployer_apply(game, pos, empty);

            let mut output = item.source_copy();
            output.angle = belt::angle(game, &result);
            output.stack = belt::core_stack(game, result);
            item.clear_fan_processing();
            let left = (item.stack.count > 1).then(|| {
                let mut left = item.source_copy();
                left.stack.count -= 1;
                left
            });
            ProcessingUpdate {
                decision: ProcessingResult::Hold,
                conversion: Some(TransportedResult::Convert {
                    outputs: vec![output],
                    held: left,
                }),
            }
        }
    }
}

pub(super) fn tick_station(
    game: &mut Game<'_>,
    pos: Pos,
    entity: &mut ModBlockEntity,
    rpm: f32,
) -> bool {
    let Some(facing) = contraption::facing(game, pos) else {
        return false;
    };
    if !matches!(get(&entity.nbt, "Powered"), None | Some(Tag::Byte(0 | 1)))
        || !get(&entity.nbt, "Overflow")
            .is_none_or(|v| matches!(v, Tag::List(items) if items.is_empty()))
    {
        return false;
    }
    let (Some(aim), Some(mut cycle), Some(hand), Some(filter)) = (
        stationary_aim(pos, facing),
        station_state(&entity.nbt),
        consistent_hand(entity),
        read_filter(&entity.nbt),
    ) else {
        return false;
    };
    let target = aim.clicked;
    let dim = game.dim.id().to_owned();
    let powered = i8::from(game.native_neighbor_signal(&dim, pos) != 0);
    let mut changed = get(&entity.nbt, "Powered") != Some(&Tag::Byte(powered));
    if changed {
        entity.nbt.insert("Powered".into(), Tag::Byte(powered));
    }
    if let Some(stack) = &hand
        && entity.items.first().is_none_or(Option::is_none)
    {
        entity.items = vec![Some(stack.clone())];
        write_hand(&mut entity.nbt, hand.clone());
        changed = true;
    }
    cycle.reach = f32::from_bits(entity.data.first().copied().unwrap_or(0) as u32);
    let previous = cycle;
    let action = cycle.tick(rpm, |mode| {
        // Java checks the hand filter only on entering the waiting branch.
        // Until there is an overflow inventory, keep a mismatched hand parked.
        if filter_rejects_hand(filter.as_ref(), hand.as_ref())
            || !contraption::resident(game, target)
        {
            return Waiting::Locked;
        }
        let block = game.native_block(target);
        if mode == Mode::Use
            && !should_use(
                hand.as_ref().map_or(Held::Empty, held_kind),
                Target {
                    block: &block,
                    fluid: None,
                    transports_items: matches!(block.as_str(), "create:belt" | "create:depot"),
                },
                Some(facing),
            )
        {
            return Waiting::Retry;
        }
        if powered != 0 {
            return Waiting::Locked;
        }
        let probe = aim.reach_probe();
        Waiting::Start {
            reach: aim.reach(clip(game, probe).map_or(probe.end, |hit| hit.point)),
        }
    });
    if cycle != previous || changed || entity.data.len() != 2 {
        entity.data = vec![cycle.reach.to_bits() as i32, game.world.game_time as i32];
        if cycle.timer != previous.timer || get(&entity.nbt, "Timer").is_none() {
            entity.nbt.insert("Timer".into(), Tag::Int(cycle.timer));
        }
        if cycle.phase != previous.phase || get(&entity.nbt, "State").is_none() {
            entity
                .nbt
                .insert("State".into(), Tag::String(cycle.phase.saved_name().into()));
        }
    }
    if matches!(action, TickAction::Activate { .. }) && cycle.mode == Mode::Use {
        let block = game.native_block(target);
        if block == "minecraft:lever" && hand.is_none() {
            use_lever(game, aim, facing);
        } else if facing == Direction::Down
            && !matches!(block.as_str(), "create:belt" | "create:depot")
            && let Some(mut stack) = hand
            && use_item(game, aim, &stack, Face::Up)
        {
            stack.count -= 1;
            let remaining = (stack.count != 0).then_some(stack);
            entity.items = vec![remaining.clone()];
            write_hand(&mut entity.nbt, remaining);
        }
    }
    changed || action != TickAction::None
}

fn use_lever(game: &mut Game<'_>, aim: Aim, facing: Direction) {
    use horizon_client::mod_api::NativeUseTarget;

    let [x, _, z] = aim.clicked;
    if !contraption::resident(game, aim.clicked) || !game.border.contains(f64::from(x), f64::from(z))
    {
        return;
    }
    let ray = aim.action_ray();
    let hit = clip(game, ray);
    let face = hit
        .as_ref()
        .and_then(|hit| native_face(hit.face))
        .or_else(|| native_face(facing.opposite().vector()));
    let Some(face) = face else { return };
    let _ = game.native_use_as_player(
        ItemStack::new("minecraft:air", 0),
        ray.start,
        aim.yaw,
        aim.pitch,
        NativeUseTarget::Block {
            pos: aim.clicked,
            face,
            point: hit.map_or(ray.end, |hit| hit.point),
        },
        false,
    );
}

fn use_item(game: &mut Game<'_>, aim: Aim, stack: &ItemStack, fallback: Face) -> bool {
    if stack.item.as_ref() != BONE_MEAL {
        return sapling_context(game, aim, stack, fallback)
            .is_some_and(|context| place_sapling(game, &context));
    }
    let [x, y, z] = aim.clicked;
    if !contraption::resident(game, aim.clicked)
        || !game.border.contains(f64::from(x), f64::from(z))
        || !matches!(
            game.native_block(aim.clicked).as_str(),
            "minecraft:oak_sapling"
                | "minecraft:wheat"
                | "minecraft:carrots"
                | "minecraft:potatoes"
                | "minecraft:beetroots"
        )
    {
        return false;
    }
    // DeployerHandler forces the action ray onto the prescribed cell and
    // preserves the ray face. Vanilla growth reports use even on failed rolls.
    let face = clip(game, aim.action_ray())
        .and_then(|hit| native_face(hit.face))
        .unwrap_or(fallback);
    let used = game
        .with_level(|b, level, ticks| b.use_bone_meal(level, ticks, BlockPos::new(x, y, z), face));
    if used {
        let _ = game.process_level_events();
    }
    used
}

pub(super) fn placed(game: &mut Game<'_>, pos: Pos) {
    let uuid = game.acting_player_uuid().to_vec();
    game.native_with_mod_block_entity(pos, |entity| {
        entity.nbt.insert("Owner".into(), Tag::IntArray(uuid));
    });
}

fn exchange_target(game: &Game<'_>, pos: Pos, hit: [f64; 3], held: Option<&ItemStack>) -> bool {
    if !game.native_on("create")
        || game.native_block(pos) != BLOCK
        || !game.may_build()
        || game.keys.contains(&winit::keyboard::KeyCode::ShiftLeft)
        || held.is_some_and(|held| !supported_item(held))
    {
        return false;
    }
    forward_hit(game, pos, hit).is_some_and(|distance| distance >= 0.75)
}

fn forward_hit(game: &Game<'_>, pos: Pos, hit: [f64; 3]) -> Option<f64> {
    let facing = contraption::facing(game, pos)?;
    let axis = facing.axis().index();
    let back = f64::from(pos[axis]) + 0.5 - f64::from(facing.vector()[axis]) * 0.5;
    Some((hit[axis] - back).abs())
}

pub(super) fn wrench(game: &mut Game<'_>, pos: Pos, face: Direction) -> bool {
    if !game.may_build() {
        return false;
    }
    if game.pick().is_some_and(|hit| {
        hit.pos == pos && forward_hit(game, pos, hit.point).is_some_and(|distance| distance > 0.75)
    }) {
        let Some(next) = entity(game, pos).and_then(|entity| match mode(&entity.nbt)? {
            Mode::Use => Some(Mode::Punch),
            Mode::Punch => Some(Mode::Use),
        }) else {
            return true;
        };
        if game
            .native_with_mod_block_entity(pos, |entity| {
                entity.nbt.insert("Mode".into(), Tag::String(next.saved_name().into()));
            })
            .is_some()
        {
            game.native_block_entity_sync(pos);
        }
        return true;
    }
    super::create_port_interactions::wrench_directional_axis(game, pos, face)
}

fn filter_slot(game: &Game<'_>, hit: &super::Hit) -> Option<FilterSlot> {
    let facing = contraption::facing(game, hit.pos)?;
    let first = game
        .native_block_property(hit.pos, "axis_along_first")
        .as_deref()
        == Some("true");
    FilterSlot::new(facing, first, Direction::from_vector(hit.face)?)
}

pub(super) fn filter_display(
    game: &Game<'_>,
    hit: &super::Hit,
) -> Option<super::create_port_motor_value_world::FilterDisplay> {
    use super::create_port_motor_value_world::{FilterDisplay, FilterLabel};

    let slot = filter_slot(game, hit)?;
    let filter = read_filter(&entity(game, hit.pos)?.nbt)?;
    Some(FilterDisplay::sample(
        slot.center,
        [slot.yaw, slot.pitch, 0.0],
        FilterLabel::Item,
        slot.contains(hit.pos, hit.point),
        filter.is_some(),
    ))
}

fn filter_target(game: &Game<'_>, hit: &super::Hit) -> bool {
    use winit::keyboard::KeyCode;

    if !game.native_on("create")
        || game.native_block(hit.pos) != BLOCK
        || !game.may_build()
        || game.keys.contains(&KeyCode::ShiftLeft)
        || game.keys.contains(&KeyCode::ShiftRight)
        || game.has_shift_down()
        || game.stack_in(game.selected).is_some_and(|item| {
            item.item.as_ref() == "create:clipboard"
                || (item.item.as_ref() != "create:wrench"
                    && super::create_port_chassis::wrench(game, item))
        })
    {
        return false;
    }
    filter_slot(game, hit).is_some_and(|slot| slot.contains(hit.pos, hit.point))
}

fn configure_filter(game: &mut Game<'_>, pos: Pos) {
    let Some(entity) = entity(game, pos) else {
        return;
    };
    let sample = game.held().filter(|item| item.count != 0);
    if sample.is_some_and(|item| !supported_item(item)) || read_filter(&entity.nbt).is_none() {
        return;
    }
    let value = sample.map_or_else(|| Tag::Compound(Compound::new()), item_to_nbt);
    if game
        .native_with_mod_block_entity(pos, |entity| {
            entity.nbt.insert("Filter".into(), value);
            entity.nbt.entry("UpTo".into()).or_insert(Tag::Byte(1));
            entity
                .nbt
                .entry("FilterAmount".into())
                .or_insert(Tag::Int(64));
        })
        .is_none()
    {
        return;
    }
    game.native_block_entity_sync(pos);
    let at = pos.map(|coordinate| f64::from(coordinate) + 0.5);
    game.with_level(|_, level, _| {
        level.native_play_sound("minecraft:entity.item_frame.add_item", at, 4, 0.25, 0.1);
    });
}

pub(super) fn predicts(game: &Game<'_>, hit: &super::Hit, held: Option<&ItemStack>) -> bool {
    filter_target(game, hit) || exchange_target(game, hit.pos, hit.point, held)
}

pub(super) fn right_click(game: &mut Game<'_>, pos: Pos) -> bool {
    if game
        .pick()
        .is_some_and(|hit| hit.pos == pos && filter_target(game, &hit))
    {
        configure_filter(game, pos);
        return true;
    }
    let held = game.held().cloned();
    let Some(hit) = game
        .pick()
        .filter(|hit| hit.pos == pos && exchange_target(game, pos, hit.point, held.as_ref()))
    else {
        return false;
    };
    let Some(entity) = entity(game, hit.pos) else {
        return false;
    };
    let (Some(previous), Some(filter)) = (read_hand(&entity.nbt), read_filter(&entity.nbt)) else {
        return false;
    };
    if let (Some(item), Some(filter)) = (held.as_ref(), filter)
        && item.item != filter.item
    {
        return false;
    }
    if held.is_none() && previous.is_none() {
        return true;
    }
    if game
        .native_with_mod_block_entity(pos, |entity| {
            entity.items = vec![held.clone()];
            write_hand(&mut entity.nbt, held);
        })
        .is_none()
    {
        return false;
    }
    *game.held_mut() = previous;
    game.native_block_entity_sync(pos);
    true
}

pub(super) fn can_capture(game: &Game<'_>, pos: Pos, state: &BlockState) -> bool {
    if !block_state(state)
        || state
            .properties
            .get("facing")
            .is_none_or(|face| face != "down")
        || !entity(game, pos).is_some_and(|entity| valid_nbt(&entity.nbt))
    {
        return false;
    }
    let key = (pos[0], pos[1], pos[2]);
    let [x, z] = contraption::column(pos);
    !game.world.block_names.contains_key(&key)
        && game.world.block_lock(key).is_none()
        && !game
            .world
            .block_entities
            .chunk_attachments(x, z)
            .iter()
            .any(|(p, _)| *p == key)
        && game
            .world
            .chunks
            .get(&(x, z))
            .and_then(|c| c.saved.as_ref())
            .is_none_or(|saved| {
                !saved
                    .block_entity_attachments
                    .iter()
                    .any(|(p, _)| *p == key)
                    && !saved.rolled_loot.iter().any(|loot| loot.pos == key)
                    && saved
                        .block_entity_sources
                        .iter()
                        .find(|(p, _)| *p == key)
                        .is_none_or(|(_, source)| source_ok(source))
            })
}

fn source_ok(source: &Tag) -> bool {
    let Tag::Compound(fields) = source else {
        return false;
    };
    if fields
        .iter()
        .any(|(key, tag)| match key.to_string().as_deref() {
            Ok("id") => *tag != Tag::String(BLOCK.into()),
            Ok("x" | "y" | "z") => !matches!(tag, Tag::Int(_)),
            Ok("keepPacked") => !matches!(tag, Tag::Byte(0)),
            _ => false,
        })
    {
        return false;
    }
    let mut nbt = fields.clone();
    nbt.retain(|key, _| {
        !matches!(
            key.to_string().as_deref(),
            Ok("id" | "x" | "y" | "z" | "keepPacked")
        )
    });
    if nbt.get(&"Items".into()).is_some_and(|tag| {
        matches!(tag, Tag::List(items) if items.is_empty()) || get(&nbt, "Inventory") == Some(tag)
    }) {
        nbt.remove(&"Items".into());
    }
    if nbt
        .get(&"components".into())
        .is_some_and(|tag| matches!(tag, Tag::Compound(parts) if parts.is_empty()))
    {
        nbt.remove(&"components".into());
    }
    valid_nbt(&nbt)
}

fn valid_local(local: Pos) -> bool {
    (local[0] != 0 || local[2] != 0)
        && local
            .into_iter()
            .all(|coordinate| coordinate.unsigned_abs() <= 15)
}

fn local_deployers(blocks: &[(Pos, BlockState)]) -> Result<Vec<Pos>, AttachmentError> {
    let mut result = Vec::new();
    for (local, block) in blocks.iter().filter(|(_, block)| block.name == BLOCK) {
        // Centered actors use the source's separate StationaryTimer path.
        if !valid_local(*local)
            || !block_state(block)
            || block
                .properties
                .get("facing")
                .is_none_or(|face| face != "down")
            || result.len() == MAX_DEPLOYERS
            || result.contains(local)
        {
            return Err(AttachmentError::Decode);
        }
        result.push(*local);
    }
    Ok(result)
}

pub(super) fn capture(
    game: &Game<'_>,
    anchor: Pos,
    blocks: &[(Pos, BlockState)],
) -> Result<Option<Cargo>, AttachmentError> {
    let locals = local_deployers(blocks)?;
    if locals.is_empty() {
        return Ok(None);
    }
    let mut cargo = Cargo::new();
    for local in locals {
        let pos = std::array::from_fn(|i| anchor[i] + local[i]);
        let entity = entity(game, pos)
            .filter(|entity| valid_nbt(&entity.nbt) && consistent_hand(entity).is_some())
            .ok_or(AttachmentError::Encode)?;
        let mut nbt = entity.nbt.clone();
        for key in [
            "Speed",
            "Stress",
            "Capacity",
            "NetworkStatus",
            "create_horizon",
        ] {
            nbt.remove(&key.into());
        }
        cargo.insert(local, nbt);
    }
    Ok(Some(cargo))
}

pub(super) fn commit_capture(
    game: &mut Game<'_>,
    key: [i32; 2],
    records: Vec<Record>,
    edits: &[Edit],
    controller: Pos,
    chest: Option<storage::Chest>,
    cargo: Option<Cargo>,
) -> bool {
    let Some(cargo) = cargo else {
        return storage::commit_capture(game, key, records, edits, controller, chest);
    };
    transaction(
        game,
        key,
        |store| store.insert(controller, cargo).is_none(),
        |game| storage::commit_capture(game, key, records, edits, controller, chest),
    )
}

pub(super) fn commit_landing(
    game: &mut Game<'_>,
    key: [i32; 2],
    records: Vec<Record>,
    edits: &[Edit],
    record: &Record,
    turn: QuarterTurn,
) -> bool {
    let locals = match local_deployers(&record.blocks) {
        Ok(locals) => locals,
        Err(_) => return false,
    };
    if locals.is_empty() {
        return storage::commit_landing(game, key, records, edits, record, record.anchor, turn);
    }
    let mut destinations = Vec::with_capacity(locals.len());
    for local in locals {
        let Some(pos) = turn.place(record.anchor, local) else {
            return false;
        };
        if contraption::column(pos) != key
            || game
                .world
                .block_entities
                .contains_key(&(pos[0], pos[1], pos[2]))
            || !edits.iter().any(|&(at, _, state)| {
                at == pos
                    && game
                        .pack
                        .assets
                        .registry
                        .state(state)
                        .is_some_and(block_state)
            })
        {
            return false;
        }
        destinations.push((local, pos));
    }
    let mut restored = Vec::with_capacity(destinations.len());
    if !transaction(
        game,
        key,
        |store| {
            let Some(mut cargo) = store.remove(&record.controller) else {
                return false;
            };
            if cargo.len() != destinations.len() {
                return false;
            }
            for (local, pos) in destinations {
                let Some(nbt) = cargo.remove(&local) else {
                    return false;
                };
                let Some(hand) = read_hand(&nbt) else {
                    return false;
                };
                restored.push((pos, nbt, hand));
            }
            true
        },
        |game| storage::commit_landing(game, key, records, edits, record, record.anchor, turn),
    ) {
        return false;
    }
    for (pos, nbt, hand) in restored {
        game.world.block_entities.insert(
            (pos[0], pos[1], pos[2]),
            BlockEntity::Mod(Box::new(ModBlockEntity::new(ModBlockEntityFields {
                id: BLOCK.into(),
                nbt,
                items: vec![hand],
                ..ModBlockEntityFields::default()
            }))),
        );
        game.native_block_entity_sync(pos);
    }
    true
}

fn transaction(
    game: &mut Game<'_>,
    key: [i32; 2],
    change: impl FnOnce(&mut Store) -> bool,
    commit: impl FnOnce(&mut Game<'_>) -> bool,
) -> bool {
    let holder = Holder::Chunk(key);
    let Ok(map) = game.attachment_map_quiet(holder) else {
        return false;
    };
    let Ok(mut store) = map.get(&CARGO) else {
        return false;
    };
    if !change(&mut store) {
        return false;
    }
    let before = map.clone();
    let saved = if store.is_empty() {
        map.remove(&CARGO).map(|_| ())
    } else {
        map.set(&CARGO, store)
    };
    if saved.is_err() {
        return false;
    }
    if commit(game) {
        return true;
    }
    if let Ok(map) = game.attachment_map_quiet(holder) {
        *map = before;
    }
    false
}

pub(super) fn supported_record(record: &Record) -> bool {
    record.axis == Axis::Y.index()
        && record.stroke.is_none()
        && record.clock_hand.is_none()
        && !record.return_home
}

pub(super) fn plant(game: &mut Game<'_>, record: &Record, local: Pos, aim: Aim) {
    let target = aim.clicked;
    let key = contraption::column(record.controller);
    if game.options.execution_role != super::execution_role::ExecutionRole::IntegratedServer
        || !supported_record(record)
    {
        return;
    }
    let holder = Holder::Chunk(key);
    let Ok(Some(store)) = game
        .attachment_map_quiet(holder)
        .and_then(|map| map.get_existing(&CARGO))
    else {
        return;
    };
    let Some(nbt) = store
        .get(&record.controller)
        .and_then(|cargo| cargo.get(&local))
    else {
        return;
    };
    let (Some(mut hand), Some(filter)) = (read_hand(nbt), read_filter(nbt)) else {
        return;
    };
    // The actor refills on a visit even if shouldActivate or placement later
    // refuses the target. In that case the one withdrawn item stays held.
    if grabs_from_storage(hand.is_none(), false)
        && let Some(mount) = storage::mounted_chest(record)
    {
        hand = storage::withdraw_one(
            game,
            mount,
            |item| {
                filter
                    .as_ref()
                    .is_none_or(|filter| item.item == filter.item)
            },
            |game, item| {
                supported_moving_item(item)
                    && update_hand(
                        game,
                        key,
                        record.controller,
                        local,
                        Some(item.clone()),
                        |_| true,
                    )
            },
        );
    }
    let Some(hand) = hand else { return };
    if key != contraption::column(target) {
        return;
    }
    let name = game.native_block(target);
    if moving_action(
        Mode::Use,
        held_kind(&hand),
        Target {
            block: &name,
            fluid: None,
            transports_items: false,
        },
        false,
    ) != MovingAction::World(Mode::Use)
    {
        return;
    }
    let ray = aim.action_ray();
    let fallback = if (ray.end[0] - ray.start[0]).abs() > (ray.end[2] - ray.start[2]).abs() {
        if ray.end[0] > ray.start[0] {
            Face::West
        } else {
            Face::East
        }
    } else if ray.end[2] > ray.start[2] {
        Face::North
    } else {
        Face::South
    };
    let mut remaining = hand.clone();
    remaining.count -= 1;
    update_hand(
        game,
        key,
        record.controller,
        local,
        (remaining.count > 0).then_some(remaining),
        |game| use_item(game, aim, &hand, fallback),
    );
}

fn clip(game: &Game<'_>, ray: Segment) -> Option<super::Hit> {
    let segment = DVec3::from_array(ray.end) - DVec3::from_array(ray.start);
    let length = segment.length();
    if !length.is_finite() || length == 0.0 {
        return None;
    }
    game.clip_ray(ray.start, (segment / length).to_array(), length)
}

fn sapling_context(
    game: &mut Game<'_>,
    aim: Aim,
    stack: &ItemStack,
    fallback: Face,
) -> Option<PlaceContext> {
    let target = aim.clicked;
    if !contraption::resident(game, target)
        || !game
            .border
            .contains(f64::from(target[0]), f64::from(target[2]))
        || !game.res.facts().is_air(contraption::state(game, target))
    {
        return None;
    }
    let ray = aim.action_ray();
    let (face, point) = clip(game, ray).map_or((fallback, ray.end), |hit| {
        (native_face(hit.face).unwrap_or(fallback), hit.point)
    });
    let pos = BlockPos::new(target[0], target[1], target[2]);
    let ctx = PlaceContext {
        clicked_pos: pos,
        face,
        hit: Vec3::new(point[0], point[1], point[2]),
        inside: false,
        yaw: aim.yaw,
        pitch: aim.pitch,
        sneaking: false,
        item: stack.item.to_string(),
        can_use_game_master_blocks: false,
    };
    game.with_level(|b, l, t| b.placement_state(l, t, &ctx))
        .is_some_and(|(at, _)| at == pos)
        .then_some(ctx)
}

fn place_sapling(game: &mut Game<'_>, context: &PlaceContext) -> bool {
    let placed = matches!(
        game.with_level(|b, l, t| b.place_block(l, t, context)),
        PlaceOutcome::Placed { .. }
    );
    if placed {
        let _ = game.process_level_events();
    }
    placed
}

fn update_hand(
    game: &mut Game<'_>,
    key: [i32; 2],
    controller: Pos,
    local: Pos,
    hand: Option<ItemStack>,
    commit: impl FnOnce(&mut Game<'_>) -> bool,
) -> bool {
    transaction(
        game,
        key,
        |store| {
            let Some(nbt) = store
                .get_mut(&controller)
                .and_then(|cargo| cargo.get_mut(&local))
            else {
                return false;
            };
            write_hand(nbt, hand);
            true
        },
        commit,
    )
}

fn native_face(normal: Pos) -> Option<Face> {
    Some(match normal {
        [0, -1, 0] => Face::Down,
        [0, 1, 0] => Face::Up,
        [0, 0, -1] => Face::North,
        [0, 0, 1] => Face::South,
        [-1, 0, 0] => Face::West,
        [1, 0, 0] => Face::East,
        _ => return None,
    })
}

fn encode(store: &Store) -> Result<Compound, AttachmentError> {
    if store.len() > MAX_RECORDS
        || store.values().any(|cargo| {
            cargo.is_empty()
                || cargo.len() > MAX_DEPLOYERS
                || cargo
                    .iter()
                    .any(|(&local, nbt)| !valid_local(local) || !valid_nbt(nbt))
        })
    {
        return Err(AttachmentError::Encode);
    }
    let entries = store
        .iter()
        .flat_map(|(controller, cargo)| {
            cargo.iter().map(|(local, nbt)| {
                Tag::compound([
                    ("Controller", Tag::IntArray(controller.to_vec())),
                    ("Pos", Tag::IntArray(local.to_vec())),
                    ("Data", Tag::Compound(nbt.clone())),
                ])
            })
        })
        .collect();
    Ok(Compound::from([
        ("Version".into(), Tag::Int(2)),
        ("Deployers".into(), Tag::List(entries)),
    ]))
}

fn decode(saved: &Compound) -> Result<Store, AttachmentError> {
    let invalid = AttachmentError::Decode;
    let Some(Tag::List(entries)) = get(saved, "Deployers") else {
        return Err(invalid);
    };
    let limit = match get(saved, "Version") {
        Some(Tag::Int(1)) => 1,
        Some(Tag::Int(2)) => MAX_DEPLOYERS,
        _ => return Err(invalid),
    };
    if saved.len() != 2 || entries.len() > MAX_RECORDS * limit {
        return Err(invalid);
    }
    let position = |entry: &Tag, key: &str| match entry.get(key) {
        Some(Tag::IntArray(values)) => <Pos>::try_from(values.as_slice()).map_err(|_| invalid),
        _ => Err(invalid),
    };
    let mut store = Store::new();
    for entry in entries {
        if !matches!(entry, Tag::Compound(fields) if fields.len() == 3) {
            return Err(invalid);
        }
        let Some(Tag::Compound(nbt)) = entry
            .get("Data")
            .filter(|tag| matches!(tag, Tag::Compound(nbt) if valid_nbt(nbt)))
        else {
            return Err(invalid);
        };
        let local = position(entry, "Pos")?;
        let cargo = store.entry(position(entry, "Controller")?).or_default();
        if !valid_local(local) || cargo.len() == limit || cargo.insert(local, nbt.clone()).is_some()
        {
            return Err(invalid);
        }
    }
    (store.len() <= MAX_RECORDS).then_some(store).ok_or(invalid)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn deployer_filter_uses_only_the_two_faces_clear_of_the_hand_and_shaft() {
        let down = FilterSlot::new(Direction::Down, true, Direction::South).unwrap();
        assert_eq!(down.center, [0.5, 0.625, 0.96875]);
        assert_eq!((down.yaw, down.pitch), (180.0, 0.0));
        let up = FilterSlot::new(Direction::East, false, Direction::Up).unwrap();
        assert_eq!(up.center, [0.375, 0.96875, 0.5]);
        assert_eq!((up.yaw, up.pitch), (90.0, 90.0));
        let pos = [1230, 109, 101];
        let point = [1230.5, 109.625, 101.96875];
        assert!(down.contains(pos, [point[0] + 0.249, point[1], point[2]]));
        assert!(!down.contains(pos, [point[0] + 0.25, point[1], point[2]]));

        for facing in Direction::ALL {
            for first in [false, true] {
                let active = Direction::ALL
                    .into_iter()
                    .filter(|&side| FilterSlot::new(facing, first, side).is_some())
                    .collect::<Vec<_>>();
                assert_eq!(active.len(), 2);
                assert_eq!(active[0].opposite(), active[1]);
                assert_ne!(active[0].axis(), facing.axis());
                assert_ne!(active[0].axis(), shaft_axis(facing, first));
            }
        }
    }

    const CONTROLLER: Pos = [1159, 99, 55];
    const PLANTER: Pos = [2, 0, 0];
    const FERTILIZER: Pos = [-2, 0, 0];
    const SAPLING: &str = "minecraft:oak_sapling";

    fn hand(item: &str, count: i32) -> Compound {
        let mut nbt = default_nbt();
        let stack =
            |count| Tag::compound([("id", Tag::String(item.into())), ("count", Tag::Int(count))]);
        nbt.insert("Filter".into(), stack(1));
        write_hand(&mut nbt, Some(item_from_nbt(&stack(count)).unwrap()));
        nbt
    }

    fn row(controller: Pos, local: Pos, nbt: Compound) -> Tag {
        Tag::compound([
            ("Controller", Tag::IntArray(controller.to_vec())),
            ("Pos", Tag::IntArray(local.to_vec())),
            ("Data", Tag::Compound(nbt)),
        ])
    }

    fn saved(version: i32, entries: Vec<Tag>) -> Compound {
        Compound::from([
            ("Version".into(), Tag::Int(version)),
            ("Deployers".into(), Tag::List(entries)),
        ])
    }

    #[test]
    fn reads_a_legacy_hand_and_writes_it_under_its_local_position() {
        let nbt = hand(SAPLING, 3);
        let old = saved(1, vec![row(CONTROLLER, PLANTER, nbt.clone())]);
        let store = decode(&old).unwrap();
        assert_eq!(store[&CONTROLLER][&PLANTER], nbt);
        let upgraded = encode(&store).unwrap();
        assert_eq!(upgraded, saved(2, vec![row(CONTROLLER, PLANTER, nbt)]));
        assert_eq!(decode(&upgraded).unwrap(), store);
    }

    #[test]
    fn restores_two_hands_with_independent_stock_and_filters() {
        let store = Store::from([(
            CONTROLLER,
            Cargo::from([
                (PLANTER, hand(SAPLING, 3)),
                (FERTILIZER, hand(BONE_MEAL, 7)),
            ]),
        )]);
        let reloaded = decode(&encode(&store).unwrap()).unwrap();
        assert_eq!(reloaded, store);
        for (local, item, count) in [(PLANTER, SAPLING, 3), (FERTILIZER, BONE_MEAL, 7)] {
            let nbt = &reloaded[&CONTROLLER][&local];
            assert_eq!(read_hand(nbt).unwrap().unwrap().count, count);
            assert_eq!(read_filter(nbt).unwrap().unwrap().item.as_ref(), item);
        }
    }

    #[test]
    fn refuses_duplicate_actors_and_too_many_hands() {
        let nbt = hand(SAPLING, 1);
        let planter = row(CONTROLLER, PLANTER, nbt.clone());
        let fertilizer = row(CONTROLLER, FERTILIZER, nbt.clone());
        assert!(decode(&saved(1, vec![planter.clone(), fertilizer.clone()])).is_err());
        assert!(decode(&saved(2, vec![planter.clone(), planter.clone()])).is_err());
        let third = row(CONTROLLER, [0, 0, 2], nbt.clone());
        assert!(decode(&saved(2, vec![planter, fertilizer, third])).is_err());
        let excess_controllers = (0..=MAX_RECORDS as i32)
            .map(|x| row([x, 99, 55], PLANTER, nbt.clone()))
            .collect();
        assert!(decode(&saved(2, excess_controllers)).is_err());
    }
}
