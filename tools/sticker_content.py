"""Original Sticker state schema with built-in vanilla-textured models."""

from fallback_textures import material

STICKER = 'sticker'


def sticker(write, model):
    turns = {'down': {'x': 180}, 'up': {}, 'north': {'x': 90},
             'south': {'x': 90, 'y': 180}, 'west': {'x': 90, 'y': 270},
             'east': {'x': 90, 'y': 90}}
    write(f'data/create/horizon/block/{STICKER}.json', {
        # StickerBlock.shouldCheckWeakPower is false. Glass gives an inert
        # full collision box without inheriting stone's redstone conduction.
        'template': 'minecraft:glass', 'item': True,
        'properties': {'hardness': 1.5, 'explosion_resistance': 6.0, 'occludes': False,
                       'requires_tool': True, 'map_color': 11, 'sounds': 'minecraft:stone'},
        'state_properties': {'facing': {'type': 'enum', 'values': list(turns)},
                             'powered': {'type': 'boolean'}, 'extended': {'type': 'boolean'}},
        'default_state': {'facing': 'north', 'powered': 'false', 'extended': 'false'},
    })
    base = [([0, 0, 0], [16, 9, 16])]
    head = [([2, 9, 2], [14, 13, 14])]
    model(f'{STICKER}/block', base, 'minecraft:block/piston_side')
    model(f'{STICKER}/block_powered', base, 'minecraft:block/redstone_block')
    model(f'{STICKER}/head', head, 'minecraft:block/slime_block')
    model(f'{STICKER}/item', base + [(*head[0], 'slide'), ([2, 13, 2], [14, 14, 14], 'pad')],
          material('sticker'), parts={'slide': material('sticker_slide'), 'pad': material('sticker_pad')})
    write(f'assets/create/blockstates/{STICKER}.json', {'variants': {
        f'extended={extended},facing={face},powered={powered}': {
            'model': f'create:block/{STICKER}/block' + ('_powered' if powered == 'true' else ''),
            **turn,
        }
        for extended in ('false', 'true')
        for face, turn in turns.items()
        for powered in ('false', 'true')
    }})
    write(f'assets/create/models/item/{STICKER}.json', {'parent': f'create:block/{STICKER}/item'})
    write(f'assets/create/items/{STICKER}.json', {'model': {
        'type': 'minecraft:model', 'model': f'create:item/{STICKER}',
    }})
