#!/usr/bin/env python3
"""Observe a belt being rebuilt before the old chain's next maintenance tick."""
import argparse
import json
from pathlib import Path
import subprocess

from chain_drive_checks import xyz
from native_check_session import NativeCheckSession


def run(game, resources, ctl):
    session = NativeCheckSession(game, resources, ctl, None,
                                 name='belt-replacement', graphics=False)
    script = session.scratch / 'commands.jsonl'
    output = session.scratch / 'observations.jsonl'
    operations = []

    def cmd(text, record=False):
        operations.append({'op': 'cmd', 'cmd': text, 'record': record})

    def tick(count):
        operations.append({'op': 'tick', 'n': count})

    def place(origin, rise):
        x, y, z = origin
        slope = 'upward' if rise else 'horizontal'
        positions = [(x + i, y + i * rise, z) for i in range(3)]
        for pos, part in zip(positions, ('start', 'middle', 'end'), strict=True):
            cmd(f'setblock {xyz(pos)} create:belt[facing=east,slope={slope},part={part}]')
        return positions

    def seed(origin, item, count):
        cmd(f'data merge block {xyz(origin)} {{Inventory:{{Items:[{{'
            f'Item:{{id:"minecraft:{item}",count:{count}}},Pos:1.5f,PrevPos:1.5f,'
            'Offset:0.0f,PrevOffset:0.0f,InSegment:1,InDirection:1,Angle:180}]}}')

    cmd('gamemode creative')
    cmd('tp @s 4.5 82 5.5')
    operations.append({'op': 'settle'})
    cmd('fill -2 80 -2 12 90 9 minecraft:air')
    cmd('fill -2 79 -2 12 79 9 minecraft:smooth_stone')
    cmd('kill @e[type=minecraft:item]')
    copper = 'type=minecraft:item,nbt={Item:{id:"minecraft:copper_ingot"}}'
    cases = [((0, 80, 0), 1), ((6, 80, 6), 0)]
    for origin, rise in cases:
        old = place(origin, 0)
        tick(8)
        seed(origin, 'copper_ingot', 7)
        tick(3)
        cmd(f'data get block {xyz(origin)} Inventory', True)
        # Ordinary commands run consecutively before the next real tick. In
        # the slope case the old far pulley stays for teardown. In the second
        # case every block is recreated with the same block state and position.
        for pos in (old[:2] if rise else old):
            cmd(f'setblock {xyz(pos)} minecraft:air')
        new = place(origin, rise)
        seed(origin, 'gold_ingot', 3)
        tick(12)
        for pos in new:
            cmd(f'execute if block {xyz(pos)} create:belt run say replacement_belt_present', True)
        if rise:
            cmd(f'execute if block {xyz(old[-1])} create:shaft run say old_pulley_restored', True)
        cmd(f'data get block {xyz(origin)} Inventory', True)
        cmd(f'execute if entity @e[{copper}]', True)
        cmd(f'data get entity @e[{copper},limit=1] Item', True)
        cmd(f'kill @e[{copper}]')
    cmd('save-all flush')
    script.write_text(''.join(json.dumps(op) + '\n' for op in operations))
    session.env.update(HORIZON_COMMAND_SCRIPT=str(script), HORIZON_COMMAND_OUTPUT=str(output),
                       HORIZON_API_DISCOVERY='http://127.0.0.1:9/')
    print(session.scratch, flush=True)
    with session.log.open('w') as log:
        subprocess.run([str(session.game), '--headless', '--resources', str(session.resources),
                        '--world', 'CreateBeltReplacement', '--seed', '5', '--creative'],
                       cwd=session.scratch, env=session.env, stdout=log, stderr=subprocess.STDOUT,
                       check=True, timeout=180)
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    messages = [' '.join(''.join(span[0] for span in message) for message in row['messages'])
                for row in rows]
    assert len(messages) == 15, messages
    index = 0
    for origin, rise in cases:
        count = 7 + bool(rise)
        case = messages[index:index + count]
        assert 'copper_ingot' in case[0] and 'count: 7' in case[0], case
        assert all('replacement_belt_present' in row for row in case[1:4]), case
        if rise:
            assert 'old_pulley_restored' in case[4], case
        assert 'gold_ingot' in case[-3] and 'count: 3' in case[-3], case
        assert 'copper_ingot' not in case[-3], case
        assert 'copper_ingot' in case[-1] and 'count: 7' in case[-1], case
        assert rows[index + count - 2]['results'] == [[True, 1]], case
        index += count
    report = {'passed': True, 'checks': messages}
    (session.scratch / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('game', 'resources', 'ctl'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.game, args.resources, args.ctl)


if __name__ == '__main__':
    main()
