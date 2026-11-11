use create_horizon_core::burner::{Burner, Candidate, Fuel, Heat};
use std::io::{self, BufRead};

fn fuel(value: usize) -> Fuel {
    [Fuel::None, Fuel::Normal, Fuel::Special][value]
}
fn heat(value: usize) -> Heat {
    [
        Heat::None,
        Heat::Smouldering,
        Heat::Fading,
        Heat::Kindled,
        Heat::Seething,
    ][value]
}
fn main() {
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        let mut words = line.split_whitespace();
        let op = words.next().unwrap();
        let values: Vec<i32> = words.map(|v| v.parse().unwrap()).collect();
        if op == "R" {
            let optional = |value| (value != -1).then_some(value);
            let candidate = Candidate::resolve(
                optional(values[0]),
                optional(values[1]),
                values[2] != 0,
                values[3],
                values[4] != 0,
            );
            println!("{} {}", candidate.fuel as u8, candidate.burn_time);
            continue;
        }
        let mut state = Burner {
            fuel: fuel(values[0] as usize),
            remaining: values[1],
            creative: values[2] != 0,
            heat: heat(values[3] as usize),
        };
        let mut updates = Vec::new();
        let accepted = match op {
            "T" => {
                for _ in 0..values[4] {
                    state.tick(|h| updates.push(h as u8));
                }
                false
            }
            "C" => {
                state.apply_creative(|h| updates.push(h as u8));
                true
            }
            "I" => state.insert(
                Candidate {
                    fuel: fuel(values[4] as usize),
                    burn_time: values[5],
                },
                values[6] != 0,
                values[7] != 0,
                |h| updates.push(h as u8),
            ),
            _ => panic!("unknown operation"),
        };
        print!(
            "{} {} {} {} {} {}",
            u8::from(accepted),
            state.fuel as u8,
            state.remaining,
            u8::from(state.creative),
            state.heat as u8,
            updates.len()
        );
        for update in updates {
            print!(" {update}");
        }
        println!();
    }
}
