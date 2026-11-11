"""Built-in Deployer shell and source voxel shapes for the moving farm tool."""

from fallback_textures import material


def deployer(write, model):
    rotations = {'down': {'x': 270}, 'up': {'x': 90}, 'north': {'y': 180},
                 'south': {}, 'west': {'y': 90}, 'east': {'y': 270}}
    axes = {'down': 1, 'up': 1, 'north': 2, 'south': 2, 'west': 0, 'east': 0}
    collision, outline = {}, {}
    for face, axis in axes.items():
        low, high = [0, 0, 0], [1, 1, 1]
        if face in ('down', 'north', 'west'):
            low[axis] = 4 / 16
        else:
            high[axis] = 12 / 16
        collision[face] = [low + high]
        low, high = [5 / 16] * 3, [11 / 16] * 3
        low[axis], high[axis] = 0, 1
        outline[face] = collision[face] + [low + high]
    write('data/create/horizon/block/deployer.json', {
        'template': 'minecraft:glass', 'item': True,
        'properties': {'hardness': 1.5, 'explosion_resistance': 6,
                       'requires_tool': True, 'occludes': False,
                       'render_shape': 'MODEL', 'sounds': 'minecraft:andesite'},
        'state_properties': {'facing': {'type': 'enum', 'values': list(rotations)},
                             'axis_along_first': {'type': 'boolean'}},
        'default_state': {'facing': 'north', 'axis_along_first': 'true'},
        'shapes': {'property': 'facing', 'values': outline},
        'collision_shapes': {'property': 'facing', 'values': collision},
    })
    body = [([0, 0, 0], [16, 16, 12])]
    filter_material = {'filter': material('deployer_filter')}
    model('deployer/fallback', body + [
        ([5, -.02, 3], [11, 0, 9], 'filter'), ([5, 16, 3], [11, 16.02, 9], 'filter'),
    ], material('deployer'), parts=filter_material)
    model('deployer/fallback_side_filter', body + [
        ([-.02, 5, 3], [0, 11, 9], 'filter'), ([16, 5, 3], [16.02, 11, 9], 'filter'),
    ], material('deployer'), parts=filter_material)
    model('deployer/pole', [([6, 6, 1], [10, 10, 14])], 'minecraft:block/iron_block')
    for hand in ('pointing', 'holding'):
        model(f'deployer/hand_{hand}', [([5, 5, 12], [11, 11, 16])], 'minecraft:block/raw_gold_block')
    model('deployer/hand_punching', [([4, 4, 11], [12, 12, 16])], 'minecraft:block/raw_gold_block')
    model('deployer/item_fallback', body + [
        ([5, 16, 3], [11, 16.02, 9], 'filter'), ([5, 5, 12], [11, 11, 16], 'hand'),
    ], material('deployer'), parts={**filter_material, 'hand': material('deployer_hand')})
    write('assets/create/blockstates/deployer.json', {'variants': {
        f'axis_along_first={first},facing={face}': {
            'model': 'create:block/deployer/fallback' + (
                '_side_filter' if (first == 'true') == (axes[face] == 0) else ''
            ), **rotation,
        }
        for face, rotation in rotations.items() for first in ('false', 'true')
    }})
    write('assets/create/models/item/deployer.json', {'parent': 'create:block/deployer/item_fallback'})
    write('assets/create/items/deployer.json', {'model': {'type': 'minecraft:model', 'model': 'create:item/deployer'}})
