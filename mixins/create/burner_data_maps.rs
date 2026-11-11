// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn burner_data_maps(types: &mut Vec<crate::mod_api::NativeDataMapType>) {
    for id in [
        "create:regular_blaze_burner_fuels",
        "create:superheated_blaze_burner_fuels",
    ] {
        if !types
            .iter()
            .any(|v| v.id == id && v.registry == "minecraft:item")
        {
            types.push(crate::mod_api::NativeDataMapType {
                id: id.into(),
                registry: "minecraft:item".into(),
            });
        }
    }
}
