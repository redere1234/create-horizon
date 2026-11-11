#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare analog chain gearshift neighbour events and ordinary BE ticks."""
import argparse
import errno
import json
from pathlib import Path
import shutil
import tempfile

from bearing_native_checks import Batch
from burner_heat_java_checks import number
from chain_drive_checks import Original, xyz
from common import PINS, ROOT
from native_check_session import NativeCheckSession
from reference_java import BASE, CREATE_SHA256


Y = 160
BOUNDARY = 1952
STARTS = [(BOUNDARY - 1, Y, z) for z in (806, 838)]
CENTER = (BOUNDARY, Y + 1, 821)
RANGE = '1936 784 1967 847'
CLEAR = 'fill 1947 159 787 1955 164 841 minecraft:air'
BLOCK = 'create:adjustable_chain_gearshift'
PRE_RESTART = [('on', 0, 15, 3), ('weaker', 15, 7, 3), ('stronger', 7, 11, 3),
               ('off', 11, 0, 3), ('pulse_on', 0, 15, 0), ('pulse_off', 15, 0, 3),
               ('parked', 0, 11, 4)]
POST_RESTART = [('reloaded', 11, 11, 2), ('reloaded_off', 11, 0, 3)]


def rigs():
    for x, y, z in STARTS:
        yield [(x, y, z), (x, y, z + 1), (x + 1, y, z), (x + 1, y, z + 1)]


POINTS = [p for lane in rigs() for p in lane]


def setup(command, put):
    command(CLEAR)
    command('fill 1947 159 787 1955 159 841 minecraft:smooth_stone')
    for adjustable_drives, (gear, drive, first, second) in zip((True, False), rigs(), strict=True):
        put(gear, f'{BLOCK}[axis=x]')
        put(drive, 'create:encased_chain_drive[axis=x]')
        for shaft in (first, second):
            put(shaft, 'create:shaft[axis=x]')
        x, y, z = gear
        command(f'fill {x} {y} {z - 16} {x} {y} {z - 1} minecraft:redstone_wire')
        put((x - 1, y, z + int(not adjustable_drives)), 'create:creative_motor[facing=east]{ScrollValue:32}')


def transition(put, before, after):
    if before == after:
        return
    for x, y, z in STARTS:
        for strength, block in ((before, 'minecraft:redstone_wire'), (after, 'minecraft:redstone_block')):
            if strength:
                put((x, y, z - 1 if strength == 15 else z - 17 + strength), block)


def row(name, tick, powered, raw):
    values = []
    for n, flag in enumerate(powered):
        slots = raw[n * 4:(n + 1) * 4]
        values.append(dict(powered=flag, signal=number({'nbt': slots[0]}, 'Signal', 0),
                           rpm=[number({'nbt': tag}, 'Speed', 0) for tag in slots]))
    return dict(phase=name, tick=tick, lanes=values)


def java_run(work):
    host = Original()
    assert json.loads((BASE / 'manifest.json').read_text())['create_sha256'] == CREATE_SHA256
    state = host.call('state', {})
    assert state['ready'] and state['data_version'] == 3955, state
    host.call('tick', {'frozen': True})
    rows = []

    def put(pos, block):
        host.command(f'setblock {xyz(pos)} {block}')

    def sample(name, tick, blocks):
        assert all(blocks[i]['id'] == BLOCK for i in (0, 4)), blocks
        flags = [blocks[i]['properties']['powered'] == 'true' for i in (0, 4)]
        rows.append(row(name, tick, flags, [block['nbt'] for block in blocks]))

    try:
        host.command('forceload add ' + RANGE)
        host.call('observe_ticks', {'positions': [list(map(int, state['position']))], 'ticks': 40})
        setup(host.command, put)
        host.call('observe_ticks', {'positions': POINTS, 'ticks': 12})
        for name, before, after, ticks in PRE_RESTART + POST_RESTART:
            transition(put, before, after)
            sample(name, 0, [host.call('block', {'pos': pos}) for pos in POINTS])
            if ticks:
                observations = host.call('observe_ticks', {'positions': POINTS, 'ticks': ticks})
                for observation in observations['samples']:
                    sample(name, observation['tick'], observation['blocks'])
        return rows
    finally:
        host.command(CLEAR)
        host.command('forceload remove ' + RANGE)
        host.call('tick', {'frozen': state['server']['frozen']})
        (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')


def native_run(session):
    rows = []
    for label, phases in [('before-restart', PRE_RESTART), ('after-restart', POST_RESTART)]:
        batch = Batch()
        batch.load(CENTER)
        for pos in POINTS:
            batch.command(f'execute if loaded {xyz(pos)} run say adjustable_loaded', True)
        if label == 'before-restart':
            setup(batch.command, batch.put)
            batch.tick(12)
        pending = []
        for name, before, after, ticks in phases:
            transition(batch.put, before, after)
            for tick in range(ticks + 1):
                if tick:
                    batch.tick()
                for pos in STARTS:
                    batch.command(f'execute if block {xyz(pos)} {BLOCK}[powered=true] run say adjustable_powered', True)
                for pos in POINTS:
                    batch.data(pos)
                pending.append((name, tick))
        observations = batch.run(session, label)
        assert all('adjustable_loaded' in line for line in observations[:len(POINTS)]), observations[:len(POINTS)]
        data = iter(observations[len(POINTS):])
        for name, tick in pending:
            flags = ['adjustable_powered' in next(data) for _ in STARTS]
            raw = [next(data) for _ in POINTS]
            assert all('create:' in tag and 'Speed:' in tag for tag in raw), raw
            rows.append(row(name, tick, flags, raw))
        assert next(data, None) is None
    return rows


def compare(native, java):
    differences = []
    for got, want in zip(native, java, strict=True):
        assert (got['phase'], got['tick']) == (want['phase'], want['tick']), (got, want)
        for lane, (a, b) in enumerate(zip(got['lanes'], want['lanes'], strict=True)):
            if (a['powered'], a['signal']) != (b['powered'], b['signal']) or any(
                    abs(x - y) > 1e-5 for x, y in zip(a['rpm'], b['rpm'], strict=True)):
                differences.append(dict(phase=got['phase'], tick=got['tick'], lane=lane, native=a, java=b))
    return differences


def verify_reference(rows):
    previous_signal = 0
    observed = iter(rows)
    for name, _, strength, ticks in PRE_RESTART + POST_RESTART:
        for tick in range(ticks + 1):
            sample = next(observed)
            assert (sample['phase'], sample['tick']) == (name, tick), sample
            signal = strength if tick else previous_signal
            modifier = 1 + (signal + 1) / 16 if signal else 1
            speeds = [(32, 32 * modifier), (32 / modifier, 32)]
            for lane, rpm in zip(sample['lanes'], speeds, strict=True):
                assert lane['powered'] == (strength > 0) and lane['signal'] == signal, sample
                assert all(abs(a - b) <= 1e-5 for a, b in zip(lane['rpm'], rpm * 2, strict=True)), sample
        if ticks:
            previous_signal = strength
    assert next(observed, None) is None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for flag in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + flag, type=Path)
    args = parser.parse_args()
    result = dict(create=PINS['create_revision'], differences=[])
    if args.java:
        work = Path(tempfile.mkdtemp(prefix='adjustable-transition-java-', dir=ROOT / '.local'))
        result['rows'] = java_run(work)
        verify_reference(result['rows'])
    else:
        if not all((args.game, args.resources, args.ctl, args.reference)):
            parser.error('Horizon runs require --game, --resources, --ctl and --reference')
        reference = json.loads(args.reference.read_text())
        assert reference['passed'] and reference['create'] == result['create']
        verify_reference(reference['rows'])
        session = NativeCheckSession(args.game, args.resources, args.ctl, None,
                                     name='adjustable-transition-native', graphics=False, world='CreateAnalogTransition')
        work = session.scratch
        try:
            result['rows'] = native_run(session)
        finally:
            session.control_temp.cleanup()
            for path in (session.resources, work / '.horizon-cache'):
                if not path.is_dir():
                    continue
                try:
                    shutil.rmtree(path)
                except OSError as error:
                    if error.errno != errno.ENOTEMPTY:
                        raise
                    shutil.rmtree(path)
        result['differences'] = compare(result['rows'], reference['rows'])
    result['passed'] = not result['differences']
    path = work / 'result.json'
    path.write_text(json.dumps(result, indent=2) + '\n')
    print(path, flush=True)
    assert result['passed'], result['differences']


if __name__ == '__main__':
    main()
