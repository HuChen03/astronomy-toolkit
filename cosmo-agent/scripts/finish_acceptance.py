#!/usr/bin/env python3
"""Chain the stages that follow the long GADGET-4 stage of an acceptance experiment.

The GADGET-4 stage is launched separately (scripts/run_acceptance.sh gadget) and runs for
hours. This watcher polls the experiment stage ledger and then runs HBT+ and the merger-tree
export through the same MCP driver, so the acceptance run finishes without a live session.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TERMINAL_BAD = {'timeout', 'failed'}


def gadget_record(stages):
    """The most recent gadget record; resumed runs append keys like gadget-r1."""
    keys = [k for k in stages if k.startswith('gadget')]
    return stages[keys[-1]] if keys else {}


def classify(stages):
    """Decide what the watcher should do. Returns (action, detail).

    action is 'wait', 'proceed' or 'fail'. A zero exit code is **not** success:
    GADGET-4 stops on TimeLimitCPU, writes restart files and returns 0 having
    produced only part of the requested snapshots. Only the driver's output
    validation verdict may release the next stage.
    """
    gadget = gadget_record(stages)
    if gadget.get('outputs_validated') is False:
        return 'fail', ('gadget exited but its outputs failed validation: '
                        f'{gadget.get("validation_error")}')
    if gadget.get('outputs_validated') is True:
        return 'proceed', 'gadget outputs validated'
    status = gadget.get('status')
    if status == 'finished' and gadget.get('exit_code') != 0:
        return 'fail', f'gadget stage failed with exit code {gadget.get("exit_code")}'
    if status in TERMINAL_BAD:
        return 'fail', f'gadget stage ended as {status}'
    return 'wait', status or 'no gadget record yet'


def driver_alive(stages):
    """False only when the ledger names a driver pid that is definitely gone.

    Uses signal 0 rather than /proc/<pid>: inside containers the pid may be
    namespaced and /proc can be mounted from outside the namespace, which would
    otherwise report a live driver as dead.
    """
    pid = (stages.get('_driver') or {}).get('pid')
    if not pid:
        return True  # ledger written by an older driver; fall back to waiting
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except (TypeError, ValueError, OSError):
        return True  # not ours / cannot tell -> do not claim it died
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('experiment', type=Path)
    parser.add_argument('--poll', type=int, default=300, help='seconds between ledger reads')
    args = parser.parse_args()
    experiment = args.experiment.resolve()
    ledger = experiment / 'mcp-stages.json'

    while True:
        stages = json.loads(ledger.read_text()) if ledger.exists() else {}
        action, detail = classify(stages)
        if action == 'proceed':
            break
        if action == 'fail':
            sys.exit(detail)
        if not driver_alive(stages):
            sys.exit(f'gadget stage is still {detail!r} (pid '
                     f'{(stages.get("_driver") or {}).get("pid")} is gone), so nothing will '
                     f'ever validate it. Inspect {ledger} and the MCP ledger before chaining HBT+.')
        time.sleep(args.poll)

    print('gadget outputs validated; starting HBT+ and tree export', flush=True)
    time.sleep(30)
    for stage in ('hbt', 'tree'):
        subprocess.run(['bash', str(ROOT / 'scripts/run_acceptance.sh'), stage, str(experiment)],
                       check=True)
    print('acceptance chain complete', flush=True)


if __name__ == '__main__':
    main()
