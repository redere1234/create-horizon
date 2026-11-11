"""In-game regression checks for placement and DepotBehaviour's top-face exchange.

`call` is the Horizon control client; commands are retained by smoke.py.
Fixtures never open an existing user world.
"""


def placement(call):
    target = (0, 65, 0)

    def trial(item, player, property_value, neighbor=None, shift=False, support="minecraft:stone"):
        call("fill", -1, 64, -1, 2, 67, 1, "minecraft:air")
        call("setblock", 0, 64, 0, support)
        if " 67 " in player:
            call("setblock", 2, 66, 0, "minecraft:stone")
        if neighbor:
            call("setblock", 1, 65, 0, neighbor)
        call("command", "kill @e[type=minecraft:item]")
        call("command", "clear @s")
        call("command", "give @s create:" + item + " 1")
        call("wait", 5)
        call("select", "create:" + item)
        call("command", "tp @s " + player)
        call("wait", 3)
        # Publish rotation before the click reaches the integrated server.
        # `interact` alone aims and clicks within one client frame.
        call("look-at", "block", 0, 64, 0, "up")
        call("wait", 3)
        if shift:
            call("key", "shift", "down")
            call("wait", 3)
        try:
            call("interact", 0, 64, 0, "up")
            call("wait", 10)
        finally:
            call("release")
        block = call("block", *target)
        assert block["block"] == "create:" + item and property_value in block["state"], block

    trial("shaft", "3 64 0.5", "axis=x")
    trial("shaft", "0.5 64 -3", "axis=z")
    trial("shaft", "2.1 67 0.5", "axis=y")
    trial("shaft", "0.5 64 -3", "axis=x", neighbor="create:shaft[axis=x]")
    trial("shaft", "0.5 64 -3", "axis=y", neighbor="create:shaft[axis=x]", shift=True)
    trial("cogwheel", "0.5 64 -3", "axis=y")
    trial("large_cogwheel", "0.5 64 -3", "axis=x", support="create:cogwheel[axis=x]")
    trial("large_cogwheel", "0.5 64 -3", "axis=y", support="create:cogwheel[axis=x]", shift=True)
    trial("creative_motor", "3 64 0.5", "facing=east")
    trial("creative_motor", "0.5 64 -3", "facing=north")
    trial("creative_motor", "2.1 67 0.5", "facing=up")
    trial("mechanical_press", "3 64 0.5", "facing=east")
    call("fill", -1, 64, -1, 2, 67, 1, "minecraft:air")
    print("In-game placement: 12 face/look/neighbor/Shift cases passed", flush=True)


DEPOT = (0, 64, 0)
MARKED = {"item": "minecraft:candle", "count": 2}


def depot(call, render=None):
    def slots():
        return call("container", *DEPOT)["slots"]

    def click(face="up"):
        call("interact", *DEPOT, face)
        call("wait", 10)
        screen = call("screen")
        assert screen["screen"] == "playing", screen
        if render:
            render(DEPOT, slots()[0])

    def clear():
        call("command", "kill @e[type=minecraft:item]")
        call("command", "clear @s")
        call("wait", 5)

    def give(item, count):
        call("command", f"give @s {item} {count}")
        call("wait", 5)
        return call("select", item.split("[", 1)[0])["held"]

    call("setblock", *DEPOT, "create:depot")
    call("command", "tp @s 0.5 65 2.5")
    clear()
    give("minecraft:iron_ingot", 5)
    click()
    assert slots()[0] == {"item": "minecraft:iron_ingot", "count": 5}, slots()
    assert call("inventory")["counts"].get("minecraft:iron_ingot", 0) == 0
    # Empty hand retrieves the entire stack. Creative mode also consumes the hand on put.
    click()
    assert all(s is None for s in slots()), slots()
    assert call("inventory")["counts"].get("minecraft:iron_ingot") == 5
    call("select", "minecraft:iron_ingot")
    click()
    give("minecraft:copper_ingot", 3)
    click()
    assert slots()[0] == {"item": "minecraft:copper_ingot", "count": 3}, slots()
    inv = call("inventory")["counts"]
    assert inv.get("minecraft:iron_ingot") == 5 and inv.get("minecraft:copper_ingot", 0) == 0, inv
    # Returning the old equal stack merges it into the hand before the new stack is taken.
    give("minecraft:copper_ingot", 2)
    click()
    assert slots()[0] == {"item": "minecraft:copper_ingot", "count": 5}, slots()
    assert call("inventory")["counts"].get("minecraft:copper_ingot", 0) == 0
    # A side click and Shift with an item must leave the depot contents alone.
    give("minecraft:gold_ingot", 1)
    call("command", "tp @s 0.5 64 2.5")
    click("south")
    assert slots()[0] == {"item": "minecraft:copper_ingot", "count": 5}, slots()
    call("command", "tp @s 0.5 65 2.5")
    call("key", "shift", "down")
    call("wait", 3)
    try:
        click()
    finally:
        call("release")
    assert slots()[0] == {"item": "minecraft:copper_ingot", "count": 5}, slots()
    assert call("inventory")["counts"].get("minecraft:gold_ingot") == 1
    # Retrieve both the held item and all eight output-buffer slots.
    clear()
    call("container", *DEPOT, "minecraft:iron_ingot", 7)
    click()
    assert all(s is None for s in slots()), slots()
    inv = call("inventory")["counts"]
    assert inv.get("minecraft:copper_ingot") == 5 and inv.get("minecraft:iron_ingot") == 7, inv
    clear()
    marked = give("minecraft:candle[minecraft:custom_data={create_port_marker:123}]", 2)
    click()
    assert slots()[0] == MARKED, slots()
    assert "create_port_marker:123" in marked.get("components", ""), marked
    click()
    inv = call("inventory")
    restored = next(s for s in inv["hotbar"] + inv["main"] if s.get("item") == "minecraft:candle")
    assert restored["count"] == 2 and restored["components"] == marked["components"], restored
    call("select", "minecraft:candle")
    click()
    # Leave this stack on the depot for save/reload verification.
    data = call("command", "data get block 0 64 0")
    encoded = str(data)
    assert "HeldItem" in encoded and "OutputBuffer" in encoded and "create:depot" in encoded, data
    print("Depot: top put/pick/swap, equal-stack merge, side/Shift, output buffer and components passed", flush=True)
    return marked


def reloaded_depot(call, expected):
    actual = call("container", *DEPOT)["slots"][0]
    # The control API's container reply deliberately omits stack components.
    assert actual == MARKED, (expected, actual)
    call("command", "tp @s 0.5 65 2.5")
    call("command", "clear @s")
    call("interact", *DEPOT, "up")
    call("wait", 10)
    inv = call("inventory")
    restored = next(s for s in inv["hotbar"] + inv["main"] if s.get("item") == "minecraft:candle")
    assert restored["count"] == 2 and restored["components"] == expected["components"], restored
    assert all(s is None for s in call("container", *DEPOT)["slots"])
    print("Depot save/reload: original ID, quantity and custom data survived", flush=True)
