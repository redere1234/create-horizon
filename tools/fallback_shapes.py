"""Independent fallback geometry for the motor and the water wheels."""

from math import cos, pi, radians, sin, sqrt, tan

from fallback_textures import material

WOODS = ('oak', 'spruce', 'birch', 'jungle', 'acacia', 'dark_oak', 'mangrove',
         'cherry', 'bamboo', 'crimson', 'warped', 'pale_oak')

FACES = ('down', 'up', 'north', 'south', 'west', 'east')


def box(start, end, skin, *, overrides=None, turns=None, angle=0):
    faces = {face: {'texture': '#' + (overrides or {}).get(face, skin), 'uv': [0, 0, 16, 16]}
             for face in FACES}
    for face, turn in (turns or {}).items():
        faces[face]['rotation'] = turn
    element = {'from': start, 'to': end, 'faces': faces}
    if angle:
        element['rotation'] = {'origin': [8, 8, 8], 'axis': 'y', 'angle': angle, 'rescale': False}
    return element


def motor(write):
    def model(name, value):
        write(f'assets/create/models/{name}.json', value)

    textures = {face: material(f'motor_{face}') for face in ('output', 'side', 'back', 'base')}
    textures.update(particle='#side', rail=material('wheel_iron'))
    horizontal = [
        box([3.5, 3.5, 1], [12.5, 12.5, 13.25], 'side', overrides={'down': 'base'}),
        box([3, 3, 0], [13, 13, 1.5], 'side', overrides={'north': 'back'}),
        box([3, 3, 12.5], [13, 13, 14], 'side', overrides={'south': 'output'}),
    ]
    vertical = [
        box([3.5, 1, 3.5], [12.5, 13.25, 12.5], 'side'),
        box([3, 0, 3], [13, 1.5, 13], 'side', overrides={'down': 'back'}),
        box([3, 12.5, 3], [13, 14, 13], 'side', overrides={'up': 'output'}),
    ]
    for x in (2.5, 12.0):
        for y in (2.5, 12.0):
            horizontal.append(box([x, y, .2], [x + 1.5, y + 1.5, 14.3], 'rail',
                                  turns={'up': 90, 'down': 90, 'west': 90, 'east': 90}))
            vertical.append(box([x, .2, y], [x + 1.5, 14.3, y + 1.5], 'rail'))
    model('block/creative_motor/block', {'textures': textures, 'elements': horizontal})
    model('block/creative_motor/block_vertical', {'textures': textures, 'elements': vertical})


def cogs(write):
    textures = {'wood': material('oak_cog'), 'iron': material('steel_axle'),
                'particle': '#wood'}
    shaft = box([6, 0, 6], [10, 16, 10], 'iron')
    for name, radius, count in [('cogwheel', 9, 8), ('large_cogwheel', 15, 12)]:
        rim = radius - 2
        elements = [
            box([8 - rim, 6 - index * .02, 8 - rim * .45],
                [8 + rim, 10 + index * .02, 8 + rim * .45], 'wood', angle=45 * index)
            for index in range(4)
        ]
        for tooth in range(count):
            half_width = 1.3 if count == 8 else 1.6
            elements.append(box([8 - half_width, 6.1, 8 + rim * .78],
                                [8 + half_width, 9.9, 8 + radius], 'wood',
                                angle=360 * tooth / count))
        for suffix, parts in [('', elements + [shaft]), ('_shaftless', elements)]:
            write(f'assets/create/models/block/{name}{suffix}.json',
                  {'textures': textures, 'elements': parts})


def flywheel_art(write):
    radius, count = 20.7, 12
    half_width = round(radius * tan(pi / count), 4)
    rim = [
        box([8 - half_width, 4.5, 8 + radius - 3.8], [8 + half_width, 11.5, 8 + radius],
            'brass', turns={'up': 90, 'down': 90}, angle=360 * index / count)
        for index in range(count)
    ]
    spokes = [
        box([6.7, 6.7, 11], [9.3, 9.3, 8 + radius - 2.7],
            'iron', turns={'west': 90, 'east': 90}, angle=45 * index)
        for index in range(8)
    ]
    hub = box([4.75, 5.8, 4.75], [11.25, 10.2, 11.25], 'iron')
    shaft = box([6, 0, 6], [10, 16, 10], 'iron')
    textures = {'brass': material('flywheel'), 'iron': material('steel_axle'),
                'particle': '#brass'}
    for name, extra in [('block', []), ('item', [shaft])]:
        write(f'assets/create/models/block/flywheel/{name}.json',
              {'textures': textures, 'elements': rim + spokes + [hub] + extra})


def wheel(radius, *, extension=False):
    large = radius > 20
    rim_radius = radius - (3.8 if large else 2.4)
    rim_half = round(rim_radius * (sqrt(2) - 1), 4)
    rim_depth = 7 if large else 2.8
    width = 5.5 if large else 3.6
    elements = []
    for turn in range(8):
        angle = 45 * turn
        elements.extend([
            box([6.3, 6.3, 8 + 2.6], [9.7, 9.7, 8 + rim_radius - 1], 'beam',
                overrides={'north': 'end', 'south': 'end'},
                turns={'west': 90, 'east': 90}, angle=angle),
            box([8 - rim_half, 4.8, 8 + rim_radius - rim_depth],
                [8 + rim_half, 11.2, 8 + rim_radius], 'beam',
                overrides={'west': 'end', 'east': 'end', 'up': 'plank', 'down': 'plank'},
                turns={'up': 90, 'down': 90}, angle=angle),
        ])
        for shift in (-rim_half * .6, rim_half * .6):
            x = 8 + shift
            elements.append(box([x - width / 2, 2.8, 8 + rim_radius - 2.4],
                                [x + width / 2, 13.2, 8 + radius], 'beam',
                                overrides={'north': 'plank', 'south': 'plank', 'up': 'end', 'down': 'end'},
                                angle=angle))
            elements.append(box([x - 1.15, 3.0, 8 + rim_radius - 1.4],
                                [x + 1.15, 4.75, 8 + rim_radius + .2], 'iron', angle=angle))
    hub = 5.7 if not large else 5.0
    return elements + [
        box([8 - hub, 3, 8 - hub], [8 + hub, 13, 8 + hub], 'beam',
            overrides={'up': 'end', 'down': 'end'}),
        box([4.1, 11.5, 4.1], [11.9, 13.9, 11.9], 'iron'),
        box([4.1, 2.1, 4.1], [11.9, 4.5, 11.9], 'iron'),
        box([6, 2 if extension else 0, 6], [10, 16, 10], 'iron'),
    ]


CORNERS = {
    'down': (1, 0, 4, 5), 'up': (2, 3, 7, 6),
    'north': (0, 2, 6, 4), 'south': (5, 7, 3, 1),
    'west': (1, 3, 2, 0), 'east': (4, 6, 7, 5),
}


def wheel_mesh(content, write, name, elements, textures):
    # The Java JSON cube reader caps element coordinates at [-16, 32].
    # Horizon's existing OBJ loader handles a full-size wheel and its UVs.
    obj = content / f'assets/create/models/block/{name}.obj'
    obj.parent.mkdir(parents=True, exist_ok=True)
    mtl = obj.parent / 'wheel.mtl'
    materials = ('beam', 'plank', 'end', 'iron')
    mtl.write_text(''.join(f'newmtl {key}\nmap_Kd #{key}\n' for key in materials))
    lines = [f'mtllib {mtl.name}', 'vt 0 1', 'vt 0 0', 'vt 1 0', 'vt 1 1']
    for index, element in enumerate(elements):
        low, high = element['from'], element['to']
        angle = radians(element.get('rotation', {}).get('angle', 0))
        for i in range(8):
            x, y, z = [(high if i & bit else low)[axis] for axis, bit in enumerate((4, 2, 1))]
            dx, dz = x - 8, z - 8
            px = (8 + cos(angle) * dx + sin(angle) * dz) / 16
            pz = (8 - sin(angle) * dx + cos(angle) * dz) / 16
            lines.append(f'v {px:.6f} {y / 16:.6f} {pz:.6f}')
        for direction, face in element['faces'].items():
            lines.append('usemtl ' + face['texture'][1:])
            turn = face.get('rotation', 0) // 90
            refs = [f'{index * 8 + corner + 1}/{(j + turn) % 4 + 1}'
                    for j, corner in enumerate(CORNERS[direction])]
            lines.append('f ' + ' '.join(refs))
    obj.write_text('\n'.join(lines) + '\n')
    write(f'assets/create/models/block/{name}.json', {
        'loader': 'neoforge:obj', 'flip_v': True, 'model': f'create:models/block/{name}.obj',
        'textures': textures,
    })


def wheels(content, write):
    def model(name, value):
        write(f'assets/create/models/{name}.json', value)

    textures = {part: material(f'wheel_spruce_{part}') for part in ('beam', 'plank', 'end')}
    textures.update(iron=material('wheel_iron'), particle='#plank')
    for path, radius, extension in [
        ('water_wheel/wheel', 15.6, False),
        ('large_water_wheel/block', 37.5, False),
        ('large_water_wheel/block_extension', 37.5, True),
    ]:
        wheel_mesh(content, write, path, wheel(radius, extension=extension), textures)
        for wood in WOODS:
            model(f'block/{path}_material_{wood}', {
                'parent': f'create:block/{path}',
                'textures': {part: material(f'wheel_{wood}_{part}') for part in ('beam', 'plank', 'end')},
            })
    model('item/large_water_wheel', {
        'parent': 'create:block/large_water_wheel/block',
        'display': {
            'gui': {'rotation': [25, 30, 0], 'scale': [.21, .21, .21]},
            'ground': {'scale': [.1, .1, .1]},
            'fixed': {'rotation': [90, 0, 0], 'scale': [.18, .18, .18]},
            'firstperson_righthand': {'scale': [.18, .18, .18]},
            'firstperson_lefthand': {'scale': [.18, .18, .18]},
            'thirdperson_righthand': {'scale': [.12, .12, .12]},
            'thirdperson_lefthand': {'scale': [.12, .12, .12]},
        },
    })
