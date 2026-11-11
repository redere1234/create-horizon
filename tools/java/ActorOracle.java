// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

import com.simibubi.create.AllTags.AllBlockTags;
import com.simibubi.create.content.kinetics.saw.TreeCutter;
import java.lang.reflect.Proxy;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Scanner;
import net.createmod.catnip.math.VecHelper;
import net.minecraft.SharedConstants;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.server.Bootstrap;
import net.minecraft.tags.BlockTags;
import net.minecraft.world.level.BlockGetter;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.LeavesBlock;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.Vec3;
import net.neoforged.fml.loading.LoadingModList;

@SuppressWarnings("deprecation")
public class ActorOracle {
    private static BlockState block(String type) {
        return switch (type) {
            case "O" -> Blocks.OAK_LOG.defaultBlockState();
            case "R" -> Blocks.MANGROVE_ROOTS.defaultBlockState();
            case "A" -> Blocks.BEE_NEST.defaultBlockState();
            case "C" -> Blocks.CACTUS.defaultBlockState();
            case "K" -> Blocks.KELP_PLANT.defaultBlockState();
            case "H" -> Blocks.CHORUS_FLOWER.defaultBlockState();
            case "P" -> Blocks.CHORUS_PLANT.defaultBlockState();
            case "M" -> Blocks.RED_MUSHROOM_BLOCK.defaultBlockState();
            case "N" -> Blocks.BROWN_MUSHROOM_BLOCK.defaultBlockState();
            default -> Blocks.OAK_LEAVES.defaultBlockState()
                .setValue(LeavesBlock.DISTANCE, Integer.parseInt(type));
        };
    }

    public static void main(String[] args) throws Exception {
        LoadingModList.of(List.of(), List.of(), List.of(), List.of(), Map.of());
        SharedConstants.tryDetectVersion();
        Bootstrap.bootStrap();
        BuiltInRegistries.BLOCK.bindTags(Map.of(
            BlockTags.LOGS, List.of(Blocks.OAK_LOG.builtInRegistryHolder()),
            AllBlockTags.ROOTS.tag, List.of(Blocks.MANGROVE_ROOTS.builtInRegistryHolder()),
            AllBlockTags.TREE_ATTACHMENTS.tag, List.of(Blocks.BEE_NEST.builtInRegistryHolder())
        ));

        try (var scanner = new Scanner(System.in).useLocale(Locale.ROOT)) {
            while (scanner.hasNext()) {
                String kind = scanner.next();
                if (kind.equals("F")) {
                    Direction facing = Direction.valueOf(scanner.next().toUpperCase(Locale.ROOT));
                    Vec3 motion = new Vec3(scanner.nextDouble(), scanner.nextDouble(), scanner.nextDouble());
                    System.out.println(!VecHelper.isVecPointingTowards(motion, facing.getOpposite()));
                    continue;
                }
                BlockState broken = block(kind);
                int count = scanner.nextInt();
                Map<BlockPos, BlockState> states = new HashMap<>();
                for (int i = 0; i < count; ++i) {
                    var position = new BlockPos(scanner.nextInt(), scanner.nextInt(), scanner.nextInt());
                    states.put(position, block(scanner.next()));
                }
                BlockGetter world = (BlockGetter) Proxy.newProxyInstance(
                    ActorOracle.class.getClassLoader(), new Class[]{BlockGetter.class}, (object, method, arguments) -> {
                        return switch (method.getName()) {
                            case "getHeight" -> 384;
                            case "getBlockState" -> states.getOrDefault((BlockPos) arguments[0], Blocks.AIR.defaultBlockState());
                            default -> throw new UnsupportedOperationException(method.getName());
                        };
                    }
                );
                var plan = TreeCutter.findTree(world, BlockPos.ZERO, broken);
                for (String name : List.of("logs", "leaves", "attachments")) {
                    var field = plan.getClass().getDeclaredField(name);
                    field.setAccessible(true);
                    System.out.print(name + "=");
                    for (Object entry : (List<?>) field.get(plan)) {
                        BlockPos p = (BlockPos) entry;
                        System.out.print(p.getX() + "," + p.getY() + "," + p.getZ() + ";");
                    }
                    System.out.print(" ");
                }
                System.out.println();
            }
        }
    }
}
