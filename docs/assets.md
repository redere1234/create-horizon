# Models and textures

Create for Horizon includes simple models and independently drawn pixel textures.
The bundled artwork is distributed under the repository's MIT license.
Horizon uses it whenever the original Create JAR is absent. [Texture register](fallback-textures.md)

## Use the original look

1. Download [Create 6.0.10 for Minecraft 1.21.1 (NeoForge)](https://modrinth.com/mod/create/version/UjX6dr61).
2. Open your Horizon instance folder. Place one copy in `horizon-mods/create-resources/`.
3. Restart Horizon.

```text
<instance>/
  horizon-mods/
    create-resources/
      create-1.21.1-6.0.10.jar
```

Keep the file as a JAR. Its name can vary. The mod verifies the archive before
importing models, textures, sounds and translations for the features it supports.
It reads the JAR locally and caches the imported resources in the instance's
`.horizon-cache/create-assets/` directory. The Java code inside the JAR is never
run. Remove the JAR and restart to return to the built-in look.

Use the specified release. Its SHA-256 is
`ef87fe5709f1ba1f5b8bb20a2925b5afb4669e178fd6d8bf10c167759eefe37a`.
With a different file or more than one JAR, Horizon keeps the built-in resources
and reports the reason in its log.

Create's original assets are All Rights Reserved. Keep the JAR and extracted
cache local to your instance. [Original license](https://github.com/Creators-of-Create/Create/blob/ac0c444d9828da3453ae8cc65338e8de063286fb/LICENSE.md)
