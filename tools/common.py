"""Local development paths; never uses the player's game or global Rust homes."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
HORIZON = Path(os.environ.get("HORIZON_SOURCE", ROOT.parent / "horizon")).resolve()
CREATE = Path(os.environ.get("CREATE_SOURCE", ROOT.parent / "Create")).resolve()
NATIVE = ROOT / "mixins" / "create"
PINS = json.loads((ROOT / "compatibility.json").read_text())


def environment():
    env = os.environ.copy()
    toolchain = ROOT / ".tools" / "rust"
    env["PATH"] = str(toolchain / "bin") + os.pathsep + env.get("PATH", "")
    env["CARGO_HOME"] = str(ROOT / ".cache" / "cargo")
    env["RUSTC"] = str(toolchain / "bin" / "rustc")
    env["RUSTDOC"] = str(toolchain / "bin" / "rustdoc")
    env["CARGO_TARGET_DIR"] = str(ROOT / "target")
    return env


def cargo(*args, cwd=ROOT, **kwargs):
    binary = ROOT / ".tools" / "rust" / "bin" / "cargo"
    if not binary.is_file():
        raise SystemExit("Run python3 tools/bootstrap.py first.")
    return subprocess.run([str(binary), *map(str, args)], cwd=cwd,
                          env=environment(), check=True, **kwargs)


def check_horizon():
    revision = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=HORIZON, text=True).strip()
    if revision != PINS["horizon_revision"]:
        raise SystemExit("Horizon revision differs from compatibility.json; use a matching checkout.")
