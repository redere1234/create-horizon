// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

// MountedItemStorage and MountedStorageMenus: moving storage owns its slots
// even while viewed by multiple players and while actors transfer items.

use super::{
    Game, create_port_contraption as contraption, create_port_contraption_storage as storage,
    lan::LanHost,
};
use crate::{
    first_person::{Hand, SwingAnimation},
    items::Items,
    lan::{
        guest::Guest,
        menu::{self, NativeStore, Rules, Slots, View},
    },
    text::Text,
};
use create_engine::kinetics::Pos;
use glam::DVec3;
use horizon_client_render::create_contraption_scene::{Record, read};
use horizon_core::geometry::{Aabb, Vec3};
use horizon_protocol::packets::play::{Clientbound, ContainerClick, SwingAnimation as SwingPacket};
use horizon_world::chunk::BlockState;
use std::{cell::RefCell, collections::BTreeMap, path::PathBuf, sync::Arc};

const CHANNEL: &str = "create:mounted_menu";
const MENU_RANGE: f64 = 8.0;

#[derive(Clone, Copy)]
struct Target {
    controller: Pos,
    local: Pos,
}

impl Target {
    fn packet(self) -> [u8; 24] {
        let mut packet = [0; 24];
        for (word, value) in packet
            .chunks_exact_mut(4)
            .zip(self.controller.into_iter().chain(self.local))
        {
            word.copy_from_slice(&value.to_be_bytes());
        }
        packet
    }

    fn decode(packet: &[u8]) -> Option<Self> {
        let packet: &[u8; 24] = packet.try_into().ok()?;
        let word = |i: usize| i32::from_be_bytes(packet[i * 4..i * 4 + 4].try_into().unwrap());
        Some(Self {
            controller: [word(0), word(1), word(2)],
            local: [word(3), word(4), word(5)],
        })
    }

    fn locate(self, game: &Game<'_>) -> Option<Located> {
        let [x, z] = contraption::column(self.controller);
        let records = read(game.world.chunks.get(&(x, z))?).ok()?;
        for record in records
            .iter()
            .filter(|record| record.controller == self.controller)
        {
            let Some((_, state)) = record.blocks.iter().find(|(local, _)| *local == self.local)
            else {
                continue;
            };
            if !storage::mounted_state(state) {
                continue;
            }
            let at = DVec3::from_array(record.origin_at(1.0))
                + DVec3::splat(0.5)
                + record.orientation(record.angle) * DVec3::from_array(self.local.map(f64::from));
            return Some(Located {
                at,
                chest: storage::chest_state(state),
                geometry: Arc::clone(&record.blocks),
            });
        }
        None
    }
}

struct Located {
    at: DVec3,
    chest: bool,
    geometry: Arc<[(Pos, BlockState)]>,
}

#[derive(Clone)]
struct Viewer {
    world: PathBuf,
    dimension: String,
    window: i32,
    target: Target,
    geometry: Arc<[(Pos, BlockState)]>,
    last_at: DVec3,
    chest: bool,
}

impl Viewer {
    fn locate(&self, game: &Game<'_>, guest: &Guest) -> Option<Located> {
        if !has_window(guest, self.window) || guest.dimension != self.dimension {
            return None;
        }
        let found = self.target.locate(game)?;
        (Arc::ptr_eq(&found.geometry, &self.geometry) && in_range(guest, &found)).then_some(found)
    }
}

struct Request {
    world: PathBuf,
    dimension: String,
    target: Target,
}

thread_local! {
    static REQUESTS: RefCell<BTreeMap<u128, Request>> = const { RefCell::new(BTreeMap::new()) };
    static VIEWERS: RefCell<BTreeMap<u128, Viewer>> = const { RefCell::new(BTreeMap::new()) };
}

fn in_range(guest: &Guest, found: &Located) -> bool {
    !guest.dead
        && !guest.spectator()
        && DVec3::from_array(guest.position).distance_squared(found.at) < MENU_RANGE * MENU_RANGE
}

fn has_window(guest: &Guest, window: i32) -> bool {
    guest
        .menu
        .as_ref()
        .is_some_and(|menu| menu.window == window && menu.slots == Slots::Native)
}

fn local_ray(record: &Record, eye: DVec3, direction: DVec3) -> ([f64; 3], [f64; 3]) {
    let pivot = DVec3::splat(0.5);
    let inverse = record.orientation(record.angle).conjugate();
    let eye = eye - DVec3::from_array(record.origin_at(1.0)) - pivot;
    (
        (inverse * eye + pivot).to_array(),
        (inverse * direction).to_array(),
    )
}

fn block_hit(
    game: &Game<'_>,
    local: Pos,
    state: &BlockState,
    eye: [f64; 3],
    dir: [f64; 3],
    reach: f64,
) -> Option<f64> {
    let id = game.pack.assets.registry.id(state)?;
    let offset = Vec3::new(
        f64::from(local[0]),
        f64::from(local[1]),
        f64::from(local[2]),
    );
    if let Some([x, y, z, a, b, c]) = game.context_outline([local[0], local[1], local[2]], id) {
        return super::ray_box(
            eye,
            dir,
            reach,
            Aabb::new(Vec3::new(x, y, z), Vec3::new(a, b, c)).move_by(offset),
        );
    }
    game.res
        .facts()
        .get(id)
        .outline
        .iter()
        .filter_map(|[x, y, z, a, b, c]| {
            super::ray_box(
                eye,
                dir,
                reach,
                Aabb::new(Vec3::new(*x, *y, *z), Vec3::new(*a, *b, *c)).move_by(offset),
            )
        })
        .min_by(f64::total_cmp)
}

fn pick(game: &Game<'_>) -> Option<(Target, bool)> {
    let (eye, dir) = game.aim()?;
    let eye = DVec3::from_array(eye);
    let dir = DVec3::from_array(dir);
    let mut reach = game.reach();
    if let Some(hit) = game.pick() {
        reach = reach.min(eye.distance(DVec3::from_array(hit.point)));
    }
    if let Some((distance, _)) = game.pick_entity_hit_at() {
        reach = reach.min(distance);
    }
    let mut target = None;
    for chunk in game.world.chunks.values() {
        let Ok(records) = read(chunk) else { continue };
        for record in records.iter() {
            let (local_eye, local_dir) = local_ray(record, eye, dir);
            for (local, block) in record.blocks.iter() {
                if let Some(hit) = block_hit(game, *local, block, local_eye, local_dir, reach)
                    && hit < reach
                {
                    reach = hit;
                    target = Some((
                        Target {
                            controller: record.controller,
                            local: *local,
                        },
                        storage::mounted_state(block),
                    ));
                }
            }
        }
    }
    target
}

pub(super) fn interaction(
    game: &mut Game<'_>,
    button: i32,
    hand: Hand,
    swing: &mut bool,
    canceled: &mut bool,
) {
    if *canceled
        || button != 1
        || hand != Hand::Main
        || !game.native_on("create")
        || game.spectator()
    {
        return;
    }
    if let Some((target, mounted)) = pick(game) {
        *canceled = true;
        *swing = false;
        if mounted {
            let _ = game.native_net_send_to_server(CHANNEL, &target.packet());
        }
    }
}

pub(super) fn receive(game: &Game<'_>, player: u128, channel: &str, data: &[u8]) {
    if channel != CHANNEL || !game.native_on("create") {
        return;
    }
    let (Some(target), Some(world)) = (Target::decode(data), game.native_world_dir()) else {
        return;
    };
    let Some(guest) = guest(game, player) else {
        return;
    };
    REQUESTS.with_borrow_mut(|pending| {
        pending.insert(
            player,
            Request {
                world,
                dimension: guest.dimension.clone(),
                target,
            },
        );
    });
}

fn guest<'g>(game: &'g Game<'_>, player: u128) -> Option<&'g Guest> {
    game.lan
        .as_ref()?
        .hub
        .guests
        .iter()
        .find(|g| g.placed && g.uuid == player)
}

fn sound(game: &mut Game<'_>, at: DVec3, event: &str) {
    let at = at.floor() + DVec3::splat(0.5);
    game.with_level(|_, level, _| level.native_play_sound(event, at.to_array(), 4, 0.75, 1.0));
}

fn open(game: &mut Game<'_>, player: u128, request: Request) {
    let target = request.target;
    if contraption::materialize_geometry(game, contraption::column(target.controller)).is_err() {
        return;
    }
    let Some(found) = target.locate(game) else {
        return;
    };
    let Some(guest) =
        guest(game, player).filter(|guest| guest.menu.is_none() && in_range(guest, &found))
    else {
        return;
    };
    let (conn, id, at) = (guest.conn, guest.entity_id, guest.position);
    let Some(items) = storage::menu_slots(game, target.controller, target.local) else {
        return;
    };
    let (name, opening) = if found.chest {
        ("block.minecraft.chest", "minecraft:block.chest.open")
    } else {
        ("block.minecraft.barrel", "minecraft:block.barrel.open")
    };
    let title = Text::translate(
        "create.contraptions.moving_container",
        &[Text::translate(name, &[])],
    );
    let Some(window) = game.native_open_menu(player, 3, title, items) else {
        return;
    };
    VIEWERS.with_borrow_mut(|viewers| {
        viewers.insert(
            player,
            Viewer {
                world: request.world,
                dimension: request.dimension,
                window,
                target,
                geometry: found.geometry,
                last_at: found.at,
                chest: found.chest,
            },
        );
    });
    if let Some(host) = game.lan.as_mut() {
        if let Some(guest) = host.hub.guest_mut(conn) {
            // An empty input range lets Horizon return the real cursor when
            // it closes the window. The displayed bank owns no escrow slots.
            guest.native_store = Some(NativeStore::Input(0..0));
        }
        let animation = SwingAnimation::DEFAULT;
        let packet = Clientbound::SwingAnimation(SwingPacket {
            id,
            hand: 0,
            kind: i32::from(animation.kind),
            duration: animation.duration,
        });
        host.hub.send_to(conn, &packet);
        host.hub.broadcast_near(at, 128.0, &packet, Some(conn));
    }
    sound(game, found.at, opening);
}

pub(super) fn tick(game: &mut Game<'_>) {
    let Some(world) = game.native_world_dir() else {
        return;
    };
    let dimension = game.dim.id();
    let pending = REQUESTS.with_borrow_mut(|requests| std::mem::take(requests));
    for (player, request) in pending {
        if request.world == world
            && guest(game, player).is_some_and(|g| g.dimension == request.dimension)
        {
            if request.dimension == dimension {
                open(game, player, request);
            } else {
                REQUESTS.with_borrow_mut(|requests| requests.insert(player, request));
            }
        }
    }
    let viewers = VIEWERS.with_borrow(Clone::clone);
    for (player, viewer) in viewers {
        if viewer.world != world || guest(game, player).is_none() {
            VIEWERS.with_borrow_mut(|viewers| viewers.remove(&player));
            continue;
        }
        if viewer.dimension != dimension {
            continue;
        }
        let Some(guest) = guest(game, player).filter(|g| !g.dead && has_window(g, viewer.window))
        else {
            continue;
        };
        let slots = viewer.locate(game, guest).and_then(|found| {
            VIEWERS.with_borrow_mut(|viewers| viewers.get_mut(&player).unwrap().last_at = found.at);
            storage::menu_slots(game, viewer.target.controller, viewer.target.local)
        });
        match slots {
            Some(slots) if slots != guest.native_menu => game.native_set_menu_items(player, slots),
            Some(_) => {}
            None => game.native_close_menu(player),
        }
    }
}

struct ChestRules<'a>(&'a Items);
impl Rules for ChestRules<'_> {
    fn items(&self) -> &Items {
        self.0
    }
    fn max_stack(&self, item: &str) -> u32 {
        self.0.get(item).map_or(64, |item| item.max_stack.min(64))
    }
    fn armor_index(&self, _: &str) -> Option<usize> {
        None
    }
}

pub(super) fn click_packet(
    game: &mut Game<'_>,
    host: &mut LanHost,
    conn: u32,
    click: &ContainerClick,
) -> bool {
    let window = click.container;
    let Some(index) = host
        .hub
        .guests
        .iter()
        .position(|guest| guest.conn == conn && guest.placed && has_window(guest, window))
    else {
        return false;
    };
    let player = host.hub.guests[index].uuid;
    let Some(viewer) = VIEWERS
        .with_borrow(|viewers| viewers.get(&player).cloned())
        .filter(|viewer| {
            viewer.window == window
                && viewer.dimension == game.dim.id()
                && game.native_world_dir().as_ref() == Some(&viewer.world)
        })
    else {
        return false;
    };
    if host.hub.guests[index].dead {
        return true;
    }
    if viewer.locate(game, &host.hub.guests[index]).is_none() {
        host.hub.close_container(conn);
        return true;
    }
    let Some(mut slots) = storage::menu_slots(game, viewer.target.controller, viewer.target.local)
    else {
        host.hub.close_container(conn);
        return true;
    };
    let slot = i32::from(click.slot);
    if slot != -999 && !(0..(slots.len() + 36) as i32).contains(&slot) {
        host.hub.resend_menu(conn, window, &game.world);
        return true;
    }
    let old_slots = slots.clone();
    let guest = &mut host.hub.guests[index];
    let mut drag = guest.menu.as_mut().and_then(|menu| menu.drag.take());
    let before = (
        guest.inventory.clone(),
        guest.carried.clone(),
        guest.offhand.clone(),
        drag.clone(),
    );
    let rules = ChestRules(world_items!(game));
    let mut view = View {
        guest,
        container: Some(&mut slots),
        shulker: false,
        hidden: &[],
    };
    let (drops, _) = menu::click(
        &mut view,
        &mut drag,
        slot,
        i32::from(click.button),
        click.input,
        &rules,
    );
    // No packet or item drop observes a change until the saved bank commits.
    let saved = slots == old_slots
        || storage::set_menu_slots(
            game,
            viewer.target.controller,
            viewer.target.local,
            slots.clone(),
        )
        .is_ok();
    if saved {
        if let Some(menu) = &mut guest.menu {
            menu.drag = drag;
        }
        host.hub.set_native_menu(conn, slots);
        game.drop_guest_items(host, index, drops);
    } else {
        let (inventory, carried, offhand, drag) = before;
        guest.inventory = inventory;
        guest.carried = carried;
        guest.offhand = offhand;
        if let Some(menu) = &mut guest.menu {
            menu.drag = drag;
        }
    }
    host.hub.resend_menu(conn, window, &game.world);
    true
}

pub(super) fn closed(game: &mut Game<'_>, player: u128, window: i32) {
    let viewer = VIEWERS.with_borrow_mut(|viewers| {
        viewers
            .get(&player)
            .is_some_and(|viewer| viewer.window == window)
            .then(|| viewers.remove(&player))
            .flatten()
    });
    let Some(viewer) = viewer else { return };
    if let Some(host) = game.lan.as_mut()
        && let Some(guest) = host
            .hub
            .guests
            .iter_mut()
            .find(|guest| guest.uuid == player && guest.dead && guest.carried.is_none())
        && let Some(returned) = host
            .hub
            .native_menu_returns
            .iter_mut()
            .find(|returned| returned.conn == guest.conn && returned.window == window)
    {
        // Leave a dead player's cursor to Horizon's normal death drop, which
        // happens after it has closed their menu.
        guest.carried = returned.cursor.take();
    }
    if !viewer.chest
        || viewer.dimension != game.dim.id()
        || game.native_world_dir().as_ref() != Some(&viewer.world)
    {
        return;
    }
    let at = viewer
        .target
        .locate(game)
        .filter(|found| Arc::ptr_eq(&found.geometry, &viewer.geometry))
        .map_or(viewer.last_at, |found| found.at);
    sound(game, at, "minecraft:block.chest.close");
}
