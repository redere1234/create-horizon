// SPDX-License-Identifier: MIT

//! Strict, world-independent preflight for original Create 6.0.10 schematics.
//!
//! Source mapping (MIT, Copyright (c) The Create Team / The Creators of Create):
//! Create commit ac0c444d9828da3453ae8cc65338e8de063286fb, SchematicExport,
//! SchematicItem, SchematicPrinter, SchematicPlacePacket, BlockHelper and
//! SmartBlockEntity.writeSafe. Adapted placement policy, not a Java runtime.
//! See the bundle's NOTICE.md for third-party credits and LICENSE for the MIT terms.
//!
//! All world/registry access belongs to `Resolver` and the consuming adapter.
//! A failed preflight produces no Plan and this crate never changes a world.
//! No data-version migration, entities, alternate palette choice or transforms
//! are silently approximated. Supported source version is verified from the
//! Minecraft 1.21.1 client JAR's version.json (`world_version`: 3955).
pub mod nbt;
pub use nbt::{Compound, Tag, TagKind};
use std::{
    collections::{BTreeMap, BTreeSet},
    fmt,
};

pub const SOURCE_DATA_VERSION: i32 = 3955;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Error {
    pub path: String,
    pub message: String,
}
impl Error {
    pub fn new(path: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            path: path.into(),
            message: message.into(),
        }
    }
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.path, self.message)
    }
}
impl std::error::Error for Error {}

#[derive(Clone, Debug)]
pub struct Limits {
    pub max_compressed_bytes: usize,
    pub max_uncompressed_bytes: usize,
    pub max_depth: usize,
    pub max_nodes: usize,
    pub max_collection_len: usize,
    pub max_string_bytes: usize,
    pub max_blocks: usize,
    pub max_side: i32,
    pub max_volume: u64,
}
impl Default for Limits {
    fn default() -> Self {
        Self {
            max_compressed_bytes: 8 << 20,
            max_uncompressed_bytes: 16 << 20,
            max_depth: 64,
            max_nodes: 500_000,
            max_collection_len: 65_536,
            max_string_bytes: 65_535,
            max_blocks: 32_768,
            max_side: 128,
            max_volume: 262_144,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct BlockState {
    pub name: String,
    pub properties: BTreeMap<String, String>,
}
impl BlockState {
    pub fn new(name: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            properties: BTreeMap::new(),
        }
    }
    pub fn command_string(&self) -> String {
        if self.properties.is_empty() {
            return self.name.clone();
        }
        format!(
            "{}[{}]",
            self.name,
            self.properties
                .iter()
                .map(|(k, v)| format!("{k}={v}"))
                .collect::<Vec<_>>()
                .join(",")
        )
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Block {
    pub relative_pos: [i32; 3],
    pub state_index: usize,
    pub block_entity: Option<Compound>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Schematic {
    pub data_version: i32,
    pub size: [i32; 3],
    pub palettes: Vec<Vec<BlockState>>,
    pub blocks: Vec<Block>,
    /// Kept intact for diagnostics. Entity placement is outside this MVP.
    pub entities: Vec<Compound>,
}

fn list<'a>(tag: Option<&'a Tag>, kind: TagKind, path: &str) -> Result<&'a [Tag], Error> {
    match tag {
        Some(Tag::List { element, values }) if *element == kind || values.is_empty() => Ok(values),
        _ => Err(Error::new(path, format!("expected {kind:?} list"))),
    }
}
fn compound<'a>(tag: &'a Tag, path: &str) -> Result<&'a Compound, Error> {
    tag.as_compound()
        .ok_or_else(|| Error::new(path, "expected compound"))
}
fn fields(data: &Compound, allowed: &[&str], path: &str) -> Result<(), Error> {
    if let Some(key) = data.keys().find(|k| !allowed.contains(&k.as_str())) {
        return Err(Error::new(format!("{path}.{key}"), "unsupported field"));
    }
    Ok(())
}
fn ints3(tag: Option<&Tag>, path: &str) -> Result<[i32; 3], Error> {
    let values = list(tag, TagKind::Int, path)?;
    if values.len() != 3 {
        return Err(Error::new(path, "expected exactly three integers"));
    }
    let mut result = [0; 3];
    for (out, value) in result.iter_mut().zip(values) {
        let Tag::Int(v) = value else {
            return Err(Error::new(path, "expected integer"));
        };
        *out = *v;
    }
    Ok(result)
}
fn string(tag: Option<&Tag>, path: &str) -> Result<String, Error> {
    match tag {
        Some(Tag::String(s)) => Ok(s.clone()),
        _ => Err(Error::new(path, "expected string")),
    }
}
fn read_palette(tags: &[Tag], path: &str) -> Result<Vec<BlockState>, Error> {
    tags.iter()
        .enumerate()
        .map(|(index, tag)| {
            let path = format!("{path}[{index}]");
            let data = compound(tag, &path)?;
            // Create 1.21.1 writes Name/Properties. Accept the current spelling too,
            // but reject ambiguous aliases rather than choosing one silently.
            fields(data, &["Name", "Properties", "id", "properties"], &path)?;
            if data.contains_key("Name") && data.contains_key("id")
                || data.contains_key("Properties") && data.contains_key("properties")
            {
                return Err(Error::new(path, "ambiguous palette aliases"));
            }
            let name = string(
                data.get("Name").or_else(|| data.get("id")),
                &format!("{path}.Name"),
            )?;
            let mut properties = BTreeMap::new();
            if let Some(tag) = data.get("Properties").or_else(|| data.get("properties")) {
                for (key, value) in compound(tag, &format!("{path}.Properties"))? {
                    properties.insert(
                        key.clone(),
                        string(Some(value), &format!("{path}.Properties.{key}"))?,
                    );
                }
            }
            Ok(BlockState { name, properties })
        })
        .collect()
}

pub fn read_gzip(bytes: &[u8], limits: &Limits) -> Result<Schematic, Error> {
    Schematic::from_compound(&nbt::decode_gzip(bytes, limits)?, limits)
}
impl Schematic {
    pub fn from_compound(root: &Compound, limits: &Limits) -> Result<Self, Error> {
        fields(
            root,
            &[
                "DataVersion",
                "size",
                "palette",
                "palettes",
                "blocks",
                "entities",
            ],
            "root",
        )?;
        let data_version = match root.get("DataVersion") {
            Some(Tag::Int(v)) => *v,
            _ => return Err(Error::new("DataVersion", "required integer missing")),
        };
        let size = ints3(root.get("size"), "size")?;
        let volume = size
            .iter()
            .try_fold(1u64, |v, s| {
                if *s <= 0 || *s > limits.max_side {
                    return None;
                }
                v.checked_mul(*s as u64)
            })
            .ok_or_else(|| Error::new("size", "nonpositive or excessive dimensions"))?;
        if volume > limits.max_volume {
            return Err(Error::new("size", "volume exceeds limit"));
        }
        if root.contains_key("palette") && root.contains_key("palettes") {
            return Err(Error::new("palette", "both palette and palettes supplied"));
        }
        let palettes = if root.contains_key("palettes") {
            let outer = list(root.get("palettes"), TagKind::List, "palettes")?;
            outer
                .iter()
                .enumerate()
                .map(|(i, tag)| {
                    let path = format!("palettes[{i}]");
                    read_palette(list(Some(tag), TagKind::Compound, &path)?, &path)
                })
                .collect::<Result<Vec<_>, _>>()?
        } else {
            vec![read_palette(
                list(root.get("palette"), TagKind::Compound, "palette")?,
                "palette",
            )?]
        };
        if palettes.is_empty() || palettes.iter().any(Vec::is_empty) {
            return Err(Error::new("palette", "empty palette"));
        }
        if palettes.iter().any(|p| p.len() > limits.max_collection_len) {
            return Err(Error::new("palette", "palette exceeds limit"));
        }
        let tags = list(root.get("blocks"), TagKind::Compound, "blocks")?;
        if tags.len() > limits.max_blocks {
            return Err(Error::new("blocks", "block count exceeds limit"));
        }
        let mut blocks = Vec::new();
        let mut positions = BTreeSet::new();
        for (i, tag) in tags.iter().enumerate() {
            let path = format!("blocks[{i}]");
            let data = compound(tag, &path)?;
            fields(data, &["pos", "state", "nbt"], &path)?;
            let relative_pos = ints3(data.get("pos"), &format!("{path}.pos"))?;
            if relative_pos
                .iter()
                .zip(size)
                .any(|(p, s)| *p < 0 || *p >= s)
            {
                return Err(Error::new(format!("{path}.pos"), "position outside size"));
            }
            if !positions.insert(relative_pos) {
                return Err(Error::new(
                    format!("{path}.pos"),
                    "duplicate block position",
                ));
            }
            let state_index = match data.get("state") {
                Some(Tag::Int(v)) if *v >= 0 => *v as usize,
                _ => {
                    return Err(Error::new(
                        format!("{path}.state"),
                        "expected nonnegative palette index",
                    ));
                }
            };
            if palettes.iter().any(|p| state_index >= p.len()) {
                return Err(Error::new(
                    format!("{path}.state"),
                    "palette index out of range",
                ));
            }
            let block_entity = data
                .get("nbt")
                .map(|t| compound(t, &format!("{path}.nbt")).cloned())
                .transpose()?;
            blocks.push(Block {
                relative_pos,
                state_index,
                block_entity,
            });
        }
        let entities = list(root.get("entities"), TagKind::Compound, "entities")?
            .iter()
            .enumerate()
            .map(|(i, t)| compound(t, &format!("entities[{i}]")).cloned())
            .collect::<Result<_, _>>()?;
        Ok(Self {
            data_version,
            size,
            palettes,
            blocks,
            entities,
        })
    }

    /// Vanilla 1.21.1 structure layout, suitable for our generated fixtures.
    pub fn to_compound(&self) -> Compound {
        let ints = |v: [i32; 3]| Tag::list(TagKind::Int, v.into_iter().map(Tag::Int).collect());
        let palette = |states: &[BlockState]| {
            Tag::list(
                TagKind::Compound,
                states
                    .iter()
                    .map(|s| {
                        let mut c = Compound::from([("Name".into(), Tag::String(s.name.clone()))]);
                        if !s.properties.is_empty() {
                            c.insert(
                                "Properties".into(),
                                Tag::Compound(
                                    s.properties
                                        .iter()
                                        .map(|(k, v)| (k.clone(), Tag::String(v.clone())))
                                        .collect(),
                                ),
                            );
                        }
                        Tag::Compound(c)
                    })
                    .collect(),
            )
        };
        let mut root = Compound::from([
            ("DataVersion".into(), Tag::Int(self.data_version)),
            ("size".into(), ints(self.size)),
            (
                "blocks".into(),
                Tag::list(
                    TagKind::Compound,
                    self.blocks
                        .iter()
                        .map(|b| {
                            let mut c = Compound::from([
                                ("pos".into(), ints(b.relative_pos)),
                                (
                                    "state".into(),
                                    Tag::Int(i32::try_from(b.state_index).unwrap_or(-1)),
                                ),
                            ]);
                            if let Some(nbt) = &b.block_entity {
                                c.insert("nbt".into(), Tag::Compound(nbt.clone()));
                            }
                            Tag::Compound(c)
                        })
                        .collect(),
                ),
            ),
            (
                "entities".into(),
                Tag::list(
                    TagKind::Compound,
                    self.entities.iter().cloned().map(Tag::Compound).collect(),
                ),
            ),
        ]);
        if self.palettes.len() == 1 {
            root.insert("palette".into(), palette(&self.palettes[0]));
        } else {
            root.insert(
                "palettes".into(),
                Tag::list(
                    TagKind::List,
                    self.palettes.iter().map(|p| palette(p)).collect(),
                ),
            );
        }
        root
    }
}

/// The adapter must supply exact registry validation, not a vanilla fallback.
pub trait Resolver {
    fn block_schema(&self, state: &BlockState) -> Result<BlockSchema, String>;
    /// Additional source BlockHelper/state-filter behavior for explicitly
    /// supported special blocks. Unsupported special blocks must be rejected.
    fn prepare_state(&self, state: &BlockState) -> Result<BlockState, String> {
        Ok(state.clone())
    }
    /// Validate semantic contents (ranges, item IDs/components, filters, text)
    /// in addition to the schema's outer tag types. Called before any Plan exists.
    fn validate_safe_nbt(&self, _state: &BlockState, _data: &Compound) -> Result<(), String> {
        Ok(())
    }
}
#[derive(Clone, Debug)]
pub struct BlockSchema {
    /// Same requested state with omitted properties filled from registry defaults.
    pub state: BlockState,
    pub block_entity: Option<BlockEntitySchema>,
    /// SchematicPrinter's brittle/deferred pass, after ordinary blocks.
    pub deferred: bool,
}
#[derive(Clone, Debug)]
pub struct BlockEntitySchema {
    pub id: String,
    /// Source writeSafe fields actually implemented by the native adapter.
    pub safe_fields: BTreeMap<String, TagKind>,
    /// Known fields deliberately omitted by source safe-NBT, reported in notes.
    /// Unknown fields are rejected rather than claiming their behavior is supported.
    pub discarded_fields: BTreeSet<String>,
}
impl BlockEntitySchema {
    pub fn new(id: impl Into<String>) -> Self {
        Self {
            id: id.into(),
            safe_fields: BTreeMap::new(),
            discarded_fields: BTreeSet::new(),
        }
    }
}
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Mirror {
    #[default]
    None,
    LeftRight,
    FrontBack,
}

impl Mirror {
    pub fn name(self) -> &'static str {
        match self {
            Self::None => "none",
            Self::LeftRight => "left_right",
            Self::FrontBack => "front_back",
        }
    }
}

#[derive(Clone, Debug, Default)]
pub struct Options {
    pub include_air: bool,
    pub quarter_turns: u8,
    pub mirror: Mirror,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Issue {
    pub path: String,
    pub relative_pos: Option<[i32; 3]>,
    pub message: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Note {
    pub relative_pos: [i32; 3],
    pub field: String,
    pub message: String,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PlannedBlockEntity {
    pub id: String,
    pub data: Compound,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PlannedBlock {
    pub relative_pos: [i32; 3],
    pub state: BlockState,
    pub block_entity: Option<PlannedBlockEntity>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Plan {
    pub size: [i32; 3],
    pub blocks: Vec<PlannedBlock>,
    pub notes: Vec<Note>,
    pub skipped_air: usize,
}

fn valid_id(id: &str) -> bool {
    let Some((namespace, path)) = id.split_once(':') else {
        return false;
    };
    !namespace.is_empty()
        && !path.is_empty()
        && namespace
            .bytes()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || b"_.-".contains(&c))
        && path
            .bytes()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || b"/_.-".contains(&c))
}

fn encased_cogwheel(name: &str) -> bool {
    matches!(
        name,
        "create:andesite_encased_cogwheel"
            | "create:andesite_encased_large_cogwheel"
            | "create:brass_encased_cogwheel"
            | "create:brass_encased_large_cogwheel"
    )
}

fn resolve(resolver: &impl Resolver, state: &BlockState) -> Result<BlockSchema, String> {
    if state.name == "create:belt" && horizontal_belt_step(state).is_none() {
        return Err("only explicit dry uncased horizontal Belt states are supported".into());
    }
    if state.name == "create:chute" {
        let property = |key| state.properties.get(key).map(String::as_str);
        if property("waterlogged") != Some("false")
            || !matches!(
                property("facing"),
                Some("down" | "north" | "south" | "east" | "west")
            )
            || !matches!(
                property("shape"),
                Some("normal" | "window" | "intersection" | "encased")
            )
            || (property("facing") != Some("down") && property("shape") == Some("window"))
        {
            return Err("a Chute requires explicit dry facing and a supported shape".into());
        }
    }
    if state.name == "create:fluid_tank" {
        let property = |key| state.properties.get(key).map(String::as_str);
        if property("top") != Some("true")
            || property("bottom") != Some("true")
            || !matches!(property("shape"), Some("plain" | "window"))
        {
            return Err(
                "a schematic Fluid Tank must be a standalone plain or windowed tank".into(),
            );
        }
    }
    if state.name == "create:deployer"
        && ["facing", "axis_along_first"]
            .iter()
            .any(|key| !state.properties.contains_key(*key))
    {
        return Err("a Deployer requires explicit facing and axis_along_first properties".into());
    }
    if encased_cogwheel(&state.name)
        && ["axis", "top_shaft", "bottom_shaft"]
            .iter()
            .any(|key| !state.properties.contains_key(*key))
    {
        return Err("an Encased Cogwheel requires explicit axis and both shaft ends".into());
    }
    if !valid_id(&state.name) {
        return Err(format!("invalid namespaced block ID {:?}", state.name));
    }
    for (key, value) in &state.properties {
        if key.is_empty()
            || value.is_empty()
            || !key
                .bytes()
                .chain(value.bytes())
                .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || b"_.-".contains(&c))
        {
            return Err(format!("invalid property syntax {key:?}={value:?}"));
        }
    }
    let schema = resolver.block_schema(state)?;
    if schema.state.name != state.name
        || state
            .properties
            .iter()
            .any(|(k, v)| schema.state.properties.get(k) != Some(v))
    {
        return Err(
            "resolver changed an explicit block ID/property instead of validating it".into(),
        );
    }
    if schema
        .block_entity
        .as_ref()
        .is_some_and(|be| !valid_id(&be.id))
    {
        return Err("invalid block-entity schema ID".into());
    }
    Ok(schema)
}

// StructureTemplate.transform reflects first, then rotates around the zero
// pivot used by SchematicItem.getSettings. Offsets may be negative.
fn transform_position([x, y, z]: [i32; 3], options: &Options) -> [i32; 3] {
    let (x, z) = match options.mirror {
        Mirror::None => (x, z),
        Mirror::LeftRight => (x, -z),
        Mirror::FrontBack => (-x, z),
    };
    match options.quarter_turns {
        1 => [-z, y, x],
        2 => [-x, y, -z],
        3 => [z, y, -x],
        _ => [x, y, z],
    }
}

fn transform_state(
    requested: &BlockState,
    mut state: BlockState,
    options: &Options,
) -> Result<BlockState, String> {
    let operation = if options.quarter_turns == 0 {
        "mirroring"
    } else {
        "rotation"
    };
    let encased = encased_cogwheel(&state.name);
    let (properties, orientation): (&[&str], Option<&str>) = match state.name.as_str() {
        "create:shaft" => (&["axis", "waterlogged"], Some("axis")),
        "create:flywheel" => (&["axis"], Some("axis")),
        _ if encased => (&["axis", "top_shaft", "bottom_shaft"], Some("axis")),
        "create:creative_motor" | "create:mechanical_press" => (&["facing"], Some("facing")),
        "create:mechanical_crafter" => (&["facing", "pointing"], Some("facing")),
        "create:deployer" => (&["facing", "axis_along_first"], Some("facing")),
        "create:belt" => (
            &["facing", "slope", "part", "casing", "waterlogged"],
            Some("facing"),
        ),
        "create:chute" => (&["facing", "shape", "waterlogged"], Some("facing")),
        "create:fluid_tank" => (&["top", "bottom", "shape"], None),
        "create:depot" => (&["waterlogged"], None),
        "minecraft:air"
        | "minecraft:cave_air"
        | "minecraft:void_air"
        | "minecraft:stone"
        | "minecraft:cobblestone"
        | "minecraft:smooth_stone"
        | "minecraft:stone_bricks"
        | "minecraft:bricks"
        | "minecraft:andesite"
        | "minecraft:diorite"
        | "minecraft:granite"
        | "minecraft:netherrack"
        | "minecraft:end_stone"
        | "minecraft:obsidian" => (&[], None),
        name if name.starts_with("minecraft:") && name.ends_with("_log") => {
            (&["axis"], Some("axis"))
        }
        name if name.starts_with("minecraft:") && name.ends_with("_planks") => (&[], None),
        name => return Err(format!("{operation} is unsupported for {name}")),
    };
    if let Some(key) = state
        .properties
        .keys()
        .find(|key| !properties.contains(&key.as_str()))
    {
        return Err(format!(
            "{operation} does not support {} property {key}",
            state.name
        ));
    }
    if state.name == "create:mechanical_crafter" && !requested.properties.contains_key("pointing") {
        return Err(format!(
            "{operation} requires the explicit pointing property for {}",
            state.name
        ));
    }
    if let Some(key) = orientation {
        // A Java export supplies these properties. Do not transform a default
        // that may differ between the two games.
        let before = requested.properties.get(key).ok_or_else(|| {
            format!(
                "{operation} requires the explicit {key} property for {}",
                state.name
            )
        })?;
        let after = if key == "axis" {
            if encased {
                let top_direction = match before.as_str() {
                    "x" => [1, 0, 0],
                    "y" => [0, 1, 0],
                    "z" => [0, 0, 1],
                    _ => return Err(format!("invalid {operation} axis {before}")),
                };
                // The top shaft is the positive end of the axis in Create.
                if transform_position(top_direction, options)
                    .into_iter()
                    .any(|sign| sign < 0)
                {
                    let top = requested
                        .properties
                        .get("top_shaft")
                        .ok_or("missing top shaft")?;
                    let bottom = requested
                        .properties
                        .get("bottom_shaft")
                        .ok_or("missing bottom shaft")?;
                    state.properties.insert("top_shaft".into(), bottom.clone());
                    state.properties.insert("bottom_shaft".into(), top.clone());
                }
            }
            // Reflection changes the direction, but not the unoriented axis.
            match (before.as_str(), options.quarter_turns % 2) {
                ("x", 1) => "z",
                ("z", 1) => "x",
                ("x" | "y" | "z", _) => before,
                _ => return Err(format!("invalid {operation} axis {before}")),
            }
        } else {
            let directions = ["north", "east", "south", "west"];
            if let Some(i) = directions
                .iter()
                .position(|facing| *facing == before.as_str())
            {
                let mirrored = match (options.mirror, before.as_str()) {
                    (Mirror::LeftRight, "north" | "south")
                    | (Mirror::FrontBack, "east" | "west") => 2,
                    _ => 0,
                };
                directions[(i + mirrored + usize::from(options.quarter_turns)) % directions.len()]
            } else if matches!(before.as_str(), "up" | "down") {
                before
            } else {
                return Err(format!("invalid {operation} facing {before}"));
            }
        };
        state.properties.insert(key.into(), after.into());
    }
    if state.name == "create:deployer" && !options.quarter_turns.is_multiple_of(2) {
        // DirectionalAxisKineticBlock.rotate toggles this property even when
        // facing is vertical. Its mirror delegates to a 0° or 180° rotation.
        let along = state
            .properties
            .get_mut("axis_along_first")
            .ok_or("resolved Deployer has no axis_along_first property")?;
        *along = match along.as_str() {
            "true" => "false".into(),
            "false" => "true".into(),
            _ => return Err("invalid Deployer axis_along_first property".into()),
        };
    }
    Ok(state)
}

fn validate_crafter_source(raw: &Compound) -> Result<(), String> {
    let empty =
        |tag: Option<&Tag>| matches!(tag, Some(Tag::List { values, .. }) if values.is_empty());
    if let Some(input) = raw.get("ConnectedInput") {
        let valid = input.as_compound().is_some_and(|input| {
            input.len() == 2
                && input.get("Controller") == Some(&Tag::Byte(1))
                && matches!(input.get("Data"), Some(Tag::List { values, .. })
                    if matches!(values.as_slice(), [Tag::Compound(offset)]
                        if offset.len() == 3 && ["X", "Y", "Z"].iter()
                            .all(|axis| offset.get(*axis) == Some(&Tag::Int(0)))))
        });
        if !valid {
            return Err("only an unlinked Mechanical Crafter ConnectedInput is supported".into());
        }
    }
    for (key, valid) in [
        (
            "Inventory",
            raw.get("Inventory").is_none_or(|tag| {
                tag.as_compound().is_some_and(|inventory| {
                    inventory.len() == 2
                        && inventory.get("Size") == Some(&Tag::Int(1))
                        && empty(inventory.get("Items"))
                })
            }),
        ),
        (
            "GroupedItems",
            raw.get("GroupedItems").is_none_or(|tag| {
                tag.as_compound()
                    .is_some_and(|grouped| grouped.len() == 1 && empty(grouped.get("Grid")))
            }),
        ),
        (
            "Phase",
            raw.get("Phase")
                .is_none_or(|tag| tag.as_str() == Some("IDLE")),
        ),
        (
            "CountDown",
            raw.get("CountDown").is_none_or(|tag| *tag == Tag::Int(0)),
        ),
        (
            "Cover",
            raw.get("Cover").is_none_or(|tag| *tag == Tag::Byte(0)),
        ),
    ] {
        if !valid {
            return Err(format!(
                "only empty idle Mechanical Crafter data is supported ({key})"
            ));
        }
    }
    Ok(())
}

fn validate_deployer_source(raw: &Compound) -> Result<(), String> {
    let empty_compound = |key| {
        raw.get(key)
            .is_none_or(|tag| matches!(tag, Tag::Compound(values) if values.is_empty()))
    };
    let empty_list = |key| {
        raw.get(key)
            .is_none_or(|tag| matches!(tag, Tag::List { values, .. } if values.is_empty()))
    };
    for (key, valid) in [
        ("Mode", raw.get("Mode").and_then(Tag::as_str) == Some("USE")),
        (
            "State",
            raw.get("State")
                .is_none_or(|tag| tag.as_str() == Some("WAITING")),
        ),
        (
            "Timer",
            raw.get("Timer")
                .is_none_or(|tag| matches!(tag, Tag::Int(-511..=5120))),
        ),
        (
            "Powered",
            raw.get("Powered").is_none_or(|tag| *tag == Tag::Byte(0)),
        ),
        (
            "Speed",
            raw.get("Speed")
                .is_none_or(|tag| matches!(tag, Tag::Float(bits) if f32::from_bits(*bits) == 0.0)),
        ),
        ("Inventory", empty_list("Inventory")),
        ("Overflow", empty_list("Overflow")),
        ("HeldItem", empty_compound("HeldItem")),
        ("Filter", empty_compound("Filter")),
        ("Source", !raw.contains_key("Source")),
        ("Network", !raw.contains_key("Network")),
        ("Sequence", !raw.contains_key("Sequence")),
    ] {
        if !valid {
            return Err(format!(
                "only empty inactive Deployer use mode is supported ({key})"
            ));
        }
    }
    match (raw.get("Filter"), raw.get("FilterAmount"), raw.get("UpTo")) {
        (None, None, None) | (Some(_), Some(Tag::Int(1..=64)), Some(Tag::Byte(0 | 1))) => Ok(()),
        _ => Err("invalid Deployer FilterAmount or UpTo safe data".into()),
    }
}

fn validate_chute_source(raw: &Compound) -> Result<(), String> {
    let empty = raw
        .get("Item")
        .is_none_or(|tag| matches!(tag, Tag::Compound(values) if values.is_empty()));
    let still = ["Pull", "Push", "BottomAirFlowDistance"]
        .into_iter()
        .all(|key| {
            raw.get(key)
                .is_none_or(|tag| matches!(tag, Tag::Float(bits) if f32::from_bits(*bits) == 0.0))
        });
    let position = raw.get("ItemPosition").is_none_or(
        |tag| matches!(tag, Tag::Float(bits) if (0.0..=1.0).contains(&f32::from_bits(*bits))),
    );
    if !empty || !still || !position {
        return Err("only empty Chute data without airflow is supported".into());
    }
    Ok(())
}

fn validate_tank_source(state: &BlockState, raw: &Compound) -> Result<(), String> {
    let window = i8::from(state.properties["shape"] == "window");
    if raw.get("Window") != Some(&Tag::Byte(window))
        || raw.get("Size") != Some(&Tag::Int(1))
        || raw.get("Height") != Some(&Tag::Int(1))
        || raw.contains_key("Controller")
        || raw
            .get("TankContent")
            .is_some_and(|tag| !matches!(tag, Tag::Compound(values) if values.is_empty()))
    {
        return Err(
            "only empty standalone Fluid Tank data matching its window state is supported".into(),
        );
    }
    Ok(())
}

fn unsupported_chute_outlets(blocks: &[(bool, PlannedBlock)]) -> Vec<[i32; 3]> {
    let chutes: BTreeSet<_> = blocks
        .iter()
        .filter(|(_, block)| block.state.name == "create:chute")
        .map(|(_, block)| block.relative_pos)
        .collect();
    blocks
        .iter()
        .filter(|(_, block)| block.state.name == "create:chute")
        .filter_map(|(_, block)| {
            let [x, y, z] = block.relative_pos;
            // The state faces uphill and the outlet is one block down and
            // opposite that facing. The schematic owns that receiver.
            let outlet = match block.state.properties.get("facing")?.as_str() {
                "north" => [x, y - 1, z + 1],
                "south" => [x, y - 1, z - 1],
                "east" => [x - 1, y - 1, z],
                "west" => [x + 1, y - 1, z],
                _ => return None,
            };
            (!chutes.contains(&outlet)).then_some(block.relative_pos)
        })
        .collect()
}

/// The horizontal direction of a supported, explicit source Belt state.
pub fn horizontal_belt_step(state: &BlockState) -> Option<[i32; 3]> {
    let property = |key| state.properties.get(key).map(String::as_str);
    if state.name != "create:belt"
        || property("slope") != Some("horizontal")
        || property("casing") != Some("false")
        || property("waterlogged") != Some("false")
        || !matches!(
            property("part"),
            Some("start" | "middle" | "pulley" | "end")
        )
    {
        return None;
    }
    match property("facing")? {
        "north" => Some([0, 0, -1]),
        "south" => Some([0, 0, 1]),
        "west" => Some([-1, 0, 0]),
        "east" => Some([1, 0, 0]),
        _ => None,
    }
}

fn validate_belt_source(raw: &Compound) -> Result<(), String> {
    let empty_inventory = raw.get("Inventory").is_none_or(|tag| {
        tag.as_compound().is_some_and(|inventory| {
            inventory.len() == 2
                && matches!(inventory.get("Items"), Some(Tag::List { values, .. }) if values.is_empty())
                && matches!(inventory.get("PositiveOrder"), Some(Tag::Byte(0 | 1)))
        })
    });
    let old_controller = raw
        .get("Controller")
        .is_none_or(|tag| matches!(tag, Tag::IntArray(pos) if pos.len() == 3));
    let old_index = ["Length", "Index"].iter().all(|key| {
        raw.get(*key)
            .is_none_or(|tag| matches!(tag, Tag::Int(0..=1000)))
    });
    let old_flag = raw
        .get("IsController")
        .is_none_or(|tag| matches!(tag, Tag::Byte(0 | 1)));
    let bare = raw
        .get("Casing")
        .is_none_or(|tag| tag.as_str() == Some("NONE"))
        && raw.get("Covered").is_none_or(|tag| *tag == Tag::Byte(0))
        && !raw.contains_key("Dye");
    if !empty_inventory {
        return Err("only an empty Belt Inventory is supported".into());
    }
    if !bare {
        return Err("dyed, covered or cased Belt data is unsupported".into());
    }
    if !old_controller || !old_index || !old_flag {
        return Err("invalid source Belt controller metadata".into());
    }
    Ok(())
}

fn incomplete_belt_segments(blocks: &[(bool, PlannedBlock)]) -> BTreeSet<[i32; 3]> {
    let belts: BTreeMap<_, _> = blocks
        .iter()
        .filter(|(_, block)| block.state.name == "create:belt")
        .map(|(_, block)| (block.relative_pos, &block.state))
        .collect();
    let mut visited = BTreeSet::new();
    let mut invalid = BTreeSet::new();
    for (&start, state) in &belts {
        if state.properties["part"] != "start" {
            continue;
        }
        let Some(step) = horizontal_belt_step(state) else {
            invalid.insert(start);
            continue;
        };
        let mut pos = start;
        loop {
            let Some(segment) = belts.get(&pos) else {
                invalid.insert(start);
                break;
            };
            let part = segment.properties["part"].as_str();
            if !visited.insert(pos)
                || horizontal_belt_step(segment) != Some(step)
                || (pos != start && part == "start")
            {
                invalid.insert(start);
                break;
            }
            if part == "end" {
                break;
            }
            pos = std::array::from_fn(|axis| pos[axis] + step[axis]);
        }
    }
    invalid.extend(belts.into_keys().filter(|pos| !visited.contains(pos)));
    invalid
}

/// Validate the complete schematic before returning a world-independent plan.
/// The adapter must additionally preflight destination bounds/chunks/permissions
/// and snapshot/rollback a failed write. This function has no world handle.
pub fn preflight(
    schematic: &Schematic,
    resolver: &impl Resolver,
    options: &Options,
) -> Result<Plan, Vec<Issue>> {
    let mut issues = Vec::new();
    let mut fail = |path: String, pos: Option<[i32; 3]>, message: String| {
        issues.push(Issue {
            path,
            relative_pos: pos,
            message,
        })
    };
    if schematic.data_version != SOURCE_DATA_VERSION {
        fail(
            "DataVersion".into(),
            None,
            format!(
                "unsupported data version {}; expected {SOURCE_DATA_VERSION}; no migration is implemented",
                schematic.data_version
            ),
        );
    }
    if schematic.palettes.len() != 1 {
        fail(
            "palettes".into(),
            None,
            "exactly one palette is supported; random palette choice is not implemented".into(),
        );
    }
    if options.quarter_turns > 3 {
        fail(
            "transform".into(),
            None,
            "expected 0 to 3 clockwise quarter turns".into(),
        );
    }
    let transformed = options.quarter_turns != 0 || options.mirror != Mirror::None;
    let limits = Limits::default();
    let volume = schematic.size.iter().try_fold(1u64, |v, s| {
        if *s <= 0 || *s > limits.max_side {
            None
        } else {
            v.checked_mul(*s as u64)
        }
    });
    if volume.is_none_or(|v| v > limits.max_volume) {
        fail(
            "size".into(),
            None,
            "invalid or excessive dimensions".into(),
        );
    }
    if schematic.blocks.len() > limits.max_blocks {
        fail(
            "blocks".into(),
            None,
            "block count exceeds placement limit".into(),
        );
    }
    if schematic.palettes.iter().any(Vec::is_empty) {
        fail("palette".into(), None, "empty palette".into());
    }
    for (i, entity) in schematic.entities.iter().enumerate() {
        let id = entity
            .get("nbt")
            .and_then(Tag::as_compound)
            .and_then(|c| c.get("id"))
            .and_then(Tag::as_str)
            .unwrap_or("<unknown>");
        fail(
            format!("entities[{i}]"),
            None,
            format!("entity {id} is unsupported; entities are never silently dropped"),
        );
    }
    let mut resolved = Vec::new();
    for (p, palette) in schematic.palettes.iter().enumerate() {
        for (i, state) in palette.iter().enumerate() {
            let schema = resolve(resolver, state).and_then(|schema| {
                if !transformed {
                    return Ok(schema);
                }
                let placed = transform_state(state, schema.state, options)?;
                resolve(resolver, &placed)
            });
            match schema {
                Ok(schema) if p == 0 => resolved.push(Some(schema)),
                Ok(_) => {}
                Err(message) => {
                    fail(
                        format!("palettes[{p}][{i}]"),
                        schematic
                            .blocks
                            .iter()
                            .find(|b| b.state_index == i)
                            .map(|b| b.relative_pos),
                        message,
                    );
                    if p == 0 {
                        resolved.push(None);
                    }
                }
            }
        }
    }
    let mut blocks = Vec::new();
    let mut notes = Vec::new();
    let mut skipped_air = 0;
    let mut positions = BTreeSet::new();
    for (index, block) in schematic.blocks.iter().enumerate() {
        let path = format!("blocks[{index}]");
        let input_pos = block.relative_pos;
        if input_pos
            .iter()
            .zip(schematic.size)
            .any(|(p, s)| *p < 0 || *p >= s)
        {
            fail(
                format!("{path}.pos"),
                Some(input_pos),
                "position outside size".into(),
            );
            continue;
        }
        let pos = transform_position(input_pos, options);
        if !positions.insert(pos) {
            fail(
                format!("{path}.pos"),
                Some(pos),
                "duplicate block position".into(),
            );
        }
        let Some(schema) = resolved.get(block.state_index) else {
            fail(
                format!("{path}.state"),
                Some(pos),
                "palette index out of range".into(),
            );
            continue;
        };
        let Some(schema) = schema else {
            continue;
        };
        let mut state = schema.state.clone();
        for property in ["waterlogged", "extended"] {
            if let Some(value) = state.properties.get_mut(property) {
                *value = "false".into();
            }
        }
        let prepared = match resolver
            .prepare_state(&state)
            .and_then(|s| resolve(resolver, &s))
        {
            Ok(prepared) => prepared,
            Err(message) => {
                fail(path, Some(pos), message);
                continue;
            }
        };
        for (key, before) in &schema.state.properties {
            if prepared.state.properties.get(key) != Some(before) {
                notes.push(Note {
                    relative_pos: pos,
                    field: key.clone(),
                    message: format!(
                        "source creative placement: {before} -> {}",
                        prepared
                            .state
                            .properties
                            .get(key)
                            .map(String::as_str)
                            .unwrap_or("<absent>")
                    ),
                });
            }
        }
        if prepared.state.name != schema.state.name {
            notes.push(Note {
                relative_pos: pos,
                field: "Name".into(),
                message: format!(
                    "source creative placement: {} -> {}",
                    schema.state.name, prepared.state.name
                ),
            });
        }
        let mut planned_be = prepared.block_entity.as_ref().map(|s| PlannedBlockEntity {
            id: s.id.clone(),
            data: Compound::new(),
        });
        if let Some(raw) = &block.block_entity {
            let Some(be_schema) = &prepared.block_entity else {
                fail(
                    format!("{path}.nbt"),
                    Some(pos),
                    "block does not support a block entity".into(),
                );
                continue;
            };
            if prepared.state.name == "create:mechanical_crafter"
                && let Err(message) = validate_crafter_source(raw)
            {
                fail(format!("{path}.nbt"), Some(pos), message);
                continue;
            }
            if prepared.state.name == "create:belt"
                && let Err(message) = validate_belt_source(raw)
            {
                fail(format!("{path}.nbt"), Some(pos), message);
                continue;
            }
            if prepared.state.name == "create:deployer"
                && let Err(message) = validate_deployer_source(raw)
            {
                fail(format!("{path}.nbt"), Some(pos), message);
                continue;
            }
            if prepared.state.name == "create:chute"
                && let Err(message) = validate_chute_source(raw)
            {
                fail(format!("{path}.nbt"), Some(pos), message);
                continue;
            }
            if prepared.state.name == "create:fluid_tank"
                && let Err(message) = validate_tank_source(&prepared.state, raw)
            {
                fail(format!("{path}.nbt"), Some(pos), message);
                continue;
            }
            if raw.get("id").and_then(Tag::as_str) != Some(be_schema.id.as_str()) {
                fail(
                    format!("{path}.nbt.id"),
                    Some(pos),
                    format!(
                        "expected block entity {}; got {:?}",
                        be_schema.id,
                        raw.get("id")
                    ),
                );
            }
            let mut safe = Compound::new();
            for (key, value) in raw {
                if key == "id" {
                    continue;
                }
                if ["x", "y", "z"].contains(&key.as_str()) {
                    if !matches!(value, Tag::Int(_)) {
                        fail(
                            format!("{path}.nbt.{key}"),
                            Some(pos),
                            "block-entity position metadata must be Int".into(),
                        );
                    }
                } else if let Some(kind) = be_schema.safe_fields.get(key) {
                    if value.kind() != *kind {
                        fail(
                            format!("{path}.nbt.{key}"),
                            Some(pos),
                            format!("expected {kind:?}, got {:?}", value.kind()),
                        );
                    } else {
                        safe.insert(key.clone(), value.clone());
                    }
                } else if be_schema.discarded_fields.contains(key) {
                    notes.push(Note {
                        relative_pos: pos,
                        field: key.clone(),
                        message: "discarded by explicitly supported source safe-NBT policy".into(),
                    });
                } else {
                    fail(
                        format!("{path}.nbt.{key}"),
                        Some(pos),
                        "unsupported block-entity field; safe placement policy is not implemented"
                            .into(),
                    );
                }
            }
            if let Err(message) = resolver.validate_safe_nbt(&prepared.state, &safe) {
                fail(format!("{path}.nbt"), Some(pos), message);
            }
            if transformed
                && safe.keys().any(|key| {
                    !matches!(
                        (prepared.state.name.as_str(), key.as_str()),
                        ("create:creative_motor", "ScrollValue")
                            | ("create:mechanical_crafter", "ConnectedInput")
                            | ("create:fluid_tank", "Window" | "Size" | "Height")
                            | (
                                "create:deployer",
                                "Mode" | "Filter" | "FilterAmount" | "UpTo"
                            )
                    )
                })
            {
                fail(
                    format!("{path}.nbt"),
                    Some(pos),
                    "rotation or mirroring is unsupported for this block-entity data".into(),
                );
            }
            planned_be = Some(PlannedBlockEntity {
                id: be_schema.id.clone(),
                data: safe,
            });
        }
        if !options.include_air
            && matches!(
                prepared.state.name.as_str(),
                "minecraft:air" | "minecraft:cave_air" | "minecraft:void_air"
            )
        {
            skipped_air += 1;
            continue;
        }
        blocks.push((
            prepared.deferred,
            PlannedBlock {
                relative_pos: pos,
                state: prepared.state,
                block_entity: planned_be,
            },
        ));
    }
    for pos in incomplete_belt_segments(&blocks) {
        fail(
            "blocks".into(),
            Some(pos),
            "Belt segments must form a complete horizontal chain from start to end".into(),
        );
    }
    for pos in unsupported_chute_outlets(&blocks) {
        fail(
            "blocks".into(),
            Some(pos),
            "a diagonal Chute requires its downhill Chute in the schematic".into(),
        );
    }
    let tanks: BTreeSet<_> = blocks
        .iter()
        .filter(|(_, block)| block.state.name == "create:fluid_tank")
        .map(|(_, block)| block.relative_pos)
        .collect();
    for &[x, y, z] in &tanks {
        if [[x + 1, y, z], [x, y + 1, z], [x, y, z + 1]]
            .into_iter()
            .any(|neighbor| tanks.contains(&neighbor))
        {
            fail(
                "blocks".into(),
                Some([x, y, z]),
                "schematic Fluid Tanks must not touch".into(),
            );
        }
    }
    if !issues.is_empty() {
        return Err(issues);
    }
    // Source creative printer visits X first, then Z, then Y, and does a
    // separate deferred pass. Source BE/shape behavior still belongs to adapter.
    blocks.sort_by_key(|(deferred, b)| {
        (
            *deferred,
            b.relative_pos[1],
            b.relative_pos[2],
            b.relative_pos[0],
        )
    });
    let [x, y, z] = schematic.size;
    Ok(Plan {
        size: if options.quarter_turns.is_multiple_of(2) {
            [x, y, z]
        } else {
            [z, y, x]
        },
        blocks: blocks.into_iter().map(|(_, b)| b).collect(),
        notes,
        skipped_air,
    })
}

#[cfg(test)]
mod tests;
