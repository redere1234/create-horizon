use create_horizon_core::kinetics::{Axis, Kind, Node, ratio};
use create_horizon_core::placement::Direction;
use std::io::{self, BufRead};
fn axis(i: i32) -> Axis {
    [Axis::X, Axis::Y, Axis::Z][i as usize]
}
fn node(kind: i32, a: i32, face: i32, power: i32, pos: [i32; 3]) -> Node {
    let kind = match kind {
        0 => Kind::Shaft,
        1 => Kind::Cog { large: false },
        2 => Kind::Cog { large: true },
        3 => Kind::Motor {
            facing: Direction::ALL[face as usize].vector(),
            rpm: 16.0,
            capacity: 16384.0,
        },
        4 => Kind::Press,
        5 => Kind::Gearbox,
        6 => Kind::Gearshift {
            powered: power != 0,
        },
        7 => Kind::Clutch {
            powered: power != 0,
        },
        _ => unreachable!(),
    };
    Node {
        pos,
        axis: axis(a),
        kind,
    }
}
fn main() {
    for line in io::stdin().lock().lines() {
        let v: Vec<i32> = line
            .unwrap()
            .split_whitespace()
            .map(|s| s.parse().unwrap())
            .collect();
        println!(
            "{}",
            ratio(
                node(v[0], v[1], v[2], v[3], [0; 3]),
                node(v[4], v[5], v[6], v[7], [v[8], v[9], v[10]])
            )
            .unwrap_or(0.0)
        );
    }
}
