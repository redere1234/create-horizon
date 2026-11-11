"""Built-in Item Drain body and grate using vanilla textures."""

BLOCK = 'item_drain'


def item_drain(write):
    shape = {'default': [[0, 0, 0, 1, 13 / 16, 1]]}
    write(f'data/create/horizon/block/{BLOCK}.json', {
        'template': 'minecraft:copper_block', 'item': True,
        # The copper template otherwise retains full-block light occlusion.
        'properties': {'occludes': False},
        'shapes': shape, 'collision_shapes': shape,
    })
    model = f'create:block/{BLOCK}'
    write(f'assets/create/blockstates/{BLOCK}.json', {'variants': {'': {'model': model}}})
    write(f'assets/create/models/item/{BLOCK}.json', {'parent': model})
    write(f'assets/create/items/{BLOCK}.json', {
        'model': {'type': 'minecraft:model', 'model': f'create:item/{BLOCK}'},
    })

    sides = ('down', 'up', 'north', 'south', 'west', 'east')
    copper = [([0, 0, 0], [16, 5, 16]),
              ([0, 5, 0], [2, 13, 16]), ([14, 5, 0], [16, 13, 16]),
              ([2, 5, 0], [14, 13, 2]), ([2, 5, 14], [14, 13, 16])]
    grate = [([2, 12, z], [14, 13, z + 1]) for z in (3, 6, 9, 12)]
    write(f'assets/create/models/block/{BLOCK}.json', {
        'textures': {'body': 'minecraft:block/copper_block', 'grate': 'minecraft:block/iron_block',
                     'particle': '#body'},
        'elements': [{'from': start, 'to': end, 'faces': dict.fromkeys(sides, {'texture': '#' + material})}
                     for material, boxes in [('body', copper), ('grate', grate)] for start, end in boxes],
    })
