// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT
// Runs the original actor tick without constructing a GPU-backed instance.
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.lang.reflect.Field;
import java.util.Locale;
import java.util.List;
import java.util.Map;
import com.simibubi.create.content.contraptions.Contraption;
import com.simibubi.create.content.contraptions.actors.harvester.HarvesterActorVisual;
import com.simibubi.create.content.contraptions.bearing.BearingContraption;
import com.simibubi.create.content.contraptions.behaviour.MovementContext;
import com.simibubi.create.content.kinetics.drill.DrillActorVisual;
import net.minecraft.SharedConstants;
import net.minecraft.client.multiplayer.ClientLevel;
import net.minecraft.server.Bootstrap;
import net.minecraft.world.level.Level;
import net.neoforged.fml.loading.LoadingModList;
import com.simibubi.create.content.contraptions.render.ActorVisual;
import net.createmod.catnip.math.AngleHelper;
import net.minecraft.core.Direction;
import net.minecraft.world.phys.Vec3;
import sun.misc.Unsafe;

public class HarvesterBladeOracle {
    private static Field field(Class<?> klass, String name) throws Exception {
        Field f = klass.getDeclaredField(name);
        f.setAccessible(true);
        return f;
    }
    public static void main(String[] args) throws Exception {
        Unsafe unsafe = (Unsafe) field(Unsafe.class, "theUnsafe").get(null);
        boolean drill = args.length > 0 && args[0].equals("drill");
        Class<? extends ActorVisual> actorType = drill ? DrillActorVisual.class : HarvesterActorVisual.class;
        var blade = (ActorVisual) unsafe.allocateInstance(actorType);
        var contraption = (Contraption) unsafe.allocateInstance(BearingContraption.class);
        var context = (MovementContext) unsafe.allocateInstance(MovementContext.class);
        if (drill) {
            // getAnimationSpeed consults the level side. Bootstrap the pinned
            // client classes without starting the game or constructing a level.
            SharedConstants.tryDetectVersion();
            LoadingModList.of(List.of(), List.of(), List.of(), List.of(), Map.of());
            Bootstrap.bootStrap();
            var level = (ClientLevel) unsafe.allocateInstance(ClientLevel.class);
            field(Level.class, "isClientSide").setBoolean(level, true);
            context.world = level;
        }
        context.contraption = contraption;
        field(ActorVisual.class, "context").set(blade, context);
        Field facing = field(actorType, "facing");
        Field previous = field(actorType, "previousRotation");
        Field rotation = field(actorType, "rotation");
        try (var reader = new BufferedReader(new InputStreamReader(System.in))) {
            for (String line; (line = reader.readLine()) != null;) {
                var a = line.split(" ");
                facing.set(blade, Direction.valueOf(a[0].toUpperCase(Locale.ROOT)));
                context.motion = new Vec3(Double.parseDouble(a[1]), Double.parseDouble(a[2]), Double.parseDouble(a[3]));
                context.relativeMotion = new Vec3(Double.parseDouble(a[4]), Double.parseDouble(a[5]), Double.parseDouble(a[6]));
                contraption.stalled = a[7].equals("1");
                context.disabled = a[8].equals("1");
                blade.tick();
                double p = previous.getDouble(blade);
                double r = rotation.getDouble(blade);
                System.out.println(p + " " + r + " " + AngleHelper.angleLerp(0.5, p, r));
            }
        }
    }
}
