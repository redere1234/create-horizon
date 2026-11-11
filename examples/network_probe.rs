use create_horizon_core::kinetics::{Axis, Kind, Node, solve};

fn main() {
    let args: Vec<_> = std::env::args().skip(1).collect();
    let rpm: f32 = args[0].parse().unwrap();
    let capacity: f32 = args[1].parse().unwrap();
    let presses: i32 = args[2].parse().unwrap();
    let mut nodes = vec![Node {
        pos: [0, 0, 0],
        axis: Axis::X,
        kind: Kind::Motor {
            facing: [1, 0, 0],
            rpm,
            capacity,
        },
    }];
    nodes.extend((1..=presses).map(|x| Node {
        pos: [x, 0, 0],
        axis: Axis::X,
        kind: Kind::Press,
    }));
    let network = solve(nodes[0], |p| nodes.iter().copied().find(|n| n.pos == p));
    println!(
        "{{\"capacity\":{},\"stress\":{}}}",
        network.capacity, network.stress
    );
}
