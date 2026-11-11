"""Built-in Rope Pulley resources and MIT source collision definitions."""


def rope_pulley(write, model):
    casing = 'rope_pulley'
    prefix = 'rope_pulley/'
    write(f'data/create/horizon/block/{casing}.json', {
        'template': 'minecraft:glass', 'item': True,
        'properties': {'hardness': 1.5, 'explosion_resistance': 6, 'requires_tool': True,
                       'occludes': False, 'render_shape': 'MODEL', 'sounds': 'minecraft:andesite'},
        'state_properties': {'axis': {'type': 'enum', 'values': ['x', 'z']}},
        'default_state': {'axis': 'x'},
    })
    model(prefix + 'block', [([0, 0, 0], [4, 16, 16]), ([12, 0, 0], [16, 16, 16]),
                             ([4, 13, 0], [12, 16, 16])], 'minecraft:block/andesite')
    model(prefix + 'rope_coil', [([4, 4, 4], [12, 12, 12])], 'minecraft:block/stripped_spruce_log')
    write(f'assets/create/blockstates/{casing}.json', {'variants': {
        'axis=x': {'model': 'create:block/rope_pulley/block', 'y': 90},
        'axis=z': {'model': 'create:block/rope_pulley/block'},
    }})
    write(f'assets/create/models/item/{casing}.json', {'parent': 'create:block/rope_pulley/block'})
    write(f'assets/create/items/{casing}.json', {
        'model': {'type': 'minecraft:model', 'model': f'create:item/{casing}'},
    })

    cable = [([6, 0, 6], [10, 16, 10])]
    foot = ([3, -3, 3], [13, 2, 13])
    for name, boxes, sound in [('rope', cable, 'brown_wool'), ('pulley_magnet', cable + [foot], 'andesite')]:
        shape = {'default': [[value / 16 for value in start + end] for start, end in boxes]}
        write(f'data/create/horizon/block/{name}.json', {
            'template': 'minecraft:glass', 'item': False,
            'properties': {'hardness': 0 if name == 'rope' else 1.5, 'occludes': False,
                           'render_shape': 'MODEL', 'sounds': f'minecraft:{sound}'},
            'state_properties': {'waterlogged': {'type': 'boolean'}},
            'default_state': {'waterlogged': 'false'}, 'shapes': shape, 'collision_shapes': shape,
        })
        texture = 'brown_wool' if name == 'rope' else 'iron_block'
        model(prefix + name, boxes, 'minecraft:block/' + texture)
        write(f'assets/create/blockstates/{name}.json', {'variants': {
            '': {'model': 'create:block/' + prefix + name},
        }})
    model(prefix + 'rope_half', [([6, 8, 6], [10, 16, 10])], 'minecraft:block/brown_wool')
    model(prefix + 'rope_half_magnet', [([6, 0, 6], [10, 5, 10]), foot], 'minecraft:block/iron_block')
    write('data/minecraft/tags/block/climbable.json', {'values': ['create:rope', 'create:pulley_magnet']})
