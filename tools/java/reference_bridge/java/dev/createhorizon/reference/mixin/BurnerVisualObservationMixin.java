// Copyright (c) 2026 create-horizon contributors; MIT.
package dev.createhorizon.reference.mixin;

import com.simibubi.create.content.processing.burner.BlazeBurnerBlock.HeatLevel;
import com.simibubi.create.content.processing.burner.BlazeBurnerBlockEntity;
import com.simibubi.create.content.processing.burner.BlazeBurnerVisual;
import com.simibubi.create.content.processing.burner.ScrollInstance;
import dev.createhorizon.reference.BurnerRenderObservation;
import dev.engine_room.flywheel.api.visualization.VisualizationContext;
import dev.engine_room.flywheel.lib.instance.TransformedInstance;
import org.spongepowered.asm.mixin.Final;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.Unique;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/** Shadow fields belong to pinned MIT Create, not Flywheel implementation. */
@Mixin(value = BlazeBurnerVisual.class, remap = false)
public abstract class BurnerVisualObservationMixin {
    @Shadow private HeatLevel heatLevel;
    @Shadow @Final private boolean isInert;
    @Shadow private boolean validBlockAbove;
    @Shadow private TransformedInstance goggles;
    @Shadow private TransformedInstance hat;
    @Shadow private TransformedInstance smallRods;
    @Shadow private ScrollInstance flame;
    @Unique private BlazeBurnerBlockEntity create_horizon$observedEntity;

    @Inject(method = "<init>", at = @At("TAIL"), remap = false)
    private void create_horizon$created(VisualizationContext context,
            BlazeBurnerBlockEntity be, float partial, CallbackInfo callback) {
        create_horizon$observedEntity = be;
        create_horizon$record(true);
    }

    @Inject(method = "animate", at = @At("TAIL"), remap = false)
    private void create_horizon$frame(float partial, CallbackInfo callback) {
        create_horizon$record(false);
    }

    @Unique private void create_horizon$record(boolean created) {
        BurnerRenderObservation.visual(create_horizon$observedEntity, created,
                heatLevel, isInert, goggles != null, hat != null,
                smallRods != null, flame != null, validBlockAbove);
    }
}
