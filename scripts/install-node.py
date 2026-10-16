#!/usr/bin/env python3
"""Install an isolated Node 24 binary with its published SHA-256 checksum."""
import hashlib
from pathlib import Path
import platform
import shutil
import sys
import tarfile
import tempfile
import urllib.request


def install(destination):
    system = {"Darwin": "darwin", "Linux": "linux"}[platform.system()]
    arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64", "AMD64": "x64"}[platform.machine()]
    base = "https://nodejs.org/dist/latest-v24.x/"
    with urllib.request.urlopen(base + "SHASUMS256.txt", timeout=60) as response:
        entries = [line.split() for line in response.read().decode().splitlines()]
    checksum, filename = next(row for row in entries if row[1].endswith(f"-{system}-{arch}.tar.gz"))
    destination = destination.expanduser().absolute()
    if destination.exists():
        raise RuntimeError(f"Node destination already exists: {destination}; set LLM_TOOLS_NODE_HOME to a new directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        archive = Path(temporary) / filename
        with urllib.request.urlopen(base + filename, timeout=120) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
        digest = hashlib.sha256()
        with archive.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != checksum:
            raise RuntimeError("Node download checksum mismatch")
        with tarfile.open(archive) as bundle:
            # Official checksum-verified archive; reject traversal and unsafe links
            # explicitly for Python versions without tarfile's data filter.
            root = Path(temporary).resolve()
            for member in bundle.getmembers():
                path = (root / member.name).resolve()
                if root not in path.parents or member.isdev():
                    raise RuntimeError("Unsafe Node archive path")
                if member.issym() or member.islnk():
                    target = (path.parent if member.issym() else root) / member.linkname
                    if root not in target.resolve().parents:
                        raise RuntimeError("Unsafe Node archive link")
            bundle.extractall(root)
        (Path(temporary) / filename[:-7]).rename(destination)
    print(f"Installed Node: {destination / 'bin/node'}")


if __name__ == "__main__":
    install(Path(sys.argv[1]))
