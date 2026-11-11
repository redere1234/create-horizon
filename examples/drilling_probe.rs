use create_horizon_core::drilling::{self, Action, DrillCycle};
use std::io::{self, BufRead};

fn main() {
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        let v: Vec<_> = line.split_whitespace().collect();
        match v[0] {
            "S" => println!("{}", drilling::break_speed(v[1].parse().unwrap())),
            "D" => println!("{}", drilling::damage(v[1].parse().unwrap())),
            "T" => {
                let rpm: f32 = v[1].parse().unwrap();
                let hardness: f32 = v[2].parse().unwrap();
                let flags: u32 = v[3].parse().unwrap();
                let mut cycle = DrillCycle {
                    progress: v[4].parse().unwrap(),
                    next_tick: v[5].parse().unwrap(),
                };
                let ticks: i32 = v[6].parse().unwrap();
                let wake: i32 = v[7].parse().unwrap();
                let stop: i32 = v[8].parse().unwrap();
                let resume: i32 = v[9].parse().unwrap();
                let mut lazy = 10;
                let (mut broken, mut hits) = (0, 0);
                for tick in 0..ticks {
                    if tick == 0 || lazy == 0 {
                        cycle.lazy_tick();
                    }
                    if lazy == 0 {
                        lazy = 10;
                    } else {
                        lazy -= 1;
                    }
                    if tick == wake {
                        cycle.wake();
                    }
                    let speed = if tick >= stop && tick < resume {
                        0.0
                    } else {
                        rpm
                    };
                    match cycle.tick(speed, hardness, flags == 0 && hardness != -1.0) {
                        Action::Break => {
                            broken += 1;
                            hits += 1;
                        }
                        Action::Hit => hits += 1,
                        _ => {}
                    }
                }
                println!("{} {} {broken} {hits}", cycle.progress, cycle.next_tick);
            }
            _ => panic!("unknown drilling probe"),
        }
    }
}
