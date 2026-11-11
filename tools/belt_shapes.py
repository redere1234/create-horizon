"""MIT BeltShapes.java geometry, south-facing before Catnip quarter turns.

Coordinates below are original voxel units; content uses block units.
"""
from itertools import product


def clip(boxes, low, high):
    result = []
    for b in boxes:
        c = [max(b[i], low[i]) for i in range(3)] + [min(b[i + 3], high[i]) for i in range(3)]
        if all(c[i] < c[i + 3] for i in range(3)):
            result.append(c)
    return result


def transform(boxes, facing, vertical=False):
    # VerticalBeltShaper: -90deg X, then sign-dependent X and -toYRot Y.
    turns = {'south': 0, 'west': 1, 'north': 2, 'east': 3}[facing]
    def point(x, y, z):
        x, y, z = x - 8, y - 8, z - 8
        if vertical:
            y, z = z, -y
            if facing in ('north', 'west'):
                y, z = -y, -z
        for _ in range(turns):
            x, z = -z, x
        return x + 8, y + 8, z + 8
    result = []
    for b in boxes:
        points = [point(*p) for p in product(*[(b[i], b[i + 3]) for i in range(3)])]
        result.append([min(p[i] for p in points) / 16 for i in range(3)] +
                      [max(p[i] for p in points) / 16 for i in range(3)])
    return result


def geometry():
    full = [[1, 3, 0, 15, 13, 16]]
    ending = [[1, 4, 0, 15, 12, 16], [1, 3, 1, 15, 13, 15]]
    side = [[3, 1, 0, 13, 15, 16]]
    side_end = [[4, 1, 0, 12, 15, 16], [3, 1, 1, 13, 15, 15]]
    opposite = {'north': 'south', 'south': 'north', 'east': 'west', 'west': 'east'}
    shapes, collisions = {}, {}
    for face, slope, part in product(('north', 'south', 'west', 'east'),
                                     ('horizontal', 'upward', 'downward', 'vertical', 'sideways'),
                                     ('start', 'middle', 'end', 'pulley')):
        base, end = (side, side_end) if slope == 'sideways' else (full, ending)
        if slope in ('upward', 'downward'):
            base = [[1, (10 - i if slope == 'upward' else i - 5), 15 - i,
                     15, (21 - i if slope == 'upward' else i + 6), 16 - i] for i in range(16)]
        if part in ('middle', 'pulley'):
            boxes = base
        else:
            south, north = (end, base) if part == 'end' else (base, end)
            boxes = clip(south, [0, -5, 8], [16, 21, 16]) + clip(north, [0, -5, 0], [16, 21, 8])
        boxes = transform(boxes, face, slope == 'vertical')
        if slope == 'horizontal' or (slope, part) in (('upward', 'start'), ('downward', 'end')):
            casing = [[0, 0, 0, 1, 11 / 16, 1]]
        elif slope in ('upward', 'downward'):
            casing = transform([[0, 0, 5, 16, 11, 16]], face if slope == 'upward' else opposite[face])
        else:
            casing = []
        # Each declared native shape holds at most sixteen boxes. The
        # diagonal casing already contains one entire step of the belt.
        cased_boxes = [box for box in boxes if not any(
            all(shell[i] <= box[i] and shell[i + 3] >= box[i + 3] for i in range(3))
            for shell in casing)] + casing
        for cased, outline in (('false', boxes), ('true', cased_boxes)):
            key = ','.join((face, slope, part, cased))
            shapes[key] = outline
            collisions[key] = clip(outline, [0, 0, 0], [1, 19 / 16, 1])
    properties = ['facing', 'slope', 'part', 'casing']
    return ({'properties': properties, 'values': shapes},
            {'properties': properties, 'values': collisions})
