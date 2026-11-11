#!/usr/bin/env python3
"""Check contracts required for installing this source as one native mod."""
import json
import re
from zipfile import ZipFile
from common import ROOT, NATIVE, PINS
from fallback_textures import texture_path
from catalog import (
    BLOCKS, EXTRA_MODELS, HIDDEN_CREATIVE_ITEMS, INTERNAL_BLOCKS, ITEMS,
    PALETTE_BLOCKS, PARTS, rust_catalog,
)


def main():
    manifest = json.loads((ROOT / "horizon-native.json").read_text())
    assert manifest["horizon"] == PINS["horizon_revision"], "Horizon pin differs"
    assert manifest["mixins"] == PINS["horizon_mixins_revision"], "Mixins pin differs"
    assert manifest["id"] == "create", "Native namespace differs"
    source = (NATIVE / "horizon-mixin.toml").read_text()
    assert re.search(r'^horizon_revision = "' + manifest["horizon"] + r'"$', source, re.M)
    assert re.search(r'^version = "' + re.escape(manifest["version"]) + r'"$', source, re.M)
    content = ROOT / "content"
    expected = {p.relative_to(content).as_posix(): p.read_text()
                for p in sorted(content.rglob("*")) if p.is_file() and p.suffix in {".json", ".toml", ".obj", ".mtl"}
                and "target" not in p.relative_to(content).parts}
    actual = json.loads((NATIVE / "data/content.json").read_text())
    assert actual == expected, "Bundled public content is stale: run tools/content.py"
    model_prefix = "assets/create/models/"
    required = {model_prefix + "block/" + part + ".json" for part in PARTS}
    required.update(model_prefix + name + ".json" for name in EXTRA_MODELS)
    missing_models = required - actual.keys()
    assert not missing_models, "Missing built-in models: " + ", ".join(sorted(missing_models))
    for block in BLOCKS:
        item = json.loads(actual[model_prefix + f'item/{block}.json'])
        if item.get('parent') == 'minecraft:item/generated':
            continue  # flat inventory sprites (glass panes), as in the original
        rotation = item['display']['gui']['rotation']
        assert rotation[0] % 90 and rotation[1] % 90, (block, rotation)
    textures = set()
    for name, text in actual.items():
        if name.startswith(model_prefix) and name.endswith(".json"):
            model = json.loads(text)
            if model.get("loader") == "neoforge:obj":
                namespace, relative = model["model"].split(":", 1)
                mesh = f"assets/{namespace}/{relative}"
                assert mesh.startswith(model_prefix) and mesh in actual, name
                material_libraries = [line.removeprefix("mtllib ") for line in actual[mesh].splitlines()
                                      if line.startswith("mtllib ")]
                assert material_libraries and all(
                    f"{mesh.rsplit('/', 1)[0]}/{library}" in actual for library in material_libraries
                ), mesh
            for texture in model.get("textures", {}).values():
                if texture.startswith(("create:block/fallback/", "create:item/fallback/")):
                    textures.add(texture_path(texture).as_posix())
                else:
                    assert texture.startswith("#") or texture == "minecraft:block/fire_0", (name, texture)
    texture_root = content / "assets/create/textures"
    assert textures == {p.relative_to(content).as_posix() for p in texture_root.rglob("*.png")}
    with ZipFile(NATIVE / "data/textures.zip") as archive:
        assert len(archive.namelist()) == len(textures) and set(archive.namelist()) == textures
        for path in sorted(textures):
            png = (content / path).read_bytes()
            assert png.startswith(b"\x89PNG\r\n\x1a\n\0\0\0\x0dIHDR\0\0\0\x10\0\0\0\x10"), path
            assert archive.read(path) == png, path
    reference=json.loads((ROOT / "tools/data/recipes.json").read_text())
    assert reference["reference"] == PINS["create_revision"]
    assert (NATIVE / "assets/src/catalog.rs").read_text() == rust_catalog(), "Importer catalog is stale"
    declared_blocks={p.stem for p in (content / "data/create/horizon/block").glob("*.json")}
    declared_items={p.stem for p in (content / "data/create/horizon/item").glob("*.json")}
    assert declared_blocks == set(BLOCKS+INTERNAL_BLOCKS) and declared_items == set(ITEMS)
    tabs = {path.stem: json.loads(path.read_text())
            for path in (content / "data/create/horizon/creative_tab").glob("*.json")}
    assert set(tabs) == {"kinetics", "palettes"}
    assert tabs["kinetics"]["title"] == "itemGroup.create.base"
    assert HIDDEN_CREATIVE_ITEMS <= set(BLOCKS + ITEMS)
    assert tabs["kinetics"]["items"] == [
        "create:" + name for name in BLOCKS + ITEMS
        if name not in PALETTE_BLOCKS and name not in HIDDEN_CREATIVE_ITEMS
    ]
    assert tabs["palettes"]["title"] == "itemGroup.create.palettes"
    assert tabs["palettes"]["items"] == ["create:" + name for name in PALETTE_BLOCKS]
    assert len(list((content / "data/create/recipe").rglob("*.json"))) == len(reference["recipes"])
    for path, value in reference.get('loot_tables', {}).items():
        assert json.loads((content / 'data' / path).read_text()) == value, 'Source loot policy changed: ' + path
    for path in [*NATIVE.rglob("*"), *content.rglob("*")]:
        assert not path.is_symlink(), "Source bundles must not contain links: " + str(path)
        if path.is_relative_to(content) and path.relative_to(content).as_posix() in textures:
            continue
        assert path.suffix.lower() not in {".jar", ".class", ".png", ".ogg"}, str(path)
    assert (NATIVE / "LICENSE").read_bytes() == (ROOT / "LICENSE").read_bytes()
    assert (NATIVE / "NOTICE.md").read_bytes() == (ROOT / "THIRD_PARTY_NOTICES.md").read_bytes()
    print(f"Source-install contracts passed: pins, content, {len(textures)} fallback textures and notices.")


if __name__ == "__main__":
    main()
