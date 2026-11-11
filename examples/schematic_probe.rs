//! Generated fixtures are our own constructions, not upstream schematic assets.
use create_schematics::{
    Block, BlockEntitySchema, BlockSchema, BlockState, Compound, Limits, Options, Resolver,
    SOURCE_DATA_VERSION, Schematic, Tag, TagKind, nbt, preflight, read_gzip,
};
use serde_json::{Value, json};
use std::{collections::BTreeMap, path::Path};

/// This probe registry is deliberately a small fixture specification, not the
/// native registry. Real imports must supply the actual runtime Resolver.
struct FixtureRegistry;
impl Resolver for FixtureRegistry {
    fn block_schema(&self, requested: &BlockState) -> Result<BlockSchema, String> {
        let mut defaults = BTreeMap::new();
        let mut entity = None;
        match requested.name.as_str() {
            "minecraft:air" | "minecraft:smooth_stone" | "minecraft:stone" => {}
            "minecraft:campfire" => {
                defaults.extend([
                    ("facing", "north"),
                    ("lit", "true"),
                    ("signal_fire", "false"),
                    ("waterlogged", "false"),
                ]);
            }
            "minecraft:lever" => {
                defaults.extend([("face", "floor"), ("facing", "north"), ("powered", "false")]);
            }
            "create:shaft" | "create:clutch" => {
                defaults.extend([("axis", "y"), ("waterlogged", "false")]);
                if requested.name == "create:clutch" {
                    defaults.insert("powered", "false");
                    entity = Some("create:clutch");
                }
            }
            "create:creative_motor" => {
                defaults.insert("facing", "north");
                entity = Some("create:motor");
            }
            "create:mechanical_press" => {
                defaults.insert("facing", "east");
                entity = Some("create:mechanical_press");
            }
            "create:encased_fan" => {
                defaults.insert("facing", "down");
                entity = Some("create:encased_fan");
            }
            "create:mechanical_drill" => {
                defaults.extend([("facing", "down"), ("waterlogged", "false")]);
                entity = Some("create:drill");
            }
            "create:millstone" => {
                entity = Some("create:millstone");
            }
            "create:depot" => {
                entity = Some("create:depot");
            }
            _ => return Err(format!("unsupported fixture block {}", requested.name)),
        }
        for (k, v) in &requested.properties {
            if !defaults.contains_key(k.as_str()) {
                return Err(format!("unknown property {k}"));
            }
            let valid = match k.as_str() {
                "axis" => ["x", "y", "z"].contains(&v.as_str()),
                "facing" => {
                    ["north", "south", "east", "west", "up", "down"].contains(&v.as_str())
                        && !(requested.name == "create:mechanical_press"
                            && ["up", "down"].contains(&v.as_str()))
                }
                "face" => ["floor", "wall", "ceiling"].contains(&v.as_str()),
                _ => ["true", "false"].contains(&v.as_str()),
            };
            if !valid {
                return Err(format!("invalid {k}={v}"));
            }
        }
        let mut state = requested.clone();
        for (k, v) in defaults {
            state.properties.entry(k.into()).or_insert(v.into());
        }
        let block_entity = entity.map(|id| {
            let mut schema = BlockEntitySchema::new(id);
            if id == "create:motor" {
                schema
                    .safe_fields
                    .insert("ScrollValue".into(), TagKind::Int);
            }
            schema.discarded_fields.extend(
                [
                    "Speed",
                    "Source",
                    "Network",
                    "NeedsSpeedUpdate",
                    "Sequence",
                    "Items",
                    "InputInventory",
                    "OutputInventory",
                    "Timer",
                    "HeldItem",
                    "OutputBuffer",
                ]
                .map(str::to_owned),
            );
            schema
        });
        Ok(BlockSchema {
            state,
            block_entity,
            deferred: requested.name == "minecraft:lever",
        })
    }
    fn validate_safe_nbt(&self, _: &BlockState, data: &Compound) -> Result<(), String> {
        if let Some(Tag::Int(v)) = data.get("ScrollValue")
            && !(-256..=256).contains(v)
        {
            return Err("ScrollValue outside -256..256".into());
        }
        Ok(())
    }
}
fn state(name: &str, properties: &[(&str, &str)]) -> BlockState {
    BlockState {
        name: name.into(),
        properties: properties
            .iter()
            .map(|(k, v)| ((*k).into(), (*v).into()))
            .collect(),
    }
}
fn fixture() -> Schematic {
    let mut s = Schematic {
        data_version: SOURCE_DATA_VERSION,
        size: [8, 4, 5],
        palettes: vec![Vec::new()],
        blocks: Vec::new(),
        entities: Vec::new(),
    };
    let mut put = |pos: [i32; 3], name: &str, properties: &[(&str, &str)], rpm: Option<i32>| {
        let state = state(name, properties);
        let index = s.palettes[0]
            .iter()
            .position(|v| v == &state)
            .unwrap_or_else(|| {
                s.palettes[0].push(state.clone());
                s.palettes[0].len() - 1
            });
        let schema = FixtureRegistry.block_schema(&state).unwrap();
        let block_entity = schema.block_entity.map(|schema| {
            let mut nbt = Compound::from([
                ("id".into(), Tag::String(schema.id)),
                ("x".into(), Tag::Int(pos[0] + 100)),
                ("y".into(), Tag::Int(pos[1] + 64)),
                ("z".into(), Tag::Int(pos[2] - 20)),
            ]);
            if let Some(rpm) = rpm {
                nbt.insert("ScrollValue".into(), Tag::Int(rpm));
                nbt.insert("Speed".into(), Tag::Float(999f32.to_bits()));
            }
            nbt
        });
        s.blocks.retain(|b| b.relative_pos != pos);
        s.blocks.push(Block {
            relative_pos: pos,
            state_index: index,
            block_entity,
        });
    };
    for x in 0..8 {
        for z in 0..5 {
            put([x, 0, z], "minecraft:smooth_stone", &[], None);
        }
    }
    put(
        [0, 2, 0],
        "create:creative_motor",
        &[("facing", "east")],
        Some(128),
    );
    put(
        [1, 2, 0],
        "create:shaft",
        &[("axis", "x"), ("waterlogged", "true")],
        None,
    );
    put(
        [2, 2, 0],
        "create:mechanical_press",
        &[("facing", "east")],
        None,
    );
    put([2, 0, 0], "create:depot", &[], None);
    put(
        [0, 1, 2],
        "create:creative_motor",
        &[("facing", "up")],
        Some(128),
    );
    put([0, 2, 2], "create:millstone", &[], None);
    put(
        [0, 1, 4],
        "create:creative_motor",
        &[("facing", "east")],
        Some(32),
    );
    put([1, 1, 4], "create:shaft", &[("axis", "x")], None);
    put([2, 1, 4], "create:encased_fan", &[("facing", "east")], None);
    put([3, 1, 4], "minecraft:campfire", &[("lit", "true")], None);
    put([5, 0, 4], "create:depot", &[], None);
    put(
        [4, 1, 2],
        "create:creative_motor",
        &[("facing", "east")],
        Some(128),
    );
    put(
        [5, 1, 2],
        "create:clutch",
        &[("axis", "x"), ("powered", "true")],
        None,
    );
    put(
        [5, 2, 2],
        "minecraft:lever",
        &[("face", "floor"), ("facing", "north"), ("powered", "true")],
        None,
    );
    put(
        [6, 1, 2],
        "create:mechanical_drill",
        &[("facing", "east")],
        None,
    );
    put([7, 1, 2], "minecraft:stone", &[], None);
    s
}
fn inspect(bytes: &[u8]) -> Result<Value, String> {
    let s = read_gzip(bytes, &Limits::default()).map_err(|e| e.to_string())?;
    match preflight(&s, &FixtureRegistry, &Options::default()) {
        Ok(plan) => Ok(
            json!({"valid":true,"data_version":s.data_version,"size":plan.size,"block_count":plan.blocks.len(),"skipped_air":plan.skipped_air,"blocks":plan.blocks.iter().map(|b|json!({"pos":b.relative_pos,"state":b.state.command_string(),"be_id":b.block_entity.as_ref().map(|be|&be.id),"safe_nbt":b.block_entity.as_ref().map(|be|format!("{:?}",be.data))})).collect::<Vec<_>>(),"notes":plan.notes.iter().map(|n|json!({"pos":n.relative_pos,"field":n.field,"message":n.message})).collect::<Vec<_>>()}),
        ),
        Err(issues) => Ok(
            json!({"valid":false,"issues":issues.iter().map(|i|json!({"path":i.path,"pos":i.relative_pos,"message":i.message})).collect::<Vec<_>>()}),
        ),
    }
}
fn unhex(s: &str) -> Result<Vec<u8>, String> {
    if !s.len().is_multiple_of(2) {
        return Err("odd hex length".into());
    }
    s.as_bytes()
        .as_chunks::<2>()
        .0
        .iter()
        .map(|c| {
            u8::from_str_radix(std::str::from_utf8(c).map_err(|e| e.to_string())?, 16)
                .map_err(|e| e.to_string())
        })
        .collect()
}
fn execute(args: &[String]) -> Result<Value, String> {
    match args {
        [mode, path] if mode == "generate" => {
            let s = fixture();
            let bytes = nbt::encode_gzip(&s.to_compound(), &Limits::default())
                .map_err(|e| e.to_string())?;
            let path = Path::new(path);
            if let Some(parent) = path.parent() {
                std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
            }
            std::fs::write(path, &bytes).map_err(|e| e.to_string())?;
            inspect(&bytes)
        }
        [mode, path] if mode == "inspect" => {
            inspect(&std::fs::read(path).map_err(|e| e.to_string())?)
        }
        [mode, hex] if mode == "utf" => {
            let bytes = unhex(hex)?;
            let text = std::str::from_utf8(&bytes).map_err(|e| e.to_string())?;
            let encoded = nbt::encode_modified_utf8(text);
            Ok(
                json!({"encoded":encoded.iter().map(|b|format!("{b:02x}")).collect::<String>(),"decoded":nbt::decode_modified_utf8(&encoded).map_err(str::to_owned)?}),
            )
        }
        _ => {
            Err("usage: schematic_probe generate|inspect FILE; schematic_probe utf UTF8HEX".into())
        }
    }
}
fn main() {
    match execute(&std::env::args().skip(1).collect::<Vec<_>>()) {
        Ok(report) => println!("{report}"),
        Err(error) => {
            println!("{}", json!({"valid":false,"error":error}));
            std::process::exit(1);
        }
    }
}
