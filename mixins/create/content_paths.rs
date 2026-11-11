// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn create_content_paths(enabled: &std::collections::BTreeSet<String>) {
    crate::game::create_port::prepare_content(enabled);
}
