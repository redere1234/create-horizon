// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

// Native data maps read explicit world-pack contributions, unlike the ordinary
// content loader's recipes/tags. Supply the actual bundled declarations below
// world packs so their replace/remove rules remain authoritative on reload.
fn create_burner_pack_files(files: &mut Vec<(String, Vec<u8>)>) {
    static MAPS: std::sync::OnceLock<Vec<(String, Vec<u8>)>> = std::sync::OnceLock::new();
    files.extend(
        MAPS.get_or_init(|| {
            let bundled: std::collections::BTreeMap<String, String> = match serde_json::from_slice(
                horizon_client::native_data!("create", "content.json"),
            ) {
                Ok(files) => files,
                Err(error) => {
                    log::error!("Create: bundled data maps could not be decoded: {error}");
                    return Vec::new();
                }
            };
            bundled
                .into_iter()
                .filter_map(|(path, content)| {
                    let path = path
                        .strip_prefix("data/create/data_maps/")?
                        .strip_suffix(".json")?;
                    Some((format!("data_maps/create:{path}"), content.into_bytes()))
                })
                .collect()
        })
        .iter()
        .cloned(),
    );
}
