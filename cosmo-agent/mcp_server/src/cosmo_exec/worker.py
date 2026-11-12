"""Detached command supervisor. Persist terminal status even if the MCP server exits.

The supervisor and command share a process group. SIGTERM sent to the group
terminates the command, while the supervisor records its exit status.
"""
import json
import signal
import subprocess
import sys
import time
from pathlib import Path


def main():
    directory = Path(sys.argv[1])
    received = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda signum, frame: received.append(signum))
    payload = json.load(sys.stdin)
    result = {}
    with (directory / 'stdout.log').open('wb') as out, (directory / 'stderr.log').open('wb') as err:
        try:
            if received:
                result['exit_code'] = -received[0]
            else:
                child = subprocess.Popen(payload['argv'], env=payload['env'],
                                         stdin=subprocess.DEVNULL, stdout=out, stderr=err)
                if received:
                    child.send_signal(received[0])
                result['exit_code'] = child.wait()
        except Exception as exc:
            result.update(exit_code=127, spawn_error=str(exc))
            err.write(f'[cosmo-exec] failed to start: {exc}\n'.encode())
    result['finished_at'] = time.time()
    tmp = directory / 'result.json.tmp'
    tmp.write_text(json.dumps(result) + '\n')
    tmp.replace(directory / 'result.json')


if __name__ == '__main__':
    main()
