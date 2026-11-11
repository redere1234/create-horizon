// Copyright (c) 2026 create-horizon contributors; MIT.
package dev.createhorizon.reference.mixin;

import com.mojang.blaze3d.vertex.PoseStack;
import com.simibubi.create.content.processing.burner.BlazeBurnerBlockEntity;
import com.simibubi.create.content.processing.burner.BlazeBurnerRenderer;
import dev.createhorizon.reference.BurnerRenderObservation;
import net.minecraft.client.renderer.MultiBufferSource;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/** Observe the concrete MIT Create overload; never cancel or alter arguments. */
@Mixin(value = BlazeBurnerRenderer.class, remap = false)
public abstract class BurnerRendererObservationMixin {
    @Inject(method = "renderSafe(Lcom/simibubi/create/content/processing/burner/BlazeBurnerBlockEntity;FLcom/mojang/blaze3d/vertex/PoseStack;Lnet/minecraft/client/renderer/MultiBufferSource;II)V", at = @At("HEAD"), remap = false)
    private void create_horizon$observe(BlazeBurnerBlockEntity be, float partial,
            PoseStack pose, MultiBufferSource buffers, int light, int overlay, CallbackInfo callback) {
        BurnerRenderObservation.renderer(be, light);
    }
}
