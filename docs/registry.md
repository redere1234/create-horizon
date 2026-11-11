# Horizon registry

Create for Horizon is a third-party native mod. The proposed entry is an
experimental preview. The page text lives in
[`horizon-registry.toml`](../horizon-registry.toml).

A submission uses the public MIT source and the matching `.hnmod` archive.
The bundle includes the built-in models, which reference standard Minecraft
textures. Players who want Create's original textures and models supply the
original Create 6.0.10 JAR themselves. [Resource setup](assets.md)

Check the archive with `cargo-horizon-mod check <archive> --kind native-mod`
before sending it for review. Include the source commit, SHA-256, game and tool
pins, and tested behavior. The 0.7.0-alpha.2 archive and listing metadata passed
the pinned Horizon registry tool's local checks. The bundle builds against the
pinned Horizon fork. Testing against the newest official Nightly is still open.
[Validation](../VALIDATION.md#optional-resources-in-070-alpha2)
[Registry policy](https://github.com/horizon-rust/horizon-mods/blob/main/MOD-POLICY.md)
· [Submission form](https://playhorizon.dev/mods/submit)
