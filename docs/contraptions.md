# Contraptions

Create for Horizon uses one structure format for moving blocks and keeps the
driver rules in `create_engine::contraption`. The reference is Create 6.0.10
for Minecraft 1.21.1. The implementations share local coordinates and motion
rules while using Horizon's block, item and player APIs.

| Layer | Responsibility |
|---|---|
| Capture | Discover a payload through block movement and attachment rules. Store original identifiers and full block states in local coordinates. |
| Drive | Mechanical and Windmill Bearings, both hands of the Clockwork Bearing, and the regular and sticky Mechanical Piston advance their own poses. Rope Pulleys share the linear actuator, while Gantry Carriages follow a loaded rail. |
| Ownership | The structure belongs to the chunk, independently of the driver. It is saved with the removal of the original blocks. Removing a driver leaves a recoverable record if a block obstructs the landing. |
| Presentation | The client receives geometry at capture and tracks it with small pose updates during motion. The rendered pose interpolates across packet arrival and local frame boundaries. Collision uses the authoritative pose. Original resources remain an optional local import. |
| Contact and actors | Horizon's normal collision paths handle moving geometry. Riders follow horizontal and translating platforms, and a rising blade can lift a rider on a bearing rotating around X or Z. Moving harvesters, saws and drills use the original crop or block rules and Horizon loot. |

The current native adapter keeps each structure's source blocks, landing cells
and persistent record in one loaded chunk column so they share a chunk save.
Older saves with geometry and pose in one record are read and converted on
the next update. Landing removes both attachments.
A rotor can pass through a neighboring loaded column between snapped poses.
The adapter refuses unsupported snapshots and most occupied landing cells
instead of discarding blocks. Capture is limited to an allowlist of stateless
blocks and idle tools. This includes ordinary dyed concrete, stained glass
and unglazed terracotta. The paired bearing check mixes them with wool and
compares the quarter-turn landing after a native restart. Dry oak and smooth
stone slabs keep their registered half-block or double-block collision. A
half-turn about X or Z flips their top or bottom state at landing. A vertical
Mechanical Bearing can carry a Deployer.

A Mechanical or Windmill Bearing can carry up to 2,048 blocks of eligible
plain stone, slime, glass, terracotta, wool or concrete. The source and snapped
positions must still fit in one loaded column. Other cargo and other drivers
retain the 64-block limit.
A vertical Mechanical Bearing, Gantry, Rope Pulley or Mechanical Piston can
carry an ordinary chest or closed barrel. All four can use the three chassis
variants to expand capture. The supported Gantry path has a fixed loaded rail
span.
The Rope Pulley supports dry rope and cargo. The clockwork hands are captured
and restored together and currently accept vanilla payloads only.

The Mechanical, Windmill and Clockwork Bearings expose the pinned Java
settings boards. Hold Use on the active value box and release on a choice.
The Mechanical and Clockwork Bearings have three choices. The Windmill
Bearing has two directions and updates its output when switched while moving.
Regular and Sticky Mechanical Pistons and the Rope Pulley use the linear
movement board. A waiting actuator can retain a manual assembly request until
a new selection or speed change wakes it.

Right-click a mounted ordinary single Chest or closed Barrel where its driver
supports that storage. The generic inventory has 27 slots and uses the current
bank shared with automation. The block that the player actually hits selects
the bank on a rotor with two separate containers. The screen closes when the
structure lands or leaves range. The menu uses Horizon's inventory actions
with each click applied before the next packet. Named, locked and double
chests are outside the supported capture rules.

Collision uses exact boxes at quarter turns, narrow strips for oblique rotation
and the registered shapes of piston parts and tools. Grounded transfer uses the
surfaces of full blocks, supported dry slabs and dry straight stair treads.
Translating platforms and bearing side contact resolve overlap before clipping
against ordinary terrain.
An X- or Z-axis bearing uses the vertical pass of Java's
`ContinuousOBBCollider`. It clips separation and horizontal contact-point
motion independently. The local client applies these corrections at the player
tick and includes them in the camera and body interpolation.

The solver matches the pinned JAR for separation, surface contact and time of
impact on all three axes. Live player trajectories still differ at some bearing
angles. Compound rotation, exact sub-tick timing, moving block bounce and
sliding, and full mob contact remain open. Sable integration remains a separate
milestone.

For supported Y-axis rotors made of full collision cubes, dropped items use the
ordinary item tick followed by Create's contact pass at the end of the level
tick. A stone tip carrying an item through a loaded neighboring column matches
the Java trajectory. Bounce on moving slime, overlapping rotors, and contact
for other moving structures still need separate parity checks.

The Harvester handles wheat, carrots, potatoes, beetroot, Nether Wart, cocoa,
sweet berries, sugar cane and supported leaves or growing plants. Its moving
blade rolls by distance, using the Flywheel phase calculation. A stall or
backwards travel holds the current blade phase. The moving Drill accumulates
head rotation in the direction of operation and while cutting. The moving
Saw pauses its platform while cutting supported vanilla trees, fungi and
stalks, and selects its blade from the actual stalled state.
A horizontal stationary Saw also fells trees. The moving Drill breaks eligible
vanilla blocks and drops their loot. The Plough tills exposed soil, clears
snow and protects crops rooted in farmland. When a living mob overlaps a
visited non-conducting cell, the Plough adds the source impulse. In the tested
Mechanical Bearing setup it launches the mob on the same tick as Java. The
Saw and Drill use the previously published bearing pose and resume their
cutting target and progress after a restart. Player throws, falling blocks,
full mob contact and block-breaking damage remain open.

An upward stationary Saw strips logs, bark blocks, stems, hyphae and Bamboo
Blocks, cuts stripped wood into planks, and cycles through plank shapes and
stonecutting results. It also cuts Andesite Alloy into six shafts. Drop an
item on the powered blade. The default Saw takes one input at a time and
outputs in the direction set by the shaft and rotation. A neighboring Depot
receives the stack directly. The Saw waits if the Depot holds a stack or
has items in its output buffer. An adjacent Millstone takes suitable items
through its normal input and leaves any remainder in the Saw. A bare Belt
takes the stack at its inline or side entry when space and direction permit.
In open space the Saw ejects the result.
The saved `RecipeIndex` and ordinary output filter select the next recipe in the pinned
Java order. A Saw with no matching recipe passes the item through unchanged.

The Saw uses Horizon's loaded stonecutting recipes with 1.21.1 ID aliases
where needed. Four additional 26.3 outputs from ordinary stone are excluded
from the Saw's cycle. Vanilla stonecutters retain their complete recipe list.
The source recipe order is checked for the original pack set. Extra datapacks
can change that order in Java. Click the upward Saw's filter slot with an
ordinary item to copy a visible sample without consuming the held stack.
An empty hand clears it. Advanced filters, hover feedback, missing Create
decorative outputs, automation and cutting particles remain open.

Up to two off-center, downward Deployers on a vertical Mechanical Bearing
can plant ordinary saplings or apply bone meal to a supported crop or oak.
Each hand refills independently from one mounted chest according to its saved
filter. Set a plain sapling or bone meal filter by clicking one of the two
side slots with the corresponding item. An empty hand clears it. Stop the
bearing to exchange the held stack by clicking the hand.
The hands, filters and sampled positions survive a restart. A stationary
downward Deployer plants saplings in the cell two
blocks below its body. A stationary Deployer in Use mode shows its ordinary
sapling in the extending hand, using the original fixed or spinning display
pose. The moving renderer shows a bare pointing hand even when its inventory
contains saplings, as in Java. A stationary downward Deployer also uses
ordinary bone meal on supported crops and oak saplings. Punching, general
item use, filter hover UI and advanced filters remain open.
[Deployer engine and host boundary](deployer.md)

## Super Glue

Use Super Glue on two connected blocks to store the selected volume. Sneak-use
on a block or change the held item to clear the first corner. With glue in hand,
attack a block through an existing volume to remove that volume. Survival uses
the two durability calls in Create 6.0.10. Creative leaves the item intact.

Volumes currently fit in one loaded chunk column. Mechanical and Windmill
Bearings transfer them with their payload and restore them at the snapped
landing pose. Gantry, dry Rope Pulley and Mechanical Pistons transfer volumes
relative to their current cargo origin, including starts away from zero stroke.
A piston carries glue on its cargo. A volume that crosses its head or pole
is refused before assembly.
A volume that would be split or include a stationary block stops capture.
The mounted volume shares the chunk save with the structure. The first corner
emits a slime-ball burst on the clicked face. Confirming or removing the volume
emits particles at half-block intervals along its edges. Selection outlines
and transfer on other drivers remain open.

Hold Super Glue in your offhand while placing an ordinary block to glue it
to the face you placed it against. A new connection uses one point of durability in
survival. Replacing a block inside an existing glue volume uses none.
A placement ray that hits a nonadjacent block cancels the placement. A ray
that misses allows ordinary placement without glue.
Offhand placement works within one loaded chunk column. Fluid-specific and
Create alias placement paths, custom glue entity data, and the face burst
for other players tracking the placement are still pending.

## Mounted inventory

An ordinary dry single chest keeps all 27 slots and item components on a
vertical Mechanical Bearing, Gantry, dry Rope Pulley or Mechanical Piston.
Harvesters, Saws and Drills on that structure insert loot from the same chunk
column in ascending slot order, matching Java's `ChestMountedStorage` and
`ItemHandlerHelper.insertItem`. Overflow and loot from neighboring columns
drop at the tool. The server saves the inventory with the structure's chunk
and restores it at its rotated or translated landing position, including
after a restart or controller removal.

A plain closed barrel uses the same 27-slot save path. A Mechanical Bearing
rotates its lid direction with the structure. Gantry, Rope Pulley and regular
or sticky Mechanical Piston translate one chest or barrel. Open barrels and
barrels with names, locks or pending loot tables are refused.

A vertical Mechanical Bearing can carry two closed ordinary chests, two
closed barrels or one of each within its loaded chunk column. The order
matches the original Java local-position hash buckets and preserves capture
order when two banks share a bucket. The saved one-bank format is unchanged.
The two-bank format stores each 27-slot inventory under the same controller
and restores both together after landing, including an obstructed restart.

A vertical Mechanical Bearing can land through ordinary dry vanilla leaves
when the incoming block has collision. The leaves use the usual block-break
effect and bare-hand drops after the assembly lands. Logs, waterlogged
leaves and other obstructions keep the structure parked.

A Portable Storage Interface on a vertical Mechanical Bearing can dock that
chest with a stationary interface and a vanilla hopper or dry vertical Chute
below. A dry Chute above the dock can supply the moving chest and holds
anything the chest could not accept. Both directions preserve the components.
[Portable Storage Interface](portable-storage.md)

Access the inventory after landing. Moving menus, more than two banks,
double chests, named, locked and loot-table containers are outside the
current adapter.

## Controller settings

Hold Use while aiming at the controller's settings icon. Release Use to save
the highlighted option. Bearings put the icon on the faces beside their
rotation axis. Mechanical Pistons put it on the faces clear of both the shaft
and the extension. Rope Pulleys put it on top.

| Controller | Settings |
| --- | --- |
| Mechanical Bearing | Always place when stopped, only place near the initial angle, or only place when the anchor is destroyed |
| Windmill Bearing | Clockwise or counter-clockwise, including while it is running |
| Clockwork Bearing | Hour hand first, minute hand first, or 24-hour hand first |
| Mechanical Piston, Sticky Mechanical Piston and Rope Pulley | Always place when stopped, place only in the starting position, or place only when the anchor is destroyed |

Each selection is saved as Create's `ScrollValue`.

## Windmill sails

Windmill Sail Frames and all sixteen sail colors use the original block IDs,
placement orientation, dye and shear rules. The item placed in Survival counts
as one sail, and recoloring preserves the dye stack. A Windmill Bearing counts
the attached sails in its rotation plane. Eight sails or frames generate 1 RPM.
The optional local Create JAR supplies original models and textures. The built-in
pack supplies sail shapes and vanilla-derived materials. Placement previews,
canvas bounce and fall damping remain open.

## Chassis

Linear, Secondary Linear and Radial Chassis expand capture on vertical
Mechanical Bearings, dry Gantry Carriages, dry Rope Pulleys and Mechanical
Pistons. Sticky faces and ranges are restored after a quarter turn or a linear
translation, including recovery after a restart and an obstructed landing.
[Chassis rules and verification](chassis.md)

The Sticker latches its head on each rising redstone edge. An extended
Sticker joins its front block when the latter supports the attachment.
The capture walk can find the same bond from either end. The stationary head
moves at the source rate and plays the slime-ball burst and sound when it
reaches a supportive block.
[Sticker rules and verification](sticker.md)

## Minecart contraptions

The Cart Assembler engine covers the five rail modes, assembler placement and
rail swaps, the pass queue and cooldown, and assembly and landing decisions for
single and coupled carts. It also computes single-cart turning and both
coupling corrections. The pinned Java sources are `CartAssemblerBlock`,
`CartAssemblerBlockEntity`, `MountedContraption`, `OrientedContraptionEntity`,
`CouplingHandler` and `CouplingPhysics`.

The native adapter still needs cart-aware rail lookup and collision shapes,
an authoritative rail-pass callback, and a moving payload saved and synced
with the cart. Coupled movement also needs the two carts' persistent links and
controller motion. The current implementation is exercised by Rust unit tests.

## Verification

- `tools/bearing_value_settings_checks.py` opens the original bearing boards in
  Java and Horizon and checks selection, restart and live windmill reversal.
  `--actuators` checks both piston variants and the rope pulley, including the
  active faces and the landing of a running piston after a mode change.
  `--actuators --queued` checks a short click queued while an unpowered piston
  waits mid-stroke for a mode change.
- `tools/bearing_reference_checks.py` and `tools/bearing_native_checks.py` compare
  three axes at 32 RPM against Java. The Horizon test also reloads a running
  structure and recovers it after the driver is removed and an obstruction is
  cleared.
- `tools/piston_checks.py` compares extension and retraction across four rigs,
  including opposite axes, a sticky payload and blocked travel: 176 tick
  samples plus final block states. The native test reloads mid-stroke and
  recovers a blocked orphan on a second restart.
- `tools/clockwork_checks.py` compares the three original modes and both hand
  angles, with native checks for grouped restoration, restart and an obstruction.
- `tools/pulley_reference_checks.py` and `tools/pulley_native_checks.py` compare
  48 ticks and 80 block observations against Java. The native run also checks
  restart, controller removal and breaking a placed rope.
- `tools/gantry_reference_checks.py` and `tools/gantry_native_checks.py` compare
  Java motion and stopped blocks. The native run checks powered pinion output,
  restart, blocked placement, reversed travel and vertical orientation.
- `tools/gantry_chassis_checks.py` checks sticky capture and translated landing
  in Java and Horizon. It also exercises native save recovery and refused
  snapshots.
- `tools/gantry_glue_checks.py` and `tools/pulley_payload_checks.py` check
  ordinary Super Glue clicks, capture away from the zero-stroke position, a
  cold native restart and restored bounds. The pulley also carries a chassis
  with its selected range and sticky row.
- `tools/cart_assembler_reference_checks.py` checks a regular minecart, a
  powered controller rail with a chest cart, a rejected TNT cart and a coupled
  payload released onto two original assembler rails in Java.
- `tools/cart_coupling_math_checks.py` compares 722 rail corrections bit for
  bit with `CouplingPhysics.followLinkOnRail` in the original JAR.
- `tools/super_glue_reference_checks.py` observes the original selection,
  durability and removal. `tools/super_glue_native_checks.py --transfer` reads
  saved volumes before and after restart, removal and bearing landing.
- `tools/super_glue_offhand_checks.py` and
  `tools/super_glue_offhand_native_checks.py` check ordinary block placement,
  survival durability, nonadjacent cancellation and a refused support face.
- `tools/sticker_checks.py` compares rising and falling redstone edges,
  placement next to a powered block and five bearing capture layouts.
- `tools/contraption_collision_checks.py --player --piston --side` verifies
  player and dropped-item movement in a disposable Horizon world.
  `tools/contraption_contact_reference_checks.py` records the unobstructed
  push and both wall exits on the original Java client.
- `tools/piston_interaction_checks.py` verifies applying slime, preserving the
  facing and shaft axis, wrenching retracted pistons and breaking a pole in
  both clients.
- `tools/piston_payload_checks.py` checks chassis and glue on ordinary and
  sticky strokes, including a saved moving payload and a refused glue volume
  crossing the piston head.
- `tools/contraption_contact_oracle.py` runs 945 comparisons against the
  discrete horizontal resolver in the pinned original JAR.
- `tools/rotary_contact_oracle.py` compares 17,280 upright contact cases with
  the pinned JAR. `tools/rotary_contact_checks.py` checks mirrored lateral pushes,
  a wall slide and an untouched player in the real clients.
- `tools/plough_checks.py` compares forward and reverse passes, including
  grass, coarse and rooted dirt, farmland crops, three snow layers and drops.
- `tools/plough_throw_checks.py` compares one strict mob overlap and three
  controls against Java. The launch tick matches and the impulse vector
  differs by less than 0.0002 blocks per tick in the recorded scene.
- `tools/bearing_actor_phase_checks.py` compares 140 Java and Horizon ticks
  across a Saw and a Drill stall, including the cut and resumed rotation.
  `tools/moving_cut_restart_checks.py` checks 46 subsequent ticks per tool
  after a cold Horizon restart during the cut.
- `tools/deployer_held_checks.py` captures both clients in five states with
  the same camera. The three fixed sapling poses have the same visible bounds.
- `tools/harvester_blade_checks.py` compares 1,600 blade angles with the
  actual Flywheel actor class from the pinned Create JAR. A separate Horizon
  capture checks changing blade poses during single-player bearing travel.
  The `--drill` mode compares 2,400 head angles across all six faces.
- `tools/deployer_farm_checks.py` and `tools/deployer_refill_checks.py --combined`
  compare planting ticks and chest slots, then test a restart and a shared
  Saw and Deployer rotor in Horizon.
- `tools/deployer_moving_meal_checks.py` checks two hands sharing a chest and
  resumes immediately before planting and fertilizing. It covers ordinary
  wheat, a blocked oak, an open oak and a refused third Deployer.
- `tools/deployer_filter_checks.py` checks ordinary item samples, the two
  shaft orientations, an untouched held stack and clearing the ghost.
- `tools/portable_farm_supply_checks.py` compares dock and planting observations
  across 125 ticks and checks the final Deployer visit on shutdown. In both
  clients, eight saplings are planted, seven remain in the mounted chest,
  and one remains in the hand after landing.
- `tools/deployer_grounded_farm_checks.py` grows an oak through vanilla
  worldgen, joins a low Saw to the rotor by ordinary Super Glue clicks and
  checks same-cell replanting, stock and the cut tree across a restart.
- `tools/saw_processing_checks.py` compares 24 ticks for three stationary Saw
  inputs and checks ejection and resumption after a process restart.
- `tools/saw_recipe_checks.py` compares 29 cycles and 1,254 per-Saw tick
  observations for alloy, planks, stone and saved filters, including a restart.
- `tools/saw_filter_checks.py` exercises all four upward filter orientations,
  placement outside the slot, Wrench and an ordinary filter across a restart.
- `tools/portable_farm_checks.py` uses the same field and wood-cutting scenes in
  the two clients. It checks the crop or log left at the first swept cell and
  the exact item delivered to the stationary chest.
- `tools/loot_dialect_checks.py` checks ordinary drops after converting the
  pinned Create loot condition format to the Horizon runtime's format.
- `tools/actor_reference_checks.py` runs the original Java Create and Catnip
  classes against the Rust actor rules. `tools/actor_native_checks.py` verifies
  crop resets and drops, tree felling, drilling and motion after a cut.
  `tools/stationary_saw_checks.py` compares the horizontal Saw over 32 Java ticks.
- `tools/mounted_storage_checks.py` checks Java slot order, rotated landing,
  custom item components, a full chest's overflow and Horizon recovery after
  an obstructed landing and real process restarts.
- `tools/linear_storage_checks.py` checks a dry single chest on Gantry, Rope
  Pulley, regular Piston and sticky Piston. It verifies source and destination
  states against Java, durability and custom components by slot, and blocked
  placement over a native process restart. A Gantry Harvester fixture checks
  replanting and delivery of the crop to its moving chest. `--barrel` runs the
  movement and storage checks with closed barrels, including sticky retraction.
- `tools/sail_reference_checks.py` and `tools/sail_native_checks.py` verify
  placement, dye, shear, axial exclusion and 1 RPM generation with eight
  sails or frames. The native runs cover restart, landing and both art packs.
- `tools/bearing_review.py` prepares a separate in-game review world. The
  checked world and screenshots are local artifacts, with no changes to the
  player's normal worlds.

[Original Java source](https://github.com/Creators-of-Create/Create/tree/ac0c444d9828da3453ae8cc65338e8de063286fb/src/main/java/com/simibubi/create/content/contraptions)
