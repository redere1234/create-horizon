use create_horizon_core::milling::{self, Action, MillCycle};
use std::io::{self, BufRead};

fn main() {
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        let v: Vec<_> = line.split_whitespace().collect();
        match v[0] {
            "S" => println!("{}", milling::processing_speed(v[1].parse().unwrap())),
            "T" => {
                let rpm = v[1].parse().unwrap();
                let mut cycle = MillCycle {
                    timer: v[2].parse().unwrap(),
                };
                let mut input: u32 = v[3].parse().unwrap();
                let valid = v[4] == "1";
                let duration = v[5].parse().unwrap();
                let mut output: u32 = v[6].parse().unwrap();
                let ticks: u32 = v[7].parse().unwrap();
                let remove_at: i32 = v[8].parse().unwrap();
                let mut processed = 0;
                for tick in 0..ticks {
                    if tick as i32 == remove_at {
                        input = 0;
                    }
                    if cycle.tick(rpm, [output], input > 0, valid.then_some(duration))
                        == Action::Process
                        && input > 0
                        && valid
                    {
                        input -= 1;
                        output = (output + 1).min(64);
                        processed += 1;
                    }
                }
                println!("{} {input} {output} {processed}", cycle.timer);
            }
            "R" => {
                let seed: u64 = v[1].parse().unwrap();
                let count = v[2].parse().unwrap();
                let chance = v[3].parse().unwrap();
                let mut state = (seed ^ 0x5deece66d) & ((1 << 48) - 1);
                let mut draws = 0;
                let count = milling::roll_count(count, chance, || {
                    state = state.wrapping_mul(0x5deece66d).wrapping_add(11) & ((1 << 48) - 1);
                    draws += 1;
                    (state >> 24) as f32 / (1 << 24) as f32
                });
                println!("{count} {draws}");
            }
            _ => panic!("unknown milling probe"),
        }
    }
}
