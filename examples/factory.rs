use create_horizon_core::kinetics::{Axis, Kind, Node, solve};
use create_horizon_core::pressing::{Action, PressCycle};

fn main() {
    let nodes = [
        Node {
            pos: [0, 2, 0],
            axis: Axis::X,
            kind: Kind::Motor {
                facing: [1, 0, 0],
                rpm: 32.0,
                capacity: 16384.0,
            },
        },
        Node {
            pos: [1, 2, 0],
            axis: Axis::X,
            kind: Kind::Shaft,
        },
        Node {
            pos: [2, 2, 0],
            axis: Axis::X,
            kind: Kind::Cog { large: false },
        },
        Node {
            pos: [2, 2, 1],
            axis: Axis::X,
            kind: Kind::Cog { large: false },
        },
        Node {
            pos: [3, 2, 1],
            axis: Axis::X,
            kind: Kind::Press,
        },
    ];
    let network = solve(nodes[0], |p| nodes.iter().copied().find(|n| n.pos == p));
    let rpm = network.speed([3, 2, 1]);
    println!(
        "network={:?} press_rpm={rpm} capacity={} stress={}",
        network.status, network.capacity, network.stress
    );
    let mut press = PressCycle::default();
    let mut output = 0;
    for tick in 0..100 {
        match press.tick(rpm, output == 0) {
            Action::Press => {
                output += 1;
                println!("tick={tick}: iron_ingot -> iron_sheet");
            }
            Action::Finished => break,
            _ => {}
        }
    }
    assert_eq!(output, 1);
}
