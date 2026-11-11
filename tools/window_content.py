"""Create 6.0.10 glass, windows, window panes (AllPaletteBlocks, WindowGen) and
the three decorative casings (AllBlocks: shadow steel, refined radiance, railway).

IDs, base properties, blockstate and model layout follow the pinned MIT
sources. Connected textures are not reproduced. Fallback art is drawn below.
"""
import random

WOODS = ('oak', 'spruce', 'birch', 'jungle', 'acacia', 'dark_oak', 'mangrove', 'crimson', 'warped',
         'cherry', 'bamboo')
# Planks' default MapColor ids (WindowGen uses planksBlock::defaultMapColor).
WOOD_COLORS = {'oak': 13, 'spruce': 34, 'birch': 2, 'jungle': 10, 'acacia': 15, 'dark_oak': 26,
               'mangrove': 28, 'crimson': 53, 'warped': 56, 'cherry': 36, 'bamboo': 18}
FRAMED = ('framed_glass', 'horizontal_framed_glass', 'vertical_framed_glass')
IRON_WINDOWS = {'ornate_iron_window': 44, 'industrial_iron_window': 21, 'weathered_iron_window': 44}

GLASS_BLOCKS = ['tiled_glass', *FRAMED]
WINDOW_BLOCKS = [f'{wood}_window' for wood in WOODS] + list(IRON_WINDOWS)
PANES = ['tiled_glass_pane', *[f'{name}_pane' for name in FRAMED],
         *[f'{name}_pane' for name in WINDOW_BLOCKS]]
# Creative order: AllPaletteBlocks registration order.
WINDOW_PALETTE = GLASS_BLOCKS + PANES[:4] + WINDOW_BLOCKS + PANES[4:]
CASINGS = ['shadow_steel_casing', 'refined_radiance_casing', 'railway_casing']
LABELS = {'shadow_steel_casing': 'Shadow Casing', 'refined_radiance_casing': 'Radiant Casing',
          'railway_casing': 'Train Casing'}

GLASS = {'hardness': 0.3, 'explosion_resistance': 0.3, 'sounds': 'minecraft:glass'}
GUI = {'rotation': [30, 225, 0], 'scale': [.625, .625, .625]}


def label(name):
    return LABELS.get(name, ' '.join(word.title() for word in name.split('_')))


def fb(name):
    return f'create:block/fallback/{name}'


def pane_blockstate(model):
    # RegistrateBlockstateProvider.paneBlock / vanilla glass pane layout.
    parts = [{'apply': {'model': model + '_post'}}]
    for side, suffix, y in (('north', '', 0), ('east', '', 90), ('south', '_alt', 0), ('west', '_alt', 90)):
        for value, kind in (('true', '_side'), ('false', '_noside')):
            if value == 'false':
                # noside faces are mirrored: north/east use noside, south/west noside_alt,
                # each rotated to the neighbouring side.
                noside = {'north': ('', 0), 'east': ('_alt', 0), 'south': ('_alt', 90), 'west': ('', 270)}[side]
                apply = {'model': model + kind + noside[0]}
                if noside[1]:
                    apply['y'] = noside[1]
            else:
                apply = {'model': model + kind + suffix}
                if y:
                    apply['y'] = y
            parts.append({'apply': apply, 'when': {side: value}})
    return {'multipart': parts}


def generate(write):
    tiles = set()

    def tex(name):
        tiles.add(name)
        return fb(name)

    def simple(name, model, decl, item=None):
        write(f'data/create/horizon/block/{name}.json', decl)
        write(f'assets/create/blockstates/{name}.json', {'variants': {'': {'model': f'create:block/{name}'}}})
        write(f'assets/create/models/block/{name}.json', model)
        write(f'assets/create/models/item/{name}.json', item or {'parent': f'create:block/{name}'})
        write(f'assets/create/items/{name}.json', {
            'model': {'type': 'minecraft:model', 'model': f'create:item/{name}'}})

    glass = {'template': 'minecraft:glass', 'item': True, 'properties': dict(GLASS)}
    simple('tiled_glass', {'parent': 'minecraft:block/cube_all', 'textures': {'all': tex('tiled_glass')}}, glass)
    for name in FRAMED:
        # BlockStateGen.cubeAll(..., "framed_glass"): every framed glass shows the framed tile
        # until connected textures apply; the item shows its own side.
        simple(name, {'parent': 'minecraft:block/cube_all', 'textures': {'all': tex('framed_glass')}}, glass,
               {'parent': 'minecraft:block/cube_column',
                'textures': {'end': tex('framed_glass'), 'side': tex(name)}, 'display': {'gui': dict(GUI)}})

    windows = {}
    for wood in WOODS:
        windows[f'{wood}_window'] = (tex(f'wheel_{wood}_plank'), WOOD_COLORS[wood], tex(f'wheel_{wood}_plank'))
    for name, color in IRON_WINDOWS.items():
        end = f'{name}_1_end' if name == 'weathered_iron_window' else f'{name}_end'
        windows[name] = (tex(end), color, tex(f'{name}_pane_top'))
    for name, (end, color, _) in windows.items():
        decl = {'template': 'minecraft:glass', 'item': True, 'properties': dict(GLASS, map_color=color)}
        side = tex(name)
        if name == 'weathered_iron_window':
            write(f'data/create/horizon/block/{name}.json', decl)
            for index in range(1, 5):
                write(f'assets/create/models/block/{name}_{index}.json', {
                    'parent': 'minecraft:block/cube_column',
                    'textures': {'end': tex(f'{name}_{index}_end'), 'side': side}})
            write(f'assets/create/blockstates/{name}.json', {'variants': {'': [
                {'model': f'create:block/{name}_{index}'} for index in range(1, 5)]}})
            write(f'assets/create/models/item/{name}.json', {'parent': f'create:block/{name}_1'})
            write(f'assets/create/items/{name}.json', {
                'model': {'type': 'minecraft:model', 'model': f'create:item/{name}'}})
        else:
            simple(name, {'parent': 'minecraft:block/cube_column', 'textures': {'end': end, 'side': side}}, decl)

    pane_textures = {'tiled_glass_pane': (tex('tiled_glass'), tex('tiled_glass'), tex('glass_pane_top'), 0)}
    for name in FRAMED:
        pane_textures[f'{name}_pane'] = (tex('framed_glass'), tex(name), tex('framed_glass_pane_top'), 0)
    for name, (_, color, top) in windows.items():
        pane_textures[f'{name}_pane'] = (tex(name), tex(name), top, color)
    for name, (side, item_side, top, color) in pane_textures.items():
        decl = {'template': 'minecraft:glass_pane', 'item': True,
                'properties': {'hardness': 0.3, 'explosion_resistance': 0.3, 'sounds': 'minecraft:glass',
                               'map_color': color}}
        write(f'data/create/horizon/block/{name}.json', decl)
        write(f'assets/create/blockstates/{name}.json', pane_blockstate(f'create:block/{name}'))
        for part in ('post', 'side', 'side_alt', 'noside', 'noside_alt'):
            write(f'assets/create/models/block/{name}_{part}.json', {
                'parent': f'minecraft:block/template_glass_pane_{part}',
                'textures': {'edge': top, 'pane': side}})
        write(f'assets/create/models/item/{name}.json', {
            'parent': 'minecraft:item/generated', 'textures': {'layer0': item_side}})
        write(f'assets/create/items/{name}.json', {
            'model': {'type': 'minecraft:model', 'model': f'create:item/{name}'}})

    # BuilderTransformers.casing / layeredCasing: SharedProperties.stone (andesite).
    casing = {'shadow_steel_casing': {'map_color': 29, 'sounds': 'minecraft:oak_planks'},
              'refined_radiance_casing': {'map_color': 8, 'sounds': 'minecraft:oak_planks', 'light': 12},
              'railway_casing': {'map_color': 45, 'sounds': 'minecraft:netherite_block'}}
    for name, props in casing.items():
        decl = {'template': 'minecraft:andesite', 'item': True, 'properties': props}
        if name == 'railway_casing':
            model = {'parent': 'minecraft:block/cube_column',
                     'textures': {'end': tex('railway_casing'), 'side': tex('railway_casing_side')}}
        else:
            model = {'parent': 'minecraft:block/cube_all', 'textures': {'all': tex(name)}}
        simple(name, model, decl)
    write('data/minecraft/tags/block/impermeable.json',
          {'values': [f'create:{name}' for name in GLASS_BLOCKS + WINDOW_BLOCKS]})
    return tiles


# ---- Procedural fallback tiles (RGBA, independent art, MIT) ----

def draw(name, plank=None):
    rng = random.Random(name)
    clear = (0, 0, 0, 0)
    px = [[clear] * 16 for _ in range(16)]

    def frame(color, width=1, sides='nsew'):
        for i in range(16):
            for w in range(width):
                if 'n' in sides:
                    px[w][i] = color
                if 's' in sides:
                    px[15 - w][i] = color
                if 'w' in sides:
                    px[i][w] = color
                if 'e' in sides:
                    px[i][15 - w] = color

    def streak(color):
        for i in range(3, 9):
            if 0 < 12 - i < 16:
                px[i][12 - i] = color
                px[i + 1][12 - i] = color

    glint = (230, 245, 250, 150)
    tint = (200, 225, 235, 40)
    if name == 'tiled_glass':
        px = [[tint] * 16 for _ in range(16)]
        for i in range(16):
            for j in (0, 8):
                px[j][i] = px[i][j] = (220, 232, 238, 200)
        streak(glint)
    elif name in ('framed_glass', 'horizontal_framed_glass', 'vertical_framed_glass'):
        px = [[tint] * 16 for _ in range(16)]
        sides = {'framed_glass': 'nsew', 'horizontal_framed_glass': 'ns', 'vertical_framed_glass': 'ew'}[name]
        frame((96, 100, 104, 255), 1, sides)
        streak(glint)
    elif name in ('framed_glass_pane_top', 'glass_pane_top'):
        px = [[(150, 160, 166, 255) if 7 <= x <= 8 else (210, 225, 230, 255) for x in range(16)]
              for _ in range(16)]
    elif name.endswith('_window') and plank:
        px = [[(205, 225, 232, 70)] * 16 for _ in range(16)]
        frame(plank, 2)
        for i in range(16):
            px[7][i] = px[8][i] = plank
            px[i][7] = px[i][8] = plank
        streak(glint)
    elif name.startswith(('ornate_iron_window', 'industrial_iron_window', 'weathered_iron_window')):
        metal = {'ornate': (70, 72, 76, 255), 'industrial': (92, 96, 100, 255),
                 'weathered': (122, 92, 70, 255)}[name.split('_')[0]]
        if name.endswith('_end') or name.endswith('_top'):
            px = [[tuple(int(c * rng.uniform(.9, 1.1)) for c in metal[:3]) + (255,) for _ in range(16)]
                  for _ in range(16)]
        else:
            px = [[(200, 220, 228, 60)] * 16 for _ in range(16)]
            frame(metal, 2 if name.startswith('industrial') else 1)
            if name.startswith('ornate'):
                for i in range(16):
                    px[i][i] = px[i][15 - i] = metal
            else:
                for i in range(16):
                    px[i][7] = px[i][8] = metal
                    px[5][i] = px[10][i] = metal
    elif 'casing' in name:
        base = {'shadow_steel_casing': (40, 34, 52), 'refined_radiance_casing': (236, 234, 220),
                'railway_casing': (52, 86, 90), 'railway_casing_side': (52, 86, 90)}[name]
        px = [[tuple(max(0, min(255, int(c * rng.uniform(.93, 1.07)))) for c in base) + (255,)
               for _ in range(16)] for _ in range(16)]
        edge = tuple(max(0, int(c * .65)) for c in base) + (255,)
        light = tuple(min(255, int(c * 1.2) + 10) for c in base) + (255,)
        frame(edge, 2)
        for i in range(2, 14):
            px[2][i] = px[i][2] = light
        if name == 'railway_casing_side':
            for i in range(16):
                px[5][i] = px[10][i] = edge
    return px


def png_rgba(px):
    import struct
    import zlib
    raw = b''.join(b'\0' + bytes(c for p in row for c in p) for row in px)

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    header = struct.pack('>IIBBBBB', 16, 16, 8, 6, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(raw, 9))
            + chunk(b'IEND', b''))


def write_tiles(content, tiles):
    folder = content / 'assets/create/textures/block/fallback'
    folder.mkdir(parents=True, exist_ok=True)

    def plank_color(wood):
        data = (folder / f'wheel_{wood}_plank.png')
        from PIL import Image
        image = Image.open(data).convert('RGB')
        pixels = list(image.getdata())
        return tuple(sum(p[i] for p in pixels) // len(pixels) for i in range(3)) + (255,)

    for name in sorted(tiles):
        path = folder / f'{name}.png'
        if path.exists():
            continue
        wood = name.removesuffix('_window') if name.removesuffix('_window') in WOODS else None
        px = draw(name, plank_color(wood) if wood else None)
        path.write_bytes(png_rgba(px))
