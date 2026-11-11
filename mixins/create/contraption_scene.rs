// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use glam::{DQuat, DVec3};
use horizon_core::geometry::{Aabb, Vec3};
use horizon_world::{
    attachments::{AttachmentCodec, AttachmentError, AttachmentSync, AttachmentType, Attachments},
    block_collision::BlockCollisionRegistry,
    chunk::BlockState,
    nbt::{Compound, Tag},
};
use std::{
    borrow::Cow,
    collections::BTreeMap,
    sync::{
        Arc,
        atomic::{AtomicI64, Ordering},
    },
};

pub type Pos = [i32; 3];
pub const MAX_BLOCKS: usize = 64;
pub const MAX_PLAIN_ROTARY_BLOCKS: usize = 2048;
pub const MAX_RECORDS: usize = 4;
pub const KEY: &str = "moving_structures";
pub const POSE_KEY: &str = "moving_structure_poses";
pub const ACTOR_VISUAL_KEY: &str = "actor_visuals";

#[derive(Clone, Debug)]
pub struct Record {
    pub controller: Pos,
    pub anchor: Pos,
    pub axis: usize,
    pub angle: f32,
    pub previous_angle: f32,
    pub rpm: f32,
    pub stalled: bool,
    pub return_home: bool,
    pub stroke: Option<Stroke>,
    pub clock_hand: Option<ClockHand>,
    pub blocks: Arc<[(Pos, BlockState)]>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum ClockHand {
    Hour,
    Minute,
}

#[derive(Clone, Copy, Debug)]
pub struct Stroke {
    pub kind: StrokeKind,
    pub initial: u32,
    pub limit: u32,
    pub offset: f32,
    pub previous: f32,
    pub waiting: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StrokeKind {
    Piston,
    RopePulley,
    Gantry,
}

impl Record {
    pub fn same_geometry(&self, other: &Self) -> bool {
        let stroke_layout = |stroke: Stroke| (stroke.kind, stroke.initial, stroke.limit);
        self.controller == other.controller
            && self.clock_hand == other.clock_hand
            && self.anchor == other.anchor
            && self.axis == other.axis
            && self.return_home == other.return_home
            && self.stroke.map(stroke_layout) == other.stroke.map(stroke_layout)
            && (Arc::ptr_eq(&self.blocks, &other.blocks) || self.blocks == other.blocks)
    }

    pub fn stroke_kind(&self) -> Option<StrokeKind> {
        self.stroke.map(|stroke| stroke.kind)
    }

    pub fn origin_at(&self, partial: f32) -> [f64; 3] {
        self.origin_for_offset(self.stroke.map_or(0.0, |stroke| {
            stroke.previous + (stroke.offset - stroke.previous) * partial
        }))
    }

    pub fn origin_for_offset(&self, offset: f32) -> [f64; 3] {
        let Some(stroke) = self.stroke else {
            return self.anchor.map(f64::from);
        };
        let mut origin = self.anchor.map(f64::from);
        let sign = match stroke.kind {
            StrokeKind::Gantry => 1,
            _ => self.anchor[self.axis] - self.controller[self.axis],
        };
        origin[self.axis] += f64::from(sign) * f64::from(offset);
        origin
    }

    pub fn orientation(&self, angle: f32) -> DQuat {
        let axis = [DVec3::X, DVec3::Y, DVec3::Z][self.axis];
        DQuat::from_axis_angle(axis, f64::from(angle).to_radians())
    }

    pub fn angle_at(&self, partial: f32) -> f32 {
        let delta = (self.angle - self.previous_angle + 180.0).rem_euclid(360.0) - 180.0;
        self.previous_angle + partial * delta
    }
}

#[derive(Clone, Debug, Default)]
pub struct SceneGeometry {
    // `None` is a legacy record that still contains its last saved pose.
    generation: Option<i64>,
    records: Vec<Record>,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct ScenePoses {
    generation: i64,
    entries: Vec<Pose>,
}

#[derive(Clone, Copy, Debug, PartialEq)]
struct Pose {
    controller: Pos,
    clock_hand: Option<ClockHand>,
    angle: f32,
    previous_angle: f32,
    rpm: f32,
    stalled: bool,
    stroke: Option<StrokePose>,
}

#[derive(Clone, Copy, Debug, PartialEq)]
struct StrokePose {
    offset: f32,
    previous: f32,
    waiting: bool,
}

impl From<&Record> for Pose {
    fn from(record: &Record) -> Self {
        Self {
            controller: record.controller,
            clock_hand: record.clock_hand,
            angle: record.angle,
            previous_angle: record.previous_angle,
            rpm: record.rpm,
            stalled: record.stalled,
            stroke: record.stroke.map(|stroke| StrokePose {
                offset: stroke.offset,
                previous: stroke.previous,
                waiting: stroke.waiting,
            }),
        }
    }
}

impl Pose {
    fn apply(self, record: &mut Record) -> Result<(), AttachmentError> {
        if (record.controller, record.clock_hand) != (self.controller, self.clock_hand)
            || ![self.angle, self.previous_angle, self.rpm]
                .into_iter()
                .all(f32::is_finite)
        {
            return Err(AttachmentError::Decode);
        }
        match (&mut record.stroke, self.stroke) {
            (Some(stroke), Some(motion))
                if (0.0..=stroke.limit as f32).contains(&motion.offset)
                    && (0.0..=stroke.limit as f32).contains(&motion.previous) =>
            {
                if matches!(stroke.kind, StrokeKind::RopePulley | StrokeKind::Gantry)
                    && (self.angle != 0.0 || self.previous_angle != 0.0)
                {
                    return Err(AttachmentError::Decode);
                }
                stroke.offset = motion.offset;
                stroke.previous = motion.previous;
                stroke.waiting = motion.waiting;
            }
            (None, None) => {}
            _ => return Err(AttachmentError::Decode),
        }
        record.angle = self.angle;
        record.previous_angle = self.previous_angle;
        record.rpm = self.rpm;
        record.stalled = self.stalled;
        Ok(())
    }
}

pub const RECORDS: AttachmentType<SceneGeometry> = AttachmentType {
    namespace: "create",
    name: KEY,
    default: SceneGeometry::default,
    codec: Some(AttachmentCodec {
        encode: encode_geometry,
        decode: decode_geometry,
    }),
    copy_on_death: false,
    sync: true,
};

pub const POSES: AttachmentType<ScenePoses> = AttachmentType {
    namespace: "create",
    name: POSE_KEY,
    default: ScenePoses::default,
    codec: Some(AttachmentCodec {
        encode: encode_poses,
        decode: decode_poses,
    }),
    copy_on_death: false,
    sync: true,
};

pub const ACTIVE: AttachmentType<bool> = AttachmentType {
    namespace: "create",
    name: "has_moving_structures",
    default: || false,
    codec: None,
    copy_on_death: false,
    sync: false,
};

fn encode_geometry(scene: &SceneGeometry) -> Result<Compound, AttachmentError> {
    encode_records(&scene.records, scene.generation)
}

fn encode_records(
    records: &[Record],
    generation: Option<i64>,
) -> Result<Compound, AttachmentError> {
    if records.len() > MAX_RECORDS {
        return Err(AttachmentError::Encode);
    }
    let mut packed = false;
    let entries = records
        .iter()
        .map(|record| {
            let mut entry = Compound::from([
                (
                    "Controller".into(),
                    Tag::IntArray(record.controller.to_vec()),
                ),
                ("Anchor".into(), Tag::IntArray(record.anchor.to_vec())),
                ("Axis".into(), Tag::Int(record.axis as i32)),
                ("ReturnHome".into(), Tag::Byte(i8::from(record.return_home))),
            ]);
            if record.blocks.len() <= MAX_BLOCKS {
                let blocks = record
                    .blocks
                    .iter()
                    .map(|(local, state)| {
                        Tag::compound([
                            ("Pos", Tag::IntArray(local.to_vec())),
                            ("State", state.to_nbt()),
                        ])
                    })
                    .collect();
                entry.insert("Blocks".into(), Tag::List(blocks));
            } else {
                if generation.is_none()
                    || record.stroke.is_some()
                    || record.clock_hand.is_some()
                    || record.blocks.len() > MAX_PLAIN_ROTARY_BLOCKS
                    || record
                        .blocks
                        .iter()
                        .any(|(_, state)| !plain_rotary_state(state))
                {
                    return Err(AttachmentError::Encode);
                }
                packed = true;
                let mut indices = BTreeMap::new();
                let mut palette = Vec::new();
                let mut positions = Vec::with_capacity(record.blocks.len() * 4);
                for (local, state) in record.blocks.iter() {
                    let index = *indices.entry(state).or_insert_with(|| {
                        palette.push(state.to_nbt());
                        palette.len() as i32 - 1
                    });
                    positions.extend([local[0], local[1], local[2], index]);
                }
                entry.insert("Palette".into(), Tag::List(palette));
                entry.insert("Blocks".into(), Tag::IntArray(positions));
            }
            if generation.is_none() {
                encode_motion(&mut entry, Pose::from(record));
            }
            if let Some(stroke) = record.stroke {
                let motion = entry.remove(&"Stroke".into());
                let mut data = match motion {
                    Some(Tag::Compound(data)) => data,
                    _ => Compound::new(),
                };
                data.extend([
                    (
                        "Kind".into(),
                        Tag::Byte(match stroke.kind {
                            StrokeKind::Piston => 0,
                            StrokeKind::RopePulley => 1,
                            StrokeKind::Gantry => 2,
                        }),
                    ),
                    ("Initial".into(), Tag::Int(stroke.initial as i32)),
                    ("Limit".into(), Tag::Int(stroke.limit as i32)),
                ]);
                entry.insert("Stroke".into(), Tag::Compound(data));
            }
            if let Some(hand) = record.clock_hand {
                let value = match hand {
                    ClockHand::Hour => 0,
                    ClockHand::Minute => 1,
                };
                entry.insert("ClockHand".into(), Tag::Byte(value));
            }
            Ok(Tag::Compound(entry))
        })
        .collect::<Result<_, AttachmentError>>()?;
    let mut scene = Compound::from([
        (
            "Version".into(),
            Tag::Int(if generation.is_some() { 2 } else { 1 }),
        ),
        ("Entries".into(), Tag::List(entries)),
    ]);
    if let Some(generation) = generation {
        scene.insert("Generation".into(), Tag::Long(generation));
    }
    if packed {
        // Leave room in the column packet for poses and other mods' data.
        let limits = horizon_world::nbt::Limits {
            max_bytes: horizon_protocol::attachment_sync::MAX_PAYLOAD / 4,
            ..Default::default()
        };
        horizon_world::nbt::write_network(&Tag::Compound(scene.clone()), limits)
            .map_err(|_| AttachmentError::Encode)?;
    }
    Ok(scene)
}

fn decode_geometry(encoded: &Compound) -> Result<SceneGeometry, AttachmentError> {
    let invalid = AttachmentError::Decode;
    let generation = match encoded.get(&"Version".into()) {
        Some(Tag::Int(1)) => None,
        Some(Tag::Int(2)) => Some(read_generation(encoded)?),
        _ => return Err(invalid),
    };
    let Some(Tag::List(entries)) = encoded.get(&"Entries".into()) else {
        return Err(invalid);
    };
    if entries.len() > MAX_RECORDS {
        return Err(invalid);
    }
    let mut owners = std::collections::BTreeSet::new();
    let records = entries
        .iter()
        .map(|entry| {
            let controller = position(entry, "Controller")?;
            let anchor = position(entry, "Anchor")?;
            let Some(Tag::Int(axis @ 0..=2)) = entry.get("Axis") else {
                return Err(invalid);
            };
            let clock_hand = read_hand(entry)?;
            let axis = *axis as usize;
            let distance = anchor[axis].abs_diff(controller[axis]);
            if !owners.insert((controller, clock_hand))
                || (0..3).any(|i| i != axis && controller[i] != anchor[i])
            {
                return Err(invalid);
            }
            let stroke = if let Some(tag) = entry.get("Stroke") {
                let kind = match tag.get("Kind") {
                    None | Some(Tag::Byte(0)) => StrokeKind::Piston,
                    Some(Tag::Byte(1)) => StrokeKind::RopePulley,
                    Some(Tag::Byte(2)) => StrokeKind::Gantry,
                    _ => return Err(invalid),
                };
                let max = if kind == StrokeKind::RopePulley {
                    384
                } else {
                    64
                };
                let Some(Tag::Int(initial)) = tag.get("Initial") else {
                    return Err(invalid);
                };
                let Some(Tag::Int(limit)) = tag.get("Limit") else {
                    return Err(invalid);
                };
                let (offset, previous) = if generation.is_some() {
                    (0.0, 0.0)
                } else {
                    (float(tag, "Offset")?, float(tag, "Previous")?)
                };
                if !(1..=max).contains(limit)
                    || !(0..=*limit).contains(initial)
                    || !(0.0..=*limit as f32).contains(&offset)
                    || !(0.0..=*limit as f32).contains(&previous)
                {
                    return Err(invalid);
                }
                Some(Stroke {
                    kind,
                    initial: *initial as u32,
                    limit: *limit as u32,
                    offset,
                    previous,
                    waiting: generation.is_none()
                        && matches!(tag.get("Waiting"), Some(Tag::Byte(1))),
                })
            } else {
                None
            };
            let return_home = matches!(entry.get("ReturnHome"), Some(Tag::Byte(1)));
            let (angle, previous_angle, rpm) = if generation.is_some() {
                (0.0, 0.0, 0.0)
            } else {
                (
                    float(entry, "Angle")?,
                    float(entry, "PreviousAngle")?,
                    float(entry, "Speed")?,
                )
            };
            let pulley = stroke.is_some_and(|stroke| stroke.kind == StrokeKind::RopePulley);
            let gantry = stroke.filter(|stroke| stroke.kind == StrokeKind::Gantry);
            let right_distance = match (gantry, clock_hand) {
                (Some(gantry), _) => controller[axis] >= anchor[axis] && distance == gantry.initial,
                (_, Some(ClockHand::Minute)) => (2..=16).contains(&distance),
                _ => distance == 1,
            };
            if clock_hand.is_some() && (stroke.is_some() || !return_home) {
                return Err(invalid);
            }
            let packed = generation.is_some() && stroke.is_none() && clock_hand.is_none();
            let blocks = decode_blocks(entry, packed, if stroke.is_some() { 81 } else { 15 })?;
            if !right_distance
                || (blocks.is_empty() && !pulley)
                || (blocks.len() > MAX_BLOCKS
                    && !fits_rotary_column(controller, anchor, axis, &blocks))
                || (pulley
                    && (axis != 1
                        || anchor[1] >= controller[1]
                        || angle != 0.0
                        || previous_angle != 0.0
                        || return_home))
                || (gantry.is_some() && (angle != 0.0 || previous_angle != 0.0 || return_home))
            {
                return Err(invalid);
            }
            if gantry.is_some()
                && !blocks.iter().any(|(local, state)| {
                    *local == [0; 3]
                        && state.name == "create:gantry_carriage"
                        && state
                            .properties
                            .get("facing")
                            .is_some_and(|facing| match axis {
                                0 => matches!(facing.as_str(), "up" | "down" | "north" | "south"),
                                1 => matches!(facing.as_str(), "east" | "west" | "north" | "south"),
                                _ => matches!(facing.as_str(), "up" | "down" | "east" | "west"),
                            })
                })
            {
                return Err(invalid);
            }
            Ok(Record {
                controller,
                anchor,
                axis,
                angle,
                previous_angle,
                rpm,
                stalled: generation.is_none() && matches!(entry.get("Stalled"), Some(Tag::Byte(1))),
                return_home,
                stroke,
                clock_hand,
                blocks,
            })
        })
        .collect::<Result<Vec<_>, _>>()?;
    for record in &records {
        let Some(hand) = record.clock_hand else {
            continue;
        };
        if owners.contains(&(record.controller, None)) {
            return Err(invalid);
        }
        if hand == ClockHand::Minute {
            let Some(hour) = records.iter().find(|candidate| {
                candidate.controller == record.controller
                    && candidate.clock_hand == Some(ClockHand::Hour)
            }) else {
                return Err(invalid);
            };
            let axis = record.axis;
            if hour.axis != axis
                || (hour.anchor[axis] > hour.controller[axis])
                    != (record.anchor[axis] > record.controller[axis])
            {
                return Err(invalid);
            }
        }
    }
    Ok(SceneGeometry {
        generation,
        records,
    })
}

pub fn plain_rotary_state(state: &BlockState) -> bool {
    if !state.properties.is_empty() {
        return false;
    }
    let Some(name) = state.name.strip_prefix("minecraft:") else {
        return false;
    };
    matches!(
        name,
        "slime_block"
            | "stone"
            | "smooth_stone"
            | "cobblestone"
            | "andesite"
            | "polished_andesite"
            | "granite"
            | "diorite"
            | "bricks"
            | "stone_bricks"
            | "glass"
            | "terracotta"
    ) || ["_wool", "_concrete", "_stained_glass", "_terracotta"]
        .into_iter()
        .any(|suffix| {
            name.strip_suffix(suffix).is_some_and(|color| {
                crate::block_entity_render::DYES
                    .iter()
                    .any(|&(dye, _)| dye == color)
            })
        })
}

fn fits_rotary_column(
    controller: Pos,
    anchor: Pos,
    axis: usize,
    blocks: &[(Pos, BlockState)],
) -> bool {
    let [u, v] = [(axis + 1) % 3, (axis + 2) % 3];
    blocks.iter().all(|(local, _)| {
        let (a, b) = (local[u], local[v]);
        [(a, b), (-b, a), (-a, -b), (b, -a)]
            .into_iter()
            .all(|(a, b)| {
                let mut offset = *local;
                (offset[u], offset[v]) = (a, b);
                [0, 2].into_iter().all(|i| {
                    anchor[i]
                        .checked_add(offset[i])
                        .is_some_and(|coord| coord >> 4 == controller[i] >> 4)
                })
            })
    })
}

fn decode_blocks(
    entry: &Tag,
    packed: bool,
    max_offset: u32,
) -> Result<Arc<[(Pos, BlockState)]>, AttachmentError> {
    let invalid = AttachmentError::Decode;
    let mut locals = std::collections::BTreeSet::new();
    let mut validate = |local: Pos| {
        if local.iter().any(|v| v.unsigned_abs() > max_offset) || !locals.insert(local) {
            return Err(invalid);
        }
        Ok(local)
    };
    match (entry.get("Blocks"), entry.get("Palette")) {
        (Some(Tag::List(blocks)), None) if blocks.len() <= MAX_BLOCKS => blocks
            .iter()
            .map(|block| {
                let local = validate(position(block, "Pos")?)?;
                let state = BlockState::from_nbt(block.get("State").ok_or(invalid)?)
                    .map_err(|_| invalid)?;
                Ok((local, state))
            })
            .collect(),
        (Some(Tag::IntArray(data)), Some(Tag::List(palette))) if packed => {
            let (cells, remainder) = data.as_chunks::<4>();
            if !remainder.is_empty()
                || !(MAX_BLOCKS + 1..=MAX_PLAIN_ROTARY_BLOCKS).contains(&cells.len())
                || palette.is_empty()
                || palette.len() > cells.len()
            {
                return Err(invalid);
            }
            let palette = palette
                .iter()
                .map(|tag| {
                    let state = BlockState::from_nbt(tag).map_err(|_| invalid)?;
                    plain_rotary_state(&state).then_some(state).ok_or(invalid)
                })
                .collect::<Result<Vec<_>, _>>()?;
            cells
                .iter()
                .map(|&[x, y, z, index]| {
                    let local = validate([x, y, z])?;
                    let index = usize::try_from(index).map_err(|_| invalid)?;
                    Ok((local, palette.get(index).ok_or(invalid)?.clone()))
                })
                .collect()
        }
        _ => Err(invalid),
    }
}

fn position(entry: &Tag, name: &str) -> Result<Pos, AttachmentError> {
    match entry.get(name) {
        Some(Tag::IntArray(values)) => values
            .as_slice()
            .try_into()
            .map_err(|_| AttachmentError::Decode),
        _ => Err(AttachmentError::Decode),
    }
}

fn float(entry: &Tag, name: &str) -> Result<f32, AttachmentError> {
    match entry.get(name) {
        Some(Tag::Float(bits)) if f32::from_bits(*bits).is_finite() => Ok(f32::from_bits(*bits)),
        _ => Err(AttachmentError::Decode),
    }
}

fn read_hand(entry: &Tag) -> Result<Option<ClockHand>, AttachmentError> {
    match entry.get("ClockHand") {
        None => Ok(None),
        Some(Tag::Byte(0)) => Ok(Some(ClockHand::Hour)),
        Some(Tag::Byte(1)) => Ok(Some(ClockHand::Minute)),
        _ => Err(AttachmentError::Decode),
    }
}

fn read_generation(encoded: &Compound) -> Result<i64, AttachmentError> {
    match encoded.get(&"Generation".into()) {
        Some(Tag::Long(generation)) if *generation > 0 => Ok(*generation),
        _ => Err(AttachmentError::Decode),
    }
}

fn encode_motion(entry: &mut Compound, pose: Pose) {
    entry.extend([
        ("Angle".into(), Tag::Float(pose.angle.to_bits())),
        (
            "PreviousAngle".into(),
            Tag::Float(pose.previous_angle.to_bits()),
        ),
        ("Speed".into(), Tag::Float(pose.rpm.to_bits())),
    ]);
    if pose.stalled {
        entry.insert("Stalled".into(), Tag::Byte(1));
    }
    if let Some(stroke) = pose.stroke {
        entry.insert(
            "Stroke".into(),
            Tag::compound([
                ("Offset", Tag::Float(stroke.offset.to_bits())),
                ("Previous", Tag::Float(stroke.previous.to_bits())),
                ("Waiting", Tag::Byte(i8::from(stroke.waiting))),
            ]),
        );
    }
}

fn encode_poses(poses: &ScenePoses) -> Result<Compound, AttachmentError> {
    if poses.generation <= 0 || poses.entries.len() > MAX_RECORDS {
        return Err(AttachmentError::Encode);
    }
    let entries = poses
        .entries
        .iter()
        .map(|&pose| {
            let mut entry =
                Compound::from([("Controller".into(), Tag::IntArray(pose.controller.to_vec()))]);
            if let Some(hand) = pose.clock_hand {
                entry.insert(
                    "ClockHand".into(),
                    Tag::Byte(i8::from(hand == ClockHand::Minute)),
                );
            }
            encode_motion(&mut entry, pose);
            Tag::Compound(entry)
        })
        .collect();
    Ok(Compound::from([
        ("Version".into(), Tag::Int(1)),
        ("Generation".into(), Tag::Long(poses.generation)),
        ("Entries".into(), Tag::List(entries)),
    ]))
}

fn decode_poses(encoded: &Compound) -> Result<ScenePoses, AttachmentError> {
    let invalid = AttachmentError::Decode;
    if encoded.get(&"Version".into()) != Some(&Tag::Int(1)) {
        return Err(invalid);
    }
    let generation = read_generation(encoded)?;
    let Some(Tag::List(entries)) = encoded.get(&"Entries".into()) else {
        return Err(invalid);
    };
    if entries.len() > MAX_RECORDS {
        return Err(invalid);
    }
    let entries = entries
        .iter()
        .map(|entry| {
            let stroke = match entry.get("Stroke") {
                None => None,
                Some(tag) => Some(StrokePose {
                    offset: float(tag, "Offset")?,
                    previous: float(tag, "Previous")?,
                    waiting: matches!(tag.get("Waiting"), Some(Tag::Byte(1))),
                }),
            };
            Ok(Pose {
                controller: position(entry, "Controller")?,
                clock_hand: read_hand(entry)?,
                angle: float(entry, "Angle")?,
                previous_angle: float(entry, "PreviousAngle")?,
                rpm: float(entry, "Speed")?,
                stalled: matches!(entry.get("Stalled"), Some(Tag::Byte(1))),
                stroke,
            })
        })
        .collect::<Result<_, AttachmentError>>()?;
    Ok(ScenePoses {
        generation,
        entries,
    })
}

fn read_attachment<'a, T: Clone + Send + Sync + 'static>(
    map: &'a Attachments,
    attachment: &AttachmentType<T>,
) -> Result<Option<Cow<'a, T>>, AttachmentError> {
    use horizon_world::attachments::create_contraption_attachment::{decoded, encoded};
    if let Some(data) = decoded(map, attachment) {
        return Ok(Some(Cow::Borrowed(data)));
    }
    let Some(value) = encoded(map, attachment.namespace, attachment.name) else {
        return if map.has(attachment) {
            Err(AttachmentError::Decode)
        } else {
            Ok(None)
        };
    };
    (attachment
        .codec
        .as_ref()
        .ok_or(AttachmentError::Decode)?
        .decode)(value)
    .map(|data| Some(Cow::Owned(data)))
}

fn merge(scene: &SceneGeometry, poses: &ScenePoses) -> Result<Vec<Record>, AttachmentError> {
    if scene.generation != Some(poses.generation) || scene.records.len() != poses.entries.len() {
        return Err(AttachmentError::Decode);
    }
    scene
        .records
        .iter()
        .cloned()
        .zip(&poses.entries)
        .map(|(mut record, pose)| {
            pose.apply(&mut record)?;
            Ok(record)
        })
        .collect()
}

pub fn read_scene(map: &Attachments) -> Result<Cow<'_, [Record]>, AttachmentError> {
    let scene = read_attachment(map, &RECORDS)?;
    let poses = read_attachment(map, &POSES)?;
    match (scene, poses) {
        (None, None) => Ok(Cow::Borrowed(&[])),
        (Some(Cow::Borrowed(scene)), None) if scene.generation.is_none() => {
            Ok(Cow::Borrowed(&scene.records))
        }
        (Some(Cow::Owned(scene)), None) if scene.generation.is_none() => {
            Ok(Cow::Owned(scene.records))
        }
        (Some(scene), Some(poses)) => merge(&scene, &poses).map(Cow::Owned),
        _ => Err(AttachmentError::Decode),
    }
}

pub fn read(chunk: &crate::chunk::Chunk) -> Result<Cow<'_, [Record]>, AttachmentError> {
    chunk
        .saved
        .as_ref()
        .map_or(Ok(Cow::Borrowed(&[])), |saved| {
            read_scene(&saved.attachments)
        })
}

pub fn apply_scene_sync(
    map: &mut Attachments,
    changes: Vec<AttachmentSync>,
    replace: bool,
) -> Result<Vec<Record>, AttachmentError> {
    if replace {
        for name in [KEY, POSE_KEY] {
            map.apply_sync(AttachmentSync {
                namespace: "create".into(),
                name: name.into(),
                value: None,
            });
        }
    }
    for change in changes {
        map.apply_sync(change);
    }
    // Cache typed values once, after the complete column packet.
    map.get_existing(&RECORDS)?;
    map.get_existing(&POSES)?;
    read_scene(map).map(Cow::into_owned)
}

pub enum SceneUpdate {
    Geometry(SceneGeometry, ScenePoses),
    Poses(ScenePoses),
    Clear,
}

impl SceneUpdate {
    pub fn apply(self, map: &mut Attachments) -> Result<(), AttachmentError> {
        let pending = match self {
            Self::Geometry(geometry, poses) => {
                let mut pending = map.clone();
                pending.set(&RECORDS, geometry)?;
                pending.set(&POSES, poses)?;
                pending
            }
            Self::Clear => {
                let mut pending = map.clone();
                pending.remove(&RECORDS)?;
                pending.remove(&POSES)?;
                pending
            }
            Self::Poses(poses) => return map.set(&POSES, poses),
        };
        *map = pending;
        Ok(())
    }
}

pub fn plan_scene_update(
    map: Option<&Attachments>,
    mut records: Vec<Record>,
) -> Result<Option<SceneUpdate>, AttachmentError> {
    let geometry = map
        .map(|map| read_attachment(map, &RECORDS))
        .transpose()?
        .flatten();
    let poses = map
        .map(|map| read_attachment(map, &POSES))
        .transpose()?
        .flatten();
    if geometry.as_ref().and_then(|scene| scene.generation)
        != poses.as_ref().map(|poses| poses.generation)
    {
        return Err(AttachmentError::Decode);
    }
    if records.is_empty() {
        return Ok(geometry.is_some().then_some(SceneUpdate::Clear));
    }
    let entries: Vec<_> = records.iter().map(Pose::from).collect();
    for (&pose, record) in entries.iter().zip(&mut records) {
        pose.apply(record).map_err(|_| AttachmentError::Encode)?;
    }
    if let Some(old_geometry) = geometry.as_ref()
        && let Some(old_poses) = poses.as_ref()
        && old_geometry.records.len() == records.len()
        && old_geometry
            .records
            .iter()
            .zip(&records)
            .all(|(before, after)| before.same_geometry(after))
    {
        if old_poses.entries == entries {
            return Ok(None);
        }
        return Ok(Some(SceneUpdate::Poses(ScenePoses {
            generation: old_poses.generation,
            entries,
        })));
    }

    static GENERATION: AtomicI64 = AtomicI64::new(0);
    let prior = geometry
        .as_ref()
        .and_then(|scene| scene.generation)
        .unwrap_or(0);
    let next = |last: i64| last.max(prior).checked_add(1);
    let last = GENERATION
        .try_update(Ordering::Relaxed, Ordering::Relaxed, next)
        .map_err(|_| AttachmentError::Encode)?;
    let generation = next(last).ok_or(AttachmentError::Encode)?;
    for record in &mut records {
        record.angle = 0.0;
        record.previous_angle = 0.0;
        record.rpm = 0.0;
        record.stalled = false;
        if let Some(stroke) = &mut record.stroke {
            stroke.offset = 0.0;
            stroke.previous = 0.0;
            stroke.waiting = false;
        }
    }
    let geometry = SceneGeometry {
        generation: Some(generation),
        records,
    };
    let poses = ScenePoses {
        generation,
        entries,
    };
    Ok(Some(SceneUpdate::Geometry(geometry, poses)))
}

fn vector(v: [f64; 3]) -> Vec3 {
    Vec3::new(v[0], v[1], v[2])
}

fn collision_rotation(angle: f32) -> [f64; 2] {
    let angle = f64::from(angle).rem_euclid(360.0);
    match angle {
        0.0 => [1.0, 0.0],
        90.0 => [0.0, 1.0],
        180.0 => [-1.0, 0.0],
        270.0 => [0.0, -1.0],
        _ => {
            let (sin, cos) = angle.to_radians().sin_cos();
            [cos, sin]
        }
    }
}

fn rotate_plane([u, v]: [usize; 2], [cos, sin]: [f64; 2], mut point: [f64; 3]) -> [f64; 3] {
    [point[u], point[v]] = [
        cos * point[u] - sin * point[v],
        sin * point[u] + cos * point[v],
    ];
    point
}

/// Minecraft's movement solver takes axis-aligned shapes. Slice the rotated
/// rectangle in its rotation plane, keeping the exact span along the pivot axis.
/// All full cubes in the same contraption share these center-relative boxes.
fn block_cross_section([u, v]: [usize; 2], [cos, sin]: [f64; 2], bounds: Aabb) -> Vec<Aabb> {
    let min = bounds.min_position().components();
    let max = bounds.max_position().components();
    if cos == 0.0 || sin == 0.0 {
        return vec![Aabb::new(
            vector(rotate_plane([u, v], [cos, sin], min)),
            vector(rotate_plane([u, v], [cos, sin], max)),
        )];
    }
    let points = [
        [min[u], min[v]],
        [max[u], min[v]],
        [max[u], max[v]],
        [min[u], max[v]],
    ]
    .map(|[x, y]| [cos * x - sin * y, sin * x + cos * y]);
    let start = points.iter().map(|p| p[0]).fold(f64::INFINITY, f64::min);
    let end = points
        .iter()
        .map(|p| p[0])
        .fold(f64::NEG_INFINITY, f64::max);
    const STRIPS: i32 = 8;
    let boundary = |index| start + (end - start) * f64::from(index) / f64::from(STRIPS);
    let mut strips = Vec::with_capacity(STRIPS as usize);
    for index in 0..STRIPS {
        let lo = boundary(index);
        let hi = if index + 1 == STRIPS {
            end
        } else {
            boundary(index + 1)
        };
        let mut y_min = f64::INFINITY;
        let mut y_max = f64::NEG_INFINITY;
        let mut include = |y: f64| {
            y_min = y_min.min(y);
            y_max = y_max.max(y);
        };
        for edge in 0..4 {
            let [x, y] = points[edge];
            let [next_x, next_y] = points[(edge + 1) % 4];
            if (lo..=hi).contains(&x) {
                include(y);
            }
            for boundary in [lo, hi] {
                if boundary > x.min(next_x) && boundary < x.max(next_x) {
                    include(y + (next_y - y) * (boundary - x) / (next_x - x));
                }
            }
        }
        let mut strip_min = min;
        let mut strip_max = max;
        strip_min[u] = lo;
        strip_max[u] = hi;
        strip_min[v] = y_min;
        strip_max[v] = y_max;
        strips.push(Aabb::new(vector(strip_min), vector(strip_max)));
    }
    strips
}

pub fn dry_slab_type(state: &BlockState) -> Option<&str> {
    if !matches!(
        state.name.as_str(),
        "minecraft:oak_slab" | "minecraft:smooth_stone_slab"
    ) || state.properties.len() != 2
        || state.properties.get("waterlogged").map(String::as_str) != Some("false")
    {
        return None;
    }
    state
        .properties
        .get("type")
        .map(String::as_str)
        .filter(|kind| matches!(*kind, "bottom" | "top" | "double"))
}

pub fn vanilla_stair(state: &BlockState) -> bool {
    state.name.starts_with("minecraft:") && state.name.ends_with("_stairs")
}

pub fn dry_straight_stair(state: &BlockState) -> bool {
    matches!(
        state.name.as_str(),
        "minecraft:oak_stairs" | "minecraft:stone_stairs"
    ) && state.properties.len() == 4
        && state.properties.get("waterlogged").map(String::as_str) == Some("false")
        && state.properties.get("shape").map(String::as_str) == Some("straight")
        && state
            .properties
            .get("half")
            .is_some_and(|half| matches!(half.as_str(), "bottom" | "top"))
        && state
            .properties
            .get("facing")
            .is_some_and(|face| matches!(face.as_str(), "north" | "south" | "east" | "west"))
}

/// Registered Create cargo with a full collision cube and no persisted state.
pub fn solid_create_payload(state: &BlockState) -> bool {
    state.properties.is_empty()
        && matches!(
            state.name.as_str(),
            "create:cut_andesite"
                | "create:polished_cut_andesite"
                | "create:cut_andesite_bricks"
                | "create:small_andesite_bricks"
                | "create:layered_andesite"
                | "create:cut_granite"
                | "create:polished_cut_granite"
                | "create:cut_granite_bricks"
                | "create:small_granite_bricks"
                | "create:cut_diorite"
                | "create:polished_cut_diorite"
                | "create:cut_diorite_bricks"
                | "create:small_diorite_bricks"
                | "create:industrial_iron_block"
                | "create:weathered_iron_block"
                | "create:zinc_ore"
                | "create:deepslate_zinc_ore"
                | "create:raw_zinc_block"
                | "create:zinc_block"
                | "create:andesite_casing"
                | "create:brass_casing"
                | "create:copper_casing"
                | "create:andesite_alloy_block"
                | "create:brass_block"
        )
}

/// Supported payload states that fill a cube without querying collision shapes.
pub fn full_cube_payload(state: &BlockState) -> bool {
    solid_create_payload(state)
        || (state.name.starts_with("minecraft:")
            && !vanilla_stair(state)
            && !matches!(
                state.name.as_str(),
                "minecraft:honey_block" | "minecraft:chest"
            )
            && (!state.name.ends_with("_slab") || dry_slab_type(state) == Some("double")))
}

pub fn upright_side_payload(record: &Record) -> bool {
    record.axis == 1
        && record.stroke.is_none()
        && record.clock_hand.is_none()
        && !record.return_home
        && record.angle != record.previous_angle
        && record
            .blocks
            .iter()
            // The lateral solver clips with its own rotor excluded. Mixed
            // shapes must stay in the ordinary terrain collision path.
            .all(|(_, state)| full_cube_payload(state))
}

pub fn append_collisions(
    world: &crate::world::World,
    binding: &BlockCollisionRegistry<'_>,
    obstacles: &mut Vec<Aabb>,
    excluded_controller: Option<Pos>,
    standing_bounds: Option<Aabb>,
    exclude_upright: bool,
) {
    if !world.attachments.has(&ACTIVE) {
        return;
    }
    let mut lookup = crate::collisions::LookupCollisions {
        block: &|_, _, _| world.air,
        binding,
    };
    let lower = Vec3::new(-0.5, -0.5, -0.5);
    let cube = Aabb::unit_cube(lower);
    for chunk in world.chunks.values() {
        let Ok(records) = read(chunk) else { continue };
        for record in records.iter() {
            if Some(record.controller) == excluded_controller
                || (exclude_upright && upright_side_payload(record))
            {
                continue;
            }
            let standing = standing_bounds.filter(|_| upright_side_payload(record));
            let plane = [(record.axis + 1) % 3, (record.axis + 2) % 3];
            let rotation = collision_rotation(record.angle);
            let full_cube = block_cross_section(plane, rotation, cube);
            let origin = vector(record.origin_at(1.0).map(|component| component + 0.5));
            for (local, state) in record.blocks.iter() {
                let center =
                    origin.add_vector(vector(rotate_plane(plane, rotation, local.map(f64::from))));
                if full_cube_payload(state) {
                    obstacles.extend(full_cube.iter().map(|aabb| aabb.move_by(center)).filter(
                        |shape| {
                            standing.is_none_or(|body| {
                                // Java's side collider resolves an overlapping
                                // rotor at normal height. Its broad phase must not
                                // make the client choose a crawl pose under it.
                                shape.min_position().y <= body.min_position().y
                                    || !shape.intersects(body)
                            })
                        },
                    ));
                    continue;
                }
                // Captured non-cubes have static shapes keyed by block state.
                // World-dependent shapes need a local block view.
                let Some(id) = binding.registry().id(state) else {
                    continue;
                };
                let Ok(shape) = binding.collision_shape(&mut lookup, id, *local) else {
                    continue;
                };
                for aabb in shape.boxes() {
                    obstacles.extend(
                        block_cross_section(plane, rotation, aabb.move_by(lower))
                            .into_iter()
                            .map(|aabb| aabb.move_by(center)),
                    );
                }
            }
        }
    }
}

#[cfg(test)]
mod collision_tests {
    use super::*;

    fn legacy_round_trip(records: &[Record]) -> Result<Vec<Record>, AttachmentError> {
        Ok(decode_geometry(&encode_records(records, None)?)?.records)
    }

    #[test]
    fn clockwork_codec_keeps_independent_hands_with_one_controller() {
        let hand = |clock_hand, distance, angle| Record {
            controller: [1, 2, 3],
            anchor: [1 + distance, 2, 3],
            axis: 0,
            angle,
            previous_angle: angle,
            rpm: 32.0,
            stalled: false,
            return_home: true,
            stroke: None,
            clock_hand: Some(clock_hand),
            blocks: vec![(
                [0; 3],
                BlockState {
                    name: "minecraft:stone".into(),
                    properties: Default::default(),
                },
            )]
            .into(),
        };
        let hour = hand(ClockHand::Hour, 1, 15.0);
        let minute = hand(ClockHand::Minute, 3, 45.0);
        let restored = legacy_round_trip(&[hour.clone(), minute.clone()]).unwrap();
        assert_eq!(restored[0].clock_hand, Some(ClockHand::Hour));
        assert_eq!(restored[1].clock_hand, Some(ClockHand::Minute));
        assert_eq!(restored[1].anchor, [4, 2, 3]);
        assert_eq!(restored[1].angle, 45.0);
        assert!(legacy_round_trip(&[minute]).is_err());
        let opposite = hand(ClockHand::Minute, -3, 45.0);
        assert!(legacy_round_trip(&[hour.clone(), opposite]).is_err());
        assert!(legacy_round_trip(&[hour.clone(), hour]).is_err());
    }

    #[test]
    fn quarter_turns_use_an_exact_cube_for_every_axis() {
        let cube = Aabb::unit_cube(Vec3::new(-0.5, -0.5, -0.5));
        for axis in 0..3 {
            let axes = [(axis + 1) % 3, (axis + 2) % 3];
            for angle in [-450.0, -90.0, 0.0, 90.0, 180.0, 270.0, 360.0] {
                assert_eq!(
                    block_cross_section(axes, collision_rotation(angle), cube),
                    [cube]
                );
            }
        }
    }

    #[test]
    fn strips_cover_rotated_cube_and_leave_far_corners_empty() {
        let [cos, sin] = collision_rotation(45.0);
        let cube = Aabb::unit_cube(Vec3::new(-0.5, -0.5, -0.5));
        let strips = block_cross_section([0, 2], [cos, sin], cube);
        for x in [-0.49, -0.25, 0.0, 0.25, 0.49] {
            for z in [-0.49, -0.25, 0.0, 0.25, 0.49] {
                let point = Vec3::new(cos * x - sin * z, 0.0, sin * x + cos * z);
                assert!(strips.iter().any(|strip| strip.contains(point)));
            }
        }
        let corner = Vec3::new(0.6, 0.0, 0.6);
        assert!(!strips.iter().any(|strip| strip.contains(corner)));
    }

    #[test]
    fn off_center_part_rotates_without_inflating_into_a_full_block() {
        let south_harvester = Aabb::new(
            Vec3::new(-0.5, -0.375, -0.5),
            Vec3::new(0.5, 0.375, -0.3125),
        );
        let east_harvester = Aabb::new(
            Vec3::new(-0.5, -0.375, -0.5),
            Vec3::new(-0.3125, 0.375, 0.5),
        );
        assert_eq!(
            block_cross_section([2, 0], collision_rotation(90.0), south_harvester),
            [east_harvester]
        );
        let rotation = collision_rotation(33.0);
        let boxes = block_cross_section([2, 0], rotation, south_harvester);
        let mid = vector(rotate_plane([2, 0], rotation, [0.0, 0.0, -0.4]));
        assert!(boxes.iter().any(|box_| box_.contains(mid)));
        assert!(!boxes.iter().any(|box_| box_.contains(Vec3::ZERO)));
    }

    #[test]
    fn slabs_keep_their_half_height_through_oblique_y_rotation() {
        let bottom = Aabb::new(Vec3::new(-0.5, -0.5, -0.5), Vec3::new(0.5, 0.0, 0.5));
        let strips = block_cross_section([2, 0], collision_rotation(37.0), bottom);
        assert!(!strips.is_empty());
        assert!(
            strips.iter().all(|bounds| {
                bounds.min_position().y == -0.5 && bounds.max_position().y == 0.0
            })
        );
        let turned = block_cross_section([1, 2], collision_rotation(180.0), bottom);
        assert_eq!(turned.len(), 1);
        assert_eq!(turned[0].min_position().components(), [-0.5, 0.0, -0.5]);
        assert_eq!(turned[0].max_position().components(), [0.5, 0.5, 0.5]);
    }

    #[test]
    fn slabs_are_not_excluded_by_the_full_cube_side_resolver() {
        let mut record = Record {
            controller: [0, 64, 0],
            anchor: [0, 65, 0],
            axis: 1,
            angle: 0.0,
            previous_angle: -0.3,
            rpm: 8.0,
            stalled: false,
            return_home: false,
            clock_hand: None,
            stroke: None,
            blocks: vec![(
                [0; 3],
                BlockState {
                    name: "minecraft:stone".into(),
                    properties: Default::default(),
                },
            )]
            .into(),
        };
        assert!(upright_side_payload(&record));
        let mut blocks = record.blocks.to_vec();
        blocks.push((
            [1, 0, 0],
            BlockState {
                name: "minecraft:oak_slab".into(),
                properties: [
                    ("type".into(), "bottom".into()),
                    ("waterlogged".into(), "false".into()),
                ]
                .into(),
            },
        ));
        record.blocks = blocks.into();
        assert!(!upright_side_payload(&record));
    }

    #[test]
    fn piston_collision_origin_uses_the_full_current_stroke() {
        let mut record = Record {
            controller: [3, 60, 2],
            anchor: [3, 59, 2],
            axis: 1,
            angle: 0.0,
            previous_angle: 0.0,
            rpm: 8.0,
            stalled: false,
            return_home: false,
            clock_hand: None,
            stroke: Some(Stroke {
                kind: StrokeKind::Piston,
                initial: 0,
                limit: 4,
                offset: 1.75,
                previous: 1.5,
                waiting: false,
            }),
            blocks: Arc::from([]),
        };
        assert_eq!(record.origin_at(0.0), [3.0, 57.5, 2.0]);
        assert_eq!(record.origin_at(1.0), [3.0, 57.25, 2.0]);
        record.anchor[1] = 61;
        assert_eq!(record.origin_at(1.0), [3.0, 62.75, 2.0]);
    }

    #[test]
    fn rope_only_pulley_persists_a_long_downward_stroke() {
        let mut record = Record {
            controller: [3, 150, 2],
            anchor: [3, 149, 2],
            axis: 1,
            angle: 0.0,
            previous_angle: 0.0,
            rpm: 16.0,
            stalled: false,
            return_home: false,
            clock_hand: None,
            blocks: Arc::from([]),
            stroke: Some(Stroke {
                kind: StrokeKind::RopePulley,
                initial: 6,
                limit: 210,
                offset: 191.5,
                previous: 191.0,
                waiting: false,
            }),
        };
        let decoded = legacy_round_trip(&[record.clone()]).unwrap();
        assert_eq!(decoded[0].stroke_kind(), Some(StrokeKind::RopePulley));
        assert_eq!(decoded[0].origin_at(1.0), [3.0, -42.5, 2.0]);
        assert!(decoded[0].blocks.is_empty());
        record.anchor[1] = 151;
        assert!(legacy_round_trip(&[record]).is_err());
    }
}

#[cfg(test)]
mod scene_attachment_tests {
    use horizon_protocol::attachment_sync::{Message, decode, encode};
    use horizon_world::attachments::Holder;

    use super::*;

    fn carrier() -> Record {
        let stone = BlockState {
            name: "minecraft:stone".into(),
            properties: Default::default(),
        };
        Record {
            controller: [0, 64, 0],
            anchor: [1, 64, 0],
            axis: 0,
            angle: 3.0,
            previous_angle: 2.0,
            rpm: 16.0,
            stalled: true,
            return_home: false,
            stroke: Some(Stroke {
                kind: StrokeKind::Piston,
                initial: 1,
                limit: 4,
                offset: 1.75,
                previous: 1.5,
                waiting: true,
            }),
            clock_hand: None,
            blocks: (0..64)
                .map(|i| ([0, i / 8, i % 8], stone.clone()))
                .collect(),
        }
    }

    fn network(
        mirror: &mut Attachments,
        changes: Vec<AttachmentSync>,
        replace: bool,
    ) -> (usize, Vec<Record>) {
        let bytes = encode(&Message {
            holder: Holder::Chunk([0, 0]),
            replace,
            changes,
        })
        .unwrap();
        let message = decode(&bytes).unwrap();
        (
            bytes.len(),
            apply_scene_sync(mirror, message.changes, message.replace).unwrap(),
        )
    }

    #[test]
    fn pose_delta_keeps_geometry_and_cold_save_restores_both() {
        let legacy = carrier();
        let mut original = Attachments::default();
        original
            .set(
                &RECORDS,
                SceneGeometry {
                    generation: None,
                    records: vec![legacy.clone()],
                },
            )
            .unwrap();
        let mut server = Attachments::from_nbt(original.to_nbt());
        let old = read_scene(&server).unwrap().into_owned();
        assert_eq!(Pose::from(&old[0]), Pose::from(&legacy));
        let mut client = Attachments::default();
        let (_, previous_client) = network(&mut client, server.synced(), true);
        assert_eq!(Pose::from(&previous_client[0]), Pose::from(&legacy));

        let mut moving = old[0].clone();
        moving.angle = 5.0;
        moving.previous_angle = 3.0;
        moving.stalled = false;
        moving.stroke.as_mut().unwrap().waiting = false;
        let update = plan_scene_update(Some(&server), vec![moving.clone()])
            .unwrap()
            .unwrap();
        assert!(matches!(update, SceneUpdate::Geometry(_, _)));
        update.apply(&mut server).unwrap();
        let changes = server.take_sync_changes();
        assert_eq!(changes.len(), 2);
        let (geometry_packet_len, previous_client) = network(&mut client, changes, false);
        assert_eq!(Pose::from(&previous_client[0]), Pose::from(&moving));
        assert!(previous_client[0].same_geometry(&moving));
        let generation = read_attachment(&server, &RECORDS)
            .unwrap()
            .unwrap()
            .generation;

        moving.angle = 7.0;
        moving.previous_angle = 5.0;
        moving.stroke.as_mut().unwrap().offset = 2.0;
        let update = plan_scene_update(Some(&server), vec![moving.clone()])
            .unwrap()
            .unwrap();
        assert!(matches!(update, SceneUpdate::Poses(_)));
        update.apply(&mut server).unwrap();
        let changes = server.take_sync_changes();
        assert_eq!(changes.len(), 1);
        assert_eq!(changes[0].name, POSE_KEY.into());
        let (pose_packet_len, next_client) = network(&mut client, changes, false);
        assert!(pose_packet_len * 8 < geometry_packet_len);
        assert_eq!(Pose::from(&next_client[0]), Pose::from(&moving));
        assert!(Arc::ptr_eq(
            &previous_client[0].blocks,
            &next_client[0].blocks
        ));
        assert_eq!(
            read_attachment(&server, &RECORDS)
                .unwrap()
                .unwrap()
                .generation,
            generation
        );
        assert!(
            plan_scene_update(Some(&server), vec![moving.clone()])
                .unwrap()
                .is_none()
        );

        let cold = Attachments::from_nbt(server.to_nbt());
        let records = read_scene(&cold).unwrap();
        assert_eq!(Pose::from(&records[0]), Pose::from(&moving));
        assert!(records[0].same_geometry(&moving));
        assert!(network(&mut client, Vec::new(), true).1.is_empty());
        assert_eq!(network(&mut client, cold.synced(), true).1[0].angle, 7.0);

        plan_scene_update(Some(&server), Vec::new())
            .unwrap()
            .unwrap()
            .apply(&mut server)
            .unwrap();
        let changes = server.take_sync_changes();
        assert_eq!(changes.len(), 2);
        assert!(changes.iter().all(|change| change.value.is_none()));
        assert!(network(&mut client, changes, false).1.is_empty());
    }

    #[test]
    fn a_missing_stale_or_unrelated_pose_cannot_move_geometry() {
        let mut server = Attachments::default();
        plan_scene_update(None, vec![carrier()])
            .unwrap()
            .unwrap()
            .apply(&mut server)
            .unwrap();
        let mut client = Attachments::default();
        let mut scene = server.synced();
        let index = scene
            .iter()
            .position(|change| change.name == POSE_KEY.into())
            .unwrap();
        let mut pose = scene.remove(index);
        assert!(apply_scene_sync(&mut client, scene, true).is_err());
        let data = pose.value.as_mut().unwrap();
        let generation = read_generation(data).unwrap();
        data.insert("Generation".into(), Tag::Long(generation + 1));
        assert!(apply_scene_sync(&mut client, vec![pose.clone()], false).is_err());
        let data = pose.value.as_mut().unwrap();
        data.insert("Generation".into(), Tag::Long(generation));
        let Some(Tag::List(entries)) = data.get_mut(&"Entries".into()) else {
            panic!()
        };
        let Tag::Compound(entry) = &mut entries[0] else {
            panic!()
        };
        entry.insert("Controller".into(), Tag::IntArray(vec![0, 65, 0]));
        assert!(apply_scene_sync(&mut client, vec![pose], false).is_err());
    }

    #[test]
    fn large_rotors_pack_shared_states_and_reject_forged_payloads() {
        let mut rotor = carrier();
        rotor.stroke = None;
        rotor.controller = [8, 64, 7];
        rotor.anchor = [8, 65, 7];
        rotor.axis = 1;
        let stone = rotor.blocks[0].1.clone();
        rotor.blocks = (0..MAX_PLAIN_ROTARY_BLOCKS)
            .map(|i| {
                (
                    [i as i32 % 13 - 6, i as i32 / 169, i as i32 / 13 % 13 - 6],
                    stone.clone(),
                )
            })
            .collect();
        let rotors: Vec<_> = (0..4)
            .map(|i| {
                let mut record = rotor.clone();
                record.controller[1] += i * 16;
                record.anchor[1] += i * 16;
                record
            })
            .collect();
        let mut server = Attachments::default();
        plan_scene_update(None, rotors.clone())
            .unwrap()
            .unwrap()
            .apply(&mut server)
            .unwrap();
        let mut client = Attachments::default();
        let (wire_size, received) = network(&mut client, server.synced(), true);
        assert!(wire_size < 140_000, "{wire_size}");
        assert!(
            received
                .iter()
                .zip(&rotors)
                .all(|(one, two)| one.same_geometry(two))
        );

        let mut corrupt = encode_records(&[rotor.clone()], Some(1)).unwrap();
        let Some(Tag::List(entries)) = corrupt.get_mut(&"Entries".into()) else {
            panic!()
        };
        let Some(Tag::IntArray(positions)) = entries[0].get_mut("Blocks") else {
            panic!()
        };
        positions[3] = -1;
        assert!(decode_geometry(&corrupt).is_err());

        let mut foreign = rotor.clone();
        foreign.anchor[0] = 0;
        foreign.controller[0] = 0;
        assert!(decode_geometry(&encode_records(&[foreign], Some(1)).unwrap()).is_err());

        let mut excess = rotor.blocks.to_vec();
        excess.push(([0, 9, 0], stone));
        rotor.blocks = excess.into();
        assert!(encode_records(&[rotor.clone()], Some(1)).is_err());
        let mut mixed = rotor.blocks[..65].to_vec();
        mixed[0].1.name = "minecraft:barrel".into();
        rotor.blocks = mixed.into();
        assert!(encode_records(&[rotor.clone()], Some(1)).is_err());
        rotor.blocks = rotors[0].blocks.clone();
        rotor.stroke = carrier().stroke;
        assert!(encode_records(&[rotor], Some(1)).is_err());
    }
}
