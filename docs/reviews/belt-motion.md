# Belt motion review

Six lanes share the same layout in Create 6.0.10 and Horizon. Each starts with
four copper ingots on the belt and its Clutch powered. The lever nearest the
belt controls the Clutch. The farther lever changes direction through the
Gearshift. The review client starts in Creative so the elevated rigs are
accessible by flying.

| Facing | Level lane | Upward lane | Downward lane |
| --- | --- | --- | --- |
| East | `768 85 40` | `781 85 40` | `794 85 40` |
| South | `768 85 53` | `781 85 53` | `794 85 53` |

Release the Clutch to watch the stack move. Switch the Gearshift while the
stack is still on the belt to reverse it. Reapply the Clutch to stop it. The
levers are on the transmission blocks beside the motor.

## Press and Depot

The separate stand at `772 85 46` starts with the press disconnected. Apply
the copper ingots to the Depot by right-clicking its top. Watch the stack
slide from the side toward the centre. Toggle the lever above the Clutch
at `771 88 46` to power the press. Right-click the top with an empty hand
to collect the held sheet and any buffered output.

`tools/belt_motion_checks.py` assembled each lane through the real connector,
then seeded one known stack for each measurement. Both games retained the
stack's side offset. The item step matched in 16 of 18 observations, including
forward, stop and reverse on all four sloped lanes. In the south-facing level
lane, the Java controller and first middle segment named each other as their
source. It stayed at +32 RPM after the Clutch opened and after reversing the
drive. Horizon stopped and then ran at −32 RPM in that fixture.

Separate frame captures cover the rendered belt strips. After the atlas fix,
stripes stay visible at each sampled step on level, upward and downward runs.
Exact render phase, item shadows and multiplayer are still open. Passenger
movement remains in the shared contact work.

`tools/belt_replacement_checks.py` checks a level belt rebuilt as a slope and
a level belt rebuilt with identical states before the next server tick. The new
belt retains its own stock. The previous belt ejects its stack exactly once.
