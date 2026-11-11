// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

use crate::containers::ModRevision;

pub(super) trait EntityRevision {
    fn is_same_create_entity(self, other: ModRevision) -> bool;
}

impl EntityRevision for ModRevision {
    fn is_same_create_entity(self, other: ModRevision) -> bool {
        self.__horizon_mixins_create_block_entity_identity()
            == other.__horizon_mixins_create_block_entity_identity()
    }
}
