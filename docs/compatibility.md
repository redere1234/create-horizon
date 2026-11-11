# Original Create identifiers and data

Version 0.11.1 pins unmodified upstream Horizon, includes independent built-in
artwork, and retains local import of the original Create resources.
[Horizon and Nightly checks](official-horizon.md)

The 0.8.0-alpha.16 development checkpoint matches the original Deployer's
final visit before the bearing stops. Vertical Mechanical Bearings can land
in dry vanilla leaves, and blocked landings can still be retried after a
restart. Two moving Deployers can share one mounted chest and preserve their
stock, filters and visit state across restarts. Capture and restoration
currently share one chunk column.
[Contraption guide](contraptions.md)

The sections marked 0.3–0.5 below retain the released historical boundaries.
The installed review checkpoint is **0.6.0-alpha.2**: see [REPORT_06.md](https://github.com/Delete228/create-horizon/blob/eb8b96e8ea1db698b79bb61fd1caf6c963f31652/REPORT_06.md)
and [DEVELOPMENT_06.md](https://github.com/Delete228/create-horizon/blob/eb8b96e8ea1db698b79bb61fd1caf6c963f31652/DEVELOPMENT_06.md) for scoped integration evidence and
remaining differences. It adds limited schematic placement, bare-belt transport,
Basin/Mixer/fluid/heat processing and Press compacting, not complete Create parity.

For the new Press adapter, `Mode` retains WORLD=0, BELT=1 and BASIN=2.
`ParticleItems` is consumed once by client-update construction and is not saved;
empty later updates clear the client's retained field. The active recipe object
is transient and retained through datapack reload, not encoded as a new recipe
field in the save. Canonical input/output inventories retain unknown sibling
data; unsupported predicates/structures fail explicitly. The measured one-tick
kinetic startup difference is historical; the bounded 0.7 source-event/ticker-order
comparison supersedes it without adding a timer offset.

Version 0.7 adds `create:encased_chain_drive`
with entity type `create:encased_shaft` and the original 24 combinations of `axis`,
`axis_along_first` and `part`. The isolated original default is axis Y,
`axis_along_first=true`, `part=none`. Two source crafting recipes and the complete
source loot data are preserved. Ordinary interactions, six settled chain scenes
and real native restarts were checked in the alpha.1 build. Full propagation and
presentation parity remain open. [0.7 report](reviews/0.7-report.md)

The target's per-stack `minecraft:damage_resistant` canonical
`{types:"#minecraft:is_fire"}` maps to original 1.21.1 `FIRE_RESISTANT` presence.
Explicit removal overrides the default component. Recognized partial selectors
do not grant full-fire resistance; unknown/malformed selectors are conservatively
retained when no recipe applies. This is not a general component data fixer.
Actual recipes retain priority. The 0.5 default-only description below is historical.

The 0.7 generator adapter distinguishes source initialization, actual GUI/crank/
wrench/flow callbacks and raw NBT reads. An initialized motor's `/data` edit is
not an ordinary live settings action in original Create. Bounded Press/Basin
traces match 1,488 ordinary tick samples without time alignment; authentic
cold-loaded Java networks, source ownership and flicker/breakage remain pending.

The behavior reference is Create **6.0.10**, Minecraft **1.21.1**, source commit
`ac0c444d9828da3453ae8cc65338e8de063286fb`. The target is Horizon's Minecraft
**26.3** implementation. Cross-version Java world interchange is outside the
current requirement. Preserve upstream identifiers and data conventions when
implementing each feature, and test save/reload inside Horizon.

| Block / item ID | Block entity type ID | Implemented state / data |
| --- | --- | --- |
| `create:shaft` | `create:simple_kinetic` | `axis`, `waterlogged` (default false) |
| `create:cogwheel` | `create:simple_kinetic` | `axis`, `waterlogged` (default false) |
| `create:large_cogwheel` | `create:simple_kinetic` | `axis`, `waterlogged` (default false) |
| `create:flywheel` | `create:flywheel` | `axis` (default Y) and common kinetic data. Wheel speed and angle are client-side and are not saved. |
| `create:creative_motor` | `create:motor` | `facing`; `ScrollValue` int, default 16 |
| `create:mechanical_press` | `create:mechanical_press` | horizontal `facing`; `Running`, `Finished` bytes; `Ticks`, `Mode` ints (WORLD=0, BELT=1) |
| `create:depot` | `create:depot` | `waterlogged` (default false), no facing/open state; `HeldItem`, `OutputBuffer` |
| `create:gearbox` | `create:gearbox` | `axis` |
| `create:clutch`, `create:gearshift` | corresponding block ID | `axis`, `powered` |
| `create:hand_crank` | `create:hand_crank` | `facing`, `waterlogged`; `InUse` int, `Backwards` byte |
| `create:andesite_encased_shaft`, `create:brass_encased_shaft` | `create:encased_shaft` | `axis` |
| `create:andesite_encased_cogwheel`, `create:brass_encased_cogwheel` | `create:encased_cogwheel` | `axis`, `top_shaft`, `bottom_shaft` |
| `create:andesite_encased_large_cogwheel`, `create:brass_encased_large_cogwheel` | `create:encased_large_cogwheel` | Same state and common kinetic data |
| `create:encased_chain_drive` | `create:encased_shaft` | `axis`, `axis_along_first`, `part` (`none`, `start`, `middle`, `end`) |
| `create:adjustable_chain_gearshift` | `create:adjustable_chain_gearshift` | Same chain properties and `powered`. Integer `Signal` stores the analog redstone strength. |
| `create:millstone` | `create:millstone` | no block-state properties; `Timer` int, `InputInventory`, `OutputInventory` |
| `create:smart_chute` | `create:smart_chute` | `powered`, `Filter`, `FilterAmount`, `UpTo`, and the normal Chute cargo and position fields |
| `create:crushing_wheel` | `create:crushing_wheel` | `axis`, axial shaft at each end, 8 SU/RPM |
| `create:crushing_wheel_controller` | `create:crushing_wheel_controller` | Internal `facing` and `valid` states, `Speed` float and 32-slot `Inventory` with the original processing fields |
| `create:brass_funnel` | `create:funnel` | Dry vertical placement; `extracting`, `powered`, `waterlogged`, plain `Filter`, `FilterAmount`, `UpTo` and `TransferCooldown` |
| `create:item_drain` | `create:item_drain` | 1500 mB `Tanks`, transported `HeldItem` and `ProcessingTicks` |
| `create:mechanical_crafter` | `create:mechanical_crafter` | Horizontal `facing`, `pointing`, `Inventory`, `ConnectedInput`, `GroupedItems.Grid`, `Phase` and `CountDown`; 2 SU/RPM |
| `create:encased_fan` | `create:encased_fan` | six-way `facing`, default `north`; common kinetic `Speed` |
| `create:mechanical_drill` | `create:drill` | six-way `facing`, `waterlogged`; defaults `north`, false; `Progress`, `NextTick`, `Breaking` |

Static casings/storage blocks and alloy/metal/wrench items retain their upstream
`create:*` IDs. Encased shafts unwrap to and drop `create:shaft`.

Apply either casing to a dry cogwheel without consuming the casing. A matching
shaft neighbor opens its end at the time of encasing. Use a Wrench on an axial
face to toggle that end, or on a tooth face to rotate the axis. Sneak-use the
Wrench to restore the original cogwheel. The original casing models and moving
parts load from the optional JAR. Neighbor-connected textures, face-sensitive
pick-block and moving Encased Cogwheels remain pending. Horizontal schematic
transforms keep each shaft on the correct signed end of the axis.

The building-blocks tab includes the cut, polished cut, cut bricks and small
bricks variants of andesite, granite and diorite, plus layered andesite. Each
has its original stonecutting recipe and can be cut back into the corresponding
vanilla stone. The local Create JAR supplies their base models and textures.
Layered andesite uses its ordinary cube model while connected textures are
pending. The tab uses cut andesite as its icon until the ornate iron window is
available.

Zinc and Deepslate Zinc Ore use the original `create:zinc_ore` feature
with eight attempts, vein size 12 and height anchors −63 and 70. The pinned
Java config defaults to enabled generation. Horizon enables the feature with
the port and uses 26.3 world generation in new chunks. The original mining
tool tier, Silk Touch, Fortune and cooking recipes are retained. Raw Zinc
can be packed into its original storage block.

The downward Crushing Wheel pair takes supported inputs from a dry Chute
or catches falling stacks. It looks up Crushing recipes before Milling
recipes. The 45 bundled crushing recipes include supported raw metals and
their storage blocks, ores, Obsidian, Wool and Tuff. The wheels eject into
open space or transfer onto a Depot, where the top stack and output buffer
control backpressure. Unported items
stay in the Chute. The controller retains its original inventory and cycle
fields through a restart, and loose outputs retain the original bypass
data. The Experience Nugget currently drops as an item. Consuming it,
entity-specific collision and damage, and other directions and output
destinations are pending.

A vertical Smart Chute can use an ordinary item as a ghost filter. The
default configuration pulls up to 64 matching items at once. A powered
Chute parks its cargo halfway along the block and resumes after the signal
clears. The filter and cargo survive a restart. Hold use over the filter when
the Chute feeds an inventory to choose Up to or Exactly. The board uses the
sample item's stack limit. Special filters remain open.

Ordinary dry Chutes connect diagonally in four directions. A complete empty
line can be pasted from a source schematic with a horizontal rotation or
mirror. Loaded Chutes, airflow and partial diagonal routes need their own
import policy.

Horizontal Mechanical Belts can feed dry Chutes and receive their downward
output, even when the receiving Belt is stopped. An incomplete Belt or a
Chute that rejects the item holds the cargo upstream.
The same item and components continue after a restart. Andesite and Brass
Casing use the original per-segment states, and dye or washing changes the
color of the full Belt. Dry horizontal Belts carry grounded local players
across bare segments and segments with Andesite or Brass Casing. Sloped
Belts and other passenger types remain open.

The original JAR supplies the full scrolling strips for plain and dyed Belts.
The private import keeps both halves available to the renderer. Without a JAR,
the simplified Belt surface uses static vanilla textures.

Mechanical Crafters support manual front-slot loading and the original
5×5 Crushing Wheel recipe in a same-facing array inside one chunk column.
The finished stack drops at the front of the last Crafter or enters a Depot.
The phase, countdown and component-bearing grouped items can resume after
a restart. The 21-Crafter test matches all 62 Java ticks. A full 5×5 grid
can use a redstone pulse or four Crafter Slot Covers for its empty corners.
The finished stack can also feed down into an ordinary container or horizontal
Belt. A blocked receiver or stopped Belt keeps the remainder after a restart.
Ordinary shaped and shapeless recipes use the loaded crafting table's recipe
order, within a 3×3 occupied area. Mirrored patterns and empty cells follow
the normal crafting rules. A recipe marked `_manual_only` stays manual.
Equal item remainders occupy separate output
cells and wait for space, as with the three buckets from a cake.
Use a Wrench on the shared edge of two same-facing Crafters from an accessible
side or back to link or separate their inputs. Feeding any linked member by
hand fills available slots from the top row down, ordered by facing within
each row. Covered and busy slots are skipped, and empty-hand pickup stays
local. The group keeps Create's controller and relative offsets across saves.
Player removal repairs the surviving loaded members. Removal by commands
and disconnected groups with unloaded members remain pending.
The animation shows ingredients merging and the finished item turning, with
the export and crafting particles. Scrolling on the Crafter's small belts,
linked hopper and machine input, edge outlines and connected textures, special
recipes, mixed remainders and side insertion into a Belt remain open.

A downward Deployer can apply the original small and large cogwheel recipes
to cargo on a Depot or bare horizontal Belt. It also has the original
vanilla copper wax, unwax and deoxidation recipes. Those recipes keep the
Honeycomb Block or Axe in the hand, including the Axe's current damage.
Changing a filter during a stroke lets that stroke finish. While waiting,
the mod parks a mismatched hand until the player changes it. Java moves
it to an overflow inventory.

The Precision Mechanism recipe takes five rounds of three tools. A Depot
keeps the original `create:sequenced_assembly` component through an actual
restart, and Survival hand transfer retains it. A horizontal Belt can run
all 15 operations in a line of Deployers across a chunk boundary. The final
roll uses the original 150-weight pool. Client-side progress UI, creative inventory
round-trips and general sequenced recipe types remain open.


A dry vertical Brass Funnel can filter with a plain item sample. Downward
extraction uses the original eight-tick cooldown, a default limit of 64, and
the stored Exactly or Up to setting. Tap use over the filter to change its
sample. Hold use to open the amount board, then release to confirm the
selection. The same controls use a simpler panel without the optional
Create JAR. An upward collector accepts direct output from a downward
Crushing Wheel Controller or an adjacent upward Saw into an ordinary inventory.
The source retains cargo while the funnel is powered or its filter rejects
it. Airborne intake, special filter items and Belt Funnel variants remain
open.

An Item Drain accepts water or lava buckets from a bare horizontal Belt,
stores 1000 mB and sends the empty bucket to a neighboring Depot or Belt.
With an incompatible or full tank, it waits at the pour position. With a
blocked Depot or stopped outgoing Belt, it holds the bucket at the exit.
The checked flows match the pinned Java tick traces and survive a restart.
Right-click with either full bucket to pour directly into the tank. Survival
returns an empty bucket, Creative keeps the full bucket, and a refused pour
keeps the bucket and its components. An empty hand retrieves an item waiting
on the Drain. A comparator reads the tank's fill level, including through one
solid conductor. Java and Horizon match the two-tick delay after the checked
conveyor or hand pour. Other containers and pipe
connections are pending. The original JAR supplies the body model.
The bucket's highlight and its overlap with the stream still differ slightly.

A standalone Fluid Tank stores up to 8,000 mB of water or lava. In Creative,
right-click with a filled bucket to add 1,000 mB or an empty bucket to drain
1,000 mB. The held bucket stays the same. Survival uses vanilla bucket
interactions. A Wrench toggles the tank's windows, and a comparator reads
its fill level. The tank uses Create's original `TankContent` save format
and exposes the same storage on every side through Horizon's fluid capability.
The original JAR supplies the tank models and textures. The built-in model
uses vanilla copper and glass.

Stacked tanks and complete square boxes of tanks (2×2 or 3×3, up to 32 high)
act as one tank, as `ConnectivityHandler` forms them: the content is shared,
fills from the bottom layer up, and renders as one fluid volume. A Wrench
toggles the windows of the whole tank with Create's 2×2 corner and 3×3 edge
window shapes. Each block keeps its own 1×1 `TankContent` share in the save.
An irregular group splits like `ConnectivityHandler` does: from the lowest
north-west tank, the width holding the most tanks, grown upward; leftovers
become their own tanks. A comparator reads the whole tank. Boilers, moving tanks, goggles tooltips, splash particles and world light
from lava are pending.

Fluid Pipes connect to any adjacent pipe, tank, and pumps and valves along
their axis, following `FluidPipeBlock.updateBlockState`: corners, tees and
crosses keep their shape, a single connection opens the opposite end and a
lone pipe straightens toward where the player looks. Fluid flows through
straight runs and bends; tees and crosses are branches and do not carry flow
yet.

Fluid Pipes and a Mechanical Pump can move water or lava between two
tanks on a dry line without branches. The pump takes power from a cog and
pushes in the direction it faces. Use a Wrench to reverse the pump. Each side
can reach a tank through up to 15 pipes, including across loaded chunks.
After the line fills, a pump at 32 RPM moves 16 mB per tick. A full tank or one
containing another fluid blocks the transfer. The supported lines resume after
a restart. The original JAR supplies the pipe connections and tank collars.

A supported line can include one `create:fluid_valve`. Drive its perpendicular
shaft with positive RPM to open it or negative RPM to close it. At zero RPM
the pointer stays where it is, and the valve keeps its last fully open or
closed state. A closed valve still carries pressure and stops fluid transfer.
The save uses `enabled` and Create's `Pointer` compound. The Wrench rotates
the casing and changes the shaft and pipe axes as in Java while retaining
the pointer position. The original JAR supplies the block and pointer
models. Subtick pointer interpolation is pending.

Bends, branches, waterlogged pipes, open ends, multiple pumps on one line and
connections to other fluid machines are pending.

The four sheet items retain `create:iron_sheet`, `create:golden_sheet` and
`create:copper_sheet` and `create:brass_sheet`. Kinetic entities retain `Speed` as a float. Depot data
uses `HeldItem.Item`, `Pos`, `PrevPos`, `Offset`, `PrevOffset`, `InSegment`,
`Angle`, `InDirection`; its eight output slots use `OutputBuffer.Size` and
`OutputBuffer.Items`. The creative tab uses upstream `itemGroup.create.base`.
All original locale files are imported unchanged from the player's supported
JAR; they are not included in the public repository.

## Present limits

This is an identifier/data convention baseline, not a completed Java serializer.
Horizon also saves its generic `Items` container field. Item stacks use Horizon's
26.3 item codec. Belt deliveries store the current and previous transport
positions of the Depot's held item. Hopper insertion and extraction follow
the ordinary Depot rules for its held slot and output buffer. A Java Depot's
`HeldItem` still needs an import path into Horizon slots. Waterlogged placement
and fluid ticks remain open.

Network serialization (`Source`, `Network`) is not fully represented yet. The prototype also stores diagnostic `Capacity`, `Stress`,
`NetworkStatus` and press bookkeeping `Applied`/`LastTick`; these are port-specific
extra fields. The `create_horizon.Ports` compound stores diagnostic physical port speeds.
Gearbox `Speed` uses a fixed reference port rather than Create's source-facing
basis; physical port ratios are preserved. Hand crank rendered motion now uses the original independent/chasing angle. Complete that schema alongside the corresponding behaviors, retaining
unknown loaded fields and documenting migrations. Existing 0.1 block entity IDs
remain accepted at runtime; newly placed blocks use the canonical type IDs above.

## Evidence

`tools/placement_oracle.py` compares Rust decisions to AST-extracted original
Java methods for 27,648 contexts. `tools/smoke.py` tests actual player placement,
depot exchange without a menu, item counts/components and save/reload, as well as
the small powered press chain. These tests do not establish full Create parity.


## 0.3 behavior boundary

The ordinary depot uses default `bulkPressing=false`, nine internal slots, direct
top exchange and a dynamic automation insertion predicate. Wire update tags carry
an explicit empty `HeldItem` compound when clearing the client; saved empty depots
omit it. This accounts for Horizon's merge semantics without leaving a stale item.
Motor updates use a bounded custom channel with server validation of packet size,
range, player, distance and target block; they do not implement Create's packet format.

The graph covers loaded components up to 4096 nodes, four-port gearboxes and split
clutch halves. Compatible generators choose the faster driver. Inconsistent cycles,
opposing sources and excessive speeds conservatively stop the component; original
breakage/network rebuilding is incomplete. Server configs are currently pinned to
the relevant Create defaults. World item scan timing/scatter, particles, random
sound variation, water and some collision/interaction shapes need later parity work.

## 0.4 data and behavior boundary

`create:speedometer` and `create:stressometer` retain `facing`, `axis_along_first`,
`Value` float and `Color` int. `create:vertical_gearbox` is an item alias for the
original `create:gearbox` block; normal/vertical recipes and axis-sensitive drops
use upstream IDs. `create:goggles` uses the head equipment slot and the original
3D head model through Horizon's item-display selection.

`create:water_wheel` retains six-way `facing`; `create:large_water_wheel` has `axis`
and `extension`. Both save `FlowScore` int and `Material.Name`, default spruce.
The invisible structural block uses the canonical `create:water_wheel_structure`
ID and `facing`. The port currently gives structural blocks a lightweight ticking
block entity to clean up missing masters; Java does not. The master also stores
`create_horizon.StructureReady` as a port-specific initialization marker.

World-axis angular transforms and crank motion have direct source/pose checks.
Gauge interpolation and comparator formulas are implemented with default config.
Native HUD layout, connection hints and rotation indicators remain provisional;
complete Java UI/Ponder/particle-provider parity is a later increment. Fluid
currents come from Horizon's vanilla sampler; Create's extra water-spread restriction
above wheel axes is not yet ported. Collision/selection shapes still include
conservative template approximations. This release adds generators, not moving
contraptions or fluid-handling machinery.

## 0.5 data and behavior boundary

The public catalog contains 24 block items and 15 standalone items: 39 creative-tab
entries, plus the internal water-wheel structural block. New item IDs are
`create:propeller`, `create:wheat_flour` and `create:dough`. The exported set has
123 source recipes and 35 tags. Processing includes 47 `create:milling`, ten
`create:splashing` and 19 `create:haunting` recipes with implemented Create or
vanilla inputs/results. Cooking uses Minecraft's real smelting, smoking and
blasting lookup; the exported dough-to-bread recipes remain
`minecraft:smelting` and `minecraft:smoking`, not invented Create recipe types.

The millstone has a fixed Y rotation axis, a shaft connection only underneath,
and the source small-cog connection behavior. Its source collision consists of a
16×6×16 base and a 12×10×12 centered upper part. One input slot and nine output
slots retain the original inventory names; Horizon also stores its generic
container representation and `create_horizon:millstone` bridge snapshot. Empty
hand collection takes output first, or input if no output exists. Recipe-filtered
automation, landed items, per-item probability rolls and timer handling are
implemented; native integration and save/reload coverage are recorded separately
in `VALIDATION.md`.

The fan's shaft is opposite `facing`; both directions and all six orientations
are represented. Airflow range, push/pull choice, processing segments, partial
obstacle sampling, propeller speed and stack-dependent processing timers are
source-derived. Current targets include dropped items, cargo on Depots and
Belts, local players and mobs. Water washes, lit ordinary fire and campfires
smoke, soul fire and soul campfires haunt, and lava blasts. Blasting can
destroy items, including smokeable food, according
to the source policy; it is not a general-purpose way to cook food.
The blasting adapter reads the effective fire resistance, including the
supported per-stack full-fire component override and explicit removal.
Other damage selectors keep their original data and need separate parity checks.

`create:fan_transparent` and block/fluid `fan_processing_catalysts/*` retain the
supported source entries; unavailable Create blocks are omitted. Until the API
exposes fluid-tag queries, the adapter recognizes vanilla water/lava IDs and
waterlogged blocks explicitly. This is not arbitrary mod-fluid compatibility.
Recipe caches refresh when server data loads or reloads.

Depot-held progress uses `HeldItem.FanProcessingType` and
`HeldItem.FanProcessingTime`. Dropped-item progress now uses the original
`NeoForgeData.CreateData.Processing.Type` and `Time` entity NBT fields, retained
through Horizon's existing persistent unknown-field storage. Native save/reload
tests verify the exact remaining timer, preserved unknown sibling keys and
one-time conversion. Normal unfrozen play has been checked for player push,
pull and smoking damage. Live Java and Horizon checks also agree on mob
effects at a dry-to-haunting boundary, including Java's single-precision
position at the fan face. A frozen motor-start check still needs investigation.
Other entity types and further particle, sound and collision cases remain open.

The stationary mechanical drill uses the source rear shaft, six orientations and
12-pixel directional casing collision. Its front target, progress and retry timing
follow `DrillBlockEntity`/`BlockBreakingKineticBlockEntity`; ordinary block loot is
used rather than creative-mode drops. Its new crafting recipe uses the existing
alloy/casing/iron ingredients. Contraption movement, entity damage and automatic
target placement are outside this increment.
The native destruction path also leaves Create's cobblestone-generator shortcut,
ice-specific melting and custom zero-motion drop spawning for a later increment.

## Behavioral parity strategy

Rust organization follows the native runtime and may combine several Java
classes into cached data and small functions. Acceptance depends on observable
behavior, not a class-for-class translation. The existing AST-based oracles
compare selected unchanged Java method bodies against Rust with restricted
development contexts; they do not run the full original mod.

The paired schematic checks paste the same authored 1.21.1 files in Create
and Horizon. For a supported palette, put the file in the Horizon instance's
`schematics` folder and use
`/create schematic paste FILE.nbt X Y Z [quarter_turns [mirror]]` in Creative
with operator permission. The mirror values are `none`, `left_right` and
`front_back`. The mirror is applied first, followed by zero to three clockwise
quarter turns around the supplied anchor. The placement can extend into
negative offsets from the anchor. The transformed palette is limited to
verified simple blocks, logs, shafts, Flywheels, Creative Motors, Mechanical
Presses, Depots, empty horizontal Belts, unlinked Crafters and inactive
empty Deployers in USE mode. Unsupported Deployer data or an unsafe
destination refuses the paste before any cells are written. See the
[paired checks](../VALIDATION.md) for the layouts.
Cross-version world interchange remains outside the supported scope.
