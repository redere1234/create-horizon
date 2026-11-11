"""Canonical chassis states and built-in models using vanilla textures."""


CHASSIS = ['linear_chassis', 'secondary_linear_chassis', 'radial_chassis']
FACES = {
    'x': ('west', 'east'),
    'y': ('down', 'up'),
    'z': ('north', 'south'),
}
RADIAL = {
    'x': {'up': 'north', 'down': 'south', 'south': 'east', 'north': 'west'},
    'y': {name: name for name in ('north', 'south', 'east', 'west')},
    'z': {'up': 'north', 'down': 'south', 'east': 'east', 'west': 'west'},
}


def chassis(write):
    for face in (direction for pair in FACES.values() for direction in pair):
        axis = next(i for i, pair in enumerate(FACES.values()) if face in pair)
        positive = face in ('east', 'up', 'south')
        start, end = [2, 2, 2], [14, 14, 14]
        start[axis], end[axis] = ((16, 16.01) if positive else (-0.01, 0))
        write(f'assets/create/models/block/chassis_fallback/sticky_{face}.json', {
            'textures': {'particle': 'minecraft:block/slime_block'},
            'elements': [{'from': start, 'to': end, 'faces': {
                face: {'texture': '#particle', 'cullface': face},
            }}],
        })

    for name, wood in zip(CHASSIS, ('spruce', 'birch', 'oak')):
        radial = name == 'radial_chassis'
        keys = [f'sticky_{face}' for face in ('north', 'south', 'east', 'west')
                ] if radial else ['sticky_top', 'sticky_bottom']
        write(f'data/create/horizon/block/{name}.json', {
            'template': 'minecraft:oak_planks', 'item': True,
            'properties': {'hardness': 2, 'explosion_resistance': 3,
                           'requires_tool': False, 'sounds': 'minecraft:oak_planks'},
            'state_properties': {'axis': {'type': 'enum', 'values': list(FACES)},
                                 **{key: {'type': 'boolean'} for key in keys}},
            'default_state': {'axis': 'y', **{key: 'false' for key in keys}},
        })
        multipart = []
        path = f'chassis_fallback/{name}_y'
        end = f'minecraft:block/{wood}_planks'
        side = f'minecraft:block/stripped_{wood}_log'
        write(f'assets/create/models/block/{path}.json', {
            'parent': 'minecraft:block/cube',
            'textures': {'particle': side, **{
                face: end if face in FACES['y'] else side
                for pair in FACES.values() for face in pair
            }},
        })
        turns = {'x': {'x': 90, 'y': 90}, 'y': {}, 'z': {'x': 90}}
        for axis, (negative, positive) in FACES.items():
            multipart.append({'when': {'axis': axis}, 'apply': {'model': f'create:block/{path}', **turns[axis]}})
            faces = RADIAL[axis] if radial else {negative: 'bottom', positive: 'top'}
            for face, key in faces.items():
                multipart.append({
                    'when': {'axis': axis, f'sticky_{key}': 'true'},
                    'apply': {'model': f'create:block/chassis_fallback/sticky_{face}'},
                })
        write(f'assets/create/blockstates/{name}.json', {'multipart': multipart})
        write(f'assets/create/models/item/{name}.json', {
            'parent': f'create:block/chassis_fallback/{name}_y',
        })
        write(f'assets/create/items/{name}.json', {'model': {
            'type': 'minecraft:model', 'model': f'create:item/{name}',
        }})
        write(f'data/create/loot_table/blocks/{name}.json', {
            'type': 'minecraft:block', 'random_sequence': f'create:blocks/{name}',
            'pools': [{'rolls': 1, 'bonus_rolls': 0,
                       'entries': [{'type': 'minecraft:item', 'name': f'create:{name}'}],
                       'conditions': [{'type': 'minecraft:survives_explosion'}]}],
        })
