// Copyright (c) The Create Team / The Creators of Create
// Copyright (c) 2026 create-horizon contributors
// SPDX-License-Identifier: MIT

// Transfer glue through the same chunk transaction as the bearing payload.

use super::{
    Game, create_port_contraption as contraption, create_port_piston as piston,
    create_port_super_glue as glue,
};
use create_engine::{
    contraption::{QuarterTurn, glue::Volume},
    kinetics::Pos,
};
use horizon_client_render::create_contraption_scene::{MAX_RECORDS, Record, StrokeKind};
use horizon_world::{
    attachments::{AttachmentCodec, AttachmentError, AttachmentType, Holder},
    nbt::{Compound, Tag},
};
use std::collections::{BTreeMap, HashSet};

type Mounted = BTreeMap<Pos, Vec<Volume>>;
const MOUNTED: AttachmentType<Mounted> = AttachmentType {
    namespace: "create",
    name: "mounted_super_glue",
    default: Mounted::new,
    codec: Some(AttachmentCodec { encode, decode }),
    copy_on_death: false,
    sync: false,
};

fn encode(mounted: &Mounted) -> Result<Compound, AttachmentError> {
    if mounted.len() > MAX_RECORDS {
        return Err(AttachmentError::Encode);
    }
    let entries = mounted
        .iter()
        .map(|(controller, volumes)| {
            Ok(Tag::Compound(Compound::from([
                ("Controller".into(), Tag::IntArray(controller.to_vec())),
                ("Bounds".into(), Tag::Compound(glue::encode(volumes)?)),
            ])))
        })
        .collect::<Result<_, AttachmentError>>()?;
    Ok(Compound::from([
        ("Version".into(), Tag::Int(1)),
        ("Entries".into(), Tag::List(entries)),
    ]))
}

fn decode(saved: &Compound) -> Result<Mounted, AttachmentError> {
    let error = AttachmentError::Decode;
    if !matches!(saved.get(&"Version".into()), Some(Tag::Int(1))) {
        return Err(error);
    }
    let Some(Tag::List(entries)) = saved.get(&"Entries".into()) else {
        return Err(error);
    };
    if entries.len() > MAX_RECORDS {
        return Err(error);
    }
    let mut mounted = Mounted::new();
    for entry in entries {
        let Tag::Compound(entry) = entry else {
            return Err(error);
        };
        let Some(Tag::IntArray(controller)) = entry.get(&"Controller".into()) else {
            return Err(error);
        };
        let &[x, y, z] = controller.as_slice() else {
            return Err(error);
        };
        let Some(Tag::Compound(bounds)) = entry.get(&"Bounds".into()) else {
            return Err(error);
        };
        let bounds = glue::decode(bounds)?;
        if bounds.is_empty()
            || bounds.iter().any(|volume| volume.is_single_block())
            || mounted.insert([x, y, z], bounds).is_some()
        {
            return Err(error);
        }
    }
    Ok(mounted)
}

fn read(game: &Game<'_>, key: [i32; 2]) -> Result<Mounted, AttachmentError> {
    use horizon_world::attachments::create_contraption_attachment::{decoded, encoded};
    let Some(chunk) = game.world.chunks.get(&(key[0], key[1])) else {
        return Err(AttachmentError::MissingHolder);
    };
    let Some(saved) = &chunk.saved else {
        return Ok(Mounted::new());
    };
    if let Some(mounted) = decoded(&saved.attachments, &MOUNTED) {
        return Ok(mounted.clone());
    }
    if let Some(value) = encoded(&saved.attachments, MOUNTED.namespace, MOUNTED.name) {
        return decode(value);
    }
    if saved.attachments.has(&MOUNTED) {
        return Err(AttachmentError::Decode);
    }
    Ok(Mounted::new())
}

pub(super) struct Update {
    static_volumes: Vec<Volume>,
    mounted: Mounted,
}

struct Footprint {
    cargo: HashSet<Pos>,
    drive: HashSet<Pos>,
}

impl Footprint {
    fn at(record: &Record, origin: Pos, turn: QuarterTurn) -> Option<Self> {
        let mut cargo = HashSet::with_capacity(record.blocks.len());
        let mut drive = HashSet::new();
        let piston = record.stroke_kind() == Some(StrokeKind::Piston);
        for (local, block) in record.blocks.iter() {
            let at = turn.place(origin, *local)?;
            // The piston stores its normalized head and rods in the same
            // scene as payload. They can become its stationary base on landing
            // and must never be used to crop or fill a moving glue volume.
            if piston && matches!(block.name.as_str(), piston::HEAD | piston::POLE) {
                drive.insert(at);
            } else {
                cargo.insert(at);
            }
        }
        Some(Self { cargo, drive })
    }

    fn valid(&self, game: &Game<'_>, key: [i32; 2], volume: Volume) -> bool {
        let [min, max] = volume.corners();
        if [min, max]
            .into_iter()
            .any(|p| contraption::column(p) != key || !contraption::resident(game, p))
        {
            return false;
        }
        (min[0]..=max[0]).all(|x| {
            (min[1]..=max[1]).all(|y| {
                (min[2]..=max[2]).all(|z| {
                    let p = [x, y, z];
                    !self.drive.contains(&p)
                        && (self.cargo.contains(&p)
                            || game.res.facts().is_air(contraption::state(game, p)))
                })
            })
        })
    }
}

pub(super) fn capture(
    game: &Game<'_>,
    key: [i32; 2],
    record: &Record,
    origin: Pos,
) -> Result<Option<Update>, AttachmentError> {
    let error = AttachmentError::Encode;
    let mut mounted = read(game, key)?;
    if mounted.contains_key(&record.controller) {
        return Err(error);
    }
    let static_volumes = glue::read(game, key)?;
    if static_volumes.is_empty() {
        return Ok(None);
    }
    let footprint = Footprint::at(record, origin, QuarterTurn::IDENTITY).ok_or(error)?;
    let mut retained = Vec::new();
    let mut moving = Vec::new();
    for &volume in static_volumes.iter() {
        // Create's face lookup never captures an entity with only one cell.
        if volume.is_single_block()
            || !footprint
                .cargo
                .iter()
                .any(|&position| volume.contains(position))
        {
            retained.push(volume);
            continue;
        }
        if !footprint.valid(game, key, volume) {
            return Err(error);
        }
        let local = volume
            .fit_to(footprint.cargo.iter().copied())
            .and_then(|fit| fit.relative_to(origin))
            .ok_or(error)?;
        moving.push(local);
    }
    if moving.is_empty() {
        return Ok(None);
    }
    mounted.insert(record.controller, moving);
    Ok(Some(Update {
        static_volumes: retained,
        mounted,
    }))
}

pub(super) fn landing(
    game: &Game<'_>,
    key: [i32; 2],
    record: &Record,
    origin: Pos,
    turn: QuarterTurn,
) -> Result<Option<Update>, AttachmentError> {
    let error = AttachmentError::Encode;
    let mut mounted = read(game, key)?;
    let Some(volumes) = mounted.remove(&record.controller) else {
        return Ok(None);
    };
    let footprint = Footprint::at(record, origin, turn).ok_or(error)?;
    let mut static_volumes = glue::read(game, key)?.into_owned();
    if static_volumes.len() + volumes.len() > glue::MAX_VOLUMES {
        return Err(error);
    }
    for volume in volumes {
        let landed = volume.place(origin, turn).ok_or(error)?;
        if landed.fit_to(footprint.cargo.iter().copied()) != Some(landed) {
            return Err(AttachmentError::Decode);
        }
        if !footprint.valid(game, key, landed) {
            return Err(error);
        }
        static_volumes.push(landed);
    }
    Ok(Some(Update {
        static_volumes,
        mounted,
    }))
}

/// The common transaction protects static glue from drivers which cannot yet
/// transfer it. Supported drivers remove their verified static data first.
pub(super) fn blocked(
    game: &Game<'_>,
    key: [i32; 2],
    cells: impl IntoIterator<Item = Pos>,
) -> bool {
    let mut cells = cells.into_iter().peekable();
    if cells.peek().is_none() {
        return false;
    }
    match glue::read(game, key) {
        Ok(volumes) => cells.any(|position| {
            volumes
                .iter()
                .any(|volume| !volume.is_single_block() && volume.contains(position))
        }),
        Err(_) => true,
    }
}

pub(super) fn commit(
    game: &mut Game<'_>,
    key: [i32; 2],
    update: Option<Update>,
    apply: impl FnOnce(&mut Game<'_>) -> bool,
) -> bool {
    let Some(update) = update else {
        return apply(game);
    };
    let holder = Holder::Chunk(key);
    let Ok(map) = game.native_attachments(holder) else {
        return false;
    };
    let previous = map.clone();
    let static_ok = if update.static_volumes.is_empty() {
        map.remove(&glue::VOLUMES).is_ok()
    } else {
        map.set(&glue::VOLUMES, update.static_volumes).is_ok()
    };
    let mounted_ok = if update.mounted.is_empty() {
        map.remove(&MOUNTED).is_ok()
    } else {
        map.set(&MOUNTED, update.mounted).is_ok()
    };
    if static_ok && mounted_ok && apply(game) {
        return true;
    }
    if let Ok(map) = game.native_attachments(holder) {
        *map = previous;
    }
    false
}
