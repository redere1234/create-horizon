// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT
// Create 6.0.10 ScrollValueRenderer, ValueBox.TextValueBox,
// ValueBoxTransform.Sided, CreativeMotorBlockEntity.MotorValueBox, AllIcons;
// bundled MIT Catnip Outliner/OutlineEntry. No original asset bytes.
use super::create_port_motor_control::MotionOptions;
use super::create_port_motor_value_ui::ICONS;
use super::{Game, create_port_chassis as chassis, native_world_draw::NativeWorldDraw};
use crate::containers::BlockEntity;
use horizon_world::nbt::Tag;
use std::{cell::RefCell, collections::HashMap};

const FULL_BRIGHT: u32 = 240 | (240 << 8);
const TILE_QUAD: [[f32; 3]; 4] = [
    [0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0],
    [1.0, 1.0, 0.0],
    [1.0, 0.0, 0.0],
];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) struct Side([i32; 3]);
impl Side {
    fn named(name: &str) -> Option<Self> {
        Some(Self(match name {
            "down" => [0, -1, 0],
            "up" => [0, 1, 0],
            "north" => [0, 0, -1],
            "south" => [0, 0, 1],
            "west" => [-1, 0, 0],
            "east" => [1, 0, 0],
            _ => return None,
        }))
    }
    fn axis(self) -> usize {
        self.0.iter().position(|v| *v != 0).unwrap_or(1)
    }
    // Catnip AngleHelper negates Direction.toYRot on the X axis.
    fn horizontal_angle(self) -> f32 {
        match self.0 {
            [0, 0, -1] => 180.0,
            [-1, 0, 0] => -90.0,
            [1, 0, 0] => -270.0,
            _ => 0.0,
        }
    }
}

/// DirectionalExtenderScrollOptionSlot, or the pulley's centered top slot.
#[derive(Clone, Copy, Debug)]
struct MotionSlot {
    facing: Option<Side>,
    side: Side,
}
impl MotionSlot {
    fn at(game: &Game<'_>, hit: &super::Hit, options: MotionOptions) -> Option<Self> {
        let side = Side(hit.face);
        if options == MotionOptions::Pulley {
            return (side.0 == [0, 1, 0]).then_some(Self { facing: None, side });
        }
        let facing = Side::named(&game.native_block_property(hit.pos, "facing")?)?;
        let shaft = if options == MotionOptions::Piston {
            use create_engine::kinetics::Axis;
            Some(match super::create_port::node(game, hit.pos)?.axis {
                Axis::X => 0,
                Axis::Y => 1,
                Axis::Z => 2,
            })
        } else {
            None
        };
        (side.axis() != facing.axis() && shaft != Some(side.axis())).then_some(Self {
            facing: Some(facing),
            side,
        })
    }

    fn offset(self) -> [f32; 3] {
        std::array::from_fn(|i| {
            0.5 + self.side.0[i] as f32 * (7.5 / 16.0)
                - self.facing.map_or(0.0, |facing| facing.0[i] as f32 / 8.0)
        })
    }

    fn rotation(self) -> [f32; 3] {
        let pitch = match self.side.0 {
            [0, 1, 0] => 90.0,
            [0, -1, 0] => 270.0,
            _ => 0.0,
        };
        let y = self
            .facing
            .filter(|_| self.side.axis() == 1)
            .map_or(0.0, |facing| facing.horizontal_angle() + 180.0);
        [y + self.side.horizontal_angle() + 180.0, pitch, 0.0]
    }
}

pub(super) fn motion_hit(game: &Game<'_>, hit: &super::Hit, options: MotionOptions) -> bool {
    matches!(
        game.world.block_entities.get(&hit.pos.into()),
        Some(BlockEntity::Mod(_))
    ) && !entity_blocks_target(game)
        && MotionSlot::at(game, hit, options)
            .is_some_and(|slot| hit_offset(hit.pos, hit.point, slot.offset()))
}

fn hit_offset(pos: [i32; 3], point: [f64; 3], offset: [f32; 3]) -> bool {
    (0..3)
        .map(|i| (point[i] - f64::from(pos[i]) - f64::from(offset[i])).powi(2))
        .sum::<f64>()
        < 0.25 * 0.25
}

#[derive(Clone, Debug)]
pub(super) struct Plan {
    pub pos: [i32; 3],
    motor_facing: Option<Side>,
    motion: Option<MotionBox>,
    filter: Option<FilterBox>,
    side: Side,
    pub text: String,
    pub active: bool,
    ticks_until_removal: i32,
}

#[derive(Clone, Debug)]
struct MotionBox {
    slot: MotionSlot,
    icon: Option<[f32; 2]>,
}

#[derive(Clone, Debug)]
struct FilterBox {
    center: [f32; 3],
    rotation: Option<[f32; 3]>,
    label: FilterLabel,
    filled: bool,
    solid_item: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum FilterLabel {
    Item,
    Recipe,
}

/// A filtering behavior's read-only presentation at the current block hit.
pub(super) struct FilterDisplay {
    pub center: [f32; 3],
    pub rotation: Option<[f32; 3]>,
    pub label: FilterLabel,
    pub hit: bool,
    pub filled: bool,
    pub solid_item: bool,
    pub count: String,
}

impl FilterDisplay {
    pub(super) fn sample(
        center: [f32; 3],
        rotation: [f32; 3],
        label: FilterLabel,
        hit: bool,
        filled: bool,
    ) -> Self {
        Self {
            center,
            rotation: Some(rotation),
            label,
            hit,
            filled,
            solid_item: false,
            count: String::new(),
        }
    }
}

impl Plan {
    fn side_active(&self) -> bool {
        self.motor_facing.is_none_or(|facing| {
            self.side.axis() != facing.axis() && !(facing.axis() != 1 && self.side.0 == [0, -1, 0])
        })
    }
    pub fn offset(&self) -> [f32; 3] {
        if let Some(motion) = &self.motion {
            return motion.slot.offset();
        }
        if let Some(filter) = &self.filter {
            return filter.center;
        }
        std::array::from_fn(|i| match self.motor_facing {
            Some(facing) => 0.5 + self.side.0[i] as f32 * (4.5 / 16.0) - facing.0[i] as f32 / 16.0,
            None => 0.5 + self.side.0[i] as f32 * (7.5 / 16.0),
        })
    }
    pub fn rotation(&self) -> [f32; 3] {
        if let Some(motion) = &self.motion {
            return motion.slot.rotation();
        }
        if let Some(rotation) = self.filter.as_ref().and_then(|filter| filter.rotation) {
            return rotation;
        }
        [
            self.side.horizontal_angle() + 180.0,
            match self.side.0 {
                [0, 1, 0] => 90.0,
                [0, -1, 0] => 270.0,
                _ => 0.0,
            },
            self.motor_facing
                .filter(|facing| facing.axis() != 1 && self.side.0 == [0, 1, 0])
                .map_or(0.0, |facing| -facing.horizontal_angle() + 180.0),
        ]
    }
    fn hit(&self, point: [f64; 3]) -> bool {
        self.side_active() && hit_offset(self.pos, point, self.offset())
    }
    fn visible(&self, partial: f32) -> bool {
        if !self.side_active() || self.ticks_until_removal < -8 {
            return false;
        }
        if self.ticks_until_removal >= 0 {
            return true;
        }
        // Outliner checks cubic alpha before calling ValueBox.render. The
        // latter deliberately ignores alpha, so it stays opaque until cut off.
        let previous = (1.0 + (self.ticks_until_removal + 1) as f32 / 8.0).min(1.0);
        let current = 1.0 + self.ticks_until_removal as f32 / 8.0;
        let alpha = previous + partial * (current - previous);
        alpha * alpha * alpha >= 0.125
    }

    /// Draw under a pose already translated to `pos - camera`.
    ///
    /// The backend uses the normal depth-tested text layer. `quad` is
    /// unshaded with ARGB tint; `text` uses the actual font and its eight-offset
    /// outline; its front glyphs use the original polygon-offset text pass.
    pub fn render(&self, draw: &mut NativeWorldDraw, width: i32, canvas: &mut impl Canvas) {
        let icon = self.motion.as_ref().and_then(|motion| motion.icon);
        if (icon.is_none() && width <= 0 && (self.filter.is_none() || !self.active))
            || !self.visible(draw.partial)
        {
            return;
        }
        let light = draw.light;
        draw.light = FULL_BRIGHT;
        draw.push();
        draw.translate(self.offset());
        let [yaw, pitch, roll] = self.rotation();
        draw.rotate_about([0.0, 1.0, 0.0], yaw, [0.0; 3]);
        draw.rotate_about([1.0, 0.0, 0.0], pitch, [0.0; 3]);
        draw.rotate_about([0.0, 0.0, 1.0], roll, [0.0; 3]);
        draw.scale([0.5; 3]);
        if self.active {
            draw.push();
            draw.scale([-2.01, -2.01, 2.01]);
            draw.translate([-0.5, -0.5, -0.5 / 16.0]);
            let icon = if self.filter.as_ref().is_some_and(|filter| !filter.filled) {
                3.0
            } else {
                2.0
            };
            canvas.quad(
                draw,
                ICONS,
                TILE_QUAD,
                // The 4px and 6px outline icons share row 8 of the source sheet.
                [icon, 8.0, icon + 1.0, 9.0],
                0xffff_ffff,
            );
            draw.pop();
        }
        if let Some([u, v]) = icon {
            draw.scale([-0.5; 3]);
            draw.translate([-0.5, -0.5, 5.0 / 32.0]);
            canvas.quad(
                draw,
                ICONS,
                TILE_QUAD,
                [u, v, u + 1.0, v + 1.0],
                0xffff_ffff,
            );
        } else if width > 0 {
            draw.scale([-1.0 / 64.0; 3]);
            if let Some(filter) = &self.filter {
                draw.translate([17.5 - width as f32, -5.0, 7.0]);
                let scale = if filter.filled {
                    draw.translate([-7.0, 10.0, if filter.solid_item { 10.25 } else { 0.0 }]);
                    1.5
                } else {
                    draw.translate([-15.0, -1.0, -2.75]);
                    1.65
                };
                if self.text == "*" {
                    draw.translate([-1.0, 3.0, 0.0]);
                }
                draw.scale([scale; 3]);
            } else {
                draw.scale([3.0, 3.0, 1.0]);
                draw.translate([-4.0, -3.75, 5.0]);
                let single = width < 10;
                let scale = 9.0 / width as f32 / if single { 2.0 } else { 1.0 };
                let margin = (width - 9) as f32 / 2.0;
                draw.scale([scale; 3]);
                draw.translate([
                    if single { (width / 2) as f32 } else { 0.0 },
                    if single { -margin } else { margin },
                    0.0,
                ]);
            }
            canvas.text(draw, &self.text, 0xffed_eded, 0xff33_3333);
        }
        draw.pop();
        draw.light = light;
    }
}

/// Native world canvas boundary; all geometry goes through Horizon's ordinary
/// font/atlas renderer, with no mod-owned GPU objects.
pub(super) trait Canvas {
    fn quad(
        &mut self,
        draw: &mut NativeWorldDraw,
        sprite: &str,
        corners: [[f32; 3]; 4],
        uv: [f32; 4],
        argb: u32,
    );
    fn text(&mut self, draw: &mut NativeWorldDraw, text: &str, color: u32, outline: u32);
}
struct NativeCanvas<'a, 'g>(&'a Game<'g>);
impl Canvas for NativeCanvas<'_, '_> {
    fn quad(
        &mut self,
        draw: &mut NativeWorldDraw,
        sprite: &str,
        corners: [[f32; 3]; 4],
        uv: [f32; 4],
        argb: u32,
    ) {
        self.0.native_world_quad(
            draw,
            sprite,
            corners,
            uv,
            [
                (argb >> 16) as u8,
                (argb >> 8) as u8,
                argb as u8,
                (argb >> 24) as u8,
            ],
        );
    }
    fn text(&mut self, draw: &mut NativeWorldDraw, text: &str, color: u32, outline: u32) {
        self.0.native_world_text(
            draw,
            &horizon_client::text::Text::literal(text),
            color,
            Some(outline),
        );
    }
}
pub(super) fn render(game: &Game<'_>, draw: &mut NativeWorldDraw) {
    let mut canvas = NativeCanvas(game);
    for plan in plans(game) {
        draw.push();
        if draw.translate_world(plan.pos.map(f64::from)) {
            let width = game.gui.atlas.font.width(&plan.text).ceil() as i32;
            plan.render(draw, width, &mut canvas);
        }
        draw.pop();
    }
}

#[derive(Default)]
struct State {
    identity: (usize, usize, &'static str),
    boxes: HashMap<[i32; 3], Plan>,
}
thread_local! {static STATE: RefCell<State> = RefCell::new(State::default());}
fn identity(game: &Game<'_>) -> (usize, usize, &'static str) {
    (
        std::ptr::from_ref(game) as usize,
        std::ptr::from_ref(&game.world) as usize,
        game.native_dimension(),
    )
}

fn entity_blocks_target(game: &Game<'_>) -> bool {
    [
        game.mob_hit().map(|hit| hit.1),
        game.boat_hit().map(|hit| hit.1),
        game.cart_hit().map(|hit| hit.1),
        game.armor_stand_hit().map(|hit| hit.1),
        game.cushion_hit().map(|hit| hit.1),
        game.frame_hit().map(|hit| hit.1),
        game.painting_hit().map(|hit| hit.1),
        game.dragon_hit().map(|hit| hit.1),
    ]
    .into_iter()
    .flatten()
    .any(|distance| game.before_block(distance))
}

fn target(game: &Game<'_>) -> Option<Plan> {
    let hit = game.pick()?;
    let block = game.native_block(hit.pos);
    let motor = block == "create:creative_motor";
    let motion = MotionOptions::for_block(&block);
    let wrench_target =
        chassis::is_chassis(&block) && game.held().is_some_and(|item| chassis::wrench(game, item));
    let filter = if !motor && motion.is_none() && !wrench_target {
        if game.native_sneaking() {
            return None;
        }
        Some(match block.as_str() {
            super::create_port_deployer::BLOCK => {
                super::create_port_deployer::filter_display(game, &hit)
            }
            super::create_port_drill::SAW => {
                super::create_port_saw_filter::filter_display(game, &hit)
            }
            super::create_port_basin::ID => super::create_port_basin_filter::display(game, &hit),
            _ => super::create_port_chute::filter_display(game, &hit, &block),
        }?)
    } else {
        None
    };
    if entity_blocks_target(game) {
        return None;
    }
    if let Some(filter) = filter {
        return Some(Plan {
            pos: hit.pos,
            motor_facing: None,
            motion: None,
            filter: Some(FilterBox {
                center: filter.center,
                rotation: filter.rotation,
                label: filter.label,
                filled: filter.filled,
                solid_item: filter.solid_item,
            }),
            side: Side(hit.face),
            text: filter.count,
            active: filter.hit,
            ticks_until_removal: 1,
        });
    }
    let BlockEntity::Mod(entity) = game
        .world
        .block_entities
        .get(&(hit.pos[0], hit.pos[1], hit.pos[2]))?
    else {
        return None;
    };
    if let Some(options) = motion {
        let slot = MotionSlot::at(game, &hit, options)?;
        let value = options.selection(entity);
        let icon = game
            .gui
            .atlas
            .sprites
            .contains_key(ICONS)
            .then(|| options.icon(value));
        return Some(Plan {
            pos: hit.pos,
            motor_facing: None,
            motion: Some(MotionBox { slot, icon }),
            filter: None,
            side: Side(hit.face),
            text: icon
                .is_none()
                .then(|| (value + 1).to_string())
                .unwrap_or_default(),
            active: hit_offset(hit.pos, hit.point, slot.offset()),
            ticks_until_removal: 1,
        });
    }
    let (value, motor_facing) = if motor {
        let value = match entity.nbt.get(&"ScrollValue".into()) {
            Some(Tag::Int(value)) => *value,
            _ => 16,
        };
        let facing = Side::named(&game.native_block_property(hit.pos, "facing")?)?;
        (value.wrapping_abs(), Some(facing))
    } else {
        let saved = chassis::configured_range(game, hit.pos)?;
        let value = super::create_port_motor_value_ui::chassis_preview_value(hit.pos)
            .unwrap_or(i32::from(saved));
        (value, None)
    };
    let mut plan = Plan {
        pos: hit.pos,
        motor_facing,
        motion: None,
        filter: None,
        side: Side(hit.face),
        text: value.to_string(),
        active: false,
        ticks_until_removal: 1,
    };
    // MotorValueBox does not override bypassesInput, even for a clipboard.
    plan.active = plan.hit(hit.point);
    Some(plan)
}

/// Once per unpaused real client tick: Ponder ticks old outlines in Pre, then
/// Create's ScrollValueRenderer replaces the current entry in Post.
pub(super) fn tick(game: &Game<'_>) {
    if !game.native_window() || !game.native_on("create") || game.player.is_none() {
        reset();
        return;
    }
    let current = target(game);
    STATE.with_borrow_mut(|state| {
        let world = identity(game);
        if state.identity != world {
            state.identity = world;
            state.boxes.clear();
        }
        state.boxes.retain(|_, plan| {
            plan.ticks_until_removal -= 1;
            plan.ticks_until_removal >= -8
        });
        if let Some(plan) = current {
            state.boxes.insert(plan.pos, plan);
        }
    });
}

pub(super) fn reset() {
    STATE.with_borrow_mut(|state| *state = State::default());
}

/// Source goggles suppression checks alive active entries, including entries
/// whose world rendering has already reached the fade cutoff.
pub(super) fn active(game: &Game<'_>) -> bool {
    STATE.with_borrow(|state| {
        state.identity == identity(game) && state.boxes.values().any(|plan| plan.active)
    })
}

pub(super) fn filter_hover(game: &Game<'_>) -> Option<(FilterLabel, bool, bool)> {
    STATE.with_borrow(|state| {
        if state.identity != identity(game) {
            return None;
        }
        let plan = state
            .boxes
            .values()
            .find(|plan| plan.active && plan.ticks_until_removal == 1 && plan.filter.is_some())?;
        let filter = plan.filter.as_ref()?;
        Some((filter.label, filter.filled, !plan.text.is_empty()))
    })
}

/// A world pass must also draw cached entries after a motor is removed; a block
/// entity submit callback alone does not cover that source Outliner behavior.
pub(super) fn plans(game: &Game<'_>) -> Vec<Plan> {
    STATE.with_borrow(|state| {
        if state.identity == identity(game) {
            state.boxes.values().cloned().collect()
        } else {
            Vec::new()
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    fn plan(facing: &str, side: &str) -> Plan {
        Plan {
            pos: [0; 3],
            motor_facing: Side::named(facing),
            motion: None,
            filter: None,
            side: Side::named(side).unwrap(),
            text: "128".into(),
            active: true,
            ticks_until_removal: 1,
        }
    }
    #[test]
    fn source_motor_sides_and_top_orientation() {
        for facing in ["down", "up", "north", "south", "west", "east"] {
            let allowed = ["down", "up", "north", "south", "west", "east"]
                .into_iter()
                .filter(|side| plan(facing, side).side_active())
                .count();
            assert_eq!(
                allowed,
                if facing == "up" || facing == "down" {
                    4
                } else {
                    3
                }
            );
        }
        let top = plan("east", "up");
        assert_eq!(top.offset(), [0.4375, 0.78125, 0.5]);
        assert_eq!(top.rotation(), [180.0, 90.0, 450.0]);
        assert!(top.hit([0.4375, 1.0, 0.5]));
        assert!(!top.hit([0.6875, 0.78125, 0.5]));
    }
    #[test]
    fn bearing_option_slots_face_the_source_direction() {
        let vertical = MotionSlot {
            facing: Side::named("up"),
            side: Side::named("south").unwrap(),
        };
        assert_eq!(vertical.offset(), [0.5, 0.375, 0.96875]);
        assert_eq!(vertical.rotation(), [180.0, 0.0, 0.0]);
        assert!(hit_offset([0; 3], [0.5, 0.375, 1.0], vertical.offset()));
        assert!(!hit_offset([0; 3], [0.5, 0.75, 1.0], vertical.offset()));
        let horizontal = MotionSlot {
            facing: Side::named("east"),
            side: Side::named("up").unwrap(),
        };
        assert_eq!(horizontal.offset(), [0.375, 0.96875, 0.5]);
        assert_eq!(horizontal.rotation(), [90.0, 90.0, 0.0]);
        let pulley = MotionSlot {
            facing: None,
            side: Side::named("up").unwrap(),
        };
        assert_eq!(pulley.offset(), [0.5, 0.96875, 0.5]);
        assert_eq!(pulley.rotation(), [180.0, 90.0, 0.0]);
    }
    #[test]
    fn value_box_opaque_until_outliner_cubic_cutoff() {
        let mut box_ = plan("east", "south");
        box_.ticks_until_removal = -4;
        assert!(box_.visible(1.0));
        box_.ticks_until_removal = -5;
        assert!(box_.visible(0.0));
        assert!(!box_.visible(0.001));
        // Entry remains alive for goggles suppression after becoming invisible.
        assert!(box_.active);
    }
}
