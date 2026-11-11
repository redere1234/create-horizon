#!/usr/bin/env python3
"""Play the prototype in the project's own persistent development world."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
from common import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resources", type=Path)
    parser.add_argument("--create-jar", type=Path, help="Copy your Create 6.0.10 JAR into the development instance for automatic local import")
    args = parser.parse_args()
    config = ROOT / ".local/development.json"
    if args.resources:
        origin = args.resources.resolve()
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps({"resources": str(origin)}, indent=2) + "\n")
    elif config.exists():
        origin = Path(json.loads(config.read_text())["resources"])
    else:
        parser.error("Pass --resources with a prepared Horizon 26.3 resource folder once")
    if not (origin / "facts.json").is_file(): raise SystemExit("Prepared resources not found")
    game = ROOT / "target/fast/horizon-client"
    if not game.is_file(): raise SystemExit("Run python3 tools/stage.py build first")
    resources = ROOT / ".local/play-resources"
    if not resources.exists():
        if os.uname().sysname == "Darwin": subprocess.run(["cp", "-cR", str(origin), str(resources)], check=True)
        else: shutil.copytree(origin, resources)
    env = os.environ.copy()
    for key, folder in [("HORIZON_HOME", "play-home"), ("HORIZON_LAUNCHER_HOME", "play-launcher"),
                        ("XDG_DATA_HOME", "play-data"), ("XDG_CONFIG_HOME", "play-config"),
                        ("HORIZON_LAUNCHER_TRASH", "play-trash"), ("HORIZON_LAUNCHER_CLIPBOARD", "play-clipboard"),
                        ("HORIZON_LAUNCHER_DESKTOP", "play-desktop")]: env[key] = str(ROOT / ".local" / folder)
    env.update({"HORIZON_NO_AUDIO": "1", "HORIZON_LAUNCHER_NO_SELF_UPDATE": "1"})
    work = ROOT / ".local/play-home"
    work.mkdir(parents=True, exist_ok=True)
    (work / "horizon-mods.txt").write_text("mod.create:true\n")
    if args.create_jar:
        inputs = work / "horizon-mods/create-resources"
        inputs.mkdir(parents=True, exist_ok=True)
        target = inputs / "create.jar"
        existing = [path for path in inputs.iterdir() if path.suffix.lower() == ".jar"]
        if existing and (len(existing) != 1 or existing[0].read_bytes() != args.create_jar.read_bytes()):
            raise SystemExit("A different resource JAR is already present in " + str(inputs))
        if not existing:
            shutil.copy2(args.create_jar, target)
    subprocess.run([str(game), "--resources", str(resources), "--world", "CreateDevelopment", "--creative",
                    "--render-distance", "4"], cwd=work, env=env, check=True)


if __name__ == "__main__":
    main()
