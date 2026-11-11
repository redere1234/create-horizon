# Chassis

The capture rules use Create 6.0.10. The pinned Java entry points are
`AbstractChassisBlock`, `LinearChassisBlock`, `RadialChassisBlock`,
`ChassisBlockEntity` and `Contraption.moveChassis`.

| Block | State and grouping | Included payload |
| --- | --- | --- |
| `create:linear_chassis` | `axis`, `sticky_top`, `sticky_bottom`. Adjacent blocks of this variant and axis form a group on all six sides. | Each sticky axial face scans a straight row. Forced movement along a face enables that row without slime. The scan stops before air or brittle blocks. It includes a solid non-supporting endpoint and stops there. |
| `create:secondary_linear_chassis` | Same properties as Linear Chassis, with a separate group. | Same row scan. |
| `create:radial_chassis` | `axis` and four reference-orientation sticky properties. Adjacent radial chassis join along the common axis. | Each sticky face floods its axis-perpendicular plane through supportive faces within the strict `range + 0.5` radius. The flood skips air and brittle blocks. |

All three variants use the `create:chassis` block entity and its
`ScrollValue` integer. The default is 8 with a range from 1 to 16.
`engine::contraption::chassis` computes group links, included blocks and
rotated sticky faces from the host's movement classification.

## Current support

Chassis can expand a vertical Mechanical Bearing, a dry Gantry Carriage, a
dry Rope Pulley or a Mechanical Piston within one chunk column. Gantry and
Rope Pulley pass no forced direction into the attachment search. Pistons
pass their stroke direction, so a parallel Linear Chassis row can be taken
without a sticky face. A sticky piston can pull cargo back. The range of each captured
chassis is saved by local position and restored with its block state at the
rotated or translated landing. Unknown block-entity data, unloaded cells and
chassis offsets outside −15 to 15 on any axis fail before world edits.
The installed mod provides fallback models and loads the original models
from the optional local JAR.

Use a slimeball or Super Glue on a glueable face to make it sticky. Clicking
an already sticky face covers the other eligible faces. Sneak-click with an
empty hand to clear the targeted face. Applying slime leaves the stack count
intact. The linear variants inherit the axis of either linear variant when
placed against it without sneaking. A same-variant, same-axis neighbor
clears the covered sticky end on placement.

Hold use with a Wrench to open the range board. Linear Chassis shows
**Range of Sticky Sides** and Radial Chassis shows **Radius when Sticky**.
Select a value from 1 to 16 and release use to apply it. Ctrl applies it to
the connected group of the same type and axis. The attached-block outline,
offhand Wrench, connected textures and slime particles remain open.

## Verification

`tools/chassis_reference_checks.py` exercises two original Java bearing rigs.
`tools/chassis_native_checks.py` repeats their group and payload layout,
then checks obstructed recovery across restarts, rotated states and drops.
Use `--hand` for ordinary survival interaction. The Rust tests also cover
forced linear movement, rotation and unavailable cells.

`tools/gantry_chassis_checks.py --java` checks the pinned Java Gantry against
three shared fixtures. With `--game`, `--resources` and `--ctl`, the same
script checks the equivalent Horizon geometry, a blocked landing and recovery
over two restarts, recapture on the next run, and capture refusals that must
preserve every source block.

`tools/pulley_payload_checks.py` lifts glued cargo with a chassis and checks
the mounted data before a process restart and the landed ranges and volumes
after it. `tools/chassis_value_settings_checks.py` exercises the real board,
single and group updates, authorization, and the saved selection on reopen.
`tools/piston_payload_checks.py` covers both piston strokes, a radial branch,
saved range and glue ownership, and a volume that crosses the head.
