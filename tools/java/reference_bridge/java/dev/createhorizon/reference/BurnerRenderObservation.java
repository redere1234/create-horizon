// Copyright (c) 2026 create-horizon contributors; MIT.
// Development observations of MIT Create targets; no render state is changed.
package dev.createhorizon.reference;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.mojang.blaze3d.vertex.DefaultVertexFormat;
import com.mojang.blaze3d.vertex.VertexFormatElement;
import com.simibubi.create.AllPartialModels;
import com.simibubi.create.content.processing.burner.BlazeBurnerBlock.HeatLevel;
import com.simibubi.create.content.processing.burner.BlazeBurnerBlockEntity;
import com.simibubi.create.content.processing.burner.BlazeBurnerRenderer;
import dev.engine_room.flywheel.lib.model.Models;
import dev.engine_room.flywheel.lib.model.baked.PartialModel;
import java.util.ArrayList;
import java.util.TreeSet;
import java.util.WeakHashMap;
import net.minecraft.client.Minecraft;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.util.RandomSource;

/** Bounded to the existing private twelve-frame fixture, never a user world. */
public final class BurnerRenderObservation {
    private static final BlockPos POSITION = new BlockPos(510, 64, 16);
    private static final WeakHashMap<BlazeBurnerBlockEntity, Sample> SAMPLES = new WeakHashMap<>();

    private static final class Sample {
        long rendererCalls, visualCreations, visualFrames;
        String rendererHeat, visualHeat, headSelection;
        int rendererInputLight;
        boolean inert, goggles, hat, rods, flame, above;
    }

    private BurnerRenderObservation() {}

    public static synchronized void renderer(BlazeBurnerBlockEntity be, int inputLight) {
        if (!be.getBlockPos().equals(POSITION)) return;
        Sample sample = SAMPLES.computeIfAbsent(be, key -> new Sample());
        sample.rendererCalls++;
        sample.rendererHeat = be.getHeatLevelFromBlock().name();
        sample.rendererInputLight = inputLight;
    }

    public static synchronized void visual(BlazeBurnerBlockEntity be, boolean created,
            HeatLevel heat, boolean inert, boolean goggles, boolean hat,
            boolean rods, boolean flame, boolean above) {
        if (be == null || !be.getBlockPos().equals(POSITION)) return;
        Sample sample = SAMPLES.computeIfAbsent(be, key -> new Sample());
        if (created) sample.visualCreations++;
        else sample.visualFrames++;
        sample.visualHeat = heat.name();
        sample.inert = inert;
        sample.goggles = goggles;
        sample.hat = hat;
        sample.rods = rods;
        sample.flame = flame;
        sample.above = above;
        // This is the source selection from actual retained fields, not a read
        // of any private Flywheel instance/mesh or a claim about GPU vertices.
        var model = BlazeBurnerRenderer.getBlazeModel(heat, above);
        sample.headSelection = model == AllPartialModels.BLAZE_INERT ? "inert"
                : model == AllPartialModels.BLAZE_IDLE ? "idle"
                : model == AllPartialModels.BLAZE_ACTIVE ? "active"
                : model == AllPartialModels.BLAZE_SUPER ? "super" : "super_active";
    }

    static synchronized JsonObject snapshot(Minecraft mc) {
        JsonObject result = new JsonObject();
        JsonArray pos = new JsonArray();
        pos.add(POSITION.getX()); pos.add(POSITION.getY()); pos.add(POSITION.getZ());
        result.add("pos", pos);
        result.addProperty("scope", "Read-only MIT Create method-entry/retained-field observations; no private Flywheel implementation or GPU-mesh access");
        if (mc.level == null || !(mc.level.getBlockEntity(POSITION) instanceof BlazeBurnerBlockEntity be)) return result;
        Sample sample = SAMPLES.get(be);
        result.addProperty("entity_identity", System.identityHashCode(be));
        result.addProperty("observed", sample != null);
        if (sample == null) return result;
        result.addProperty("renderer_calls", sample.rendererCalls);
        result.addProperty("renderer_heat", sample.rendererHeat);
        result.addProperty("renderer_input_light", sample.rendererInputLight);
        result.addProperty("visual_creations", sample.visualCreations);
        result.addProperty("visual_frames", sample.visualFrames);
        result.addProperty("visual_heat", sample.visualHeat);
        result.addProperty("visual_is_inert", sample.inert);
        result.addProperty("visual_goggles_present", sample.goggles);
        result.addProperty("visual_goggles_selection", sample.inert ? "goggles_small" : "goggles");
        result.addProperty("visual_hat_present", sample.hat);
        result.addProperty("visual_rods_present", sample.rods);
        result.addProperty("visual_flame_present", sample.flame);
        result.addProperty("visual_valid_above", sample.above);
        result.addProperty("head_selection_from_fields", sample.headSelection);
        return result;
    }

    /** One-shot public model/material inspection, never a per-frame renderer. */
    static JsonObject models() {
        PartialModel[] parts = {
            AllPartialModels.BLAZE_INERT, AllPartialModels.BLAZE_IDLE,
            AllPartialModels.BLAZE_ACTIVE, AllPartialModels.BLAZE_SUPER,
            AllPartialModels.BLAZE_SUPER_ACTIVE, AllPartialModels.BLAZE_GOGGLES,
            AllPartialModels.BLAZE_GOGGLES_SMALL, AllPartialModels.BLAZE_BURNER_RODS,
            AllPartialModels.BLAZE_BURNER_RODS_2, AllPartialModels.BLAZE_BURNER_SUPER_RODS,
            AllPartialModels.BLAZE_BURNER_SUPER_RODS_2, AllPartialModels.BLAZE_BURNER_FLAME,
            AllPartialModels.TRAIN_HAT, AllPartialModels.LOGISTICS_HAT
        };
        JsonArray result = new JsonArray();
        var format = DefaultVertexFormat.BLOCK;
        int stride = format.getVertexSize() / 4;
        int colorIndex = format.getOffset(VertexFormatElement.COLOR) / 4;
        int normalIndex = format.getOffset(VertexFormatElement.NORMAL) / 4;
        for (PartialModel part : parts) {
            JsonObject row = new JsonObject();
            row.addProperty("id", part.modelLocation().toString());
            var baked = part.get();
            var quads = new ArrayList<net.minecraft.client.renderer.block.model.BakedQuad>();
            quads.addAll(baked.getQuads(null, null, RandomSource.create(42)));
            for (Direction face : Direction.values())
                quads.addAll(baked.getQuads(null, face, RandomSource.create(42)));
            int shaded = 0, ao = 0;
            TreeSet<String> colors = new TreeSet<>(), normals = new TreeSet<>();
            TreeSet<Integer> tints = new TreeSet<>();
            for (var quad : quads) {
                if (quad.isShade()) shaded++;
                if (quad.hasAmbientOcclusion()) ao++;
                tints.add(quad.getTintIndex());
                int[] vertices = quad.getVertices();
                if (vertices.length != stride * 4)
                    throw new IllegalStateException("Unsupported source quad vertex stride: " + vertices.length);
                for (int vertex = 0; vertex < 4; vertex++) {
                    colors.add(String.format("%08x", vertices[vertex * stride + colorIndex]));
                    normals.add(String.format("%08x", vertices[vertex * stride + normalIndex]));
                }
            }
            row.addProperty("quad_count", quads.size()); row.addProperty("shade_true", shaded);
            row.addProperty("ao_true", ao); row.addProperty("vertex_stride", stride);
            JsonArray colorValues = new JsonArray(), normalValues = new JsonArray(), tintValues = new JsonArray();
            colors.forEach(colorValues::add); normals.forEach(normalValues::add); tints.forEach(tintValues::add);
            row.add("colors", colorValues); row.add("normals", normalValues); row.add("tints", tintValues);
            JsonArray materials = new JsonArray();
            for (var mesh : Models.partial(part).meshes()) {
                var material = mesh.material();
                JsonObject value = new JsonObject();
                value.addProperty("cardinal_lighting", material.cardinalLightingMode().name());
                value.addProperty("use_light", material.useLight());
                value.addProperty("use_overlay", material.useOverlay());
                value.addProperty("ambient_occlusion", material.ambientOcclusion());
                value.addProperty("depth_test", material.depthTest().name());
                value.addProperty("write_mask", material.writeMask().name());
                value.addProperty("transparency", material.transparency().name());
                value.addProperty("cull", material.backfaceCulling());
                value.addProperty("polygon_offset", material.polygonOffset());
                value.addProperty("blur", material.blur()); value.addProperty("mipmap", material.mipmap());
                materials.add(value);
            }
            row.add("public_flywheel_materials", materials);
            result.add(row);
        }
        JsonObject output = new JsonObject();
        output.add("parts", result);
        output.addProperty("scope", "Actual loaded public BakedModel/BakedQuad and public Flywheel Material metadata; no positions/UV/private implementation");
        return output;
    }
}
