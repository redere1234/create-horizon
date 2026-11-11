#!/usr/bin/env python3
"""Real enclosed-chain topology checks in isolated original/native worlds.

Six shaft/chain-axis combinations, a perpendicular center shaft, removal and
reconnection use identical commands and ordinary ticks in both games. This is
settled state/speed comparison, not a claim of transient, visual or sound parity.
Original observations are collected with --java before --reference is consumed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import tempfile

from burner_heat_java_checks import number
from common import PINS, ROOT
from native_check_session import NativeCheckSession, wait_loaded
import reference_java as java

BASE = (640, 80, 40)
LETTERS = 'xyz'
FACES = ('east', 'up', 'south')


def offset(pos, axis, amount):
    return tuple(v + (amount if i == axis else 0) for i, v in enumerate(pos))


def xyz(pos):
    return ' '.join(map(str, pos))


class Original:
    def __init__(self):
        self.trace = []

    def call(self, method, body):
        result = java.call(java.BASE, method, body)
        self.trace.append(dict(method=method, body=body, reply=result))
        return result

    def command(self, command):
        return self.call('command', {'command': command})

    def snapshot(self, positions, ticks):
        observed = self.call('observe_ticks', {'ticks': ticks, 'positions': positions})
        blocks = observed['samples'][-1]['blocks']
        return [dict(block=b['id'], properties={k: v.lower() for k, v in b['properties'].items()},
                     speed=number(b, 'Speed', 0), nbt=b.get('nbt', '')) for b in blocks]


class Native:
    def __init__(self, session):
        self.session = session

    def command(self, command):
        return self.session.call('command', command)

    def snapshot(self, positions, ticks):
        self.session.call('wait', ticks)
        result = []
        for pos in positions:
            block = self.session.call('block', *pos)
            raw = ' '.join(self.command('data get block ' + xyz(pos))['chat'])
            result.append(dict(block=block['block'], properties=dict(re.findall(r'(\w+)=(\w+)', block['state'])),
                               speed=number({'nbt': raw}, 'Speed', 0), nbt=raw))
        return result


def scenarios(host, report, save):
    host.command('gamemode creative')
    host.command('forceload add 624 24 655 55')
    host.command('fill 636 76 36 647 76 47 minecraft:smooth_stone')
    for shaft_axis in range(3):
        for chain_axis in range(3):
            if shaft_axis == chain_axis:
                continue
            host.command('fill 636 77 36 647 87 47 minecraft:air')
            chains = [offset(BASE, chain_axis, i) for i in range(3)]
            output = offset(chains[-1], shaft_axis, 1)
            motor = offset(BASE, shaft_axis, -1)
            positions = chains + [output, motor]
            for pos in chains:
                host.command('setblock ' + xyz(pos) + f' create:encased_chain_drive[axis={LETTERS[shaft_axis]}]')
            host.command('setblock ' + xyz(output) + f' create:shaft[axis={LETTERS[shaft_axis]}]')
            host.command('setblock ' + xyz(motor) + f' create:creative_motor[facing={FACES[shaft_axis]}]{{ScrollValue:32}}')
            row = dict(shaft_axis=LETTERS[shaft_axis], chain_axis=LETTERS[chain_axis], positions=positions, phases={})
            report['active'] = row
            row['phases']['straight'] = host.snapshot(positions, 30)
            initial = row['phases']['straight']
            assert [b['properties']['part'] for b in initial[:3]] == ['start', 'middle', 'end'], row
            assert [b['speed'] for b in initial] == [32] * 5, row
            assert all('create:encased_shaft' in b['nbt'] for b in initial[:3]), row
            # Mixed shaft axes are legal: the enclosed chain's connection axis
            # is independent of the exposed shaft, and carries unchanged RPM.
            other_axis = next(a for a in range(3) if a not in (shaft_axis, chain_axis))
            host.command('setblock ' + xyz(chains[1]) + ' minecraft:air')
            host.command('setblock ' + xyz(chains[1]) + f' create:encased_chain_drive[axis={LETTERS[other_axis]}]')
            row['phases']['perpendicular'] = host.snapshot(positions, 16)
            assert [b['speed'] for b in row['phases']['perpendicular']] == [32] * 5, row
            host.command('setblock ' + xyz(chains[1]) + ' minecraft:air')
            row['phases']['removed'] = host.snapshot(positions, 16)
            broken = row['phases']['removed']
            assert broken[0]['properties']['part'] == broken[2]['properties']['part'] == 'none', row
            assert broken[0]['speed'] == 32 and broken[2]['speed'] == broken[3]['speed'] == 0, row
            host.command('setblock ' + xyz(chains[1]) + f' create:encased_chain_drive[axis={LETTERS[other_axis]}]')
            row['phases']['reconnected'] = host.snapshot(positions, 16)
            assert [b['speed'] for b in row['phases']['reconnected']] == [32] * 5, row
            report['cases'].append(row)
            report.pop('active')
            save()


def compare(actual, expected):
    assert len(actual) == len(expected) == 6
    for got, wanted in zip(actual, expected):
        assert (got['shaft_axis'], got['chain_axis']) == (wanted['shaft_axis'], wanted['chain_axis'])
        for phase, blocks in got['phases'].items():
            for index, (a, b) in enumerate(zip(blocks, wanted['phases'][phase])):
                for key in ('block', 'properties', 'speed'):
                    assert a[key] == b[key], (got['shaft_axis'], got['chain_axis'], phase, index, key, a, b)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--java', action='store_true')
    for arg in ['game', 'resources', 'ctl', 'create-jar', 'reference', 'build-result']:
        parser.add_argument('--' + arg, type=Path)
    args = parser.parse_args()
    session = None
    if args.java:
        host = Original()
        work = Path(tempfile.mkdtemp(prefix='chain-drive-java-', dir=ROOT / '.local'))
        state = host.call('state', {})
        assert state['ready'] and state['data_version'] == 3955, state
        host.call('tick', {'frozen': True})
    else:
        assert all(getattr(args, n) for n in ['game', 'resources', 'ctl', 'create_jar', 'reference', 'build_result'])
        build = json.loads(args.build_result.read_text())
        assert build['passed'] and Path(build['game']).resolve() == args.game.resolve()
        assert hashlib.sha256(args.game.read_bytes()).hexdigest() == build['game_sha256']
        session = NativeCheckSession(args.game, args.resources, args.ctl, args.create_jar,
                                     name='chain-drive-native', graphics=False, world='CreateChainDrive07')
        work, host = session.scratch, Native(session)
    report = dict(passed=False, create=PINS['create_revision'], scope=__doc__, cases=[],
                  fixture_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())

    def save():
        (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
        if args.java:
            (work / 'transcript.json').write_text(json.dumps(host.trace, indent=2) + '\n')

    print(json.dumps({'work': str(work)}), flush=True)
    try:
        if session:
            session.start()
            host.command('tp @s 642.5 88 42.5')
            wait_loaded(session.call, [(636, 80, 36), (647, 80, 47)])
            report['game_sha256'] = build['game_sha256']
            report['horizon'] = build['horizon']
            report['build_receipt_sha256'] = hashlib.sha256(args.build_result.read_bytes()).hexdigest()
        scenarios(host, report, save)
        if session:
            expected = json.loads(args.reference.read_text())
            assert expected['passed'] and expected['create'] == report['create']
            compare(report['cases'], expected['cases'])
            report['reference_sha256'] = hashlib.sha256(args.reference.read_bytes()).hexdigest()
            # A true process restart preserves canonical chain states and RPM.
            before = report['cases'][-1]['phases']['reconnected']
            host.command('save-all flush')
            session.restart()
            after = host.snapshot(report['cases'][-1]['positions'], 20)
            for a, b in zip(after, before):
                assert all(a[k] == b[k] for k in ('block', 'properties', 'speed')), (a, b)
            report['restarted'] = after
        report['passed'] = True
    except BaseException as error:
        report['error'] = repr(error)
        raise
    finally:
        if session:
            session.stop()
        else:
            host.call('tick', {'frozen': True})
        save()
        print(json.dumps({'passed': report['passed'], 'cases': len(report['cases']), 'result': str(work / 'result.json')}), flush=True)


if __name__ == '__main__':
    main()
