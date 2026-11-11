use create_horizon_core::{
    kinetics::Axis,
    placement::{self, Direction},
};
use std::io::{self, BufRead, Write};

fn main() {
    let mut out = io::BufWriter::new(io::stdout().lock());
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        let v: Vec<usize> = line
            .split_whitespace()
            .map(|s| s.parse().unwrap())
            .collect();
        let ports = std::array::from_fn(|i| v[1] & (1 << i) != 0);
        let look = Direction::ALL[v[2]];
        let face = Direction::ALL[v[3]];
        if v[0] == 1 {
            writeln!(out, "{}", placement::motor(look, v[4] != 0, ports).name()).unwrap();
            continue;
        }
        let axis = if v[0] == 0 {
            placement::shaft(look, face, v[4] != 0, ports)
        } else {
            placement::cog(
                face,
                v[4] != 0,
                ports,
                match v[5] {
                    1 => Some(Axis::X),
                    2 => Some(Axis::Y),
                    3 => Some(Axis::Z),
                    _ => None,
                },
            )
        };
        writeln!(
            out,
            "{}",
            match axis {
                Axis::X => "x",
                Axis::Y => "y",
                Axis::Z => "z",
            }
        )
        .unwrap();
    }
}
