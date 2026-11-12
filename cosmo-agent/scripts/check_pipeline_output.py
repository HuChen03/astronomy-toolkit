#!/usr/bin/env python3
"""Validate the prepared single-file DM pipeline against its explicit specification."""
import argparse
import json
import re
from pathlib import Path

import h5py
import numpy as np


def check_logs(paths):
    errors = re.compile(r'HDF5-DIAG|MPI_ABORT|I miss a value|Code termination|Fatal|\bERROR\b|Assertion .*failed', re.I)
    for path in paths:
        if path is None:
            continue
        with path.open(errors='replace') as stream:
            for line in stream:
                if errors.search(line):
                    raise ValueError(f'{path}: {line.strip()}')
                if 'FOF: Comoving linking length:' in line and float(line.split(':')[-1]) <= 0:
                    raise ValueError('non-positive FoF linking length')


def validate(experiment):
    d = json.loads((experiment / 'derived.json').read_text())
    out = experiment / 'gadget/output'
    files = sorted(out.glob('snapshot_*.hdf5'))
    expected = d['scale_factors']
    if [p.name for p in files] != [f'snapshot_{i:03d}.hdf5' for i in range(len(expected))]:
        raise ValueError(f'expected exactly {len(expected)} consecutive single-file snapshots, found {len(files)}')
    reference_ids = None
    rows = []
    for index, path in enumerate(files):
        with h5py.File(path) as h:
            header = h['Header'].attrs
            counts = np.asarray(header['NumPart_ThisFile'])
            if int(counts[1]) != d['particle_count'] or int(counts.sum()) != d['particle_count']:
                raise ValueError(f'{path}: not the required pure-DM particle count')
            if not np.array_equal(counts, header['NumPart_Total']) or int(header['NumFilesPerSnapshot']) != 1:
                raise ValueError(f'{path}: wrong totals or shard count')
            if not np.isclose(header['BoxSize'], d['box_comoving_mpc_h'], rtol=1e-12):
                raise ValueError(f'{path}: wrong box size')
            a = float(header['Time'])
            # Output occurs at the next available integration tick; allow at most the configured timestep.
            if not expected[index] * (1 - 1e-10) <= a <= expected[index] * np.exp(d.get('max_step_dln_a', 0.005) * 1.01):
                raise ValueError(f'{path}: time {a} does not match scheduled {expected[index]}')
            part = h['PartType1']
            ids = np.sort(part['ParticleIDs'][()])
            if len(ids) != d['particle_count'] or (np.diff(ids) == 0).any():
                raise ValueError(f'{path}: duplicate or missing particle IDs')
            if reference_ids is not None and not np.array_equal(ids, reference_ids):
                raise ValueError(f'{path}: particle IDs changed')
            reference_ids = ids
            for key in ('Coordinates', 'Velocities'):
                values = part[key][()]
                if values.shape != (d['particle_count'], 3) or not np.isfinite(values).all():
                    raise ValueError(f'{path}: invalid {key}')
            mass = float(header['MassTable'][1])
            if mass <= 0 and ('Masses' not in part or not (part['Masses'][()] > 0).all()):
                raise ValueError(f'{path}: invalid masses')
        with h5py.File(out / f'fof_tab_{index:03d}.hdf5') as h:
            header = h['Header'].attrs
            groups = int(header['Ngroups_Total'])
            if not np.isclose(header['Time'], a, rtol=1e-12) or int(header['Ngroups_ThisFile']) != groups:
                raise ValueError(f'FoF {index}: inconsistent time or group count')
            if groups:
                lengths = h['Group/GroupLen'][()]
                if len(lengths) != groups or int(lengths.sum()) != int(header['Nids_Total']):
                    raise ValueError(f'FoF {index}: group lengths mismatch')
        rows.append({'snapshot': index, 'a': a, 'groups': groups})
    if not rows[-1]['groups']:
        raise ValueError('final FoF catalogue is empty; investigate before accepting the baseline')
    (experiment / 'snapshot-validation.json').write_text(json.dumps(rows, indent=2) + '\n')
    print(f'[PASS] {len(rows)} DM snapshots and FoF catalogues; final groups={rows[-1]["groups"]}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('experiment', type=Path)
    parser.add_argument('--stdout', type=Path)
    parser.add_argument('--stderr', type=Path)
    parser.add_argument('--hbt', action='store_true', help='check HBT logs only; shard checks are separate')
    args = parser.parse_args()
    check_logs([args.stdout, args.stderr])
    if not args.hbt:
        validate(args.experiment)
    else:
        print('[PASS] HBT logs contain no recognised errors')
