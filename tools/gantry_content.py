"""Provisional Gantry models and static shapes from the pinned block definitions."""


def gantry(write, model):
    rotations = {'down': {'x': 180}, 'up': {}, 'north': {'x': 90},
                 'south': {'x': 90, 'y': 180}, 'west': {'x': 90, 'y': 270},
                 'east': {'x': 90, 'y': 90}}
    facing = {'type': 'enum', 'values': list(rotations)}
    parts = ['start', 'middle', 'end', 'single']
    flags = ['false', 'true']
    boxes = {face: [[.25, 0, .25, .75, 1, .75]] for face in ('up', 'down')}
    boxes.update({face: [[0, .25, .25, 1, .75, .75]] for face in ('east', 'west')})
    boxes.update({face: [[.25, .25, 0, .75, .75, 1]] for face in ('north', 'south')})
    for name in ('gantry_shaft', 'gantry_carriage'):
        rail = name == 'gantry_shaft'
        properties = {'facing': facing}
        default = {'facing': 'north'}
        if rail:
            properties.update(part={'type': 'enum', 'values': parts}, powered={'type': 'boolean'})
            default.update(part='single', powered='false')
        else:
            properties['axis_along_first'] = {'type': 'boolean'}
            default['axis_along_first'] = 'true'
        declaration = {'template': 'minecraft:glass', 'item': True,
                       'properties': {'hardness': 1.5, 'explosion_resistance': 6,
                                      'occludes': False, 'render_shape': 'MODEL',
                                      'requires_tool': True, 'sounds': 'minecraft:andesite'},
                       'state_properties': properties, 'default_state': default}
        if rail:
            declaration['shapes'] = {'property': 'facing', 'values': boxes}
        write(f'data/create/horizon/block/{name}.json', declaration)
        if rail:
            model(name + '/fallback', [([4, 0, 4], [12, 16, 12])], 'minecraft:block/iron_block')
            variants = {f'facing={face},part={part},powered={power}': rotation
                        for face, rotation in rotations.items() for part in parts for power in flags}
        else:
            model(name + '/fallback', [([1, 4, 1], [15, 16, 15]), ([3, 1, 3], [13, 4, 13])],
                  'minecraft:block/andesite')
            variants = {f'facing={face},axis_along_first={first}': rotation
                        for face, rotation in rotations.items() for first in flags}
        write(f'assets/create/blockstates/{name}.json', {'variants': {
            key: {'model': 'create:block/' + name + '/fallback', **rotation}
            for key, rotation in variants.items()}})
        write(f'assets/create/models/item/{name}.json', {'parent': 'create:block/' + name + '/fallback'})
        write(f'assets/create/items/{name}.json', {'model': {'type': 'minecraft:model', 'model': 'create:item/' + name}})
