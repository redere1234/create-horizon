// Copyright (c) 2026 create-horizon contributors
// World/frame integration adapted from Horizon NeoForgeBench (MIT),
// Copyright (c) 2026 Ludovic Marie and the Horizon contributors.
// Full notice: META-INF/LICENSE. Development only; no shipped Java runtime.
package dev.createhorizon.reference;

import com.google.gson.*;
import com.mojang.blaze3d.platform.NativeImage;
import com.simibubi.create.AllDataComponents;
import com.simibubi.create.content.schematics.SchematicItem;
import com.simibubi.create.content.schematics.packet.SchematicPlacePacket;
import com.simibubi.create.foundation.utility.CreatePaths;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.*;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.Supplier;
import net.minecraft.SharedConstants;
import net.minecraft.client.KeyMapping;
import net.minecraft.client.Minecraft;
import net.minecraft.client.Screenshot;
import net.minecraft.client.gui.screens.TitleScreen;
import net.minecraft.commands.CommandSource;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.core.registries.Registries;
import net.minecraft.nbt.*;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.server.level.ServerPlayer;
import net.minecraft.world.Difficulty;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.level.*;
import net.minecraft.world.level.block.Mirror;
import net.minecraft.world.level.block.Rotation;
import net.minecraft.world.level.block.entity.BlockEntity;
import net.minecraft.world.level.block.entity.TickingBlockEntity;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.level.block.state.properties.Property;
import net.minecraft.world.level.levelgen.WorldOptions;
import net.minecraft.world.level.levelgen.presets.WorldPresets;
import net.minecraft.world.phys.Vec3;
import net.neoforged.api.distmarker.Dist;
import net.neoforged.fml.common.Mod;
import net.neoforged.neoforge.client.event.ClientTickEvent;
import net.neoforged.neoforge.client.event.RenderFrameEvent;
import net.neoforged.neoforge.common.NeoForge;
import net.neoforged.neoforge.event.tick.ServerTickEvent;
import org.lwjgl.glfw.GLFW;

@Mod(value = "create_reference_bridge", dist = Dist.CLIENT)
public final class ReferenceBridge {
    private static final Gson JSON = new GsonBuilder().disableHtmlEscaping().create();
    private final Path root;
    private final String token;
    private final String world;
    private final long seed;
    private final boolean normalWorld;
    private final Queue<FrameJob> frameJobs = new ConcurrentLinkedQueue<>();
    private final Queue<KeyMapping> release = new ConcurrentLinkedQueue<>();
    // Short presses belong to the simulation clock, even when a frame stalls.
    private KeyMapping pendingTap;
    private KeyMapping activeTap;
    private volatile long frames;
    private volatile double frameMs;
    private long previousFrame;
    private boolean opened;
    private final HttpServer http;
    // Server-thread-only observation state; no gameplay methods are replaced.
    private TickObservation tickObservation;

    private static final class TickObservation {
        final ServerLevel level;
        final List<BlockPos> positions;
        final JsonArray samples = new JsonArray();
        final CompletableFuture<JsonObject> result = new CompletableFuture<>();
        final int requested;
        final boolean includeTickerOrder;
        long previousTime;
        int remaining;
        TickObservation(ServerLevel level, List<BlockPos> positions, int ticks, boolean includeTickerOrder) {
            this.level = level; this.positions = positions; this.requested = ticks;
            this.includeTickerOrder = includeTickerOrder;
            this.remaining = ticks; this.previousTime = level.getGameTime();
        }
    }

    private record FrameJob(long after, JsonObject body, CompletableFuture<JsonObject> result) {}

    public ReferenceBridge() throws IOException {
        String configName = System.getProperty("create.reference.config");
        if (configName == null) throw new IllegalStateException("Reference bridge requires its isolated configuration");
        JsonObject config = JsonParser.parseString(Files.readString(Path.of(configName))).getAsJsonObject();
        root = Path.of(config.get("root").getAsString()).toAbsolutePath().normalize();
        token = config.get("token").getAsString();
        normalWorld = Boolean.getBoolean("create.reference.normal_world");
        world = config.get("world").getAsString() + (normalWorld ? "Normal" : "");
        seed = config.get("seed").getAsLong();
        http = HttpServer.create(new InetSocketAddress("127.0.0.1", config.get("port").getAsInt()), 8);
        http.setExecutor(Executors.newFixedThreadPool(4, r -> {
            Thread t = new Thread(r, "Create reference HTTP"); t.setDaemon(true); return t;
        }));
        http.createContext("/", this::request);
        http.start();
        JsonObject ready = object("url", "http://127.0.0.1:" + http.getAddress().getPort());
        ready.addProperty("minecraft", "1.21.1"); ready.addProperty("create", "6.0.10");
        ready.addProperty("data_version", SharedConstants.getCurrentVersion().getDataVersion().getVersion());
        Files.writeString(root.resolve("ready.json"), JSON.toJson(ready));
        NeoForge.EVENT_BUS.addListener(RenderFrameEvent.Pre.class, event -> beforeFrame(Minecraft.getInstance()));
        NeoForge.EVENT_BUS.addListener(RenderFrameEvent.Post.class, event -> afterFrame(Minecraft.getInstance()));
        NeoForge.EVENT_BUS.addListener(ClientTickEvent.Pre.class, event -> beginTap());
        NeoForge.EVENT_BUS.addListener(ClientTickEvent.Post.class, event -> endTap());
        NeoForge.EVENT_BUS.addListener(ServerTickEvent.Post.class, event -> observeServerTick(event.getServer()));
        Runtime.getRuntime().addShutdownHook(new Thread(() -> http.stop(0)));
    }

    private static JsonObject object(String key, String value) {
        JsonObject result = new JsonObject(); result.addProperty(key, value); return result;
    }
    private static int integer(JsonObject body, String key, int fallback) {
        return body.has(key) ? body.get(key).getAsInt() : fallback;
    }
    private static boolean flag(JsonObject body, String key, boolean fallback) {
        return body.has(key) ? body.get(key).getAsBoolean() : fallback;
    }
    private static String string(JsonObject body, String key, String fallback) {
        return body.has(key) ? body.get(key).getAsString() : fallback;
    }
    private static JsonArray vector(double... values) {
        JsonArray result = new JsonArray(); for (double value : values) result.add(value); return result;
    }
    private static Vec3 vec(JsonObject body, String key) {
        JsonArray values = body.getAsJsonArray(key);
        if (values == null || values.size() != 3) throw new IllegalArgumentException(key + " requires three coordinates");
        return new Vec3(values.get(0).getAsDouble(), values.get(1).getAsDouble(), values.get(2).getAsDouble());
    }
    private static BlockPos pos(JsonObject body, String key) {
        Vec3 p = vec(body, key);
        for(double value:new double[]{p.x,p.y,p.z}) {
            if(!Double.isFinite(value)||value!=Math.rint(value)||value<Integer.MIN_VALUE||value>Integer.MAX_VALUE)
                throw new IllegalArgumentException(key + " requires integer block coordinates");
        }
        return new BlockPos((int)p.x, (int)p.y, (int)p.z);
    }
    private static <T> T await(CompletableFuture<T> future) throws Exception {
        return future.get(60, TimeUnit.SECONDS);
    }
    private static <T> CompletableFuture<T> client(Supplier<T> action) {
        CompletableFuture<T> future = new CompletableFuture<>();
        Minecraft.getInstance().execute(() -> {
            try {future.complete(action.get());} catch (Throwable error) {future.completeExceptionally(error);}
        });
        return future;
    }
    private static MinecraftServer server() {
        MinecraftServer result = Minecraft.getInstance().getSingleplayerServer();
        if (result == null || !result.isReady()) throw new IllegalStateException("The reference integrated world is not ready");
        return result;
    }
    private static ServerPlayer player(MinecraftServer server) {
        if (server.getPlayerList().getPlayers().isEmpty()) throw new IllegalStateException("The reference player is not ready");
        return server.getPlayerList().getPlayers().getFirst();
    }

    private void request(HttpExchange exchange) throws IOException {
        try {
            byte[] received = Optional.ofNullable(exchange.getRequestHeaders().getFirst("Authorization")).orElse("").getBytes(StandardCharsets.UTF_8);
            byte[] expected = ("Bearer " + token).getBytes(StandardCharsets.UTF_8);
            if (!MessageDigest.isEqual(received, expected)) {reply(exchange, 403, object("error", "Local bridge authorization required")); return;}
            if (!exchange.getRequestMethod().equals("POST")) {reply(exchange, 405, object("error", "Use POST JSON")); return;}
            byte[] bytes = exchange.getRequestBody().readNBytes(1024 * 1024 + 1);
            if (bytes.length > 1024 * 1024) throw new IllegalArgumentException("Request exceeds one MiB");
            JsonObject body = bytes.length == 0 ? new JsonObject() : JsonParser.parseString(new String(bytes, StandardCharsets.UTF_8)).getAsJsonObject();
            JsonObject result = dispatch(exchange.getRequestURI().getPath(), body);
            reply(exchange, 200, result);
        } catch (Throwable error) {
            while ((error instanceof ExecutionException || error instanceof CompletionException) && error.getCause() != null) error = error.getCause();
            reply(exchange, 400, object("error", error.getClass().getSimpleName() + ": " + error.getMessage()));
        }
    }

    private static void reply(HttpExchange exchange, int status, JsonObject result) throws IOException {
        byte[] bytes = JSON.toJson(result).getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        exchange.sendResponseHeaders(status, bytes.length);
        try (OutputStream out = exchange.getResponseBody()) {out.write(bytes);}
    }

    private JsonObject dispatch(String path, JsonObject body) throws Exception {
        return switch (path) {
            case "/state" -> state();
            case "/ui" -> await(client(Observations::ui));
            case "/burner_models" -> await(client(BurnerRenderObservation::models));
            case "/deployer_actor_frames" -> DeployerActorObservation.snapshot();
            case "/particles" -> await(client(() -> Observations.particles(body)));
            case "/damage" -> await(server().submit(() -> Observations.damage(server(), body)));
            case "/entities" -> await(server().submit(() -> Observations.entities(player(server()).serverLevel(), body)));
            case "/command" -> await(server().submit(() -> command(server(), body.get("command").getAsString())));
            case "/block" -> await(server().submit(() -> block(body)));
            case "/ticker_order" -> await(server().submit(() -> tickerOrder(player(server()).serverLevel(), observationPositions(body))));
            case "/camera" -> camera(body);
            case "/tick" -> ticks(body);
            case "/observe_ticks" -> observeTicks(body);
            case "/capture" -> capture(body);
            case "/input" -> await(client(() -> input(body)));
            case "/language" -> language(body);
            case "/schematic" -> await(server().submit(() -> schematic(body)));
            case "/quit" -> {client(() -> {Minecraft.getInstance().stop(); return null;}); yield object("status", "stopping");}
            default -> throw new IllegalArgumentException("Unknown reference method " + path);
        };
    }

    private void beforeFrame(Minecraft mc) {
        long now = System.nanoTime();
        frameMs = previousFrame == 0 ? 0 : (now - previousFrame) / 1e6;
        previousFrame = now;
        if (!opened && mc.screen instanceof TitleScreen && mc.getOverlay() == null) {
            opened = true;
            mc.options.pauseOnLostFocus = false;
            Path save = mc.gameDirectory.toPath().resolve("saves").resolve(world).resolve("level.dat");
            if (Files.isRegularFile(save)) {
                mc.createWorldOpenFlows().openWorld(world, () -> {});
            } else {
                LevelSettings settings = new LevelSettings(world, GameType.CREATIVE, false, Difficulty.PEACEFUL,
                    true, new GameRules(), WorldDataConfiguration.DEFAULT);
                var preset = normalWorld ? WorldPresets.NORMAL : WorldPresets.FLAT;
                mc.createWorldOpenFlows().createFreshLevel(world, settings, new WorldOptions(seed, normalWorld, false),
                    access -> access.registryOrThrow(Registries.WORLD_PRESET).getHolderOrThrow(preset).value().createWorldDimensions(), mc.screen);
            }
        }
    }

    private void afterFrame(Minecraft mc) {
        frames++;
        KeyMapping key;
        while ((key = release.poll()) != null) key.setDown(false);
        int count = frameJobs.size();
        for (int i = 0; i < count; i++) {
            FrameJob job = frameJobs.poll();
            if (job == null) break;
            if (frames < job.after()) {frameJobs.add(job); continue;}
            try {
                String filename = string(job.body(), "name", "reference-" + frames + ".png");
                Path destination = bounded("captures", filename);
                if (!filename.endsWith(".png")) throw new IllegalArgumentException("Capture requires a .png filename");
                Files.createDirectories(destination.getParent());
                int width, height;
                try (NativeImage image = Screenshot.takeScreenshot(mc.getMainRenderTarget())) {
                    width = image.getWidth(); height = image.getHeight(); image.writeToFile(destination);
                }
                JsonObject result = object("path", destination.toString());
                result.addProperty("width", width); result.addProperty("height", height);
                result.addProperty("frame", frames); result.add("client", clientState(mc));
                job.result().complete(result);
            } catch (Throwable error) {job.result().completeExceptionally(error);}
        }
    }

    private JsonObject clientState(Minecraft mc) {
        JsonObject result = new JsonObject();
        result.addProperty("ready", mc.level != null && mc.player != null && mc.screen == null && mc.getOverlay() == null);
        result.addProperty("screen", mc.screen == null ? "playing" : mc.screen.getClass().getSimpleName());
        result.addProperty("screen_title", mc.screen == null ? "" : mc.screen.getTitle().getString());
        result.addProperty("language", mc.getLanguageManager().getSelected());
        result.addProperty("fps", mc.getFps()); result.addProperty("frame", frames); result.addProperty("frame_ms", frameMs);
        result.addProperty("gui_scale", mc.options.guiScale().get()); result.addProperty("fov", mc.options.fov().get());
        result.add("gui_size", vector(mc.getWindow().getGuiScaledWidth(), mc.getWindow().getGuiScaledHeight()));
        result.add("framebuffer_size", vector(mc.getWindow().getWidth(), mc.getWindow().getHeight()));
        result.addProperty("data_version", SharedConstants.getCurrentVersion().getDataVersion().getVersion());
        result.add("render_backend", renderBackend(mc));
        result.add("burner_render_observation", BurnerRenderObservation.snapshot(mc));
        if (mc.player != null) {
            result.add("position", vector(mc.player.getX(), mc.player.getY(), mc.player.getZ()));
            result.addProperty("yaw", mc.player.getYRot()); result.addProperty("pitch", mc.player.getXRot());
            result.addProperty("dimension", mc.player.level().dimension().location().toString());
            result.addProperty("held", BuiltInRegistries.ITEM.getKey(mc.player.getMainHandItem().getItem()).toString());
            result.addProperty("head", BuiltInRegistries.ITEM.getKey(mc.player.getItemBySlot(net.minecraft.world.entity.EquipmentSlot.HEAD).getItem()).toString());
            result.add("hit", Observations.hit(mc));
            result.addProperty("chunks", mc.level.getChunkSource().getLoadedChunksCount());
        }
        return result;
    }

    /** Read-only public Flywheel/vanilla registration observations, not a render override. */
    @SuppressWarnings({"rawtypes", "unchecked"})
    private static JsonObject renderBackend(Minecraft mc) {
        JsonObject result = new JsonObject();
        var backend = dev.engine_room.flywheel.api.backend.BackendManager.currentBackend();
        var id = dev.engine_room.flywheel.api.backend.Backend.REGISTRY.getId(backend);
        result.addProperty("backend", id == null ? "unregistered" : id.toString());
        result.addProperty("backend_on", dev.engine_room.flywheel.api.backend.BackendManager.isBackendOn());
        result.addProperty("backend_supported", backend.isSupported());
        boolean supported = mc.level != null && dev.engine_room.flywheel.api.visualization.VisualizationManager.supportsVisualization(mc.level);
        result.addProperty("supports_visualization", supported);
        if (supported) {
            var manager = dev.engine_room.flywheel.api.visualization.VisualizationManager.get(mc.level);
            if (manager != null) result.addProperty("block_entity_visual_count", manager.blockEntities().visualCount());
        }
        result.addProperty("individual_visual_scope", "Public API exposes no per-block-entity visual lookup; registered visualizer and skip policy only");
        if (mc.level != null && mc.hitResult instanceof net.minecraft.world.phys.BlockHitResult hit) {
            var be = mc.level.getBlockEntity(hit.getBlockPos());
            if (be != null) {
                result.addProperty("hit_block_entity", BuiltInRegistries.BLOCK_ENTITY_TYPE.getKey(be.getType()).toString());
                var renderer = mc.getBlockEntityRenderDispatcher().getRenderer(be);
                result.addProperty("vanilla_renderer_class", renderer == null ? "none" : renderer.getClass().getName());
                var visualizer = dev.engine_room.flywheel.api.visualization.VisualizerRegistry.getVisualizer((net.minecraft.world.level.block.entity.BlockEntityType) be.getType());
                result.addProperty("visualizer_class", visualizer == null ? "none" : visualizer.getClass().getName());
                if (visualizer != null) result.addProperty("skip_vanilla_render", visualizer.skipVanillaRender(be));
            }
        }
        return result;
    }

    private JsonObject state() throws Exception {
        JsonObject result = await(client(() -> clientState(Minecraft.getInstance())));
        MinecraftServer server = Minecraft.getInstance().getSingleplayerServer();
        if (server != null && server.isReady()) {
            JsonObject world = await(server.submit(() -> {
                JsonObject value = new JsonObject();
                value.addProperty("game_time", server.overworld().getGameTime());
                value.addProperty("day_time", server.overworld().getDayTime());
                value.addProperty("server_tick", server.getTickCount());
                value.addProperty("frozen", server.tickRateManager().isFrozen());
                value.addProperty("players", server.getPlayerList().getPlayerCount());
                return value;
            }));
            result.add("server", world);
        }
        return result;
    }

    private JsonObject command(MinecraftServer server, String text) {
        JsonArray messages = new JsonArray();
        CommandSource capture = new CommandSource() {
            public void sendSystemMessage(Component message) {messages.add(message.getString());}
            public boolean acceptsSuccess() {return true;}
            public boolean acceptsFailure() {return true;}
            public boolean shouldInformAdmins() {return false;}
        };
        var source = server.createCommandSourceStack().withSource(capture).withPermission(4);
        if (!server.getPlayerList().getPlayers().isEmpty()) {
            var player = player(server);
            source = source.withEntity(player).withPosition(player.position()).withLevel(player.serverLevel());
        }
        server.getCommands().performPrefixedCommand(source, text.startsWith("/") ? text.substring(1) : text);
        JsonObject result = object("command", text); result.add("messages", messages);
        result.addProperty("game_time", server.overworld().getGameTime()); return result;
    }

    private JsonObject block(JsonObject body) {
        MinecraftServer server = server(); ServerLevel level = player(server).serverLevel();
        BlockPos position = pos(body, "pos");
        JsonObject result = blockAt(level, position);
        if (flag(body, "default_state", false)) {
            result.add("default_properties", properties(level.getBlockState(position).getBlock().defaultBlockState()));
        }
        return result;
    }

    private static JsonObject properties(BlockState state) {
        JsonObject result = new JsonObject();
        state.getValues().forEach((key, value) -> result.addProperty(key.getName(), value.toString()));
        return result;
    }

    private static JsonObject blockAt(ServerLevel level, BlockPos pos) {
        BlockState state = level.getBlockState(pos);
        JsonObject result = object("id", BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString());
        result.add("pos", vector(pos.getX(), pos.getY(), pos.getZ()));
        result.add("properties", properties(state));
        BlockEntity entity = level.getBlockEntity(pos);
        if (entity != null) result.addProperty("nbt", entity.saveWithFullMetadata(level.registryAccess()).toString());
        return result;
    }

    private static List<BlockPos> observationPositions(JsonObject body) {
        JsonArray raw = body.getAsJsonArray("positions");
        if (raw == null || raw.isEmpty() || raw.size() > 32) throw new IllegalArgumentException("Provide1..32 block positions");
        List<BlockPos> positions = new ArrayList<>();
        for (JsonElement entry : raw) {
            JsonObject holder = new JsonObject(); holder.add("pos", entry);
            positions.add(pos(holder, "pos"));
        }
        return positions;
    }

    // Development-only observer: inspect vanilla's actual lists without sorting,
    // inserting, removing, or invoking a block-entity ticker.
    private static JsonObject tickerOrder(ServerLevel level, List<BlockPos> positions) {
        JsonObject result = object("mode", "read-only Level ticker lists on the server thread");
        result.addProperty("game_time", level.getGameTime());
        Set<BlockPos> selected = new HashSet<>(positions);
        for (String name : List.of("blockEntityTickers", "pendingBlockEntityTickers")) {
            JsonArray rows = new JsonArray();
            try {
                var field = Level.class.getDeclaredField(name);
                field.setAccessible(true);
                if (!(field.get(level) instanceof List<?> tickers)) throw new IllegalStateException("Not a ticker list: " + name);
                for (int index = 0; index < tickers.size(); index++) {
                    if (!(tickers.get(index) instanceof TickingBlockEntity ticker)) throw new IllegalStateException("Unknown ticker entry: " + name);
                    BlockPos position = ticker.getPos();
                    if (!selected.contains(position)) continue;
                    JsonObject row = object("type", ticker.getType());
                    row.add("pos", vector(position.getX(), position.getY(), position.getZ()));
                    row.addProperty("index", index);
                    row.addProperty("removed", ticker.isRemoved());
                    rows.add(row);
                }
            } catch (ReflectiveOperationException error) {
                throw new IllegalStateException("Cannot observe " + name, error);
            }
            result.add(name, rows);
        }
        return result;
    }

    private JsonObject observeTicks(JsonObject body) throws Exception {
        MinecraftServer server = server();
        int count = integer(body, "ticks", 1);
        if (count < 1 || count > 400) throw new IllegalArgumentException("Observation range is1..400 ticks");
        List<BlockPos> positions = observationPositions(body);
        JsonArray commands = body.has("commands") ? body.getAsJsonArray("commands") : new JsonArray();
        if (commands.size() > 16) throw new IllegalArgumentException("At most16 setup commands");
        for (JsonElement entry : commands) if (!entry.isJsonPrimitive() || !entry.getAsJsonPrimitive().isString()
                || entry.getAsString().length() > 4096) throw new IllegalArgumentException("Commands must be bounded strings");
        if (!await(client(() -> clientState(Minecraft.getInstance()).get("ready").getAsBoolean())))
            throw new IllegalStateException("Close screens before observing normal server ticks");
        TickObservation job = await(server.submit(() -> {
            if (tickObservation != null) throw new IllegalStateException("An observation is already active");
            if (!server.tickRateManager().isFrozen()) throw new IllegalStateException("Freeze before starting an observation");
            ServerLevel level = player(server).serverLevel();
            for (BlockPos position : positions) if (!level.hasChunkAt(position))
                throw new IllegalArgumentException("Observation position is not loaded: " + position);
            for (JsonElement entry : commands) command(server, entry.getAsString());
            TickObservation next = new TickObservation(level, positions, count, flag(body, "ticker_order", false));
            tickObservation = next;
            server.tickRateManager().setFrozen(false);
            return next;
        }));
        try { return await(job.result); }
        catch (Exception error) {
            await(server.submit(() -> {
                if (tickObservation == job) { tickObservation = null; server.tickRateManager().setFrozen(true); }
                return null;
            }));
            throw error;
        }
    }

    private void observeServerTick(MinecraftServer server) {
        TickObservation job = tickObservation;
        if (job == null) return;
        try {
            long now = job.level.getGameTime();
            if (now == job.previousTime) return;
            if (now != job.previousTime + 1) throw new IllegalStateException("Observation skipped a simulation tick");
            job.previousTime = now;
            JsonObject sample = new JsonObject();
            sample.addProperty("tick", job.requested - job.remaining + 1);
            sample.addProperty("game_time", now);
            JsonArray blocks = new JsonArray();
            for (BlockPos position : job.positions) blocks.add(blockAt(job.level, position));
            sample.add("blocks", blocks); job.samples.add(sample);
            if (job.includeTickerOrder) sample.add("ticker_order", tickerOrder(job.level, job.positions));
            if (--job.remaining == 0) {
                server.tickRateManager().setFrozen(true); tickObservation = null;
                JsonObject result = object("mode", "normal simulation observed at ServerTickEvent.Post");
                result.addProperty("ticks", job.requested); result.add("samples", job.samples);
                job.result.complete(result);
            }
        } catch (Throwable error) {
            server.tickRateManager().setFrozen(true); tickObservation = null;
            job.result.completeExceptionally(error);
        }
    }

    private JsonObject camera(JsonObject body) throws Exception {
        MinecraftServer server = server();
        Vec3 position = vec(body, "position");
        JsonObject angles = await(client(() -> {
            Minecraft mc = Minecraft.getInstance();
            float yaw = body.has("yaw") ? body.get("yaw").getAsFloat() : mc.player.getYRot();
            float pitch = body.has("pitch") ? body.get("pitch").getAsFloat() : mc.player.getXRot();
            if (body.has("target")) {
                Vec3 delta = vec(body, "target").subtract(position.add(0, mc.player.getEyeHeight(), 0));
                yaw = (float)Math.toDegrees(Math.atan2(-delta.x, delta.z));
                pitch = (float)-Math.toDegrees(Math.atan2(delta.y, Math.sqrt(delta.x*delta.x + delta.z*delta.z)));
            }
            JsonObject value = new JsonObject(); value.addProperty("yaw", yaw); value.addProperty("pitch", pitch); return value;
        }));
        await(server.submit(() -> {
            ServerPlayer player = player(server);
            player.teleportTo(player.serverLevel(), position.x, position.y, position.z, angles.get("yaw").getAsFloat(), angles.get("pitch").getAsFloat());
            return null;
        }));
        return await(client(() -> {
            Minecraft mc = Minecraft.getInstance();
            mc.player.setPos(position); mc.player.setYRot(angles.get("yaw").getAsFloat()); mc.player.setXRot(angles.get("pitch").getAsFloat());
            mc.player.setOldPosAndRot(); mc.player.setDeltaMovement(Vec3.ZERO);
            if (body.has("window_size")) {
                JsonArray size = body.getAsJsonArray("window_size");
                if (size.size() != 2) throw new IllegalArgumentException("window_size needs width and height");
                int width = size.get(0).getAsInt(), height = size.get(1).getAsInt();
                if (width < 320 || width > 3840 || height < 200 || height > 2160)
                    throw new IllegalArgumentException("Reference window size is outside the capture bounds");
                if (mc.getWindow().isFullscreen())
                    throw new IllegalArgumentException("window_size requires a windowed reference client");
                GLFW.glfwRestoreWindow(mc.getWindow().getWindow());
                GLFW.glfwSetWindowSize(mc.getWindow().getWindow(), width, height);
            }
            if (body.has("fov")) mc.options.fov().set(integer(body, "fov", 70));
            if (body.has("gui_scale")) {mc.options.guiScale().set(integer(body, "gui_scale", 2)); mc.resizeDisplay();}
            if (body.has("hide_gui")) mc.options.hideGui = flag(body, "hide_gui", false);
            return clientState(mc);
        }));
    }

    private JsonObject ticks(JsonObject body) throws Exception {
        MinecraftServer server = server();
        if (body.has("frozen")) await(server.submit(() -> command(server, flag(body,"frozen",true) ? "tick freeze" : "tick unfreeze")));
        int count = integer(body, "step", 0);
        if (count < 0 || count > 10000) throw new IllegalArgumentException("Step range is 0..10000");
        if (count > 0) {
            if (!await(server.submit(() -> server.tickRateManager().isFrozen()))) throw new IllegalArgumentException("Freeze the simulation before stepping");
            long start = await(server.submit(() -> server.overworld().getGameTime()));
            await(server.submit(() -> command(server, "tick step " + count)));
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(60);
            while (await(server.submit(() -> server.overworld().getGameTime())) < start + count) {
                if (System.nanoTime() > deadline) throw new TimeoutException("Server tick step timed out");
                Thread.sleep(5);
            }
        }
        return state();
    }

    private JsonObject capture(JsonObject body) throws Exception {
        CompletableFuture<JsonObject> result = new CompletableFuture<>();
        frameJobs.add(new FrameJob(frames + Math.max(1, integer(body, "frames", 2)), body, result));
        return await(result);
    }

    private void beginTap() {
        activeTap = pendingTap;
        pendingTap = null;
        if (activeTap != null) {
            KeyMapping.click(activeTap.getKey());
            activeTap.setDown(true);
        }
    }

    private void endTap() {
        if (activeTap != null) {
            activeTap.setDown(false);
            activeTap = null;
        }
    }

    private JsonObject input(JsonObject body) {
        Minecraft mc = Minecraft.getInstance();
        String kind = string(body,"kind","key");
        if ((kind.equals("mouse") || kind.equals("move")) && mc.screen != null) {
            int button = integer(body, "button", 0);
            double x = body.get("x").getAsDouble(), y = body.get("y").getAsDouble();
            GLFW.glfwSetCursorPos(mc.getWindow().getWindow(), x * mc.getWindow().getScreenWidth() / mc.getWindow().getGuiScaledWidth(),
                y * mc.getWindow().getScreenHeight() / mc.getWindow().getGuiScaledHeight());
            // GLFW cursor movement is not delivered to an unfocused Cocoa
            // window. Preserve the actual Screen render/input coordinates via
            // Create's own pinned MouseHandler accessors in this test bridge.
            var cursor=(com.simibubi.create.foundation.mixin.accessor.MouseHandlerAccessor)mc.mouseHandler;
            cursor.create$setXPos(x * mc.getWindow().getScreenWidth() / mc.getWindow().getGuiScaledWidth());
            cursor.create$setYPos(y * mc.getWindow().getScreenHeight() / mc.getWindow().getGuiScaledHeight());
            mc.screen.mouseMoved(x,y);
            if (kind.equals("mouse")) {
                if (body.has("down")) {
                    if (flag(body,"down",false)) mc.screen.mouseClicked(x,y,button); else mc.screen.mouseReleased(x,y,button);
                } else {mc.screen.mouseClicked(x,y,button); mc.screen.mouseReleased(x,y,button);}
            }
        } else if (kind.equals("escape")) {
            if (mc.screen != null) mc.screen.onClose(); else mc.pauseGame(false);
        } else if (kind.equals("character")) {
            if (mc.screen == null) throw new IllegalStateException("No text input screen is open");
            for (char character : body.get("text").getAsString().toCharArray()) mc.screen.charTyped(character,0);
        } else {
            String name = string(body,"key",kind.equals("mouse") ? (integer(body,"button",0)==1 ? "use" : "attack") : "use");
            KeyMapping key = switch(name) {
                case "use" -> mc.options.keyUse; case "attack" -> mc.options.keyAttack;
                case "shift" -> mc.options.keyShift; case "inventory" -> mc.options.keyInventory;
                case "jump" -> mc.options.keyJump; case "forward" -> mc.options.keyUp;
                case "back" -> mc.options.keyDown; default -> throw new IllegalArgumentException("Unknown key " + name);
            };
            if (kind.equals("tap")) {
                if (mc.screen != null || pendingTap != null || activeTap != null)
                    throw new IllegalStateException("A short press requires an idle game screen");
                pendingTap = key;
            } else if (body.has("down")) key.setDown(flag(body,"down",false));
            else {KeyMapping.click(key.getKey()); key.setDown(true); release.add(key);}
        }
        return clientState(mc);
    }

    private JsonObject language(JsonObject body) throws Exception {
        String language = body.get("language").getAsString();
        CompletableFuture<Void> reload = await(client(() -> {
            Minecraft mc = Minecraft.getInstance();
            if (mc.getLanguageManager().getLanguage(language) == null) throw new IllegalArgumentException("Unknown language " + language);
            mc.getLanguageManager().setSelected(language); mc.options.languageCode = language; mc.options.save();
            return mc.reloadResourcePacks();
        }));
        await(reload); return state();
    }

    private Path bounded(String directory, String name) {
        Path parent = root.resolve(directory).normalize(); Path path = parent.resolve(name).normalize();
        if (!path.startsWith(parent) || path.equals(parent)) throw new IllegalArgumentException("Path must stay in " + directory);
        return path;
    }

    private static <T extends Comparable<T>> BlockState applyProperty(BlockState state, Property<T> property, String value) {
        return state.setValue(property, property.getValue(value).orElseThrow(() -> new IllegalArgumentException("Unknown property/value " + property.getName() + "=" + value)));
    }

    private static BlockState property(BlockState state, String name, String value) {
        Property<?> property = state.getBlock().getStateDefinition().getProperty(name);
        if (property == null) throw new IllegalArgumentException("Unknown property " + name);
        return applyProperty(state,property,value);
    }

    private JsonObject schematic(JsonObject body) {
        try {
            MinecraftServer server = server(); ServerPlayer player = player(server); ServerLevel level = player.serverLevel();
            if (!player.isCreative()) throw new IllegalStateException("Original creative schematic placement requires creative mode");
            String name = body.get("file").getAsString();
            if (!name.endsWith(".nbt") || !Path.of(name).getFileName().toString().equals(name)) throw new IllegalArgumentException("Use a staged .nbt filename");
            Path file = bounded("schematics", name);
            CompoundTag tag = NbtIo.readCompressed(file, NbtAccounter.create(64L * 1024 * 1024));
            if (!tag.contains("DataVersion",Tag.TAG_INT)||!tag.contains("palette",Tag.TAG_LIST)||!tag.contains("blocks",Tag.TAG_LIST)||!tag.contains("size",Tag.TAG_LIST)) throw new IllegalArgumentException("Schematic requires typed DataVersion, palette, blocks and size");
            if (tag.getInt("DataVersion") != 3955) throw new IllegalArgumentException("Schematic DataVersion must be exactly 3955");
            ListTag size = tag.getList("size", Tag.TAG_INT);
            if (size.size()!=3) throw new IllegalArgumentException("Schematic requires three size entries");
            for (int i=0;i<3;i++) if (size.getInt(i)<1||size.getInt(i)>256) throw new IllegalArgumentException("Schematic dimensions must be 1..256");
            if (tag.contains("palettes")) throw new IllegalArgumentException("Multiple palettes are outside the shared-fixture contract");
            ListTag palette = tag.getList("palette", Tag.TAG_COMPOUND); ListTag blocks = tag.getList("blocks", Tag.TAG_COMPOUND);
            ListTag rawBlocks=(ListTag)tag.get("blocks");
            if(!rawBlocks.isEmpty()&&rawBlocks.getElementType()!=Tag.TAG_COMPOUND) throw new IllegalArgumentException("Schematic blocks must be compounds");
            if (palette.isEmpty()||blocks.size()>1000000) throw new IllegalArgumentException("Invalid palette/block count");
            List<BlockState> states=new ArrayList<>();
            for (int i=0;i<palette.size();i++) {
                CompoundTag entry=palette.getCompound(i); ResourceLocation id=ResourceLocation.parse(entry.getString("Name"));
                if (!BuiltInRegistries.BLOCK.containsKey(id)) throw new IllegalArgumentException("Unknown block " + id);
                BlockState state=BuiltInRegistries.BLOCK.get(id).defaultBlockState();
                if(entry.contains("Properties")&&!entry.contains("Properties",Tag.TAG_COMPOUND)) throw new IllegalArgumentException("Block Properties must be a compound");
                CompoundTag props=entry.getCompound("Properties");
                for(String key:props.getAllKeys()) {
                    if(!props.contains(key,Tag.TAG_STRING)) throw new IllegalArgumentException("Property must be a string: " + key);
                    state=property(state,key,props.getString(key));
                }
                states.add(state);
            }
            Rotation rotation=Rotation.valueOf(string(body,"rotation","NONE").toUpperCase(Locale.ROOT));
            Mirror mirror=Mirror.valueOf(string(body,"mirror","NONE").toUpperCase(Locale.ROOT));
            Set<BlockPos> seen=new HashSet<>(); BlockPos origin=pos(body,"origin");
            for(int i=0;i<blocks.size();i++) {
                CompoundTag entry=blocks.getCompound(i); ListTag position=entry.getList("pos",Tag.TAG_INT);
                if(position.size()!=3) throw new IllegalArgumentException("Block requires three coordinates");
                BlockPos at=new BlockPos(position.getInt(0),position.getInt(1),position.getInt(2));
                if(at.getX()<0||at.getY()<0||at.getZ()<0||at.getX()>=size.getInt(0)||at.getY()>=size.getInt(1)||at.getZ()>=size.getInt(2)||!seen.add(at)) throw new IllegalArgumentException("Duplicate or out-of-bounds block " + at);
                if(!entry.contains("state",Tag.TAG_INT)||entry.getInt("state")<0||entry.getInt("state")>=palette.size()) throw new IllegalArgumentException("Invalid palette index");
                if(origin.getY()+at.getY()<level.getMinBuildHeight()||origin.getY()+at.getY()>=level.getMaxBuildHeight()) throw new IllegalArgumentException("Placement exceeds world build height");
                if(entry.contains("nbt")) {
                    if(!entry.contains("nbt",Tag.TAG_COMPOUND)) throw new IllegalArgumentException("Block entity NBT must be a compound");
                    String id=entry.getCompound("nbt").getString("id");
                    if(id.isEmpty()||!BuiltInRegistries.BLOCK_ENTITY_TYPE.containsKey(ResourceLocation.parse(id))) throw new IllegalArgumentException("Unknown block entity " + id);
                    if(!BuiltInRegistries.BLOCK_ENTITY_TYPE.get(ResourceLocation.parse(id)).isValid(states.get(entry.getInt("state")))) throw new IllegalArgumentException("Block entity " + id + " is invalid for palette index " + entry.getInt("state"));
                }
            }
            if(tag.contains("entities")&&!tag.contains("entities",Tag.TAG_LIST)) throw new IllegalArgumentException("Schematic entities must be a list");
            ListTag entities=tag.getList("entities",Tag.TAG_COMPOUND);
            if(tag.get("entities") instanceof ListTag rawEntities&&!rawEntities.isEmpty()&&rawEntities.getElementType()!=Tag.TAG_COMPOUND) throw new IllegalArgumentException("Schematic entities must be compounds");
            if(!entities.isEmpty()) throw new IllegalArgumentException("Entities are outside the initial shared-fixture contract");
            JsonObject result=object("mode","Create SchematicPlacePacket.handle");
            result.addProperty("blocks",blocks.size());result.addProperty("palette",palette.size());
            result.addProperty("preflight",flag(body,"preflight",false));
            if(flag(body,"preflight",false)) return result;
            Path uploaded=CreatePaths.UPLOADED_SCHEMATICS_DIR.resolve("reference").resolve(name);
            Files.createDirectories(uploaded.getParent());Files.copy(file,uploaded,StandardCopyOption.REPLACE_EXISTING);
            ItemStack blueprint=SchematicItem.create(level,name,"reference");
            blueprint.set(AllDataComponents.SCHEMATIC_DEPLOYED,true);
            blueprint.set(AllDataComponents.SCHEMATIC_ANCHOR,origin);
            blueprint.set(AllDataComponents.SCHEMATIC_ROTATION,rotation);
            blueprint.set(AllDataComponents.SCHEMATIC_MIRROR,mirror);
            new SchematicPlacePacket(blueprint).handle(player);
            result.addProperty("placed",true);return result;
        } catch(IOException error) {throw new UncheckedIOException(error);}
    }
}
