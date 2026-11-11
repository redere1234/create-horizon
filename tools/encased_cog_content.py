# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Fallback models and state definitions for Create's four Encased Cogwheels."""

from itertools import product


ENGLISH = {
    'andesite_encased_cogwheel': 'Andesite Encased Cogwheel',
    'andesite_encased_large_cogwheel': 'Andesite Encased Large Cogwheel',
    'brass_encased_cogwheel': 'Brass Encased Cogwheel',
    'brass_encased_large_cogwheel': 'Brass Encased Large Cogwheel',
}
RUSSIAN = {
    'andesite_encased_cogwheel': 'Шестерня в андезитовом корпусе',
    'andesite_encased_large_cogwheel': 'Большая шестерня в андезитовом корпусе',
    'brass_encased_cogwheel': 'Шестерня в латунном корпусе',
    'brass_encased_large_cogwheel': 'Большая шестерня в латунном корпусе',
}
BLOCKS = list(ENGLISH)


def encased_cogs(write, model):
    rotations = {'x': {'x': 90, 'y': 90}, 'y': {}, 'z': {'x': 90, 'y': 180}}
    axis = {'type': 'enum', 'values': list(rotations)}
    end = {'type': 'boolean'}
    full = {'default': [[0, 0, 0, 1, 1, 1]]}
    values = ('false', 'true')

    def plate(opening, low, high):
        if not opening:
            return [([0, low, 0], [16, high, 16])]
        return [
            ([0, low, 0], [6, high, 16]), ([10, low, 0], [16, high, 16]),
            ([6, low, 0], [10, high, 6]), ([6, low, 10], [10, high, 16]),
        ]

    for name in BLOCKS:
        brass = name.startswith('brass_')
        texture = 'minecraft:block/raw_gold_block' if brass else 'minecraft:block/polished_andesite'
        write(f'data/create/horizon/block/{name}.json', {
            'template': 'minecraft:andesite',
            'item': True,
            'properties': {
                'map_color': 48 if brass else 34,
                'occludes': False,
            },
            'state_properties': {'axis': axis, 'top_shaft': end, 'bottom_shaft': end},
            'default_state': {'axis': 'y', 'top_shaft': 'false', 'bottom_shaft': 'false'},
            'shapes': full,
            'collision_shapes': full,
        })
        variants = {}
        for (bottom, top) in product(values, repeat=2):
            suffix = ('_top' if top == 'true' else '') + ('_bottom' if bottom == 'true' else '')
            part = name + suffix
            # Our fallback casing leaves the spinning wheel visible in the
            # middle. The original geometry is supplied by the local JAR.
            model(part, plate(bottom == 'true', 0, 5) + plate(top == 'true', 11, 16), texture)
            for axis_name, rotation in rotations.items():
                variants[f'axis={axis_name},bottom_shaft={bottom},top_shaft={top}'] = {
                    'model': f'create:block/{part}', **rotation,
                }
        write(f'assets/create/blockstates/{name}.json', {'variants': variants})
        write(f'assets/create/models/item/{name}.json', {'parent': f'create:block/{name}'})
        write(f'assets/create/items/{name}.json', {
            'model': {'type': 'minecraft:model', 'model': f'create:item/{name}'},
        })
