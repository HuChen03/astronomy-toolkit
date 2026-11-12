#!/usr/bin/env python3
"""Render a new, isolated 2LPTIC -> Gadget4 -> HBT experiment; never launch it."""
import argparse
import json
import math
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def read_params(path):
    result = {}
    for line in path.read_text().splitlines():
        line = line.split('%', 1)[0].split('#', 1)[0].strip()
        if line:
            key, value = line.split(maxsplit=1)
            if key in result:
                raise ValueError(f'duplicate parameter: {key}')
            result[key] = value
    return result


def write_params(path, values):
    path.write_text(''.join(f'{key:<36} {value}\n' for key, value in values.items()))


def prepare(spec, destination):
    c, ic, out = spec['cosmology'], spec['initial_conditions'], spec['outputs']
    n, h = spec['particles_per_dimension'], c['h']
    if not isinstance(n, int) or n < 2 or n & (n - 1):
        raise ValueError('particles_per_dimension must be a power of two >= 2')
    if spec['box']['unit'] not in ('comoving_Mpc', 'comoving_Mpc/h'):
        raise ValueError('box unit must be explicit: comoving_Mpc or comoving_Mpc/h')
    box = spec['box']['length'] * (h if spec['box']['unit'] == 'comoving_Mpc' else 1)
    if box <= 0 or h <= 0 or not 0 <= c['omega_b'] < c['omega_m']:
        raise ValueError('invalid box or cosmology')
    if abs(c['omega_m'] + c['omega_lambda'] - 1) > 1e-8:
        raise ValueError('this baseline requires flat cosmology')
    if ic['generator'] != '2LPTIC' or ic['spectrum'] != 'eisenstein_hu':
        raise ValueError('this renderer currently supports 2LPTIC / eisenstein_hu')
    if ic['mesh'] < n or ic['files'] < 1:
        raise ValueError('IC mesh must be >= particle grid; files must be positive')
    if out['spacing'] != 'log_a' or out['include_initial_conditions']:
        raise ValueError('use log_a outputs, excluding the IC file')
    if not ic['redshift'] > out['first_redshift'] > out['final_redshift'] >= 0:
        raise ValueError('require z_IC > z_first > z_final >= 0')
    count = out['count']
    if not isinstance(count, int) or count < 2:
        raise ValueError('need at least two snapshots')
    first, last = 1 / (1 + out['first_redshift']), 1 / (1 + out['final_redshift'])
    times = [math.exp(math.log(first) + i * math.log(last / first) / (count - 1)) for i in range(count)]
    times[0], times[-1] = first, last
    soft = box / n * spec['gravity']['softening_fraction_of_spacing']
    soft_phys = box / n * spec['gravity']['max_physical_softening_fraction']
    destination.mkdir(parents=True, exist_ok=False)
    for sub in ('ic/output', 'gadget/output', 'hbt/output', 'trees'):
        (destination / sub).mkdir(parents=True)
    (destination / 'experiment.yaml').write_text(yaml.safe_dump(spec, sort_keys=False))
    (destination / 'gadget/outputs.txt').write_text(''.join(f'{a:.16g} 1\n' for a in times))

    lpt = read_params(ROOT / 'skills/twolptic/assets/2LPT-small.param')
    lpt.update(Nmesh=ic['mesh'], Nsample=n, GlassTileFac=n, Box=box,
               Omega=c['omega_m'], OmegaLambda=c['omega_lambda'], OmegaBaryon=c['omega_b'],
               HubbleParam=h, Redshift=ic['redshift'], Sigma8=c['sigma8'],
               PrimordialIndex=c['ns'], Seed=ic['seed'], NumFilesWrittenInParallel=ic['files'])
    write_params(destination / 'ic/2LPT.param', lpt)

    gadget = read_params(ROOT / 'skills/gadget4/assets/param-DM-L50-N128.txt')
    for key in ('NSample', 'GridSize', 'Seed', 'SphereMode', 'PowerSpectrumType',
                'ReNormalizeInputSpectrum', 'PrimordialIndex', 'ShapeGamma', 'Sigma8',
                'PowerSpectrumFile', 'InputSpectrum_UnitLength_in_cm'):
        gadget.pop(key, None)
    gadget.update(InitCondFile='../ic/output/ics', OutputDir='./output',
                  TimeBegin=1 / (1 + ic['redshift']), TimeMax=last,
                  Omega0=c['omega_m'], OmegaLambda=c['omega_lambda'], OmegaBaryon=0,
                  HubbleParam=h, BoxSize=box, OutputListOn=1,
                  SofteningComovingClass0=soft, SofteningMaxPhysClass0=soft_phys,
                  TimeLimitCPU=spec['execution']['time_limit_seconds'],
                  MaxSizeTimestep=spec['gravity']['max_step_dln_a'],
                  MaxMemSize=spec['execution']['memory_mb_per_rank'])
    write_params(destination / 'gadget/param.txt', gadget)
    config = ['PERIODIC', 'SELFGRAVITY', 'RANDOMIZE_DOMAINCENTER',
              f"PMGRID={spec['gravity']['pmgrid']}", 'TREEPM_NOTIMESPLIT', 'ASMTH=2.0',
              'NSOFTCLASSES=1', 'NTYPES=2', 'POSITIONS_IN_32BIT', 'DOUBLEPRECISION=2',
              'FOF', f"FOF_LINKLENGTH={spec['gravity']['fof_linking_fraction']}",
              'GADGET2_HEADER', 'IDS_32BIT']
    # External ICs: omit CREATE_GRID/NGENIC. Per-particle masses: omit LEAN.
    (destination / 'gadget/Config.sh').write_text('\n'.join(config) + '\n')
    write_params(destination / 'hbt/param.conf', dict(
        SnapshotPath=destination / 'gadget/output', HaloPath=destination / 'gadget/output',
        SubhaloPath=destination / 'hbt/output', SnapshotFileBase='snapshot',
        MinSnapshotIndex=0, MaxSnapshotIndex=count - 1, BoxSize=box, SofteningHalo=soft,
        SnapshotFormat='gadget4_hdf', GroupFileFormat='gadget4_hdf',
        MassInMsunh='1e10', LengthInMpch=1, VelInKmS=1))
    derived = dict(particle_count=n**3, box_comoving_mpc_h=box,
                   box_comoving_mpc=box / h, scale_factors=times,
                   softening_comoving_mpc_h=soft,
                   max_step_dln_a=spec['gravity']['max_step_dln_a'],
                   status='prepared_not_run',
                   gadget_omega_baryon=0,
                   omega_baryon_note='All matter is represented by type-1 particles; physical baryons enter the IC transfer function. Gadget FoF subtracts OmegaBaryon in its density estimate.')
    (destination / 'derived.json').write_text(json.dumps(derived, indent=2) + '\n')
    return derived


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', type=Path, default=ROOT / 'configs/dm128-200mpc.yaml')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--pilot', action='store_true', help='32^3, 5 outputs, 64-cell FFT/PM; same box and cosmology')
    args = parser.parse_args()
    spec = yaml.safe_load(args.spec.read_text())
    if args.pilot:
        spec['name'] += '-pilot'
        spec['particles_per_dimension'] = 32
        spec['initial_conditions']['mesh'] = 64
        spec['gravity']['pmgrid'] = 64
        spec['outputs']['count'] = 5
        spec['gravity']['max_step_dln_a'] = 0.04
    result = prepare(spec, args.output.resolve())
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
