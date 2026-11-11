// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use super::*;

struct Registry;
impl Resolver for Registry {
    fn block_schema(&self, requested: &BlockState) -> Result<BlockSchema, String> {
        let mut state = requested.clone();
        let mut defaults = BTreeMap::new();
        let mut be = None;
        match state.name.as_str() {
            "minecraft:stone" | "minecraft:air" => {}
            "create:shaft" => {
                defaults.insert("axis", "y");
                defaults.insert("waterlogged", "false");
            }
            name if encased_cogwheel(name) => {
                defaults.extend([
                    ("axis", "y"),
                    ("top_shaft", "false"),
                    ("bottom_shaft", "false"),
                ]);
                be = Some(BlockEntitySchema::new(if name.contains("_large_") {
                    "create:encased_large_cogwheel"
                } else {
                    "create:encased_cogwheel"
                }));
            }
            "create:creative_motor" => {
                defaults.insert("facing", "north");
                let mut schema = BlockEntitySchema::new("create:motor");
                schema
                    .safe_fields
                    .insert("ScrollValue".into(), TagKind::Int);
                schema
                    .discarded_fields
                    .extend(["Speed", "Source", "Network", "Items"].map(str::to_owned));
                be = Some(schema);
            }
            "create:mechanical_crafter" => {
                defaults.insert("facing", "north");
                defaults.insert("pointing", "up");
                let mut schema = BlockEntitySchema::new("create:mechanical_crafter");
                schema
                    .safe_fields
                    .insert("ConnectedInput".into(), TagKind::Compound);
                schema.discarded_fields.extend(
                    ["Inventory", "GroupedItems", "Phase", "CountDown", "Cover"].map(str::to_owned),
                );
                be = Some(schema);
            }
            "create:deployer" => {
                defaults.extend([("facing", "down"), ("axis_along_first", "true")]);
                let mut schema = BlockEntitySchema::new("create:deployer");
                schema.safe_fields.extend([
                    ("Mode".into(), TagKind::String),
                    ("Filter".into(), TagKind::Compound),
                    ("FilterAmount".into(), TagKind::Int),
                    ("UpTo".into(), TagKind::Byte),
                ]);
                schema.discarded_fields.extend(
                    [
                        "State",
                        "Timer",
                        "Powered",
                        "Speed",
                        "Inventory",
                        "HeldItem",
                        "Overflow",
                    ]
                    .map(str::to_owned),
                );
                be = Some(schema);
            }
            "create:belt" => {
                defaults.extend([
                    ("facing", "north"),
                    ("slope", "horizontal"),
                    ("part", "start"),
                    ("casing", "false"),
                    ("waterlogged", "false"),
                ]);
                let mut schema = BlockEntitySchema::new("create:belt");
                schema.discarded_fields.extend(
                    [
                        "Controller",
                        "Length",
                        "Index",
                        "IsController",
                        "Inventory",
                        "Casing",
                        "Covered",
                    ]
                    .map(str::to_owned),
                );
                be = Some(schema);
            }
            "create:chute" => {
                defaults.extend([
                    ("facing", "down"),
                    ("shape", "normal"),
                    ("waterlogged", "false"),
                ]);
                let mut schema = BlockEntitySchema::new("create:chute");
                schema.discarded_fields.extend(
                    [
                        "Item",
                        "ItemPosition",
                        "Pull",
                        "Push",
                        "BottomAirFlowDistance",
                    ]
                    .map(str::to_owned),
                );
                be = Some(schema);
            }
            "minecraft:piston" => {
                defaults.insert("extended", "false");
            }
            "minecraft:torch" => {}
            _ => return Err(format!("unsupported block {}", state.name)),
        }
        for (key, value) in &state.properties {
            if !defaults.contains_key(key.as_str()) {
                return Err(format!("unsupported property {key}"));
            }
            let valid = match key.as_str() {
                "axis" => ["x", "y", "z"].contains(&value.as_str()),
                "facing" => {
                    ["north", "south", "east", "west", "up", "down"].contains(&value.as_str())
                }
                "pointing" => ["up", "left", "down", "right"].contains(&value.as_str()),
                "slope" => value == "horizontal",
                "part" => ["start", "middle", "pulley", "end"].contains(&value.as_str()),
                "shape" => {
                    ["normal", "window", "intersection", "encased"].contains(&value.as_str())
                }
                _ => ["false", "true"].contains(&value.as_str()),
            };
            if !valid {
                return Err(format!("invalid {key}={value}"));
            }
        }
        for (key, value) in defaults {
            state.properties.entry(key.into()).or_insert(value.into());
        }
        let deferred = state.name == "minecraft:torch";
        Ok(BlockSchema {
            state,
            block_entity: be,
            deferred,
        })
    }
    fn validate_safe_nbt(&self, _state: &BlockState, data: &Compound) -> Result<(), String> {
        if let Some(Tag::Int(v)) = data.get("ScrollValue")
            && !(-256..=256).contains(v)
        {
            return Err("motor ScrollValue out of source range".into());
        }
        Ok(())
    }
}

#[test]
fn encased_cogwheels_transform_the_positive_shaft_end() {
    for (axis, rotation) in [
        ("x", [("x", false), ("z", false), ("x", true), ("z", true)]),
        ("y", [("y", false); 4]),
        ("z", [("z", false), ("x", true), ("z", true), ("x", false)]),
    ] {
        let requested = BlockState {
            name: "create:brass_encased_large_cogwheel".into(),
            properties: BTreeMap::from([
                ("axis".into(), axis.into()),
                ("top_shaft".into(), "true".into()),
                ("bottom_shaft".into(), "false".into()),
            ]),
        };
        assert!(resolve(&Registry, &requested).is_ok());
        for (mirror, mirrored) in [
            (Mirror::None, false),
            (Mirror::LeftRight, axis == "z"),
            (Mirror::FrontBack, axis == "x"),
        ] {
            for (turns, (expected_axis, rotated)) in rotation.into_iter().enumerate() {
                let transformed = transform_state(
                    &requested,
                    requested.clone(),
                    &Options {
                        mirror,
                        quarter_turns: turns as u8,
                        ..Options::default()
                    },
                )
                .unwrap();
                let swapped = mirrored ^ rotated;
                assert_eq!(transformed.properties["axis"], expected_axis);
                assert_eq!(transformed.properties["top_shaft"], (!swapped).to_string());
                assert_eq!(transformed.properties["bottom_shaft"], swapped.to_string());
            }
        }
        let mut incomplete = requested;
        incomplete.properties.remove("top_shaft");
        assert!(
            resolve(&Registry, &incomplete)
                .unwrap_err()
                .contains("both shaft ends")
        );
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
    // Our own original two-block mechanism, not a copied upstream asset.
    Schematic {
        data_version: SOURCE_DATA_VERSION,
        size: [4, 2, 2],
        palettes: vec![vec![
            state("create:creative_motor", &[("facing", "east")]),
            state("create:shaft", &[("axis", "x"), ("waterlogged", "true")]),
            BlockState::new("minecraft:air"),
        ]],
        blocks: vec![
            Block {
                relative_pos: [0, 0, 0],
                state_index: 0,
                block_entity: Some(Compound::from([
                    ("id".into(), Tag::String("create:motor".into())),
                    ("ScrollValue".into(), Tag::Int(128)),
                    ("Speed".into(), Tag::Float(128f32.to_bits())),
                    ("Source".into(), Tag::IntArray(vec![20, 70, 30])),
                    (
                        "Network".into(),
                        Tag::Compound(Compound::from([("Id".into(), Tag::Long(123456789))])),
                    ),
                    (
                        "Items".into(),
                        Tag::list(
                            TagKind::Compound,
                            vec![Tag::Compound(Compound::from([(
                                "id".into(),
                                Tag::String("minecraft:diamond".into()),
                            )]))],
                        ),
                    ),
                    ("x".into(), Tag::Int(17)),
                    ("y".into(), Tag::Int(64)),
                    ("z".into(), Tag::Int(-3)),
                ])),
            },
            Block {
                relative_pos: [1, 0, 0],
                state_index: 1,
                block_entity: None,
            },
            Block {
                relative_pos: [2, 0, 0],
                state_index: 2,
                block_entity: None,
            },
        ],
        entities: vec![],
    }
}
fn raw_be(s: &mut Schematic) -> &mut Compound {
    s.blocks[0].block_entity.as_mut().unwrap()
}
fn plan(s: &Schematic) -> Result<Plan, Vec<Issue>> {
    preflight(s, &Registry, &Options::default())
}

#[test]
fn clockwise_rotations_use_the_zero_pivot_and_preserve_safe_motor_settings() {
    let mut schematic = fixture();
    schematic.blocks[1].relative_pos = [1, 0, 1];
    for (turns, expected_pos, axis, facing, size) in [
        (1, [-1, 0, 1], "z", "south", [2, 2, 4]),
        (2, [-1, 0, -1], "x", "west", [4, 2, 2]),
        (3, [1, 0, -1], "z", "north", [2, 2, 4]),
    ] {
        let placed = preflight(
            &schematic,
            &Registry,
            &Options {
                quarter_turns: turns,
                ..Options::default()
            },
        )
        .unwrap();
        assert_eq!(placed.size, size);
        assert_eq!(placed.skipped_air, 1);
        let motor = placed
            .blocks
            .iter()
            .find(|b| b.relative_pos == [0; 3])
            .unwrap();
        assert_eq!(motor.state.properties["facing"], facing);
        assert_eq!(
            motor.block_entity.as_ref().unwrap().data,
            Compound::from([("ScrollValue".into(), Tag::Int(128))])
        );
        let shaft = placed
            .blocks
            .iter()
            .find(|b| b.relative_pos == expected_pos)
            .unwrap();
        assert_eq!(shaft.state.properties["axis"], axis);
        assert_eq!(shaft.state.properties["waterlogged"], "false");
    }
}

#[test]
fn mirrors_precede_rotation_and_preserve_the_motor_setting() {
    let mut schematic = fixture();
    schematic.blocks[1].relative_pos = [1, 0, 1];
    for (mirror, shaft_positions, facings) in [
        (
            Mirror::LeftRight,
            [[1, 0, -1], [1, 0, 1], [-1, 0, 1], [-1, 0, -1]],
            ["east", "south", "west", "north"],
        ),
        (
            Mirror::FrontBack,
            [[-1, 0, 1], [-1, 0, -1], [1, 0, -1], [1, 0, 1]],
            ["west", "north", "east", "south"],
        ),
    ] {
        for quarter_turns in 0..=3 {
            let placed = preflight(
                &schematic,
                &Registry,
                &Options {
                    mirror,
                    quarter_turns,
                    ..Options::default()
                },
            )
            .unwrap();
            let motor = placed
                .blocks
                .iter()
                .find(|block| block.relative_pos == [0; 3])
                .unwrap();
            assert_eq!(
                motor.state.properties["facing"],
                facings[quarter_turns as usize]
            );
            assert_eq!(
                motor.block_entity.as_ref().unwrap().data,
                Compound::from([("ScrollValue".into(), Tag::Int(128))])
            );
            let shaft = placed
                .blocks
                .iter()
                .find(|block| block.state.name == "create:shaft")
                .unwrap();
            assert_eq!(shaft.relative_pos, shaft_positions[quarter_turns as usize]);
            assert_eq!(
                shaft.state.properties["axis"],
                if quarter_turns % 2 == 0 { "x" } else { "z" }
            );
        }
    }
    schematic.palettes[0][0]
        .properties
        .insert("facing".into(), "north".into());
    let placed = preflight(
        &schematic,
        &Registry,
        &Options {
            mirror: Mirror::LeftRight,
            ..Options::default()
        },
    )
    .unwrap();
    let motor = placed
        .blocks
        .iter()
        .find(|block| block.relative_pos == [0; 3])
        .unwrap();
    assert_eq!(motor.state.properties["facing"], "south");
}

#[test]
fn rotated_preflight_rejects_unsupported_blocks_missing_axes_and_invalid_positions() {
    let mut schematic = fixture();
    let options = Options {
        quarter_turns: 1,
        ..Options::default()
    };
    schematic.palettes[0].push(BlockState::new("minecraft:torch"));
    assert!(plan(&schematic).is_ok());
    assert!(
        preflight(&schematic, &Registry, &options).unwrap_err()[0]
            .message
            .contains("rotation is unsupported for minecraft:torch")
    );
    assert!(
        preflight(
            &schematic,
            &Registry,
            &Options {
                mirror: Mirror::LeftRight,
                ..Options::default()
            }
        )
        .unwrap_err()[0]
            .message
            .contains("mirroring is unsupported for minecraft:torch")
    );
    schematic.palettes[0].pop();
    schematic.palettes[0][1].properties.remove("axis");
    assert!(
        preflight(&schematic, &Registry, &options).unwrap_err()[0]
            .message
            .contains("explicit axis")
    );
    schematic.palettes[0][1]
        .properties
        .insert("axis".into(), "x".into());
    schematic.blocks[1].relative_pos = [i32::MIN, 0, 0];
    assert!(
        preflight(&schematic, &Registry, &options).unwrap_err()[0]
            .message
            .contains("position outside size")
    );
}

fn crafter_fixture() -> Schematic {
    let offset = Tag::Compound(Compound::from(
        ["X", "Y", "Z"].map(|key| (key.into(), Tag::Int(0))),
    ));
    let connected = Tag::Compound(Compound::from([
        ("Controller".into(), Tag::Byte(1)),
        ("Data".into(), Tag::list(TagKind::Compound, vec![offset])),
    ]));
    Schematic {
        data_version: SOURCE_DATA_VERSION,
        size: [1; 3],
        palettes: vec![vec![state(
            "create:mechanical_crafter",
            &[("facing", "east"), ("pointing", "left")],
        )]],
        blocks: vec![Block {
            relative_pos: [0; 3],
            state_index: 0,
            block_entity: Some(Compound::from([
                ("id".into(), Tag::String("create:mechanical_crafter".into())),
                ("ConnectedInput".into(), connected),
                (
                    "Inventory".into(),
                    Tag::Compound(Compound::from([
                        ("Size".into(), Tag::Int(1)),
                        ("Items".into(), Tag::list(TagKind::Compound, Vec::new())),
                    ])),
                ),
                (
                    "GroupedItems".into(),
                    Tag::Compound(Compound::from([(
                        "Grid".into(),
                        Tag::list(TagKind::Compound, Vec::new()),
                    )])),
                ),
                ("Phase".into(), Tag::String("IDLE".into())),
                ("CountDown".into(), Tag::Int(0)),
                ("Cover".into(), Tag::Byte(0)),
            ])),
        }],
        entities: Vec::new(),
    }
}

#[test]
fn crafter_facing_transforms_but_pointing_and_safe_input_stay_fixed() {
    let schematic = crafter_fixture();
    let connected = schematic.blocks[0].block_entity.as_ref().unwrap()["ConnectedInput"].clone();
    for mirror in [Mirror::None, Mirror::LeftRight, Mirror::FrontBack] {
        let facings = if mirror == Mirror::FrontBack {
            ["west", "north", "east", "south"]
        } else {
            ["east", "south", "west", "north"]
        };
        for (quarter_turns, facing) in facings.into_iter().enumerate() {
            let plan = preflight(
                &schematic,
                &Registry,
                &Options {
                    mirror,
                    quarter_turns: quarter_turns as u8,
                    ..Options::default()
                },
            )
            .unwrap();
            let block = &plan.blocks[0];
            assert_eq!(block.state.properties["facing"], facing);
            assert_eq!(block.state.properties["pointing"], "left");
            assert_eq!(
                block.block_entity.as_ref().unwrap().data,
                Compound::from([("ConnectedInput".into(), connected.clone())])
            );
        }
    }
}

#[test]
fn crafter_links_and_live_fields_are_rejected_before_any_plan() {
    for (field, value, message) in [
        (
            "ConnectedInput",
            Tag::Compound(Compound::from([("Controller".into(), Tag::Byte(0))])),
            "unlinked",
        ),
        ("Cover", Tag::Byte(1), "Cover"),
        ("Phase", Tag::String("EXPORTING".into()), "Phase"),
        ("CountDown", Tag::Int(250), "CountDown"),
        ("Inventory", Tag::Compound(Compound::new()), "Inventory"),
        (
            "GroupedItems",
            Tag::Compound(Compound::new()),
            "GroupedItems",
        ),
    ] {
        let mut schematic = crafter_fixture();
        schematic.blocks[0]
            .block_entity
            .as_mut()
            .unwrap()
            .insert(field.into(), value);
        let issues = preflight(&schematic, &Registry, &Options::default()).unwrap_err();
        assert!(
            issues.iter().any(|issue| issue.message.contains(message)),
            "{issues:?}"
        );
    }
}

fn deployer_fixture(facing: &str, axis: &str) -> Schematic {
    let safe = Compound::from([
        ("id".into(), Tag::String("create:deployer".into())),
        ("Mode".into(), Tag::String("USE".into())),
        ("Filter".into(), Tag::Compound(Compound::new())),
        ("FilterAmount".into(), Tag::Int(23)),
        ("UpTo".into(), Tag::Byte(0)),
        ("State".into(), Tag::String("WAITING".into())),
        ("Timer".into(), Tag::Int(500)),
        ("Speed".into(), Tag::Float(0)),
        ("Powered".into(), Tag::Byte(0)),
        ("HeldItem".into(), Tag::Compound(Compound::new())),
        ("Inventory".into(), Tag::list(TagKind::Compound, Vec::new())),
        ("Overflow".into(), Tag::list(TagKind::Compound, Vec::new())),
    ]);
    Schematic {
        data_version: SOURCE_DATA_VERSION,
        size: [2, 1, 3],
        palettes: vec![vec![state(
            "create:deployer",
            &[("facing", facing), ("axis_along_first", axis)],
        )]],
        blocks: vec![Block {
            relative_pos: [1, 0, 2],
            state_index: 0,
            block_entity: Some(safe),
        }],
        entities: Vec::new(),
    }
}

#[test]
fn deployer_rotation_toggles_both_shaft_choices_for_all_six_facings() {
    let facings = ["north", "east", "south", "west", "up", "down"];
    for (direction, facing) in facings.into_iter().enumerate() {
        for axis in ["true", "false"] {
            let schematic = deployer_fixture(facing, axis);
            let source = schematic.blocks[0].block_entity.as_ref().unwrap();
            let safe = ["Mode", "Filter", "FilterAmount", "UpTo"]
                .map(|key| (key.into(), source[key].clone()));
            for (mirror, reflect) in [
                (Mirror::None, [0, 1, 2, 3, 4, 5]),
                (Mirror::LeftRight, [2, 1, 0, 3, 4, 5]),
                (Mirror::FrontBack, [0, 3, 2, 1, 4, 5]),
            ] {
                for quarter_turns in 0..=3 {
                    let mirrored = reflect[direction];
                    let placed = if mirrored < 4 {
                        facings[(mirrored + usize::from(quarter_turns)) % 4]
                    } else {
                        facing
                    };
                    let options = Options {
                        mirror,
                        quarter_turns,
                        ..Options::default()
                    };
                    let plan = preflight(&schematic, &Registry, &options).unwrap();
                    let block = &plan.blocks[0];
                    assert_eq!(block.state.properties["facing"], placed);
                    assert_eq!(
                        block.state.properties["axis_along_first"],
                        ((axis == "true") ^ (quarter_turns % 2 != 0)).to_string()
                    );
                    assert_eq!(
                        block.block_entity.as_ref().unwrap().data,
                        Compound::from(safe.clone())
                    );
                }
            }
        }
    }
}

#[test]
fn deployer_requires_explicit_orientation_and_refuses_live_or_nonempty_data() {
    let mut missing = deployer_fixture("up", "true");
    missing.palettes[0][0].properties.remove("axis_along_first");
    assert!(preflight(&missing, &Registry, &Options::default()).is_err());

    let stack = Compound::from([("id".into(), Tag::String("minecraft:stick".into()))]);
    for (key, value) in [
        ("Mode", Tag::String("PUNCH".into())),
        ("State", Tag::String("EXPANDING".into())),
        ("Speed", Tag::Float(16f32.to_bits())),
        ("Powered", Tag::Byte(1)),
        ("HeldItem", Tag::Compound(stack.clone())),
        (
            "Inventory",
            Tag::list(TagKind::Compound, vec![Tag::Compound(stack.clone())]),
        ),
        (
            "Overflow",
            Tag::list(TagKind::Compound, vec![Tag::Compound(stack.clone())]),
        ),
        ("Filter", Tag::Compound(stack)),
        ("Source", Tag::IntArray(vec![0, 0, 0])),
        ("Network", Tag::Compound(Compound::new())),
        ("FilterAmount", Tag::Int(0)),
    ] {
        let mut schematic = deployer_fixture("down", "false");
        schematic.blocks[0]
            .block_entity
            .as_mut()
            .unwrap()
            .insert(key.into(), value);
        let issues = preflight(&schematic, &Registry, &Options::default()).unwrap_err();
        assert!(
            issues.iter().any(|issue| issue.message.contains(key)),
            "{issues:?}"
        );
    }
}

fn belt_fixture() -> Schematic {
    let parts = ["start", "middle", "pulley", "end"];
    let palette = parts.map(|part| {
        state(
            "create:belt",
            &[
                ("facing", "east"),
                ("slope", "horizontal"),
                ("part", part),
                ("casing", "false"),
                ("waterlogged", "false"),
            ],
        )
    });
    Schematic {
        data_version: SOURCE_DATA_VERSION,
        size: [4, 1, 1],
        palettes: vec![palette.into()],
        blocks: (0..parts.len())
            .map(|index| Block {
                relative_pos: [index as i32, 0, 0],
                state_index: index,
                block_entity: Some(Compound::from([
                    ("id".into(), Tag::String("create:belt".into())),
                    ("Controller".into(), Tag::IntArray(vec![7, 80, -9])),
                    ("Length".into(), Tag::Int(4)),
                    ("Index".into(), Tag::Int(index as i32)),
                    ("IsController".into(), Tag::Byte(i8::from(index == 0))),
                ])),
            })
            .collect(),
        entities: Vec::new(),
    }
}

#[test]
fn dry_chute_transform_keeps_the_outlet_and_refuses_cargo_or_missing_receivers() {
    let chute = |facing, shape| {
        state(
            "create:chute",
            &[
                ("facing", facing),
                ("shape", shape),
                ("waterlogged", "false"),
            ],
        )
    };
    let source = Schematic {
        data_version: SOURCE_DATA_VERSION,
        size: [3, 3, 1],
        palettes: vec![vec![
            chute("down", "intersection"),
            chute("east", "normal"),
            chute("east", "intersection"),
        ]],
        blocks: (0..3)
            .map(|index| Block {
                relative_pos: [index as i32, index as i32, 0],
                state_index: index,
                block_entity: Some(Compound::from([
                    ("id".into(), Tag::String("create:chute".into())),
                    ("Item".into(), Tag::Compound(Compound::new())),
                ])),
            })
            .collect(),
        entities: Vec::new(),
    };
    let options = Options {
        mirror: Mirror::FrontBack,
        quarter_turns: 1,
        ..Options::default()
    };
    let plan = preflight(&source, &Registry, &options).unwrap();
    assert_eq!(plan.blocks[1].relative_pos, [0, 1, -1]);
    assert_eq!(plan.blocks[1].state.properties["facing"], "north");
    assert!(
        plan.blocks[1]
            .block_entity
            .as_ref()
            .unwrap()
            .data
            .is_empty()
    );
    let mut disconnected = source.clone();
    disconnected.blocks.remove(0);
    let errors = preflight(&disconnected, &Registry, &options).unwrap_err();
    assert!(
        errors
            .iter()
            .any(|error| error.message.contains("downhill Chute"))
    );
    let mut loaded = source;
    loaded.blocks[1].block_entity.as_mut().unwrap().insert(
        "Item".into(),
        Tag::Compound(Compound::from([(
            "id".into(),
            Tag::String("minecraft:stick".into()),
        )])),
    );
    let errors = preflight(&loaded, &Registry, &options).unwrap_err();
    assert!(
        errors
            .iter()
            .any(|error| error.message.contains("empty Chute"))
    );
}

#[test]
fn complete_horizontal_belt_pastes_without_old_world_metadata() {
    let schematic = belt_fixture();
    for (mirror, turns, facing) in [
        (Mirror::None, 0, "east"),
        (Mirror::None, 1, "south"),
        (Mirror::FrontBack, 1, "north"),
        (Mirror::LeftRight, 2, "west"),
    ] {
        let result = preflight(
            &schematic,
            &Registry,
            &Options {
                mirror,
                quarter_turns: turns,
                ..Options::default()
            },
        )
        .unwrap();
        assert_eq!(result.blocks.len(), 4);
        let start = result
            .blocks
            .iter()
            .find(|b| b.state.properties["part"] == "start")
            .unwrap();
        let step = horizontal_belt_step(&start.state).unwrap();
        for (i, part) in ["start", "middle", "pulley", "end"].into_iter().enumerate() {
            let pos = step.map(|d| d * i as i32);
            let block = result
                .blocks
                .iter()
                .find(|b| b.relative_pos == pos)
                .unwrap();
            assert_eq!(block.state.properties["facing"], facing);
            assert_eq!(block.state.properties["part"], part);
            assert!(block.block_entity.as_ref().unwrap().data.is_empty());
        }
    }
}

#[test]
fn partial_mismatched_or_occupied_belts_never_return_a_plan() {
    for invalid in 0..5 {
        let mut schematic = belt_fixture();
        let message = match invalid {
            0 => {
                schematic.blocks.remove(1);
                "complete horizontal chain"
            }
            1 => {
                schematic.palettes[0][1]
                    .properties
                    .insert("facing".into(), "north".into());
                "complete horizontal chain"
            }
            2 => {
                schematic.palettes[0][1]
                    .properties
                    .insert("waterlogged".into(), "true".into());
                "dry uncased"
            }
            3 => {
                schematic.blocks[0].block_entity.as_mut().unwrap().insert(
                    "Inventory".into(),
                    Tag::Compound(Compound::from([
                        ("PositiveOrder".into(), Tag::Byte(1)),
                        (
                            "Items".into(),
                            Tag::list(TagKind::Compound, vec![Tag::Compound(Compound::new())]),
                        ),
                    ])),
                );
                "empty Belt Inventory"
            }
            _ => {
                schematic.blocks.pop();
                "complete horizontal chain"
            }
        };
        let issues = preflight(&schematic, &Registry, &Options::default()).unwrap_err();
        assert!(
            issues.iter().any(|issue| issue.message.contains(message)),
            "{issues:?}"
        );
    }
}

#[test]
fn generated_fixture_roundtrip_preserves_types_and_source_safe_policy() {
    let s = fixture();
    let root = s.to_compound();
    let bytes = nbt::encode_gzip(&root, &Limits::default()).unwrap();
    let decoded = read_gzip(&bytes, &Limits::default()).unwrap();
    assert_eq!(decoded, s);
    let plan = plan(&decoded).unwrap();
    assert_eq!(plan.blocks.len(), 2);
    assert_eq!(plan.skipped_air, 1);
    assert_eq!(plan.blocks[1].state.properties["waterlogged"], "false");
    let be = plan.blocks[0].block_entity.as_ref().unwrap();
    assert_eq!(be.id, "create:motor");
    assert_eq!(
        be.data,
        Compound::from([("ScrollValue".into(), Tag::Int(128))])
    );
    assert_eq!(plan.notes.len(), 5); // waterlogging plus four explicitly discarded fields.
    assert!(!be.data.contains_key("Source"));
    assert!(!be.data.contains_key("Items"));
    assert_eq!(fixture(), s); // Preflight did not edit the source.
}
#[test]
fn raw_nbt_all_types_and_modified_utf8_roundtrip() {
    let root = Compound::from([
        ("byte".into(), Tag::Byte(-128)),
        ("short".into(), Tag::Short(-30000)),
        ("int".into(), Tag::Int(i32::MIN)),
        ("long".into(), Tag::Long(i64::MAX)),
        ("float".into(), Tag::Float(0x7fc00042)),
        ("double".into(), Tag::Double(0x8000000000000000)),
        ("bytes".into(), Tag::ByteArray(vec![-128, 0, 127])),
        ("ints".into(), Tag::IntArray(vec![-1, 2])),
        ("longs".into(), Tag::LongArray(vec![i64::MIN, 7])),
        ("nul\0Ж😀".into(), Tag::String("A\0Ж😀".into())),
        ("emptytyped".into(), Tag::list(TagKind::Compound, vec![])),
        (
            "nested".into(),
            Tag::list(TagKind::List, vec![Tag::list(TagKind::End, vec![])]),
        ),
    ]);
    let bytes = nbt::encode_named(&root, &Limits::default()).unwrap();
    assert_eq!(nbt::decode_named(&bytes, &Limits::default()).unwrap(), root);
    // Independent Java DataOutputStream.writeUTF vector: NUL is C0 80;
    // supplementary characters are a pair of three-byte UTF-16 encodings.
    assert_eq!(
        nbt::encode_modified_utf8("A\0Ж😀"),
        [
            0x41, 0xc0, 0x80, 0xd0, 0x96, 0xed, 0xa0, 0xbd, 0xed, 0xb8, 0x80
        ]
    );
    assert!(
        nbt::decode_modified_utf8(&[0xed, 0xa0, 0x80])
            .unwrap_err()
            .contains("unpaired")
    );
    assert!(nbt::decode_modified_utf8(&[0xf0, 0x9f, 0x98, 0x80]).is_err());
}
#[test]
fn defaults_air_policy_and_deferred_order_are_explicit() {
    let mut s = fixture();
    s.palettes[0][1].properties.clear();
    s.palettes[0].push(BlockState::new("minecraft:torch"));
    s.blocks.push(Block {
        relative_pos: [0, 0, 1],
        state_index: 3,
        block_entity: None,
    });
    let p = preflight(
        &s,
        &Registry,
        &Options {
            include_air: true,
            ..Options::default()
        },
    )
    .unwrap();
    assert_eq!(p.blocks.len(), 4);
    assert_eq!(p.skipped_air, 0);
    assert_eq!(p.blocks[1].state.properties["axis"], "y");
    assert_eq!(p.blocks.last().unwrap().state.name, "minecraft:torch");
    let mut s = fixture();
    s.palettes[0][1] = state("minecraft:piston", &[("extended", "true")]);
    assert_eq!(
        plan(&s).unwrap().blocks[1].state.properties["extended"],
        "false"
    );
}
#[test]
fn unknowns_are_aggregated_and_unused_palette_entries_are_validated() {
    let mut s = fixture();
    s.palettes[0].push(BlockState::new("addon:missing"));
    s.palettes[0][1]
        .properties
        .insert("axis".into(), "diagonal".into());
    raw_be(&mut s).insert("UnknownConfig".into(), Tag::Int(7));
    let issues = plan(&s).unwrap_err();
    assert_eq!(issues.len(), 3);
    assert!(issues.iter().any(|i| i.message.contains("addon:missing")));
    assert!(issues.iter().any(|i| i.path.ends_with("UnknownConfig")));
    assert!(issues.iter().any(|i| i.message.contains("diagonal")));
}
#[test]
fn invalid_properties_are_not_defaulted_or_normalized_into_acceptance() {
    for (key, value) in [("facing", "east"), ("waterlogged", "maybe")] {
        let mut s = fixture();
        s.palettes[0][1].properties.insert(key.into(), value.into());
        assert!(plan(&s).is_err());
    }
    struct Liar;
    impl Resolver for Liar {
        fn block_schema(&self, _: &BlockState) -> Result<BlockSchema, String> {
            Registry.block_schema(&BlockState::new("minecraft:air"))
        }
    }
    assert!(
        preflight(&fixture(), &Liar, &Options::default())
            .unwrap_err()
            .iter()
            .any(|i| i.message.contains("instead of validating"))
    );
}
#[test]
fn wrong_block_entity_id_types_unknown_fields_and_semantics_reject_whole_plan() {
    for (key, value) in [
        ("id", Tag::String("create:drill".into())),
        ("ScrollValue", Tag::Long(128)),
        ("ScrollValue", Tag::Int(999)),
        ("Unknown", Tag::Byte(1)),
        ("x", Tag::String("17".into())),
    ] {
        let mut s = fixture();
        raw_be(&mut s).insert(key.into(), value);
        assert!(plan(&s).is_err(), "{key}");
    }
    let mut s = fixture();
    s.blocks[1].block_entity = Some(Compound::new());
    assert!(
        plan(&s)
            .unwrap_err()
            .iter()
            .any(|i| i.message.contains("does not support"))
    );
}
#[test]
fn version_entities_transforms_and_random_palettes_fail_explicitly() {
    for version in [0, 3465, 3954, 3956] {
        let mut s = fixture();
        s.data_version = version;
        assert!(plan(&s).unwrap_err()[0].message.contains("no migration"));
    }
    let s = fixture();
    assert!(
        preflight(
            &s,
            &Registry,
            &Options {
                quarter_turns: 4,
                ..Options::default()
            }
        )
        .is_err()
    );
    let mut s = fixture();
    s.palettes.push(s.palettes[0].clone());
    assert!(plan(&s).is_err());
    let mut s = fixture();
    s.entities.push(Compound::from([(
        "nbt".into(),
        Tag::Compound(Compound::from([(
            "id".into(),
            Tag::String("create:super_glue".into()),
        )])),
    )]));
    assert!(
        plan(&s)
            .unwrap_err()
            .iter()
            .any(|i| i.message.contains("create:super_glue"))
    );
}
#[test]
fn bad_structure_shape_indexes_positions_and_aliases_are_rejected() {
    let limits = Limits::default();
    for size in [[0, 2, 2], [-1, 2, 2], [129, 2, 2], [128, 128, 128]] {
        let mut s = fixture();
        s.size = size;
        assert!(Schematic::from_compound(&s.to_compound(), &limits).is_err());
        assert!(plan(&s).is_err());
    }
    let mut s = fixture();
    s.blocks[0].state_index = 99;
    assert!(Schematic::from_compound(&s.to_compound(), &limits).is_err());
    assert!(plan(&s).is_err());
    let mut s = fixture();
    s.blocks[0].relative_pos = [-1, 0, 0];
    assert!(Schematic::from_compound(&s.to_compound(), &limits).is_err());
    assert!(plan(&s).is_err());
    let mut s = fixture();
    s.blocks[1].relative_pos = s.blocks[0].relative_pos;
    assert!(Schematic::from_compound(&s.to_compound(), &limits).is_err());
    assert!(plan(&s).is_err());
    let mut root = fixture().to_compound();
    root.insert("surprise".into(), Tag::Int(1));
    assert!(Schematic::from_compound(&root, &limits).is_err());
    let mut root = fixture().to_compound();
    root.remove("DataVersion");
    assert!(Schematic::from_compound(&root, &limits).is_err());
    let mut root = fixture().to_compound();
    if let Tag::List { values, .. } = root.get_mut("palette").unwrap()
        && let Tag::Compound(c) = &mut values[0]
    {
        c.insert("id".into(), Tag::String("minecraft:air".into()));
    }
    assert!(Schematic::from_compound(&root, &limits).is_err());
}
#[test]
fn every_truncated_prefix_bad_crc_members_and_trailing_nbt_fail() {
    let limits = Limits::default();
    let root = fixture().to_compound();
    let bytes = nbt::encode_gzip(&root, &limits).unwrap();
    for n in 0..bytes.len() {
        assert!(
            nbt::decode_gzip(&bytes[..n], &limits).is_err(),
            "prefix {n}"
        );
    }
    let mut bad = bytes.clone();
    let last = bad.len() - 1;
    bad[last] ^= 1;
    assert!(nbt::decode_gzip(&bad, &limits).is_err());
    let mut bad = bytes.clone();
    bad.extend(&bytes);
    assert!(nbt::decode_gzip(&bad, &limits).is_err());
    let mut bad = bytes;
    bad.push(0);
    assert!(nbt::decode_gzip(&bad, &limits).is_err());
    let mut raw = nbt::encode_named(&root, &limits).unwrap();
    raw.push(0);
    assert!(nbt::decode_named(&raw, &limits).is_err());
    assert!(
        nbt::decode_named(
            &[
                10, 0, 0, 3, 0, 1, b'x', 0, 0, 0, 1, 3, 0, 1, b'x', 0, 0, 0, 2, 0
            ],
            &limits
        )
        .unwrap_err()
        .message
        .contains("duplicate")
    );
    assert!(nbt::decode_named(&[10, 0, 0, 9, 0, 0, 0, 0, 0, 0, 1, 0], &limits).is_err()); // end-tag list of length1.
}
#[test]
fn bounded_decompression_depth_nodes_and_collection_lengths_fail_before_large_allocation() {
    let root = fixture().to_compound();
    let limits = Limits::default();
    let gzip = nbt::encode_gzip(&root, &limits).unwrap();
    for small in [
        Limits {
            max_compressed_bytes: 10,
            ..limits.clone()
        },
        Limits {
            max_uncompressed_bytes: 32,
            ..limits.clone()
        },
        Limits {
            max_depth: 2,
            ..limits.clone()
        },
        Limits {
            max_nodes: 10,
            ..limits.clone()
        },
        Limits {
            max_collection_len: 2,
            ..limits.clone()
        },
        Limits {
            max_string_bytes: 2,
            ..limits.clone()
        },
    ] {
        assert!(nbt::decode_gzip(&gzip, &small).is_err());
    }
    let huge = [10, 0, 0, 7, 0, 0, 0x7f, 0xff, 0xff, 0xff, 0];
    assert!(
        nbt::decode_named(&huge, &limits)
            .unwrap_err()
            .message
            .contains("length exceeds")
    );
    let negative = [10, 0, 0, 7, 0, 0, 0xff, 0xff, 0xff, 0xff, 0];
    assert!(
        nbt::decode_named(&negative, &limits)
            .unwrap_err()
            .message
            .contains("negative")
    );
    let mut nested = Tag::Int(1);
    for _ in 0..70 {
        nested = Tag::Compound(Compound::from([("n".into(), nested)]));
    }
    assert!(nbt::encode_gzip(&Compound::from([("n".into(), nested)]), &limits).is_err());
}
