#!/usr/bin/env python3
"""Validate Arepo snapshot files and shards against the configured output count."""
import argparse
import re
from pathlib import Path

import h5py
import numpy as np


def validate(run):
    params = {}
    for line in (run / "param.txt").read_text().splitlines():
        line = line.split("%", 1)[0].split("#", 1)[0].strip()
        if line:
            key, value = line.split(maxsplit=1)
            params[key] = value
    out = run / params.get("OutputDir", "output")
    base = params.get("SnapshotFileBase", "snap")
    groups = {}
    for path in list(out.glob(f"{base}_*.hdf5")) + list(out.glob(f"snapdir_*/{base}_*.hdf5")):
        match = re.fullmatch(re.escape(base) + r"_(\d+)(?:\.(\d+))?\.hdf5", path.name)
        if match:
            groups.setdefault(int(match[1]), []).append(path)
    if not groups:
        raise FileNotFoundError("no HDF5 snapshots")
    expected = None
    if params.get("OutputListOn") == "1":
        rows = []
        for line in (run / params["OutputListFilename"]).read_text().splitlines():
            line = line.split("%", 1)[0].split("#", 1)[0].strip()
            if line:
                row = line.split()
                if len(row) == 1 or int(row[1]) != 0:
                    rows.append(float(row[0]))
        begin, end = float(params.get("TimeBegin", 0)), float(params["TimeMax"])
        expected = [t for t in rows if begin <= t <= end]
        if len(groups) < len(expected):
            raise FileNotFoundError(f"expected {len(expected)} snapshots, found {len(groups)}")
        if sorted(groups) != list(range(len(expected))):
            raise ValueError("unexpected or missing snapshot indices")
    times = []
    for snap, paths in sorted(groups.items()):
        count = np.zeros(6, dtype=np.uint64)
        reference = None
        for path in paths:
            with h5py.File(path) as h:
                hdr = h["Header"].attrs
                total = np.asarray(hdr["NumPart_Total"], dtype=np.uint64)
                total += np.asarray(hdr.get("NumPart_Total_HighWord", np.zeros(6)), dtype=np.uint64) << np.uint64(32)
                current = (float(hdr["Time"]), int(hdr["NumFilesPerSnapshot"]), total.tolist())
                if reference is not None and current != reference:
                    raise ValueError(f"snapshot {snap}: inconsistent shard headers")
                reference = current
                counts = np.asarray(hdr["NumPart_ThisFile"], dtype=np.uint64)
                count += counts
                for kind, size in enumerate(counts):
                    if size:
                        for field in ("Coordinates", "Velocities", "ParticleIDs"):
                            if len(h[f"PartType{kind}/{field}"]) != size:
                                raise ValueError(f"{path}: incorrect {field} length")
        time, nfiles, totals = reference
        if len(paths) != nfiles:
            raise FileNotFoundError(f"snapshot {snap}: expected {nfiles} shards, found {len(paths)}")
        if count.tolist() != totals:
            raise ValueError(f"snapshot {snap}: particle count mismatch")
        times.append(time)
    if not all(np.isfinite(times)) or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("invalid snapshot time ordering")
    energy = out / "energy.txt"
    if not energy.is_file() or not energy.stat().st_size:
        raise ValueError("missing or empty energy.txt")
    return len(groups), times[-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    try:
        count, final = validate(args.run)
    except FileNotFoundError as exc:
        print(f"[INCOMPLETE] {exc}")
        return 2
    except (OSError, KeyError, ValueError) as exc:
        print(f"[FAIL] {exc}")
        return 1
    print(f"[PASS] {count} snapshots, all shards readable; final Time={final}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
