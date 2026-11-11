# Deployer engine and host boundary

The engine follows the pinned Create 6.0.10 Deployer. It covers the stationary
stroke timer and hand pose, moving active point and trigger, item and target
checks, filtered inventory routing, and moving block-break retries.
The original block and entity ID is `create:deployer`.

| Original code | Rust responsibility |
| --- | --- |
| `DeployerBlockEntity` | Stationary phases, RPM timing, reach ray and hand extension |
| `DeployerHandler.shouldActivate` | Same block and filled bucket checks, and the downward belt distinction |
| `DeployerMovementBehaviour` | Active point two blocks ahead, cell entry, reverse-pass activation, mounted input and stall timing |
| `DeployerRenderer` and `DeployerActorVisual` | Extension along the current hand axis and the original stalled oscillation |
| `DeployerItemHandler` | Filtered insertion, matching hand stacks, overflow-first slots and protected filtered extraction |

Preserve the Java data keys `Mode`, `State`, `Timer`, `Powered`, `Owner`,
`Inventory`, `HeldItem`, `Overflow`, `Filter`, `FilterAmount` and `UpTo` when wiring the block entity. `Reach`
and `Fistbump` are transient client update values. The moving context has its
own `HeldItem` and optional stall `Timer`.

## Horizon integration

The pinned Horizon `Game::clip_ray` takes an explicit origin, direction and
reach. The exported `native_raycast` uses the window player's camera. The
Deployer needs the former with the two prescribed segments, and needs the
action to retain the prescribed target cell when the ray returns a different
cell. Bucket and sandpaper actions also need a temporary ray-world mask.

Horizon already has the normal block-item placement path in
`LevelBehaviour::place_block`. `Game::use_hand` constructs its `PlaceContext`,
applies item-supplied block state and block entity components, then handles
placement callbacks, events, sound and item consumption. That path can supply
the actual placement rules for a sapling. Its acting-player inventory, GUI and
event handling are currently tied to the live player. A server automation entry
point must carry its own hand and inventory, pose, owner identity and
permission context through the complete placement action.

The same boundary is needed for use-first, block use, item use, entity
interaction and attack. The existing native click and damage hooks observe
those operations. They do not execute them from an automation context. The
adapter needs the original consuming-result order and a way to suppress menus
for an actor while retaining the gameplay effects of block and entity use.
Block and entity loot must flow back to the actor inventory and its mounted
storage, with the source distinction for experience from mob kills. A mining
adapter also needs access to ordinary tool wear, harvest checks and block crack
stages under the actor identity.

## Moving tree-farm slice

The native adapter registers `create:deployer` with the original six-way
`facing`, `axis_along_first`, block entity ID and idle USE data. Clicking the
hand exchanges a stack of plain saplings or bone meal. A vertical Mechanical
Bearing can carry up to two downward Deployers away from its axis. They visit
the original active cells. Planting uses Horizon's ordinary `PlaceContext`
and block-item survival checks. Bone meal uses vanilla growth for oak
saplings, wheat, carrots, potatoes and beetroots. A valid use can consume bone
meal without growing a tree. A mature crop or invalid target keeps the stock.

An empty hand takes one item from the first matching slot of the shared
ordinary mounted chest before attempting the visit. Each Deployer keeps its
own filter and stock. Occupied cells and invalid soil leave a withdrawn
sapling in the hand.

The controller column stores the moving hand privately under
`create:mounted_deployer`, keyed by controller and the Deployer's position
inside the assembly. Version 1 saves with one Deployer per controller still
load. The movement tracker retains each hand's previous visit across restart.
Capture, landing and item consumption use the controller column's terrain and
attachment transaction. The restored block entities retain `Owner`, `Mode`,
`Filter`, `Inventory` and `HeldItem`. The native private slot backs ordinary
inventory spill. This slice runs on the integrated server, checks the border,
and accepts targets in the controller column. The general owner-aware item
and entity dispatch described above remains a separate API.

Refill accepts an empty filter or the canonical `Filter` stack for a plain
sapling or bone meal. The latter matches by item ID and skips unrelated slots. With an
empty filter, an unsupported item in the first occupied slot stops the
bounded adapter at that slot. The chest withdrawal and the new hand are saved
together, with placement consumption in the subsequent same-column write.

Centered actors, other drivers, PUNCH,
filter controls, complex filters and placement with custom item components
remain pending. The moving render uses the source pole and hand pose. Held item rendering and
shaft animation are pending.

Run `python3 tools/deployer_reference_checks.py` against the isolated Java
reference for the original stationary and piston planting. Run
`python3 tools/deployer_farm_checks.py --help` for the shared rotating layout,
tick comparison and native process restart. `tools/deployer_refill_checks.py`
compares the one-sapling blocked refill, depletion and restored chest slots.
Run `python3 tools/deployer_moving_meal_checks.py --help` for the shared chest,
simultaneous planting and fertilizing, and cold restart comparison.

## Stationary planting

A downward Deployer accepts plain saplings through the hand interaction.
Connect either shaft face and put plantable soil three blocks below the body.
The hand visits the cell two blocks below the body. It leaves the stock alone
if the target is occupied or the soil rejects the sapling. A redstone signal
prevents starting a new stroke. A stroke in progress keeps its phase and
timer when rotation stops and continues on the next powered turn.

The block saves `State`, `Timer`, `Powered` and the remaining hand stack. The
render update carries `Reach` and a timer sample for interpolation. The
animated pole, hand and shaft use the existing Deployer partial models.
Held item rendering, other stationary actions and filtered automation remain
open. `tools/deployer_stationary_reference_checks.py` records the Java state
sequence and `tools/deployer_stationary_native_checks.py` compares the native
sequence and cold reload of a paused stroke.

### Use and Attack

Click the hand with a Wrench to switch between Use and Attack. Wrenching the
body adjusts its facing or shaft axis. Goggles show the current mode, the
held stack and the stress impact. The stationary Deployer saves `Mode` as
`USE` or `PUNCH` and uses the corresponding original hand pose with the JAR.

An empty hand can flip a vanilla lever in Use. Attack follows the stationary
stroke cycle and passes new Belt cargo through. An operation already caught
by the Belt callback can finish after a mode change. Entity attacks,
block breaking, fist bumps and switching modes on a moving Deployer are
pending.

### Bone meal

A stationary downward Deployer in Use mode can hold plain bone meal and
fertilize an oak sapling, wheat, carrots, potatoes or beetroots two blocks
below it. Each successful vanilla use spends one item and emits the normal
growth effect. A valid sapling can consume bone meal without growing. The
Deployer can itself obstruct the trunk above an oak sapling, so allow the
tree a clear growth path before using this arrangement for a farm.

Invalid targets and mature crops still take a normal hand stroke and keep
the stock. The existing redstone lock controls the start of each stroke.
`tools/deployer_bone_meal_checks.py` compares the held count, target state
and stroke timer against Create 6.0.10.

## Survival crafting

Craft Rose Quartz from a Nether quartz and eight redstone dust. Craft either
Sand Paper from paper and its matching sand. Hold use with the Sand Paper in
one hand and Rose Quartz in the other. You can also aim at a dropped stack
within three blocks. A 32-tick hold polishes one item and consumes one of the
paper's eight uses in Survival. Releasing early returns the reserved item
with its components intact.

Craft an Electron Tube with a Polished Rose Quartz above an Iron Sheet. Craft
a Brass Hand with an Andesite Alloy above a row of three Brass Sheets, with a
fourth Brass Sheet below the center. Stack the Electron Tube, Andesite Casing
and Brass Hand vertically to craft a Deployer.

The original item art, translations and sanding sound are loaded from the
optional Create JAR. Built-in item models use vanilla sprites. The dedicated
first-person renderer, finish burst, copper scraping and Deployer polishing
remain pending. The local fixtures are `tools/sandpaper_reference_checks.py`
and `tools/sandpaper_native_checks.py`.
