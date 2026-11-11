// Copyright (c) 2026 create-horizon contributors; MIT.
package dev.createhorizon.reference.mixin;

import com.simibubi.create.content.contraptions.behaviour.MovementContext;
import com.simibubi.create.content.contraptions.render.ActorVisual;
import com.simibubi.create.content.kinetics.deployer.DeployerActorVisual;
import dev.createhorizon.reference.DeployerActorObservation;
import dev.engine_room.flywheel.api.visualization.VisualizationContext;
import net.minecraft.world.level.BlockAndTintGetter;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

@Mixin(value = DeployerActorVisual.class, remap = false)
public abstract class DeployerActorObservationMixin extends ActorVisual {
    protected DeployerActorObservationMixin(VisualizationContext visualization, BlockAndTintGetter world,
            MovementContext context) {
        super(visualization, world, context);
    }

    @Inject(method = "deploymentDistance()F", at = @At("RETURN"), remap = false)
    private void create_horizon$observe(CallbackInfoReturnable<Float> callback) {
        DeployerActorObservation.frame(context, callback.getReturnValueF());
    }
}
