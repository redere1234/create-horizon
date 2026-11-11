#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Exercise the real Horizon server's Mechanical Bearing and chunk save path."""
import argparse
import json
import os
from pathlib import Path
import subprocess

from bearing_reference_checks import (
    PAYLOAD_ANCHOR, PAYLOAD_MOTOR, PAYLOAD_PIVOT, PAYLOAD_RIM, offset, put_payload,
)
from burner_heat_java_checks import number
from chain_drive_checks import xyz
from common import PINS
from native_check_session import NativeCheckSession


CASES = (
    ('east', (1, 0, 0), 'z', (0, 0, 1), 'y', (0, -1, 0)),
    ('up', (0, 1, 0), 'z', (0, 0, 1), 'x', (1, 0, 0)),
    ('south', (0, 0, 1), 'x', (1, 0, 0), 'y', (0, 1, 0)),
)


class Batch:
    def __init__(self):
        self.ops = []

    def command(self, value, record=False):
        self.ops.append(dict(op='cmd', cmd=value, record=record))

    def load(self, pos):
        self.command(f'tp @s {pos[0]}.5 {pos[1] + 1} {pos[2]}.5')
        self.ops.append(dict(op='settle'))

    def tick(self, n=1):
        self.ops.append(dict(op='tick', n=n))

    def put(self, pos, block):
        self.command(f'setblock {xyz(pos)} {block}')

    def data(self, pos):
        self.command(f'data get block {xyz(pos)}', True)

    def expect(self, pos, block):
        self.command(f'execute if block {xyz(pos)} {block} run say bearing_check', True)

    def run(self, session, label):
        self.command('save-all flush')
        script = session.scratch / (label + '.jsonl')
        output = session.scratch / (label + '-observations.jsonl')
        script.write_text(''.join(json.dumps(op) + '\n' for op in self.ops))
        env = session.env | dict(HORIZON_COMMAND_SCRIPT=str(script), HORIZON_COMMAND_OUTPUT=str(output),
                                 HORIZON_API_DISCOVERY='http://127.0.0.1:9/')
        with session.log.open('a+') as log:
            log.seek(0, os.SEEK_END)
            start = log.tell()
            subprocess.run([str(session.game), '--headless', '--resources', str(session.resources),
                            '--world', session.world, '--seed', '5', '--creative', '--render-distance', '4',
                            '--name', 'BearingReview'], cwd=session.scratch, env=env, stdout=log,
                           stderr=subprocess.STDOUT, check=True, timeout=240)
            log.seek(start)
            for line in log:
                if 'bundled content could not be loaded' in line or 'Horizon: content mods not loaded:' in line:
                    raise AssertionError(line.strip())
        return [' '.join(''.join(span[0] for span in message) for message in json.loads(line)['messages'])
                for line in output.read_text().splitlines()]


def rig(batch, pivot, case, rpm=32):
    facing, axis, log_axis, radial, final_axis, target = case
    anchor = offset(pivot, axis)
    motor = offset(pivot, axis, -1)
    log = offset(anchor, radial)
    landing = offset(anchor, target)
    batch.put(pivot, f'create:mechanical_bearing[facing={facing}]')
    batch.put(anchor, 'minecraft:slime_block')
    batch.put(log, f'minecraft:oak_log[axis={log_axis}]')
    batch.put(motor, f'create:creative_motor[facing={facing}]{{ScrollValue:{rpm}}}')
    return motor, anchor, log, landing, final_axis


def test(session, reference):
    batch = Batch()
    batch.load((911, 100, 50))
    batch.command('fill 897 95 42 925 108 63 minecraft:air')
    for index, case in enumerate(CASES):
        pivot = (903 + 7 * index, 100, 50)
        motor, anchor, log, target, final_axis = rig(batch, pivot, case)
        for _ in range(10):
            batch.tick()
            batch.data(pivot)
        batch.expect(anchor, 'minecraft:air')
        batch.expect(log, 'minecraft:air')
        batch.put(motor, 'minecraft:air')
        batch.tick()
        batch.data(pivot)
        batch.expect(anchor, 'minecraft:slime_block')
        batch.expect(log, 'minecraft:air')
        batch.expect(target, f'minecraft:oak_log[axis={final_axis}]')
    rows = batch.run(session, 'axes')
    for i, case in enumerate(reference['cases']):
        window = rows[i * 16:(i + 1) * 16]
        java = [number(sample['blocks'][0], 'Angle') for sample in case['trace']]
        native = [number({'nbt': text}, 'Angle', 0) for text in window[:10]]
        assert native == java, (case['facing'], native, java, window)
        assert all('bearing_check' in row for row in window[10:12] + window[13:]), window
        assert number({'nbt': window[12]}, 'Running') == 0, window

    pivot = (904, 100, 58)
    batch = Batch()
    batch.load(pivot)
    motor, anchor, log, _, _ = rig(batch, pivot, CASES[1], rpm=8)
    batch.tick(10)
    batch.data(pivot)
    batch.expect(anchor, 'minecraft:air')
    rows = batch.run(session, 'before-restart')
    angle = number({'nbt': rows[0]}, 'Angle')
    assert 0 < angle < 180 and 'bearing_check' in rows[1], rows

    batch = Batch()
    batch.load(pivot)
    batch.tick(5)
    batch.data(pivot)
    batch.expect(anchor, 'minecraft:air')
    batch.expect(log, 'minecraft:air')
    batch.put(anchor, 'minecraft:obsidian')
    batch.put(pivot, 'minecraft:air')
    batch.tick(3)
    batch.expect(anchor, 'minecraft:obsidian')
    for side in ((1, 0, 0), (0, 0, -1), (-1, 0, 0), (0, 0, 1)):
        batch.expect(offset(anchor, side), 'minecraft:air')
    rows = batch.run(session, 'restart-and-remove')
    assert number({'nbt': rows[0]}, 'Running') == 1, rows
    assert number({'nbt': rows[0]}, 'Angle') != angle, rows
    assert all('bearing_check' in row for row in rows[1:]), rows

    batch = Batch()
    batch.load(pivot)
    batch.expect(pivot, 'minecraft:air')
    batch.expect(anchor, 'minecraft:obsidian')
    batch.put(anchor, 'minecraft:air')
    batch.tick(3)
    batch.expect(anchor, 'minecraft:slime_block')
    # Exactly one copy among the four possible snapped positions.
    for side in ((1, 0, 0), (0, 0, -1), (-1, 0, 0), (0, 0, 1)):
        batch.expect(offset(anchor, side), 'minecraft:oak_log')
    rows = batch.run(session, 'restore-orphan')
    assert all('bearing_check' in row for row in rows[:3]), rows
    assert sum('bearing_check' in row for row in rows[3:]) == 1, rows


def test_honey(session):
    batch = Batch()
    pivot = (904, 100, 88)
    batch.load(pivot)
    batch.command('fill 900 96 84 909 106 92 minecraft:air')
    batch.put(pivot, 'create:mechanical_bearing[facing=up]')
    batch.put((904, 101, 88), 'minecraft:honey_block')
    batch.put((905, 101, 88), 'minecraft:birch_log[axis=x]')
    batch.put((903, 101, 88), 'minecraft:slime_block')
    motor = (904, 99, 88)
    batch.put(motor, 'create:creative_motor[facing=up]{ScrollValue:32}')
    batch.tick(10)
    batch.data(pivot)
    batch.expect((904, 101, 88), 'minecraft:air')
    batch.expect((905, 101, 88), 'minecraft:air')
    batch.expect((903, 101, 88), 'minecraft:slime_block')
    batch.put(motor, 'minecraft:air')
    batch.tick()
    batch.expect((904, 101, 88), 'minecraft:honey_block')
    batch.expect((904, 101, 87), 'minecraft:birch_log[axis=z]')
    batch.expect((903, 101, 88), 'minecraft:slime_block')
    rows = batch.run(session, 'honey')
    assert number({'nbt': rows[0]}, 'Running') == 1 and all(
        row == '[BearingReview] bearing_check' for row in rows[1:]), rows


def test_payload(session, reference):
    positions = (PAYLOAD_ANCHOR, *PAYLOAD_RIM)
    batch = Batch()
    batch.load(PAYLOAD_PIVOT)
    batch.command('fill 900 96 69 909 106 75 minecraft:air')
    put_payload(batch.put)
    batch.tick(10)
    batch.data(PAYLOAD_PIVOT)
    for pos in positions:
        batch.expect(pos, 'minecraft:air')
    observed = batch.run(session, 'colored-payload-moving')
    assert number({'nbt': observed[0]}, 'Running') == 1, observed
    assert number({'nbt': observed[0]}, 'Angle') == reference['angle'], observed
    assert all('bearing_check' in row for row in observed[1:]), observed

    batch = Batch()
    batch.load(PAYLOAD_PIVOT)
    for pos in positions:
        batch.expect(pos, 'minecraft:air')
    batch.put(PAYLOAD_MOTOR, 'minecraft:air')
    batch.tick()
    batch.data(PAYLOAD_PIVOT)
    for pos, block in zip(positions, reference['landed'], strict=True):
        batch.expect(pos, block)
    observed = batch.run(session, 'colored-payload-restart')
    assert all('bearing_check' in row for row in observed[:5] + observed[6:]), observed
    assert number({'nbt': observed[5]}, 'Running') == 0, observed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + flag, type=Path, required=True)
    parser.add_argument('--create-jar', type=Path)
    args = parser.parse_args()
    reference = json.loads(args.reference.read_text())
    assert reference['passed'] and reference['create'] == PINS['create_revision']
    session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                 name='bearing-native', graphics=False, world='CreateBearingChecks')
    print(session.scratch, flush=True)
    try:
        test(session, reference)
        test_honey(session)
        if 'payload' in reference:
            test_payload(session, reference['payload'])
    finally:
        session.control_temp.cleanup()
    print(json.dumps(dict(passed=True, world=str(session.scratch))))


if __name__ == '__main__':
    main()
