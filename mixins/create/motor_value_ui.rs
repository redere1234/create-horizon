// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT
// Create 6.0.10 ValueSettingsClient/Screen and KineticScrollValueBehaviour.
// Rendering uses the original private value_settings.png sheet via the importer.
use super::create_port_motor_control::MotionOptions;
use super::create_port_motor_value_world::FilterLabel;
use super::{Game, create_port_chassis as chassis, create_port_chute as chute};
use crate::{containers::BlockEntity, mod_api::NativeScreenView};
use create_engine::contraption::chassis::{DEFAULT_RANGE, MAX_RANGE};
use horizon_client::{
    first_person::Hand,
    hud::{HudBatch, rgba},
    keybinds,
    text::{Style, Text},
};
use horizon_world::nbt::Tag;
use std::cell::RefCell;

const SPRITE: &str = "create:gui/value_settings";
pub(super) const ICONS: &str = "create:gui/icons";
const BACKDROP: [u8; 4] = [24, 16, 12, 216];
const FRAME: [u8; 4] = [181, 125, 61, 255];
const LABEL: [u8; 4] = [221, 178, 104, 255];
const TRACK: [u8; 4] = [63, 43, 28, 255];
const MILESTONE: [u8; 4] = [123, 86, 51, 255];
const CURSOR: [u8; 4] = [250, 211, 129, 255];
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct Setting {
    row: i32,
    value: i32,
}
#[derive(Clone, Copy)]
struct Holding {
    target: Target,
    ticks: u8,
}
#[derive(Clone, Copy)]
struct Panel {
    target: Target,
    ticks: u32,
    hovered: Option<Setting>,
    sound_cooldown: u8,
}
#[derive(Default)]
struct State {
    holding: Option<Holding>,
    panel: Option<Panel>,
    cursor: Option<[f32; 2]>,
    sound: Option<f32>,
    submission: Option<(Target, Setting, bool)>,
    close: bool,
    hover_warmup: i32,
    hover_ticks: i32,
    last_hover_tip: Option<HoverTip>,
}
thread_local! {static STATE: RefCell<State> = RefCell::new(State::default());}

#[derive(Clone, Copy)]
enum HoverTip {
    Board(Board),
    Filter {
        label: FilterLabel,
        filled: bool,
        show_amount: bool,
    },
}

impl HoverTip {
    fn lines(self) -> (Text, Text, Option<Text>) {
        match self {
            Self::Board(board) => (
                board.title(),
                Text::translate_with_fallback(
                    "create.gui.value_settings.hold_to_edit",
                    "Click and hold to edit",
                    &[],
                ),
                None,
            ),
            Self::Filter {
                label,
                filled,
                show_amount,
            } => (
                match label {
                    FilterLabel::Item => {
                        Text::translate_with_fallback("create.logistics.filter", "Filter", &[])
                    }
                    FilterLabel::Recipe => Text::translate_with_fallback(
                        "create.logistics.recipe_filter",
                        "Recipe Filter",
                        &[],
                    ),
                },
                if filled {
                    Text::translate_with_fallback(
                        "create.logistics.filter.click_to_replace",
                        "Click with item to replace",
                        &[],
                    )
                } else {
                    Text::translate_with_fallback(
                        "create.logistics.filter.click_to_set",
                        "Click with item to set",
                        &[],
                    )
                },
                show_amount.then(|| filter_text("hold_to_set_amount", "Click and hold for amount")),
            ),
        }
    }
}

fn filter_text(key: &str, fallback: &str) -> Text {
    Text::translate_with_fallback(&format!("create.logistics.filter.{key}"), fallback, &[])
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Board {
    Motor,
    LinearChassis,
    RadialChassis,
    Motion(MotionOptions),
    Filter { maximum: i32 },
}

impl MotionOptions {
    fn title(self) -> Text {
        let (key, fallback) = match self {
            Self::Mechanical | Self::Piston | Self::Pulley => {
                ("create.contraptions.movement_mode", "Movement Mode")
            }
            Self::Windmill => (
                "create.contraptions.windmill.rotation_direction",
                "Rotation Direction",
            ),
            Self::Clockwork => (
                "create.contraptions.clockwork.clock_hands",
                "Clock Hand Arrangement",
            ),
        };
        Text::translate_with_fallback(key, fallback, &[])
    }

    fn label(self, value: i32) -> Text {
        let (key, fallback) = match self {
            Self::Mechanical => [
                (
                    "create.contraptions.movement_mode.rotate_place",
                    "Always Place when Stopped",
                ),
                (
                    "create.contraptions.movement_mode.rotate_place_returned",
                    "Only Place near Initial Angle",
                ),
                (
                    "create.contraptions.movement_mode.rotate_never_place",
                    "Only Place when Anchor Destroyed",
                ),
            ][value as usize],
            Self::Windmill => [
                ("create.generic.clockwise", "Clockwise"),
                ("create.generic.counter_clockwise", "Counter-Clockwise"),
            ][value as usize],
            Self::Clockwork => [
                (
                    "create.contraptions.clockwork.hour_first",
                    "Hour hand first",
                ),
                (
                    "create.contraptions.clockwork.minute_first",
                    "Minute hand first",
                ),
                (
                    "create.contraptions.clockwork.hour_first_24",
                    "24-Hour hand first",
                ),
            ][value as usize],
            Self::Piston | Self::Pulley => [
                (
                    "create.contraptions.movement_mode.move_place",
                    "Always Place when Stopped",
                ),
                (
                    "create.contraptions.movement_mode.move_place_returned",
                    "Place only in Starting Position",
                ),
                (
                    "create.contraptions.movement_mode.move_never_place",
                    "Place only when Anchor Destroyed",
                ),
            ][value as usize],
        };
        Text::translate_with_fallback(key, fallback, &[])
    }

    // AllIcons indices in the original 16x16 tile grid.
    pub(super) fn icon(self, value: i32) -> [f32; 2] {
        let value = value as f32;
        match self {
            Self::Mechanical => [6.0 + value, 1.0],
            Self::Windmill if value == 0.0 => [3.0, 1.0],
            Self::Windmill => [4.0, 5.0],
            Self::Clockwork => [5.0 + value, 5.0],
            Self::Piston | Self::Pulley => [9.0 + value, 1.0],
        }
    }
}

impl Board {
    fn title(self) -> Text {
        let key = match self {
            Self::Motor => "create.kinetics.creative_motor.rotation_speed",
            Self::LinearChassis => "create.contraptions.chassis.range",
            Self::RadialChassis => "create.contraptions.chassis.radius",
            Self::Motion(options) => return options.title(),
            Self::Filter { .. } => return filter_text("extracted_amount", "Extracted Amount"),
        };
        Text::translate(key, &[])
    }

    fn max(self) -> i32 {
        match self {
            Self::Motor => 256,
            Self::Motion(options) => options.max(),
            Self::Filter { maximum } => maximum,
            _ => i32::from(MAX_RANGE) - 1,
        }
    }

    fn milestone(self) -> i32 {
        match self {
            Self::Motor => 32,
            Self::Filter { .. } => 16,
            _ => 1,
        }
    }

    fn rows(self) -> i32 {
        match self {
            Self::Motor | Self::Filter { .. } => 2,
            _ => 1,
        }
    }

    fn milestone_size(self) -> i32 {
        if matches!(self, Self::Motion(_)) {
            8
        } else {
            4
        }
    }

    fn label(self, row: i32) -> Text {
        match self {
            Self::Motor => arrow(row),
            Self::Motion(_) => Text::literal("Select"),
            Self::Filter { .. } if row == 0 => filter_text("up_to", "Up to"),
            Self::Filter { .. } => filter_text("exactly", "Exactly"),
            _ => Text::translate("create.contraptions.chassis.distance", &[]),
        }
    }

    fn formatted(self, setting: Setting) -> Text {
        match self {
            Self::Motor => {
                crate::game::create_port_goggles::numeral(f64::from(setting.value.abs().max(1)))
                    .append(arrow(setting.row))
            }
            Self::Filter { maximum } if setting.row == 0 && setting.value == maximum => {
                filter_text("any_amount_short", "Any")
            }
            Self::Filter { .. } => Text::literal(format!(
                "{}{}",
                if setting.row == 0 { '≤' } else { '=' },
                setting.value.max(1)
            )),
            Self::Motion(options) => options.label(setting.value),
            _ => crate::game::create_port_goggles::numeral(f64::from(setting.value + 1)),
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct Target {
    pos: [i32; 3],
    board: Board,
}

impl Target {
    fn setting(self, game: &Game<'_>) -> Setting {
        match self.board {
            Board::Motor => {
                let value = saved(game, self.pos);
                Setting {
                    row: i32::from(value >= 0),
                    value: value.saturating_abs().min(256),
                }
            }
            Board::Filter { maximum } => chute::amount_board(game, self.pos).map_or(
                Setting {
                    row: 0,
                    value: maximum,
                },
                |amount| Setting {
                    row: i32::from(!amount.up_to),
                    value: amount.value,
                },
            ),
            Board::Motion(options) => Setting {
                row: 0,
                value: match game.world.block_entities.get(&self.pos.into()) {
                    Some(BlockEntity::Mod(entity)) => options.selection(entity),
                    _ => 0,
                },
            },
            _ => {
                let value = chassis::configured_range(game, self.pos).unwrap_or(DEFAULT_RANGE);
                Setting {
                    row: 0,
                    value: i32::from(value) - 1,
                }
            }
        }
    }
}
fn arrow(row: i32) -> Text {
    Text::styled(
        if row == 0 { "⟳" } else { "⟲" },
        Style {
            bold: Some(true),
            ..Style::default()
        },
    )
}
fn can_interact(game: &Game<'_>) -> bool {
    game.player.is_some() && game.may_build() && !game.native_sneaking()
}
fn saved(game: &Game<'_>, pos: [i32; 3]) -> i32 {
    match game.world.block_entities.get(&(pos[0], pos[1], pos[2])) {
        Some(BlockEntity::Mod(entity)) => match entity.nbt.get(&"ScrollValue".into()) {
            Some(Tag::Int(value)) => *value,
            _ => 16,
        },
        _ => 16,
    }
}
// CreativeMotorBlockEntity.MotorValueBox plus ValueBoxTransform.testHit.
fn target(game: &Game<'_>) -> Option<Target> {
    let hit = game.pick()?;
    let block = game.native_block(hit.pos);
    if let Some(options) = MotionOptions::for_block(&block) {
        return super::create_port_motor_value_world::motion_hit(game, &hit, options).then_some(
            Target {
                pos: hit.pos,
                board: Board::Motion(options),
            },
        );
    }
    let board = match block.as_str() {
        "create:linear_chassis" | "create:secondary_linear_chassis" => Board::LinearChassis,
        "create:radial_chassis" => Board::RadialChassis,
        "create:creative_motor" => Board::Motor,
        _ => {
            return chute::amount_board_hit(game, &hit, &block).map(|amount| Target {
                pos: hit.pos,
                board: Board::Filter {
                    maximum: amount.maximum,
                },
            });
        }
    };
    let target = Target {
        pos: hit.pos,
        board,
    };
    if board != Board::Motor {
        return (game.held().is_some_and(|item| chassis::wrench(game, item))
            && chassis::configured_range(game, hit.pos).is_some()
            && chassis::value_box_hit(hit.pos, hit.face, hit.point))
        .then_some(target);
    }
    let facing = match game.native_block_property(hit.pos, "facing")?.as_str() {
        "east" => [1, 0, 0],
        "west" => [-1, 0, 0],
        "up" => [0, 1, 0],
        "down" => [0, -1, 0],
        "south" => [0, 0, 1],
        "north" => [0, 0, -1],
        _ => return None,
    };
    let axis = facing.iter().position(|value| *value != 0)?;
    if hit.face[axis] != 0 || (axis != 1 && hit.face == [0, -1, 0]) {
        return None;
    }
    let distance = (0..3)
        .map(|axis| {
            let offset =
                0.5 + f64::from(hit.face[axis]) * 4.5 / 16.0 - f64::from(facing[axis]) / 16.0;
            (hit.point[axis] - f64::from(hit.pos[axis]) - offset).powi(2)
        })
        .sum::<f64>();
    (distance < 0.25 * 0.25).then_some(target)
}

pub(super) fn chassis_preview_value(pos: [i32; 3]) -> Option<i32> {
    STATE.with_borrow(|state| {
        let panel = state.panel?;
        (panel.target.pos == pos
            && matches!(
                panel.target.board,
                Board::LinearChassis | Board::RadialChassis
            ))
        .then(|| panel.hovered.map(|setting| setting.value + 1))
        .flatten()
    })
}

/// Alive source Outliner entries suppress goggles, including their expiry ticks.
pub(super) fn active_value_box(game: &Game<'_>) -> bool {
    crate::game::create_port_motor_value_world::active(game)
}

pub(super) fn interaction(
    game: &mut Game<'_>,
    button: i32,
    hand: Hand,
    _swing: &mut bool,
    canceled: &mut bool,
) {
    if button != 1
        || hand != Hand::Main
        || !game.native_on("create")
        || !can_interact(game)
        || game
            .held()
            .is_some_and(|stack| stack.item.as_ref() == "create:clipboard")
    {
        return;
    }
    let Some(target) = target(game) else {
        return;
    };
    STATE.with_borrow_mut(|state| {
        if state.holding.is_none() {
            state.holding = Some(Holding { target, ticks: 0 });
        }
    });
    *canceled = true;
}

/// Call once per real client tick, including while the non-pausing board is open.
pub(super) fn tick(game: &mut Game<'_>) {
    if !game.native_window() || !game.native_on("create") {
        return;
    }
    STATE.with_borrow_mut(|state| {
        state.hover_warmup = (state.hover_warmup - 1).max(0);
        state.hover_ticks = (state.hover_ticks - 1).max(0);
        if let Some(panel) = &mut state.panel {
            panel.ticks = panel.ticks.saturating_add(1);
            panel.sound_cooldown = panel.sound_cooldown.saturating_sub(1);
        }
    });
    let holding = STATE.with_borrow(|state| state.holding);
    if let Some(mut holding) = holding {
        let valid = can_interact(game)
            && target(game) == Some(holding.target)
            && !game
                .held()
                .is_some_and(|stack| stack.item.as_ref() == "create:clipboard");
        if !valid || !game.native_mapping("key.use").is_some_and(|value| value.0) {
            STATE.with_borrow_mut(|state| state.holding = None);
            if valid && matches!(holding.target.board, Board::Filter { .. }) {
                send_filter_tap(game, holding.target.pos);
            }
        } else if holding.ticks >= 5 {
            STATE.with_borrow_mut(|state| state.holding = None);
            if game.native_mod_screen_open("create") {
                let current = holding.target.setting(game);
                STATE.with_borrow_mut(|state| {
                    state.panel = Some(Panel {
                        target: holding.target,
                        ticks: 0,
                        hovered: None,
                        sound_cooldown: 0,
                    });
                    if let Some(size) = game.native_physical_window_size() {
                        let batch = HudBatch::new(size);
                        state.cursor = Some(
                            layout(game, [batch.width, batch.height], holding.target.board)
                                .coordinate(current),
                        );
                    }
                });
            }
        } else {
            holding.ticks += 1;
            STATE.with_borrow_mut(|state| state.holding = Some(holding));
        }
    }
    if game.native_mod_screen().is_none()
        && let Some(tip) = target(game)
            .filter(|target| !matches!(target.board, Board::Filter { .. }))
            .map(|target| HoverTip::Board(target.board))
            .or_else(|| {
                super::create_port_motor_value_world::filter_hover(game).map(
                    |(label, filled, show_amount)| HoverTip::Filter {
                        label,
                        filled,
                        show_amount,
                    },
                )
            })
    {
        // ScrollValueRenderer.showHoverTip; one call per client tick.
        STATE.with_borrow_mut(|state| {
            if state.hover_warmup < 6 {
                state.hover_warmup += 2;
            } else {
                state.hover_warmup += 1;
                state.hover_ticks = if state.hover_ticks == 0 {
                    11
                } else {
                    state.hover_ticks.max(6)
                };
                state.last_hover_tip = Some(tip);
            }
        });
    }
}

fn send_filter_tap(game: &mut Game<'_>, pos: [i32; 3]) {
    let Some(hit) = game.pick().filter(|hit| hit.pos == pos) else {
        return;
    };
    let offset = std::array::from_fn::<_, 3, _>(|axis| {
        ((hit.point[axis] - f64::from(pos[axis])) as f32).to_bits() as i32
    });
    let mut bytes = Vec::with_capacity(32);
    for value in pos
        .into_iter()
        .chain([hit.face[0], hit.face[2]])
        .chain(offset)
    {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    if let Err(error) = game.native_net_send_to_server("create:filter_tap", &bytes) {
        log::debug!("Create filter tap: {error}");
    }
}

#[derive(Clone, Copy, Debug)]
struct Layout {
    x: i32,
    y: i32,
    label: i32,
    bar: i32,
    width: i32,
    height: i32,
    board: Board,
}
impl Layout {
    fn coordinate(self, setting: Setting) -> [f32; 2] {
        let column = setting.value;
        let interval = self.board.milestone();
        let size = self.board.milestone_size();
        let mut x = self.x as f32
            + (((column.max(1) - 1) / interval) * size + column * self.scale()) as f32
            + 1.5;
        x += (self.label + 18) as f32;
        if column % interval == 0 {
            x += (size / 2) as f32;
        }
        if column > 0 {
            x += size as f32;
        }
        [x, self.y as f32 + (setting.row as f32 + 0.5) * 11.0 - 0.5]
    }
    fn closest(self, mouse: [f32; 2], shift: bool) -> Setting {
        let [mx, my] = mouse.map(|value| value as i32);
        let mut row = 0;
        let mut best = f64::MAX;
        for candidate in 0..self.board.rows() {
            let difference = f64::from(
                (self.coordinate(Setting {
                    row: candidate,
                    value: 0,
                })[1]
                    - my as f32)
                    .abs(),
            );
            if best < difference {
                break;
            }
            best = difference;
            row = candidate;
        }
        best = f64::MAX;
        let mut value = 0;
        for column in 0..=self.board.max() {
            let candidate = if shift {
                column * self.board.milestone()
            } else {
                column
            };
            let difference = f64::from(
                (self.coordinate(Setting {
                    row,
                    value: candidate,
                })[0]
                    - mx as f32)
                    .abs(),
            );
            if best < difference {
                break;
            }
            best = difference;
            value = candidate.min(self.board.max());
        }
        Setting { row, value }
    }
    fn scale(self) -> i32 {
        if self.board.max() > 128 { 1 } else { 2 }
    }
}
fn layout(game: &Game<'_>, size: [f32; 2], board: Board) -> Layout {
    let label = if matches!(board, Board::Motion(_)) {
        -18
    } else {
        (0..board.rows())
            .map(|row| game.gui.atlas.font.width_text(&board.label(row)) as i32)
            .max()
            .unwrap_or(0)
    };
    let scale = if board.max() > 128 { 1 } else { 2 };
    let bar = (board.max() + 1) * scale
        + 1
        + (board.max() / board.milestone() + 1) * board.milestone_size();
    let width = label + 14 + bar + 10;
    let height = board.rows() * 11;
    Layout {
        x: (size[0] as i32 - width) / 2,
        y: (size[1] as i32 - height) / 2,
        label,
        bar,
        width,
        height,
        board,
    }
}

fn quad(game: &Game<'_>, batch: &mut HudBatch, src: [f32; 4], dst: [f32; 4], fallback: [u8; 4]) {
    if !game.native_sprite(batch, SPRITE, src, dst) && dst[2] > 0.0 && dst[3] > 0.0 {
        // Author a solid-color panel when the player has no private Create art.
        let [r, g, b, a] = fallback;
        let color = rgba(r, g, b, a);
        let [x, y, w, h] = dst;
        batch.fill_gradient(&game.gui.atlas, (x, y, w, h), color, color);
    }
}
// UIRenderHelper.drawCropped samples with the original sheet's repeating UVs.
// Split at the 256px sheet boundary so a crop never reads a neighboring atlas slot.
fn crop(
    game: &Game<'_>,
    batch: &mut HudBatch,
    source: [i32; 2],
    at: [i32; 2],
    size: [i32; 2],
    fallback: [u8; 4],
) {
    let mut dy = 0;
    while dy < size[1] {
        let sy = (source[1] + dy).rem_euclid(256);
        let h = (256 - sy).min(size[1] - dy);
        let mut dx = 0;
        while dx < size[0] {
            let sx = (source[0] + dx).rem_euclid(256);
            let w = (256 - sx).min(size[0] - dx);
            quad(
                game,
                batch,
                [sx as f32, sy as f32, w as f32, h as f32],
                [(at[0] + dx) as f32, (at[1] + dy) as f32, w as f32, h as f32],
                fallback,
            );
            dx += w;
        }
        dy += h;
    }
}
fn frame_border(game: &Game<'_>, batch: &mut HudBatch, x: i32, y: i32, w: i32, h: i32) {
    for (src, at) in [
        ([65, 9], [x, y]),
        ([70, 9], [x + w - 4, y]),
        ([65, 19], [x, y + h - 4]),
        ([70, 19], [x + w - 4, y + h - 4]),
    ] {
        crop(game, batch, src, at, [4, 4], FRAME);
    }
    if h > 8 {
        quad(
            game,
            batch,
            [65., 14., 3., 4.],
            [x as f32, (y + 4) as f32, 3., (h - 8) as f32],
            FRAME,
        );
        quad(
            game,
            batch,
            [71., 14., 3., 4.],
            [(x + w - 3) as f32, (y + 4) as f32, 3., (h - 8) as f32],
            FRAME,
        );
    }
    if w > 8 {
        crop(game, batch, [0, 24], [x + 4, y], [w - 8, 3], FRAME);
        crop(game, batch, [0, 27], [x + 4, y + h - 3], [w - 8, 3], FRAME);
    }
}
fn text(game: &Game<'_>, batch: &mut HudBatch, text: &Text, at: [i32; 2], rgb: u32) {
    let [_, r, g, b] = rgb.to_be_bytes();
    batch.text_styled(
        &game.gui.atlas,
        text,
        at[0] as f32,
        at[1] as f32,
        rgba(r, g, b, 255),
        false,
    );
}

fn mode_icon(game: &Game<'_>, batch: &mut HudBatch, icon: [f32; 2], at: [i32; 2]) -> bool {
    let Some(mut rect) = game.gui.atlas.sprites.get(ICONS).copied() else {
        return false;
    };
    let width = (rect.u1 - rect.u0) / 16.0;
    let height = (rect.v1 - rect.v0) / 16.0;
    rect.u0 += icon[0] * width;
    rect.v0 += icon[1] * height;
    rect.u1 = rect.u0 + width;
    rect.v1 = rect.v0 + height;
    batch.rect_uv(
        at[0] as f32,
        at[1] as f32,
        16.0,
        16.0,
        rect,
        rgba(68, 32, 0, 255),
    );
    true
}

pub(super) fn draw(game: &Game<'_>, batch: &mut HudBatch, screen: &NativeScreenView<'_>) {
    if game.native_mod_screen() != Some("create") {
        return;
    }
    let Some(panel) = STATE.with_borrow(|state| state.panel) else {
        return;
    };
    let board = panel.target.board;
    let icon_mode = matches!(board, Board::Motion(_));
    let extra_height = if icon_mode { 46 } else { 33 };
    let l = layout(game, [batch.width, batch.height], board);
    let partial = screen.partial_tick;
    let shade = (80.0 * ((panel.ticks as f32 + partial) / 20.0).min(1.0)) as u8;
    batch.fill_gradient(
        &game.gui.atlas,
        (0., 0., batch.width, batch.height),
        rgba(16, 16, 16, shade),
        rgba(16, 16, 16, shade),
    );
    let title = board.title();
    let use_name = keybinds::display_name(game.settings.keys.get("key.use"));
    let tip = Text::translate_with_fallback(
        "create.gui.value_settings.release_to_confirm",
        "Release %1$s to Confirm",
        &[use_name],
    );
    let font = &game.gui.atlas.font;
    let mut fattest = font.width_text(&title).max(font.width_text(&tip)) as i32;
    if let Board::Motion(options) = board {
        for value in 0..=options.max() {
            fattest = fattest.max(font.width_text(&options.label(value)) as i32);
        }
    }
    let fat_offset = (fattest + 10 - (l.width + 13)).max(0) / 2;
    let bg_width = (l.width + 13).max(fattest + 10);
    let fade = ((panel.ticks as f32 + partial) / 4.0).clamp(0., 1.);
    let fade_width = (bg_width as f64 * f64::from(fade)) as i32;
    let fade_start = (bg_width - fade_width) / 2 - fat_offset;
    quad(
        game,
        batch,
        [80., 9., 1., 1.],
        [
            (l.x - 11 + fade_start) as f32,
            (l.y - 17) as f32,
            fade_width as f32,
            (l.height + extra_height) as f32,
        ],
        BACKDROP,
    );
    quad(
        game,
        batch,
        [80., 9., 1., 1.],
        [
            (l.x - 10 + fade_start) as f32,
            (l.y - 18) as f32,
            (fade_width - 2) as f32,
            1.,
        ],
        BACKDROP,
    );
    // The pinned source's third drawStretched call has width=zLevel=0;
    // it draws no bottom-strip pixels. Preserve that observable behavior.
    if fade_width > fattest {
        let center = l.x - 11 - fat_offset + bg_width / 2;
        text(
            game,
            batch,
            &title,
            [
                center - game.gui.atlas.font.width_text(&title) as i32 / 2,
                l.y - 14,
            ],
            0xdddddd,
        );
        text(
            game,
            batch,
            &tip,
            [
                center - game.gui.atlas.font.width_text(&tip) as i32 / 2,
                l.y + l.height + extra_height - 27,
            ],
            0xdddddd,
        );
    }
    frame_border(
        game,
        batch,
        l.x + l.label + 14,
        l.y - 3,
        l.bar + 8,
        l.height + 5,
    );
    quad(
        game,
        batch,
        [75., 9., 1., 1.],
        [
            (l.x + l.label + 17) as f32,
            l.y as f32,
            (l.bar + 2) as f32,
            (l.height - 1) as f32,
        ],
        TRACK,
    );
    for row in 0..board.rows() {
        let y = l.y + row * 11;
        let bar_x = l.x + l.label + 18;
        if !icon_mode {
            crop(game, batch, [0, 31], [l.x - 4, y], [l.label + 8, 11], LABEL);
            for w in (0..l.bar).step_by(248) {
                crop(
                    game,
                    batch,
                    [7, 0],
                    [bar_x + w, y + 1],
                    [(l.bar - w).min(249), 8],
                    TRACK,
                );
            }
            text(game, batch, &board.label(row), [l.x, y + 1], 0x442000);
        }
        let spacing = board.milestone_size() + board.milestone() * l.scale();
        let (source, size) = if icon_mode {
            ([75, 14], [13, 8])
        } else {
            ([0, 0], [7, 8])
        };
        for milestone in 0..=board.max() / board.milestone() {
            crop(
                game,
                batch,
                source,
                [bar_x + milestone * spacing, y + 1],
                size,
                MILESTONE,
            );
        }
    }
    if !icon_mode {
        frame_border(game, batch, l.x - 7, l.y - 3, l.label + 14, l.height + 5);
    }
    if panel.ticks < 1 {
        return;
    }
    let shift = game.has_shift_down();
    let hovered = l.closest(screen.mouse, shift);
    STATE.with_borrow_mut(|state| {
        let Some(current) = state.panel.as_mut() else {
            return;
        };
        if current.hovered != Some(hovered) && current.sound_cooldown == 0 {
            state.sound = Some(1.15 + (hovered.value as f32 / board.max() as f32) * (1.5 - 1.15));
            current.sound_cooldown = 1;
        }
        current.hovered = Some(hovered);
    });
    let coordinate = l.coordinate(hovered);
    let cursor = board.formatted(hovered);
    let cursor_width = if icon_mode {
        19
    } else {
        (font.width_text(&cursor) as i32 / 2) * 2 + 3
    };
    let x = coordinate[0] as i32 - cursor_width / 2;
    let y = coordinate[1] as i32 - 7;
    if let Board::Motion(options) = board {
        crop(game, batch, [0, 44], [x - 2, y - 3], [22, 20], CURSOR);
        if !mode_icon(game, batch, options.icon(hovered.value), [x + 1, y - 1]) {
            text(
                game,
                batch,
                &Text::literal((hovered.value + 1).to_string()),
                [x + 6, y + 3],
                0x442000,
            );
        }
        if fade_width > fattest {
            text(
                game,
                batch,
                &cursor,
                [
                    l.x - 11 - fat_offset + (bg_width - font.width_text(&cursor) as i32) / 2,
                    l.y + l.height + extra_height - 40,
                ],
                0xfbdc7d,
            );
        }
    } else {
        crop(game, batch, [0, 9], [x - 3, y], [3, 14], CURSOR);
        crop(game, batch, [4, 9], [x, y], [cursor_width, 14], CURSOR);
        crop(game, batch, [61, 9], [x + cursor_width, y], [3, 14], CURSOR);
        text(game, batch, &cursor, [x + 2, y + 3], 0x442000);
    }
    if std::env::var_os("CREATE_HORIZON_TRACE").is_some() {
        thread_local! {static LAST:RefCell<String>=const{RefCell::new(String::new())};}
        let trace=serde_json::json!({"pos":panel.target.pos,"value":hovered.value,"row":hovered.row,"origin":[l.x,l.y],"size":[l.width,l.height],"coordinate":coordinate,"cursor":cursor.plain(),"title":title.plain(),"tip":tip.plain(),"title_width":game.gui.atlas.font.width_text(&title),"tip_width":game.gui.atlas.font.width_text(&tip)}).to_string();
        LAST.with_borrow_mut(|last| {
            if *last != trace {
                let name = match board {
                    Board::Motor => "motor",
                    Board::Filter { .. } => "filter",
                    Board::Motion(options) if options.linear() => "actuator",
                    Board::Motion(_) => "bearing",
                    _ => "chassis",
                };
                log::info!("Create {name} board: {trace}");
                *last = trace;
            }
        });
    }
}

pub(super) fn mouse_press(
    game: &Game<'_>,
    _screen: &NativeScreenView<'_>,
    _button: i32,
    canceled: &mut bool,
) {
    if game.native_mod_screen() == Some("create")
        && STATE.with_borrow(|state| state.panel.is_some())
    {
        *canceled = true;
    }
}
pub(super) fn mouse_release(
    game: &Game<'_>,
    screen: &NativeScreenView<'_>,
    button: i32,
    canceled: &mut bool,
) {
    let name = match button {
        0 => "key.mouse.left".to_owned(),
        1 => "key.mouse.right".to_owned(),
        2 => "key.mouse.middle".to_owned(),
        3..=31 => format!("key.mouse.{}", button + 1),
        _ => return,
    };
    if game.settings.keys.get("key.use") == name && submit(game, screen) {
        *canceled = true;
    }
}
pub(super) fn key_release(
    game: &Game<'_>,
    screen: &NativeScreenView<'_>,
    key: &str,
    canceled: &mut bool,
) {
    if game.settings.keys.get("key.use") == key && submit(game, screen) {
        *canceled = true;
    }
}
fn submit(game: &Game<'_>, screen: &NativeScreenView<'_>) -> bool {
    if game.native_mod_screen() != Some("create") {
        return false;
    }
    STATE.with_borrow_mut(|state| {
        let Some(panel) = state.panel else {
            return false;
        };
        state.submission = Some((
            panel.target,
            layout(game, [screen.rect[2], screen.rect[3]], panel.target.board)
                .closest(screen.mouse, game.has_shift_down()),
            game.has_control_down(),
        ));
        state.close = true;
        true
    })
}
pub(super) fn scroll(
    game: &Game<'_>,
    screen: &NativeScreenView<'_>,
    scroll: [f64; 2],
    modifiers: u32,
    canceled: &mut bool,
) {
    if game.native_mod_screen() != Some("create") || !scroll[1].is_finite() {
        return;
    }
    let Some(board) = STATE.with_borrow(|state| state.panel.map(|panel| panel.target.board)) else {
        return;
    };
    let l = layout(game, [screen.rect[2], screen.rect[3]], board);
    let shift = modifiers & 1 != 0;
    let old = l.closest(screen.mouse, shift);
    let value = (old.value
        + (scroll[1].signum() as i32) * if shift { board.milestone() } else { 1 })
    .clamp(0, board.max());
    if value != old.value {
        STATE.with_borrow_mut(|state| {
            state.cursor = Some(l.coordinate(Setting {
                row: old.row,
                value,
            }))
        });
        *canceled = true;
    }
}

pub(super) fn frame(game: &mut Game<'_>) {
    if !game.native_window() {
        return;
    }
    let (cursor, sound, submission, close) = STATE.with_borrow_mut(|state| {
        (
            state.cursor.take(),
            state.sound.take(),
            state.submission.take(),
            std::mem::take(&mut state.close),
        )
    });
    if let Some(at) = cursor {
        game.cursor = (at[0], at[1]);
        if game.focused
            && !game.options.offscreen
            && let (Some(window), Some(size)) = (&game.window, game.native_physical_window_size())
        {
            let scale = HudBatch::new(size).scale;
            let _ = window.set_cursor_position(winit::dpi::PhysicalPosition::new(
                game.view_at[0] as f64 + f64::from(at[0] * scale),
                game.view_at[1] as f64 + f64::from(at[1] * scale),
            ));
        }
    }
    if let Some(pitch) = sound {
        game.audio.play("create:scroll_value", None, 0.25, pitch);
    }
    if let Some((target, setting, bulk)) = submission {
        let mut bytes = Vec::with_capacity(20);
        let (channel, fields) = match target.board {
            Board::Motor => ("create:motor_settings_v2", [setting.row, setting.value]),
            Board::Motion(options) => ("create:motion_settings", [options.wire(), setting.value]),
            Board::Filter { .. } => ("create:filter_settings", [setting.row, setting.value]),
            _ => ("create:chassis_settings", [i32::from(bulk), setting.value]),
        };
        for value in target.pos.into_iter().chain(fields) {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        if let Err(error) = game.native_net_send_to_server(channel, &bytes) {
            log::debug!("Create value setting: {error}");
        }
    }
    if close {
        game.native_mod_screen_close("create");
    }
    if game.native_mod_screen() != Some("create") {
        STATE.with_borrow_mut(|state| state.panel = None);
    }
}

pub(super) fn hud(game: &Game<'_>, batch: &mut HudBatch) {
    if game.ui.hide_gui || !can_interact(game) {
        return;
    }
    let (ticks, tip, filter_board) = STATE.with_borrow(|state| {
        (
            state.hover_ticks,
            state.last_hover_tip,
            state
                .panel
                .is_some_and(|panel| matches!(panel.target.board, Board::Filter { .. })),
        )
    });
    let Some(tip) = tip else { return };
    if ticks == 0
        || (game.native_mod_screen().is_some()
            && !(filter_board && matches!(tip, HoverTip::Filter { .. })))
    {
        return;
    }
    let alpha = if ticks > 5 {
        (11 - ticks) as f32 / 5.0
    } else {
        (ticks as f32 / 5.0).min(1.)
    };
    let x = batch.width as i32 / 2;
    let (title, hint, amount) = tip.lines();
    if matches!(tip, HoverTip::Filter { .. })
        && game.ticks.is_multiple_of(4)
        && std::env::var_os("CREATE_HORIZON_TRACE").is_some()
    {
        let lines: Vec<_> = [&title, &hint]
            .into_iter()
            .chain(amount.as_ref())
            .map(|line| line.resolved().plain())
            .collect();
        log::info!("Create filter hover: {}", serde_json::json!(lines));
    }
    let mut y = batch.height as i32 - 75 - 12 * (2 + i32::from(amount.is_some()));
    for (i, line) in [title, hint].into_iter().chain(amount).enumerate() {
        let [r, g, b] = if i == 0 {
            [0xfb, 0xdc, 0x7d]
        } else {
            [255, 255, 255]
        };
        batch.text_styled(
            &game.gui.atlas,
            &line,
            (x - game.gui.atlas.font.width_text(&line) as i32 / 2) as f32,
            y as f32,
            rgba(r, g, b, (255.0 * alpha) as u8),
            true,
        );
        y += 12;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn bearing_options_use_the_source_icon_milestones() {
        let layout = Layout {
            x: 10,
            y: 20,
            label: -18,
            bar: 31,
            width: 37,
            height: 11,
            board: Board::Motion(MotionOptions::Mechanical),
        };
        for (value, x) in [(0, 15.5), (1, 25.5), (2, 35.5)] {
            let setting = Setting { row: 0, value };
            assert_eq!(layout.coordinate(setting), [x, 25.0]);
            assert_eq!(layout.closest([x, 25.0], false), setting);
        }
        assert_eq!(MotionOptions::Mechanical.icon(2), [8.0, 1.0]);
        assert_eq!(MotionOptions::Windmill.icon(1), [4.0, 5.0]);
        assert_eq!(MotionOptions::Clockwork.icon(2), [7.0, 5.0]);
        assert_eq!(MotionOptions::Piston.icon(0), [9.0, 1.0]);
        assert_eq!(MotionOptions::Pulley.icon(2), [11.0, 1.0]);
    }

    #[test]
    fn original_chassis_coordinates_match_the_live_reference() {
        let layout = Layout {
            x: 773,
            y: 517,
            label: 42,
            bar: 97,
            width: 163,
            height: 11,
            board: Board::LinearChassis,
        };
        assert_eq!(
            layout.coordinate(Setting { row: 0, value: 0 }),
            [836.5, 522.0]
        );
        assert_eq!(
            layout.coordinate(Setting { row: 0, value: 7 }),
            [878.5, 522.0]
        );
        assert_eq!(
            layout.closest([10000., -1000.], true),
            Setting { row: 0, value: 15 }
        );
    }

    #[test]
    fn original_motor_coordinates_match_live_reference_at_gui_640_by_360() {
        let layout = Layout {
            x: 157,
            y: 169,
            label: 8,
            bar: 294,
            width: 326,
            height: 22,
            board: Board::Motor,
        };
        assert_eq!(
            layout.coordinate(Setting { row: 0, value: 0 }),
            [186.5, 174.0]
        );
        assert_eq!(
            layout.coordinate(Setting { row: 1, value: 128 }),
            [330.5, 185.0]
        );
        assert_eq!(
            layout.coordinate(Setting { row: 0, value: 256 }),
            [474.5, 174.0]
        );
        assert_eq!(
            layout.closest([258.5, 174.], false),
            Setting { row: 0, value: 64 }
        );
        assert_eq!(
            layout.closest([-1000., 1000.], false),
            Setting { row: 1, value: 0 }
        );
        assert_eq!(
            layout.closest([10000., -1000.], true),
            Setting { row: 0, value: 256 }
        );
    }
}
