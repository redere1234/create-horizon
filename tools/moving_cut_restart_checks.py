#!/usr/bin/env python3
# Copyright (c) 2026 create-horizon contributors
# SPDX-License-Identifier: MIT
"""Compare a moving cut against Java after a real Horizon restart."""

import argparse
import json
from pathlib import Path

from actor_native_checks import matched
from bearing_actor_phase_checks import AIR, MOTOR, PIVOT, SCENES, TARGET, motor, setup
from bearing_native_checks import Batch
from burner_heat_java_checks import number
from common import PINS
from native_check_session import NativeCheckSession
from saved_block_checks import read_saved_chunk_tag


SAVE_AT = 24
KEYS = ('horizon:attachments', 'create', 'moving_actor_ticks', 'value')


def current_cut(session):
    attachment = read_saved_chunk_tag(session.scratch, PIVOT, KEYS, session.world)['nbt']
    if not attachment:
        return None
    assert attachment['value']['Version']['value'] == 1, attachment
    groups = attachment['value']['Structures']['value']
    if not groups:
        return None
    [group] = groups
    assert group['value']['Controller']['value'] == list(PIVOT), group
    [actor] = group['value']['Actors']['value']
    cut = actor['value']
    assert cut['BreakingPos']['value'] == list(TARGET), cut
    assert 0 < cut['Progress']['value'] < 10, cut
    assert cut['TicksUntilNextProgress']['value'] >= 0, cut
    return cut


def verify(session, tool, reference):
    block, target = SCENES[tool]
    batch = Batch()
    batch.load(PIVOT)
    setup(batch.command, block, target)
    batch.tick(3)
    batch.put(MOTOR, motor())
    batch.tick(SAVE_AT)
    batch.expect(TARGET, target)
    batch.data(PIVOT)
    still_solid, stopped = batch.run(session, tool + '-before-cold-restart')
    assert matched(still_solid) and abs(number({'nbt': stopped}, 'Angle') - 19.2) < .001, stopped
    saved = current_cut(session)
    assert saved, 'The moving cut had no saved progress'

    batch = Batch()
    batch.load(PIVOT)
    for expected in reference[SAVE_AT:]:
        batch.tick()
        batch.data(PIVOT)
        batch.expect(TARGET, AIR if expected['target'] == AIR else target)
    rows = batch.run(session, tool + '-after-cold-restart')
    assert len(rows) == 2 * (len(reference) - SAVE_AT), rows
    for expected, controller, target_state in zip(reference[SAVE_AT:], rows[::2], rows[1::2], strict=True):
        assert matched(target_state) and abs(number({'nbt': controller}, 'Angle') - expected['angle']) < .001, (
            tool, expected, controller, target_state)
    assert current_cut(session) is None
    return dict(saved_progress=saved['Progress']['value'], cooldown=saved['TicksUntilNextProgress']['value'],
                post_restart_ticks=len(reference) - SAVE_AT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('game', 'resources', 'ctl', 'reference'):
        parser.add_argument('--' + flag, type=Path, required=True)
    args = parser.parse_args()
    reference = json.loads(args.reference.read_text())
    assert reference['create'] == PINS['create_revision']
    result = {}
    for tool, rows in reference['cases'].items():
        session = NativeCheckSession(args.game, args.resources, args.ctl, None, graphics=False,
                                     name='moving-cut-restart-' + tool, world='CreateMovingCutRestart')
        try:
            report = verify(session, tool, rows)
            path = session.scratch / 'result.json'
            path.write_text(json.dumps(report, indent=2) + '\n')
            result[tool] = str(path)
        finally:
            session.control_temp.cleanup()
    print(json.dumps(result))


if __name__ == '__main__':
    main()
