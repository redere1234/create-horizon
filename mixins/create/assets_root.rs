// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_assets_root(root: std::path::PathBuf) -> std::path::PathBuf {
    crate::game::create_port::asset_root(root)
}
