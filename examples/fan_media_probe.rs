use create_horizon_core::{
    burner::Heat,
    fan::{Medium, ProcessingType},
};
use std::io::{self, BufRead};
fn main() {
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        let v: Vec<i32> = line
            .split_whitespace()
            .map(|v| v.parse().unwrap())
            .collect();
        let medium = Medium {
            fluid: std::array::from_fn(|i| v[0] & (1 << i) != 0),
            block: std::array::from_fn(|i| v[1] & (1 << i) != 0),
            campfire: v[2] != 0,
            lit: match v[3] {
                0 => Some(false),
                1 => Some(true),
                _ => None,
            },
            flame_soul: match v[4] {
                0 => Some(false),
                1 => Some(true),
                _ => None,
            },
            heat: match v[5] {
                0 => Some(Heat::None),
                1 => Some(Heat::Smouldering),
                2 => Some(Heat::Fading),
                3 => Some(Heat::Kindled),
                4 => Some(Heat::Seething),
                _ => None,
            },
        };
        let kinds = [
            ProcessingType::Blasting,
            ProcessingType::Haunting,
            ProcessingType::Smoking,
            ProcessingType::Splashing,
        ];
        let mask = kinds
            .into_iter()
            .enumerate()
            .fold(0, |out, (i, k)| out | (i32::from(medium.accepts(k)) << i));
        println!("{} {}", mask, medium.processing().map_or(-1, |k| k as i32));
    }
}
