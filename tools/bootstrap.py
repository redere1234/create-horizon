#!/usr/bin/env python3
"""Install Horizon's pinned official Rust components inside this project only."""
import hashlib
import platform
import re
import shutil
import subprocess
import tarfile
from pathlib import Path
from urllib.request import Request, urlopen
from common import ROOT, PINS

# Same hashes as the pinned Horizon launcher/src/rust_toolchain.rs.
PINNED_APPLE = {
    "rustc": "cc998c1dc8df006106472357aa87838b2da3f7b25446b98a94cfd58796cb0610",
    "cargo": "b5cc7634f919949c3e5e131123f813416dc47f6b809a5371d12f1f593595ae13",
    "rust-std": "c124006d63885ba1029aca49efd59e93be6b2b171c379318ff94a00ef5eba664",
}


def download(url, destination):
    temporary = destination.with_suffix(destination.suffix + ".part")
    print("Downloading", destination.name, flush=True)
    with urlopen(Request(url, headers={"User-Agent": "create-horizon-development/0.1"}), timeout=60) as response:
        with temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
    temporary.replace(destination)


def main():
    machine = {"arm64": "aarch64", "x86_64": "x86_64"}.get(platform.machine())
    system = {"Darwin": "apple-darwin", "Linux": "unknown-linux-gnu"}.get(platform.system())
    if not machine or not system:
        raise SystemExit("Use a Rust installation matching compatibility.json on this platform.")
    host = machine + "-" + system
    cache = ROOT / ".tools" / "downloads"
    prefix = ROOT / ".tools" / "rust"
    cache.mkdir(parents=True, exist_ok=True)
    manifest = cache / ("channel-rust-" + PINS["rust_version"] + ".toml")
    base = "https://static.rust-lang.org/dist/" + PINS["rust_date"] + "/"
    if not manifest.exists():
        download(base + manifest.name, manifest)
    text = manifest.read_text()
    for component in ["rustc", "cargo", "rust-std", "rustfmt-preview", "clippy-preview"]:
        section = re.search(r"\[pkg\." + re.escape(component) + r"\.target\." + re.escape(host)
                            + r"\]\n(.*?)(?=\n\[|\Z)", text, re.S)
        if not section:
            raise SystemExit("Missing official component: " + component + " / " + host)
        url = re.search(r'^url = "([^"]+)"', section[1], re.M)[1]
        expected = re.search(r'^hash = "([^"]+)"', section[1], re.M)[1]
        if host == "aarch64-apple-darwin" and component in PINNED_APPLE:
            if expected != PINNED_APPLE[component]:
                raise SystemExit("Rust component differs from Horizon's pinned checksum: " + component)
        archive = cache / url.rsplit("/", 1)[-1]
        if not archive.exists():
            download(url, archive)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != expected:
            raise SystemExit("Checksum mismatch: " + str(archive))
        marker = prefix / (".installed-" + component)
        if marker.exists():
            continue
        unpack = cache / (component + "-unpacked")
        unpack.mkdir(exist_ok=True)
        with tarfile.open(archive) as package:
            for member in package.getmembers():
                name = Path(member.name)
                if name.is_absolute() or ".." in name.parts:
                    raise SystemExit("Unsafe toolchain archive member")
                if member.issym() or member.islnk():
                    target = (unpack / name.parent / member.linkname).resolve()
                    if unpack.resolve() not in target.parents:
                        raise SystemExit("Unsafe toolchain archive link")
            package.extractall(unpack)
        installer = next(unpack.glob("*/install.sh"))
        subprocess.run(["sh", str(installer), "--prefix=" + str(prefix),
                        "--disable-ldconfig"], check=True)
        marker.touch()
        shutil.rmtree(unpack)
    subprocess.run([str(prefix / "bin" / "rustc"), "--version"], check=True)
    # rust-objcopy's macOS rpath points to the host lib folder, while the
    # standalone rustc installer places LLVM in the prefix's common lib.
    llvm = prefix / "lib" / "libLLVM.dylib"
    host_llvm = prefix / "lib" / "rustlib" / host / "lib" / "libLLVM.dylib"
    if llvm.is_file() and not host_llvm.exists():
        host_llvm.parent.mkdir(parents=True, exist_ok=True)
        host_llvm.symlink_to("../../../libLLVM.dylib")
    subprocess.run([str(prefix / "bin" / "cargo"), "--version"], check=True)


if __name__ == "__main__":
    main()
