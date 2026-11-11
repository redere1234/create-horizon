# Burner definition synchronization

`burner_sync.rs` supplies the client half of Create6.0.10's burner interactions
with the authoritative server definitions. It uses existing native mod-message,
server-data and player lifecycle hooks; it adds no engine registry or network
ID convention. `BlazeBurnerBlockEntity.tryUpdateFuel` is the behavior reference
at source commit `ac0c444d9828da3453ae8cc65338e8de063286fb`. The portable burner
core owns admission order; the snapshot transports its inputs.

One server-generation snapshot contains the two merged fuel data maps, the
special/regular item tags, positive ordinary furnace burn times for registered
item IDs, and the merged capturable entity-type tag. Data-map contributions
from bundled content remain below world packs, including replace/remove rules.
Entity tags use the ordinary merged tag loader because the initial world-data
callback precedes command-store population. Definitions compile once per
generation, never in an interaction or warm tick.

`create:burner_data_v1` frames contain resource names, not local registry IDs.
The big-endian format has a magic/version, nonzero world/reload generations,
fragment index/count and total size. Limits are 2 MiB total, 24,000 payload bytes
per fragment, 8,192 entries per collection and 256 bytes per resource ID. Durations
must be positive signed 32-bit integers. Duplicate IDs, invalid names, malformed
lengths, conflicting fragments and trailing data are rejected. A receiver keeps
its previous complete generation until every newer fragment decodes; partial or
invalid data cannot replace the active definitions.

Login and reload enqueue the shared encoded snapshot. Each guest receives at
most four fragments per tick. `create:burner_data_request_v1` carries a fixed
versioned request; only current server players can request, with one enqueue
per 100 ticks. A client without a complete snapshot retries at that interval and
fails closed for fuel/capture prediction. Same-connection dimension replacement
retains the snapshot. Disconnect, reconfiguration without a level, failed world
open/close and final close clear the appropriate connection/server state.

Reproduce the controlled actual-Game checks after applying the complete native
mod through the official `horizon-mixins apply` pipeline into an owned stage:

```sh
python3.14 tools/burner_sync_checks.py \
  --stage .local/my-official-stage \
  --resources /path/to/private/prepared/26.3 \
  --target .local/my-sync-target
```

The runner restores its stage source files in `finally`, uses private homes,
and opens no game window or network listener. The test loads normal bundled
content and actual world packs; it exercises initial cake 3200/coal 1600,
reload removal/override, tag replacement, normal NativeNet/Hub packet delivery,
request throttling and logout cleanup. A normal Remote over a memory Pipe
exercises the actual client admission and prediction functions: 20 particles,
source flame kind, creative old-heat pre-skip, offhand, no heat/inventory writes,
rejected/cache-miss RNG preservation and dimension/disconnect cache lifecycle.
Three protocol tests cover multipart complete commit, stale generations,
malformed/truncated data, duplicate entries and bounds.

The controlled Game test is not a live joined-client handshake, audio/pixel
comparison or process-restart proof. Its older full-stage snapshot contains an
unrelated retired depot decoder which these tests do not call or validate.
Clippy is strict inside the two sync modules and their proof; unrelated existing
full-mod Clippy findings are outside that scoped result and retained in the
full-stage log. Actual launcher acceptance is recorded separately.
