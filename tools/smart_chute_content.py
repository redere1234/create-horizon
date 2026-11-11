"""Canonical Smart Chute states and authored vanilla-textured fallback."""

from fallback_textures import material

BLOCK = 'smart_chute'


def smart_chute(write, model):
    shape = {'default': [[0, 0, 0, 1, 1, 1]]}
    write(f'data/create/horizon/block/{BLOCK}.json', {
        # Glass gives this full cube the original nonconducting/non-suffocating defaults.
        'template': 'minecraft:glass', 'item': True,
        'properties': {'hardness': 3.0, 'explosion_resistance': 6.0, 'occludes': False,
                       'requires_tool': True, 'sounds': 'minecraft:netherite_block', 'map_color': 21},
        'state_properties': {'powered': {'type': 'boolean'}},
        'default_state': {'powered': 'true'}, 'shapes': shape, 'collision_shapes': shape,
    })
    walls = [([0, 0, 0], [3, 16, 16]), ([13, 0, 0], [16, 16, 16]),
             ([3, 0, 0], [13, 16, 3]), ([3, 0, 13], [13, 16, 16])]
    slots = [([5, 8, -.02], [11, 14, 0], 'filter'),
             ([5, 8, 16], [11, 14, 16.02], 'filter'),
             ([-.02, 8, 5], [0, 14, 11], 'filter'),
             ([16, 8, 5], [16.02, 14, 11], 'filter')]
    for suffix, tile in (('', 'smart_chute'), ('_powered', 'smart_chute_powered')):
        # SmartChuteFilterSlotPositioning centers every horizontal filter at y=11.
        gate = [([3, 2, 3], [13, 4, 13], 'gate')] if suffix else []
        model(f'{BLOCK}/block{suffix}', walls + slots + gate, material(tile),
              parts={'filter': material('smart_chute_filter'), 'gate': material('chute')})
    write(f'assets/create/blockstates/{BLOCK}.json', {'variants': {
        'powered=false': {'model': f'create:block/{BLOCK}/block'},
        'powered=true': {'model': f'create:block/{BLOCK}/block_powered'},
    }})
    write(f'assets/create/models/item/{BLOCK}.json', {'parent': f'create:block/{BLOCK}/block'})
    write(f'assets/create/items/{BLOCK}.json', {'model': {'type': 'minecraft:model', 'model': f'create:item/{BLOCK}'}})
