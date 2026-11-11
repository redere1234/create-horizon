use create_horizon_core::{
    fan::{self, Processing, ProcessingType},
    placement::Direction,
};
use std::io::{self, BufRead};

fn kind(index: i32) -> Option<ProcessingType> {
    match index {
        0 => Some(ProcessingType::Blasting),
        1 => Some(ProcessingType::Haunting),
        2 => Some(ProcessingType::Smoking),
        3 => Some(ProcessingType::Splashing),
        _ => None,
    }
}

fn kind_index(kind: Option<ProcessingType>) -> i32 {
    match kind {
        None => -1,
        Some(ProcessingType::Blasting) => 0,
        Some(ProcessingType::Haunting) => 1,
        Some(ProcessingType::Smoking) => 2,
        Some(ProcessingType::Splashing) => 3,
    }
}

fn main() {
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        let values: Vec<_> = line.split_whitespace().collect();
        match values[0] {
            "M" => println!("{}", fan::max_distance(values[1].parse().unwrap())),
            "V" => println!("{}", fan::propeller_speed(values[1].parse().unwrap())),
            "P" => {
                let direction = [
                    Direction::Down,
                    Direction::Up,
                    Direction::North,
                    Direction::South,
                    Direction::West,
                    Direction::East,
                ][values[2].parse::<usize>().unwrap()];
                println!(
                    "{}",
                    u8::from(fan::pushing(values[1].parse().unwrap(), direction))
                );
            }
            "D" | "T" => {
                let mut processing = Processing {
                    kind: kind(values[1].parse().unwrap()),
                    time: values[2].parse().unwrap(),
                };
                let mut result = String::new();
                for phase in &values[3..] {
                    let phase: Vec<_> = phase.split(',').collect();
                    let kind = kind(phase[0].parse().unwrap()).unwrap();
                    let count = phase[1].parse().unwrap();
                    let can_process = phase[2] == "1";
                    for _ in 0..phase[3].parse::<usize>().unwrap() {
                        let converted = if values[0] == "D" {
                            processing.dropped(kind, count, can_process)
                        } else {
                            processing.transported(kind, count, can_process)
                        };
                        result.push_str(&format!(
                            "{}:{}:{} ",
                            kind_index(processing.kind),
                            processing.time,
                            u8::from(converted)
                        ));
                    }
                }
                println!("{result}");
            }
            _ => panic!("unknown fan probe"),
        }
    }
}
