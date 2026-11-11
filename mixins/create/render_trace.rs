// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

// Test instrumentation of the actual pose used by Horizon's model submit path.
fn create_render_trace(draw: &crate::game::native_block_entity_draw::BlockEntityDraw, model: &str) {
    static TRACE: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
    let processor = model.ends_with("millstone/inner")
        || model.ends_with("encased_fan/propeller")
        || model.ends_with("mechanical_drill/head");
    if !*TRACE.get_or_init(|| std::env::var_os("CREATE_HORIZON_TRACE_POSES").is_some())
        || !processor && draw.game_time % 10 != 0
        || !model.starts_with("create:")
    {
        return;
    }
    if !(model.ends_with("/shaft")
        || model.ends_with("/shaft_half")
        || model.contains("hand_crank/")
        || model.ends_with("gauge/dial")
        || model.contains("_material_"))
        && !processor
    {
        return;
    }
    let matrix = draw.pose().to_cols_array();
    let offset = if model.ends_with("/shaft")
        || model.ends_with("hand_crank/block")
        || model.contains("_material_")
        || model.ends_with("millstone/inner")
    {
        4
    } else {
        8
    };
    let direction: [i8; 3] = std::array::from_fn(|i| matrix[offset + i].round() as i8);
    thread_local! {static LAST:std::cell::RefCell<std::collections::BTreeMap<([i32;3],String,[i8;3]),i64>>=const{std::cell::RefCell::new(std::collections::BTreeMap::new())};}
    let emit = LAST.with(|v| {
        v.borrow_mut()
            .insert((draw.block, model.into(), direction), draw.game_time)
            != Some(draw.game_time)
    });
    if emit {
        log::info!(
            "Create pose: {}",
            serde_json::json!({"pos":draw.block,"model":model,"time":draw.game_time as f64+f64::from(draw.partial),"matrix":matrix,"axis":direction})
        );
    }
}
