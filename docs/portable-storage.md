# Portable Storage Interface

The item interface uses the movement probe from
`PortableStorageInterfaceMovement` and the station state from
`PortableStorageInterfaceBlockEntity` in Create 6.0.10. The Rust engine keeps
both rules in `create_engine::contraption::portable_storage`. The inventory
bridge follows `PortableItemInterfaceBlockEntity`.

The rotating probe sits 1.85 blocks in front of the moving interface's center.
It checks its grid cell and one more cell in the nearest cardinal direction.
That direction must be within 0.5 of the rotated unit vector. The station
must face the probe and be unpowered. If the moving probe is about to pass
the center of its partner, the actor stalls and keeps the link alive. When
the station's timer reaches four, the actor releases its stall.

The station starts at timer 14. A live link permits item transfer while the
timer is in the inclusive connected window, from four through 64 at the
default timeout. Each successful real insertion or extraction resets the
timer to 64. A failed transfer or a simulation leaves the timer alone.
Comparator output uses the timer window. Item access also requires a live
owner. The saved `Timer`, `Distance` and `Powered` fields preserve the visible
state. The running owner and keepalive are rediscovered in the world.

`tools/portable_storage_reference_checks.py` records a 32 RPM vertical
bearing carrying a chest and a moving interface. A station supplies a hopper
with three wheat and two sticks that carry custom data. The fixture checks
the connection angle, extraction cadence, held angle, timer release, and
comparator wire. It then powers the station during an active transfer and
checks that the next revolution reconnects after power is removed.

Horizon supports one moving item interface on a vertical Mechanical Bearing,
one ordinary mounted chest, and a matching stationary interface in the same
loaded chunk column. Put a vanilla hopper directly below the stationary
interface to extract one item through its normal eight-tick cycle. A
[Chute](chute.md) in the same position pulls up to 16 matching items into
its ordinary transit. Both routes carry the original item components. A
rejected transfer leaves the stack in the mounted chest and the timeout
continues counting down.

A dry Chute above the same stationary interface feeds the moving chest.
It first simulates insertion at the midpoint, then commits at the exit.
Existing matching stacks fill before empty slots. The unaccepted remainder
stays in the Chute. A successful insertion refreshes the link. A full chest
or interrupted link leaves the source stack intact and does not refresh it.

The supplied fallback models use vanilla textures. The optional local JAR
provides the original casing, stem and head. The adapter renders the paired
parts at the current connection distance. The moving arm's Java chaser
interpolation, generic item capabilities, and fluid interfaces
remain separate steps. Craft the interface from a Chute and an Andesite
Casing. [Chute](chute.md)

`tools/portable_storage_native_checks.py` runs the shared geometry headlessly
and compares bearing, interface, hopper, chest and comparator observations
against the Java trace. Separate cases exercise an incompatible nearly full
hopper and a process restart during transfer.
`tools/portable_chute_input_checks.py` checks full, partial, tagged and
power-interrupted insertion in both clients, including a native restart.
