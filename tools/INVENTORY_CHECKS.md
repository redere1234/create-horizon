# Canonical Create inventories

`mixins/create/inventory_codec.rs` shares canonical item decoding between cold
save loading and client update receipt. It is independently authored from the
pinned MIT Create schemas and recorded public-API input/output observations.
The public observation file contains functional SNBT/slot values and version
metadata, with no upstream implementation, libraries, bytecode or assets.

| Block entity | Input | Output | Native slots |
|---|---|---|---|
| Depot | `HeldItem.Item` | `OutputBuffer`, eight slots | 9 |
| Basin | `InputItems`, nine slots | `OutputItems`, nine slots | 18 |
| Millstone | `InputInventory`, one slot | `OutputInventory`, nine slots | 10 |

Generic `Items` is a redundant Horizon snapshot. It cannot revive items absent
from canonical fields. An explicit integer `Size` different from the supported
size leaves canonical NBT opaque and exposes no native slots; normal ticking,
automation, use, wrench and break paths refuse to alter it. Restoring the size
recovers the retained canonical stacks. Unknown sibling fields and stack
components are preserved. This is a bounded same-version codec, not a Java
1.21.1 to Minecraft26.3 data fixer or arbitrary edited-inventory support.

Client receipt follows the pinned Horizon type/block/tag gates. Nonempty updates
clear absent owned canonical halves before the ordinary NBT merge; unrelated
NBT and live entity identity/runtime data remain intact. A completely empty
update is Horizon's no-op, while an empty cold saved compound has empty slots.

Reproduce the portable/actual-type checks:

```sh
python3 tools/inventory_decode_checks.py --horizon ../horizon-port-runtime
```

The driver checks 147 recorded Depot cases, all three canonical schemas,
components/unknown fields, real `ModBlockEntity` identity/merge semantics,
ordinary writers, and the extracted unchanged native hopper merge method.
These are method/type checks, not a live client or rendering claim.

Run real Basin/Millstone automation and two-process persistence checks:

```sh
python3 tools/inventory_native_checks.py \
  --game /path/to/built/horizon-client \
  --resources /path/to/prepared/26.3 \
  --ctl /path/to/horizon-ctl \
  --create-jar /path/to/create-1.21.1-6.0.10.jar
```

The runner owns a new private world. It tests canonical fields while machine
ticks are frozen, removal of each half, ordinary hopper `3 + 5 = 8`, opaque-size
refusal/recovery, exact typed on-disk NBT around closing, and real process reload.
`container` control queries are authoritative server reads; they do not prove
what the client rendered. The separate `depot_sync_checks.py` uses the actual
render callback trace and PNGs after normal hopper extraction to detect a
stale displayed stack without repairing it by reopening the world. PNG viewing
and pixel parity remain explicit additional acceptance steps.
