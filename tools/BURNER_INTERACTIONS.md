# Burner interaction adapters

Behavior source: Create6.0.10, commit
`ac0c444d9828da3453ae8cc65338e8de063286fb`, methods in
`BlazeBurnerBlock`, `BlazeBurnerBlockItem`, `LitBlazeBurnerBlock` and
`IWrenchable`. No original model/texture/sound bytes are included here.

`mixins/create/burner_interactions.rs` handles empty ignition, shovel
extinguishing, regular-to-soul conversion, and empty-item capture from a spawner
or living mob. Inventory, durability, block writes, removal, particles and sound
use ordinary Horizon paths. `clone_item` returns only a fresh base item ID; the
caller must retain normal Ctrl-pick component/block-entity handling. Wrench
pickup belongs to ordinary state-aware block loot, not to clone serialization.

Preserved details:

- Soul conversion consumes no item; a water bucket does not extinguish this block.
- Empty spawner potentials consult next spawn data. Nonempty potentials scan all
  entries and never fall back to the next data. The spawner is not consumed.
- Living capture discards without death loot and source FAIL suppresses the arm
  swing. Spawner capture answers SUCCESS and swings once.
- Capture requests40 flame and40 smoke particles in source order. Original smoke
  coordinates omit the capture origin's X/Z; this is preserved.
- Shovel wear deliberately uses the source MAINHAND break-event slot even when
  the damaged stack is in the offhand. Flint uses the acting hand's slot.
- Capture sounds are server-owned HOSTILE events. Block interaction sounds are
  client-predicted BLOCKS events, with the actor excluded from the server copy.
  Client/server random streams are independent.

`burner_prediction.rs` is injected into `game/remote.rs`. Its two Game methods
own only recognized burner turns, send the ordinary sequenced UseItemOn or
Interact packet, then perform the local effects/result. The surrounding
remote_use_block item-height behavior remains native. Spectator clicks pass,
and an entity action the ordinary client consumes retains priority. The HEAD
adapters in `burner_predict_{block,entity}.rs` preserve that client turn. Server
capture uses the pending `native_item_interact_mob` fallback after normal entity
actions have passed; its first `Some(false)` ends the turn without a swing.
The earlier API29 claimed-entity phase remains unchanged. Until the fragment is
stamped, the adapter names the exact pinned source target.

The source actor-excluded route is exact-pinned only to
`remote::hand_operated`, recognizing the two burner IDs. Horizon's normal Audio
capture must preserve its resolved SoundSource through the guest queues; the
separate generic captured-sound-source fix supplies that boundary. No custom
sound drain or global category heuristic is inserted by this mod.

Reproduce the actual Game check in a disposable copy of the full official-apply
stage. Never pass the stable build cache or pinned runtime checkout. This
77f7 test uses the actual compiled Create modules and injected callbacks:

```sh
python3.14 tools/burner_interactions_adapter_checks.py \
  --stage .local/burner-adapter-77f7/stage \
  --revision 77f7afbebd722e2f21b4e1001ffd7cd1901db9e1 \
  --resources /path/to/prepared/26.3 \
  --target .local/burner-sync-target
```

The runner appends only a cfg(test) probe and restores that copied source in
`finally`. It does not replace production modules, fuel logic or callback
wiring. It uses private homes/resources and opens no window or listener.
Clippy is strict for the test module; inherited full-mod findings are outside
that scoped lint result. The report records the exact production source hashes.

The fixture distinguishes direct prediction-helper assertions from real normal
entity interaction: an actual world pack tags villagers, Panda and zombies;
the injected server callback lets a tagged villager trade, captures ordinary
and Panda-pass targets, preserves offhand exchange and FAIL-without-swing,
and leaves an untagged mob alone. The actual Remote adapter checks ordinary
client priority, both hands,40+40 particles, unchanged client inventory and
entity lifetime, and spectator rejection without particle/RNG/inventory/audio
writes. The spectator block case first proves the same ray can use the block
in survival. The synchronized capturable set comes from the actual server tag
and passes through the injected data callback. This memory-Pipe test does not
claim a live joined handshake or packet delivery to another process.

The server fixture freezes the actual clock and checks a normal command sees
each target before capture, then an immediate `execute unless entity` and
chunk-save assembly omit it afterwards. No world/entity tick intervenes.
Unmodified runtime77f7 fails this new assertion: removed mobs remain visible to
selectors. The isolated runtime candidate adds removal guards to enumeration,
UUID lookup and passenger save assembly. When testing that delta on a copied
stage, pass `--runtime-patch /path/to/candidate.diff`; the report records the
base revision, diff hash and actual runtime source hashes. Such a run is
explicitly a patched candidate result, not an unchanged77f7 result.

`tools/burner_interactions_reference.py` drives the isolated original Java
client;12 original lifecycle cases passed, including an actual40+40 burst.
`tools/burner_interactions_checks.py` provides normal native player-click cases
and a genuine process-restart callback. Native acceptance is recorded separately
when the integrated build runs it; passing the Java and Game tests alone is not
an audio, pixel or multiplayer parity claim.

Current boundaries: vanilla shovel metadata is supported; arbitrary NeoForge
ItemAbility addons are not executed. Entity capture uses Horizon's mob entity
implementation. The remote prediction path now receives the authoritative
merged capturable tag through the bounded mod-owned snapshot described in
[BURNER_SYNC.md](BURNER_SYNC.md); a cold or invalid snapshot fails closed.
