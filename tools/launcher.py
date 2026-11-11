#!/usr/bin/env python3
"""Install/build Create with the unmodified official Horizon Launcher CLI."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile
from common import ROOT, NATIVE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", required=True, help="Existing test instance name or ID")
    parser.add_argument("--launcher", type=Path)
    parser.add_argument("--profile", choices=["dev", "performance", "release"], default="dev")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--github", help="Install this GitHub source URL before building")
    mode.add_argument("--source", action="store_true", help="Build this checkout instead of the installed bundle (Create must already be enabled)")
    args = parser.parse_args()
    launcher = args.launcher or shutil.which("horizon-launcher")
    if not launcher:
        mac = Path("/Applications/Horizon.app/Contents/MacOS/horizon-launcher")
        launcher = mac if mac.is_file() else None
    if not launcher:
        parser.error("Install Horizon Launcher or pass --launcher /path/to/horizon-launcher")
    if args.github:
        subprocess.run([
            str(launcher), "mods", "add-github", args.github,
            "--instance", args.instance, "--trust-native-code",
        ], check=True)
    command = [str(launcher), "native-build", "--instance", args.instance,
               "--profile", args.profile, "--trust-native-code"]
    if not args.source:
        subprocess.run(command, check=True)
        return
    # Give the launcher a bundle, not the development checkout's caches, Git
    # directory or input JARs. The published GitHub source has the same layout.
    with tempfile.TemporaryDirectory(prefix="create-native-source-") as temporary:
        source = Path(temporary)
        shutil.copy2(ROOT / "horizon-native.json", source / "horizon-native.json")
        shutil.copytree(NATIVE, source / "mixins/create",
                        ignore=shutil.ignore_patterns("target", "Cargo.lock", "__pycache__", "*.pyc"))
        subprocess.run([*command, str(source)], check=True)


if __name__ == "__main__":
    main()
