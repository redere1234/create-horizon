# Development

The engine in `mixins/create/engine/` holds Rust gameplay logic. The other
files in `mixins/create/` connect it to Horizon through native hooks.
`content/` holds recipes, block declarations and built-in resources.
`tools/content.py` updates those files and bundles them into the native mod.
The exact Java and Horizon versions are in [compatibility.json](../compatibility.json).

## Build and test

```sh
python3 tools/bootstrap.py
python3 tools/cargo.py fmt --all -- --check
python3 tools/cargo.py test --locked --workspace
python3 tools/cargo.py clippy --locked --workspace --all-targets -- -D warnings
python3 tools/check_distribution.py
```

Run `python3 tools/content.py` after editing generated content. To compare
behavior with Java, check out the pinned Create source at `../Create` or set
`CREATE_SOURCE`, then run the relevant `tools/*_oracle.py` check with a JDK.

To build the native client, use the pinned Horizon and Mixins checkouts with
`python3 tools/dev_build.py --help`. For a distributable archive, run
`python3 tools/package.py --cli /path/to/cargo-horizon-mod` with the pinned
Horizon checkout and tool. The archive is written under `dist/`. Use the
[installation guide](installation.md) to try the published source in Launcher.

Game tests use disposable instances. Original Create resources are optional and
can be supplied locally using the [resource guide](assets.md). The latest
gameplay results and their limits are in the [official Horizon checks](official-horizon.md).
[Earlier verification](../VALIDATION.md) · [Roadmap](roadmap.md)
