# Belt connector preview

The review world starts beside three shafts with a Mechanical Belt in hand.
Right-click the horizontal shaft at `720 80 51`, then aim at either endpoint.

| Endpoint | Expected |
| --- | --- |
| Horizontal shaft at `720 80 55` | Green dust. A second right click builds the belt and clears the preview. |
| Vertical shaft at `720 80 47` | Red dust. A right click leaves the shafts and the selected first endpoint in place. |

The first lane, near `720 80 40`, is already assembled and powered. The
preview is a separate client effect from the animation of that lane.

`tools/belt_preview_checks.py` captured the same accepted and rejected clicks
in Java Create 6.0.10 and Horizon. The Horizon trace also verifies that no
preview is emitted before selection or after the successful connection.
The projection test covers snapping, a vertical shaft and the length limit.
The captures do not establish frame-by-frame animation, every aiming edge
case or multiplayer parity.

Passenger movement and the surface animation audit remain open. Passenger
motion needs a contact boundary that can work with static and moving surfaces.
