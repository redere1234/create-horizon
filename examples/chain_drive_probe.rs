use create_horizon_core::{
    chain_drive::{self, Part, State},
    kinetics::Axis,
    placement::Direction,
};
use std::io::{self, BufRead};

fn state(code: usize) -> State {
    State {
        axis: [Axis::X, Axis::Y, Axis::Z][code / 8],
        first: (code % 8) / 4 != 0,
        part: [Part::Start, Part::Middle, Part::End, Part::None][code % 4],
    }
}

fn code(state: State) -> usize {
    state.axis.index() * 8 + usize::from(state.first) * 4 + state.part as usize
}

fn main() {
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        let mut words = line.split_whitespace();
        let op = words.next().unwrap();
        let values: Vec<i32> = words.map(|s| s.parse().unwrap()).collect();
        let number = |i: usize| values[i] as usize;
        let direction = |i| Direction::ALL[number(i)];
        let neighbors = |offset: usize| {
            std::array::from_fn(|i| (values[offset + i] >= 0).then(|| state(number(offset + i))))
        };
        match op {
            "U" => println!(
                "{}",
                code(
                    state(number(0))
                        .update(direction(1), (values[2] >= 0).then(|| state(number(2))))
                )
            ),
            "C" => println!(
                "{}",
                u8::from(state(number(0)).connected(state(number(1)), direction(2)))
            ),
            "M" => {
                let m = state(number(0)).model();
                println!("{} {} {}", m.suffix, m.x_rotation, m.y_rotation);
            }
            "R" => println!("{}", code(state(number(0)).rotated_wrench(direction(1)))),
            "W" => println!(
                "{}",
                code(state(number(0)).wrenched(direction(1), neighbors(2)))
            ),
            "P" => {
                let n = neighbors(3);
                let ports = std::array::from_fn(|i| {
                    n[i].map_or(values[2] & (1 << i) != 0, |s| {
                        s.axis == Direction::ALL[i].axis()
                    })
                });
                println!(
                    "{}",
                    code(chain_drive::placement(
                        direction(0),
                        values[1] != 0,
                        ports,
                        n
                    ))
                );
            }
            _ => panic!("Unknown chain drive probe operation"),
        }
    }
}
