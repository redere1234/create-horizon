#!/usr/bin/env python3
"""Run the real Horizon pipeline on an explicitly pinned, published Create jar.

The source checkout is 6.0.11; the published resource bootstrap is 6.0.10.
Use --jar with your own jar or explicitly request --download-bootstrap. All imported files
stay in .local because upstream assets are All Rights Reserved.
"""
import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from urllib.request import Request, urlopen
from common import ROOT, PINS, check_horizon, cargo


def get(url):
    return urlopen(Request(url, headers={"User-Agent": "create-horizon-local-development/0.1"}), timeout=60)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs_group = parser.add_mutually_exclusive_group(required=True)
    inputs_group.add_argument("--jar", type=Path, help="Use your own Create jar (offline)")
    inputs_group.add_argument("--download-bootstrap", action="store_true", help="Explicitly download the pinned 6.0.10 development input from Modrinth")
    args = parser.parse_args()
    check_horizon()
    binary = ROOT / "target" / "debug" / "horizon-port-pack"
    if not binary.is_file():
        cargo("build", "--manifest-path", ROOT.parent / "horizon/Cargo.toml", "--locked", "-p", "horizon-port-pack", "-p", "cargo-horizon-mod")
    inputs = ROOT / ".local" / "input-instance" / "mods"
    inputs.mkdir(parents=True, exist_ok=True)
    if args.jar:
        source = args.jar.resolve()
        jar = inputs / source.name
        if source != jar:
            shutil.copy2(source, jar)
        provenance = {"source": "user-built jar", "path": str(source)}
    else:
        with get("https://api.modrinth.com/v2/version/" + PINS["import_modrinth_version"]) as response:
            version = json.load(response)
        file = next(f for f in version["files"] if f["primary"])
        jar = inputs / file["filename"]
        if not jar.is_file():
            print("Downloading", file["filename"], flush=True)
            temporary = jar.with_suffix(".part")
            with get(file["url"]) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output)
            temporary.replace(jar)
        if hashlib.sha512(jar.read_bytes()).hexdigest() != file["hashes"]["sha512"]:
            raise SystemExit("Create jar SHA-512 mismatch")
        provenance = {"source": "Modrinth", "version": version["version_number"], "url": file["url"], "hashes": file["hashes"]}
    # Avoid stale input versions silently creating duplicate create namespaces.
    others = [p for p in inputs.glob("*.jar") if p != jar]
    if others:
        raise SystemExit("Use a clean .local/input-instance/mods before changing the input jar: " + str(others))
    provenance.update({"sha256": hashlib.sha256(jar.read_bytes()).hexdigest(), "reference_source_revision": PINS["create_revision"]})
    (ROOT / ".local/import-provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    work = ROOT / ".local" / "port-work"
    commands = [
        ["import", inputs.parent, work],
        ["inventory", work, "--offline"],
        ["carry", work, "create"],
        ["report", work],
        ["check", jar, ROOT / ".local" / "jar-check"],
    ]
    for command in commands:
        subprocess.run([str(binary), *map(str, command)], check=True)
    print("Resource carry-over only. Java behavior is not translated or marked complete.")


if __name__ == "__main__":
    main()
