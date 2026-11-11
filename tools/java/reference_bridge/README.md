# Original Create development reference

This development-only client bridge runs Minecraft 1.21.1, NeoForge 21.1.227,
Create 6.0.10 (source `ac0c444d9828da3453ae8cc65338e8de063286fb`) and its bundled
JarJar dependencies on Java 21.0.7. It is not part of the native distribution.
The selected libraries/runtime are copied or read from Prism's cache; no Prism
instance, world, configuration or account files are changed. The direct official
BootstrapLauncher client uses an isolated developer identity, not account data.

From the repository directory:

```sh
python3 tools/reference_java.py prepare
python3 tools/reference_java.py build
python3 tools/reference_java.py launch
python3 tools/reference_java.py call state
python3 tools/reference_java.py call camera '{"position":[2.5,64,3.5],"target":[2.5,66.5,0.5],"gui_scale":4}'
python3 tools/reference_java.py call capture '{"name":"comparison.png","frames":8}'
python3 tools/reference_java.py stop
```

Use `launch --normal-world` after stopping the reference client for checks
that need naturally generated terrain. It opens a separate save with the
ordinary world preset and the same pinned seed.

`prepare` verifies the exact Create JAR checksum and copies only the selected
official metadata/libraries/assets. Missing hash-addressed Mojang assets may be
fetched from their official URLs after digest verification. The default root is
`.local/java-reference`; `--root PATH` selects another isolated root. Cached
source libraries remain read only. No EULA acceptance or server install is used.

The loopback-only endpoint is `http://127.0.0.1:38261` by default. Every endpoint
requires POST JSON and a private random bearer token. The CLI reads that token
from the private configuration; do not print or publish it. `ready.json` announces
the endpoint when the mod is loaded, but **actual world readiness** requires
`/state.ready == true`. An open GUI sets this false while still permitting GUI
observation/control. Client work runs on the render thread and world work on the
integrated server thread. Captures use Minecraft's original framebuffer API.

| Method | JSON request | Result / behavior |
| --- | --- | --- |
| `state` | `{}` | World/player/GUI readiness, pose, hit target, dimensions, scale, frames, server clock/frozen state |
| `command` | `{"command":"setblock ..."}` | Original permission-4 command execution as the isolated player, captured messages |
| `block` | `{"pos":[x,y,z]}` | Actual state/properties and full original block-entity SNBT |
| `entities` | `{"center":[x,y,z],"radius":16}` | Entity position/motion/fire/health and full SNBT; radius at most 128 |
| `camera` | `{"position":[x,y,z],"target":[x,y,z],"gui_scale":4}` | Matching server/client player pose; alternatively yaw/pitch, optional fov/hide_gui. Optional `window_size:[1280,720]` restores a windowed reference to that logical size; wait for `state.framebuffer_size` before comparing captures (Retina uses twice the logical size). |
| `tick` | `{"frozen":true,"step":3}` | Original tick freeze/unfreeze/step; step requires frozen and waits for exact game-time advancement |
| `observe_ticks` | `{"ticks":180,"positions":[[0,64,0],[0,66,0]],"commands":["summon ..."]}` | Requires frozen, playing world; runs normal unfrozen simulation, records block/NBT state after each actual server tick, then freezes again. At most400 ticks,32 positions and16 bounded setup commands |
| `capture` | `{"name":"x.png","frames":8}` | Original framebuffer PNG after frames; paths bounded to the isolated captures directory |
| `ui` | `{}` | Actual Screen/widgets, original tooltip-provider components and font widths, motor board labels/value coordinates; live Outliner value-box entries, expiry, icon texels and original block-local pose matrices |
| `deployer_actor_frames` | `{}` | Drain the bounded frame observations for the private moving Deployer fixture, including the actual Flywheel hand extension and actor context |
| `particles` | `{"limit":128,"class_contains":"AirFlow","partial":1}` | Live engine counts; instance IDs; original positions, velocity, color, alpha, age/lifetime, sprite/UV, quad size and light; Catnip client/level animation ticks and render time |
| `damage` | `{"ids":["create:fan_fire","create:fan_lava"]}` | Loaded original damage registry definitions and resolved tags |
| `input` | `{"key":"use","down":true}` | Hold/release normal key mappings; use, attack, shift, inventory, jump, forward, back |
| `input` | `{"kind":"move","x":330.5,"y":185}` | Set GUI cursor position; uses original Create MouseHandler accessors for unfocused Cocoa windows |
| `input` | `{"kind":"mouse","x":258.5,"y":174,"button":1,"down":false}` | Original Screen mouse handlers; optional down separates press/release; coordinates in GUI pixels |
| `input` | `{"kind":"escape"}` or `{"kind":"character","text":"..."}` | Original GUI close / text input |
| `language` | `{"language":"ru_ru"}` | Original resource/language reload; awaits completion |
| `schematic` | `{"file":"staged.nbt","origin":[x,y,z],"preflight":true}` | Strict shared-format validation; omit preflight to call original Create creative SchematicPlacePacket.handle |
| `quit` | `{}` | Graceful shutdown of this client only |

Stage an authored fixture using
`python3 tools/reference_java.py stage-schematic PATH.nbt`; its checksum is added
to the filename. The bridge requires DataVersion 3955, one palette, bounded typed
positions, valid registered blocks/properties and matching block-entity types.
It rejects unsupported entities and invalid entries before any world changes.
The actual placement uses Create's own safe-NBT, waterlogging, transform and
creative-placement policies. Commands are privileged diagnostics and can of
course alter this isolated reference world.

`ui.goggles` calls the original providers; it is explicitly a component-provider
trace, not a claim to intercept every rendering branch. Use PNGs for actual
rendering evidence. Particle snapshots are actual instances, not a deterministic
random seed oracle. Camera placement obeys normal gravity after teleport, so use
a grounded pose or freeze before comparison. Snapshots and SNBT must be compared
at corresponding simulated ticks; independent frame captures do not by themselves
prove numerical or temporal parity with Horizon.

Create's `KineticBlockEntity.getSpeed` returns zero while the tick manager is
frozen, including ordinary `/tick step`. Use `observe_ticks` for active kinetic
cycle comparisons. Its post-tick census checks contiguous actual game times;
it does not infer elapsed simulation from a sprint request or elapsed wall time.
The bridge only changes the normal tick manager's frozen flag and observes
states; it never calls a machine tick or recipe implementation directly.

Create rotation-indicator samples also expose the original origin/offset,
radius/radius1/radius2, speed, axis and visibility. Airflow samples include their
source position/speed, current direction/push mode/range/bounds and processing
segment offsets/types, so each observed trajectory can be replayed without
assuming the two clients share random seeds.

The world-boot/frame integration derives from Horizon's MIT NeoForgeBench.
The full notice is in `resources/META-INF/LICENSE`. This bridge contains no
original textures/models/audio, no authentication data and no addon mods.

`state.render_backend` records the public Flywheel current backend ID, support
state and visualization support for the actual client level. For the current hit
block entity it records the registered visualizer class, skip-vanilla policy and
vanilla renderer class. These are read-only registration/backend observations;
VisualManager exposes only an aggregate count, so individual visual presence is
not inferred. No renderer/backend/configuration is changed by the observation.
