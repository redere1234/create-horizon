#!/usr/bin/env python3
"""Exercise the native motor -> shafts/cogs -> press -> depot in a fresh world."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from common import ROOT
from native_motors import replace_motor
import interaction_checks
import foundation_checks
import engineering_checks
import milling_checks
import fan_checks
import audit05_checks
import drilling_checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resources", type=Path, required=True)
    parser.add_argument("--ctl", type=Path)
    parser.add_argument("--game", type=Path, help="Test this launcher-built client instead of target/fast/horizon-client")
    parser.add_argument("--offscreen", action="store_true", help="Also render and capture a frame")
    parser.add_argument("--create-jar", type=Path, help="Exercise the automatic import from this user-supplied Create 6.0.10 JAR")
    parser.add_argument("--audio", action="store_true", help="Enable normal audio output during this test")
    parser.add_argument("--engineering-only",action="store_true",help="Run the new engineering scenarios while iterating; full release validation omits this flag")
    parser.add_argument("--processors-only",action="store_true",help="Run the new milling/fan scenarios while iterating")
    parser.add_argument("--fan-only",action="store_true",help="Iterate on native fan scenarios")
    args = parser.parse_args()
    original = args.resources.resolve()
    if not (original / "facts.json").is_file(): raise SystemExit("Not a prepared Horizon resource folder")
    ctl = args.ctl or original.parents[2] / "horizon-ctl"
    game = (args.game or ROOT / "target/fast/horizon-client").resolve()
    if not game.is_file(): raise SystemExit("Run python3 tools/stage.py build first")
    scratch = Path(tempfile.mkdtemp(prefix="smoke-", dir=ROOT / ".local"))
    (scratch / "horizon-mods.txt").write_text("mod.create:true\n")
    if args.create_jar:
        inputs = scratch / "horizon-mods/create-resources"
        inputs.mkdir(parents=True)
        shutil.copy2(args.create_jar, inputs / "create.jar")
    resources = scratch / "resources"
    # A private writable copy: resource loaders may create or refresh caches.
    if os.uname().sysname == "Darwin":
        subprocess.run(["cp", "-cR", str(original), str(resources)], check=True)
    else:
        shutil.copytree(original, resources)
    env = os.environ.copy()
    for key, folder in [("HORIZON_HOME", "home"), ("HORIZON_LAUNCHER_HOME", "launcher"),
                        ("XDG_DATA_HOME", "data"), ("XDG_CONFIG_HOME", "config"),
                        ("HORIZON_LAUNCHER_TRASH", "trash"), ("HORIZON_LAUNCHER_CLIPBOARD", "clipboard"),
                        ("HORIZON_LAUNCHER_DESKTOP", "desktop")]:
        env[key] = str(scratch / folder)
    env.update({"HORIZON_NO_AUDIO": "1", "HORIZON_LAUNCHER_NO_SELF_UPDATE": "1", "CREATE_HORIZON_TRACE": "1", "CREATE_HORIZON_TRACE_POSES":"1"})
    if args.audio: env.pop("HORIZON_NO_AUDIO",None)
    socket = scratch / "ctl.sock"
    transcript = []

    def call(*words, timeout=120):
        reply = subprocess.run([str(ctl), "--socket", str(socket), *map(str, words)], env=env,
                               text=True, capture_output=True, timeout=timeout)
        if reply.returncode:
            raise RuntimeError(str(words) + ": " + reply.stdout + reply.stderr)
        data = json.loads(reply.stdout)
        transcript.append({"command": list(map(str, words)), "reply": data})
        return data

    def expect_sheet(item, count):
        data = call("container", 3, 64, 1)
        encoded = json.dumps(data)
        def stacks(value):
            if isinstance(value, dict):
                if value.get("item", value.get("id")) == item:
                    yield value.get("count")
                for child in value.values(): yield from stacks(child)
            elif isinstance(value, list):
                for child in value: yield from stacks(child)
        if sum(stacks(data)) != count:
            raise AssertionError("Expected " + item + ": " + encoded)
        # The raw reply is kept for auditing the count and the container slot.
        print("Container:", encoded, flush=True)
        return data

    log_path = scratch / "game.log"
    print("Scratch world:", scratch, flush=True)
    with log_path.open("w") as log:
        launch = [str(game), "--resources", str(resources), "--world", "CreatePortSmoke",
                  "--seed", "5", "--creative", "--render-distance", "2",
                  "--control-socket", str(socket),
                  "--offscreen" if args.offscreen else "--headless"]
        # The client also stores saves/options relative to cwd, independently of HOME.
        process = subprocess.Popen(launch, cwd=scratch, env=env, stdout=log, stderr=subprocess.STDOUT)

        def ready():
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                if process.poll() is not None: raise RuntimeError(log_path.read_text()[-8000:])
                try:
                    call("state", timeout=5)
                    break
                except (RuntimeError, subprocess.TimeoutExpired):
                    time.sleep(.25)
            else: raise TimeoutError("Control socket startup; see " + str(log_path))
            call("wait-ready", 120, timeout=150)

        def input_stack(item, count):
            # Horizon's vanilla /item command does not yet address mod containers.
            # Replace this fixture's depot and fill it through the supported control API.
            call("setblock", 3, 64, 1, "minecraft:air")
            call("setblock", 3, 64, 1, "create:depot")
            call("container", 3, 64, 1, item, count)
        try:
            ready()
            if args.processors_only or args.fan_only:
                milling=None if args.fan_only else milling_checks.run(call,args.offscreen,log_path,scratch)
                fan=fan_checks.run(call,args.offscreen,log_path,scratch)
                audit05_checks.run(call,args.offscreen,log_path,scratch)
                audit05_checks.press_resets_fan_progress(call)
                drill=None if args.fan_only else drilling_checks.run(call,args.offscreen,log_path,scratch)
                dropped=audit05_checks.prepare_dropped_reload(call)
                call('quit');process.wait(timeout=30)
                process=subprocess.Popen(launch,cwd=scratch,env=env,stdout=log,stderr=subprocess.STDOUT)
                ready()
                if milling:milling_checks.reloaded(call,milling)
                fan_checks.reloaded(call,fan)
                if drill:drilling_checks.reloaded(call,drill)
                audit05_checks.reloaded_dropped(call,dropped)
                (scratch/'result.json').write_text(json.dumps({'passed':True,'scope':'processors-only','milling':milling,'fan':fan},indent=2)+'\n')
                print('Processors smoke passed:',scratch/'result.json',flush=True)
                return
            if args.engineering_only:
                engineering=engineering_checks.run(call,args.offscreen,log_path,scratch)
                call('quit');process.wait(timeout=30)
                process=subprocess.Popen(launch,cwd=scratch,env=env,stdout=log,stderr=subprocess.STDOUT)
                ready();engineering_checks.reloaded(call,engineering)
                (scratch/'result.json').write_text(json.dumps({'passed':True,'scope':'engineering-only','fixture':engineering},indent=2)+'\n')
                print('Engineering smoke passed:',scratch/'result.json',flush=True)
                return
            if args.create_jar:
                receipts = list((scratch / ".horizon-cache/create-assets/imports").glob("*/import.json"))
                if len(receipts) != 1:
                    raise AssertionError("The game did not automatically import the local JAR: " + log_path.read_text()[-8000:])
                receipt = json.loads(receipts[0].read_text())
                if not any(name.endswith("/axis.png") for name in receipt["files"]):
                    raise AssertionError("Original shaft texture was not imported")
                if f"Create: {len(receipt['files'])} local resources" not in log_path.read_text():
                    raise AssertionError("The imported resource pack was not applied")
            call("command", "tp @s 2 68 6")
            call("wait-ready", 120, timeout=150)
            call("fill", -2, 64, -2, 7, 68, 7, "minecraft:air")
            call("fill", -2, 63, -2, 7, 63, 7, "minecraft:smooth_stone")
            interaction_checks.placement(call)
            def rendered(pos, expected):
                call("wait", 4)
                rows = []
                for line in log_path.read_text().splitlines():
                    if "Create render depot: " in line:
                        row = json.loads(line.split("Create render depot: ", 1)[1])
                        if row["pos"] == list(pos): rows.append(row)
                assert rows and rows[-1]["stack"] == expected, {"expected":expected,"last_client_frame":rows[-1:]}
            marked = interaction_checks.depot(call, rendered if args.offscreen else None)
            foundation = foundation_checks.run(call, args.offscreen, log_path, scratch)
            engineering = engineering_checks.run(call,args.offscreen,log_path,scratch)
            milling=milling_checks.run(call,args.offscreen,log_path,scratch)
            fan=fan_checks.run(call,args.offscreen,log_path,scratch)
            audit05_checks.run(call,args.offscreen,log_path,scratch)
            audit05_checks.press_resets_fan_progress(call)
            drill=drilling_checks.run(call,args.offscreen,log_path,scratch)
            dropped=audit05_checks.prepare_dropped_reload(call)
            # The processor/drill scenarios visit distant chunks. Load the
            # original press station before editing its blocks again.
            call("command", "tp @s 3.5 68 4.5")
            call("wait-ready", 120, timeout=150)
            fixtures = [([0, 66, 0], "create:creative_motor[facing=east]"),
                        ([1, 66, 0], "create:shaft[axis=x]"),
                        ([2, 66, 0], "create:cogwheel[axis=x]"),
                        ([2, 66, 1], "create:cogwheel[axis=x]"),
                        ([3, 66, 1], "create:mechanical_press[facing=east]"),
                        ([3, 64, 1], "create:depot")]
            for pos, block in fixtures:
                actual = call("setblock", *pos, block)
                assert actual["block"].split("[")[0] == block.split("[")[0], (pos, block, actual)
                if "[" in block:
                    requested = set(block.split("[", 1)[1].rstrip("]").split(","))
                    returned = set(actual["block"].split("[", 1)[1].rstrip("]").split(","))
                    assert requested <= returned, (pos, block, actual)
            # Interrupt after the first stroke: return both the remaining inputs
            # and the buffer, then let the abandoned cycle finish without duplication.
            input_stack("minecraft:iron_ingot", 8)
            for _ in range(90):
                sample = call("container", 3,64,1)["slots"]
                if any(s and s["item"] == "create:iron_sheet" for s in sample): break
                call("wait",2)
            else: raise AssertionError("No first pressing stroke")
            assert sample[0] == {"item":"minecraft:iron_ingot","count":7}, sample
            call("command", "clear @s"); call("command", "tp @s 3.5 65 3.5")
            call("interact",3,64,1,"up"); call("wait",10)
            inv = call("inventory")["counts"]
            assert inv.get("minecraft:iron_ingot") == 7 and inv.get("create:iron_sheet") == 1, inv
            call("wait",150)
            assert all(s is None for s in call("container",3,64,1)["slots"])
            assert call("inventory")["counts"] == inv
            if args.offscreen: rendered((3,64,1),None)
            print("Mid-cycle pickup: seven inputs plus one result returned exactly once; no ghost output",flush=True)
            call("command", "clear @s")
            replace_motor(call, (0, 66, 0), 128, 'east')
            before_strokes = log_path.read_text().count("Create sound: create:mechanical_press_activation [3, 66, 1]")
            call("container", 3, 64, 1, "minecraft:iron_ingot", 8)
            call("wait", 150)
            expect_sheet("create:iron_sheet", 8)
            strokes = log_path.read_text().count("Create sound: create:mechanical_press_activation [3, 66, 1]") - before_strokes
            assert strokes == 8, {"expected_strokes":8,"actual_strokes":strokes}
            call("command", "clear @s")
            call("command", "tp @s 3.5 65 3.5")
            call("interact", 3, 64, 1, "up"); call("wait", 10)
            assert call("inventory")["counts"].get("create:iron_sheet") == 8
            assert all(s is None for s in call("container", 3, 64, 1)["slots"])
            if args.offscreen: rendered((3,64,1), None)
            print("Processed stack: all eight sheets retrieved by one empty-hand click; client visual cleared", flush=True)
            call("command", "data get block 3 66 1")
            call("messages", 5)
            # Cut power and replace the input; a stopped network must not process it.
            call("setblock", 1, 66, 0, "minecraft:air")
            input_stack("minecraft:copper_ingot", 4)
            call("wait", 150)
            stopped = call("container", 3, 64, 1)
            if "minecraft:copper_ingot" not in json.dumps(stopped): raise AssertionError(stopped)
            call("setblock", 1, 66, 0, "create:shaft[axis=x]")
            call("wait", 150)
            expect_sheet("create:copper_sheet", 4)
            if args.offscreen:
                call("command", "time set day")
                call("command", "tp @s 3 65 3")
                call("look-at", 2, 65, 1)
                call("screenshot", scratch / "factory.png")
                call("command", "clear @s")
                call("look-at", 3.5, 64.9, 1.5)
                call("screenshot", scratch / "depot.png")
            input_stack("minecraft:gold_ingot", 3)
            call("wait", 20)
            call("quit", timeout=30)
            process.wait(timeout=30)
            process = subprocess.Popen(launch, cwd=scratch, env=env, stdout=log, stderr=subprocess.STDOUT)
            ready()
            call("wait", 150)
            expect_sheet("create:golden_sheet", 3)
            interaction_checks.reloaded_depot(call, marked)
            foundation_checks.reloaded(call, foundation)
            engineering_checks.reloaded(call,engineering)
            milling_checks.reloaded(call,milling)
            fan_checks.reloaded(call,fan)
            drilling_checks.reloaded(call,drill)
            audit05_checks.reloaded_dropped(call,dropped)
            result = {"passed": True, "scope": "placement, depot exchange/client rendering/components/save, transmissions/redstone, crank, wrench/casings, crafting, hopper IO, dropped-item capture/pressing, motor settings, sequential pressing, goggles/gauges/comparators, water wheels/multiblock structure, millstone/filtering/bonuses, fan washing/smoking/haunting/blasting, flow/media/direction, stationary drill/loot/gamerules, adversarial inventory conservation, power interruption and reload",
                      "scratch": str(scratch), "original_assets": bool(args.create_jar), "renderer_checks": args.offscreen, "audio_enabled":args.audio, "skipped": [] if args.offscreen else ["crafting menu", "motor screen", "render snapshots"], "transcript": transcript}
            if args.create_jar and "cache verified" not in log_path.read_text():
                raise AssertionError("The second game start did not reuse the verified resource cache")
            (scratch / "result.json").write_text(json.dumps(result, indent=2) + "\n")
            print("Smoke test passed:", scratch / "result.json", flush=True)
        finally:
            (scratch / "transcript.json").write_text(json.dumps(transcript, indent=2) + "\n")
            if process.poll() is None:
                try: call("quit", timeout=30)
                except Exception: pass
                try: process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=10)


if __name__ == "__main__":
    main()
