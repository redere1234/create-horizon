// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT
// Authored explicit client contexts; pinned Create method bodies are injected privately.
use create_horizon_core::{particles::ParticleRandom, pressing::*};
use std::io::{self, BufRead};
struct Random {
    state: u64,
    level: i32,
    emitted: Vec<(i32, [f64; 3], [f64; 3])>,
}
impl Random {
    fn new(seed: i64) -> Self {
        Self {
            state: (seed as u64 ^ 0x5deece66d) & ((1 << 48) - 1),
            level: 0,
            emitted: Vec::new(),
        }
    }
    fn bits(&mut self, n: u32) -> u32 {
        self.state = (self.state.wrapping_mul(0x5deece66d).wrapping_add(11)) & ((1 << 48) - 1);
        (self.state >> (48 - n)) as u32
    }
}
impl ParticleRandom for Random {
    fn next_float(&mut self) -> f32 {
        self.bits(24) as f32 / 16777216.0
    }
    fn next_int(&mut self, b: i32) -> i32 {
        if b & (b - 1) == 0 {
            return ((i64::from(b) * i64::from(self.bits(31))) >> 31) as i32;
        }
        loop {
            let n = self.bits(31) as i32;
            let v = n % b;
            if n.wrapping_sub(v).wrapping_add(b - 1) >= 0 {
                return v;
            }
        }
    }
}
impl PressParticleContext<i32> for Random {
    fn emit(&mut self, item: &i32, p: [f64; 3], v: [f64; 3]) {
        self.emitted.push((*item, p, v));
        if self.level == 1 {
            self.next_int(3);
        }
    }
}
fn f(n: f32) -> String {
    if n.is_nan() {
        "nan".into()
    } else {
        (n.to_bits() as i32).to_string()
    }
}
fn d(n: f64) -> String {
    if n.is_nan() {
        "nan".into()
    } else {
        (n.to_bits() as i64).to_string()
    }
}
fn main() {
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        let a = line.split_whitespace().collect::<Vec<_>>();
        let mut r = Random::new(a[1].parse().unwrap());
        r.level = a[18].parse().unwrap();
        let rpm = f32::from_bits(a[2].parse().unwrap());
        let mut p = PressClient {
            running: a[3] == "1",
            previous_ticks: a[4].parse().unwrap(),
            ticks: a[5].parse().unwrap(),
            mode: PressMode::from_index(a[6].parse().unwrap()).unwrap(),
            finished: a[7] == "1",
            particle_items: (0..a[12].parse::<i32>().unwrap())
                .map(|i| 70 + i)
                .collect::<Vec<_>>(),
        };
        let n = a[10].parse::<usize>().unwrap();
        let partial = f32::from_bits(a[11].parse().unwrap());
        match a[0] {
            "T" => {
                for _ in 0..n {
                    p.tick(rpm, a[8] == "1", a[9] == "1")
                }
            }
            "S" => p.start(PressMode::from_index(n as i32).unwrap()),
            _ => {
                let state = PressPacket {
                    running: a[13] == "1",
                    finished: a[14] == "1",
                    ticks: a[15].parse().unwrap(),
                    mode: PressMode::from_index(a[16].parse().unwrap()).unwrap(),
                };
                let count = a[17].parse::<i32>().unwrap();
                for _ in 0..n {
                    if a[0] == "R" {
                        p.read_packet(state, (0..count).map(|i| 17 + i), [1, 10, 2], &mut r);
                    } else {
                        p.read(state);
                    }
                }
            }
        }
        print!(
            "{} {} {} {} {} {} {} {} {} {}",
            p.running,
            p.finished,
            p.previous_ticks,
            p.ticks,
            p.mode as i32,
            p.particle_items.len(),
            f(p.rendered_offset(partial)),
            f(p.rendered_travel(partial)),
            r.next_int(1073741824),
            r.emitted.len()
        );
        for (item, p, v) in r.emitted {
            print!(
                " {}:{}:{}:{}:{}:{}:{}",
                item,
                d(p[0]),
                d(p[1]),
                d(p[2]),
                d(v[0]),
                d(v[1]),
                d(v[2])
            );
        }
        println!();
    }
}
