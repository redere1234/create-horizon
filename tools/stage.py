#!/usr/bin/env python3
"""Use Horizon Mixins on a pristine git export; never patch the upstream checkout."""
import argparse
import subprocess
import tarfile
import shutil
import hashlib
import tempfile
from pathlib import Path
from common import ROOT, HORIZON, NATIVE, PINS, cargo, check_horizon, environment
import setup_mixins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["stage", "check", "build"])
    args = parser.parse_args()
    check_horizon()
    setup_mixins.main()
    source = ROOT / ".local" / ("horizon-source-" + PINS["horizon_revision"])
    if not source.exists():
        source.mkdir(parents=True)
        archive = ROOT / ".local" / "horizon-source.tar"
        with archive.open("wb") as output:
            subprocess.run(["git", "archive", PINS["horizon_revision"]], cwd=HORIZON, stdout=output, check=True)
        with tarfile.open(archive) as package:
            package.extractall(source, members=[m for m in package.getmembers() if not m.issym() and not m.islnk()])
        archive.unlink()
        (source / ".horizon-revision").write_text(PINS["horizon_revision"])
    # The upstream CLAUDE.md is a documentation alias; Mixins rejects symlinks.
    for path in source.rglob("*"):
        if path.is_symlink():
            if path.name != "CLAUDE.md":
                raise SystemExit("Unexpected symlink in pristine export: " + str(path))
            path.unlink()
    mixins = ROOT / "target" / "debug" / "horizon-mixins"
    if not mixins.exists():
        cargo("build", "--locked", "--manifest-path", ROOT / ".tools/horizon-mixins/Cargo.toml", "-p", "horizon-mixins-cli")
    stage = ROOT / ".local" / "stage"
    digest = hashlib.sha256(str(PINS).encode())
    for path in sorted(NATIVE.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(NATIVE).as_posix().encode())
            digest.update(path.read_bytes())
    marker = ROOT / ".local" / "stage-key.txt"
    key = digest.hexdigest()
    if not marker.exists() or marker.read_text() != key or not stage.exists():
        mods = ROOT / ".local" / "mixin-input"
        if mods.exists():
            shutil.rmtree(mods)
        shutil.copytree(NATIVE, mods / "create",
                        ignore=shutil.ignore_patterns("target", "Cargo.lock", "__pycache__", "*.pyc"))
        subprocess.run([str(mixins), "plan", "--workspace", str(source), "--mods", str(mods),
                        "--out", str(ROOT / ".local/plan.json")], env=environment(), check=True)
        # Mixins' atomic replacement works on Linux only. Like Horizon's launcher,
        # apply to a fresh output and synchronize changed files to a stable Cargo
        # workspace. Unchanged source paths/mtimes keep incremental builds useful.
        with tempfile.TemporaryDirectory(prefix="mixin-stage-", dir=ROOT / ".local") as temporary:
            fresh = Path(temporary) / "game"
            subprocess.run([str(mixins), "apply", "--workspace", str(source), "--mods", str(mods),
                            "--out", str(fresh)], env=environment(), check=True)
            wanted = set()
            for path in fresh.rglob("*"):
                relative = path.relative_to(fresh)
                wanted.add(relative)
                target = stage / relative
                if path.is_dir(): target.mkdir(parents=True, exist_ok=True)
                elif not target.exists() or target.read_bytes() != path.read_bytes():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
            if stage.exists():
                for path in sorted(stage.rglob("*"), reverse=True):
                    if path.relative_to(stage) not in wanted:
                        if path.is_dir(): path.rmdir()
                        else: path.unlink()
        marker.write_text(key)
    if args.action != "stage":
        command = [args.action, "--locked", "--manifest-path", stage / "Cargo.toml", "-p", "horizon-client", "--bin", "horizon-client", "--no-default-features", "--jobs", "4"]
        if args.action == "build":
            command += ["--profile", "fast", "--config", "profile.fast.package.horizon-client.opt-level=0"]
        cargo(*command)


if __name__ == "__main__":
    main()
