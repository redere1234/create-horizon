"""Built-in crushing wheel and invisible controller resources."""

WHEEL = 'crushing_wheel'
CONTROLLER = 'crushing_wheel_controller'
FACES = ('down', 'up', 'north', 'south', 'west', 'east')


def crushing(write, model):
    write(f'data/create/horizon/block/{WHEEL}.json', {
        'template': 'minecraft:andesite', 'item': True,
        'properties': {'occludes': False, 'requires_tool': True,
                       'map_color': 6, 'render_shape': 'ENTITYBLOCK_ANIMATED'},
        'state_properties': {'axis': {'type': 'enum', 'values': ['x', 'y', 'z']}},
        'default_state': {'axis': 'y'},
    })
    model(f'{WHEEL}/block', [
        ([-10, 5, -3], [26, 11, 19]), ([-3, 5, -10], [19, 11, 26]),
        ([-7, 5, -7], [23, 11, 23]), ([5, -2, 5], [11, 18, 11]),
    ], 'minecraft:block/polished_andesite')
    write(f'assets/create/blockstates/{WHEEL}.json', {'variants': {'': {'model': 'minecraft:block/air'}}})
    write(f'assets/create/models/item/{WHEEL}.json', {
        'parent': f'create:block/{WHEEL}/block',
        'display': {'gui': {'rotation': [30, 225, 0], 'scale': [.45, .45, .45]},
                    'fixed': {'rotation': [90, 0, 0], 'scale': [.45, .45, .45]}},
    })
    write(f'assets/create/items/{WHEEL}.json', {
        'model': {'type': 'minecraft:model', 'model': f'create:item/{WHEEL}'},
    })

    # The original solid cross-section is 13 pixels deep and rotates with
    # the opening. Its per-entity collision exceptions are a separate path.
    boxes = {'down': [0, 0, 0, 1, 13 / 16, 1], 'up': [0, 3 / 16, 0, 1, 1, 1],
             'north': [0, 0, 0, 1, 1, 13 / 16], 'south': [0, 0, 3 / 16, 1, 1, 1],
             'west': [0, 0, 0, 13 / 16, 1, 1], 'east': [3 / 16, 0, 0, 1, 1, 1]}
    shapes = {'property': 'facing', 'values': {face: [box] for face, box in boxes.items()}}
    item_shapes = {'properties': ['facing', 'valid'], 'values': {
        f'{face},{valid}': [] if face == 'down' and valid == 'true' else [box]
        for face, box in boxes.items() for valid in ('false', 'true')
    }}
    write(f'data/create/horizon/block/{CONTROLLER}.json', {
        'template': 'minecraft:glass', 'item': False,
        'properties': {'occludes': False, 'map_color': 11, 'render_shape': 'INVISIBLE'},
        'state_properties': {'facing': {'type': 'enum', 'values': FACES},
                             'valid': {'type': 'boolean'}},
        'default_state': {'facing': 'north', 'valid': 'false'},
        'collision_shapes': shapes, 'collision_context_shapes': {'item': item_shapes},
    })
    write(f'assets/create/blockstates/{CONTROLLER}.json', {
        'variants': {'': {'model': 'minecraft:block/air'}},
    })
