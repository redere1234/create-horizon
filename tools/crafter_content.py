"""Built-in Mechanical Crafter resources using vanilla textures."""

CRAFTER = 'mechanical_crafter'
PARTS = ('block', 'item', 'arrow', 'belt', 'belt_animated', 'lid')
FACING_ROTATION = {'north': 0, 'east': 90, 'south': 180, 'west': 270}
POINTING = ('up', 'left', 'down', 'right')


def crafter(write, model):
    base = f'create:block/{CRAFTER}'
    write(f'data/create/horizon/block/{CRAFTER}.json', {
        'template': 'minecraft:gold_block', 'item': True,
        'properties': {'occludes': False, 'map_color': 40, 'render_shape': 'MODEL'},
        'state_properties': {
            'facing': {'type': 'enum', 'values': list(FACING_ROTATION)},
            'pointing': {'type': 'enum', 'values': list(POINTING)},
        },
        'default_state': {'facing': 'north', 'pointing': 'up'},
    })
    write(f'assets/create/blockstates/{CRAFTER}.json', {'variants': {
        f'facing={facing},pointing={pointing}': {
            'model': f'{base}/block', **({'y': rotation} if rotation else {})}
        for facing, rotation in FACING_ROTATION.items() for pointing in POINTING
    }})

    # The north-facing fallback has a brass frame around the visible item slot.
    sides = ('down', 'up', 'north', 'south', 'west', 'east')
    boxes = [([0, 0, 2], [16, 16, 16], 'case'),
             ([0, 0, 0], [4, 16, 2], 'frame'), ([12, 0, 0], [16, 16, 2], 'frame'),
             ([4, 0, 0], [12, 4, 2], 'frame'), ([4, 12, 0], [12, 16, 2], 'frame'),
             ([4, 4, 1], [12, 12, 2], 'slot')]
    write(f'assets/create/models/block/{CRAFTER}/block.json', {
        'textures': {'case': 'minecraft:block/yellow_terracotta', 'frame': 'minecraft:block/gold_block',
                     'slot': 'minecraft:block/stripped_dark_oak_log_top', 'particle': '#case'},
        'elements': [{'from': start, 'to': end, 'faces': dict.fromkeys(sides, {'texture': '#' + material})}
                     for start, end, material in boxes],
    })
    write(f'assets/create/models/block/{CRAFTER}/item.json', {'parent': f'{base}/block'})
    write(f'assets/create/models/item/{CRAFTER}.json', {'parent': f'{base}/item'})
    write(f'assets/create/items/{CRAFTER}.json', {
        'model': {'type': 'minecraft:model', 'model': f'create:item/{CRAFTER}'},
    })

    # These partials share Java's west-facing, upward-pointing local frame.
    model(f'{CRAFTER}/arrow', [([-0.75, 11, 7], [0, 14, 9]), ([-0.75, 13, 6], [0, 14, 10]),
                               ([-0.75, 14, 7.5], [0, 15, 8.5])], 'minecraft:block/gold_block')
    model(f'{CRAFTER}/belt', [([-0.5, 12, 5], [0.5, 19, 6]), ([-0.5, 12, 10], [0.5, 19, 11])],
          'minecraft:block/yellow_terracotta')
    model(f'{CRAFTER}/belt_animated', [([-0.75, 12, 6], [0, 19, 10])], 'minecraft:block/black_concrete')
    model(f'{CRAFTER}/lid', [([-0.75, 5, 5], [0, 11, 11])], 'minecraft:block/yellow_terracotta')
