#!/usr/bin/env python3
"""Validate all HBT shards. Usage: check_hbt_output.py <output_root> <snapshot>."""
import argparse
from pathlib import Path

import h5py
import numpy as np


def validate(root, snap):
    nested = root / f"{snap:03d}"
    folder = nested if nested.is_dir() else root
    files = sorted(folder.glob(f"SubSnap_{snap:03d}*.hdf5"))
    if not files:
        raise FileNotFoundError(f"no SubSnap files for snapshot {snap} in {folder}")
    ids, expected_total, expected_files = [], None, None
    for path in files:
        with h5py.File(path) as h:
            sub = h["Subhalos"]
            if "TrackId" not in (sub.dtype.names or ()):
                raise ValueError(f"{path}: missing TrackId compound field")
            nfiles = int(np.asarray(h["NumberOfFiles"]).reshape(-1)[0])
            total = int(np.asarray(h["NumberOfSubhalosInAllFiles"]).reshape(-1)[0])
            if expected_files is not None and (nfiles, total) != (expected_files, expected_total):
                raise ValueError(f"{path}: inconsistent shard totals")
            expected_files, expected_total = nfiles, total
            if "SnapshotId" in h and int(np.asarray(h["SnapshotId"]).reshape(-1)[0]) != snap:
                raise ValueError(f"{path}: incorrect snapshot ID")
            ids.extend(sub["TrackId"].tolist())
    if len(files) != expected_files:
        raise FileNotFoundError(f"expected {expected_files} shards, found {len(files)}")
    if expected_files > 1:
        expected = {f"SubSnap_{snap:03d}.{i}.hdf5" for i in range(expected_files)}
        if {p.name for p in files} != expected:
            raise ValueError("shard indices are not consecutive")
    if len(ids) != expected_total or len(set(ids)) != len(ids) or any(i < 0 for i in ids):
        raise ValueError("incorrect total, duplicate or negative TrackId")
    return len(files), len(ids)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("snapshot", type=int)
    args = parser.parse_args()
    try:
        nfiles, nsubs = validate(args.root, args.snapshot)
    except FileNotFoundError as exc:
        print(f"[INCOMPLETE] {exc}")
        return 2
    except (OSError, KeyError, ValueError) as exc:
        print(f"[FAIL] {exc}")
        return 1
    print(f"[PASS] snapshot={args.snapshot}, files={nfiles}, subhalos={nsubs}, unique TrackId")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
