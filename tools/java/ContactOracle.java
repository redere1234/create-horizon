// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

import com.simibubi.create.foundation.collision.CollisionList;
import com.simibubi.create.foundation.collision.ContinuousOBBCollider;
import com.simibubi.create.foundation.collision.OrientedBB;
import java.util.Locale;
import java.util.Scanner;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.Vec3;

public class ContactOracle {
    public static void main(String[] args) {
        CollisionList shapes = new CollisionList();
        var add = new CollisionList.Populate(shapes);
        add.consume(0, 0.375, 0.375, 0.75, 0.625, 0.625);
        add.consume(0.75, 0, 0, 1, 1, 1);
        add.consume(1, 0, 0, 2, 1, 1);
        CollisionList candidates = new CollisionList();

        try (Scanner input = new Scanner(System.in).useLocale(Locale.ROOT)) {
            while (input.hasNextDouble()) {
                double x = input.nextDouble();
                double y = input.nextDouble();
                double z = input.nextDouble();
                AABB box = new AABB(x - 0.3, y, z - 0.3, x + 0.3, y + 1.675, z + 0.3);
                OrientedBB body = new OrientedBB(box.inflate(1e-7));
                Vec3 response = ContinuousOBBCollider
                    .collideMany(shapes, candidates, body, Vec3.ZERO, 0.6f, true)
                    .collisionResponse;
                System.out.printf(Locale.ROOT, "contact %s %s %s%n", response.x, response.y, response.z);
            }
        }
    }
}
