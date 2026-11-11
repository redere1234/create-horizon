"""Authored fallback geometry for ordinary Funnels."""

from fallback_textures import material

BLOCK = 'andesite_funnel'
BRASS = 'brass_funnel'
FACES = ('down', 'up', 'north', 'south', 'west', 'east')
NORTH = [(2, 2, 14, 14, 14, 18), (1, 8, 12, 15, 15, 14),
         (0.1, 13, 7, 15.9, 15, 11), (0.1, 9, 8, 15.9, 13, 12),
         (0.1, 5, 9, 15.9, 9, 13), (0.1, 1, 10, 15.9, 5, 14),
         (0.1, -1, 11, 15.9, 1, 15)]
UP = [(2, -2, 2, 14, 8, 14), (1, 1, 1, 15, 8, 15), (0, 4, 0, 16, 10, 16)]
Y_ROTATION = {'north': 0, 'east': 90, 'south': 180, 'west': 270}


def clockwise(box):
    x1, y1, z1, x2, y2, z2 = box
    return 16 - z2, y1, x1, 16 - z1, y2, x2


def shape(facing):
    if facing == 'up':
        return UP
    if facing == 'down':
        return [(x1, 16 - y2, z1, x2, 16 - y1, z2) for x1, y1, z1, x2, y2, z2 in UP]
    boxes = NORTH
    for _ in range(Y_ROTATION[facing] // 90):
        boxes = [clockwise(box) for box in boxes]
    return boxes


def funnel(write, model, block=BLOCK):
    brass = block == BRASS
    model_dir = 'brass_funnel' if brass else 'funnel'
    off, on = (('minecraft:block/gold_block', 'minecraft:block/copper_block') if brass
               else ('minecraft:block/andesite', 'minecraft:block/polished_andesite'))
    shapes = {'property': 'facing', 'values': {
        face: [[value / 16 for value in box] for box in shape(face)] for face in FACES
    }}
    write(f'data/create/horizon/block/{block}.json', {
        'template': 'minecraft:gold_block' if brass else 'minecraft:stone', 'item': True,
        'properties': {'occludes': False, 'requires_tool': True, **({'map_color': 40} if brass else {})},
        'state_properties': {'facing': {'type': 'enum', 'values': FACES},
                             **{name: {'type': 'boolean'} for name in ('extracting', 'powered', 'waterlogged')}},
        'default_state': {'facing': 'north', 'extracting': 'false', 'powered': 'false', 'waterlogged': 'false'},
        'shapes': shapes, 'collision_shapes': shapes,
    })
    for kind, geometry in [('horizontal', NORTH), ('vertical', UP)]:
        for powered, texture in [('off', off), ('on', on)]:
            boxes = [(box[:3], box[3:]) for box in geometry]
            parts = None
            if brass and kind == 'vertical':
                # An upwards funnel's click target sits at y=2 on every side.
                # The downwards model is the same shell rotated 180 degrees.
                boxes += [([5, 0, .98], [11, 4, 1], 'filter'),
                          ([5, 0, 15], [11, 4, 15.02], 'filter'),
                          ([.98, 0, 5], [1, 4, 11], 'filter'),
                          ([15, 0, 5], [15.02, 4, 11], 'filter')]
                parts = {'filter': material('brass_funnel_filter')}
            model(f'{model_dir}/{kind}_{powered}', boxes, texture, parts=parts)
    variants = {}
    for face in FACES:
        orientation = ({'y': Y_ROTATION[face]} if face in Y_ROTATION else {'x': 180} if face == 'down' else {})
        kind = 'horizontal' if face in Y_ROTATION else 'vertical'
        for powered, suffix in [('false', 'off'), ('true', 'on')]:
            variants[f'facing={face},powered={powered}'] = {
                'model': f'create:block/{model_dir}/{kind}_{suffix}', **orientation,
            }
    write(f'assets/create/blockstates/{block}.json', {'variants': variants})
    write(f'assets/create/models/item/{block}.json', {
        'parent': f'create:block/{model_dir}/' + ('vertical_off' if brass else 'horizontal_off'),
    })
    write(f'assets/create/items/{block}.json', {'model': {'type': 'minecraft:model', 'model': f'create:item/{block}'}})
