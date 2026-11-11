"""Explicit motor controls for native fixtures that intend to change power."""


def replace_motor(call, pos, rpm, facing):
    """Replace only the fixture motor, loading ScrollValue before initialization.

    A /data write to an initialized motor does not publish a new generated speed
    in Create. These fixtures need an actual power transition, including zero
    (the original settings GUI clamps zero to one), so issue ordinary AIR removal
    followed by one motor placement with its requested NBT already attached.

    This is not a GUI interaction or a /data-deserialization test. It neither
    rewrites neighboring machines/inventories nor advances the clock: callers
    retain their existing settling waits and cycle/persistence assertions.
    """
    pos = tuple(pos)
    if len(pos) != 3 or any(type(value) is not int for value in pos):
        raise ValueError('A motor position must contain three integer coordinates')
    if type(rpm) is not int or not -(2 ** 31) <= rpm < 2 ** 31:
        raise ValueError('ScrollValue must be a signed 32-bit integer')
    if not isinstance(facing, str) or facing not in {
        'down', 'up', 'north', 'south', 'west', 'east',
    }:
        raise ValueError('A motor facing must be a canonical direction')
    coordinates = ' '.join(map(str, pos))
    removed = call('command', f'setblock {coordinates} minecraft:air')
    placed = call(
        'command',
        f'setblock {coordinates} create:creative_motor[facing={facing}]'
        f'{{ScrollValue:{rpm}}}',
    )
    return removed, placed
