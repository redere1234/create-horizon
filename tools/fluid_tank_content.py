"""Ordinary Fluid Tank with a simple vanilla-textured fallback."""

from itertools import product

BLOCK = 'fluid_tank'
SHAPES = ('plain', 'window', 'window_nw', 'window_sw', 'window_ne', 'window_se')


def fluid_tank(write, model):
    write(f'data/create/horizon/block/{BLOCK}.json', {
        'template': 'minecraft:copper_block',
        'item': True,
        'properties': {'occludes': False},
        'state_properties': {'top': {'type': 'boolean'}, 'bottom': {'type': 'boolean'},
                             'shape': {'type': 'enum', 'values': SHAPES}},
        'default_state': {'top': 'true', 'bottom': 'true', 'shape': 'window'},
    })
    model(f'{BLOCK}/block_single', [([0, 0, 0], [16, 16, 16])], 'minecraft:block/copper_block')
    sides = ('down', 'up', 'north', 'south', 'west', 'east')
    caps = [([0, 0, 0], [16, 4, 16]), ([0, 12, 0], [16, 16, 16])]
    corners = [([x, 4, z], [x + 2, 12, z + 2]) for x, z in product((0, 14), repeat=2)]
    panes = [([2, 4, z], [14, 12, z + 1]) for z in (0, 15)]
    panes += [([x, 4, 2], [x + 1, 12, 14]) for x in (0, 15)]
    write(f'assets/create/models/block/{BLOCK}/block_single_window.json', {
        'textures': {'frame': 'minecraft:block/copper_block', 'glass': 'minecraft:block/glass',
                     'particle': '#frame'},
        'elements': [{'from': start, 'to': end,
                      'faces': dict.fromkeys(sides, {'texture': '#' + material})}
                     for material, boxes in [('frame', caps + corners), ('glass', panes)]
                     for start, end in boxes],
    })
    base = f'create:block/{BLOCK}/block_single'
    write(f'assets/create/blockstates/{BLOCK}.json', {'variants': {
        f'bottom={bottom},shape={shape},top={top}': {'model': base + ('' if shape == 'plain' else '_window')}
        for bottom, shape, top in product(('false', 'true'), SHAPES, ('false', 'true'))
    }})
    write(f'assets/create/models/item/{BLOCK}.json', {'parent': base + '_window'})
    write(f'assets/create/items/{BLOCK}.json', {
        'model': {'type': 'minecraft:model', 'model': f'create:item/{BLOCK}'},
    })
