"""Original interface states with independently built vanilla-textured models."""

PSI = 'portable_storage_interface'


def portable_storage(write, model, axial_boxes):
    turns = {'down': {'x': 180}, 'up': {}, 'north': {'x': 90},
             'south': {'x': 90, 'y': 180}, 'west': {'x': 90, 'y': 270},
             'east': {'x': 90, 'y': 90}}
    write(f'data/create/horizon/block/{PSI}.json', {
        'template': 'minecraft:stone', 'item': True,
        'properties': {'hardness': 1.5, 'explosion_resistance': 6, 'occludes': False,
                       'requires_tool': True, 'sounds': 'minecraft:andesite'},
        'state_properties': {'facing': {'type': 'enum', 'values': list(turns)}},
        'default_state': {'facing': 'north'},
        'shapes': {'property': 'facing', 'values': {
            face: axial_boxes(face, [(0, 0, 14)]) for face in turns
        }},
    })
    body = [([0, 0, 0], [16, 8, 16]), ([1, 8, 1], [15, 10, 15])]
    plate = [([2, 12, 2], [14, 14, 14])]
    stem = [([4, 3, 4], [12, 7, 12])]
    model(f'{PSI}/block', body, 'minecraft:block/polished_andesite')
    model(f'{PSI}/block_middle', stem, 'minecraft:block/iron_block')
    model(f'{PSI}/block_middle_powered', stem, 'minecraft:block/copper_block')
    model(f'{PSI}/block_top', plate, 'minecraft:block/iron_block')
    model(f'{PSI}/item', body + [([4, 9, 4], [12, 13, 12])] + plate,
          'minecraft:block/polished_andesite')
    write(f'assets/create/blockstates/{PSI}.json', {'variants': {
        f'facing={face}': {'model': f'create:block/{PSI}/block', **turn}
        for face, turn in turns.items()
    }})
    write(f'assets/create/models/item/{PSI}.json', {'parent': f'create:block/{PSI}/item'})
    write(f'assets/create/items/{PSI}.json', {'model': {
        'type': 'minecraft:model', 'model': f'create:item/{PSI}',
    }})
