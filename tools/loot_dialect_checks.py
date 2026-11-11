#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Check the normal block-drop path for migrated Create loot conditions."""
import argparse
import json
from pathlib import Path

from bearing_native_checks import Batch
from burner_heat_java_checks import number
from chain_drive_checks import xyz
from native_check_session import NativeCheckSession


CASES = (
    ('encased_chain_drive[axis=y]', 'encased_chain_drive'),
    ('gearbox[axis=y]', 'gearbox'),
    ('gearbox[axis=x]', 'vertical_gearbox'),
    ('red_sail[facing=north]', 'white_sail'),
    ('mechanical_saw[facing=up]', 'mechanical_saw'),
    ('deployer[facing=down]', 'deployer'),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'resources', 'ctl'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                 name='loot-dialect', graphics=False, world='CreateLootDialect')
    batch = Batch()
    batch.load((1014, 99, 55))
    batch.command('fill 997 99 53 1021 102 57 minecraft:air')
    batch.command('fill 997 98 53 1021 98 57 minecraft:stone')
    for i, (block, item) in enumerate(CASES):
        x, y, z = pos = (999 + 3 * i, 99, 55)
        batch.put(pos, 'create:' + block)
        batch.command(f'setblock {xyz(pos)} minecraft:air destroy')
        selector = (f'@e[type=minecraft:item,x={x+.5},y={y+.5},z={z+.5},'
                    f'distance=..2,nbt={{Item:{{id:"create:{item}"}}}},limit=1]')
        batch.command(f'data get entity {selector} Item', True)
    try:
        rows = batch.run(session, 'loot-dialect')
        for (_, item), raw in zip(CASES, rows, strict=True):
            assert f'create:{item}' in raw and number({'nbt': raw}, 'count') == 1, raw
        path = session.scratch / 'result.json'
        path.write_text(json.dumps(dict(passed=True, cases=rows), indent=2) + '\n')
        print(path)
    finally:
        session.control_temp.cleanup()


if __name__ == '__main__':
    main()
