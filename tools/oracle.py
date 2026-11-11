#!/usr/bin/env python3
"""Compare capacity/stress with the actual, unmodified Java KineticNetwork.

The tiny BE/world adapter supplies loaded identities and numeric getters. This
does not establish full NeoForge gameplay, graph propagation or rendering parity.
Original Java source is exported to .local, never copied into the port's sources.
"""
import itertools
import json
import shutil
import subprocess
from common import ROOT, CREATE, PINS, cargo


def main():
    java, javac = shutil.which("java"), shutil.which("javac")
    if not java or not javac: raise SystemExit("A JDK is required for this development-only oracle")
    work = ROOT / ".local" / "network-oracle"
    work.mkdir(parents=True, exist_ok=True)
    source = work / "KineticNetwork.java"
    upstream = "src/main/java/com/simibubi/create/content/kinetics/KineticNetwork.java"
    source.write_bytes(subprocess.check_output(["git", "show", PINS["create_revision"] + ":" + upstream], cwd=CREATE))
    subprocess.run([javac, "-d", str(work), str(source), str(ROOT / "tools/java/KineticBlockEntity.java"),
                    str(ROOT / "tools/java/NetworkOracle.java")], check=True)
    cargo("build", "--example", "network_probe", "--target-dir", ROOT / "target/core")
    probe = ROOT / "target/core/debug/examples/network_probe"
    checked = 0
    for speed, capacity, count in itertools.product([-128, -16, 0, 16, 256], [0, 4, 8, 16, 16384], [0, 1, 4]):
        args = list(map(str, [speed, capacity, count]))
        expected = json.loads(subprocess.check_output([java, "-cp", str(work), "com.simibubi.create.content.kinetics.NetworkOracle", *args], text=True))
        actual = json.loads(subprocess.check_output([str(probe), *args], text=True))
        if actual != expected: raise SystemExit(str({"input": args, "java": expected, "rust": actual}))
        checked += 1
    result = {"passed": checked, "reference": PINS["create_revision"], "scope": "capacity/stress only; unmodified KineticNetwork + fixture BE/world"}
    (work / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
