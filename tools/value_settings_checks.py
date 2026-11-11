"""Real motor hold/release interaction checks against the source value board.

Coordinates use the upstream ValueSettingsBoard layout already compared to the
original client. These checks additionally exercise actual native input, screen
lifetime, server commit and downstream kinetics; they are not pixel comparisons.
"""
import json
import re


def motor_board_coordinate(layout, row, speed):
    left, top = layout['origin']
    label = layout['size'][0] - 318
    horizontal = left + ((max(1, speed) - 1) // 32) * 4 + speed + 1.5 + label + 18
    horizontal += 2 if speed % 32 == 0 else 0
    horizontal += 4 if speed > 0 else 0
    return horizontal, top + (row + .5) * 11 - .5


def run(call, graphics, log, scratch, pos):
    if not graphics:
        raise AssertionError('Value settings checks require a rendered client')
    x, y, z = pos

    def value():
        text = ' '.join(call('command', f'data get block {x} {y} {z}')['chat'])
        match = re.search(r'\bScrollValue:\s*(-?\d+)', text)
        assert match, text
        return int(match[1])

    def aim():
        call('look-at', 'block', x, y, z, 'south')
        call('wait', 3)

    def board():
        aim()
        call('mouse', 'right', 'down')
        call('wait', 9)
        assert call('screen')['screen'] == 'mod', call('screen')
        rows = [json.loads(line.split('Create motor board: ', 1)[1])
                for line in log.read_text().splitlines() if 'Create motor board: ' in line]
        assert rows, 'Source motor board was not rendered'
        last = rows[-1]
        assert last['size'][1] == 22, last
        return last

    def choose(row, speed):
        before = value()
        layout = board()
        point = motor_board_coordinate(layout, row, speed)
        # Left-click must not commit a board opened with the right use binding.
        call('click-at', *point)
        call('wait', 2)
        assert call('screen')['screen'] == 'mod'
        assert value() == before
        call('screenshot', scratch / f'motor-value-row-{row}-{speed}.png')
        # The control command 'mouse' is world-only. A native GUI right click
        # supplies the release event; the source board ignores its press.
        call('click-at', *point, 'right')
        call('release')
        call('wait', 8)
        assert call('screen')['screen'] == 'playing', call('screen')
        expected = max(1, speed) * (-1 if row == 0 else 1)
        assert value() == expected, (expected, value())
        return expected

    call('command', 'clear @s')
    initial = value()
    aim()
    call('mouse', 'right', 'click')
    call('wait', 8)
    assert call('screen')['screen'] == 'playing', 'Short interaction opened a board'
    assert value() == initial
    # The removed provisional wheel shortcut must never change motor RPM.
    call('scroll-at', 100, 100, 1)
    call('wait', 5)
    assert value() == initial
    choose(1, 128)
    choose(0, 64)
    layout = board()
    call('click-at', *motor_board_coordinate(layout, 1, 256))
    call('key', 'escape', 'tap')
    call('release')
    call('wait', 8)
    assert call('screen')['screen'] == 'playing'
    assert value() == -64, 'Escape committed the hovered value'
    # Original raw zero displays/clamps to one when the server applies it.
    choose(1, 0)
    assert value() == 1
    # Survival use may hold an ordinary item; clipboard is the source exception.
    call('command', 'give @s create:cogwheel 1')
    call('wait', 5)
    call('select', 'create:cogwheel')
    choose(1, 256)
    call('release')
    print('Value settings: hold/release, rows, zero, cancellation, held item and no world-wheel shortcut passed', flush=True)
    return {'motor_pos': pos, 'speed': value()}
