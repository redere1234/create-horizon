# Official Horizon compatibility

Create 0.11.1 builds on the unmodified official Horizon commit `fdc87ae`
with Minecraft 26.3 resources. It was built with the pinned Horizon Mixins
tool. The native client loaded both resource sets, restored a lit Blaze
Burner after restart, and matched the Java reference across 460 ticks of
Precision Mechanism assembly, including a restart after operation seven.
[Pinned source](https://github.com/horizon-rust/horizon/commit/fdc87ae)

The supported launcher target is the official Horizon nightly `fdc87ae`. This compatibility profile avoids hooks introduced after that nightly.
[Source](https://github.com/horizon-rust/horizon/tree/nightly-source/2026-11-08-fdc87ae)

## Merged engine changes

| Area | Horizon pull requests |
| --- | --- |
| Dropped items landing on machines | [#11051](https://github.com/horizon-rust/horizon/pull/11051) |
| Block state light and entity creation | [#11068](https://github.com/horizon-rust/horizon/pull/11068), [#11098](https://github.com/horizon-rust/horizon/pull/11098) |
| Pick Block and alternate block items | [#11070](https://github.com/horizon-rust/horizon/pull/11070), [#11114](https://github.com/horizon-rust/horizon/pull/11114) |
| Living interaction and held tool wear | [#11099](https://github.com/horizon-rust/horizon/pull/11099), [#11100](https://github.com/horizon-rust/horizon/pull/11100) |
| Native block tanks | [#11090](https://github.com/horizon-rust/horizon/pull/11090) |
| One-shot client updates and collision context | [#11115](https://github.com/horizon-rust/horizon/pull/11115), [#11116](https://github.com/horizon-rust/horizon/pull/11116) |
| Fluid and model rendering | [#11117](https://github.com/horizon-rust/horizon/pull/11117), [#11118](https://github.com/horizon-rust/horizon/pull/11118) |
| Data edits, mob discard and container notifications | [#11122](https://github.com/horizon-rust/horizon/pull/11122), [#11127](https://github.com/horizon-rust/horizon/pull/11127), [#11129](https://github.com/horizon-rust/horizon/pull/11129) |

The fluid renderer builds on the block tank PR for its fluid stack type. The
model renderer builds on the fluid renderer for shared terrain batching. The
combined build uses the stock atlas declarations, item fluid operations, inventory
and block entity draw pose. Chunk attachments and Create's recipe and tank rules
live in the mod.

The exact fan timing tests use the ordinary `/tick sprint` command. The separate
sprint boundary fix is for the test runner and vanilla tick behavior. It does
not change the native mod interface. [Horizon #11143](https://github.com/horizon-rust/horizon/pull/11143)

## Check a Nightly before publishing

1. Pick an official Nightly that includes the required changes. Check the full
   mod with `tools/dev_build.py --check-only` and the official Mixins tool.
2. Run the native client in a fresh instance. Check fallback assets, then
   repeat with a local Create 6.0.10 JAR. Test placement and Pick Block,
   Basin and Mixer, Blaze Burner, the fan, and moving structure save and reload.
3. Set the same official commit in `compatibility.json`, `horizon-native.json`
   and `mixins/create/horizon-mixin.toml`. Build the package, check its pins and
   install it through the unmodified Launcher before updating the registry.

Launcher and registry compatibility require a clean installation against the
official Nightly after it picks up these changes.
