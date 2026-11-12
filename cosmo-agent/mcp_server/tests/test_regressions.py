"""Small regression tests for observed pipeline/executor failures."""
import asyncio
import contextlib
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import h5py
import httpx
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'mcp_server'))
from client_helpers import mcp_call
from cosmo_exec.config import Config
from cosmo_exec.ledger import Ledger
from cosmo_exec.processes import ProcessManager

INITIALIZE = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                         "clientInfo": {"name": "regression-probe", "version": "0"}}}


def module(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class RegressionTests(unittest.TestCase):
    def test_background_exit_survives_new_manager(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = Config(root, [root])
            old = ProcessManager(config, Ledger(root))
            run = old.start_background(argv=[sys.executable, '-c', "import time;time.sleep(.2);print('persisted');raise SystemExit(7)"])
            recovered = ProcessManager(config, Ledger(root))
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                record = recovered._refresh(run['run_id'])
                if record['exit_code'] is not None:
                    break
                time.sleep(.05)
            self.assertEqual(record['exit_code'], 7)
            self.assertIn('persisted', recovered.read_output(run['run_id'])['stdout'])
            old._live[run['run_id']].wait(timeout=5)

    def test_merger_graph_detects_cycle(self):
        exporter = module('exporter', 'scripts/export_hbt_tree.py')
        nodes = np.zeros(2, dtype=exporter.NODE_DTYPE)
        nodes['NodeId'] = [0, 1]
        nodes['TrackId'] = [10, 11]
        nodes['SinkTrackId'] = [11, 10]
        nodes['Active'] = True
        edges = np.array([(0, 1, 1), (1, 0, 1)], dtype=exporter.EDGE_DTYPE)
        with self.assertRaisesRegex(ValueError, 'cycle'):
            exporter.validate_graph(nodes, edges)

    def test_timeout_stops_descendants_and_keeps_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = ProcessManager(Config(root, [root]), Ledger(root))
            # A descendant would write a marker after its parent timed out.
            code = "import time;from pathlib import Path;time.sleep(2);Path('leaked').touch()"
            command = [sys.executable, '-c', f"import subprocess,time;subprocess.Popen({[sys.executable, '-c', code]!r});print('before timeout',flush=True);time.sleep(10)"]
            result = manager.run_foreground(argv=command, cwd=tmp, timeout=1)
            self.assertTrue(result['timed_out'])
            self.assertIn('before timeout', result['stdout'])
            time.sleep(1.3)
            self.assertFalse((root / 'leaked').exists())

    def test_missing_executable_is_terminal_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = Ledger(root)
            manager = ProcessManager(Config(root, [root]), ledger)
            result = manager.run_foreground(argv=[str(root / 'missing')])
            self.assertEqual(result['exit_code'], 127)
            self.assertIsNotNone(ledger.read_meta(result['run_id'])['finished_at'])

    def test_mutating_timeout_is_not_retried(self):
        class Session:
            calls = 0

            async def call_tool(self, *args, **kwargs):
                self.calls += 1
                raise TimeoutError('lost response')

        session = Session()
        with self.assertRaises(TimeoutError):
            asyncio.run(mcp_call(session, 'exec_start', {}, tries=3))
        self.assertEqual(session.calls, 1)

    def test_hbt_compound_ids_and_missing_shard(self):
        checker = module('hbt_checker', 'skills/hbtplus/scripts/check_hbt_output.py')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / '004'
            folder.mkdir()
            for i in range(2):
                with h5py.File(folder / f'SubSnap_004.{i}.hdf5', 'w') as h:
                    h['Subhalos'] = np.array([(i,)], dtype=[('TrackId', '<i8')])
                    h['NumberOfFiles'] = [2]
                    h['NumberOfSubhalosInAllFiles'] = [2]
                    h['SnapshotId'] = [4]
            self.assertEqual(checker.validate(root, 4), (2, 2))
            (folder / 'SubSnap_004.1.hdf5').unlink()
            with self.assertRaises(FileNotFoundError):
                checker.validate(root, 4)

    def test_spec_units_and_fifty_times(self):
        renderer = module('renderer', 'scripts/prepare_experiment.py')
        spec = yaml.safe_load((ROOT / 'configs/dm128-200mpc.yaml').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / 'experiment'
            result = renderer.prepare(spec, dest)
            self.assertEqual(result['particle_count'], 2097152)
            self.assertAlmostEqual(result['box_comoving_mpc_h'], 135.6)
            self.assertEqual(len(result['scale_factors']), 50)
            self.assertEqual(result['scale_factors'][-1], 1)
            self.assertTrue(np.all(np.diff(result['scale_factors']) > 0))
            config = (dest / 'gadget/Config.sh').read_text().splitlines()
            self.assertIn('GADGET2_HEADER', config)
            self.assertNotIn('CREATE_GRID', config)
            self.assertNotIn('LEAN', config)
            with self.assertRaises(FileExistsError):
                renderer.prepare(spec, dest)

    def test_exec_output_pages_streams_independently(self):
        """stdout offset must never silently skip an equal-length stderr prefix."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = ProcessManager(Config(root, [root]), Ledger(root))
            run = manager.start_background(
                command="for i in 1 2 3 4 5 6 7 8; do echo out$i; echo err$i >&2; done",
                shell=True)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and manager._refresh(run['run_id'])['exit_code'] is None:
                time.sleep(0.2)
            first = manager.read_output(run['run_id'], offset=0, max_bytes=16)
            self.assertIn('out1', first['stdout'])
            self.assertIn('err1', first['stderr'])
            later = manager.read_output(run['run_id'], offset=first['stdout_info']['next_offset'])
            # stderr restarts from 0 when stderr_offset is omitted, so nothing is lost.
            self.assertIn('err1', later['stderr'])
            self.assertEqual(later['stderr_info']['offset'], 0)
            explicit = manager.read_output(run['run_id'], offset=0, stderr_offset=100)
            self.assertNotIn('err1', explicit['stderr'])

    def test_env_info_exposes_slurm_mock_backend(self):
        """env_info must surface the manifest's mock Slurm backend."""
        from cosmo_exec.config import load_config
        from cosmo_exec.server import build_server

        config = load_config(manifest_path=str(ROOT / 'environments/local.yaml'))
        tools = getattr(getattr(build_server(config), '_tool_manager', None), '_tools', None)
        if not tools or 'env_info' not in tools:
            self.skipTest('FastMCP tool registry not reachable')
        info = tools['env_info'].fn()
        self.assertEqual(info['slurm_mock_backend'], config.manifest['slurm']['mock_backend'])
        self.assertTrue(info['slurm_mock_available'])


    def test_watcher_does_not_chain_on_bare_zero_exit(self):
        """GADGET-4 returns 0 when it stops on TimeLimitCPU; that is not success."""
        watcher = module('finish_acceptance', 'scripts/finish_acceptance.py')
        self.assertEqual(watcher.classify({'gadget': {'status': 'finished', 'exit_code': 0}}),
                         ('wait', 'finished'))
        self.assertEqual(watcher.classify({'gadget': {'status': 'finished', 'exit_code': 0,
                                                      'outputs_validated': False,
                                                      'validation_error': 'found 29'}})[0], 'fail')
        self.assertEqual(watcher.classify({'gadget': {'outputs_validated': True}}),
                         ('proceed', 'gadget outputs validated'))
        self.assertEqual(watcher.classify({'gadget': {'status': 'timeout'}})[0], 'fail')
        self.assertEqual(watcher.classify({'gadget': {'status': 'finished', 'exit_code': 9}})[0], 'fail')
        # a resumed run is tracked under its own stage key
        self.assertEqual(watcher.classify({'gadget-resume': {'outputs_validated': True}})[0], 'proceed')
        # ... and the newest gadget record is the one that decides
        chained = {'gadget': {'status': 'finished', 'exit_code': 0},
                   'gadget-r1': {'status': 'finished', 'exit_code': 0},
                   'gadget-r2': {'outputs_validated': True}}
        self.assertEqual(watcher.classify(chained), ('proceed', 'gadget outputs validated'))
        unfinished = {'gadget': {'status': 'finished', 'exit_code': 0},
                      'gadget-r1': {'status': 'running'}}
        self.assertEqual(watcher.classify(unfinished), ('wait', 'running'))

    def test_watcher_detects_dead_driver(self):
        watcher = module('finish_acceptance', 'scripts/finish_acceptance.py')
        self.assertTrue(watcher.driver_alive({}))
        self.assertTrue(watcher.driver_alive({'_driver': {'pid': os.getpid()}}))
        self.assertFalse(watcher.driver_alive({'_driver': {'pid': 999999999}}))

    # ---- HTTP transport security (proxy/tunnel Host headers) ----

    def test_transport_security_policy_object(self):
        from cosmo_exec.server import build_transport_security

        default = build_transport_security()
        self.assertTrue(default.enable_dns_rebinding_protection)
        self.assertIn('127.0.0.1:*', default.allowed_hosts)

        self.assertFalse(build_transport_security(disable=True).enable_dns_rebinding_protection)

        custom = build_transport_security(['tunnel.example.com', 'other.example:9000'])
        self.assertTrue(custom.enable_dns_rebinding_protection)
        # loopback stays allowed, a bare name accepts any port, host:port stays exact
        self.assertIn('localhost:*', custom.allowed_hosts)
        self.assertIn('tunnel.example.com', custom.allowed_hosts)
        self.assertIn('tunnel.example.com:*', custom.allowed_hosts)
        self.assertIn('other.example:9000', custom.allowed_hosts)
        self.assertNotIn('other.example:9000:*', custom.allowed_hosts)

        self.assertIn('https://tunnel.example.com',
                      build_transport_security(allowed_origins=['https://tunnel.example.com']).allowed_origins)

    def _probe_host(self, port, host, content_type='application/json'):
        """POST an initialize request with an arbitrary Host header."""
        headers = {'Host': host, 'Accept': 'application/json, text/event-stream'}
        if content_type:
            headers['Content-Type'] = content_type
        # content= (not json=) so that content_type=None really sends no header.
        body = json.dumps(INITIALIZE).encode()
        # trust_env=False: a SOCKS/HTTP proxy in the environment must not swallow loopback calls.
        with httpx.Client(trust_env=False, timeout=60) as client:
            return client.post(f'http://127.0.0.1:{port}/mcp', content=body, headers=headers)

    @contextlib.contextmanager
    def _http_server(self, port, extra_args=()):
        try:
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', port))
        except OSError as exc:
            self.skipTest(f'loopback binding unavailable ({exc}); rerun outside the sandbox')
        log = Path(tempfile.mkdtemp()) / 'server.log'
        argv = [sys.executable, '-m', 'cosmo_exec.server',
                '--env', str(ROOT / 'environments/local.yaml'),
                '--state-dir', str(log.parent / 'state'),
                '--allowed-root', str(log.parent),
                '--transport', 'streamable-http', '--port', str(port), *extra_args]
        with log.open('wb') as fh:
            proc = subprocess.Popen(argv, stdout=fh, stderr=fh, start_new_session=True)
        try:
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    self.fail(f'MCP server exited early:\n{log.read_text()[-2000:]}')
                try:
                    with httpx.Client(trust_env=False, timeout=2) as client:
                        client.get(f'http://127.0.0.1:{port}/mcp')
                    break
                except httpx.HTTPError:
                    time.sleep(0.2)
            else:
                self.fail(f'MCP server did not start:\n{log.read_text()[-2000:]}')
            yield proc
        finally:
            proc.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=10)
            if proc.poll() is None:
                proc.kill()

    def test_proxied_host_header_rejected_by_default(self):
        """FastMCP auto-enables DNS-rebinding protection on a loopback bind: a
        proxy/tunnel that forwards the client-facing Host gets 421."""
        with self._http_server(8831) as _:
            self.assertEqual(self._probe_host(8831, 'tunnel.example.com').status_code, 421)
            self.assertEqual(self._probe_host(8831, '127.0.0.1:8831').status_code, 200)

    def test_allowed_host_lets_proxied_request_through(self):
        with self._http_server(8832, ['--allowed-host', 'tunnel.example.com']) as _:
            self.assertEqual(self._probe_host(8832, 'tunnel.example.com:443').status_code, 200)
            self.assertEqual(self._probe_host(8832, '127.0.0.1:8832').status_code, 200)
            # an unlisted host is still rejected
            self.assertEqual(self._probe_host(8832, 'evil.example.com').status_code, 421)

    def test_disabling_rebinding_still_requires_json_content_type(self):
        with self._http_server(8833, ['--no-dns-rebinding-protection']) as _:
            self.assertEqual(self._probe_host(8833, 'tunnel.example.com').status_code, 200)
            self.assertEqual(self._probe_host(8833, 'tunnel.example.com', content_type=None).status_code, 400)


if __name__ == '__main__':
    unittest.main()
