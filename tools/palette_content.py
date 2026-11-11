"""Create 6.0.10 stone palettes: AllPaletteStoneTypes x PaletteBlockPattern x PaletteBlockPartial.

IDs, patterns, partials, base properties and model/blockstate layout follow the
pinned MIT sources (content/decoration/palettes). The blockstates and models are
generated here from that layout. The original textures stay in the player's JAR;
without it the blocks use the procedurally drawn fallback tiles below.
"""
import random
import struct
import zlib
from pathlib import Path

# Vanilla stones keep their vanilla base block; the seven Create stones are
# registered by paletteStoneBlock. Order is the enum order.
VANILLA_STONES = ('granite', 'diorite', 'andesite', 'calcite', 'dripstone', 'deepslate', 'tuff')
CREATE_STONES = ('asurine', 'crimsite', 'limestone', 'ochrum', 'scoria', 'scorchia', 'veridium')
# paletteStoneBlock(..., hasNaturalVariants): four random cube models.
NATURAL_VARIANTS = ('asurine', 'crimsite', 'ochrum', 'veridium')
STONES = VANILLA_STONES + CREATE_STONES

# Properties a block copies from its base (initialProperties / ofFullCopy).
# (plain vanilla template, hardness, explosion resistance, sounds, MapColor id)
# A deepslate base is a RotatedPillarBlock; cobbled deepslate has its sounds
# without the axis, and the hardness below restores deepslate's.
BASE = {
    'granite': ('granite', 1.5, 6.0, 'stone', 10),
    'diorite': ('diorite', 1.5, 6.0, 'stone', 14),
    'andesite': ('andesite', 1.5, 6.0, 'stone', 11),
    'calcite': ('calcite', 0.75, 0.75, 'calcite', 36),
    'dripstone': ('dripstone_block', 1.5, 1.0, 'dripstone_block', 48),
    'deepslate': ('cobbled_deepslate', 3.0, 6.0, 'deepslate', 59),
    'tuff': ('tuff', 1.5, 6.0, 'tuff', 43),
    # paletteStoneBlock(base) + destroyTime(1.25) where the enum sets it, and mapColor.
    'asurine': ('cobbled_deepslate', 1.25, 6.0, 'deepslate', 25),
    'crimsite': ('cobbled_deepslate', 1.25, 6.0, 'deepslate', 28),
    'limestone': ('sandstone', 1.25, 0.8, 'sandstone', 2),
    'ochrum': ('calcite', 1.25, 0.75, 'calcite', 40),
    'scoria': ('blackstone', 1.5, 6.0, 'blackstone', 26),
    'scorchia': ('blackstone', 1.5, 6.0, 'blackstone', 43),
    'veridium': ('tuff', 1.25, 6.0, 'tuff', 55),
}

# PaletteBlockPattern: (id, name type, texture kinds, partials, slab with its own side)
PATTERNS = (
    ('cut', 'prefix', ('cut',), True, False),
    ('polished_cut', 'prefix', ('polished', 'slab'), True, True),
    ('cut_bricks', 'wrap', ('brick',), True, False),
    ('small_bricks', 'wrap', ('small_brick',), True, False),
    ('layered', 'prefix', ('layered', 'cap'), False, False),
    ('pillar', 'suffix', ('pillar', 'cap'), False, False),
)
PARTIALS = ('stairs', 'slab', 'wall')


def pattern_name(pattern, name_type, stone):
    if name_type == 'wrap':
        first, second = pattern.split('_')
        return f'{first}_{stone}_{second}'
    return f'{stone}_{pattern}' if name_type == 'suffix' else f'{pattern}_{stone}'


def partial_name(block, partial):
    # Lang.nonPluralId: "cut_andesite_bricks" -> "cut_andesite_brick"
    return (block[:-1] if block.endswith('s') else block) + '_' + partial


def entries(stone):
    """(id, kind, pattern block, pattern) in registration order."""
    result = []
    if stone in CREATE_STONES:
        result.append((stone, 'base', stone, None))
    for pattern in PATTERNS:
        block = pattern_name(pattern[0], pattern[1], stone)
        result.append((block, 'block', block, pattern))
        if pattern[3]:
            result.extend((partial_name(block, p), p, block, pattern) for p in PARTIALS)
    return result


STONE_PALETTES = {stone: [entry[0] for entry in entries(stone)] for stone in STONES}
PALETTE_NAMES = [name for names in STONE_PALETTES.values() for name in names]
WALLS = [e[0] for s in STONES for e in entries(s) if e[1] == 'wall']
STAIRS = [e[0] for s in STONES for e in entries(s) if e[1] == 'stairs']
SLABS = [e[0] for s in STONES for e in entries(s) if e[1] == 'slab']


# Fallback tile per stone and texture kind. The first three stones keep the
# tiles the port already shipped.
def tile(stone, kind):
    if kind.startswith('natural_'):
        return f'{stone}_{kind}'
    return {
        'base': stone, 'cut': f'cut_{stone}', 'polished': f'polished_cut_{stone}',
        'slab': f'polished_cut_{stone}_slab', 'brick': f'cut_{stone}_bricks',
        'small_brick': f'small_{stone}_bricks', 'layered': f'layered_{stone}',
        'cap': f'{stone}_cap', 'pillar': f'{stone}_pillar',
    }[kind]


def texture(stone, kind):
    return f'create:block/fallback/{tile(stone, kind)}'


def label(name):
    words = name.split('_')
    if words[0] == 'layered' or words[-1] == 'pillar' or len(words) == 1:
        return ' '.join(w.title() for w in words)
    return ' '.join(w.title() for w in words)


# ---- Blockstates (vanilla BlockModelGenerators layouts used by registrate) ----

FACING_Y = {'east': 0, 'south': 90, 'west': 180, 'north': 270}


def _variant(model, x=0, y=0, uvlock=False):
    value = {'model': model}
    if uvlock:
        value['uvlock'] = True
    if x:
        value['x'] = x
    if y:
        value['y'] = y
    return value


def stairs_blockstate(model):
    variants = {}
    for facing in ('east', 'north', 'south', 'west'):
        for half in ('bottom', 'top'):
            for shape in ('inner_left', 'inner_right', 'outer_left', 'outer_right', 'straight'):
                y = FACING_Y[facing]
                if shape != 'straight':
                    if half == 'bottom' and shape.endswith('left'):
                        y += 270
                    elif half == 'top' and shape.endswith('right'):
                        y += 90
                y %= 360
                part = model + ('_inner' if shape.startswith('inner') else '_outer' if shape.startswith('outer') else '')
                variants[f'facing={facing},half={half},shape={shape}'] = _variant(
                    part, 180 if half == 'top' else 0, y, uvlock=bool(y) or half == 'top')
    return {'variants': variants}


def slab_blockstate(model, double):
    return {'variants': {'type=bottom': {'model': model}, 'type=double': {'model': double},
                         'type=top': {'model': model + '_top'}}}


def wall_blockstate(model):
    parts = [{'apply': {'model': model + '_post'}, 'when': {'up': 'true'}}]
    for side, y in (('north', 0), ('east', 90), ('south', 180), ('west', 270)):
        for height, suffix in (('low', '_side'), ('tall', '_side_tall')):
            apply = {'model': model + suffix, 'uvlock': True}
            if y:
                apply['y'] = y
            parts.append({'apply': apply, 'when': {side: height}})
    return {'multipart': parts}


def pillar_blockstate(model):
    return {'variants': {
        'axis=x': {'model': model + '_horizontal', 'x': 90, 'y': 90},
        'axis=y': {'model': model},
        'axis=z': {'model': model + '_horizontal', 'x': 90},
    }}


GUI = {'rotation': [30, 225, 0], 'scale': [.625, .625, .625]}


def generate(write):
    """Write declarations, blockstates and models; return the fallback tiles used."""
    tiles = set()

    def tex(stone, kind):
        tiles.add((stone, kind))
        return texture(stone, kind)

    for stone in STONES:
        template, hardness, resistance, sounds, color = BASE[stone]
        props = {'hardness': hardness, 'explosion_resistance': resistance, 'requires_tool': True,
                 'map_color': color, 'sounds': f'minecraft:{sounds}'}
        for name, kind, block, pattern in entries(stone):
            ns = f'create:block/{name}'
            if kind == 'base':
                decl = template
                if stone in NATURAL_VARIANTS:
                    for index in range(4):
                        write(f'assets/create/models/block/{name}_natural_{index}.json', {
                            'parent': 'minecraft:block/cube_all',
                            'textures': {'all': tex(stone, f'natural_{index}')}})
                    state = {'variants': {'': [{'model': f'{ns}_natural_{i}'} for i in range(4)]}}
                else:
                    write(f'assets/create/models/block/{name}.json', {
                        'parent': 'minecraft:block/cube_all', 'textures': {'all': tex(stone, 'base')}})
                    state = {'variants': {'': {'model': ns}}}
            elif kind == 'block':
                main = pattern[2][0]
                if pattern[0] in ('layered', 'pillar'):
                    # LayeredBlock and ConnectedPillarBlock are RotatedPillarBlocks.
                    decl = 'quartz_pillar'
                    model = {'parent': 'minecraft:block/cube_column',
                             'textures': {'side': tex(stone, main), 'end': tex(stone, 'cap')}}
                    write(f'assets/create/models/block/{name}.json', model)
                    if pattern[0] == 'pillar':
                        write(f'assets/create/models/block/{name}_horizontal.json', {
                            'parent': 'minecraft:block/cube_column_horizontal',
                            'textures': {'side': tex(stone, main), 'end': tex(stone, 'cap')}})
                        state = pillar_blockstate(ns)
                    else:
                        state = {'variants': {'': {'model': ns}}}
                else:
                    decl = template
                    write(f'assets/create/models/block/{name}.json', {
                        'parent': 'minecraft:block/cube_all', 'textures': {'all': tex(stone, main)}})
                    state = {'variants': {'': {'model': ns}}}
            else:
                main = tex(stone, pattern[2][0])
                decl = f'andesite_{kind}'
                if kind == 'stairs':
                    for suffix, parent in (('', 'stairs'), ('_inner', 'inner_stairs'), ('_outer', 'outer_stairs')):
                        write(f'assets/create/models/block/{name}{suffix}.json', {
                            'parent': f'minecraft:block/{parent}',
                            'textures': {'bottom': main, 'side': main, 'top': main}})
                    state = stairs_blockstate(ns)
                elif kind == 'slab':
                    side = tex(stone, 'slab') if pattern[4] else main
                    for suffix, parent in (('', 'slab'), ('_top', 'slab_top')):
                        write(f'assets/create/models/block/{name}{suffix}.json', {
                            'parent': f'minecraft:block/{parent}',
                            'textures': {'bottom': main, 'side': side, 'top': main}})
                    if pattern[4]:
                        double = ns + '_double'
                        write(f'assets/create/models/block/{name}_double.json', {
                            'parent': 'minecraft:block/cube_column',
                            'textures': {'end': main, 'side': side}})
                    else:
                        double = f'create:block/{block}'
                    state = slab_blockstate(ns, double)
                else:
                    # RegistrateBlockstateProvider.wallBlock names the models after the
                    # pattern block ("cut_andesite_bricks_wall_post"), not the partial id.
                    wall = f'{block}_wall'
                    for suffix, parent in (('_post', 'template_wall_post'), ('_side', 'template_wall_side'),
                                           ('_side_tall', 'template_wall_side_tall')):
                        write(f'assets/create/models/block/{wall}{suffix}.json', {
                            'parent': f'minecraft:block/{parent}', 'textures': {'wall': main}})
                    state = wall_blockstate(f'create:block/{wall}')
            write(f'data/create/horizon/block/{name}.json', {
                'template': f'minecraft:{decl}', 'item': True, 'properties': dict(props)})
            write(f'assets/create/blockstates/{name}.json', state)
            if kind == 'wall':
                item = {'parent': 'minecraft:block/wall_inventory',
                        'textures': {'wall': main}, 'display': {'gui': dict(GUI)}}
            elif kind == 'base' and stone in NATURAL_VARIANTS:
                item = {'parent': f'{ns}_natural_1'}
            else:
                item = {'parent': ns}
            write(f'assets/create/models/item/{name}.json', item)
            write(f'assets/create/items/{name}.json', {
                'model': {'type': 'minecraft:model', 'model': f'create:item/{name}'}})
    # Vanilla tags that give the partials their vanilla behaviour (walls connect
    # through #minecraft:walls) and item grouping.
    for tag, names in (('walls', WALLS), ('stairs', STAIRS), ('slabs', SLABS)):
        for kind in ('block', 'item'):
            write(f'data/minecraft/tags/{kind}/{tag}.json', {'values': [f'create:{n}' for n in names]})
    return tiles


# ---- Procedural fallback tiles (independent art, MIT) ----

# Base colour per stone, approximating each stone's overall tone.
COLORS = {
    'granite': (149, 103, 85), 'diorite': (188, 188, 186), 'andesite': (136, 137, 136),
    'calcite': (222, 222, 216), 'dripstone': (134, 107, 92), 'deepslate': (80, 80, 86),
    'tuff': (108, 109, 102), 'asurine': (86, 118, 180), 'crimsite': (164, 62, 64),
    'limestone': (200, 194, 168), 'ochrum': (196, 152, 76), 'scoria': (110, 76, 60),
    'scorchia': (62, 60, 58), 'veridium': (66, 122, 100),
}


def _shade(color, amount):
    return tuple(max(0, min(255, int(c * amount))) for c in color)


def draw(stone, kind):
    rng = random.Random(f'{stone}:{kind}')
    base = COLORS[stone]
    px = [[None] * 16 for _ in range(16)]

    def noise(x, y, spread=0.07):
        px[y][x] = _shade(base, 1 + rng.uniform(-spread, spread))

    for y in range(16):
        for x in range(16):
            noise(x, y, 0.12 if kind == 'base' or kind.startswith('natural_') else 0.05 if kind in ('polished', 'slab') else 0.08)
    dark, light = _shade(base, 0.68), _shade(base, 1.16)
    if kind in ('cut', 'polished', 'slab', 'cap'):
        for i in range(16):
            px[0][i] = px[i][0] = light
            px[15][i] = px[i][15] = dark
        if kind == 'slab':
            for i in range(16):
                px[7][i], px[8][i] = dark, light
        if kind == 'cap':
            for i in range(3, 13):
                px[3][i] = px[i][3] = dark
                px[12][i] = px[i][12] = light
    elif kind in ('brick', 'small_brick'):
        height = 8 if kind == 'brick' else 4
        width = 16 if kind == 'brick' else 8
        for y in range(16):
            row = y // height
            offset = (width // 2) * (row % 2)
            for x in range(16):
                if y % height == height - 1 or (x + offset) % width == width - 1:
                    px[y][x] = dark
                elif y % height == 0 or (x + offset) % width == 0:
                    px[y][x] = light
    elif kind == 'layered':
        for y in range(16):
            band = 0.9 if (y // 4) % 2 else 1.05
            for x in range(16):
                px[y][x] = _shade(px[y][x], band)
            if y % 4 == 3:
                px[y] = [dark] * 16
    elif kind == 'pillar':
        for y in range(16):
            for x in range(16):
                if x in (0, 15):
                    px[y][x] = dark if x == 15 else light
                elif x % 4 == 2:
                    px[y][x] = _shade(px[y][x], 0.82)
                elif x % 4 == 1:
                    px[y][x] = _shade(px[y][x], 1.08)
    return px


def png(px):
    raw = b''.join(b'\0' + bytes(c for p in row for c in p) for row in px)

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    header = struct.pack('>IIBBBBB', 16, 16, 8, 2, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(raw, 9))
            + chunk(b'IEND', b''))


def write_tiles(content: Path, tiles):
    folder = content / 'assets/create/textures/block/fallback'
    folder.mkdir(parents=True, exist_ok=True)
    for stone, kind in sorted(tiles):
        path = folder / f'{tile(stone, kind)}.png'
        if not path.exists():
            path.write_bytes(png(draw(stone, kind)))
