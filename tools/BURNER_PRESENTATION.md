# Burner presentation checks

The reference is Create 6.0.10 at
`ac0c444d9828da3453ae8cc65338e8de063286fb`. The Java sources used here are MIT;
original models, textures and generated probes remain in the private local cache.

Two source renderers are deliberate separate specifications:

- `Visual` models `BlazeBurnerVisual`, including retained rods/flame/hat choices
  and its constructor's inert goggles choice. The native adapter currently uses
  this model.
- `RendererFrame` models the stateless `BlazeBurnerRenderer.renderShared`
  fallback. It is a test/reference boundary with no native consumer or automatic
  backend selection. Its different goggles, hat transform, materials and UV
  arithmetic must not be presented as runtime features.

Run the CPU checks from the repository root:

```sh
python3 tools/burner_visual_oracle.py
python3 tools/burner_renderer_oracle.py
python3 tools/burner_cache_checks.py --horizon ../horizon-port-runtime
```

The visual oracle exports unchanged methods from the pinned source and executes
the player's actual Catnip animation, angle, Minecraft trigonometry and random
dependencies. Separate disposal cases record instances around unchanged
`animate`, `setupFlameInstance` and `_delete`: heat transitions and visual
recreation must delete every created instance exactly once. These recording
contexts do not establish actual GPU allocation, client scheduling or images.

The renderer oracle records unchanged `renderShared`, `getBlazeModel` and `draw`
poses, model/material selection, fullbright and UV operations. It proves that
independent reference model, not which backend rendered a reference screenshot.

The cache check compiles the native adapter's unchanged cache implementations
and `reset`, plus the actual Horizon `ModRevision` declaration/`same_entity`.
Controlled identity inputs test ordinary NBT/property writes, replacement,
unload, dimension/world switches, resource reload, frozen diagnostic bounds and
the reset callback. Its dimension-query context is authored; it is not an actual
Game/chunk-loader/packet test. Callback wiring is checked separately in the same
driver. A resource reload recreates visual choices while retaining the live BE's
chasers and unsaved phase. World close and entity replacement discard them.

The opt-in `CREATE_HORIZON_TRACE_POSES` diagnostic retains only live client BE
identities. World-time expiration alone cannot bound it during `/tick freeze`.
Its snapshots describe actual render input, not the resulting pixels.

## Stage10 material checks and image limits

The earlier private twelve-case captures showed darker native dynamic parts and
different visible gold details in case 10. They were not evidence that the source
selected large goggles. The two-case live observation below proves small
goggles selection in the source Visual; that selection remains unchanged.

Stage10 disables directional shading for four OBJ rod
models and the OBJ flame only. Actual loaded source quads report `shade=false`
for these five parts and their public Flywheel materials report cardinal
lighting `OFF`. JSON heads, goggles and hats report shaded quads and `ENTITY`
lighting; their native policy stays unchanged. This is an explicit pinned-part
draw policy, not a general rule about OBJ files. Stage10 also registers both
imported entity hats as standalone models; importing their files alone had not
made them available to native draw.

`burner_material_checks.py` compares the previous and candidate native draw
functions through an actual CPU Game and its model catalog. It compiles first,
then runs the single test from a fresh private game directory containing the
verified local JAR. Cargo's package working directory alone would load the
provisional models. Every observed source part, including both entity hats,
must resolve with its original face count before the vertex comparison starts.
The comparison permits only the five OBJ parts' directional-lighting payload
to change; poses, UVs, sprite/material routing, colors, light, JSON parts and
entity NBT/revision must remain identical. It is not a rendered-pixel test.
The `--test-binary` mode consumes an already captured test executable plus build
and test receipts. It invokes neither Cargo nor stage weaving, so coordinated
fixtures can share one compilation and execute from separate private game
directories. The receipts and executable hash remain attached to the result.

The exact Stage10 test executable passed all fourteen source/native face-count
guards, including four faces for each goggles model and fifteen for each hat.
Across 128 controlled frames and 30,976 vertices, only the 23,040 OBJ vertices'
directional-lighting payload changed. Poses, UVs, sprite/material routing,
colors, packed light, JSON normals and entity NBT/revision remained unchanged.
This was an actual Game/model-catalog check using the verified original JAR;
it did not run a GPU. Failed earlier setup and missing-hat guards were retained,
not removed or counted as passing evidence.

Two new raw native PNGs, cases 05 and 10, were captured on the immutable Stage10
binary and viewed alongside both original Java PNGs. Rods and flame now appear
comparably bright; the gold panel and red/white TrainHat details are visible in
the same region as Java. The previous missing hat is resolved. Different terrain
backgrounds, floor/cage shading, particles and animation phase remain visible.
These four images do not establish identical JSON-head/goggles shading, all
materials or all orientations, and do not establish full-frame pixel or
animation-phase parity.

Eliminated or limited hypotheses:

- The supplied JAR's `BlazeBurnerVisual` matches the pinned source's retained
  constructor decisions. This is not an established JAR/source mismatch.
- All fourteen imported native parts resolve to shaded faces without explicit
  per-face colors. That native-only observation did not establish source flags:
  the later actual loaded source probe found unshaded OBJ rods/flame. Merely
  changing native `Entity` to `Model` would retain their imported shading; the
  five explicit `Off` choices address the demonstrated boundary.
- API9 fullbright still applies its diffuse term. The relevant native shader and
  Catnip's entity-style diffuse calculation use the same classic formula; this
  alone does not establish identical baked inputs or the actual source path.
- A historical display failure prevented early observation. After the display
  became available, actual cases09/10 ran with Flywheel instancing and the
  registered skip-vanilla policy enabled. Read-only MIT Create method observers
  recorded zero `BlazeBurnerRenderer.renderSafe` calls, positive Visual frame
  counts and retained `isInert=true`/`goggles_small` selection in both cases.
  The public registry observation alone was insufficient; these actual method
  counters disprove the fallback hypothesis for this bounded live capture.
- An isolated original `BakedQuad.isShade` probe could not initialize the model
  loader outside FML access transformation. That failed setup is not accepted
  evidence about source baked faces.

`burner_backend_reference.py` captures only cases09/10 with the private diagnostic
bridge already running. Its one-shot public model observation reads loaded
`BakedModel`/`BakedQuad` metadata and public Flywheel `Material` getters, without
reading Flywheel implementation or private mesh state. It emits no vertex
positions or UVs; all model-derived results and PNGs remain private. The helper
does not launch a client or select a backend. The bridge observers count calls
only at the existing private fixture `(510,64,16)` and never cancel or change
render arguments/results.
