"""Re-hash the corpus against MANIFEST.json.

The manifest is the record's integrity claim. Once deposited it cannot be
corrected, only superseded, so it is checked against the bytes that are about to
be uploaded rather than against the ones that happened to be present when it was
written.

    python3 bench/verify_manifest.py                     # the working tree
    python3 bench/verify_manifest.py corpus-v1.0.0.tar.gz  # what will be uploaded

Exits non-zero on the first disagreement of any kind: a missing file, a wrong
digest, a wrong length, or a file present in the archive that the manifest does
not describe.
"""

import hashlib
import json
import os
import sys
import tarfile

MANIFEST = os.path.join("dataset", "MANIFEST.json")

# The manifest describes the corpus; it cannot describe the files that describe
# the corpus, and MANIFEST.json cannot contain its own digest. These three are
# expected in the archive and carry no entry.
METADATA = {
    "dataset/MANIFEST.json",
    "dataset/gate-decisions.json",
    "dataset/gate-decisions.croissant.json",
}


def entries(manifest):
    for group in manifest["groups"].values():
        for entry in group.get("entries", []):
            yield entry


def from_tree(paths):
    for path in paths:
        try:
            with open(path, "rb") as handle:
                yield path, handle.read()
        except FileNotFoundError:
            yield path, None


def from_archive(archive, paths):
    """Members are prefixed with a directory name; strip it and index by path."""
    with tarfile.open(archive) as tar:
        members = {}
        for member in tar.getmembers():
            if not member.isfile():
                continue
            _, _, relative = member.name.partition("/")
            members[relative] = tar.extractfile(member).read()
    for path in paths:
        yield path, members.pop(path, None)
    for surplus in sorted(members):
        yield surplus, None if surplus in METADATA else b"<not in manifest>"


def main():
    archive = sys.argv[1] if len(sys.argv) > 1 else None
    with open(MANIFEST) as handle:
        manifest = json.load(handle)
    expected = {entry["path"]: entry for entry in entries(manifest)}

    source = from_archive(archive, expected) if archive else from_tree(expected)
    faults = []
    metadata = []
    checked = 0
    total = 0
    for path, data in source:
        entry = expected.get(path)
        if entry is None:
            if path in METADATA:
                metadata.append(path)
            else:
                faults.append(f"{path}: in the archive, not in the manifest")
            continue
        if data is None:
            faults.append(f"{path}: missing")
            continue
        checked += 1
        total += len(data)
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            faults.append(f"{path}: sha256 differs")
        elif len(data) != entry["bytes"]:
            faults.append(f"{path}: {len(data)} bytes, manifest says {entry['bytes']}")

    where = archive if archive else "working tree"
    print(f"{where}: {checked}/{len(expected)} files, {total} bytes")
    if archive:
        absent = sorted(METADATA - set(metadata))
        for path in absent:
            faults.append(f"{path}: metadata file missing from the archive")
    if faults:
        for fault in faults:
            print(f"  FAIL {fault}")
        return 1
    if total != manifest["totals"]["bytes"]:
        print(f"  FAIL totals: {total} bytes, manifest says {manifest['totals']['bytes']}")
        return 1
    print("manifest holds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
