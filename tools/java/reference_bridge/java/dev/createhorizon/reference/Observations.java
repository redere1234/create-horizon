// Copyright (c) 2026 create-horizon contributors
// Development diagnostics against the pinned original client; not shipped.
package dev.createhorizon.reference;

import com.google.gson.*;
import com.mojang.blaze3d.vertex.PoseStack;
import com.simibubi.create.CreateClient;
import com.simibubi.create.api.equipment.goggles.IHaveGoggleInformation;
import com.simibubi.create.api.equipment.goggles.IHaveHoveringInformation;
import com.simibubi.create.api.registry.CreateBuiltInRegistries;
import com.simibubi.create.content.kinetics.base.RotationIndicatorParticle;
import com.simibubi.create.content.kinetics.fan.AirFlowParticle;
import com.simibubi.create.content.kinetics.fan.IAirCurrentSource;
import com.simibubi.create.content.kinetics.fan.processing.FanProcessingType;
import com.simibubi.create.content.equipment.goggles.GoggleOverlayRenderer;
import com.simibubi.create.content.equipment.goggles.GogglesItem;
import com.simibubi.create.foundation.blockEntity.behaviour.ValueSettingsBehaviour.ValueSettings;
import com.simibubi.create.foundation.blockEntity.behaviour.ValueSettingsBoard;
import com.simibubi.create.foundation.blockEntity.behaviour.ValueSettingsScreen;
import com.simibubi.create.foundation.blockEntity.behaviour.ValueBox;
import com.simibubi.create.foundation.blockEntity.behaviour.ValueBoxTransform;
import com.simibubi.create.infrastructure.config.AllConfigs;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.*;
import net.createmod.catnip.animation.AnimationTickHolder;
import net.createmod.catnip.outliner.Outliner;
import net.minecraft.client.Minecraft;
import net.minecraft.client.gui.components.AbstractWidget;
import net.minecraft.client.particle.Particle;
import net.minecraft.client.particle.SingleQuadParticle;
import net.minecraft.client.particle.TextureSheetParticle;
import net.minecraft.client.renderer.texture.TextureAtlasSprite;
import net.minecraft.core.BlockPos;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.core.registries.Registries;
import net.minecraft.nbt.CompoundTag;
import net.minecraft.network.chat.CommonComponents;
import net.minecraft.network.chat.Component;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.world.entity.LivingEntity;
import net.minecraft.world.phys.AABB;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.EntityHitResult;
import net.minecraft.world.phys.Vec3;
import net.minecraft.world.level.block.state.BlockState;

final class Observations {
    private Observations() {}

    private static JsonArray vector(double... values) {
        JsonArray result=new JsonArray();for(double value:values) result.add(value);return result;
    }
    private static Object field(Object value, Class<?> owner, String name) {
        try {Field field=owner.getDeclaredField(name);field.setAccessible(true);return field.get(value);}
        catch(ReflectiveOperationException error) {throw new IllegalStateException("Pinned reference field changed: " + owner.getName() + "." + name,error);}
    }
    private static int particleLight(Particle particle,float partial) {
        try {
            Method method=Particle.class.getDeclaredMethod("getLightColor",float.class);
            method.setAccessible(true);return (Integer)method.invoke(particle,partial);
        } catch(ReflectiveOperationException error) {
            throw new IllegalStateException("Pinned reference particle light method changed",error);
        }
    }
    private static JsonObject component(Component value) {
        Minecraft mc=Minecraft.getInstance();JsonObject result=new JsonObject();
        result.addProperty("text",value.getString());result.addProperty("width",mc.font.width(value));
        result.add("component",JsonParser.parseString(Component.Serializer.toJson(value,mc.level.registryAccess())));
        return result;
    }

    static JsonObject hit(Minecraft mc) {
        JsonObject result=new JsonObject();
        if(mc.hitResult==null) return result;
        result.addProperty("type",mc.hitResult.getType().toString());
        Vec3 location=mc.hitResult.getLocation();result.add("location",vector(location.x,location.y,location.z));
        if(mc.hitResult instanceof BlockHitResult block) {
            BlockPos pos=block.getBlockPos();result.add("pos",vector(pos.getX(),pos.getY(),pos.getZ()));
            result.addProperty("face",block.getDirection().getName());
            result.addProperty("block",BuiltInRegistries.BLOCK.getKey(mc.level.getBlockState(pos).getBlock()).toString());
        } else if(mc.hitResult instanceof EntityHitResult entity) result.addProperty("entity_id",entity.getEntity().getId());
        return result;
    }

    static JsonObject ui() {
        Minecraft mc=Minecraft.getInstance();JsonObject result=new JsonObject();
        result.add("hit",hit(mc));result.addProperty("language",mc.getLanguageManager().getSelected());
        result.addProperty("screen",mc.screen==null?"playing":mc.screen.getClass().getName());
        JsonArray widgets=new JsonArray();
        if(mc.screen!=null) {
            result.add("title",component(mc.screen.getTitle()));
            for(var child:mc.screen.children()) {
                JsonObject widget=new JsonObject();widget.addProperty("class",child.getClass().getName());
                if(child instanceof AbstractWidget w) {
                    widget.add("bounds",vector(w.getX(),w.getY(),w.getWidth(),w.getHeight()));
                    widget.add("message",component(w.getMessage()));widget.addProperty("active",w.active);widget.addProperty("visible",w.visible);
                }
                widgets.add(widget);
            }
            if(mc.screen instanceof ValueSettingsScreen settings) result.add("value_settings",valueSettings(settings));
        }
        result.add("widgets",widgets);result.add("goggles",goggles(mc));result.add("value_boxes",valueBoxes(mc));
        var settingsClient = CreateClient.VALUE_SETTINGS_HANDLER;
        JsonArray hoverTip = new JsonArray();
        if (settingsClient.hoverTicks > 0 && settingsClient.lastHoverTip != null)
            settingsClient.lastHoverTip.forEach(line -> hoverTip.add(line.getString()));
        result.add("value_hover_tip", hoverTip);
        return result;
    }

    private static JsonArray matrix(PoseStack pose) {
        JsonArray result=new JsonArray();for(float value:pose.last().pose().get(new float[16]))result.add(value);return result;
    }

    // Actual live Outliner entries and original transform methods. Poses are
    // block-local column-major matrices, without the camera translation.
    private static JsonArray valueBoxes(Minecraft mc) {
        JsonArray result=new JsonArray();
        for(var entry:Outliner.getInstance().getOutlines().values()) {
            if(!(entry.getOutline() instanceof ValueBox box))continue;
            BlockPos pos=(BlockPos)field(box,ValueBox.class,"pos");
            BlockState state=(BlockState)field(box,ValueBox.class,"blockState");
            ValueBoxTransform transform=(ValueBoxTransform)field(box,ValueBox.class,"transform");
            JsonObject value=new JsonObject();value.add("pos",vector(pos.getX(),pos.getY(),pos.getZ()));
            value.addProperty("block",BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString());
            value.addProperty("passive",box.isPassive);value.addProperty("ticks_until_removal",entry.getTicksTillRemoval());
            value.addProperty("alive",entry.isAlive());value.addProperty("fading",entry.isFading());
            var face=box.getParams().getHighlightedFace();if(face!=null)value.addProperty("face",face.getName());
            PoseStack pose=new PoseStack();
            if(transform!=null) {
                if(transform instanceof ValueBoxTransform.Sided sided&&face!=null)sided.fromSide(face);
                value.addProperty("should_render",transform.shouldRender(mc.level,pos,state));
                transform.transform(mc.level,pos,state,pose);
            }
            value.add("slot_pose",matrix(pose));
            pose.pushPose();pose.scale(-2.01f,-2.01f,2.01f);pose.translate(-.5,-.5,-.5/16);
            value.add("hover_icon_pose",matrix(pose));pose.popPose();
            var icon=box.getOutline();value.add("icon_texels",vector((Integer)field(icon,icon.getClass(),"iconX"),(Integer)field(icon,icon.getClass(),"iconY"),16,16));
            if(box instanceof ValueBox.TextValueBox) {
                Component text=(Component)field(box,ValueBox.TextValueBox.class,"text");value.add("text",component(text));
                float fontScale=transform==null?-1/64f:-transform.getFontScale();pose.scale(fontScale,fontScale,fontScale);
                pose.scale(3,3,1);pose.translate(-4,-3.75,5);
                int width=mc.font.width(text);float numberScale=9f/width;boolean single=width<10;
                if(single)numberScale/=2;float margin=(width-9)/2f;
                pose.scale(numberScale,numberScale,numberScale);pose.translate(single?width/2:0,single?-margin:margin,0);
                value.add("text_pose",matrix(pose));
            }
            result.add(value);
        }
        return result;
    }

    private static JsonObject valueSettings(ValueSettingsScreen screen) {
        ValueSettingsBoard board=(ValueSettingsBoard)field(screen,ValueSettingsScreen.class,"board");
        JsonObject result=new JsonObject();result.add("title",component(board.title()));
        result.addProperty("max_value",board.maxValue());result.addProperty("milestone_interval",board.milestoneInterval());
        result.addProperty("ticks_open",(Integer)field(screen,ValueSettingsScreen.class,"ticksOpen"));
        JsonArray rows=new JsonArray();for(Component row:board.rows()) rows.add(component(row));result.add("rows",rows);
        ValueSettings initial=(ValueSettings)field(screen,ValueSettingsScreen.class,"initialSettings");
        ValueSettings hovered=(ValueSettings)field(screen,ValueSettingsScreen.class,"lastHovered");
        for(var entry:Map.of("initial",initial,"hovered",hovered).entrySet()) {
            ValueSettings value=entry.getValue();JsonObject setting=new JsonObject();
            setting.addProperty("row",value.row());setting.addProperty("value",value.value());
            setting.add("formatted",component(board.formatter().format(value)));
            var at=screen.getCoordinateOfValue(value.row(),value.value());setting.add("gui_coordinate",vector(at.x,at.y));result.add(entry.getKey(),setting);
        }
        JsonArray samples=new JsonArray();
        for(int row=0;row<board.rows().size();row++) for(int value:new int[]{0,16,32,64,128,256}) {
            if(value>board.maxValue()) continue;
            JsonObject sample=new JsonObject();sample.addProperty("row",row);sample.addProperty("value",value);
            var at=screen.getCoordinateOfValue(row,value);sample.add("gui_coordinate",vector(at.x,at.y));
            sample.add("formatted",component(board.formatter().format(new ValueSettings(row,value))));samples.add(sample);
        }
        result.add("sample_coordinates",samples);return result;
    }

    // The original providers build the same component list used by renderOverlay.
    // This is a provider trace; framebuffer captures independently show rendering.
    private static JsonObject goggles(Minecraft mc) {
        JsonObject result=new JsonObject();result.addProperty("trace","original tooltip providers");
        result.addProperty("hover_ticks",GoggleOverlayRenderer.hoverTicks);
        result.addProperty("wearing",mc.player!=null&&GogglesItem.isWearingGoggles(mc.player));
        JsonArray lines=new JsonArray();
        if(mc.player==null||!(mc.hitResult instanceof BlockHitResult hit)) {result.add("lines",lines);return result;}
        BlockPos pos=GoggleOverlayRenderer.proxiedOverlayPosition(mc.level,hit.getBlockPos());
        var entity=mc.level.getBlockEntity(pos);boolean shift=mc.player.isShiftKeyDown();
        List<Component> tooltip=new ArrayList<>();boolean added=false;
        if(entity instanceof IHaveGoggleInformation info&&GogglesItem.isWearingGoggles(mc.player)) added=info.addToGoggleTooltip(tooltip,shift);
        if(entity instanceof IHaveHoveringInformation info) {
            boolean separator=!tooltip.isEmpty();if(separator)tooltip.add(CommonComponents.EMPTY);
            if(!info.addToTooltip(tooltip,shift)&&added&&separator)tooltip.removeLast();
        }
        int width=0;for(Component line:tooltip) {lines.add(component(line));width=Math.max(width,mc.font.width(line));}
        result.add("lines",lines);result.addProperty("shift",shift);result.addProperty("max_text_width",width);
        int height=tooltip.size()>1?10+(tooltip.size()-1)*10:8;
        var config=AllConfigs.client();
        result.add("source_tooltip_anchor",vector(Math.min(mc.getWindow().getGuiScaledWidth()/2+config.overlayOffsetX.get(),mc.getWindow().getGuiScaledWidth()-width-20),
            Math.min(mc.getWindow().getGuiScaledHeight()/2+config.overlayOffsetY.get(),mc.getWindow().getGuiScaledHeight()-height-20)));
        result.addProperty("tooltip_height",height);return result;
    }

    static JsonObject particles(JsonObject body) {
        Minecraft mc=Minecraft.getInstance();int limit=body.has("limit")?body.get("limit").getAsInt():128;
        if(limit<0||limit>2048)throw new IllegalArgumentException("Particle limit must be 0..2048");
        float partial=body.has("partial")?body.get("partial").getAsFloat():1;
        if(!Float.isFinite(partial)||partial<0||partial>1)throw new IllegalArgumentException("Particle partial must be 0..1");
        String filter=body.has("class_contains")?body.get("class_contains").getAsString():"";
        JsonObject result=new JsonObject();JsonArray samples=new JsonArray();Map<String,Integer> counts=new TreeMap<>();
        result.addProperty("partial",partial);result.addProperty("game_time",mc.level.getGameTime());
        result.addProperty("animation_ticks",AnimationTickHolder.getTicks());
        result.addProperty("animation_ticks_including_paused",AnimationTickHolder.getTicks(true));
        result.addProperty("level_animation_ticks",AnimationTickHolder.getTicks(mc.level));
        result.addProperty("animation_partial",AnimationTickHolder.getPartialTicks(mc.level));
        result.addProperty("animation_render_time",AnimationTickHolder.getRenderTime(mc.level));
        mc.particleEngine.iterateParticles(particle->{
            String name=particle.getClass().getName();counts.merge(name,1,Integer::sum);
            if(samples.size()>=limit||!name.contains(filter))return;
            JsonObject sample=new JsonObject();sample.addProperty("class",name);
            sample.addProperty("instance_id",System.identityHashCode(particle));
            Vec3 at=particle.getPos();sample.add("position",vector(at.x,at.y,at.z));
            sample.addProperty("render_type",particle.getRenderType().toString());sample.addProperty("alive",particle.isAlive());
            sample.addProperty("light",particleLight(particle,partial));
            if(particle instanceof SingleQuadParticle quad) {
                sample.addProperty("quad_size",quad.getQuadSize(partial));
                sample.addProperty("base_quad_size",(Float)field(particle,SingleQuadParticle.class,"quadSize"));
            }
            if(particle instanceof TextureSheetParticle) {
                TextureAtlasSprite sprite=(TextureAtlasSprite)field(particle,TextureSheetParticle.class,"sprite");
                if(sprite!=null) {
                    sample.addProperty("sprite",sprite.contents().name().toString());
                    sample.add("sprite_uv",vector(sprite.getU0(),sprite.getV0(),sprite.getU1(),sprite.getV1()));
                }
            }
            if(particle instanceof RotationIndicatorParticle) {
                JsonObject rotation=new JsonObject();
                for(String key:new String[]{"radius","radius1","radius2","speed"})rotation.addProperty(key,(Number)field(particle,RotationIndicatorParticle.class,key));
                for(String key:new String[]{"origin","offset"}) {
                    Vec3 value=(Vec3)field(particle,RotationIndicatorParticle.class,key);rotation.add(key,vector(value.x,value.y,value.z));
                }
                rotation.addProperty("axis",field(particle,RotationIndicatorParticle.class,"axis").toString());
                rotation.addProperty("visible",(Boolean)field(particle,RotationIndicatorParticle.class,"isVisible"));
                sample.add("rotation",rotation);
            }
            if(particle instanceof AirFlowParticle) {
                IAirCurrentSource source=(IAirCurrentSource)field(particle,AirFlowParticle.class,"source");
                var current=source.getAirCurrent();JsonObject air=new JsonObject();
                var origin=source.getAirCurrentPos();air.add("origin",vector(origin.getX(),origin.getY(),origin.getZ()));
                air.addProperty("speed",source.getSpeed());air.addProperty("removed",source.isSourceRemoved());
                var originSide=source.getAirflowOriginSide();if(originSide!=null)air.addProperty("origin_side",originSide.getName());
                if(current!=null) {
                    if(current.direction!=null)air.addProperty("direction",current.direction.getName());
                    air.addProperty("pushing",current.pushing);air.addProperty("max_distance",current.maxDistance);
                    if(current.bounds!=null)air.add("bounds",vector(current.bounds.minX,current.bounds.minY,current.bounds.minZ,current.bounds.maxX,current.bounds.maxY,current.bounds.maxZ));
                    JsonArray segments=new JsonArray();
                    for(Object segment:current.segments) {
                        JsonObject part=new JsonObject();
                        part.addProperty("start_offset",(Integer)field(segment,segment.getClass(),"startOffset"));
                        part.addProperty("end_offset",(Integer)field(segment,segment.getClass(),"endOffset"));
                        FanProcessingType type=(FanProcessingType)field(segment,segment.getClass(),"type");
                        if(type!=null)part.addProperty("type",CreateBuiltInRegistries.FAN_PROCESSING_TYPE.getKey(type).toString());
                        segments.add(part);
                    }
                    air.add("segments",segments);
                }
                sample.add("air_current",air);
            }
            JsonObject fields=new JsonObject();
            for(String key:new String[]{"xo","yo","zo","xd","yd","zd","age","lifetime","rCol","gCol","bCol","alpha","roll","oRoll","gravity","friction","hasPhysics","onGround"}) {
                Object value=field(particle,Particle.class,key);
                if(value instanceof Number number)fields.addProperty(key,number);else if(value instanceof Boolean flag)fields.addProperty(key,flag);
            }
            sample.add("fields",fields);samples.add(sample);
        });
        result.add("counts",new Gson().toJsonTree(counts));result.add("samples",samples);return result;
    }

    static JsonObject damage(MinecraftServer server,JsonObject body) {
        var registry=server.registryAccess().registryOrThrow(Registries.DAMAGE_TYPE);
        JsonArray types=new JsonArray();
        JsonArray requested=body.has("ids")?body.getAsJsonArray("ids"):new Gson().toJsonTree(List.of("create:fan_fire","create:fan_lava")).getAsJsonArray();
        for(JsonElement element:requested) {
            ResourceLocation id=ResourceLocation.parse(element.getAsString());var holder=registry.getHolder(id).orElseThrow(()->new IllegalArgumentException("Unknown damage type " + id));
            var damage=holder.value();JsonObject value=new JsonObject();value.addProperty("id",id.toString());
            value.addProperty("message_id",damage.msgId());value.addProperty("scaling",damage.scaling().getSerializedName());
            value.addProperty("effects",damage.effects().getSerializedName());value.addProperty("exhaustion",damage.exhaustion());
            value.addProperty("death_message_type",damage.deathMessageType().getSerializedName());
            JsonArray tags=new JsonArray();holder.tags().map(tag->tag.location().toString()).sorted().forEach(tags::add);value.add("tags",tags);types.add(value);
        }
        JsonObject result=new JsonObject();result.add("types",types);return result;
    }

    static JsonObject entities(ServerLevel level,JsonObject body) {
        JsonArray center=body.getAsJsonArray("center");
        if(center==null||center.size()!=3)throw new IllegalArgumentException("Entity center requires three coordinates");
        double radius=body.has("radius")?body.get("radius").getAsDouble():16;
        if(!Double.isFinite(radius)||radius<0||radius>128)throw new IllegalArgumentException("Entity radius must be 0..128");
        Vec3 at=new Vec3(center.get(0).getAsDouble(),center.get(1).getAsDouble(),center.get(2).getAsDouble());
        JsonArray entities=new JsonArray();
        for(var entity:level.getEntities(null,new AABB(at,at).inflate(radius))) {
            JsonObject result=new JsonObject();result.addProperty("id",entity.getId());result.addProperty("uuid",entity.getStringUUID());
            result.addProperty("type",BuiltInRegistries.ENTITY_TYPE.getKey(entity.getType()).toString());
            result.add("position",vector(entity.getX(),entity.getY(),entity.getZ()));var motion=entity.getDeltaMovement();result.add("motion",vector(motion.x,motion.y,motion.z));
            result.addProperty("fire_ticks",entity.getRemainingFireTicks());result.addProperty("fire_immune",entity.fireImmune());
            if(entity instanceof LivingEntity living)result.addProperty("health",living.getHealth());
            result.addProperty("nbt",entity.saveWithoutId(new CompoundTag()).toString());entities.add(result);
        }
        JsonObject result=new JsonObject();result.add("entities",entities);result.addProperty("game_time",level.getGameTime());return result;
    }
}
