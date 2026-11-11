"""Windmill sail states and MIT shape definitions with built-in fallback models."""

COLORS = (
    'white', 'orange', 'magenta', 'light_blue', 'yellow', 'lime', 'pink', 'gray',
    'light_gray', 'cyan', 'purple', 'blue', 'brown', 'green', 'red', 'black',
)
SAIL_ITEMS = ['sail_frame', 'white_sail']
COLORED_SAILS = [color + '_sail' for color in COLORS if color != 'white']
ROTATIONS = {
    'down': {'x': 180}, 'up': {}, 'north': {'x': 90},
    'south': {'x': 90, 'y': 180}, 'west': {'x': 90, 'y': 270}, 'east': {'x': 90, 'y': 90},
}


def shape(boxes):
    """Rotate AllShapes' UP voxel boxes around the center of the block."""
    def rotate(point, face):
        x, y, z = point
        return {
            'up': (x, y, z), 'down': (x, 16 - y, 16 - z),
            'north': (x, z, 16 - y), 'south': (16 - x, z, y),
            'west': (16 - y, z, 16 - x), 'east': (y, z, x),
        }[face]

    def box(start, end, face):
        ends = list(zip(rotate(start, face), rotate(end, face)))
        return [bound / 16 for limit in (min, max) for bound in map(limit, ends)]

    return {'property': 'facing', 'values': {
        face: [box(start, end, face) for start, end in boxes] for face in ROTATIONS
    }}


def sails(write, model):
    frame_shape = [([0, 5, 0], [16, 9, 16])]
    frame_ring = [
        ([0, 5, 0], [2, 9, 16]), ([14, 5, 0], [16, 9, 16]),
        ([2, 5, 0], [14, 9, 2]), ([2, 5, 14], [14, 9, 16]),
    ]
    canvas_shape = [([0, 5, 0], [16, 10, 16])]
    for name in SAIL_ITEMS + COLORED_SAILS:
        frame = name == 'sail_frame'
        selectable = shape(frame_shape if frame else canvas_shape)
        write(f'data/create/horizon/block/{name}.json', {
            'template': 'minecraft:glass', 'item': name in SAIL_ITEMS,
            'properties': {'hardness': 2, 'explosion_resistance': 3, 'requires_tool': False,
                           'occludes': False, 'render_shape': 'MODEL', 'sounds': 'minecraft:scaffolding'},
            'state_properties': {'facing': {'type': 'enum', 'values': list(ROTATIONS)}},
            'default_state': {'facing': 'north'},
            'shapes': selectable, 'collision_shapes': shape(frame_ring) if frame else selectable,
        })
        fallback = f'sail/{name}_fallback'
        color = name.removesuffix('_sail')
        texture = 'spruce_planks' if frame else f'{color}_wool'
        model(fallback, frame_ring if frame else canvas_shape, f'minecraft:block/{texture}')
        write(f'assets/create/blockstates/{name}.json', {'variants': {
            f'facing={face}': {'model': f'create:block/{fallback}', **rotation}
            for face, rotation in ROTATIONS.items()
        }})
        if name in SAIL_ITEMS:
            write(f'assets/create/models/item/{name}.json', {'parent': f'create:block/{fallback}'})
            write(f'assets/create/items/{name}.json', {'model': {
                'type': 'minecraft:model', 'model': f'create:item/{name}',
            }})
