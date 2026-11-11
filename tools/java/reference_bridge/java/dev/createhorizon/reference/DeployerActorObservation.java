// Copyright (c) 2026 create-horizon contributors; MIT.
package dev.createhorizon.reference;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.simibubi.create.content.contraptions.behaviour.MovementContext;
import java.util.ArrayDeque;
import net.createmod.catnip.animation.AnimationTickHolder;
import net.minecraft.core.BlockPos;
import net.minecraft.world.phys.Vec3;

/** Frame observations from the private moving Deployer fixture. */
public final class DeployerActorObservation {
    private static final BlockPos ANCHOR = new BlockPos(1448, 149, 150);
    private static final ArrayDeque<JsonObject> FRAMES = new ArrayDeque<>();
    private static final int LIMIT = 1024;

    private DeployerActorObservation() {}

    public static void frame(MovementContext context, float extension) {
        if (context.contraption.entity == null
                || !BlockPos.containing(context.contraption.entity.getAnchorVec()).equals(ANCHOR)) return;
        JsonObject row = new JsonObject();
        row.addProperty("extension", extension);
        row.addProperty("stalled", context.contraption.stalled);
        row.addProperty("stationary_timer", context.data.contains("StationaryTimer"));
        row.addProperty("disabled", context.disabled);
        row.addProperty("render_time", AnimationTickHolder.getRenderTime());
        row.addProperty("partial", AnimationTickHolder.getPartialTicks());
        row.add("position", vector(context.position));
        row.add("motion", vector(context.motion));
        synchronized (FRAMES) {
            if (FRAMES.size() == LIMIT) FRAMES.removeFirst();
            FRAMES.addLast(row);
        }
    }

    private static JsonArray vector(Vec3 vector) {
        if (vector == null) return null;
        JsonArray values = new JsonArray();
        values.add(vector.x);
        values.add(vector.y);
        values.add(vector.z);
        return values;
    }

    static JsonObject snapshot() {
        JsonArray frames = new JsonArray();
        synchronized (FRAMES) {
            FRAMES.forEach(frames::add);
            FRAMES.clear();
        }
        JsonObject output = new JsonObject();
        output.add("frames", frames);
        return output;
    }
}
