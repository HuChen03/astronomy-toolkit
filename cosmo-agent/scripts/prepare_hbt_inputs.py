#!/usr/bin/env python3
"""Expose single-file Gadget FoF snapshots under the paths required by HBT-G4.

Only symlinks are made; particle order and all numerical data are preserved.
"""
import argparse
from pathlib import Path
import h5py
import numpy as np


def prepare(output, count):
    for snap in range(count):
        snapshot = output / f'snapshot_{snap:03d}.hdf5'
        catalogue = output / f'fof_tab_{snap:03d}.hdf5'
        with h5py.File(snapshot) as s, h5py.File(catalogue) as f:
            sh, fh = s['Header'].attrs, f['Header'].attrs
            if int(sh['NumFilesPerSnapshot']) != 1 or int(fh['NumFiles']) != 1:
                raise ValueError('this adapter handles single-file snapshots/catalogues only')
            if not np.isclose(sh['Time'], fh['Time'], rtol=1e-12, atol=0):
                raise ValueError(f'snapshot {snap}: FoF/snapshot times differ')
            groups = int(fh['Ngroups_Total'])
            if groups:
                lengths = f['Group/GroupLen'][()]
                if len(lengths) != groups or int(lengths.sum()) != int(fh['Nids_Total']):
                    raise ValueError(f'snapshot {snap}: invalid FoF lengths')
            elif int(fh['Nids_Total']) != 0:
                raise ValueError(f'snapshot {snap}: particles without groups')
        pairs = [(output / f'snapdir_{snap:03d}/snapshot_{snap:03d}.0.hdf5', snapshot),
                 (output / f'groups_{snap:03d}/fof_subhalo_tab_{snap:03d}.0.hdf5', catalogue)]
        for link, target in pairs:
            link.parent.mkdir(exist_ok=True)
            if link.exists() or link.is_symlink():
                if not link.is_symlink() or link.resolve() != target.resolve():
                    raise FileExistsError(f'refusing to replace {link}')
            else:
                link.symlink_to(Path('..') / target.name)
    print(f'[PASS] HBT input layout: {count} snapshots, original data preserved')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('count', type=int)
    args = parser.parse_args()
    prepare(args.output.resolve(), args.count)
