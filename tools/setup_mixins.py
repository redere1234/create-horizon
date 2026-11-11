#!/usr/bin/env python3
"""Build the exact published Mixins commit, without modifying its source."""
import io
import tarfile
from urllib.request import urlopen
from common import ROOT, PINS, cargo


def main():
    revision = PINS["horizon_mixins_revision"]
    root = ROOT / ".tools" / ("horizon-mixins-" + revision[:12])
    if not root.exists():
        with urlopen("https://codeload.github.com/horizon-rust/horizon-mixins/tar.gz/" + revision, timeout=60) as response:
            data = response.read()
        root.mkdir(parents=True)
        with tarfile.open(fileobj=io.BytesIO(data)) as package:
            for member in package.getmembers():
                parts = member.name.split("/")[1:]
                if not parts or parts == [""]: continue
                if member.issym() or member.islnk() or ".." in parts:
                    raise SystemExit("Unexpected Mixins archive entry")
                target = root.joinpath(*parts)
                if member.isdir(): target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(package.extractfile(member).read())
        (root / ".revision").write_text(revision)
    if (root / ".revision").read_text().strip() != revision:
        raise SystemExit("Mixins source revision differs from compatibility.json")
    built = ROOT / ".tools/mixins-built-revision"
    if not built.exists() or built.read_text().strip() != revision or not (ROOT / "target/debug/horizon-mixins").exists():
        cargo("build", "--locked", "--manifest-path", root / "Cargo.toml", "-p", "horizon-mixins-cli")
        built.write_text(revision + "\n")


if __name__ == "__main__":
    main()
