// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

import com.simibubi.create.foundation.collision.CollisionList;
import com.simibubi.create.foundation.collision.ContinuousOBBCollider;
import com.simibubi.create.foundation.collision.Matrix3d;
import com.simibubi.create.foundation.collision.OrientedBB;
import net.createmod.catnip.math.AngleHelper;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;

import java.util.Locale;
import java.util.Scanner;

public class RotaryContactOracle {
    public static void main(String[] args) {
        CollisionList shapes = new CollisionList();
        var add = new CollisionList.Populate(shapes);
        add.consume(0, 0, 0, 1, 1, 1);
        add.consume(1, 0, 0, 2, 1, 1);
        add.consume(1, 1, -1, 2, 2, 0);
        CollisionList candidates = new CollisionList();
        Vec3 pivot = new Vec3(.5, .5, .5);
        try (Scanner input = new Scanner(System.in).useLocale(Locale.ROOT)) {
            while (input.hasNextInt()) {
                int axis = input.nextInt();
                float angle = input.nextFloat();
                double x = input.nextDouble();
                double y = input.nextDouble();
                double z = input.nextDouble();
                Vec3 velocity = new Vec3(input.nextDouble(), input.nextDouble(), input.nextDouble());
                AABB bounds = new AABB(x - .3, y, z - .3, x + .3, y + 1.8, z + .3);
                Matrix3d matrix = new Matrix3d();
                float radians = AngleHelper.rad(-angle);
                switch (axis) {
                    case 0 -> matrix.asXRotation(radians);
                    case 1 -> matrix.asYRotation(radians);
                    case 2 -> matrix.asZRotation(radians);
                    default -> throw new IllegalArgumentException("Unknown axis " + axis);
                }
                Vec3 center = bounds.getCenter();
                Vec3 local = matrix.transform(center.subtract(pivot)).add(pivot);
                OrientedBB body = new OrientedBB(bounds.contract(0, 2 / 16f, 0)
                    .move(local.subtract(center)).inflate(1e-7));
                body.setRotation(matrix);
                var result = ContinuousOBBCollider.collideMany(shapes, candidates, body,
                    matrix.transform(velocity), .6f, axis == 1);
                Vec3 world = matrix.transformTransposed(result.collisionResponse);
                System.out.printf(Locale.ROOT, "contact %s %s %s %s %d%n", world.x, world.y,
                    world.z, result.temporalResponse, result.surfaceCollision ? 1 : 0);
            }
        }
    }
}
