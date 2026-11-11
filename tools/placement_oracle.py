#!/usr/bin/env python3
"""Compare placement decisions against actual Java method bodies from pinned Create.

The context supplies neighboring shaft ports, clicked face, look and shift.
It does not prove the Minecraft context, collision, waterlogging or network adapter.
"""
import itertools
import json
import shutil
import subprocess
from common import ROOT, CREATE, PINS, cargo


def main():
    java, javac = shutil.which("java"), shutil.which("javac")
    if not java or not javac:
        raise SystemExit("A JDK is required")
    work = ROOT / ".local/placement-oracle"
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run([javac, "-d", str(work), str(ROOT / "tools/java/ExportMethod.java")], check=True)
    template = (ROOT / "tools/java/PlacementOracle.java.in").read_text()
    base = "src/main/java/com/simibubi/create/content/kinetics/"
    methods = [
        ("SHAFT_PREFERRED", "base/RotatedPillarKineticBlock.java", "getPreferredAxis"),
        ("SHAFT_STATE", "base/RotatedPillarKineticBlock.java", "getStateForPlacement"),
        ("COG_AXIS", "simpleRelays/CogWheelBlock.java", "getAxisForPlacement"),
        ("DIRECTION_PREFERRED", "base/DirectionalKineticBlock.java", "getPreferredFacing"),
        ("DIRECTION_STATE", "base/DirectionalKineticBlock.java", "getStateForPlacement"),
        ("MOTOR_STATE", "motor/CreativeMotorBlock.java", "getStateForPlacement"),
    ]
    for marker, relative, method in methods:
        source = work / relative.rsplit("/", 1)[1]
        source.write_bytes(subprocess.check_output(["git", "show", PINS["create_revision"] + ":" + base + relative], cwd=CREATE))
        body = subprocess.check_output([java, "-cp", str(work), "ExportMethod", str(source), method], text=True)
        template = template.replace("@@" + marker + "@@", body)
    oracle = work / "PlacementOracle.java"
    oracle.write_text(template)
    subprocess.run([javac, "-d", str(work), str(oracle)], check=True)
    cases = []
    for kind, mask, look, face, shift in itertools.product(range(3), range(64), range(6), range(6), range(2)):
        for against in range(4) if kind == 2 else [0]:
            cases.append(f"{kind} {mask} {look} {face} {shift} {against}")
    inputs = "\n".join(cases) + "\n"
    expected = subprocess.check_output([java, "-cp", str(work), "PlacementOracle"], input=inputs, text=True).splitlines()
    cargo("build", "--locked", "--example", "placement_probe", "--target-dir", ROOT / "target/core")
    actual = subprocess.check_output([str(ROOT / "target/core/debug/examples/placement_probe")], input=inputs, text=True).splitlines()
    assert len(actual) == len(expected) == len(cases)
    for case, original, port in zip(cases, expected, actual):
        if original != port:
            raise SystemExit(str({"input": case, "java": original, "rust": port}))
    result = {"passed": len(cases), "reference": PINS["create_revision"], "scope": "shaft/cog/motor placement decisions; original AST-exported methods with fixture contexts"}
    (work / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
