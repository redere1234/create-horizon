// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

fn contraption_menu_click(
    game: &mut crate::game::Game<'_>,
    host: &mut crate::game::lan::LanHost,
    conn: u32,
    packet: &horizon_protocol::packets::play::Serverbound,
) -> std::ops::ControlFlow<()> {
    use horizon_protocol::packets::play::Serverbound;
    use std::ops::ControlFlow;
    if let Serverbound::ContainerClick(click) = packet
        && crate::game::create_port_contraption_menu::click_packet(game, host, conn, click)
    {
        return ControlFlow::Break(());
    }
    ControlFlow::Continue(())
}
