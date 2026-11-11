use create_horizon_core::{depot, pressing};
use std::io::{self, BufRead};

fn main() {
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        let v: Vec<_> = line.split_whitespace().collect();
        match v[0] {
            "D" => {
                let result = depot::press(v[1].parse().unwrap(), v[2] == "1").unwrap();
                println!(
                    "{} {} {}",
                    result.processed,
                    result.input_left,
                    u8::from(result.output_held)
                );
            }
            "S" => println!("{}", pressing::tick_speed(v[1].parse().unwrap())),
            "H" => println!("{}", pressing::head_offset(v[1].parse().unwrap())),
            _ => panic!("unknown probe"),
        }
    }
}
