#!/usr/bin/env python3
"""Run a prepared experiment through MCP. This is a deterministic integration test,
not a substitute for a natural-language Agent acceptance test.
"""
import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'mcp_server'))
from client_helpers import mcp_session, mcp_call


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('experiment', type=Path)
    parser.add_argument('--stage', choices=['ic', 'gadget', 'gadget-resume', 'checkpoint', 'hbt', 'tree', 'all'], default='all')
    parser.add_argument('--gadget-binary', type=Path, default=ROOT / 'sources/Gadget4/build-cosmo-pilot/Gadget4')
    parser.add_argument('--timeout', type=int, default=1800)
    parser.add_argument('--max-resumes', type=int, default=8,
                        help='how many times to resume GADGET-4 after a TimeLimitCPU checkpoint')
    parser.add_argument('--transport', choices=['stdio', 'http'], default='http')
    parser.add_argument('--port', type=int, default=8787, help='MCP HTTP port (http transport only)')

    args = parser.parse_args()
    experiment = args.experiment.resolve()
    spec = yaml.safe_load((experiment / 'experiment.yaml').read_text())
    state_file = experiment / 'mcp-stages.json'
    stages = json.loads(state_file.read_text()) if state_file.exists() else {}
    # Let scripts/finish_acceptance.py tell "still running" apart from "driver died
    # without validating the outputs" instead of waiting forever.
    stages['_driver'] = {'pid': os.getpid(),
                         'stage': args.stage,
                         'started_at': time.strftime('%Y-%m-%dT%H:%M:%S%z')}

    def save():
        tmp = state_file.with_suffix('.tmp')
        tmp.write_text(json.dumps(stages, indent=2) + '\n')
        tmp.replace(state_file)

    async with mcp_session(ROOT / 'environments/local.yaml', transport=args.transport,
                           state=ROOT / 'runs', port=args.port) as session:
        if args.stage == 'checkpoint':
            await mcp_call(session, 'file_write', {'path': str(experiment / 'gadget/output/stop'),
                                                  'content': 'checkpoint requested by pipeline test\n'})
            print('Graceful checkpoint requested', flush=True)
            return
        async def checked(argv, cwd=experiment):
            result = await mcp_call(session, 'exec_run', {'argv': list(map(str, argv)), 'cwd': str(cwd), 'timeout': 120}, timeout=150)
            if result['exit_code'] != 0:
                raise RuntimeError(f"{argv}: {result['stdout']}\n{result['stderr']}")
            return result

        async def run(stage, argv, cwd):
            if stage in stages:
                raise RuntimeError(f'{stage} already has a record. Inspect {state_file} and the MCP ledger; use a new experiment for a fresh run.')
            stages[stage] = {'status': 'submitting', 'argv': list(map(str, argv))}
            save()
            result = await mcp_call(session, 'exec_start', {
                'argv': list(map(str, argv)), 'cwd': str(cwd), 'env_extra': {'OMP_NUM_THREADS': str(spec['execution']['omp_threads'])}})
            stages[stage].update(result, status='running')
            save()
            print(f"{stage}: run_id={result['run_id']}", flush=True)
            started = time.monotonic()
            while time.monotonic() - started < args.timeout:
                meta = (await mcp_call(session, 'run_get', {'run_id': result['run_id']}))['meta']
                if meta['exit_code'] is not None:
                    stages[stage].update(status='finished', exit_code=meta['exit_code'])
                    save()
                    if meta['exit_code'] != 0:
                        raise RuntimeError(f'{stage} failed: {meta}; see recorded logs')
                    print(f'{stage}: exited 0', flush=True)
                    return result
                await asyncio.sleep(5)
            await mcp_call(session, 'exec_stop', {'run_id': result['run_id']})
            stages[stage]['status'] = 'timeout'
            save()
            raise TimeoutError(f'{stage} exceeded test deadline and was stopped')

        async def validates(stage, label, argv):
            """Run an output check and record the verdict in the stage ledger.

            A process can exit 0 without having produced the requested outputs
            (e.g. GADGET-4 stops on TimeLimitCPU and writes restart files). The
            watcher chains the next stage, so it must key off this verdict and
            not off the exit code.
            """
            try:
                result = await checked(argv)
            except RuntimeError as exc:
                stages[stage]['outputs_validated'] = False
                stages[stage]['validation_error'] = f'{label}: {exc}'[:2000]
                save()
                raise
            stages[stage]['outputs_validated'] = True
            save()
            return result

        evidence = []
        for pattern, folder in [('GADGET2_HEADER', 'sources/Gadget4/documentation'),
                                ('OutputListFilename', 'sources/Gadget4/documentation'),
                                ('SnapshotIndexOfSink|SinkTrackId', 'sources/HBTplus-g4/src/subhalo.h')]:
            result = await checked(['rg', '-n', pattern, folder], ROOT)
            evidence.append(f'## rg -n {pattern} {folder}\n\n```text\n{result["stdout"]}\n```\n')
        await mcp_call(session, 'file_write', {'path': str(experiment / 'documentation-evidence.md'), 'content': '\n'.join(evidence)})
        mpi = ['mpirun', '--allow-run-as-root']
        if args.stage in ('ic', 'all'):
            await checked([sys.executable, ROOT / 'skills/twolptic/scripts/make_grid_glass.py', experiment / 'ic/glass.dat', '1.0'])
            await run('ic', [*mpi, '-np', str(spec['initial_conditions']['files']), ROOT / 'sources/2lptic/2LPTic', '2LPT.param'], experiment / 'ic')
            result = await validates('ic', '2lptic outputs', [sys.executable, ROOT / 'skills/twolptic/scripts/check_2lptic_output.py', experiment / 'ic/output', 'ics', str(spec['initial_conditions']['files'])])
            print(result['stdout'], flush=True)
        if args.stage in ('gadget', 'gadget-resume', 'all'):
            async def run_simulation(base_stage, resume_first):
                """Run GADGET-4 to TimeMax, resuming after each TimeLimitCPU checkpoint.

                GADGET-4 stops by design once 85% of TimeLimitCPU has elapsed: it writes
                restart files and returns 0. For a box that needs longer than one budget
                that is a checkpoint - neither a failure nor a finished run - so keep
                resuming from the restart files until the log stops saying so.
                """
                stage, resume = base_stage, resume_first
                for attempt in range(args.max_resumes + 1):
                    result = await run(stage, [*mpi, '-np', str(spec['execution']['mpi_ranks']),
                                               args.gadget_binary.resolve(), 'param.txt',
                                               *(['1'] if resume else [])], experiment / 'gadget')
                    probe = await mcp_call(session, 'exec_run', {
                        'argv': ['/bin/grep', '-c', 'reaching time-limit',
                                 result['log_files']['stdout']],
                        'cwd': str(ROOT), 'timeout': 60}, timeout=90)
                    if probe['exit_code'] != 0:
                        return stage, result
                    if attempt == args.max_resumes:
                        raise RuntimeError(
                            f'gadget still stops on TimeLimitCPU after {args.max_resumes} resumes; '
                            'raise execution.time_limit_seconds in the experiment config')
                    print(f'{stage}: hit TimeLimitCPU (checkpoint), resuming from restart files', flush=True)
                    resume = True
                    stage = f'{base_stage}-r{attempt + 1}'

            gadget_stage, result = await run_simulation(
                'gadget-resume' if args.stage == 'gadget-resume' else 'gadget',
                args.stage == 'gadget-resume')
            # Scientific failures can return zero, so inspect both complete log files.
            await validates(gadget_stage, 'gadget outputs', [sys.executable, ROOT / 'scripts/check_pipeline_output.py', experiment,
                           '--stdout', result['log_files']['stdout'], '--stderr', result['log_files']['stderr']])
            print('gadget: outputs validated', flush=True)
        if args.stage in ('hbt', 'all'):
            await checked([sys.executable, ROOT / 'scripts/prepare_hbt_inputs.py', experiment / 'gadget/output', str(spec['outputs']['count'])])
            result = await run('hbt', [*mpi, '-np', str(spec['execution']['hbt_mpi_ranks']), ROOT / 'sources/HBTplus-g4/HBTi8', 'param.conf'], experiment / 'hbt')
            for snap in range(spec['outputs']['count']):
                await checked([sys.executable, ROOT / 'skills/hbtplus/scripts/check_hbt_output.py', experiment / 'hbt/output', str(snap)])
            await validates('hbt', 'hbt outputs', [sys.executable, ROOT / 'scripts/check_pipeline_output.py', experiment,
                           '--stdout', result['log_files']['stdout'], '--stderr', result['log_files']['stderr'], '--hbt'])
            print('hbt: outputs validated', flush=True)
        if args.stage in ('tree', 'all'):
            # Merge tree: same-TrackId continuity across snapshots plus HBT sink events.
            trees = experiment / 'trees'
            trees.mkdir(exist_ok=True)
            result = await checked([sys.executable, ROOT / 'scripts/export_hbt_tree.py',
                                    experiment / 'hbt/output', str(spec['outputs']['count']),
                                    trees / 'merger-tree.hdf5'])
            print(result['stdout'], flush=True)
    print('REQUESTED STAGES PASS', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
