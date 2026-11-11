# Clutch and Gearshift review

The creative review world has four motor-driven lines. Flip the lever on each
relay and watch the shafts on the side away from the motor.

| Relay | Coordinates | Motor drives toward | Lever on |
|---|---|---|---|
| Clutch | `850 80 40` | East | Output stops. |
| Clutch | `850 80 49` | West | Output stops. |
| Gearshift | `850 80 58` | East | Output reverses. |
| Gearshift | `850 80 67` | West | Output reverses. |

The input keeps turning at 32 RPM. Turning the lever off restores the output's
original direction. Stand beside the relay so both sets of shafts are visible.

`tools/transmission_checks.py` compared the `powered` state and four shaft
speeds before and after the same redstone commands in Create 6.0.10 and Horizon
26.3. The previous build differed in 12 of 44 observations. The new build
matched all 44, including the immediate stop, next-tick reattachment and two
signal changes before a tick. The saved native world was reopened and both
positions of all four levers were checked by right-clicking them.

The port batches the read-only Horizon neighbour notifications until its level
event drain. It then detaches the two halves and reconnects them at the start
of the next block tick when required. The Java reference is
`ClutchBlock.neighborChanged` and `GearshiftBlock.detachKinetics`/`tick`.
This comparison covers direct redstone changes on straight, single-source
lines. Signals that change multiple times within one neighbour update cascade,
multiple competing sources, and exact animation and sound remain open.
