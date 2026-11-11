use create_horizon_core::{kinetics::Axis, visual, waterwheel};
use std::io::{self, BufRead};
fn main() {
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        let p: Vec<_> = line.split_whitespace().collect();
        let f = |i: usize| p[i].parse::<f32>().unwrap();
        let result = match p[0] {
            "A" => visual::angle(f(1) as f64, f(2), f(3)) / 180.0 * std::f32::consts::PI,
            "O" => visual::rotation_offset(
                [f(2) as i32, f(3) as i32, f(4) as i32],
                [Axis::X, Axis::Y, Axis::Z][f(1) as usize],
                p[5] == "1",
            ),
            "S" => visual::speed_dial(f(1)),
            "W" => waterwheel::rpm(f(1) as i32, p[2] == "2"),
            "C" => {
                let mut c = visual::CrankMotion::default();
                for t in 0..200 {
                    c.tick(if t < 50 {
                        f(1)
                    } else if t < 100 {
                        -f(1)
                    } else {
                        0.0
                    });
                }
                c.rendered(f(2))
            }
            _ => panic!("unknown visual probe"),
        };
        println!("{result}");
    }
}
