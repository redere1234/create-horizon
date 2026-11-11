"""Read-only private-fixture Anvil/NBT inspection using our bounded MIT codec.

The region header contract follows Horizon's MIT horizon-world/src/region.rs;
NBT is decoded by this repository's independently written create-schematics
codec. A private Cargo probe avoids adding any public Horizon path dependency.
Only .local saves are accepted. External/LZ4/unknown compression is refused
explicitly; these current fixture chunks use zlib. Nothing writes a save.
"""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import zlib

from common import ROOT, environment

MAX_RAW = 16 << 20
PROBE = r'''
use create_schematics::{nbt, Limits, Tag};
use serde_json::{json, Value};
fn value(tag: &Tag) -> Value {
    match tag {
        Tag::Byte(v) => json!({"type":"byte","value":v}),
        Tag::Short(v) => json!({"type":"short","value":v}),
        Tag::Int(v) => json!({"type":"int","value":v}),
        Tag::Long(v) => json!({"type":"long","value":v}),
        Tag::Float(v) => json!({"type":"float-bits","value":v}),
        Tag::Double(v) => json!({"type":"double-bits","value":v}),
        Tag::String(v) => json!({"type":"string","value":v}),
        Tag::ByteArray(v) => json!({"type":"byte-array","value":v}),
        Tag::IntArray(v) => json!({"type":"int-array","value":v}),
        Tag::LongArray(v) => json!({"type":"long-array","value":v}),
        Tag::List {element, values} => json!({"type":"list","element":format!("{element:?}"),
            "value":values.iter().map(value).collect::<Vec<_>>()}),
        Tag::Compound(v) => json!({"type":"compound","value":v.iter()
            .map(|(k,v)|(k.clone(),value(v))).collect::<serde_json::Map<_,_>>()}),
    }
}
fn run() -> Result<Value, Box<dyn std::error::Error>> {
    let args:Vec<_> = std::env::args().skip(1).collect();
    if args.len()<3 {return Err("raw-nbt x y z or raw-nbt --tag key [...] required".into());}
    let path=std::path::Path::new(&args[0]);
    if path.metadata()?.len()>16<<20 {return Err("NBT exceeds limit".into());}
    let root=nbt::decode_named(&std::fs::read(path)?,&Limits::default())?;
    if args[1]=="--tag" {
        let mut tag=root.get(&args[2]);
        for key in &args[3..] {
            tag=tag.and_then(Tag::as_compound).and_then(|map| map.get(key));
        }
        return Ok(tag.map_or(Value::Null,value));
    }
    if args.len()!=4 {return Err("raw-nbt x y z required".into());}
    let pos=[args[1].parse::<i32>()?,args[2].parse()?,args[3].parse()?];
    let Some(Tag::List{values,..})=root.get("block_entities") else {
        return Err("chunk has no block_entities list".into());
    };
    let found:Vec<_>=values.iter().filter(|t| t.as_compound().is_some_and(|c|
        ["x","y","z"].into_iter().zip(pos).all(|(key,want)|
            matches!(c.get(key),Some(Tag::Int(actual)) if *actual==want)))).collect();
    if found.len()!=1 {return Err(format!("expected one block entity at {pos:?}, got {}",found.len()).into());}
    Ok(value(found[0]))
}
fn main(){match run(){Ok(v)=>println!("{v}"),Err(e)=>{eprintln!("{e}");std::process::exit(1);}}}
'''


def _probe():
    work = ROOT / '.local/saved-block-reader'
    (work / 'src').mkdir(parents=True, exist_ok=True)
    manifest = ('[package]\nname="create-saved-block-reader"\nversion="0.0.0"\n'
                'edition="2024"\npublish=false\n[workspace]\n[dependencies]\n'
                'serde_json="1"\ncreate-schematics={path=' +
                json.dumps(str(ROOT / 'mixins/create/schematics')) + '}\n')
    codec = ROOT / 'mixins/create/schematics'
    dependency = ''.join(hashlib.sha256((codec / p).read_bytes()).hexdigest()
                         for p in ['Cargo.toml', 'src/lib.rs', 'src/nbt.rs'])
    digest = hashlib.sha256((PROBE + manifest + dependency).encode()).hexdigest()
    binary = work / 'target/debug/create-saved-block-reader'
    stamp = work / 'source.sha256'
    if not binary.is_file() or not stamp.is_file() or stamp.read_text() != digest:
        (work / 'Cargo.toml').write_text(manifest)
        (work / 'src/main.rs').write_text(PROBE)
        log = work / 'build.log'
        env = environment(); env['CARGO_TARGET_DIR'] = str(work / 'target')
        with log.open('w') as stream:
            result = subprocess.run([str(ROOT / '.tools/rust/bin/cargo'), 'build', '--offline',
                '--manifest-path', str(work / 'Cargo.toml')], cwd=ROOT, env=env,
                stdout=stream, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError('Private saved-block probe compile failed: ' + str(log))
        stamp.write_text(digest)
    return binary, work


def _raw_chunk(region, chunk_x, chunk_z):
    """Bounded, read-only Anvil inline gzip/zlib/raw chunk extraction."""
    with region.open('rb') as stream:
        index = (chunk_x % 32) + (chunk_z % 32) * 32
        stream.seek(index * 4)
        location = stream.read(4)
        assert len(location) == 4, 'Truncated region header'
        offset = int.from_bytes(location[:3], 'big') * 4096
        sectors = location[3]
        assert offset >= 8192 and sectors > 0, 'Fixture chunk is absent'
        assert offset + sectors * 4096 <= region.stat().st_size, 'Region allocation is truncated'
        stream.seek(offset)
        header = stream.read(5)
        assert len(header) == 5, 'Truncated chunk header'
        size = struct.unpack('>I', header[:4])[0]
        codec = header[4]
        assert 1 < size <= sectors * 4096 - 4, 'Invalid inline chunk length'
        assert codec in (1, 2, 3), 'Unsupported/external chunk compression: ' + str(codec)
        payload = stream.read(size - 1)
        assert len(payload) == size - 1, 'Truncated compressed chunk'
    if codec == 3:
        raw = payload
    else:
        decoder = zlib.decompressobj(31 if codec == 1 else 15)
        raw = decoder.decompress(payload, MAX_RAW + 1)
        assert decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail, 'Invalid or oversized compressed NBT'
    assert len(raw) <= MAX_RAW, 'Uncompressed NBT exceeds limit'
    return raw, dict(region=str(region), chunk=[chunk_x, chunk_z], codec=codec,
        compressed_sha256=hashlib.sha256(payload).hexdigest(), raw_sha256=hashlib.sha256(raw).hexdigest())


def read_saved_block(scratch, pos, world='CreateParity06'):
    """Return full typed saved BE NBT plus the exact disk chunk fingerprint."""
    return _read_saved_chunk(scratch, pos, world, list(map(str, pos)))


def read_saved_chunk_tag(scratch, pos, keys, world='CreateParity06'):
    """Return an exact typed tag or null from the chunk holding `pos`."""
    return _read_saved_chunk(scratch, pos, world, ['--tag', *keys])


def _read_saved_chunk(scratch, pos, world, probe_args):
    scratch = Path(scratch).resolve()
    scratch.relative_to((ROOT / '.local').resolve())
    if not world or world in ('.', '..') or '/' in world or '\\' in world:
        raise ValueError('A single private fixture world name is required')
    x, _, z = pos
    chunk_x, chunk_z = x // 16, z // 16
    save = scratch / 'saves' / world
    region_dir = save / 'dimensions/minecraft/overworld/region'
    if not region_dir.is_dir():
        region_dir = save / 'region'  # Java 1.21.1 overworld layout.
    region = region_dir / f'r.{chunk_x // 32}.{chunk_z // 32}.mca'
    region.resolve().relative_to(scratch)
    assert not region.is_symlink(), 'Symlinked fixture saves are refused'
    raw, source = _raw_chunk(region, chunk_x, chunk_z)
    binary, work = _probe()
    # Each read owns its own input, so concurrent unrelated fixtures cannot race.
    import tempfile
    with tempfile.NamedTemporaryFile(dir=work, suffix='.nbt') as stream:
        stream.write(raw); stream.flush()
        result = subprocess.run([str(binary), stream.name, *probe_args],
            text=True, capture_output=True, env=environment())
    if result.returncode:
        raise AssertionError(('Saved NBT probe failed', result.stderr, source))
    return dict(nbt=json.loads(result.stdout), source=source)
